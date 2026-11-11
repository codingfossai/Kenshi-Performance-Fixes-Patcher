#!/usr/bin/env python3
"""
test_patch_mods.py - Unit test suite for patch_mods.py verification and patch logic.
"""

import os
import shutil
import subprocess
import sys
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

    def test_rtm_whitelist_bytes(self):
        # Pin the WT slot values copied from the disassembled ReturnToMainMenu.dll
        # (gate at 0x1800023F0): a transcription error here would silently
        # whitelist the wrong exe hash.
        rtm = next(d for d in MOD_DEFINITIONS if d["item_id"] == "3806763804")
        self.assertEqual(rtm["requires_patched"], ["kenshi_x64"])
        off, orig, patched, _ = rtm["patches"][0]
        self.assertEqual(off, 0x687D0)
        self.assertEqual(
            orig.decode(),
            "504b362cde850d56afb1cea6f5b7b0ee014d9dd7b47e188599d91c804502cd3e",
        )
        self.assertEqual(
            patched.decode(),
            "452d7a89b36f80c5e313844200b39f70cace691d7d11c497db651d2da0b1d1f5",
        )

    def test_rtm_skipped_when_exe_not_patched(self):
        # End-to-end: with a pristine (ORIGINAL_COMPATIBLE) exe, patch_mods
        # must SKIP the RTM entry and leave both files byte-identical;
        # patching the DLL alone would regress a pristine exe to RTM-D02.
        exe_def = next(d for d in MOD_DEFINITIONS if d["item_id"] == "kenshi_x64")
        rtm = next(d for d in MOD_DEFINITIONS if d["item_id"] == "3806763804")
        buf = bytearray(exe_def["expected_size"])
        for off, orig, _, _ in exe_def["patches"]:
            buf[off : off + len(orig)] = orig
        with open(os.path.join(self.game_dir, exe_def["filename"]), "wb") as f:
            f.write(buf)
        buf = bytearray(rtm["expected_size"])
        buf[0x687D0 : 0x687D0 + 64] = rtm["patches"][0][1]
        mod_dir = os.path.join(self.workshop_dir, rtm["item_id"])
        os.makedirs(mod_dir, exist_ok=True)
        dll_path = os.path.join(mod_dir, rtm["filename"])
        with open(dll_path, "wb") as f:
            f.write(buf)
        self.assertEqual(
            inspect_target(exe_def, self.workshop_dir, self.game_dir)["status"],
            "ORIGINAL_COMPATIBLE",
        )
        with open(dll_path, "rb") as f:
            before = f.read()
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch_mods.py")
        proc = subprocess.run(
            [
                sys.executable,
                script,
                "--workshop-dir",
                self.workshop_dir,
                "--game-dir",
                self.game_dir,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("SKIPPED", proc.stdout)
        with open(dll_path, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(os.path.exists(dll_path + ".orig"))


if __name__ == "__main__":
    unittest.main()
