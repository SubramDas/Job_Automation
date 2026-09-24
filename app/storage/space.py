"""Local Space persistence for Phase 03.

The database is a single-user SQLite store. It keeps private data under the configured
private root and preserves version/history records so agents can propose changes without
silently confirming candidate facts.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "2026-09-23.phase03"


class SpaceError(ValueError):
    """Raised when a Space operation violates Phase 03 policy."""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class SpacePaths:
    private_root: Path
    database: Path
    artifacts: Path

    @classmethod
    def from_project_root(cls, project_root: Path) -> SpacePaths:
        private_root = project_root / "private"
        return cls(
            private_root=private_root,
            database=private_root / "db" / "space.sqlite3",
            artifacts=private_root / "artifacts",
        )


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    version: int
    sha256: str
    content_type: str
    size_bytes: int
    owner: str
    path: Path
    created_at: str


class ArtifactStore:
    """Immutable private artifact storage with opaque IDs and content hashes."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put_file(self, source: Path, *, content_type: str, owner: str, artifact_id: str | None = None) -> ArtifactRecord:
        if not source.is_file():
            raise SpaceError(f"artifact source is not a file: {source}")
        payload = source.read_bytes()
        return self.put_bytes(
            payload,
            filename=source.name,
            content_type=content_type,
            owner=owner,
            artifact_id=artifact_id,
        )

    def put_bytes(
        self,
        payload: bytes,
        *,
        filename: str,
        content_type: str,
        owner: str,
        artifact_id: str | None = None,
    ) -> ArtifactRecord:
        if not payload:
            raise SpaceError("artifact payload is empty")
        artifact_id = artifact_id or new_id("artifact")
        version = self._next_version(artifact_id)
        sha256 = hashlib.sha256(payload).hexdigest()
        suffix = Path(filename).suffix.lower() or ".bin"
        created_at = utc_now()
        target_dir = self.root / artifact_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"v{version}{suffix}"
        if target.exists():
            raise SpaceError(f"artifact version already exists: {artifact_id} v{version}")
        target.write_bytes(payload)
        return ArtifactRecord(
            artifact_id=artifact_id,
            version=version,
            sha256=sha256,
            content_type=content_type,
            size_bytes=len(payload),
            owner=owner,
            path=target,
            created_at=created_at,
        )

    def _next_version(self, artifact_id: str) -> int:
        artifact_dir = self.root / artifact_id
        if not artifact_dir.exists():
            return 1
        versions = []
        for child in artifact_dir.iterdir():
            if child.name.startswith("v"):
                stem = child.stem.removeprefix("v")
                if stem.isdigit():
                    versions.append(int(stem))
        return max(versions, default=0) + 1


