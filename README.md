# Kenshi Performance & Stability Fixes - Binary Patch Verifier

> [!IMPORTANT]
> **Clear-Text Security & AI Review Notice:**
> No binary executables (`.exe`) are distributed in this repository. All patches are provided in plain-text Python source code and transparent byte offsets so that users and their AI coding assistants (such as Claude Code, Cursor, Codex, Copilot, ChatGPT, Gemini, or local models) can independently audit, adapt, and execute the patches.

---

## Overview

When playing heavily modded Kenshi setups (such as the [MEGA Kaizo/UWE+ Modpack](https://steamcommunity.com/sharedfiles/filedetails/?id=2822248814)), players frequently suffer from:
1. **A rhythmic micro-stutter every ~1.65 seconds** (a ~650 ms full simulation freeze).
2. **Periodic hitches every ~5 seconds** caused by disk I/O on the main render thread.
3. **Instant crash to desktop (CTD, `0xc0000005`)** when hovering over or organizing buildings and crafting stations in the build menu.
4. **Instant CTD (`0xc0000005`)** when interacting with cages, looting bodies, or updating character inventory/equipment components.

This repository provides clear-text documentation of the root causes, exact disassembly breakdowns, and an automated verification script ([`patch_mods.py`](patch_mods.py)) to apply and preserve these fixes against Steam Workshop re-downloads.

---

## The Issues & Root Causes

### 1. `PersistentPrisoners.dll` (Workshop ID: `3798215878`)
- **Symptom:** Every ~1.65–1.71 seconds, Kenshi locks up for ~620–680 ms. Frame rate drops to 0, DXVK and physics worker threads stall waiting for the main thread lock.
- **Root Cause:**
  The mod hooks Kenshi's `periodicUpdate` (`0x1407b5a10`). Inside its hook (`0x180005ef0`), it measures elapsed time using `GetTickCount()` against a 1,000 ms (`0x3e8`) threshold. When triggered, it invokes an internal world search function (`0x180005c20`) that sequentially scans active squads and characters in the loaded game world (`0x1407945a0`).
  In populated worlds, this brute-force search takes **~650 ms of CPU execution**.
  Because the timer checks every 1,000 ms and the scan takes 650 ms, the total cycle duration is:
  $$\text{Interval} = 1000\text{ ms} + 650\text{ ms} \approx 1650\text{ ms}$$
- **Fix:**
  Scale the timer threshold from 1,000 ms (`0x3e8`) to 60,000 ms (`0xea60` / 60 seconds). Cage persistence, prisoner states, and hunger floors remain 100% functional, while 98.4% of all CPU pauses are permanently eliminated.
  - **Raw File Offset:** `0x5450` (RVA `0x6050`)
  - **Original Opcode:** `3d e8 03 00 00` (`cmp %eax, 0x3e8`)
  - **Patched Opcode:** `3d 60 ea 00 00` (`cmp %eax, 0xea60`)

---

### 2. `BetterPhysics.dll` (Workshop ID: `3792126203`) & `FallDamage.dll` (Workshop ID: `3791565594`)
- **Symptom:** Rhythmic frame hitches every 5 seconds.
- **Root Cause:**
  Both DLLs hook Kenshi's main game loop and check a 5,000 ms timer (`cmp %rcx, 0x1388`). On every tick, each DLL executes synchronous Win32 file I/O (`GetModuleFileNameA`, `fopen`, line parsing, and `fclose`) on the simulation thread to hot-reload `*_Config.txt` files, followed by synchronous `DebugLog()` writes to disk. In addition, `FallDamage.dll` logs a heartbeat every 1,000 ms.
- **Fix:**
  Bypass the 5-second reload checks on the main thread (the initial config is still loaded at game startup):
  - **`BetterPhysics.dll`** offset `0xee1`: Change `72 0c` (`jb +0xc`) to `eb 0c` (`jmp +0xc`).
  - **`FallDamage.dll`** offset `0x19d0`: Change `72 0c` to `eb 0c`.
  - **`FallDamage.dll`** offset `0x1a87` (1s heartbeat log): Change `72 72` to `eb 72`.

---

### 3. `Organize-the-Crafting-Stations.dll` (Workshop ID: `3688602277`) & `kenshi_x64.exe` CTD
- **Symptom:** Hovering over or sorting crafting stations/buildings in the build menu causes an immediate crash with `STATUS_ACCESS_VIOLATION` (`0xc0000005` reading `0x0000000000000078`).
- **Root Cause:**
  When comparing items to sort the build menu (`+0x4af08`), `Organize-the-Crafting-Stations` invokes Kenshi's exported `is_trader` query function via `KenshiLib` (`0x1405cf4e0`) on building objects:
  ```assembly
  0x1405cf4e0: mov 0x658(%rcx), %rcx    ; extracts trader component from object
  0x1405cf4e7: jmp 0x14003b912          ; jumps to 0x140387820 (reads "is trader" property)
  ```
  Vanilla Kenshi only calls `is_trader` on characters/squads that always have a non-null `0x658` component. Buildings and crafting stations lack this component (`[rcx + 0x658] == NULL`). Kenshi passes NULL into `0x140387820`, which executes:
  ```assembly
  0x140387870: mov 0x78(%rbx), %rax     ; DEREFERENCES NULL + 0x78 -> CRASH!
  ```
- **Fix:**
  In `kenshi_x64.exe` at `0x1405cf4e0`, insert a NULL check returning `0` (`false`) if `rcx` or `[rcx + 0x658]` is NULL. If an object has no trader component, it is obviously not a trader.
  - **Raw File Offset:** `0x5ce8e0` (VA `0x1405cf4e0`)
  - **Original Opcode (12 bytes + padding):**
    `48 8b 89 58 06 00 00 e9 26 c4 a6 ff ...`
  - **Patched Opcode (32 bytes):**
    `48 85 c9 74 13 48 8b 89 58 06 00 00 48 85 c9 74 07 e9 1c c4 a6 ff cc cc 31 c0 c3 cc cc cc cc cc`

---

### 4. UI Item-Slot "outside" Layout Lookup CTD (`0x14074707f` / `0x140713f3b`)
- **Symptom:** Hovering over or interacting with certain inventory/equipment items triggers an instant crash with `STATUS_ACCESS_VIOLATION` (`0xc0000005` reading `0x0000000000000028`).
- **Root Cause:**
  During item UI event handling (`MyGUI::WidgetInput` -> `0x140713e50`), the engine queries the item's visual attachment container (`call *0x70(%rax)`) to look up its `"outside"` slot node in an internal `std::map`. For items without visual external attachments or custom modded equipment, the virtual method returns `NULL`. The engine then calls `0x14004fdb8` (`std::map::find` at `0x140747070`) passing `rcx = NULL`, causing `0x14074707f` (`movzbl 0x28(%rcx), %eax`) to crash on NULL dereference.
- **Fix:**
  In `kenshi_x64.exe` at `0x140713f10`, check if the container pointer (`0x48(%rsp)`) is NULL when comparing the slot name against `"outside"`. If NULL, immediately branch to the clean string-cleanup function exit (`0x1407145ac`).
  - **Raw File Offset:** `0x713310` (VA `0x140713f10`)
  - **Original Opcode (18 bytes):**
    `85 c9 0f 94 c0 84 c0 0f 94 c0 84 c0 0f 84 8a 06 00 00`
  - **Patched Opcode (18 bytes):**
    `85 c9 75 08 48 83 7c 24 48 00 75 06 e9 8b 06 00 00 90`

---

### 5. Character Equipment Container Lookup CTD (`0x14026b7b9` / `0x140012788`)
- **Symptom:** Interacting with character cages (e.g. cannibalism / eat-alive tasks), looting entities, or updating inventory slots triggers an instant crash with `STATUS_ACCESS_VIOLATION` (`0xc0000005` reading `0x00000000000001f8` or `0x0000000000000008`).
- **Root Cause:**
  Callers (such as `0x14050dd03`) call thunk `0x140012788` -> `0x14026b750` passing a container pointer in `%rcx` and slot index `0..4` in `%edx`. At `0x14026b770`, the function computes an offset into `%rcx` based on `%edx` into `%r13` (`lea 0x1f8(%rcx), %r13`). If the target entity lacks the inventory component (`%rcx == NULL`), or if `%edx > 4` (unsupported slot), `%r13` becomes `0x1f8` or `NULL`, and `0x14026b7b9` (`mov 0x8(%r13), %ebx`) unconditionally dereferences `[%r13 + 8]`, crashing the engine.
- **Fix:**
  Insert a NULL and bounds-check preamble in the unused alignment padding preceding `0x14026b750` (at `0x14026b745`, raw offset `0x26ab45`) returning immediately if `%rcx == NULL` or `%edx > 4`. Redirect thunk `0x140012788` (offset `0x11b88`) to the preamble:
  - **Thunk File Offset:** `0x11B88` (VA `0x140012788`)
    - **Original Opcode:** `e9 c3 8f 25 00` (`jmp 0x14026b750`)
    - **Patched Opcode:** `e9 b8 8f 25 00` (`jmp 0x14026b745`)
  - **Preamble File Offset:** `0x26AB45` (VA `0x14026b745`)
    - **Original Opcode (11 bytes):** `cc cc cc cc cc cc cc cc cc cc cc`
    - **Patched Opcode (11 bytes):** `48 85 c9 74 05 83 fa 04 76 01 c3`
      - `test %rcx, %rcx; je ret; cmp $4, %edx; jbe enter; ret`

---

## How to Apply

### Option A: Use Your Favorite AI Coding Assistant (Recommended)

Because this repository contains clear-text code and exact offsets, you can instruct your AI assistant (e.g., Claude Code, Cursor, Aider, Copilot, ChatGPT):

> *"Please review the patch definitions in `patch_mods.py` against my local Kenshi installation, create safety backups (`.orig`), and apply the binary performance and crash fixes for BetterPhysics, FallDamage, PersistentPrisoners, and kenshi_x64.exe."*

Your assistant can verify the byte patterns, check file hashes, and safely apply the changes directly in your environment.

---

### Option B: Run the Clear-Text Python Script Directly

Prerequisites: Python 3.8+ installed.

1. **Verify status without making any changes:**
   ```bash
   python patch_mods.py --check-only
   ```
2. **Apply the patches:**
   ```bash
   python patch_mods.py
   ```
   The script will:
   - Auto-detect your Steam Workshop and Kenshi game folders on Linux and Windows.
   - Automatically create `<filename>.orig` safety backups before touching any file.
   - Verify SHA256 checksums and exact machine code patterns.
   - Safeguard against corrupting files if an author has updated the mod with a new binary layout.

3. **Specify custom Steam paths (if not installed in standard directories):**
   ```bash
   python patch_mods.py --workshop-dir "D:\SteamLibrary\steamapps\workshop\content\233860" --game-dir "D:\SteamLibrary\steamapps\common\Kenshi"
   ```

---

## Re-Download Safeguard

Steam Workshop periodically audits subscribed items and re-downloads original files, silently reverting local patches.

Running `python patch_mods.py` whenever you notice stuttering will instantly verify all four targets and re-apply the fixes in seconds.

---

## Disclaimer

This repository is an independent community performance initiative and is not affiliated with or endorsed by Lo-Fi Games or the original mod authors. Always keep backups of your game files before applying any binary patches.
