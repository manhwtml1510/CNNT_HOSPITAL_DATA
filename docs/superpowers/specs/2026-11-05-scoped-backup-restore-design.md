# Scoped Backup and Restore Design

## Goal

Make archive contents explicit and prevent restore from replacing unrelated data under `STORAGE_ROOT`.

## Included and excluded paths

| Storage path | Backup | Restore behavior |
| --- | --- | --- |
| `Clinical`, `Laboratory`, `Imaging`, `Administration`, `HR` | Yes, including nested files and empty directories | Replace only these five department directories |
| `Quarantine` | Yes, under its own archive component | Optional checkbox; copy selected contents to `Quarantine\RestoredFromBackup-{restore_job_id}` and never promote files into a department |
| `System\ApplicationLogs` | Yes, under its own archive component | Optional checkbox; copy selected contents to `System\ApplicationLogs\RestoredFromBackup-{restore_job_id}` |
| `Backup\Incoming`, `Backup\Repository` | No | Leave untouched |
| `RestoreTest` | No | Leave untouched |
| Other paths | No | Leave untouched |

Automatic safety rollback restores the database and the five department directories. Optional quarantine and log imports are staged in unique directories and removed if the selected restore fails, so rollback does not overwrite their original contents.

## Archive format

New archives use format version 2 and contain:

```text
database.sql
files/{Clinical,Laboratory,Imaging,Administration,HR}/...
quarantine/...
logs/application/...
logs/backup_metadata.json
metadata/manifest.json
```

All five department directories are represented even when empty. The manifest records relative paths, entry type, size, and SHA-256. Backup metadata records job ID/type, creation time, database name, system version, format version, and included/excluded components. New archive names are `hospital-backup-{id}.zip` and `hospital-safety-{id}.zip`.

The restore reader remains compatible with format version 1 archives using root `manifest.json` and `files/` paths. Legacy paths are classified by their relative storage path; excluded folders are never applied to the live root.

## API and UI

Restore requests keep `confirm: true` and add optional `restore_quarantine` and `restore_application_logs` booleans, both defaulting to false. The confirmation dialog shows two unchecked choices and states the separate restore destinations. Existing record/file APIs and role permissions do not change.

## Safety

- The archive contains only the declared components; backup staging remains outside `STORAGE_ROOT`.
- Restore replaces the five department directories individually and preserves all unrelated paths.
- Quarantine content is never restored into an active department.
- Manifest, archive checksum, path traversal checks, symlink/junction rejection, and per-file checksums remain enforced.
- A failed selected restore attempts safety rollback only after database application starts; any optional restore directories created for the attempt are cleaned up first.
