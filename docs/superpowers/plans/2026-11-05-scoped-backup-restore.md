# Scoped Backup and Restore Implementation Plan

> **For agentic workers:** Execute sequentially in the current workspace. Do not run tests unless explicitly requested; use compile/build checks and inspect safety-sensitive flows.

**Goal:** Back up only the declared HospitalData components and restore them without removing unrelated directories.

**Architecture:** Backend writes version 2 ZIP archives with a scoped allowlist and validates both new and legacy archives. Restore replaces only the five department directories; optional quarantine and application logs are copied into separate per-restore folders. React adds unchecked restore choices for those two components.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Python standard library, React, Vite.

**Spec:** `docs/superpowers/specs/2026-11-05-scoped-backup-restore-design.md`

## Global Constraints

- Exclude `Backup\Incoming`, `Backup\Repository`, and `RestoreTest` from both backup and restore.
- Include the five department trees, including empty directories.
- Back up Quarantine and ApplicationLogs separately; restore each only by explicit selection and only into its own isolated destination.
- Preserve archive checksum, manifest validation, safe paths, symlink/junction rejection, and legacy v1 restore support.
- Do not change MySQL credentials, role permissions, or record/file API behavior.

## Review Focus

- Restore must leave excluded paths byte-for-byte untouched.
- Quarantine files must never be placed under an active department.
- Empty folders must be present in the archive and after restore.
- Legacy v1 archives must still pass validation and restore only eligible department entries.
- A partial selected restore must remove its isolated log/quarantine output before safety rollback.

## Tasks

### Task 1: Version 2 scoped archive writer and reader

**Files:** Modify `backend/app/core/backup.py`.

- [x] Define explicit included and excluded storage paths.
- [x] Write department folders, quarantine, application logs, backup metadata, and a v2 manifest with entry type/path/size/SHA-256.
- [x] Include empty directories and use `hospital-backup-{id}.zip` / `hospital-safety-{id}.zip` names.
- [x] Validate v2 structure while preserving v1 manifest compatibility.
- [x] Verify generated path logic, manifest membership, and legacy branch by code inspection.

### Task 2: Scoped restore application and rollback

**Files:** Modify `backend/app/core/backup.py`, `backend/app/schemas/backups.py`, `backend/app/api/backups.py`.

- [x] Replace only the five department directories; preserve every excluded and unrelated path.
- [x] Add default-false restore flags for quarantine and application logs.
- [x] Stage optional data under unique names in their own destination trees; clean partial outputs on failure.
- [x] Keep rollback behavior gated on database import start and restore database plus department directories only.
- [x] Verify rollback and path safety by code inspection.

### Task 3: Restore choices and documentation

**Files:** Modify `frontend/src/api.js`, `frontend/src/BackupPage.jsx`, `frontend/src/styles.css`, `frontend/README.md`.

- [x] Add unchecked quarantine/log checkboxes and send explicit selections in restore requests.
- [x] Explain isolated restore destinations in the confirmation UI.
- [x] Document included/excluded paths and archive v2 layout.
- [x] Run backend `compileall`, `git diff --check`, and frontend production build.

## Execution

The user selected sequential inline implementation and approved the scope in the request and follow-up choice. Keep changes in the current workspace.
