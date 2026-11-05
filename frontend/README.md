# MedVault frontend

React 19 + Vite interface for the FastAPI hospital records backend.

## Run locally

1. Start the backend from `backend` with its environment configured and run Uvicorn on port `8000`.
2. In this directory, install dependencies and start Vite:

   ```powershell
   npm install
   npm run dev
   ```

3. Open the local URL printed by Vite. The development server proxies `/api` and `/health` to `http://127.0.0.1:8000`. Set `VITE_BACKEND_URL` in a local `.env` file to use another backend address.

For a separately hosted frontend, set `VITE_API_BASE_URL` to the backend API base URL (for example, `https://api.example.com/api/v1`). The backend must allow that origin through CORS.

## Included screens and actions

- JWT login and current-user profile, with permission-aware controls.
- Searchable, filterable medical-record list scoped by backend permissions and department.
- Create and update records using the existing API fields.
- Upload allowed PDF, PNG, JPEG, TXT, and CSV files up to 10 MB, and download uploads during the current browser session.

The backend does not expose a list-files endpoint, so uploads from earlier sessions cannot be shown in the records view. User management is not included because corresponding APIs are not available.

## Backup and restore configuration

The audit and backup pages appear only for accounts with the matching backend permission. Set these backend values in `backend/.env` (copy the keys from `.env.example`):

```dotenv
BACKUP_ROOT=D:\HospitalBackups
MYSQLDUMP_PATH=C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe
MYSQL_PATH=C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe
MYSQL_RESTORE_USER=hospital_restore
MYSQL_RESTORE_PASSWORD=replace_with_restore_password
```

Use a dedicated MySQL account for `MYSQL_RESTORE_USER` rather than granting restore privileges to the normal application account. It must be allowed to execute the statements in the SQL dump for `DB_NAME` (including creating, dropping, and altering schema objects). For example, a database administrator can grant the required database-level privileges on `hospital_storage.*` to this account; the MySQL account's host portion must match the backend's connection source. The normal `DB_USER` continues to be used for the application and database export. Keep the restore password secret in `backend/.env` and out of source control.

The backend service account needs read/write access to `BACKUP_ROOT` and the medical storage directory. Restrict `BACKUP_ROOT` and the service account's temporary directory to that service account because they contain protected data and transient MySQL credentials. Install or configure the MySQL client binaries on the backend host. Backup and restore run synchronously; while they run, record creation/updates and file uploads return a retryable conflict.

### Backup archive contents

Format version 2 archives use `hospital-backup-{id}.zip` (safety copies use `hospital-safety-{id}.zip`) and contain `database.sql`, `metadata/manifest.json`, and `logs/backup_metadata.json`. The manifest records paths, entry types, sizes, and SHA-256 checksums.

- `files/Clinical`, `files/Laboratory`, `files/Imaging`, `files/Administration`, and `files/HR` are included, including empty directories.
- `quarantine/` and `logs/application/` are included as separate components.
- `Backup/Incoming`, `Backup/Repository`, `RestoreTest`, and other storage paths are excluded.

Restore replaces the database and only the five department directories. It preserves excluded and unrelated folders. Quarantine and application logs remain untouched unless selected in the confirmation dialog; selected contents are copied to unique `RestoredFromBackup-{restore_job_id}` subfolders under their own component. Quarantine files are never restored into an active department. The reader continues to support existing format version 1 archives.
