from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.profile.onboarding import OnboardingService
from app.profile.resume_ingestion import ingest_resume
from app.storage.space import SpaceError, SpacePaths, SpaceStore


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


def _write_docx(path: Path, text: str) -> None:
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{escaped}</w:t></w:r></w:p></w:body>
</w:document>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


class SpacePhase03Tests(unittest.TestCase):
    def test_migration_creates_uniqueness_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, _ = _space(temp_dir)
            with store.connect() as db:
                db.execute(
                    """
                    INSERT INTO jobs
                      (id, canonical_url, normalized_identity, description_hash, retrieved_at, status, created_at)
                    VALUES ('job_1', 'https://example.test/job/1', 'company|title|blr', 'hash', 'now', 'new', 'now')
                    """
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        """
                        INSERT INTO jobs
                          (id, canonical_url, normalized_identity, description_hash, retrieved_at, status, created_at)
                        VALUES ('job_2', 'https://example.test/job/1', 'company|title|blr', 'hash2', 'now', 'new', 'now')
                        """
                    )

    def test_artifact_store_records_immutable_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, _ = _space(temp_dir)
            source = Path(temp_dir) / "resume.docx"
            _write_docx(source, "Synthetic resume text with test@example.com and many extra words.")

            artifact = store.artifacts.put_file(
                source,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                owner="candidate",
            )
            store.record_artifact(artifact)

            self.assertTrue(artifact.path.exists())
            with store.connect() as db:
                row = db.execute("SELECT sha256, immutable FROM artifacts WHERE id = ?", (artifact.artifact_id,)).fetchone()
            self.assertEqual(row["sha256"], artifact.sha256)
            self.assertEqual(row["immutable"], 1)

    def test_agents_can_propose_but_not_confirm_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, onboarding = _space(temp_dir)
            fact_id = onboarding.propose_fact(
                field_key="skills.python",
                value_type="boolean",
                value=True,
                source_ref="artifact_1",
                source_span={"start": 1, "end": 7},
                provenance={"method": "fixture"},
                sensitivity="public",
                actor="agent",
            )

            with self.assertRaises(SpaceError):
                onboarding.set_fact_state(fact_id, state="confirmed", actor="agent", reason="not allowed")

            onboarding.set_fact_state(fact_id, state="confirmed", actor="user", reason="verified fixture")
            facts = onboarding.list_facts()
            self.assertEqual(facts[0].confirmation_state, "confirmed")

    def test_preferences_answers_questions_and_invalidations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            version = onboarding.create_preference_policy(
                hard_constraints=[{"field": "location", "allowed": ["Bengaluru", "Hyderabad"]}],
                weighted_preferences=[{"field": "skills", "weight": 35}],
                exclusions=[],
                actor="user",
            )
            self.assertEqual(version, 1)

            answer_id = onboarding.create_reusable_answer(
                semantic_key="availability.notice_period_days",
                original_question="What is your notice period?",
                typed_value=30,
                unit="days",
                scope={"country": "IN", "employment_type": "full_time"},
                sensitivity="private",
                reuse_permission="same_scope",
                provenance={"source": "user"},
                expires_at=None,
                actor="user",
            )
            self.assertEqual(
                onboarding.resolve_exact_answer(
                    semantic_key="availability.notice_period_days",
                    scope={"country": "IN", "employment_type": "full_time"},
                ),
                answer_id,
            )

            with store.connect() as db:
                db.execute(
                    """
                    INSERT INTO applications
                      (id, durable_identity, state, job_snapshot, resume_snapshot,
                       answer_snapshot_json, authorization_version, created_at, updated_at)
                    VALUES ('app_1', 'company|req|candidate', 'ready', 'job_1', NULL, '[]', NULL, 'now', 'now')
                    """
                )
            fact_id = onboarding.propose_fact(
                field_key="work_history.example",
                value_type="string",
                value="Example Corp",
                source_ref="manual",
                source_span=None,
                provenance={"source": "user"},
                sensitivity="private",
                actor="user",
            )
            onboarding.revise_fact(
                fact_id,
                value="Example Corp revised",
                provenance={"source": "user"},
                actor="user",
                reason="correction",
            )
            with store.connect() as db:
                invalidations = db.execute("SELECT COUNT(*) AS count FROM invalidation_events").fetchone()
            self.assertGreaterEqual(invalidations["count"], 1)

            question_id = onboarding.create_pending_question(
                application_id="app_1",
                field_context={"field": "salary"},
                reason="missing expected compensation",
                suggested_reuse_scope={"country": "IN"},
            )
            checkpoint_id = onboarding.save_checkpoint(
                application_id="app_1",
                stage="preparing",
                checkpoint={"field_count": 3},
            )
            self.assertTrue(question_id.startswith("question_"))
            self.assertTrue(checkpoint_id.startswith("checkpoint_"))

    def test_docx_resume_ingestion_preserves_original_and_proposes_unconfirmed_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            resume = Path(temp_dir) / "resume.docx"
            _write_docx(
                resume,
                "Synthetic Candidate test@example.com +91 98765 43210 "
                "Python SQL projects education experience outcomes " * 12,
            )

            result = ingest_resume(resume, store)
            self.assertEqual(result.extraction_status, "extracted")
            self.assertTrue(result.original.path.exists())
            self.assertGreaterEqual(len(result.proposed_facts), 2)

            for proposal in result.proposed_facts:
                onboarding.propose_fact(actor="import", **proposal)
            states = [fact.confirmation_state for fact in onboarding.list_facts()]
            self.assertEqual(states, ["proposed", "proposed"])

    def test_unreadable_pdf_is_labeled_for_editable_copy_or_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, _ = _space(temp_dir)
            resume = Path(temp_dir) / "resume.pdf"
            resume.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF")

            result = ingest_resume(resume, store)
            self.assertEqual(result.extraction_status, "needs_editable_copy_or_approved_ocr")
            self.assertIn("possible_scanned_or_unreadable_pdf", result.uncertainty_labels)

    def test_export_and_delete_profile_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            onboarding.propose_fact(
                field_key="education.degree",
                value_type="string",
                value="Synthetic BTech",
                source_ref="manual",
                source_span=None,
                provenance={"source": "test"},
                sensitivity="private",
                actor="user",
            )
            exported = store.export_profile()
            self.assertEqual(exported["schema_version"], "2026-09-23.phase03")
            self.assertEqual(json.loads(exported["candidate_facts"][0]["value_json"]), "Synthetic BTech")
            store.delete_private_data()
            self.assertFalse(store.paths.private_root.exists())

    def test_backup_and_restore_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store, onboarding = _space(temp_dir)
            onboarding.propose_fact(
                field_key="skills.sql",
                value_type="boolean",
                value=True,
                source_ref="manual",
                source_span=None,
                provenance={"source": "test"},
                sensitivity="public",
                actor="user",
            )
            backup = store.backup(Path(temp_dir) / "backups")
            store.delete_private_data()
            store.restore(backup)
            store.migrate()
            facts = OnboardingService(store).list_facts()
            self.assertEqual(facts[0].field_key, "skills.sql")


if __name__ == "__main__":
    unittest.main()
