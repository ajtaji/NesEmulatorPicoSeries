"""Check the N64 static memory layout."""

import re


RDRAM_CART_RESERVE = 0x80200000


def check_storage_layout(compiler_log: str) -> None:
    """Reject program statics overlapping the first reserved VI framebuffer."""
    match = re.search(r"VR4300: image .*?, variables to \$([0-9A-Fa-f]+);", compiler_log)
    if not match:
        raise ValueError("PureMetal Forge did not report the N64 static memory extent")
    end = int(match[1], 16)
    if end > RDRAM_CART_RESERVE:
        raise ValueError(f"N64 program statics end at ${end:08X}, overlapping the VI framebuffer pool")
