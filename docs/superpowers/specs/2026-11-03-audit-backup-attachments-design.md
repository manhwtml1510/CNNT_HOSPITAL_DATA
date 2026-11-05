# Audit, Backup, Restore, and Record Attachments

## Intent

Complete the missing parts of the hospital workspace: let authorized staff review access history, create and restore complete database-plus-file backups, and attach a PDF while creating a record. The backend remains authoritative for department scope and permissions.

## Goals

- Show paginated, filterable audit history to users with `audit:read`.
- Create a verifiable archive of the MySQL database and configured medical-file storage under `D:\HospitalBackups` by default.
- List backup/restore jobs, and restore a selected valid archive only after creating a pre-restore backup and receiving explicit confirmation.
- Allow one optional PDF (within the existing 10 MB upload limit) in the create-record form.
- Keep the existing record and file APIs compatible.

## Non-goals

- Scheduled backups, off-site replication, user management, audit-log mutation, or new backup destinations selected by browser input.
- Restoring into a different database/schema or different storage root.
- Making record creation and file upload a single database transaction. The existing API separates them, so the UI must explain a partial result and provide a retry path without creating a duplicate record.

## Constraints and safety

- Use existing role permissions: `audit:read`, `backup:read`, `backup:execute`, and `restore:execute`.
- Keep MySQL credentials server-side; invoke configured `mysqldump`/`mysql` executables without a shell and pass credentials through a temporary defaults file in the backend service account's private OS temporary directory.
- Configure `BACKUP_ROOT` (default `D:\HospitalBackups`), `MYSQLDUMP_PATH`, and `MYSQL_PATH`; never accept a filesystem path from a client.
- A backup ZIP contains a database SQL dump, the file-storage tree, and a manifest with format version and checksums. Store archive checksum and destination in `BackupJob`.
- Validate archive format/checksums and reject paths that escape the staging directory before restoring. Resolve a backup only by its database job ID and ensure its archive path remains under `BACKUP_ROOT`.
- Before restore, create a full safety archive of current database and files. If applying the selected archive fails, attempt to restore that safety archive and mark the restore job failed. Require a confirmation field on the API and a clear confirmation dialog in the UI.
- Backup and restore execute synchronously in the first version; report success/failure and elapsed job fields through `BackupJob`.
- Serialize backup/restore jobs and record/file writes through a MySQL advisory lock. Record creation, record updates, and file uploads fail fast with a retryable conflict while backup or restore is running.
- Create the database snapshot before copying the file tree. The current upload route writes file bytes before committing file metadata and there is no delete endpoint, so an upload concurrent with a backup can leave an extra unreferenced file in the archive, but a committed metadata row will still have its file. Out-of-band file mutations are outside this guarantee.
- Restore replaces the complete active storage tree. Files created after the selected archive are removed from the active tree but preserved in the pre-restore safety archive.
- Stage and validate restore files before applying database changes, then swap the file store; on failure, use the safety archive for rollback and report any rollback failure clearly.
- Create a `running` job before the synchronous work and update it on completion. If the client loses its response, the caller can refresh the job list to see the result; a reverse proxy with shorter request timeouts is not part of the current local setup.

## Approaches

1. **MySQL-native dump plus file archive (chosen).** Use `mysqldump` and `mysql`, bundle the SQL and storage tree, and restore only validated archives. This matches the backend's MySQL database, produces a standard SQL dump, and supports a complete recovery. It requires the MySQL client binaries to be configured on the backend host.
2. **Application-level table export.** Serialize all database tables through SQLAlchemy and bundle the files. This avoids client executables, but duplicates database schema, ordering, and type-conversion behavior in application code and is less portable as the schema evolves.
3. **Frontend-only views.** Expose existing database rows without real backup or restore operations. This would present controls that cannot protect or recover data, so it does not meet the request.

## API and interface

- `GET /api/v1/audit-logs?limit=50&offset=0&action=&outcome=` requires `audit:read`; returns audit ID, actor username/ID, action, resource type/ID, outcome, IP, and timestamp, plus pagination metadata.
- `GET /api/v1/backups?limit=50&offset=0` requires `backup:read`; returns `BackupJob` fields and whether a successful archive exists.
- `POST /api/v1/backups` requires `backup:execute`; creates a job, writes the archive under `BACKUP_ROOT`, and records size, checksum, timestamps, and outcome.
- `POST /api/v1/backups/{job_id}/restore` requires `restore:execute` and JSON `{ "confirm": true }`; creates a safety backup, validates the selected successful backup, restores database and files, and records outcome.
- For record creation, the frontend first calls existing `POST /records`, then uploads the optional PDF through existing `POST /files/records/{record_id}`. If upload fails, retain the created record in the list and show its ID with the existing upload control as a retry path.
- Add audit and backup/restore pages to React navigation only when the current user has matching permissions. Restore prompts for explicit confirmation. Existing API errors and denied permissions remain visible without clearing a valid session.

## Implementation calls left to the builder

- Use a dedicated archive manifest and SHA-256 verification; keep archive staging under the configured backup root and MySQL credential files in the OS temporary directory whose ACL is restricted to the backend service account.
- Return actor username by joining `audit_logs.actor_user_id` to `users.id`; do not return `details` by default because it can later contain sensitive metadata.
- Keep the job list bounded and paginated. Do not add a browser download endpoint for backup archives in this iteration.
- Update backend `.env.example` and frontend README with required paths, runtime permissions for the backup folder, and the synchronous nature of backup/restore.
