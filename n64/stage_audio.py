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


def stage_audio(name: str, source: str, mapper: int, audio_rate: int = 48000) -> str:
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
        if audio_rate == 20000:
            source = replace(source, "ApuOutput=ApuLastY*65400", "ApuOutput=ApuLastY*65210")
        # The native oscillator path returns before the less frequent DMC edge.
        # Keep DMC fetch, looping and IRQ side effects in the shared implementation.
        begin = source.index("Procedure ApuTick(dt.i)")
        dmc = source.index("  While DmcTimer<=0", begin)
        source = source[:begin] + ('XIncludeFile "../n64/oscillators.n64"\n'
                                   'Procedure NesDmcEdge()\n') + source[dmc:]
        blocked = mapper not in IMMEDIATE_MIXERS
        source = f"#NES_APU_BLOCKED={int(blocked)}\n" + source
        if not blocked:
            return source

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
