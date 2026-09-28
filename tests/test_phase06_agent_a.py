from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.discovery.job_review_workspace import write_latest_keyword_plan_review_file
from app.mcp.runtime import ToolContext, build_phase04_registry
from app.storage.space import SpacePaths, SpaceStore


JOB_TEXT = """
Title: Python Kubernetes Software Engineer
Company: Example Systems
Location: Bengaluru

Requirements
- Python
- SQL
- Kubernetes

Responsibilities
- Build Python REST APIs and improve observability for backend services.
"""


def _space(temp_dir: str) -> SpaceStore:
    root = Path(temp_dir)
    store = SpaceStore(
        SpacePaths(
            private_root=root / "private",
            database=root / "private" / "db" / "space.sqlite3",
            artifacts=root / "private" / "artifacts",
        )
    )
    store.migrate()
    return store


class Phase06AgentAKeywordPlanTests(unittest.TestCase):
    def test_codex_mcp_generated_plan_is_validated_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _space(temp_dir)
            registry = build_phase04_registry(store, Path.cwd())
            saved = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_b"),
                "jobs.save_job",
                {"source_id": "manual_import", "url": "https://example.test/jobs/codex-mcp", "description": JOB_TEXT},
            )
            job_id = saved["result"]["job_id"]
            fetched = registry.call(
                ToolContext(agent_id="agent_a_resume", task_id="task_a", assigned_job_ids=frozenset({job_id})),
                "jobs.get_job",
                {"job_id": job_id},
            )
            self.assertTrue(fetched["ok"])
            self.assertIn("Python Kubernetes Software Engineer", fetched["result"]["description"])
            planned = registry.call(
                ToolContext(agent_id="agent_a_resume", task_id="task_a", assigned_job_ids=frozenset({job_id})),
                "jobs.save_keyword_plan",
                {
                    "job_id": job_id,
                    "keywords": [
                        {"term": "Python", "priority": "high", "mandate": "mandatory", "category": "skill", "rationale": "Listed as a requirement."},
                        {"term": "Kubernetes", "priority": "high", "mandate": "mandatory", "category": "platform", "rationale": "Listed as a requirement."},
                        {"term": "Observability", "priority": "medium", "mandate": "recommended", "category": "responsibility", "rationale": "Named in the role responsibilities."},
                    ],
                    "model": {"selected_model": "codex-session", "provider_mode": "codex_mcp", "route_status": "codex_mcp_in_session"},
                },
            )
            self.assertTrue(planned["ok"])
            result = planned["result"]
            self.assertEqual(result["status"], "validated")
            self.assertEqual(result["model"]["provider_mode"], "codex_mcp")
            self.assertEqual(result["priority_counts"], {"high": 2, "medium": 1, "low": 0})
            keyword_file = list((store.paths.private_root / "job_reviews").glob("*/*/keywords.md"))[0]
            self.assertIn("**Python**", keyword_file.read_text(encoding="utf-8"))
            keyword_file.unlink()
            self.assertTrue(write_latest_keyword_plan_review_file(store, job_id=job_id).exists())

    def test_save_keyword_plan_deduplicates_and_filters_boilerplate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _space(temp_dir)
            registry = build_phase04_registry(store, Path.cwd())
            saved = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_b"),
                "jobs.save_job",
                {"source_id": "manual_import", "url": "https://example.test/jobs/normalization", "description": JOB_TEXT},
            )
            job_id = saved["result"]["job_id"]
            planned = registry.call(
                ToolContext(agent_id="agent_a_resume", task_id="task_a", assigned_job_ids=frozenset({job_id})),
                "jobs.save_keyword_plan",
                {
                    "job_id": job_id,
                    "keywords": [
                        {"term": "Python", "priority": "high", "mandate": "mandatory", "category": "skill", "rationale": "Required."},
                        {"term": "python", "priority": "high", "mandate": "mandatory", "category": "skill", "rationale": "Duplicate."},
                        {"term": "Equal opportunity", "priority": "low", "mandate": "optional", "category": "domain_term", "rationale": "Boilerplate."},
                    ],
                },
            )
            self.assertTrue(planned["ok"])
            self.assertEqual([item["term"] for item in planned["result"]["keywords"]], ["Python"])
            self.assertEqual(planned["result"]["validation"]["status"], "passed")
            self.assertNotIn("openai", json.dumps(planned["result"]["model"]).lower())

    def test_agent_a_scope_blocks_unassigned_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _space(temp_dir)
            registry = build_phase04_registry(store, Path.cwd())
            saved = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_b"),
                "jobs.save_job",
                {"source_id": "manual_import", "url": "https://example.test/jobs/scope", "description": JOB_TEXT},
            )
            denied = registry.call(
                ToolContext(agent_id="agent_a_resume", task_id="task_a", assigned_job_ids=frozenset({"job_other"})),
                "jobs.save_keyword_plan",
                {"job_id": saved["result"]["job_id"], "keywords": []},
            )
            self.assertFalse(denied["ok"])
            self.assertEqual(denied["error"]["code"], "authorization_failed")


if __name__ == "__main__":
    unittest.main()
