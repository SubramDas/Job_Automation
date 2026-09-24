# Contributor Notes: Agent A Keyword Package

`AGENT.md` is the canonical runtime reference for Agent A. Keep this package scoped to job-description keyword extraction, priority ranking, artifact persistence, and handoff of the keyword plan.

Shared contracts live in `app/core/contracts.py`, `schemas/`, and the Phase 01 decision records. Do not duplicate broad project policy here; point to the canonical runtime file and update the Phase 02 validator when package structure changes.

Use fictional data in examples. Real job descriptions and generated keyword artifacts belong under `private/` and must stay out of version control.
