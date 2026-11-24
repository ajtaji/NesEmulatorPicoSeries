"""Stage VR4300 hot paths for the shared PPU, preserving mapper callbacks."""

import re


CLEAR_SPRITES = """ProcedureNaked PpuClearSprites()
  ASM
    la t0, global_spriteline
    la t1, global_spritespan
    daddiu t2, t0, 256
nes_clear_sprite_line:
    sd zero, 0(t0)
    sd zero, 8(t0)
    sd zero, 16(t0)
    sd zero, 24(t0)
    daddiu t0, t0, 32
    bne t0, t2, nes_clear_sprite_line
    nop
    sd zero, 0(t1)
    sd zero, 8(t1)
    sd zero, 16(t1)
    jr ra
    sd zero, 24(t1)
  EndASM
EndProcedure"""


RENDER_SPAN = """Procedure PpuRender8Reference()
  Protected dot.i=PpuDot, mask.i=PpuMask, fine.i=PpuFineX
  Protected first.i=0, second.i=0, nextFirst.i, nextSecond.i, shift.i, v.i=PpuV
  ; Keep both fetch callbacks when fine scroll crosses a tile. MMC5 uses WI.
  If mask&8
    WAddr=v : WI=0
    PpuFetchTile()
    first=WLo : second=WHi
    If fine
      If (v&31)=31 : WAddr=(v&$7FE0)!$400 : Else : WAddr=v+1 : EndIf
      WI=1 : PpuFetchTile()
      nextFirst=WLo : nextSecond=WHi
      If fine>=4
        first=second : second=nextFirst : nextFirst=nextSecond
        fine=fine-4
      EndIf
      If fine
        shift=fine<<3
        first=((first&$FFFFFFFF)>>shift)|(second<<(32-shift))
        second=((second&$FFFFFFFF)>>shift)|(nextFirst<<(32-shift))
      EndIf
    EndIf
  EndIf
  If dot=0 And (mask&2)=0 : first=0 : second=0 : EndIf
  PpuN64StoreSpan(@LinePixels(0)+dot,first,second)
  If SpriteSpan(dot>>3)
    WOff=dot : PpuOverlay8()
  EndIf
  PpuPixels=PpuPixels+8
  If mask&$18
    If (v&31)=31 : PpuV=(v&$7FE0)!$400 : Else : PpuV=v+1 : EndIf
  EndIf
EndProcedure"""


def replace_procedure(source: str, name: str, replacement: str) -> str:
    result, count = re.subn(rf"^Procedure {name}\(.*?^EndProcedure$", lambda _: replacement,
                            source, flags=re.M | re.S)
    if count != 1:
        raise ValueError(f"PPU fast path expected one {name} procedure")
    return result


def native_pixel_spread() -> str:
    # Each decoded byte contains four 2-bit pixels, leftmost in bits 1:0.
    # Put that pixel in the high byte of the word for a big-endian store.
    values = [sum(((value >> (2 * pixel)) & 3) << (24 - 8 * pixel) for pixel in range(4))
              for value in range(256)]
    data = "\n".join("  Data.l " + ",".join(f"${value:08X}" for value in values[i:i+8])
                     for i in range(0, len(values), 8))
    return "\nDataSection\nNesBgPixelSpread:\n" + data + "\nEndDataSection\n"


def stage_fastppu(name: str, source: str) -> str:
    if name != "ppu":
        return source
    # The native row converter is in ppu.n64. The shared lookup table is RGB565.
    source = replace_procedure(source, "PpuRgbLineRaw", "")
    source = source.replace("    color=Rgb64(e+c)\n",
                            "    color=Rgb64(e+c)\n    color=(color&$FFC0)|((color&31)<<1)|1\n")
    source = replace_procedure(source, "PpuBeginLine", """Procedure PpuBeginLine()
  DisplayWaitLine(PpuLine)
  If PpuLine<#NES_VIDEO_HALF_ROWS
    FrameRow=RenderTop+PpuLine*PpuFrameStride
  Else
    FrameRow=FrameBottom+(PpuLine-#NES_VIDEO_HALF_ROWS)*PpuFrameStride
  EndIf
EndProcedure""")
    source = replace_procedure(source, "PpuClearSprites", CLEAR_SPRITES)
    source = replace_procedure(source, "PpuRender8Reference",
                               "CompilerIf #GAME_MAPPER=5 Or #GAME_MAPPER=9\n" + RENDER_SPAN +
                               "\nCompilerElse\n" + native_pixel_spread() + "CompilerEndIf")
    # Visible spans have an eight-dot edge and no regional line-width changes.
    visible = """    If PpuLine<240 And PpuDot<256
      If PpuDot=0
        PpuBeginLine()
        PpuSprites()
      EndIf
      step=256-PpuDot
      If step>dots : step=dots : EndIf
      NesRenderTo(PpuDot+step)
      dots=dots-step
      If PpuDot=256
        If PpuMask&$18 : PpuIncY() : EndIf
        PpuRgbLineRaw()
        PpuSendLine()
      EndIf
      Continue
    EndIf
    edge=341
    If PpuLine<240
      If PpuDot=256 : edge=257 : EndIf
    ElseIf PpuLine=241 Or PpuLine=PpuPreLine"""
    old_start = source.index("    edge=341\n", source.index("Procedure PpuAdvanceReference("))
    old_end = source.index("    ElseIf PpuLine=241 Or PpuLine=PpuPreLine", old_start)
    source = source[:old_start] + visible + source[old_end + len("    ElseIf PpuLine=241 Or PpuLine=PpuPreLine"):]
    visible_end = """      ElseIf PpuLine<240 And edge=256
        If PpuMask&$18
          PpuIncY()
        EndIf
        PpuRgbLineRaw()
        PpuSendLine()
"""
    if source.count(visible_end) != 1:
        raise ValueError("PPU visible line-end site changed")
    return source.replace(visible_end, "").replace(
        "Protected dots.i, edge.i, step.i, width.i, sample.i", "Protected dots.i, edge.i, step.i, width.i")
