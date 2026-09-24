# Private Storage Boundaries

Status: Phase 01 contract.

## Boundary

Private candidate data belongs under `private/` for local development and is ignored by Git.
This includes resumes, PDFs, DOCX files, compensation data, answer snapshots,
browser sessions, screenshots, generated keyword-plan artifacts, SQLite databases, and credentials.

The example paths are defined in `config/storage.example.json`:

- Database: `private/db/space.sqlite3`
- Artifacts: `private/artifacts`
- Sessions: `private/sessions`
- Screenshots: `private/screenshots`

## Secrets

No secret store is configured in Phase 01 because live integrations are disabled. A later
phase must choose an OS secret store or approved secret manager before credentials, tokens,
or browser sessions are used.

## Backups

Backups are not configured in Phase 01. Later backup rules must keep private data out of the
repository and document retention, export, deletion, and recovery behavior.

