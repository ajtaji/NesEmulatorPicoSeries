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
  PpuN64StoreSpan(NesLineRow+dot,first,second)
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


def stage_sprite_rows(source: str) -> str:
    source = replace_procedure(source, "PpuBuildSpriteCache", "")
    proc = source.index("Procedure PpuSpritesReference()")
    draw = source.index("  PpuClearSprites()\n", proc)
    end = source.index("\nEndProcedure", draw)
    declarations = "j.i, sx.i, pixel.i, flags.i"
    if source[proc:draw].count(declarations) != 1:
        raise ValueError("PPU sprite-row declarations changed")
    head = source[proc:draw].replace(declarations, "j.i, flags.i, clip.i, spanFlags.i")
    # Keep OAM selection and address calculation in the shared evaluator.
    # The native path loads each selected pattern row once for all eight pixels.
    return source[:proc] + head + """  PpuClearSprites()
  If PpuMask&$10
    If (PpuMask&4)=0 : clip=8 : EndIf
    For i=SprCount-1 To 0 Step -1
      flags=16+((SprAttr(i)&3)*4)+((SprAttr(i)&$20)*2) : spanFlags=1
      If SprIndex(i)=0
        flags=flags|$80
        If i=0 : spanFlags=3 : EndIf
      EndIf
      NesDrawSpriteRow(PeekU(Pattern+SprRow(i)),SprX(i),flags,spanFlags,clip,SprAttr(i))
    Next
  EndIf""" + source[end:]


def stage_fastppu(name: str, source: str) -> str:
    if name == "worker":
        copy = """    OamCacheDirty=1
    For i=0 To 255
      Oam((PpuOamAddr+i)&255)=WorkerRead(value*256+i)
    Next"""
        if source.count(copy) != 1:
            raise ValueError("PPU OAM DMA loop changed")
        return source.replace(copy, """    If value<$20 And PpuOamAddr=0
      NesOamRamDma(value)
    Else
      OamCacheDirty=1
      For i=0 To 255
        Oam((PpuOamAddr+i)&255)=WorkerRead(value*256+i)
      Next
    EndIf""")
    if name != "ppu":
        return source
    decode = "  PokeU(Pattern+dest,bits)"
    if source.count(decode) != 1:
        raise ValueError("PPU CHR decode update changed")
    source = source.replace(decode, decode + "\n  CompilerIf #NES_BG_EXPANDED\n"
                            "    NesExpandBg(dest,bits)\n  CompilerEndIf")
    # The indexed framebuffer and RDP palette replace Anvil's RGB row cache.
    # Its old buffers otherwise occupy part of the VR4300 stack on large MMC5 carts.
    source = replace_procedure(source, "PpuBuildRgbPairs", "")
    for declaration in ("Global Dim FrameTop.u(30720)", "Global FrameRow.i, FrameBottom.i",
                        "Global Dim NameDesc.u(4096)", "Global Dim RgbCache.i(4096)",
                        "Global Dim RgbTags.i(1024)", "Global Dim RgbPairs.i(64)"):
        if source.count(declaration) != 1:
            raise ValueError(f"unexpected PPU video storage: {declaration}")
        source = source.replace(declaration + "\n", "")
    # Sprite priority is resolved before that row's indexed pixels go to RDP.
    source = source.replace("LinePixels.a(256)", "LinePixels.a(61440)")
    # The shared lookup is RGB565; VI and the texture palette use RGBA5551.
    source = replace_procedure(source, "PpuRgbLineRaw", "")
    source = source.replace("    color=Rgb64(e+c)\n",
                            "    color=Rgb64(e+c)\n    color=(color&$FFC0)|((color&31)<<1)|1\n")
    source = replace_procedure(source, "PpuBeginLine", """Procedure PpuBeginLine()
  ; DisplayWaitLine handles frame start and the sixteen-line audio cadence.
  If (PpuLine&15)=0 : DisplayWaitLine(PpuLine) : EndIf
  NesLineRow=@LinePixels(0)+PpuLine*256
EndProcedure""")
    source = replace_procedure(source, "PpuClearSprites", CLEAR_SPRITES)
    source = replace_procedure(source, "PpuOverlay8", "")
    source = stage_sprite_rows(source)
    source = replace_procedure(source, "PpuRender8Reference",
                               "CompilerIf #GAME_MAPPER=5 Or #GAME_MAPPER=9\n" + RENDER_SPAN +
                               "\nCompilerElse\n" + native_pixel_spread() + "CompilerEndIf")
    # Finish the visible row and hblank together when the interval spans
    # both. Partial intervals keep the dot 256 and 257 edges distinct.
    visible = """    If PpuLine<240
      startDot=PpuDot : endDot=startDot+dots
      If startDot<256
        If startDot=0
          PpuBeginLine()
          PpuSprites()
        EndIf
        step=endDot
        If step>256 : step=256 : EndIf
        NesRenderTo(step)
        If endDot<256 : Break : EndIf
        If PpuMask&$18 : PpuIncY() : EndIf
        PpuRgbLineRaw()
        If PpuLine=239 : DisplayFrame() : EndIf
      EndIf
      If startDot<257 And endDot>=257 And (PpuMask&$18)<>0
        PpuV=(PpuV&$7BE0)|(PpuT&$41F)
      EndIf
      If endDot<341 : PpuDot=endDot : Break : EndIf
      PpuDot=0 : PpuLine=PpuLine+1 : dots=endDot-341
      Continue
    EndIf
    edge=341
    If PpuLine=241 Or PpuLine=PpuPreLine"""
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
        "Protected dots.i, edge.i, step.i, width.i, sample.i",
        "Protected dots.i, edge.i, step.i, width.i, startDot.i, endDot.i")
