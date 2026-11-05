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
```

The backend service account needs read/write access to `BACKUP_ROOT` and the medical storage directory. Restrict `BACKUP_ROOT` and the service account's temporary directory to that service account because they contain protected data and transient MySQL credentials. Install or configure the MySQL client binaries on the backend host. Backup and restore run synchronously; while they run, record creation/updates and file uploads return a retryable conflict. Restore replaces the active database and file tree after creating a safety backup.
