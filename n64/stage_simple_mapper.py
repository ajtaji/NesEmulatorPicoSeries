"""Stage native cartridge writes for boards with fixed bank registers."""

import re


def stage_simple_mapper(name: str, source: str, mapper: int) -> str:
    if mapper not in (0, 2, 3, 7, 11, 66):
        return source
    if name == "mappers" and mapper in (3, 7, 11):
        source, count = re.subn(r"^Procedure MapperWrite\(addr\.i,value\.i,stamp\.i\)\n.*?^EndProcedure",
                                'XIncludeFile "../n64/simple_mapper_write.n64"', source, flags=re.M | re.S)
        if count != 1:
            raise ValueError("simple mapper write source changed")
    if name == "bridge":
        signature = "Procedure NesWrite(addr.i, value.i)\n"
        head, separator, tail = source.partition(signature)
        write, end, suffix = tail.partition("\nEndProcedure")
        write, count = re.subn(r"^  ElseIf addr>=\$6000\n.*?(?=^  ElseIf addr=\$4016\n)",
                               "  ElseIf addr>=$6000\n    NesWriteBoard(addr,value)\n", write, flags=re.M | re.S)
        if not separator or not end or count != 1:
            raise ValueError("simple mapper CPU write branch changed")
        source = head + 'XIncludeFile "../n64/simple_board_bus.n64"\n' + signature + write + end + suffix
        if mapper in (2, 66):
            for procedure in ("CartUxBank", "CartBank"):
                source, count = re.subn(rf"^Procedure {procedure}\(value\.i\)\n.*?^EndProcedure\n",
                                        "", source, flags=re.M | re.S)
                if count != 1:
                    raise ValueError(f"simple mapper {procedure} source changed")
            source = source.replace("Declare CartUxBank(value.i)\n", "")
    return source
