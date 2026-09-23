"""Phase 03 onboarding and profile operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.storage.space import SpaceError, SpaceStore, new_id, stable_json, utc_now

USER_ACTORS = {"user"}
PROPOSAL_ACTORS = {"agent", "import"}


@dataclass(frozen=True)
class FactProposal:
    fact_id: str
    field_key: str
    value_type: str
    value: Any
    source_ref: str
    confirmation_state: str


class OnboardingService:
    """Controlled writes for facts, preferences, answers, and review queues."""

    def __init__(self, store: SpaceStore) -> None:
        self.store = store

    def propose_fact(
        self,
        *,
        field_key: str,
        value_type: str,
        value: Any,
        source_ref: str,
        source_span: dict[str, Any] | None,
        provenance: dict[str, Any],
        sensitivity: str,
        actor: str,
    ) -> str:
        if actor not in PROPOSAL_ACTORS and actor not in USER_ACTORS:
            raise SpaceError("fact proposals must come from user, import, or agent workflow")
        state = "confirmed" if actor == "user" else "proposed"
        fact_id = new_id("fact")
        now = utc_now()
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO candidate_facts
                  (id, field_key, value_type, value_json, source_ref, source_span_json,
                   provenance_json, confirmation_state, sensitivity, created_by, version,
                   supersedes_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    fact_id,
                    field_key,
                    value_type,
                    stable_json(value),
                    source_ref,
                    stable_json(source_span) if source_span is not None else None,
                    stable_json(provenance),
                    state,
                    sensitivity,
                    actor,
                    1,
                    now,
                    now,
                ),
            )
            self._history(db, fact_id, None, state, actor, "fact created")
        return fact_id

    def set_fact_state(self, fact_id: str, *, state: str, actor: str, reason: str) -> None:
        if actor != "user":
            raise SpaceError("only the authenticated user workflow can confirm or reject facts")
        if state not in {"confirmed", "rejected"}:
            raise SpaceError("fact review state must be confirmed or rejected")
        now = utc_now()
        with self.store.connect() as db:
            current = db.execute(
                "SELECT confirmation_state FROM candidate_facts WHERE id = ?",
                (fact_id,),
            ).fetchone()
            if current is None:
                raise SpaceError(f"unknown fact: {fact_id}")
            db.execute(
                "UPDATE candidate_facts SET confirmation_state = ?, updated_at = ? WHERE id = ?",
                (state, now, fact_id),
            )
            self._history(db, fact_id, current["confirmation_state"], state, actor, reason)
            if state == "confirmed":
                self._invalidate_pending_for_profile_change(db, "candidate_fact", fact_id)

    def revise_fact(
        self,
        fact_id: str,
        *,
        value: Any,
        provenance: dict[str, Any],
        actor: str,
        reason: str,
    ) -> str:
        if actor != "user":
            raise SpaceError("only the authenticated user workflow can revise confirmed facts")
        now = utc_now()
        with self.store.connect() as db:
            old = db.execute("SELECT * FROM candidate_facts WHERE id = ?", (fact_id,)).fetchone()
            if old is None:
                raise SpaceError(f"unknown fact: {fact_id}")
            db.execute(
                """
                UPDATE candidate_facts
                SET confirmation_state = 'superseded', updated_at = ?
                WHERE id = ?
                """,
                (now, fact_id),
            )
            replacement_id = new_id("fact")
            db.execute(
                """
                INSERT INTO candidate_facts
                  (id, field_key, value_type, value_json, source_ref, source_span_json,
                   provenance_json, confirmation_state, sensitivity, created_by, version,
                   supersedes_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, 'user', ?, ?, ?, ?)
                """,
                (
                    replacement_id,
                    old["field_key"],
                    old["value_type"],
                    stable_json(value),
                    old["source_ref"],
                    old["source_span_json"],
                    stable_json(provenance),
                    old["sensitivity"],
                    old["version"] + 1,
                    fact_id,
                    now,
                    now,
                ),
            )
            self._history(db, fact_id, old["confirmation_state"], "superseded", actor, reason)
            self._history(db, replacement_id, None, "confirmed", actor, reason)
            self._invalidate_pending_for_profile_change(db, "candidate_fact", replacement_id)
        return replacement_id

    def list_facts(self, *, include_rejected: bool = False) -> list[FactProposal]:
        where = "" if include_rejected else "WHERE confirmation_state != 'rejected'"
        with self.store.connect() as db:
            rows = db.execute(
                f"""
                SELECT id, field_key, value_type, value_json, source_ref, confirmation_state
                FROM candidate_facts
                {where}
                ORDER BY field_key, created_at
                """
            ).fetchall()
        return [
            FactProposal(
                fact_id=row["id"],
                field_key=row["field_key"],
                value_type=row["value_type"],
                value=json.loads(row["value_json"]),
                source_ref=row["source_ref"],
                confirmation_state=row["confirmation_state"],
            )
            for row in rows
        ]

    def create_preference_policy(
        self,
        *,
        hard_constraints: list[dict[str, Any]],
        weighted_preferences: list[dict[str, Any]],
        exclusions: list[dict[str, Any]],
        actor: str,
    ) -> int:
        if actor != "user":
            raise SpaceError("only the authenticated user workflow can create preference policies")
        now = utc_now()
        with self.store.connect() as db:
            current = db.execute("SELECT COALESCE(MAX(version), 0) AS version FROM preference_policies").fetchone()
            version = int(current["version"]) + 1
            policy_id = new_id("policy")
            db.execute(
                """
                INSERT INTO preference_policies
                  (id, version, hard_constraints_json, weighted_preferences_json,
                   exclusions_json, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    version,
                    stable_json(hard_constraints),
                    stable_json(weighted_preferences),
                    stable_json(exclusions),
                    actor,
                    now,
                ),
            )
            self._invalidate_pending_for_profile_change(db, "preference_policy", policy_id)
        return version

    def import_prior_application(
        self,
        *,
        company: str,
        role: str,
        applied_on: str | None,
        source_ids: list[str],
        destination: str | None,
        status: str,
    ) -> str:
        application_id = new_id("priorapp")
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO prior_applications
                  (id, company, role, applied_on, source_ids_json, destination, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_id,
                    company,
                    role,
                    applied_on,
                    stable_json(source_ids),
                    destination,
                    status,
                    utc_now(),
                ),
            )
        return application_id

    def create_reusable_answer(
        self,
        *,
        semantic_key: str,
        original_question: str,
        typed_value: Any,
        unit: str | None,
        scope: dict[str, Any],
        sensitivity: str,
        reuse_permission: str,
        provenance: dict[str, Any],
        expires_at: str | None,
        actor: str,
    ) -> str:
        if actor != "user":
            raise SpaceError("only the authenticated user workflow can confirm reusable answers")
        answer_id = new_id("answer")
        now = utc_now()
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO reusable_answers
                  (id, semantic_key, original_question, typed_value_json, unit, scope_json,
                   confirmation_state, expires_at, sensitivity, reuse_permission,
                   provenance_json, version, supersedes_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, 1, NULL, ?, ?)
                """,
                (
                    answer_id,
                    semantic_key,
                    original_question,
                    stable_json(typed_value),
                    unit,
                    stable_json(scope),
                    expires_at,
                    sensitivity,
                    reuse_permission,
                    stable_json(provenance),
                    now,
                    now,
                ),
            )
        return answer_id

    def resolve_exact_answer(self, *, semantic_key: str, scope: dict[str, Any]) -> str | None:
        encoded_scope = stable_json(scope)
        with self.store.connect() as db:
            row = db.execute(
                """
                SELECT id FROM reusable_answers
                WHERE semantic_key = ?
                  AND scope_json = ?
                  AND confirmation_state = 'confirmed'
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY version DESC, created_at DESC
                LIMIT 1
                """,
                (semantic_key, encoded_scope, utc_now()),
            ).fetchone()
        return None if row is None else str(row["id"])

    def create_pending_question(
        self,
        *,
        application_id: str | None,
        field_context: dict[str, Any],
        reason: str,
        suggested_reuse_scope: dict[str, Any] | None,
    ) -> str:
        question_id = new_id("question")
        now = utc_now()
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO pending_questions
                  (id, application_id, field_context_json, reason, suggested_reuse_scope_json,
                   status, answer_ref, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'open', NULL, ?, ?)
                """,
                (
                    question_id,
                    application_id,
                    stable_json(field_context),
                    reason,
                    stable_json(suggested_reuse_scope) if suggested_reuse_scope is not None else None,
                    now,
                    now,
                ),
            )
        return question_id

    def save_checkpoint(self, *, application_id: str, stage: str, checkpoint: dict[str, Any]) -> str:
        checkpoint_id = new_id("checkpoint")
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO application_checkpoints
                  (id, application_id, stage, checkpoint_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (checkpoint_id, application_id, stage, stable_json(checkpoint), utc_now()),
            )
        return checkpoint_id

    def _history(
        self,
        db: Any,
        fact_id: str,
        old_state: str | None,
        new_state: str,
        actor: str,
        reason: str,
    ) -> None:
        db.execute(
            """
            INSERT INTO fact_history
              (id, fact_id, old_state, new_state, actor, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id("history"), fact_id, old_state, new_state, actor, reason, utc_now()),
        )

    def _invalidate_pending_for_profile_change(self, db: Any, source_type: str, source_id: str) -> None:
        for row in db.execute(
            """
            SELECT id FROM applications
            WHERE state NOT IN ('submitted','cancelled','permanent_failure')
            """
        ).fetchall():
            db.execute(
                """
                INSERT INTO invalidation_events
                  (id, reason, affected_record_type, affected_record_id,
                   source_record_type, source_record_id, created_at)
                VALUES (?, ?, 'application', ?, ?, ?, ?)
                """,
                (
                    new_id("invalidate"),
                    "profile_or_preference_changed",
                    row["id"],
                    source_type,
                    source_id,
                    utc_now(),
                ),
            )


def load_onboarding_service(project_root: Path) -> OnboardingService:
    from app.storage.space import SpacePaths

    store = SpaceStore(SpacePaths.from_project_root(project_root))
    store.migrate()
    return OnboardingService(store)
