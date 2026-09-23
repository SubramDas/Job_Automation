# ADR-0001: Phase 01 Runtime Stack

Status: accepted for Phase 01.

Date: 2026-09-23.

## Decision

Use a local-first Python 3.12 CLI foundation with SQLite planned for Phase 03 and no runtime
third-party dependency in Phase 01. Configuration and contract validation use only the Python
standard library so the repository can validate on the user's laptop before provider,
dependency, and personal-data decisions are complete.

Optional development tooling is pinned in `requirements-dev.txt`:

- `pytest==9.1.1` for the later test runner, based on the current pytest documentation and
  changelog checked on 2026-09-23.
- `ruff==0.16.0` for linting and formatting, based on Astral's official Ruff docs/changelog
  checked on 2026-09-23.

## Rationale

Phase 00 selected local laptop operation, CLI-only review, synthetic data only, and no live
submission. A Python CLI keeps the MVP small while fitting document processing, deterministic
validation, SQLite, and future adapter work. Avoiding runtime dependencies in Phase 01 means
configuration validation can run even before `pip` is available locally.

## Consequences

- Phase 01 validation is deliberately modest: it checks startup configuration, source flags,
  dry-run policy, and storage boundaries.
- Later phases may add document, model, browser, and database dependencies behind explicit
  decisions and lock files.
- No application code in this phase processes real candidate data.

