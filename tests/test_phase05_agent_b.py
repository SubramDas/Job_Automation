from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.matching.calibration import (
    LabeledMatchCase,
    evaluate_agent_b_model_routes,
    evaluate_labeled_matches,
    suggest_thresholds,
)
from app.mcp.runtime import ToolContext, build_phase04_registry
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


JOB_TEXT = """
Title: Python Software Engineer
Company: Example Systems
Job ID: EX-123
Location: Bengaluru
Work mode: Hybrid
Employment type: Full-time permanent
Experience: 1-3 years
Compensation: INR 8-12 LPA
Apply: https://careers.example.test/jobs/ex-123

Responsibilities
- Build Python APIs for internal workflow tools
- Maintain SQL-backed services and production dashboards

Requirements
- Python
- SQL
- REST APIs

Preferred
- Cloud deployment exposure
"""

JOB_TEXT_UNSTATED_COMPENSATION = JOB_TEXT.replace("Compensation: INR 8-12 LPA\n", "")


class Phase05AgentBTests(unittest.TestCase):
    def test_manual_import_extracts_and_preserves_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, _ = _space(temp_dir)
            registry = build_phase04_registry(store, Path.cwd())
            response = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_1"),
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://board.example.test/job/EX-123?tracking=abc",
                    "description": JOB_TEXT,
                },
            )
            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(result["extraction"]["company"]["value"], "Example Systems")
            self.assertEqual(result["extraction"]["work_arrangement"]["value"], "hybrid")
            self.assertEqual(result["extraction"]["locations"]["value"], ["Bengaluru"])
            self.assertEqual(result["extraction"]["experience"]["value"]["minimum_years"], 1)
            self.assertIn("description_hash", result)

            with store.connect() as db:
                artifact = db.execute(
                    "SELECT storage_path FROM artifacts WHERE id = ?",
                    (result["snapshot_artifact_id"],),
                ).fetchone()
                extraction = db.execute(
                    "SELECT extraction_json FROM job_extractions WHERE job_id = ?",
                    (result["job_id"],),
                ).fetchone()
            self.assertIsNotNone(artifact)
            self.assertIsNotNone(extraction)

    def test_exact_duplicate_reuses_existing_job_without_new_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, _ = _space(temp_dir)
            registry = build_phase04_registry(store, Path.cwd())
            context = ToolContext(agent_id="agent_b_discovery", task_id="task_1")
            first = registry.call(
                context,
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://board.example.test/job/EX-123",
                    "description": JOB_TEXT,
                },
            )
            second = registry.call(
                context,
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://board.example.test/job/EX-123?utm=ignored",
                    "description": JOB_TEXT,
                },
            )

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(first["result"]["job_id"], second["result"]["job_id"])
            self.assertEqual(first["result"]["snapshot_artifact_id"], second["result"]["snapshot_artifact_id"])
            with store.connect() as db:
                jobs = db.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()
                snapshots = db.execute("SELECT COUNT(*) AS count FROM artifacts WHERE owner = 'jobs'").fetchone()
                duplicate_audits = db.execute(
                    "SELECT COUNT(*) AS count FROM audit_events WHERE event_type = 'job_duplicate_reused'"
                ).fetchone()
            self.assertEqual(jobs["count"], 1)
            self.assertEqual(snapshots["count"], 1)
            self.assertEqual(duplicate_audits["count"], 1)

    def test_matching_creates_shortlist_handoff_for_clear_fit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            onboarding.create_preference_policy(
                hard_constraints=[],
                weighted_preferences=[
                    {"field": "skills", "weight": 35},
                    {"field": "responsibilities", "weight": 25},
                    {"field": "experience", "weight": 15},
                    {"field": "location", "weight": 10},
                    {"field": "compensation", "weight": 10},
                    {"field": "company", "weight": 5},
                ],
                exclusions=[],
                actor="user",
            )
            registry = build_phase04_registry(store, Path.cwd())
            saved = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_1"),
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://board.example.test/job/EX-123",
                    "description": JOB_TEXT_UNSTATED_COMPENSATION,
                },
            )
            job_id = saved["result"]["job_id"]
            matched = registry.call(
                ToolContext(
                    agent_id="agent_b_discovery",
                    task_id="task_1",
                    assigned_job_ids=frozenset({job_id}),
                ),
                "jobs.evaluate_match",
                {"job_id": job_id},
            )
            self.assertTrue(matched["ok"])
            self.assertEqual(matched["result"]["decision"], "shortlisted")
            self.assertIsNotNone(matched["result"]["handoff_id"])

            with store.connect() as db:
                handoff = db.execute("SELECT payload_json FROM b_to_a_handoffs").fetchone()
            self.assertIsNotNone(handoff)
            self.assertIn("required", handoff["payload_json"])

    def test_matching_explanation_uses_public_candidate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            onboarding.propose_fact(
                field_key="skills.python",
                value_type="boolean",
                value=True,
                source_ref="fixture",
                source_span=None,
                provenance={"source": "test"},
                sensitivity="public",
                actor="user",
            )
            onboarding.propose_fact(
                field_key="skills.sql",
                value_type="boolean",
                value=True,
                source_ref="fixture",
                source_span=None,
                provenance={"source": "test"},
                sensitivity="public",
                actor="user",
            )
            onboarding.create_preference_policy(
                hard_constraints=[],
                weighted_preferences=[],
                exclusions=[],
                actor="user",
            )
            registry = build_phase04_registry(store, Path.cwd())
            saved = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_1"),
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://board.example.test/job/evidence",
                    "description": JOB_TEXT_UNSTATED_COMPENSATION,
                },
            )
            job_id = saved["result"]["job_id"]
            matched = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_1"),
                "jobs.evaluate_match",
                {"job_id": job_id},
            )
            self.assertTrue(matched["ok"])
            with store.connect() as db:
                row = db.execute(
                    "SELECT explanation_json FROM match_results WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            explanation = json.loads(row["explanation_json"])
            coverage = explanation["requirement_coverage"]
            self.assertTrue(coverage["profile_evidence_available"])
            self.assertEqual(coverage["supported"], 2)
            self.assertIn("skills.python", str(coverage))

    def test_known_hard_filter_failure_is_rejected_before_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            onboarding.create_preference_policy(
                hard_constraints=[],
                weighted_preferences=[],
                exclusions=[],
                actor="user",
            )
            registry = build_phase04_registry(store, Path.cwd())
            saved = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_1"),
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://board.example.test/job/pune",
                    "description": JOB_TEXT.replace("Bengaluru", "Pune").replace("1-3 years", "5-7 years"),
                },
            )
            job_id = saved["result"]["job_id"]
            matched = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_1"),
                "jobs.evaluate_match",
                {"job_id": job_id},
            )
            self.assertTrue(matched["ok"])
            self.assertEqual(matched["result"]["decision"], "rejected_by_preferences")
            self.assertIn("outside Bengaluru/Hyderabad", str(matched["result"]["review_reasons"]))

    def test_closed_job_routes_to_expired(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            onboarding.create_preference_policy(
                hard_constraints=[],
                weighted_preferences=[],
                exclusions=[],
                actor="user",
            )
            registry = build_phase04_registry(store, Path.cwd())
            saved = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_1"),
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://board.example.test/job/closed",
                    "description": JOB_TEXT + "\nThis job is no longer available.",
                },
            )
            matched = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_1"),
                "jobs.evaluate_match",
                {"job_id": saved["result"]["job_id"]},
            )
            self.assertTrue(matched["ok"])
            self.assertEqual(matched["result"]["decision"], "expired")

    def test_ambiguous_duplicate_routes_to_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            onboarding.create_preference_policy(
                hard_constraints=[],
                weighted_preferences=[],
                exclusions=[],
                actor="user",
            )
            registry = build_phase04_registry(store, Path.cwd())
            first = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_1"),
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://board.example.test/job/a",
                    "description": JOB_TEXT.replace("EX-123", "EX-123A"),
                },
            )
            self.assertTrue(first["ok"])
            second = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_2"),
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://board.example.test/job/b",
                    "description": JOB_TEXT.replace("EX-123", "EX-123B"),
                },
            )
            self.assertTrue(second["ok"])
            self.assertIn("ambiguous", str(second["result"]["duplicate_signals"]))

            matched = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_2"),
                "jobs.evaluate_match",
                {"job_id": second["result"]["job_id"]},
            )
            self.assertTrue(matched["ok"])
            self.assertEqual(matched["result"]["decision"], "needs_review")

    def test_calibration_and_model_route_reports_are_synthetic(self) -> None:
        cases = [
            LabeledMatchCase("case_yes", "yes", "shortlisted", 88.0),
            LabeledMatchCase("case_maybe", "maybe", "needs_review", 70.0),
            LabeledMatchCase("case_no", "no", "rejected_by_preferences", 20.0, held_out=True),
        ]
        report = evaluate_labeled_matches(cases)
        thresholds = suggest_thresholds(cases)
        routes = evaluate_agent_b_model_routes(
            Path.cwd(),
            [
                {"description": "Clear Python role"},
                {"description": "Ambiguous multi-role posting", "ambiguous": True},
            ],
        )
        self.assertEqual(report["known_hard_filter_escape_count"], 0)
        self.assertEqual(report["held_out_count"], 1)
        self.assertGreaterEqual(thresholds["shortlist_threshold"], 80)
        self.assertEqual(routes["routes"][0]["selected_model"], "gpt-5.4-nano")
        self.assertEqual(routes["routes"][1]["selected_model"], "gpt-5.4-mini")


if __name__ == "__main__":
    unittest.main()
