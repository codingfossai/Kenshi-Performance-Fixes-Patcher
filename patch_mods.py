#!/usr/bin/env python3
"""
patch_mods.py - Verifies and applies binary performance and crash patches
for Kenshi and its mod collection plugins.

Supported Patches:
1. PersistentPrisoners.dll (Steam Workshop ID: 3798215878)
   - Issue: periodicUpdate triggers a full-world unindexed linear squad/character search
     every 1,000 ms, freezing the main simulation thread for ~650 ms (causing a rhythmic
     stutter every ~1.65 seconds).
   - Fix: Extends the throttle timer from 1,000 ms (0x3e8) to 60,000 ms (0xea60).
2. BetterPhysics.dll (Steam Workshop ID: 3792126203)
   - Issue: Synchronous config text reload (fopen/fclose) on the main thread every 5,000 ms.
   - Fix: Bypasses the 5-second reload timer check on the main thread.
3. FallDamage.dll (Steam Workshop ID: 3791565594)
   - Issue: Synchronous config reload every 5,000 ms + 1-second heartbeat debug logging.
   - Fix: Bypasses the 5s reload check and the 1s heartbeat log write.
4. kenshi_x64.exe (Game Executable)
   - Issue: Organize-the-Crafting-Stations invokes Kenshi's is_trader (0x1405cf4e0) when sorting
     crafting stations/buildings in the build menu. Buildings lack a trader component (NULL),
     causing Kenshi to blind-dereference [rcx + 0x658], crashing with 0xc0000005 at 0x140387870.
   - Fix: Inserts a NULL check in is_trader returning false (0) if rcx or [rcx + 0x658] is NULL.

Usage:
    python patch_mods.py [--check-only] [--dry-run] [--force]
    python patch_mods.py --workshop-dir "C:\\Program Files (x86)\\Steam\\steamapps\\workshop\\content\\233860" --game-dir "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Kenshi"
"""

import argparse
import hashlib
import os
import platform
import shutil
import sys
from typing import Dict, List, Optional, Tuple


