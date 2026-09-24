"""Run Agent A keyword planning through the project MCP facade."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.env import load_env_file
from app.mcp.runtime import ToolContext, build_phase04_registry
from app.storage.space import SpacePaths, SpaceStore


@dataclass(frozen=True)
class AgentARunResult:
    status: str
    job_id: str
    keyword_plan_artifact_id: str
    result: dict[str, Any]


def run_agent_a_keyword_planning(
    *,
    project_root: Path,
    job_id: str | None,
    job_description_file: Path | None = None,
    job_url: str | None = None,
    space_paths: SpacePaths | None = None,
) -> AgentARunResult:
    load_env_file(project_root)
    store = SpaceStore(space_paths or SpacePaths.from_project_root(project_root))
    store.migrate()
    registry = build_phase04_registry(store, project_root)

    resolved_job_id = job_id or _save_manual_job(registry, job_description_file, job_url)
    planned = registry.call(
        ToolContext(
            agent_id="agent_a_resume",
            task_id="agent_a_keyword_plan",
            assigned_job_ids=frozenset({resolved_job_id}),
        ),
        "jobs.create_keyword_plan",
        {"job_id": resolved_job_id},
    )
    if not planned["ok"]:
        raise SystemExit(json.dumps(planned["error"], indent=2))
    return AgentARunResult(
        status=planned["result"]["status"],
        job_id=resolved_job_id,
        keyword_plan_artifact_id=planned["result"]["keyword_plan_artifact_id"],
        result=planned["result"],
    )


# Backwards-compatible import name while callers migrate. It no longer accepts resume inputs.
def run_agent_a_tailoring(**kwargs: Any) -> AgentARunResult:
    unsupported = {"resume_artifact_id", "resume_tex_file", "approve"} & set(kwargs)
    for key in unsupported:
        if kwargs.get(key) not in (None, False):
            raise TypeError(f"{key} is no longer supported; Agent A only creates keyword plans")
    return run_agent_a_keyword_planning(
        project_root=kwargs["project_root"],
        job_id=kwargs.get("job_id"),
        job_description_file=kwargs.get("job_description_file"),
        job_url=kwargs.get("job_url"),
        space_paths=kwargs.get("space_paths"),
    )


def _save_manual_job(registry: Any, job_description_file: Path | None, job_url: str | None) -> str:
    if job_description_file is None:
        raise SystemExit("provide either --job-id or --job-description-file")
    description = job_description_file.read_text(encoding="utf-8")
    saved = registry.call(
        ToolContext(agent_id="agent_b_discovery", task_id="agent_a_manual_import"),
        "jobs.save_job",
        {
            "source_id": "manual_import",
            "url": job_url or f"file://{job_description_file.resolve()}",
            "description": description,
        },
    )
    if not saved["ok"]:
        raise SystemExit(json.dumps(saved["error"], indent=2))
    return str(saved["result"]["job_id"])


def format_summary(result: AgentARunResult) -> str:
    payload = result.result
    lines = [
        f"Agent A status: {result.status}",
        f"Job ID: {result.job_id}",
        f"Keyword plan artifact: {result.keyword_plan_artifact_id} ({payload['keyword_plan_sha256']})",
        "",
        "Priority counts:",
        f"- High: {payload['priority_counts'].get('high', 0)}",
        f"- Medium: {payload['priority_counts'].get('medium', 0)}",
        f"- Low: {payload['priority_counts'].get('low', 0)}",
        "",
        "Mandatory keywords:",
    ]
    mandatory = [item for item in payload["keywords"] if item["mandate"] == "mandatory"]
    for item in mandatory[:20]:
        lines.append(f"- {item['term']} [{item['priority']}, {item['category']}] - {item['rationale']}")
    if not mandatory:
        lines.append("- none detected")
    recommended = [item for item in payload["keywords"] if item["mandate"] == "recommended"]
    if recommended:
        lines.extend(["", "Recommended keywords:"])
        for item in recommended[:15]:
            lines.append(f"- {item['term']} [{item['priority']}, {item['category']}]")
    warnings = payload.get("warnings", [])
    if warnings:
        lines.extend(["", "Warnings:"])
        for item in warnings[:10]:
            lines.append(f"- {item['code']}")
    lines.extend(
        [
            "",
            f"Validation: {payload['validation']['status']}",
            f"Model route: {payload['model']['route_status']} ({payload['model']['selected_model']})",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Agent A keyword planning locally.")
    parser.add_argument("--job-id", help="Existing saved job ID from Agent B.")
    parser.add_argument("--job-description-file", type=Path, help="Path to a job description text file to import first.")
    parser.add_argument("--job-url", help="URL/source to associate with --job-description-file.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    if bool(args.job_id) == bool(args.job_description_file):
        parser.error("provide exactly one of --job-id or --job-description-file")

    result = run_agent_a_keyword_planning(
        project_root=Path.cwd(),
        job_id=args.job_id,
        job_description_file=args.job_description_file,
        job_url=args.job_url,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "status": result.status,
                    "job_id": result.job_id,
                    "keyword_plan_artifact_id": result.keyword_plan_artifact_id,
                    "result": result.result,
                },
                indent=2,
            )
        )
    else:
        print(format_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
