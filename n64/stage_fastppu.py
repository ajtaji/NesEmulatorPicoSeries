"""Stage VR4300 hot paths for the shared PPU, preserving mapper callbacks."""

import re


CLEAR_SPRITES = """ProcedureNaked PpuClearSprites()
  ASM
    la t0, global_spriteline
    la t1, global_spritespan
    ; Every populated sprite pixel sets its span flag.
    ld t2, 0(t1)
    ld t3, 8(t1)
    or t2, t2, t3
    ld t3, 16(t1)
    or t2, t2, t3
    ld t3, 24(t1)
    or t2, t2, t3
    beq t2, zero, nes_clear_sprite_done
    nop
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
    sd zero, 24(t1)
nes_clear_sprite_done:
    jr ra
    nop
  EndASM
EndProcedure"""


CLEAR_DIRTY_GROUPS = """ProcedureNaked PpuClearSprites()
  ASM
    la t1, global_spritespan
    ld t2, 0(t1)
    ld t3, 8(t1)
    ld t8, 16(t1)
    ld t9, 24(t1)
    or a0, t2, t3
    or a1, t8, t9
    or a0, a0, a1
    beqz a0, nes_clear_sprite_groups_done
    nop
    la t0, global_spriteline
    beqz t2, nes_clear_sprite_group_0_done
    nop
    sd zero, 0(t0)
    sd zero, 8(t0)
    sd zero, 16(t0)
    sd zero, 24(t0)
    sd zero, 32(t0)
    sd zero, 40(t0)
    sd zero, 48(t0)
    sd zero, 56(t0)
    sd zero, 0(t1)
nes_clear_sprite_group_0_done:
    beqz t3, nes_clear_sprite_group_1_done
    nop
    sd zero, 64(t0)
    sd zero, 72(t0)
    sd zero, 80(t0)
    sd zero, 88(t0)
    sd zero, 96(t0)
    sd zero, 104(t0)
    sd zero, 112(t0)
    sd zero, 120(t0)
    sd zero, 8(t1)
nes_clear_sprite_group_1_done:
    beqz t8, nes_clear_sprite_group_2_done
    nop
    sd zero, 128(t0)
    sd zero, 136(t0)
    sd zero, 144(t0)
    sd zero, 152(t0)
    sd zero, 160(t0)
    sd zero, 168(t0)
    sd zero, 176(t0)
    sd zero, 184(t0)
    sd zero, 16(t1)
nes_clear_sprite_group_2_done:
    beqz t9, nes_clear_sprite_group_3_done
    nop
    sd zero, 192(t0)
    sd zero, 200(t0)
    sd zero, 208(t0)
    sd zero, 216(t0)
    sd zero, 224(t0)
    sd zero, 232(t0)
    sd zero, 240(t0)
    sd zero, 248(t0)
    sd zero, 24(t1)
nes_clear_sprite_group_3_done:
nes_clear_sprite_groups_done:
    jr ra
    nop
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
    result, count = re.subn(rf"^Procedure(?:\.\w+)? {name}\(.*?^EndProcedure$", lambda _: replacement,
                            source, flags=re.M | re.S)
    if count != 1:
        raise ValueError(f"PPU fast path expected one {name} procedure")
    return result


def native_chr_spread() -> str:
    # Reverse each bitplane and spread its bits into the even output bits.
    values = [sum(((value >> (7 - pixel)) & 1) << (2 * pixel) for pixel in range(8))
              for value in range(256)]
    data = "\n".join("  Data.u " + ",".join(f"${value:04X}" for value in values[i:i+16])
                     for i in range(0, len(values), 16))
    return "\nDataSection\nNesChrBitSpread:\n" + data + "\nEndDataSection\n"


def native_pixel_spread(mmc3_palette: bool) -> str:
    # Each decoded byte contains four 2-bit pixels, leftmost in bits 1:0.
    # Put that pixel in the high byte of the word for a big-endian store.
    values = [sum(((value >> (2 * pixel)) & 3) << (24 - 8 * pixel) for pixel in range(4))
              for value in range(256)]
    def words(palette):
        return "\n".join("  Data.l " + ",".join(f"${value | palette:08X}" for value in values[i:i+8])
                         for i in range(0, len(values), 8))
    data = ["", "DataSection", "NesBgPixelSpread:", words(0)]
    if mmc3_palette:
        data.extend(words(palette) for palette in (0x04040404, 0x08080808, 0x0C0C0C0C))
    return "\n".join([*data, "EndDataSection", ""])


def stage_fastppu(name: str, source: str, runtime_mmc3: bool = False) -> str:
    if name in ("mapper_extra_bus", "mapper_adapters"):
        procedure = "ExtraLatchRead" if name == "mapper_extra_bus" else "PpuFetchTile"
        original = re.search(rf"^Procedure {procedure}\(.*?^EndProcedure$", source, re.M | re.S)
        if original is None:
            raise ValueError(f"PPU latch path expected {procedure}")
        source = replace_procedure(source, procedure, "CompilerIf #GAME_MAPPER<>9\n" +
                                   original[0] + "\nCompilerEndIf")
        if name == "mapper_adapters":
            original = re.search(r"^Procedure PpuSpritesRaw\(.*?^EndProcedure$", source, re.M | re.S)
            if original is None:
                raise ValueError("PPU latch path expected PpuSpritesRaw")
            source = replace_procedure(source, "PpuSpritesRaw", """CompilerIf #GAME_MAPPER=9
