"""Select the persistent byte range and instrument the N64 mapper's stores."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class _Store:
    unit: str
    procedure: str
    assignment: str
    offset: str
    case: int | None = None


@dataclass(frozen=True)
class SaveSegment:
    offset: int
    size: int
    backing: str


@dataclass(frozen=True)
class SaveProfile:
    size: int = 0
    backing: str = "0"
    restore: str = ""
    reason: str = ""
    _stores: tuple[_Store, ...] = ()
    _extra_segments: tuple[SaveSegment, ...] = ()

    @property
    def segments(self) -> tuple[SaveSegment, ...]:
        if not self.size:
            return ()
        first_size = self._extra_segments[0].offset if self._extra_segments else self.size
        return (SaveSegment(0, first_size, self.backing), *self._extra_segments)


_LINEAR_ASSIGNMENT = "MapRam(addr&8191)=value"
_LINEAR_OFFSET = "addr&8191"
_MMC3_STORE = _Store("mappers", "MapperWrite", _LINEAR_ASSIGNMENT, _LINEAR_OFFSET)
_EXTRA_STORE = {
    mapper: _Store("mapper_extra", "ExtraMapperWrite", _LINEAR_ASSIGNMENT, _LINEAR_OFFSET, mapper)
    for mapper in (6, 9, 34, 68, 105)
}
_NAMCO = "mapper_konami_namco"
_NAMCO_RESTORE = "MapCopy(@N1Sound(0),@N1Ram(0),128)"
_NAMCO_INTERNAL_ASSIGNMENT = "N1Sound(address)=value"
_MMC5_RESTORE = (
    "MapPrgSlots(0)=-1 : MapPrgSlots(1)=-1 : MapPrgSlots(2)=-1\n"
    "M5PrgUpdate()"
)
_MMC5_INDEX = "offset+(addr&8191)"
_SUNSOFT_INDEX = "((ExtraRegs(8)&3)*8192)+(addr&8191)"
_PRG_STORES = {
    1: ("@MapRam(0)", _Store("mmc1", "MapperWrite", _LINEAR_ASSIGNMENT, _LINEAR_OFFSET), ""),
    4: ("@MapRam(0)", _MMC3_STORE, ""),
    5: ("@M5Ram(0)", _Store("mapper5", "M5PrgWrite", f"M5Ram({_MMC5_INDEX})=value", _MMC5_INDEX), _MMC5_RESTORE),
    19: ("@MapRam(0)", _Store(_NAMCO, "N1Write", _LINEAR_ASSIGNMENT, _LINEAR_OFFSET), ""),
    24: ("@MapRam(0)", _Store(_NAMCO, "VrcWrite", _LINEAR_ASSIGNMENT, _LINEAR_OFFSET), ""),
    26: ("@MapRam(0)", _Store(_NAMCO, "VrcWrite", _LINEAR_ASSIGNMENT, _LINEAR_OFFSET), ""),
    69: ("@ExtraRam(0)", _Store("mapper_extra", "ExtraMapperWrite", f"ExtraRam({_SUNSOFT_INDEX})=value", _SUNSOFT_INDEX, 69), ""),
    118: ("@MapRam(0)", _MMC3_STORE, ""),
    119: ("@MapRam(0)", _MMC3_STORE, ""),
    **{mapper: ("@MapRam(0)", store, "") for mapper, store in _EXTRA_STORE.items()},
}


def save_profile(cart, header: bytes) -> SaveProfile:
    """Describe packed NVRAM for an already validated NES image.

    NES 2.0 declares nonvolatile bytes independently of total mapped RAM.
    Supported mixed boards place the retained chip first. iNES supplies a
    battery flag and an inferred total; MMC5's two 8 KiB chips retain only
    the first, while larger ambiguous iNES totals use the core's mapped size.
    A reason with zero bytes identifies requested persistence we cannot back.
    """
    nes2 = header[7] & 12 == 8
    if nes2 and header[11] >> 4:
        return SaveProfile(reason="CHR NVRAM has no supported backing")
    nibble = header[10] >> 4 if nes2 else 0
    if not cart.battery:
        if nibble:
            return SaveProfile(reason="NES 2.0 PRG NVRAM is declared without a battery flag")
        return SaveProfile()

    size = (64 << nibble if nibble else 0) if nes2 else cart.ram_size
    if cart.mapper == 19 and not size:
        if not nes2 and header[8] == 1:
            # The shared legacy reader leaves RAM size unspecified for N163.
            # The board implementation exposes a full 8 KiB external window.
            size = 8192
        else:
            return SaveProfile(
                128, "@N1Ram(0)", _NAMCO_RESTORE,
                _stores=(_Store(_NAMCO, "N1SoundRamWrite", _NAMCO_INTERNAL_ASSIGNMENT, "address"),),
            )
    if not nes2 and cart.mapper in (24, 26) and not size:
        size = 8192
    if not nes2 and cart.mapper == 5 and size == 16384:
        size = 8192

    target = _PRG_STORES.get(cart.mapper)
    if not size or target is None or (cart.mapper == 34 and not cart.chr):
        return SaveProfile(reason=f"mapper {cart.mapper} has no supported NVRAM backing for this header")
    backing, store, restore = target
    if cart.mapper == 19:
        internal = _Store(_NAMCO, "N1SoundRamWrite", _NAMCO_INTERNAL_ASSIGNMENT, f"{size}+address")
        return SaveProfile(
            size + 128, backing, _NAMCO_RESTORE, _stores=(store, internal),
            _extra_segments=(SaveSegment(size, 128, "@N1Ram(0)"),),
        )
    return SaveProfile(size, backing, restore, _stores=(store,))


def stage_save(name: str, code: str, profile: SaveProfile) -> str:
    """Mark writes after the actual backing store, inside the same branch."""
    for store in profile._stores:
        if name == store.unit:
            code = _mark_store(code, store)
    return code


def _mark_store(code: str, store: _Store) -> str:
    proc = re.search(rf"(?m)^Procedure(?:\.\w+)? {store.procedure}\([^\n]*\)\n[\s\S]*?^EndProcedure\b", code)
    if proc is None:
        raise ValueError(f"{store.unit}: save backing procedure {store.procedure} changed")
    proc_body = proc.group()
    scope = (0, len(proc_body))
    if store.case is not None:
        case = re.search(rf"(?m)^    Case {store.case}\n[\s\S]*?(?=^    Case |^  EndSelect\b)", proc_body)
        if case is None:
            raise ValueError(f"{store.unit}: save backing branch for mapper {store.case} changed")
        scope = case.span()
    begin, end = proc.start() + scope[0], proc.start() + scope[1]
    segment = code[begin:end]
    if segment.count(store.assignment) != 1:
        raise ValueError(f"{store.unit}: save backing assignment changed in {store.procedure}")
    marked = store.assignment + f" : NesSaveChanged({store.offset})"
    return code[:begin] + segment.replace(store.assignment, marked) + code[end:]


def save_copy_source(profile: SaveProfile) -> str:
    """Emit copies for each intersection of a save page and a backing segment."""
    if not profile.segments:
        return ""
    lines = [
        "Procedure NesSaveCopy(offset.i,page.i,bytes.i,restore.i)",
        "  Protected first.i, last.i, limit.i, guest.i, buffer.i",
        f"  If offset<0 Or offset>={profile.size} Or bytes<=0 : ProcedureReturn : EndIf",
        f"  If bytes>{profile.size}-offset : bytes={profile.size}-offset : EndIf",
        "  limit=offset+bytes",
    ]
    for segment in profile.segments:
        start = segment.offset
        end = start + segment.size
        lines += [
            f"  If offset<{end} And limit>{start}",
            f"    first=offset : If first<{start} : first={start} : EndIf",
            f"    last=limit : If last>{end} : last={end} : EndIf",
            f"    guest={segment.backing}+first-{start}",
            "    buffer=page+first-offset",
            "    If restore : MapCopy(guest,buffer,last-first)",
            "    Else : MapCopy(buffer,guest,last-first) : EndIf",
            "  EndIf",
        ]
    lines += ["EndProcedure", "", "Procedure NesSaveClear()"]
    lines += [f"  GuestClear({segment.backing},{segment.size})" for segment in profile.segments]
    lines += ["EndProcedure", ""]
    return "\n".join(lines)
