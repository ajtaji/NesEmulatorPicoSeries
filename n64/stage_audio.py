"""Stage single-CPU bus and APU timing paths for the Nintendo 64."""

import re


IMMEDIATE_MIXERS = frozenset((5, 19, 24, 26, 69))


SYNCHRONOUS_BRIDGE = """Procedure.i NesPost(command.i, addr.i, value.i, stamp.i)
  WorkerCommand(command,addr,value,stamp)
  QSent=QSent+1 : QComplete=QSent
  ProcedureReturn QSent
EndProcedure
Procedure.i NesRpc(command.i, addr.i, value.i, stamp.i)
  NesPost(command,addr,value,stamp)
  NesRpcCalls=NesRpcCalls+1
  ProcedureReturn QResult
EndProcedure"""


def replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"N64 audio staging expected a single occurrence of {old!r}")
    return source.replace(old, new)


def triangle_mean_table(source: str) -> str:
    # The TND index is 3*triangle + 2*noise + DMC. Average the nonlinear
    # mixer output rather than feeding it the triangle's mean DAC position.
    table = re.search(r"^TndData:\n(.*?)^RgbData:", source, re.M | re.S)
    if table is None:
        raise ValueError("N64 audio staging expected the shared TND table")
    values = [int(value) for value in re.findall(r"\d+", table[1])]
    if len(values) != 203:
        raise ValueError("N64 audio staging expected 203 TND levels")
    mean = [(sum(values[base + dac * 3] for dac in range(16)) + 8) // 16 for base in range(158)]
    rows = ["NesTndTriMeanData:"]
    for start in range(0, len(mean), 16):
        rows.append("  Data.u " + ",".join(map(str, mean[start:start + 16])))
    return replace(source, "\nRgbData:", "\n" + "\n".join(rows) + "\nRgbData:")


def stage_apu_split(source: str) -> str:
    """The runtime MMC3 cartridge's APU split (design note N.25): the timing in the hot unit, the
    synthesis by block from its log. ApuWrite logs itself at its end, after its effects, instead of
    opening the old sound boundary at its start. The whole old sound path - ApuVolume, ApuTarget,
    ApuQuarter, ApuHalf, ApuDmcFetch, ApuTick, ApuMixSampleBase and ApuAdvance - gives way to
    apusplit.n64 (the stubs into the unit, the log, the synthesis): since N6 nothing calls the rest
    of it (design note N.26a; the ApuMixSample adapter goes with it, in stage_audio below)."""
    begin = source.index("Procedure.i ApuVolume(ch.i)")
    end = source.index("Procedure ApuWrite(addr.i, value.i)", begin)
    if "Procedure ApuAdvance(dt.i)" not in source[begin:end]:
        raise ValueError("N64 audio staging expected ApuAdvance before ApuWrite")
    source = source[:begin] + 'XIncludeFile "../n64/apusplit.n64"\n' + source[end:]
    source = replace(source, "  WorkerIrq=ApuFrameIrq|DmcIrq\nEndProcedure\nProcedure.i ApuReadStatus()",
                     "  NesApuLogWrite(r,value)\n  WorkerIrq=ApuFrameIrq|DmcIrq\nEndProcedure\n"
                     "Procedure.i ApuReadStatus()")
    return "#NES_APU_BLOCKED=0\n" + source


def stage_audio(name: str, source: str, mapper: int, audio_rate: int = 48000, split: bool = False) -> str:
    if name == "lookup_tables":
        return triangle_mean_table(source)
    if split and name == "mapper_adapters":
        # the split's synthesis mixes by block (apusynth.n64): the per-sample adapter has no caller
        adapter = re.search(r"^Procedure ApuMixSample\(\)\n.*?^EndProcedure\n", source, re.M | re.S)
        if not adapter:
            raise ValueError("N64 audio staging expected ApuMixSample")
        return replace(source, adapter[0], "")
    if split and name == "mapper_state":
        return replace(source, "Declare ApuMixSample()\n", "")
    if name == "bridge":
        shared = re.search(r"^Procedure\.i NesPost\(.*?^Procedure\.i NesRpc\(.*?^EndProcedure",
                           source, re.M | re.S)
        if not shared:
            raise ValueError("N64 synchronous bridge expected NesPost and NesRpc")
        return replace(source, shared[0], SYNCHRONOUS_BRIDGE)
    if name == "worker":
        # Preserve command deadlines and mapper/APU/PPU order. The N64 build
        # has no second worker to wait for or per-command timing display.
        source = replace(source, "Procedure PpuSync(stamp.i)\n  Protected dt.i, timer.i",
                         "Procedure PpuSync(stamp.i)\n  Protected dt.i")
        source = replace(source, "    timer=NesHostUs()\n    PpuAdvance(dt)\n"
                         "    WorkerPpuUs=WorkerPpuUs+NesHostUs()-timer\n", "    PpuAdvance(dt)\n")
        source = replace(source, "Procedure WorkerAdvance(stamp.i)\n  Protected dt.i, timer.i",
                         "Procedure WorkerAdvance(stamp.i)\n  Protected dt.i")
        source = replace(source, "    timer=NesHostUs()\n    If ExtraManaged(CartMapper)",
                         "    If ExtraManaged(CartMapper)")
        source = replace(source, "    WorkerApuUs=WorkerApuUs+NesHostUs()-timer\n", "")
        source = replace(source, "      timer=NesHostUs()\n      PpuAdvance(dt)\n"
                         "      WorkerPpuUs=WorkerPpuUs+NesHostUs()-timer\n", "      PpuAdvance(dt)\n")
        return replace(source, "  QResult=0\n  If command=1", "  QResult=0\n  If command=0 : ProcedureReturn : EndIf\n  If command=1")
    if name == "apu":
        if split:
            return stage_apu_split(source)
        if audio_rate == 20000:
            source = replace(source, "ApuOutput=ApuLastY*65400", "ApuOutput=ApuLastY*65210")
            begin = source.index("Procedure.i ApuVolume(ch.i)")
            end = source.index("Procedure ApuDmcFetch()", begin)
            source = source[:begin] + 'XIncludeFile "../n64/apuframe.n64"\n' + source[end:]
        if audio_rate == 20000 or mapper == 4:
            begin = source.index("Procedure ApuDmcFetch()")
            end = source.index("Procedure ApuMixSampleBase()", begin)
            source = source[:begin] + ('XIncludeFile "../n64/apudmc.n64"\n'
                                       'XIncludeFile "../n64/oscillators.n64"\n') + source[end:]
        else:
            # DMC cartridge reads and IRQ effects remain synchronous.
            begin = source.index("Procedure ApuTick(dt.i)")
            dmc = source.index("  While DmcTimer<=0", begin)
            source = source[:begin] + ('XIncludeFile "../n64/oscillators.n64"\n'
                                       'Procedure NesDmcEdge()\n') + source[dmc:]
        blocked = mapper not in IMMEDIATE_MIXERS
        source = f"#NES_APU_BLOCKED={int(blocked)}\n" + source
        if not blocked:
            mix = "  x=PulseMix(pulse)+TndMix(TriDac*3+noise*2+DmcLevel)+ExpSample"
            return replace(source, mix, """  If ApuPeriod(2)<=1 And ApuLength(2)>0 And ApuLinear>0
    target=noise*2+DmcLevel
    x=PeekU(?NesTndTriMeanData+target*2)
  Else
    x=TndMix(TriDac*3+noise*2+DmcLevel)
  EndIf
  x=x+PulseMix(pulse)+ExpSample""")

        # Mixer and event scheduler preserve old oscillator parameters until
        # register/clock boundaries. DMC bus work stays in the shared code.
        source = replace(source, "  r=addr-$4000\n", "  NesAudioBoundary()\n  r=addr-$4000\n")
        scheduler = re.search(r"^Procedure ApuAdvance\(dt\.i\)\n.*?^EndProcedure$", source, re.M | re.S)
        if not scheduler:
            raise ValueError("N64 audio staging expected ApuAdvance")
        source = replace(source, scheduler[0], 'XIncludeFile "../n64/apublock.n64"\n'
                         'XIncludeFile "../n64/apuschedule.n64"')
    return source


def stage_oscillators(source: str, mapper: int) -> str:
    if mapper in IMMEDIATE_MIXERS:
        return source
    source = replace(source, "ProcedureNaked ApuTick(dt.i)", "ProcedureNaked NesOscillatorTick(dt.i)")
    # DMC stays synchronous for cartridge reads, cycle steals, and IRQs.
    return replace(source, "    sd t3, 8(t0)\n    la t0, global_dmctimer", """    jr ra
    sd t3, 8(t0)
  EndASM
EndProcedure

ProcedureNaked ApuTick(dt.i)
  ASM
    la t0, global_nesoscpending
    ld t1, 0(t0)
    addu t1, t1, a0
    sd t1, 0(t0)
    la t0, global_dmctimer""")
