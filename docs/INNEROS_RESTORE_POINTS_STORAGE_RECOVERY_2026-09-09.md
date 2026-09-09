# InnerOS Restore Points + Storage Recovery — 2026-09-09

Task: `ops_7ffd0d39186b`  
Correlation: `inneros-restore-points-storage-recovery-20260909`  
Mode: read-first, no destructive storage writes.

## What Changed

- AG-37 Disk Steward now treats `/mnt/datos_agentes` as a primary monitored mount for Intel `.4`.
- Disk Steward detects large backup trees on primary mounts and labels them as `second_gate_review_before_move_or_delete`.
- Disk Steward alerting now has dedup/hysteresis (`DISK_ALERT_DEDUP_MINUTES`, default 360) so Rafael is alerted on actionable state changes without timer spam.
- Added bounded InnerOS Restore Points: config/release checkpoints with manifest, hashes and copied small files. These are explicitly not backups or disk snapshots.
- Added MCP tools:
  - `inneros_restore_point_create`
  - `inneros_restore_point_list`
  - `inneros_restore_point_plan`
- Restore execution is intentionally not exposed; restore plans require explicit owner approval before any live overwrite.

## Read-Only Inventory Summary

### Intel `.4` / `ralphi-ia-ver-10`

Observed via `lsblk`, `findmnt`, `df`, `blkid` without destructive writes.

| Mount | Device | FS | Approx total | Used | Free | Use | Role |
|---|---:|---|---:|---:|---:|---:|---|
| `/` | `/dev/mapper/ubuntu--vg-ubuntu--lv` | ext4 on LVM | 877G | 625G | 216G | 75% | primary/root |
| `/mnt/datos_agentes` | `/dev/sdb1` | ext4 | 880G | 679G | 156G | 82% | primary/data |
| `/boot` | `/dev/sda2` | ext4 | 2.0G | 201M | 1.6G | 11% | boot |
| `/boot/efi` | `/dev/sda1` | vfat | 1.1G | 6.2M | 1.1G | 1% | boot |

Physical devices detected:

| Device | Model | ROTA | Size | Notes |
|---|---|---:|---:|---|
| `/dev/sda` | ADATA SU650 | 0 | 960GB | OS SSD, LVM root |
| `/dev/sdb` | HS-SSD-WAVE(S) | 0 | 960GB | mounted at `/mnt/datos_agentes` |

No mechanical HDD was visible/mounted on Intel `.4` in this read-only inventory.

Root cause candidate found by AG-37 smoke:

| Path | Size | Mount | Issue |
|---|---:|---|---|
| `/home/rlopez/data/backups` | ~607.79G | `/mnt/datos_agentes` | large backup tree on primary mount |
| `/home/rlopez/data/backups/disaster_recovery` | ~604.43G | `/mnt/datos_agentes` | large backup tree on primary mount |

Earlier direct `du` also saw `/mnt/datos_agentes/backups/off-root` around ~649G before the live status resolved the canonical symlinked path as `/home/rlopez/data/backups`.

### AMD `.5` / `ralfiia-amd`

| Mount | Device | FS | Approx total | Used | Free | Use | Role |
|---|---:|---|---:|---:|---:|---:|---|
| `/` | `/dev/mapper/ubuntu--vg-ubuntu--lv` | ext4 on LVM | 466G | 279G | 168G | 63% | primary/root |
| `/home/rlopez/projects` | `/dev/nvme0n1p3` | ext4 | 466G | 12G | 431G | 3% | fast SSD projects |
| `/home/rlopez/data` | `/dev/sdb1` | ext4 | 1.8T | 687G | 1.1T | 40% | mechanical/cold data |

Physical devices detected:

| Device | Model | ROTA | Size | Mount |
|---|---|---:|---:|---|
| `/dev/sda` | ADATA SU650 | 0 | 512GB | root LVM |
| `/dev/nvme0n1` | ADATA LEGEND 710 | 0 | 512GB | `/home/rlopez/projects` |
| `/dev/sdb` | WDC WD20PURZ-85G | 1 | 2TB | `/home/rlopez/data` |

AMD is currently using the mechanical disk correctly for data/backups. Large data consumers are expected/known categories: ROCm canary, Ollama models, Google Drive mirrors/archive, Takeouts, PST archive, venvs. No destructive cleanup was performed.

## What Could Not Be Fully Verified Without Privilege

The following commands require passwordless sudo or an approved helper and were not forced:

- `pvs`, `vgs`, `lvs` with full LVM lock access.
- `smartctl --scan-open` and disk SMART health.
- Any partition/mount/resize/mkfs operation.

Non-root evidence still confirms filesystem, mounts, ROTA, sizes and backup placement.

## Restore Point Policy

Restore Points are for rollback checkpoints of config/source state. They are not backups.

Recommended default policy:

- Mandatory pre/post deploy restore point.
- Hourly restore point only for bounded config/release roots, not data/model folders.
- Keep 24 hourly / 7 daily / 4 weekly restore point manifests.
- Store restore points on `/home/rlopez/data/inneros_restore_points` where available.
- If a node lacks a mechanical/archive mount, do not store large restore payloads there.

## Second-Gate Recovery Plan For Intel `.4`

No automatic deletion/move should run yet. The next destructive action must be separately approved.

1. Confirm whether `/home/rlopez/data/backups/disaster_recovery` is duplicated content, hardlinked content, or the canonical only copy.
2. Generate manifest of top-level backup folders with mtime, inode/device, file count, and sample hashes.
3. Confirm target archive destination:
   - preferred: a mechanical HDD on Intel if one exists but is not mounted;
   - otherwise: AMD `.5` `/home/rlopez/data/archive/disk_steward/intel-4/` over an audited transfer path;
   - do not move to another hot SSD and call it a backup.
4. Create pre-migration restore point and backup manifest.
5. Stage `rsync --dry-run --checksum` to target archive.
6. Only after owner approval: execute transfer, verify hashes, then delete source only after successful verification and retention confirmation.
7. Re-run AG-37 and verify `/mnt/datos_agentes` free space returns above warning threshold.

## Verification Performed

- New focused tests: `platform/tests/test_disk_steward_policy.py` — PASS, 5 tests.
- New focused tests: `platform/tests/test_restore_points.py` — PASS, 3 tests.
- `py_compile` for modified/new runtime modules — PASS.
- AG-37 live smoke on Intel `.4` with no WhatsApp send — PASS; reports `overall=critical` and flags the large backup trees.
- Restore point smoke using temporary directory — PASS; create/list/plan works and plan remains approval-gated.

## Full Discover Note

A broad `unittest discover` of `platform/inneros_core_runtime/tests` was attempted and failed for ambient reasons unrelated to this patch:

- missing `httpx` in the selected Python environment;
- old tests expecting previous path/module layout such as `inneros_core_runtime/pool_agent_runners.py`.

Focused tests and compile checks for the changed surfaces passed.
