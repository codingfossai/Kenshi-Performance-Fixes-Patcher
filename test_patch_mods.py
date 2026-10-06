#!/usr/bin/env python3
"""
test_patch_mods.py - Unit test suite for patch_mods.py verification and patch logic.
"""

import os
import shutil
import tempfile
import unittest
from patch_mods import MOD_DEFINITIONS, apply_patch, inspect_target


class TestPatchMods(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workshop_dir = os.path.join(self.tmpdir, "workshop")
        self.game_dir = os.path.join(self.tmpdir, "game")
        os.makedirs(self.workshop_dir, exist_ok=True)
        os.makedirs(self.game_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_files(self):
        for mod_def in MOD_DEFINITIONS:
            res = inspect_target(mod_def, self.workshop_dir, self.game_dir)
            self.assertEqual(res["status"], "MISSING")
            self.assertFalse(res["exists"])

    def test_patch_and_verify_cycle(self):
        # Create dummy binaries with original bytes at offsets
        for mod_def in MOD_DEFINITIONS:
            size = mod_def["expected_size"]
            buf = bytearray(size)
            for off, orig_bytes, patch_bytes, desc in mod_def["patches"]:
                buf[off : off + len(orig_bytes)] = orig_bytes

            category = mod_def.get("category", "workshop")
            if category == "game":
                target_path = os.path.join(self.game_dir, mod_def["filename"])
            else:
                mod_dir = os.path.join(self.workshop_dir, mod_def["item_id"])
                os.makedirs(mod_dir, exist_ok=True)
                target_path = os.path.join(mod_dir, mod_def["filename"])

            with open(target_path, "wb") as f:
                f.write(buf)

            # Check: should detect as ORIGINAL_COMPATIBLE
            res_before = inspect_target(mod_def, self.workshop_dir, self.game_dir)
            self.assertEqual(res_before["status"], "ORIGINAL_COMPATIBLE")

            # Apply patch
            success = apply_patch(mod_def, res_before, dry_run=False)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(target_path + ".orig"))

            # Check after patch
            with open(target_path, "rb") as f:
                patched_data = f.read()
            for off, orig_bytes, patch_bytes, desc in mod_def["patches"]:
                self.assertEqual(patched_data[off : off + len(patch_bytes)], patch_bytes)

    def test_corrupted_or_incompatible_detection(self):
        # Corrupt target offset with invalid opcodes
        mod_def = MOD_DEFINITIONS[0]
        size = mod_def["expected_size"]
        buf = bytearray(size)
        off, orig_bytes, patch_bytes, desc = mod_def["patches"][0]
        buf[off : off + len(orig_bytes)] = b"\xaa\xbb"  # Corrupted bytes

        mod_dir = os.path.join(self.workshop_dir, mod_def["item_id"])
        os.makedirs(mod_dir, exist_ok=True)
        target_path = os.path.join(mod_dir, mod_def["filename"])
        with open(target_path, "wb") as f:
            f.write(buf)

        res = inspect_target(mod_def, self.workshop_dir, self.game_dir)
        self.assertEqual(res["status"], "INCOMPATIBLE_UPDATE")


if __name__ == "__main__":
    unittest.main()