ProcedureNaked PpuSpritesRaw()
  ASM
    j ppuspritesreference
    nop
  EndASM
EndProcedure
CompilerElse
""" + original[0] + "\nCompilerEndIf")
        return source
    if name == "mapper5_video":
        original = re.search(r"^Procedure M5FetchTile\(.*?^EndProcedure$", source, re.M | re.S)
        if original is None:
            raise ValueError("PPU MMC5 tile path changed")
        source = replace_procedure(source, "M5FetchTile",
                                 'CompilerIf #GAME_MAPPER=5\nXIncludeFile "../n64/mmc5_video.n64"\n'
                                 'CompilerElse\n' + original[0] + '\nCompilerEndIf')
        for procedure in ("M5PpuRead", "M5PpuNotice", "M5PpuTicks"):
            original = re.search(rf"^Procedure {procedure}\(.*?^EndProcedure$", source, re.M | re.S)
            if original is None:
                raise ValueError(f"PPU MMC5 path expected {procedure}")
            source = replace_procedure(source, procedure, "CompilerIf #GAME_MAPPER<>5\n" +
                                       original[0] + "\nCompilerEndIf")
        return source
    if name == "mapper9_video":
        return ('CompilerIf #GAME_MAPPER=9\nXIncludeFile "../n64/mmc2_video.n64"\n'
                'CompilerElse\n' + source + '\nCompilerEndIf\n')
    if runtime_mmc3 and name == "ppu_bus_read":
        return replace_procedure(source, "PpuRead", "Declare.i PpuRead(addr.i)")
    if runtime_mmc3 and name == "ppu_bus_write":
        return replace_procedure(source, "PpuWrite",
                                 'XIncludeFile "../n64/mmc3_ppu_bus.n64"')
    if name == "ppu_bus_write":
        # Write notices and the address increment remain on the caller's path.
        source = source.replace("        PokeA(Chr+addr,value) : PpuDecode(addr)", """        CompilerIf #NES_BG_EXPANDED
          If PeekA(Chr+addr)=value : ProcedureReturn : EndIf
        CompilerEndIf
        PokeA(Chr+addr,value) : PpuDecode(addr)""")
        start_nt = "    ntAddress=PpuNtAddr(addr)\n"
        end_nt = "  Else\n    Pal(PpuPalAddr(addr))"
        if source.count(start_nt) != 1 or source.count(end_nt) != 1:
            raise ValueError("PPU nametable write changed")
        start, end = source.index(start_nt), source.index(end_nt)
        source = (source[:start] + "    CompilerIf #NES_BG_EXPANDED\n"
                  "      NesWriteExpandedNt(addr,value)\n"
                  "    CompilerElse\n" + source[start:end] +
                  "    CompilerEndIf\n" + source[end:])
        mapped = "      MapCiram(ntAddress)=value : offset=addr&1023"
        if source.count(mapped) != 1:
            raise ValueError("PPU CIRAM write changed")
        source = source.replace(mapped, """      CompilerIf #NES_RETAINED_ROWS
        If MapCiram(ntAddress)=value : ProcedureReturn : EndIf
        NesInvalidateTileRow(ntAddress)
      CompilerEndIf
