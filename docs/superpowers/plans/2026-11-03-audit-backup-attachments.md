# Audit, Backup, Restore, and Record Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add permission-gated audit and complete database/file backup screens and APIs, plus optional PDF upload during record creation.

**Architecture:** FastAPI adds paginated audit and backup-job routes. A backend backup service calls configured MySQL client tools and builds validated ZIP archives under a server-only root; React consumes those APIs and adds separate audit and backup views. Record creation continues using the current endpoints and uploads the optional PDF immediately after metadata creation.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, MySQL 8 `mysqldump`/`mysql`, Python standard library, React 19, Vite 8.

**Spec:** `docs/superpowers/specs/2026-11-03-audit-backup-attachments-design.md`

## Global Constraints

- The backup includes the MySQL database and medical-file storage; `BACKUP_ROOT` defaults to `D:\HospitalBackups`.
- Only server configuration supplies backup root and MySQL executable paths; API clients supply a backup job ID, never a filesystem path.
- Restore requires `restore:execute`, explicit confirmation, archive validation, and a full pre-restore safety backup.
- UI actions are shown only for existing permissions; backend dependencies enforce permissions independently.
- File upload limits and allowed types remain those in `backend/app/core/file_storage.py`.
- Do not add dependencies unless the implementation requires one; use existing Python and browser standard libraries.

## Review Focus

- Invalid, corrupt, or path-traversal ZIP data is rejected before restore; cover the archive validator in the backup service's manual verification checklist.
- Failed restore attempts use the safety archive for rollback and retain a clear failed job state; cover a controlled invalid-SQL restore attempt in backend integration verification only if a disposable database is available.
- A selected PDF upload failure does not repeat record creation; cover the partial-success path in the UI review.
- Roles without records access can still land on their permitted audit or backup page; cover with each seeded role during UI review if the backend is available.
- Missing MySQL executable or unwritable backup root produces a failed job with a clear message; cover these configuration errors in service verification.

---

## File Structure

- Create `backend/app/schemas/audit.py` for audit response and paginated-list schemas.
- Create `backend/app/api/audit.py` for permission-checked audit listing and filters.
- Create `backend/app/schemas/backups.py` for backup-job and restore-request schemas.
- Create `backend/app/core/backup.py` for archive creation, validation, restore, rollback, checksums, and MySQL subprocess setup.
- Create `backend/app/api/backups.py` for job listing, backup execution, and confirmed restore endpoints.
- Modify `backend/app/core/config.py`, `backend/.env.example`, and `backend/app/main.py` for backup configuration and router registration.
- Modify `frontend/src/api.js` for audit/backup endpoints and response handling.
- Modify `frontend/src/App.jsx` for permission-aware navigation, pages, and sequential record-plus-PDF creation.
- Create `frontend/src/AuditPage.jsx` and `frontend/src/BackupPage.jsx` for focused list/filter/action UI.
- Modify `frontend/src/styles.css` and `frontend/README.md` for responsive views and runtime configuration.

## Task 1: Audit Log API

**Interfaces:** `GET /api/v1/audit-logs` returns `{items, total, limit, offset}`; accepts `limit` (1–100), `offset` (0+), optional exact `action` and `outcome`; requires `audit:read`.

- [x] Add Pydantic schemas exposing ID, actor ID/name, action, resource type/ID, outcome, IP, and timestamp. Do not expose `details`.
- [x] Implement the endpoint with `AuditLog` joined to `User`, newest-first ordering by timestamp then ID, count query, and the stated filters.
- [x] Register the router in `backend/app/main.py` under `/api/v1`.
- [x] Check the route/schema imports with `python -m compileall app` from `backend`.

## Task 2: Backup Archive Service and API

**Interfaces:** `create_backup(db, job_type) -> BackupJob`; `restore_backup(db, backup_job_id, confirm) -> BackupJob`; `GET /api/v1/backups` returns `{items, total, limit, offset}`; POST create and restore return the completed job. Backup routes require `backup:read`/`backup:execute`/`restore:execute` respectively.

- [x] Add `backup_root`, `mysqldump_path`, and `mysql_path` settings with defaults and document equivalent environment variables in `.env.example`.
- [x] Implement a server-generated temporary MySQL defaults file in the service account's OS temporary directory, subprocess invocation with argument arrays and no shell, and cleanup on both success and failure.
- [x] Create a ZIP with `database.sql`, the `storage_root` tree, and a versioned JSON manifest containing per-entry SHA-256 checksums; exclude `backup_jobs` from the SQL snapshot so active job history survives restoration.
- [x] Record a `BackupJob` before work begins, update `started_at`, `finished_at`, status, destination, byte count, checksum, and a sanitized failure message; list job records newest-first with pagination.
- [x] Resolve restore archives only from successful backup jobs whose resolved path stays under `backup_root`; validate manifest, checksums, archive members, and staging paths before changing live data.
- [x] For restore, create a full safety archive first, stage the selected file tree, import its SQL with configured `mysql`, replace the storage tree, and attempt safety-archive rollback if either application step fails. Require `confirm is True`.
- [x] Serialize backup/restore jobs and record/file writes with a MySQL advisory lock; record creation, record updates, and uploads return a clear conflict while the lock is held.
- [x] Register the backup router in `main.py`; ensure backup and restore events use existing audit logging without recording secrets or SQL contents.
- [x] Run `python -m compileall app` from `backend`; inspect the generated help/version output of the configured MySQL tools without connecting to or changing the live database.

## Task 3: React Audit and Backup Views

**Interfaces:** `AuditPage` receives `token`; `BackupPage` receives `token`, `permissions`, and `onError`; API helpers return JSON objects matching Task 1 and Task 2.

- [x] Add `getAuditLogs`, `getBackupJobs`, `createBackup`, and `restoreBackup` helpers to `frontend/src/api.js`.
- [x] Add audit view with action/outcome filters, paging, actor and timestamp display, and clear loading/empty/error states.
- [x] Add backup view with paginated jobs, status, created time, archive size/checksum, permission-gated create action, and a confirmation dialog for restore-capable users.
- [x] Update `App.jsx` navigation to show sections according to permissions and default users without `records:read` to their first permitted section.
- [x] Add responsive styles and update README with required backup folder permissions and MySQL path configuration.
- [x] Run `npm run build` from `frontend`; responsive styles included for narrow screens.

## Task 4: PDF Attachment During Record Creation

**Interfaces:** `RecordModal` returns record fields plus an optional PDF `File`; existing `createRecord` and `uploadFile` helpers remain unchanged.

- [x] Add an optional PDF file input to the create form with a 10 MB client-side size check; leave edit mode unchanged.
- [x] After successful record creation, immediately upload the selected file to the created record ID.
- [x] Update the records list as soon as creation succeeds; on upload failure, close/reset the create form, preserve the new record, show its ID and upload failure, and leave the existing row upload control available for retry.
- [x] Run `npm run build` from `frontend`; reviewed the create/upload state flow in code without creating a record.

## Task 5: End-to-End Review

- [x] Re-read the spec and confirm each goal and non-goal is represented in Tasks 1–4.
- [x] Review restore path validation, pre-restore backup, rollback errors, authorization, and client confirmation in the actual diff; a reviewer found and prompted fixes for maintenance 409 messaging, upload permission visibility, and unsupported storage paths.
- [x] Run `python -m compileall app` from `backend` and `npm run build` from `frontend`; database-dependent backup/restore could not be exercised without connecting to the application database.
