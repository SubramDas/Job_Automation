# Private Storage Boundaries

Status: Phase 01 contract.

## Boundary

Private candidate data belongs under `private/` for local development and is ignored by Git.
This includes resumes, PDFs, DOCX files, compensation data, answer snapshots,
browser sessions, screenshots, generated keyword-plan artifacts, SQLite databases, and credentials.

The example paths are defined in `config/storage.example.json`:

- Database: `private/db/space.sqlite3`
- Artifacts: `private/artifacts`
- Human-readable job review workspace: `private/job_reviews`
- Sessions: `private/sessions`
- Screenshots: `private/screenshots`

## Job Review Workspace

Agent B's immutable job-description snapshots and run reports live in the artifact store so
they can be hashed, versioned, deduplicated, and linked to downstream Agent A/C work.
Those artifact IDs are intentionally opaque, but they are not pleasant for manual review.

Add a generated review layer under `private/job_reviews/`:

```text
private/job_reviews/
  index.md
  <company-slug>/
    <job-title-slug>__<job-id-short>/
      job-details.md
      job-description.txt
      extracted.json
```

The review workspace is a convenience copy, not the source of truth. Folder names must be
sanitized labels and must include a stable job-ID suffix to avoid collisions between
same-company/same-title roles, reposts, locations, and cross-board duplicates. Do not use
company and title alone as durable identity.

`job-details.md` should be the user's normal entry point for a job: source links,
application destination, match decision, score, warnings, unknown fields, duplicate signals,
freshness, extracted fields, and references back to `job_id`, `snapshot_artifact_id`, and
description hash. `job-description.txt` should contain the exact description text used by
the extractor and matcher, copied from the immutable snapshot.

Regenerating `private/job_reviews/` may update readable files for the same job ID, but must
not delete or mutate database rows, immutable artifacts, keyword-plan artifacts, audit
events, or historical match records.

## Secrets

No secret store is configured in Phase 01 because live integrations are disabled. A later
phase must choose an OS secret store or approved secret manager before credentials, tokens,
or browser sessions are used.

## Backups

Backups are not configured in Phase 01. Later backup rules must keep private data out of the
repository and document retention, export, deletion, and recovery behavior.