""" + mapped)
        palette = "    Pal(PpuPalAddr(addr))=value&63\n    PpuColours()"
        if source.count(palette) != 1:
            raise ValueError("PPU palette write changed")
        return source.replace(palette, "    NesWritePalette(PpuPalAddr(addr),value&63)")
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
    if runtime_mmc3:
        clock = "  If ExtraA12(CartMapper) : MapperPpuTicks(cycles) : EndIf\n"
        if source.count(clock) != 1:
            raise ValueError("PPU mapper clock changed")
        source = source.replace(clock, "")
        # Keep the shared reference fetchers consistent with the native
        # renderer when they are used for diagnostics.
        views = (
            ("PeekU(Pattern+row)", "PeekU(NesMmc3PatternPointer(row))"),
            ("PeekA(Chr+row)", "PeekA(NesMmc3ChrPointer(row))"),
            ("PeekA(Chr+row+8)", "PeekA(NesMmc3ChrPointer(row+8))"),
            ("PeekU(Pattern+SprRow(i))", "PeekU(NesMmc3PatternPointer(SprRow(i)))"),
        )
        # PpuDecode also reads raw patterns while loading the cartridge. Its
        # replacement below continues decoding physical banks, before mapper init.
        start = source.index("Procedure PpuFetchTileBase()")
        fetchers = source[start:]
        for old, new in views:
            if fetchers.count(old) != 1:
                raise ValueError(f"MMC3 reference pattern read changed: {old}")
            fetchers = fetchers.replace(old, new)
        source = source[:start] + fetchers
    source = replace_procedure(source, "PpuDecode", "") + native_chr_spread()
    # The indexed framebuffer and RDP palette replace Anvil's RGB row cache.
    # Its old buffers otherwise occupy part of the VR4300 stack on large MMC5 carts.
    source = replace_procedure(source, "PpuBuildRgbPairs", "")
    for declaration in ("Global Dim FrameTop.u(30720)", "Global FrameRow.i, FrameBottom.i",
                        "Global Dim NameDesc.u(4096)", "Global Dim RgbCache.i(4096)",
                        "Global Dim RgbTags.i(1024)", "Global Dim RgbPairs.i(64)"):
        if source.count(declaration) != 1:
            raise ValueError(f"unexpected PPU video storage: {declaration}")
        source = source.replace(declaration + "\n", "")
    mask = "    PpuMask=value : PpuColours()"
    if source.count(mask) != 1:
        raise ValueError("PPUMASK write changed")
    source = source.replace(mask, "    previous=PpuMask : PpuMask=value\n"
                            "    If value&$18 : NesBlankUntouched=0 : EndIf\n"
                            "    If (previous!value)&$E1 : PpuColours() : EndIf")
    # Sprite priority is resolved before that row's indexed pixels go to RDP.
    # Leave room to use a whole cache-line-aligned 256-byte row.
    # (#NES_LINE_BYTES, game.pmi: 61,455 for a whole frame; the N5 build keeps only its fallback lines' slots.)
    source = source.replace("LinePixels.a(256)", "LinePixels.a(#NES_LINE_BYTES)")
    # The shared lookup is RGB565; VI and the texture palette use RGBA5551.
    source = replace_procedure(source, "PpuRgbLineRaw", "")
    source = replace_procedure(source, "PpuColours", "Declare PpuColours()")
    source = replace_procedure(source, "PpuBeginLine", """Procedure PpuBeginLine()
  ; DisplayWaitLine handles frame start and the sixteen-line audio cadence.
  If (PpuLine&15)=0 : DisplayWaitLine(PpuLine) : EndIf
  NesLineRow=NesIndexedPixels()+PpuLine*256
EndProcedure""")
    source = replace_procedure(source, "PpuClearSprites",
                               CLEAR_DIRTY_GROUPS if runtime_mmc3 else CLEAR_SPRITES)
    source = replace_procedure(source, "PpuOverlay8", "")
    source = replace_procedure(source, "PpuBuildSpriteCache", "")
    source = replace_procedure(source, "PpuSpritesReference", "")
    source = replace_procedure(source, "PpuRender8Reference",
                               "CompilerIf #GAME_MAPPER=9\n" + RENDER_SPAN +
                               "\nCompilerElseIf #GAME_MAPPER<>5\n" +
                               native_pixel_spread(runtime_mmc3) + "CompilerEndIf")
    # Finish the visible row and hblank together when the interval spans
    # both. Partial intervals keep the dot 256 and 257 edges distinct.
    visible = """    If PpuLine<240
      startDot=PpuDot : endDot=startDot+dots
      If startDot<256
        If startDot=0
          PpuBeginLine()
          CompilerIf #GAME_MAPPER=5 Or #GAME_MAPPER=9
            PpuSpritesRaw()
          CompilerElse
            PpuSpritesReference()
          CompilerEndIf
        EndIf
        step=endDot
        If step>256 : step=256 : EndIf
        CompilerIf #NES_RETAINED_ROWS
          NesReuseLine(step)
        CompilerElse
          NesRenderTo(step)
        CompilerEndIf
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
    if runtime_mmc3:
        source = source.replace(visible_end, "")
        for procedure in ("PpuBeginLine", "PpuIncY"):
            source = replace_procedure(source, procedure, f"Declare {procedure}()")
        for procedure, declaration in (
            ("PpuRegRead", "Declare.i PpuRegRead(addr.i)"),
            ("PpuRegWrite", "Declare PpuRegWrite(addr.i,value.i)"),
        ):
            source = replace_procedure(source, procedure, declaration)
        source += '\nXIncludeFile "../n64/mmc3_ppu_registers.n64"\n'
        return replace_procedure(source, "PpuAdvanceReference",
                                 'XIncludeFile "../n64/mmc3_ppu_raster.n64"')
    return source.replace(visible_end, "").replace(
        "Protected dots.i, edge.i, step.i, width.i, sample.i",
        "Protected dots.i, edge.i, step.i, width.i, startDot.i, endDot.i")
