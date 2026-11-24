"""Read physical controller snapshots at the NES strobe and live-bit edges."""


def stage_input(source: str) -> str:
    for marker in (
        "  ElseIf addr=$4016\n    NesStrobe=",
        "    If NesStrobe\n      v=(NesController&1)|$40",
        "    If NesStrobe\n      v=v|(NesController2&1)",
    ):
        if source.count(marker) != 1:
            raise ValueError("NES controller bridge hook changed")
        head, tail = marker.split("\n", 1)
        indent = tail[:len(tail) - len(tail.lstrip())]
        source = source.replace(marker, head + "\n" + indent + "CompilerIf #VERIFY_INPUT=0\n"
                                + indent + "  HostHarvestPads()\n" + indent + "CompilerEndIf\n" + tail)
    return source