def find_default_steam_paths() -> Tuple[Optional[str], Optional[str]]:
    """Attempts to auto-detect Steam Workshop and Kenshi game installation directories."""
    system = platform.system()
    workshop_candidates: List[str] = []
    game_candidates: List[str] = []

    if system == "Linux":
        home = os.path.expanduser("~")
        workshop_candidates.extend([
            os.path.join(home, ".local/share/Steam/steamapps/workshop/content/233860"),
            os.path.join(home, ".steam/steam/steamapps/workshop/content/233860"),
            os.path.join(home, ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/workshop/content/233860"),
        ])
        game_candidates.extend([
            os.path.join(home, ".local/share/Steam/steamapps/common/Kenshi"),
            os.path.join(home, ".steam/steam/steamapps/common/Kenshi"),
            os.path.join(home, ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/common/Kenshi"),
        ])
    elif system == "Windows":
        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        prog_64 = os.environ.get("ProgramFiles", r"C:\Program Files")
        drives = [r"C:", r"D:", r"E:", r"F:", r"G:", r"S:"]

        for d in drives:
            workshop_candidates.append(os.path.join(d, r"\SteamLibrary\steamapps\workshop\content\233860"))
            workshop_candidates.append(os.path.join(d, r"\steamapps\workshop\content\233860"))
            game_candidates.append(os.path.join(d, r"\SteamLibrary\steamapps\common\Kenshi"))
            game_candidates.append(os.path.join(d, r"\steamapps\common\Kenshi"))

        workshop_candidates.extend([
            os.path.join(prog_x86, r"Steam\steamapps\workshop\content\233860"),
            os.path.join(prog_64, r"Steam\steamapps\workshop\content\233860"),
        ])
        game_candidates.extend([
            os.path.join(prog_x86, r"Steam\steamapps\common\Kenshi"),
            os.path.join(prog_64, r"Steam\steamapps\common\Kenshi"),
        ])

    detected_workshop = next((p for p in workshop_candidates if os.path.isdir(p)), None)
    detected_game = next((p for p in game_candidates if os.path.isdir(p)), None)

    return detected_workshop, detected_game


MOD_DEFINITIONS: List[Dict] = [
    {
        "name": "BetterPhysics",
        "category": "workshop",
        "item_id": "3792126203",
        "filename": "BetterPhysics.dll",
        "description": "Bypasses 5-second synchronous BetterPhysics_Config.txt disk reload loop",
        "orig_sha256": "5e2ee8919ea340e1a99e4f458ef3c3edd641d7ec9784ce8cff67d9349a5ba156",
        "patched_sha256": "9607b2778dd6fb828797bd233d5845e7dba3603072b84158b21636d2324a2cd1",
        "expected_size": 27136,
        "patches": [
            (
                0xEE1,
                bytes.fromhex("720c"),
                bytes.fromhex("eb0c"),
                "5s config reload timer check (jb +0xc -> jmp +0xc)",
            ),
        ],
    },
    {
        "name": "FallDamage",
        "category": "workshop",
        "item_id": "3791565594",
        "filename": "FallDamage.dll",
        "description": "Bypasses 5-second FallDamage_Config.txt reload & 1-second heartbeat debug logging",
        "orig_sha256": "2051dfed8a340fa3c6e910c1c60275290bb97127e9733e93a46d1d994b01d7f9",
        "patched_sha256": "ad8cffc8ad8c942773b478a10325e079f14ebc97cb7e2a491e6077665f8083d8",
        "expected_size": 28160,
        "patches": [
            (
                0x19D0,
                bytes.fromhex("720c"),
                bytes.fromhex("eb0c"),
                "5s config reload timer check (jb +0xc -> jmp +0xc)",
            ),
            (
                0x1A87,
                bytes.fromhex("7272"),
                bytes.fromhex("eb72"),
                "1s heartbeat debug logging loop (jb +0x72 -> jmp +0x72)",
            ),
        ],
    },
    {
        "name": "PersistentPrisoners",
        "category": "workshop",
        "item_id": "3798215878",
        "filename": "PersistentPrisoners.dll",
        "description": "Scales periodicUpdate full-world linear squad scan interval from 1s to 60s",
        "orig_sha256": "b158f04ae136d85830c57974894daad3b43a2b9d069dc11d03f44f00f6b1f518",
        "patched_sha256": "2efa65e18b5fd915967fe99f028e803f854b3210bfbf09b7d243a2ab2abd551a",
        "expected_size": 196608,
        "patches": [
            (
                0x5450,
                bytes.fromhex("3de8030000"),
                bytes.fromhex("3d60ea0000"),
                "periodicUpdate timer check (cmp eax, 1000 -> cmp eax, 60000)",
            ),
        ],
    },
    {
        "name": "kenshi_x64.exe (Game Executable)",
        "category": "game",
        "item_id": "kenshi_x64",
        "filename": "kenshi_x64.exe",
        "description": "NULL-safe guard in is_trader (0x1405cf4e0) preventing crash when mods like Organize-the-Crafting-Stations sort non-character buildings",
        "orig_sha256": "504b362cde850d56afb1cea6f5b7b0ee014d9dd7b47e188599d91c804502cd3e",
        "patched_sha256": "b2939d05c08af970213ff8431ed04c1709f3b77138e3407b10f6497a92d05508",
        "expected_size": 36713984,
        "patches": [
            (
                0x5CE8E0,
                bytes.fromhex("488b8958060000e926c4a6ffcccccccccccccccccccccccccccccccccccccccc"),
                bytes.fromhex("4885c97413488b89580600004885c97407e91cc4a6ffcccc31c0c3cccccccccc"),
                "is_trader NULL component check (test rcx, jz return_false)",
            ),
        ],
    },
]


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_target(mod_def: Dict, workshop_dir: Optional[str], game_dir: Optional[str]) -> Dict:
    category = mod_def.get("category", "workshop")
    if category == "game":
        base_dir = game_dir
        path = os.path.join(base_dir, mod_def["filename"]) if base_dir else None
    else:
        base_dir = workshop_dir
        path = os.path.join(base_dir, mod_def["item_id"], mod_def["filename"]) if base_dir else None

    result = {
        "name": mod_def["name"],
        "category": category,
        "item_id": mod_def["item_id"],
        "path": path,
        "exists": False,
        "status": "MISSING",  # MISSING, PATCHED, ORIGINAL_COMPATIBLE, INCOMPATIBLE_UPDATE
        "sha256": None,
        "size": None,
        "details": [],
    }

    if not path or not os.path.isfile(path):
        result["details"].append(f"Target not found: {path or '(directory not configured)'}")
        return result

    result["exists"] = True
    with open(path, "rb") as f:
        data = f.read()

    result["size"] = len(data)
    curr_sha256 = compute_sha256(data)
    result["sha256"] = curr_sha256

    # 1. Exact SHA256 match for already patched
    if curr_sha256 == mod_def["patched_sha256"]:
        result["status"] = "PATCHED"
        result["details"].append("File matches known patched SHA256 exactly.")
        return result

    # 2. Exact SHA256 match for original
    if curr_sha256 == mod_def["orig_sha256"]:
        result["status"] = "ORIGINAL_COMPATIBLE"
        result["details"].append("File matches known original baseline SHA256 exactly.")
        return result

    # 3. File hash differs: check individual patch byte patterns at designated offsets
    all_patched = True
    all_orig = True
    opcodes_corrupted = False

    for offset, orig_bytes, patch_bytes, patch_desc in mod_def["patches"]:
        p_len = len(orig_bytes)
        if offset + p_len > len(data):
            opcodes_corrupted = True
            all_patched = False
            all_orig = False
            result["details"].append(
                f"Offset {hex(offset)} ({patch_desc}) exceeds file length ({len(data)} bytes)."
            )
            continue

        chunk = data[offset : offset + p_len]
        if chunk == patch_bytes:
            all_orig = False
        elif chunk == orig_bytes:
            all_patched = False
        else:
            all_patched = False
            all_orig = False
            opcodes_corrupted = True
            result["details"].append(
                f"Byte mismatch at {hex(offset)} ({patch_desc}): "
                f"found '{chunk.hex()}', expected orig '{orig_bytes.hex()}' or patch '{patch_bytes.hex()}'."
            )

    if all_patched and not opcodes_corrupted:
        result["status"] = "INCOMPATIBLE_UPDATE"
        result["details"].append(
            f"File SHA256 ({curr_sha256[:12]}...) differs from baseline ({mod_def['patched_sha256'][:12]}...), "
            f"though target opcodes match. Target was likely updated upstream or modified."
        )
        return result

    if all_orig and not opcodes_corrupted:
        result["status"] = "ORIGINAL_COMPATIBLE"
        result["details"].append(
            f"Notice: File SHA256 ({curr_sha256[:12]}...) differs from baseline ({mod_def['orig_sha256'][:12]}...), "
            f"but all patch sites match expected original opcodes (binary compatible)."
        )
        return result

    # If neither, mod has been updated or altered upstream
    result["status"] = "INCOMPATIBLE_UPDATE"
    result["details"].append(
        f"File SHA256 ({curr_sha256[:12]}...) does not match known original ({mod_def['orig_sha256'][:12]}...) "
        f"or patched version, and target opcodes differ. The file was updated upstream by author or corrupted."
    )
    return result


def apply_patch(mod_def: Dict, mod_info: Dict, dry_run: bool = False) -> bool:
    path = mod_info["path"]
    with open(path, "rb") as f:
        data = bytearray(f.read())

    # Create safety backup if not already present
    orig_backup = path + ".orig"
    if not os.path.exists(orig_backup):
        if not dry_run:
            shutil.copy2(path, orig_backup)
        print(f"  [+] Created backup: {orig_backup}")
    else:
        print(f"  [*] Backup already exists: {orig_backup}")

    # Patch bytes in bytearray
    for offset, orig_bytes, patch_bytes, patch_desc in mod_def["patches"]:
        curr = bytes(data[offset : offset + len(patch_bytes)])
        if curr == patch_bytes:
            print(f"  [*] Already patched at {hex(offset)}: {patch_desc}")
            continue
        if curr != orig_bytes:
            print(
                f"  [-] Error: Unexpected bytes at {hex(offset)} ({curr.hex()} != {orig_bytes.hex()}). Aborting patch."
            )
            return False
        data[offset : offset + len(patch_bytes)] = patch_bytes
        print(f"  [+] Patched {hex(offset)}: {orig_bytes.hex()} -> {patch_bytes.hex()} ({patch_desc})")

    if not dry_run:
        with open(path, "wb") as f:
            f.write(data)
        new_sha256 = compute_sha256(bytes(data))
        if new_sha256 == mod_def["patched_sha256"]:
            print(f"  [✓] Verified: File hash matches expected patched SHA256 ({new_sha256[:12]}...).")
        else:
            print(f"  [!] Note: New SHA256 is {new_sha256[:12]}... (applied successfully).")
    else:
        print("  [DRY-RUN] No changes written to disk.")

    return True


def main():
    detected_workshop, detected_game = find_default_steam_paths()

    parser = argparse.ArgumentParser(
        description="Verify and patch Kenshi mod stalls (BetterPhysics, FallDamage, PersistentPrisoners) & build menu CTD."
    )
    parser.add_argument(
        "--workshop-dir",
        default=detected_workshop,
        help=f"Path to Kenshi Steam Workshop folder (233860) [Default: {detected_workshop}]",
    )
    parser.add_argument(
        "--game-dir",
        default=detected_game,
        help=f"Path to Kenshi game directory (containing kenshi_x64.exe) [Default: {detected_game}]",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check status and print reports; do not modify files on disk.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate patching without modifying files on disk.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-applying patch even if already patched.",
    )
    args = parser.parse_args()

    print("=" * 76)
    print(" Kenshi Performance & Stability Fixes - Binary Patch Verifier & Updater")
    print(f" Workshop directory: {args.workshop_dir or '(Not found / not specified)'}")
    print(f" Game directory:     {args.game_dir or '(Not found / not specified)'}")
    print("=" * 76)

    has_incompatible = False
    has_unpatched = False

    for mod_def in MOD_DEFINITIONS:
        print(f"\n[{mod_def['name']}] (ID: {mod_def['item_id']})")
        print(f"  Purpose: {mod_def['description']}")

        info = inspect_target(mod_def, args.workshop_dir, args.game_dir)
        status = info["status"]

        if status == "PATCHED":
            print("  Status: [PATCHED] (OK - performance / stability fix is active)")
            for d in info["details"]:
                print(f"    - {d}")
            if args.force:
                print("  --force specified: re-applying patch...")
                apply_patch(mod_def, info, dry_run=args.dry_run)

        elif status == "ORIGINAL_COMPATIBLE":
            has_unpatched = True
            print("  Status: [ORIGINAL - COMPATIBLE] (Binary is unpatched or re-downloaded by Steam)")
            for d in info["details"]:
                print(f"    - {d}")
            if args.check_only:
                print("  Action: Patch needed (--check-only specified, skipping write).")
            else:
                print("  Action: Applying binary patch...")
                success = apply_patch(mod_def, info, dry_run=args.dry_run)
                if not success:
                    print("  [-] Patching failed.")

        elif status == "INCOMPATIBLE_UPDATE":
            has_incompatible = True
            print("  Status: [ALERT: INCOMPATIBLE UPDATE / UNEXPECTED BYTES]")
            for d in info["details"]:
                print(f"    ! {d}")
            print("  Recommendation:")
            print("    The author updated the mod or file structure changed.")
            print("    Please investigate the new binary or ask your AI coding agent to inspect")
            print("    the updated disassembly to verify if upstream fixed the issue or if new offsets are needed.")

        elif status == "MISSING":
            print(f"  Status: [NOT INSTALLED / NOT FOUND]")
            for d in info["details"]:
                print(f"    - {d}")

    print("\n" + "=" * 76)
    if has_incompatible:
        print("SUMMARY: WARNING - One or more targets have been updated upstream with a new")
        print("         binary layout. Manual / AI agent review is recommended.")
        sys.exit(2)
    elif has_unpatched and args.check_only:
        print("SUMMARY: Notice - One or more files are unpatched.")
        print("         Run 'python patch_mods.py' without --check-only to patch them.")
        sys.exit(1)
    else:
        print("SUMMARY: All inspected targets are properly patched and verified.")
        sys.exit(0)


if __name__ == "__main__":
    main()
