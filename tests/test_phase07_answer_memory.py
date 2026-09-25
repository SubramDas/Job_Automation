from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.profile.onboarding import OnboardingService
from app.storage.space import SpacePaths, SpaceStore


def _space(temp_dir: str) -> tuple[SpaceStore, OnboardingService]:
    root = Path(temp_dir)
    paths = SpacePaths(
        private_root=root / "private",
        database=root / "private" / "db" / "space.sqlite3",
        artifacts=root / "private" / "artifacts",
    )
    store = SpaceStore(paths)
    store.migrate()
    return store, OnboardingService(store)


def _insert_application(store: SpaceStore, app_id: str = "app_1", state: str = "preparing") -> None:
    with store.connect() as db:
        db.execute(
            """
            INSERT INTO applications
              (id, durable_identity, state, job_snapshot, resume_snapshot,
               answer_snapshot_json, authorization_version, created_at, updated_at)
            VALUES (?, ?, ?, 'job_1', NULL, '[]', NULL, 'now', 'now')
            """,
            (app_id, f"identity|{app_id}", state),
        )


class Phase07AnswerMemoryTests(unittest.TestCase):
    def test_salary_unit_currency_and_scope_do_not_leak(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            _insert_application(store)
            onboarding.create_reusable_answer(
                semantic_key="compensation.expected_annual_fixed",
                original_question="Expected annual fixed compensation?",
                typed_value=1800000,
                unit="annual",
                scope={
                    "country": "IN",
                    "employment_type": "full_time",
                    "currency": "INR",
                    "unit": "annual",
                },
                sensitivity="private",
                reuse_permission="same_scope",
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
            )

            resolved = onboarding.resolve_answer(
                semantic_key="compensation.expected_annual_fixed",
                context={
                    "country": "IN",
                    "employment_type": "full_time",
                    "currency": "INR",
                    "unit": "annual",
                },
                expected_type="number",
                unit="annual",
            )
            self.assertEqual(resolved.status, "resolved")

            hourly = onboarding.resolve_answer(
                semantic_key="compensation.expected_annual_fixed",
                context={
                    "country": "US",
                    "employment_type": "contract",
                    "currency": "USD",
                    "unit": "hourly",
                },
                expected_type="number",
                unit="hourly",
            )
            self.assertEqual(hourly.status, "incompatible")
            self.assertIsNone(hourly.answer_id)

    def test_sponsorship_answer_is_country_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, onboarding = _space(temp_dir)
            onboarding.create_reusable_answer(
                semantic_key="work_authorization.needs_sponsorship",
                original_question="Do you need sponsorship in India?",
                typed_value=False,
                unit=None,
                scope={"country": "IN"},
                sensitivity="private",
                reuse_permission="same_scope",
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
            )

            self.assertEqual(
                onboarding.resolve_answer(
                    semantic_key="work_authorization.needs_sponsorship",
                    context={"country": "IN"},
                    expected_type="boolean",
                ).status,
                "resolved",
            )
            self.assertEqual(
                onboarding.resolve_answer(
                    semantic_key="work_authorization.needs_sponsorship",
                    context={"country": "US"},
                    expected_type="boolean",
                ).status,
                "incompatible",
            )

    def test_professional_and_total_experience_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, onboarding = _space(temp_dir)
            onboarding.create_reusable_answer(
                semantic_key="experience.years_total",
                original_question="Total experience?",
                typed_value=4,
                unit="years",
                scope={"experience_definition": "total"},
                sensitivity="private",
                reuse_permission="same_scope",
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
            )

            professional = onboarding.resolve_answer(
                semantic_key="experience.years_professional",
                context={"experience_definition": "professional"},
                expected_type="number",
                unit="years",
            )
            self.assertEqual(professional.status, "missing")

    def test_stale_answer_and_conflict_route_to_question(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            _insert_application(store)
            answer_id = onboarding.create_reusable_answer(
                semantic_key="availability.notice_period_days",
                original_question="Notice period?",
                typed_value=30,
                unit="days",
                scope={"country": "IN", "employment_type": "full_time"},
                sensitivity="private",
                reuse_permission="same_scope",
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
            )
            old = (datetime.now(UTC) - timedelta(days=120)).isoformat().replace("+00:00", "Z")
            with store.connect() as db:
                db.execute(
                    "UPDATE reusable_answers SET created_at = ?, updated_at = ? WHERE id = ?",
                    (old, old, answer_id),
                )

            stale = onboarding.resolve_answer(
                semantic_key="availability.notice_period_days",
                context={"country": "IN", "employment_type": "full_time"},
                expected_type="number",
                unit="days",
                application_id="app_1",
                original_question="What is your current notice period?",
                create_question=True,
                checkpoint={"stage": "preparing", "field_count": 6},
            )
            self.assertEqual(stale.status, "stale")
            self.assertTrue(stale.question_id.startswith("question_"))
            with store.connect() as db:
                app = db.execute("SELECT state FROM applications WHERE id = 'app_1'").fetchone()
                checkpoints = db.execute(
                    "SELECT COUNT(*) AS count FROM application_checkpoints"
                ).fetchone()
            self.assertEqual(app["state"], "needs_user_input")
            self.assertEqual(checkpoints["count"], 1)

            onboarding.create_reusable_answer(
                semantic_key="work_authorization.needs_sponsorship",
                original_question="Sponsorship?",
                typed_value=False,
                unit=None,
                scope={"country": "IN"},
                sensitivity="private",
                reuse_permission="same_scope",
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
            )
            onboarding.create_reusable_answer(
                semantic_key="work_authorization.needs_sponsorship",
                original_question="Sponsorship correction?",
                typed_value=True,
                unit=None,
                scope={"country": "IN"},
                sensitivity="private",
                reuse_permission="same_scope",
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
            )
            conflict = onboarding.resolve_answer(
                semantic_key="work_authorization.needs_sponsorship",
                context={"country": "IN"},
                expected_type="boolean",
            )
            self.assertEqual(conflict.status, "conflict")
            self.assertEqual(len(conflict.candidates), 2)

    def test_pending_questions_deduplicate_but_employer_specific_questions_stay_distinct(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            _insert_application(store)
            question = {
                "application_id": "app_1",
                "field_context": {
                    "semantic_key": "compensation.expected_annual_total",
                    "context": {
                        "country": "IN",
                        "employment_type": "full_time",
                        "currency": "INR",
                        "unit": "annual",
                    },
                },
                "reason": "missing salary",
                "suggested_reuse_scope": {
                    "country": "IN",
                    "employment_type": "full_time",
                    "currency": "INR",
                    "unit": "annual",
                },
            }
            first = onboarding.batch_pending_questions([question])[0]
            second = onboarding.batch_pending_questions([question])[0]
            self.assertEqual(first, second)

            employer_question = {
                **question,
                "field_context": {
                    "semantic_key": "employer_disclosure.conflict",
                    "context": {"employer": "Example Corp"},
                },
                "suggested_reuse_scope": {"employer": "Example Corp"},
            }
            other_employer_question = {
                **employer_question,
                "field_context": {
                    "semantic_key": "employer_disclosure.conflict",
                    "context": {"employer": "Other Corp"},
                },
                "suggested_reuse_scope": {"employer": "Other Corp"},
            }
            ids = onboarding.batch_pending_questions([employer_question, other_employer_question])
            self.assertNotEqual(ids[0], ids[1])

    def test_answering_question_resumes_application_and_corrections_invalidate_pending_packages(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            _insert_application(store, state="needs_user_input")
            onboarding.save_checkpoint(
                application_id="app_1",
                stage="preparing",
                checkpoint={"form_id": "fixture_form"},
            )
            question_id = onboarding.create_pending_question(
                application_id="app_1",
                field_context={
                    "semantic_key": "availability.notice_period_days",
                    "original_question": "Notice period?",
                    "context": {"country": "IN", "employment_type": "full_time"},
                },
                reason="missing answer",
                suggested_reuse_scope={"country": "IN", "employment_type": "full_time"},
            )
            answer_id = onboarding.answer_pending_question(
                question_id=question_id,
                typed_value=30,
                unit="days",
                sensitivity="private",
                reuse_permission="same_scope",
                scope={"country": "IN", "employment_type": "full_time"},
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
            )

            with store.connect() as db:
                app = db.execute(
                    """
                    SELECT state, answer_snapshot_json
                    FROM applications
                    WHERE id = 'app_1'
                    """
                ).fetchone()
                question = db.execute(
                    """
                    SELECT status, answer_ref
                    FROM pending_questions
                    WHERE id = ?
                    """,
                    (question_id,),
                ).fetchone()
            self.assertEqual(app["state"], "preparing")
            self.assertIn(answer_id, json.loads(app["answer_snapshot_json"]))
            self.assertEqual(question["status"], "answered")
            self.assertEqual(question["answer_ref"], answer_id)

            replacement_id = onboarding.revise_reusable_answer(
                answer_id,
                typed_value=45,
                unit="days",
                scope={"country": "IN", "employment_type": "full_time"},
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
                reason="notice period correction",
            )
            with store.connect() as db:
                invalidation = db.execute(
                    """
                    SELECT source_record_id FROM invalidation_events
                    WHERE affected_record_id = 'app_1'
                    """
                ).fetchone()
            self.assertEqual(invalidation["source_record_id"], replacement_id)

    def test_special_review_keys_never_auto_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, onboarding = _space(temp_dir)
            onboarding.create_reusable_answer(
                semantic_key="consent.background_check",
                original_question="Do you consent to a background check?",
                typed_value=True,
                unit=None,
                scope={"employer": "Example Corp"},
                sensitivity="sensitive",
                reuse_permission="same_scope",
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
            )
            result = onboarding.resolve_answer(
                semantic_key="consent.background_check",
                context={"employer": "Example Corp"},
                expected_type="boolean",
            )
            self.assertEqual(result.status, "needs_explicit_review")
            self.assertIsNone(result.answer_id)


if __name__ == "__main__":
    unittest.main()