class SpaceStore:
    """Repository for private profile, answer, job, and application records."""

    def __init__(self, paths: SpacePaths) -> None:
        self.paths = paths
        self.artifacts = ArtifactStore(paths.artifacts)

    def connect(self) -> sqlite3.Connection:
        self.paths.database.parent.mkdir(parents=True, exist_ok=True)
        self.paths.artifacts.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.paths.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version TEXT PRIMARY KEY,
                  applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                  id TEXT NOT NULL,
                  version INTEGER NOT NULL,
                  sha256 TEXT NOT NULL,
                  content_type TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL,
                  owner TEXT NOT NULL,
                  storage_path TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  immutable INTEGER NOT NULL DEFAULT 1,
                  PRIMARY KEY (id, version),
                  UNIQUE (sha256, owner)
                );

                CREATE TABLE IF NOT EXISTS candidate_facts (
                  id TEXT PRIMARY KEY,
                  field_key TEXT NOT NULL,
                  value_type TEXT NOT NULL,
                  value_json TEXT NOT NULL,
                  source_ref TEXT NOT NULL,
                  source_span_json TEXT,
                  provenance_json TEXT NOT NULL,
                  confirmation_state TEXT NOT NULL
                    CHECK (confirmation_state IN ('proposed','confirmed','rejected','superseded')),
                  sensitivity TEXT NOT NULL CHECK (sensitivity IN ('public','private','sensitive')),
                  created_by TEXT NOT NULL CHECK (created_by IN ('user','agent','import')),
                  version INTEGER NOT NULL,
                  supersedes_id TEXT REFERENCES candidate_facts(id),
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_candidate_facts_field ON candidate_facts(field_key);

                CREATE TABLE IF NOT EXISTS fact_history (
                  id TEXT PRIMARY KEY,
                  fact_id TEXT NOT NULL REFERENCES candidate_facts(id),
                  old_state TEXT,
                  new_state TEXT NOT NULL,
                  actor TEXT NOT NULL,
                  reason TEXT,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preference_policies (
                  id TEXT PRIMARY KEY,
                  version INTEGER NOT NULL UNIQUE,
                  hard_constraints_json TEXT NOT NULL,
                  weighted_preferences_json TEXT NOT NULL,
                  exclusions_json TEXT NOT NULL,
                  created_by TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS prior_applications (
                  id TEXT PRIMARY KEY,
                  company TEXT NOT NULL,
                  role TEXT NOT NULL,
                  applied_on TEXT,
                  source_ids_json TEXT NOT NULL,
                  destination TEXT,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reusable_answers (
                  id TEXT PRIMARY KEY,
                  semantic_key TEXT NOT NULL,
                  original_question TEXT NOT NULL,
                  typed_value_json TEXT NOT NULL,
                  unit TEXT,
                  scope_json TEXT NOT NULL,
                  confirmation_state TEXT NOT NULL,
                  expires_at TEXT,
                  sensitivity TEXT NOT NULL,
                  reuse_permission TEXT NOT NULL,
                  provenance_json TEXT NOT NULL,
                  version INTEGER NOT NULL,
                  supersedes_id TEXT REFERENCES reusable_answers(id),
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reusable_answers_key ON reusable_answers(semantic_key);

                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  canonical_url TEXT,
                  employer TEXT,
                  requisition_id TEXT,
                  title TEXT,
                  normalized_identity TEXT NOT NULL,
                  description_hash TEXT NOT NULL,
                  retrieved_at TEXT NOT NULL,
                  status TEXT NOT NULL,
                  snapshot_artifact_id TEXT,
                  created_at TEXT NOT NULL,
                  UNIQUE (canonical_url),
                  UNIQUE (employer, requisition_id),
                  UNIQUE (normalized_identity, description_hash)
                );

                CREATE TABLE IF NOT EXISTS job_source_ids (
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  source_id TEXT NOT NULL,
                  PRIMARY KEY (job_id, source_id),
                  UNIQUE (source_id)
                );

                CREATE TABLE IF NOT EXISTS job_extractions (
                  id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  extraction_json TEXT NOT NULL,
                  evidence_json TEXT NOT NULL,
                  warnings_json TEXT NOT NULL,
                  unknown_fields_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_duplicate_signals (
                  id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  signal_type TEXT NOT NULL,
                  signal_value TEXT NOT NULL,
                  matched_job_id TEXT,
                  risk TEXT NOT NULL CHECK (risk IN ('exact','ambiguous','none')),
                  details_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_job_duplicate_signals_job
                  ON job_duplicate_signals(job_id);

                CREATE TABLE IF NOT EXISTS match_results (
                  id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  policy_version INTEGER,
                  profile_version INTEGER NOT NULL,
                  hard_filter_results_json TEXT NOT NULL,
                  preference_scores_json TEXT NOT NULL,
                  score REAL,
                  coverage_json TEXT NOT NULL,
                  decision TEXT NOT NULL,
                  gaps_json TEXT NOT NULL,
                  review_reasons_json TEXT NOT NULL,
                  explanation_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_match_results_job ON match_results(job_id);

                CREATE TABLE IF NOT EXISTS b_to_a_handoffs (
                  id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  match_result_id TEXT NOT NULL REFERENCES match_results(id),
                  payload_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_keyword_plans (
                  id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                  artifact_id TEXT NOT NULL,
                  artifact_sha256 TEXT NOT NULL,
                  description_hash TEXT NOT NULL,
                  model_json TEXT NOT NULL,
                  priority_counts_json TEXT NOT NULL,
                  mandate_counts_json TEXT NOT NULL,
                  warnings_json TEXT NOT NULL,
                  validation_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_job_keyword_plans_job
                  ON job_keyword_plans(job_id);

                CREATE TABLE IF NOT EXISTS agent_b_review_actions (
                  id TEXT PRIMARY KEY,
                  run_id TEXT,
                  job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
                  action TEXT NOT NULL
                    CHECK (action IN ('accept_shortlist','reject_job','mark_duplicate',
                                      'request_manual_import','label')),
                  label TEXT CHECK (label IN ('yes','maybe','no') OR label IS NULL),
                  reason TEXT,
                  source_feedback_json TEXT NOT NULL,
                  actor TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_b_review_actions_job
                  ON agent_b_review_actions(job_id);

                CREATE TABLE IF NOT EXISTS applications (
                  id TEXT PRIMARY KEY,
                  durable_identity TEXT NOT NULL UNIQUE,
                  state TEXT NOT NULL,
                  job_snapshot TEXT NOT NULL,
                  resume_snapshot TEXT,
                  answer_snapshot_json TEXT NOT NULL,
                  authorization_version TEXT,
                  profile_version INTEGER,
                  preference_version INTEGER,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_questions (
                  id TEXT PRIMARY KEY,
                  application_id TEXT REFERENCES applications(id),
                  field_context_json TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  suggested_reuse_scope_json TEXT,
                  status TEXT NOT NULL,
                  answer_ref TEXT REFERENCES reusable_answers(id),
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS answer_snapshots (
                  id TEXT PRIMARY KEY,
                  application_id TEXT NOT NULL REFERENCES applications(id),
                  answer_ids_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS application_checkpoints (
                  id TEXT PRIMARY KEY,
                  application_id TEXT NOT NULL REFERENCES applications(id),
                  stage TEXT NOT NULL,
                  checkpoint_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS invalidation_events (
                  id TEXT PRIMARY KEY,
                  reason TEXT NOT NULL,
                  affected_record_type TEXT NOT NULL,
                  affected_record_id TEXT NOT NULL,
                  source_record_type TEXT NOT NULL,
                  source_record_id TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                  id TEXT PRIMARY KEY,
                  actor TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  subject_type TEXT NOT NULL,
                  subject_id TEXT NOT NULL,
                  details_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )

    def record_artifact(self, artifact: ArtifactRecord) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO artifacts
                  (id, version, sha256, content_type, size_bytes, owner, storage_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.version,
                    artifact.sha256,
                    artifact.content_type,
                    artifact.size_bytes,
                    artifact.owner,
                    str(artifact.path),
                    artifact.created_at,
                ),
            )

    def backup(self, backup_dir: Path) -> Path:
        if not self.paths.database.exists():
            raise SpaceError("cannot back up before the database exists")
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"space-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        shutil.copy2(self.paths.database, target)
        return target

    def restore(self, backup_path: Path) -> None:
        if not backup_path.is_file():
            raise SpaceError(f"backup does not exist: {backup_path}")
        self.paths.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup_path) as source:
            result = source.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise SpaceError("backup failed SQLite integrity check")
        shutil.copy2(backup_path, self.paths.database)

    def export_profile(self) -> dict[str, Any]:
        with self.connect() as db:
            facts = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, field_key, value_type, value_json, source_ref, provenance_json,
                           confirmation_state, sensitivity, version, created_at, updated_at
                    FROM candidate_facts
                    ORDER BY field_key, created_at
                    """
                )
            ]
            policies = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, version, hard_constraints_json, weighted_preferences_json,
                           exclusions_json, created_at
                    FROM preference_policies
                    ORDER BY version
                    """
                )
            ]
            answers = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, semantic_key, original_question, typed_value_json, unit,
                           scope_json, confirmation_state, expires_at, sensitivity,
                           reuse_permission, version, created_at, updated_at
                    FROM reusable_answers
                    ORDER BY semantic_key, created_at
                    """
                )
            ]
        return {
            "schema_version": SCHEMA_VERSION,
            "exported_at": utc_now(),
            "candidate_facts": facts,
            "preference_policies": policies,
            "reusable_answers": answers,
        }

    def delete_private_data(self) -> None:
        if self.paths.private_root.exists():
            shutil.rmtree(self.paths.private_root)
