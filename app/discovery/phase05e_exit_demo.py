"""Reproducible Phase 05E exit demo."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.discovery.agent_b_run import run_agent_b_discovery
from app.mcp.runtime import ToolContext, build_phase04_registry
from app.profile.onboarding import OnboardingService
from app.storage.space import SpacePaths, SpaceStore, stable_json

MANUAL_DEMO_JOB = """Title: Python Software Engineer
Company: Manual Demo Co
Job ID: MANUAL-DEMO-1
Location: Bengaluru
Work mode: Hybrid
Employment type: Full-time permanent
Experience: 1-3 years
Posted: 2026-09-22
Apply: https://careers.manual-demo.example/jobs/manual-demo-1

Responsibilities
- Build Python APIs for internal workflow tools
- Maintain SQL-backed services and dashboards

Requirements
- Python
- SQL
- REST APIs

Preferred
- Cloud deployment exposure
"""


def run_phase05e_exit_demo(project_root: Path) -> dict[str, Any]:
    demo_root = project_root / "private" / "phase05e_exit_demo"
    paths = SpacePaths(
        private_root=demo_root,
        database=demo_root / "db" / "space.sqlite3",
        artifacts=demo_root / "artifacts",
    )
    store = SpaceStore(paths)
    store.migrate()
    onboarding = OnboardingService(store)
    onboarding.create_preference_policy(
        hard_constraints=[
            {"field": "location", "allowed": ["Bengaluru", "Hyderabad"]},
            {"field": "work_mode", "allowed": ["remote", "hybrid", "onsite"]},
            {"field": "role_title", "allowed": ["Python Software Engineer", "Backend Engineer"]},
            {"field": "employment_type", "value": "full_time_permanent"},
        ],
        weighted_preferences=[],
        exclusions=[],
        actor="user",
    )
    discovery = run_agent_b_discovery(
        project_root=project_root,
        sources=["fixture_remote_jobs", "fixture_india_jobs", "ats_allowlist_fixture"],
        max_results=3,
        space_paths=paths,
    )
    registry = build_phase04_registry(store, project_root)
    context = ToolContext(agent_id="agent_b_discovery", task_id="phase05e_exit_demo")
    saved = registry.call(
        context,
        "jobs.save_job",
        {
            "source_id": "manual_import",
            "url": "https://careers.manual-demo.example/jobs/manual-demo-1",
            "description": MANUAL_DEMO_JOB,
        },
    )
    manual: dict[str, Any] = {"saved": saved}
    if saved["ok"]:
        job_id = saved["result"]["job_id"]
        scoped = ToolContext(
            agent_id="agent_b_discovery",
            task_id="phase05e_exit_demo",
            assigned_job_ids=frozenset({job_id}),
        )
        manual["match"] = registry.call(scoped, "jobs.evaluate_match", {"job_id": job_id})
        manual["job"] = registry.call(scoped, "jobs.get_job", {"job_id": job_id})
    return {
        "status": "completed",
        "space_private_root": str(paths.private_root),
        "discovery_run_id": discovery.run_id,
        "discovery_summary": discovery.summary,
        "discovery_rows": discovery.rows,
        "manual_import": manual,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Run the Phase 05E exit demo.")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    payload = run_phase05e_exit_demo(Path(args.project_root).resolve())
    print(stable_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
