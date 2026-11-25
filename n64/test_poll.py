"""Cycle and side-effect boundaries for the N64 cartridge's polling descriptors."""
import unittest

from stage_poll import poll_rule
from stage_ramwait import ram_wait_source


class StatusLoopTests(unittest.TestCase):
    def rule(self, program, value=0, offset=0):
        rom = bytearray(0x8000)
        rom[offset:offset + len(program)] = program
        return poll_rule(rom, offset, value)

    def test_lda_loop_charges_taken_page_crossing(self):
        code = bytes.fromhex("ad 02 20 10 fb")
        self.assertEqual(self.rule(code, offset=0xfd), (2 << 8) | 8)
        self.assertEqual(self.rule(code, 128), 0)

    def test_bit_preserves_accumulator_and_observes_two_status_bits(self):
        code = bytes.fromhex("2c 02 20 30 02 50 f9")
        self.assertEqual(self.rule(code), (3 << 8) | 9)
        for value in (64, 128, 192):
            self.assertEqual(self.rule(code, value), 0)

    def test_skip_requires_known_flags_and_no_other_bus_access(self):
        for body in ("f0 fb", "a9 00 10 f9", "85 00 10 f9", "90 fb"):
            self.assertEqual(self.rule(bytes.fromhex("2c 02 20 " + body)), 0)
        self.assertEqual(self.rule(bytes.fromhex("ad 02 20 50 fb")), 0)

    def test_banked_wait_may_only_follow_relative_control_flow_inside_the_slot(self):
        page = bytearray(8192)
        page[:6] = bytes.fromhex("ad 02 20 4c 00 80")
        self.assertEqual(poll_rule(page, 0, 0, relocatable=True), 0)
        page[-6:] = bytes.fromhex("ad 02 20 10 01 ea")
        self.assertEqual(poll_rule(page, 8186, 0, relocatable=True), 0)

    def test_cmp_carry_and_retired_count(self):
        code = bytes.fromhex("ad 02 20 c9 40 90 f9")
        rule = self.rule(code, 32)
        self.assertEqual(rule & 65535, (3 << 8) | 9)
        self.assertEqual(((rule >> 16) & 511) - 256, -32)
        self.assertTrue(rule & (1 << 25))


class RamWaitWindowTests(unittest.TestCase):
    def test_mmc1_checks_both_instruction_addresses_across_banks_and_pages(self):
        rom = bytearray(32768)
        rom[0x45:0x49] = bytes.fromhex("a5 07 d0 fc")
        rom[0x40fe:0x4102] = bytes.fromhex("a5 05 f0 fc")
        source, found = ram_wait_source(rom, 1)
        self.assertTrue(found)
        table = source.split("NesPossibleWait:\n")[1].split("EndDataSection")[0]
        values = [int(byte) for row in table.splitlines()
                  for byte in row.strip().removeprefix("Data.a ").split(",")]
        self.assertEqual(len(values), 256)
        self.assertEqual({i for i, byte in enumerate(values) if byte}, {0x45, 0x47, 0xfe, 0x00})


if __name__ == "__main__":
    unittest.main()
