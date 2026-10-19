    ; PpuRenderRaw's tile loop for the RP2350's Cortex-M33 (spliced in by tools/port_rp2350.py in place
    ; of the Thumb-1 loop in rp2040/ppu_render.pico). Same contract: r4 = V, r5 = line buffer, r7 = tiles
    ; left, r12 = pattern base; leaves through __r_place. Thumb-2 does the masks with UBFX, the tag fetch
    ; and store as scaled loads ([Rn, Rm, lsl #2]), and keeps the tag base in r6, so a hit takes two literal loads, not
    ; six. A miss converts the pattern row exactly as the Thumb-1 miss does. The key carries the
    ; cache generation (RgbTagGen) in bits 24-31, so the palette comes from bits 14-23 only.
    ldr r6, =global_rgbtags
__r_tile:
    ubfx r0, r4, #0, #12
    lsls r0, r0, #1
    ldr r1, =global_namedesc
    ldrh r0, [r1, r0]
    lsrs r1, r0, #8
    lsls r0, r0, #24
    lsrs r0, r0, #21
    orr r0, r0, r1, lsl #14
    add r0, r12
    eor r1, r0, r0, lsr #10
    ubfx r1, r1, #0, #11   ; 2048 tags on the RP2350 (port_rp2350.py sizes the arrays)
    ldr r2, [r6, r1, lsl #2]
    adds r0, #1
    cmp r2, r0
    bne __r_miss
    ldr r2, =global_rgbcache
    add.w r1, r2, r1, lsl #4
__r_copy_tile:
    ldmia r1, {r0, r1, r2, r3}
    stmia r5!, {r0, r1, r2, r3}
    adds r4, #1
    movs r0, #31
    tst r4, r0
    bne __r_tile_next
    subs r4, #32
    ldr r0, =$400
    eors r4, r0
__r_tile_next:
    subs r7, #1
    bne __r_tile
    b __r_place
__r_miss:
    str r0, [r6, r1, lsl #2]
    subs r0, #1
    ldr r2, =global_rgbcache
    add.w r1, r2, r1, lsl #4
    ldr r2, =global_rgbmisses
    ldr r3, [r2]
    adds r3, #1
    str r3, [r2]
    push {r1, r4, r5}
    lsls r4, r0, #8
    lsrs r4, r4, #22
    lsls r4, r4, #6
    ldr r2, =global_rgbpairs
    adds r4, r4, r2
    ubfx r0, r0, #0, #12
    lsls r0, r0, #1
    ldr r2, =global_pattern
    ldr r2, [r2]
    ldrh r5, [r2, r0]
    movs r0, #15
    ands r0, r5
    lsls r0, r0, #2
    ldr r2, [r4, r0]
    str r2, [r1, #0]
    lsrs r5, r5, #4
    movs r0, #15
    ands r0, r5
    lsls r0, r0, #2
    ldr r2, [r4, r0]
    str r2, [r1, #4]
    lsrs r5, r5, #4
    movs r0, #15
    ands r0, r5
    lsls r0, r0, #2
    ldr r2, [r4, r0]
    str r2, [r1, #8]
    lsrs r5, r5, #4
    lsls r0, r5, #2
    ldr r2, [r4, r0]
    str r2, [r1, #12]
    pop {r1, r4, r5}
    b __r_copy_tile
