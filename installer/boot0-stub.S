/*
 * Loaded by the vendor boot0 from eMMC (sector 38192) at 0x4a000000 in place of its u-boot, after
 * DRAM initialization. Copies the bundled SPL (u-boot-nodram, skips DRAM) to SRAM A1, marks the
 * eGON header as booted from eMMC (MMC2) and jumps to the SPL; the rest is as on other screens.
 * File layout: 0x000 "uboot" header (boot0 overwrites 0x30-0xb0 and 0xe4), 0x400 this code,
 * 0x1000 SPL. Build: install/make-boot0-payload.sh
 */
	.arm
	.text
	.global	_start
_start:
	ldr	r0, =0x00000000		@ SRAM A1, SPL load address used by the BROM
	ldr	r1, =0x4a001000		@ SPL in this file
	ldr	r2, [r1, #0x10]		@ SPL length from the eGON header
1:	ldr	r3, [r1], #4
	str	r3, [r0], #4
	subs	r2, r2, #4
	bne	1b
	mov	r0, #0
	mov	r3, #2			@ boot_media = SUNXI_BOOTED_FROM_MMC2
	str	r3, [r0, #0x28]
	mcr	p15, 0, r0, c7, c5, 0	@ invalidate I-cache
	dsb
	isb
	bx	r0
	.ltorg
