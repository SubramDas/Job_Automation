"""Run Agent B discovery through the project MCP facade."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.env import load_env_file
from app.mcp.runtime import ToolContext, build_phase04_registry
from app.storage.space import SpacePaths, SpaceStore, new_id, stable_json, utc_now


@dataclass(frozen=True)
class AgentBRunResult:
    run_id: str
    status: str
    output_artifact_id: str | None
    markdown_artifact_id: str | None
    summary: dict[str, Any]
    rows: list[dict[str, Any]]


DEFAULT_SOURCES = ("fixture_remote_jobs", "fixture_india_jobs")


def run_agent_b_discovery(
    *,
    project_root: Path,
    sources: list[str],
    max_results: int,
    preview: bool = False,
    space_paths: SpacePaths | None = None,
) -> AgentBRunResult:
    load_env_file(project_root)
    store = SpaceStore(space_paths or SpacePaths.from_project_root(project_root))
    store.migrate()
    registry = build_phase04_registry(store, project_root)
    run_id = new_id("agent_b_run")
    lock_path = store.paths.private_root / "run_locks" / "agent_b_discovery.lock"
    if lock_path.exists():
        return AgentBRunResult(
            run_id=run_id,
            status="blocked_existing_run_lock",
            output_artifact_id=None,
            markdown_artifact_id=None,
            summary={"lock_path": str(lock_path)},
            rows=[],
        )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(run_id, encoding="utf-8")
    try:
        context = ToolContext(agent_id="agent_b_discovery", task_id=run_id)
        search_profile = registry.call(context, "space.get_search_profile", {})
        policy = _policy_from_profile(search_profile)
        query_plan = build_query_plan(policy, sources=sources, max_results=max_results)
        if preview:
            return AgentBRunResult(
                run_id=run_id,
                status="preview",
                output_artifact_id=None,
                markdown_artifact_id=None,
                summary={"query_plan": query_plan, "source_count": len(sources)},
                rows=[],
            )

        rows: list[dict[str, Any]] = []
        source_errors: list[dict[str, Any]] = []
        for plan in query_plan:
            searched = registry.call(
                context,
                "jobs.search_sources",
                {
                    "source_id": plan["source_id"],
                    "query": plan["query"],
                    "locations": plan["locations"],
                    "work_modes": plan["work_modes"],
                    "employment_type": plan["employment_type"],
                    "max_results": plan["max_results"],
                },
            )
            if not searched["ok"]:
                source_errors.append({"source_id": plan["source_id"], "error": searched["error"]})
                continue
            for result in searched["result"].get("results", []):
                row = _process_result(registry, context, result)
                rows.append(row)

        grouped = _group_rows(rows, source_errors)
        output_payload = {
            "run_id": run_id,
            "created_at": utc_now(),
            "query_plan": query_plan,
            "summary": grouped,
            "rows": rows,
            "source_errors": source_errors,
            "live_external_actions": False,
        }
        output_artifact_id = _store_report(
            store,
            output_payload,
            filename="agent-b-discovery.json",
            content_type="application/json",
        )
        markdown_artifact_id = _store_report(
            store,
            _markdown_report(output_payload).encode("utf-8"),
            filename="agent-b-discovery.md",
            content_type="text/markdown",
        )
        _audit_run(store, run_id, grouped, output_artifact_id, markdown_artifact_id)
        return AgentBRunResult(
            run_id=run_id,
            status="completed",
            output_artifact_id=output_artifact_id,
            markdown_artifact_id=markdown_artifact_id,
            summary=grouped,
            rows=rows,
        )
    finally:
        if lock_path.exists() and lock_path.read_text(encoding="utf-8") == run_id:
            lock_path.unlink()


def build_query_plan(policy: dict[str, Any] | None, *, sources: list[str], max_results: int) -> list[dict[str, Any]]:
    hard_constraints = policy.get("hard_constraints", []) if policy else []
    weighted = policy.get("weighted_preferences", []) if policy else []
    locations = _constraint_values(hard_constraints, "location") or ["Bengaluru", "Hyderabad"]
    work_modes = _constraint_values(hard_constraints, "work_mode") or ["remote", "hybrid", "onsite"]
    role_terms = _constraint_values(hard_constraints, "role_title") or _preference_values(weighted, "role_title")
    if not role_terms:
        role_terms = ["Python Software Engineer", "AI ML Engineer", "Software Engineer"]
    employment_type = (_constraint_values(hard_constraints, "employment_type") or ["full_time_permanent"])[0]
    query = " OR ".join(role_terms)
    return [
        {
            "source_id": source_id,
            "query": query,
            "locations": locations,
            "work_modes": work_modes,
            "employment_type": employment_type,
            "max_results": max_results,
        }
        for source_id in sources
    ]


def _process_result(registry: Any, context: ToolContext, result: dict[str, Any]) -> dict[str, Any]:
    fetched = registry.call(
        context,
        "jobs.fetch_description",
        {
            "source_id": result["source_id"],
            "url": result["result_url"],
            "source_job_id": result["source_job_id"],
        },
    )
    if not fetched["ok"]:
        return {
            "source_id": result["source_id"],
            "source_job_id": result["source_job_id"],
            "title": result["title"],
            "company": result["company"],
            "state": "manual_handoff",
            "link": result["result_url"],
            "description_status": "unavailable",
            "error": fetched["error"],
        }
    saved = registry.call(
        context,
        "jobs.save_job",
        {
            "source_id": result["source_id"],
            "url": fetched["result"]["url"],
            "description": fetched["result"]["description"],
        },
    )
    if not saved["ok"]:
        return {
            "source_id": result["source_id"],
            "source_job_id": result["source_job_id"],
            "title": result["title"],
            "company": result["company"],
            "state": "manual_handoff",
            "link": result["result_url"],
            "description_status": "save_failed",
            "error": saved["error"],
        }
    job_id = saved["result"]["job_id"]
    matched = registry.call(
        ToolContext(
            agent_id=context.agent_id,
            task_id=context.task_id,
            assigned_job_ids=frozenset({job_id}),
        ),
        "jobs.evaluate_match",
        {"job_id": job_id},
    )
    job = registry.call(
        ToolContext(
            agent_id=context.agent_id,
            task_id=context.task_id,
            assigned_job_ids=frozenset({job_id}),
        ),
        "jobs.get_job",
        {"job_id": job_id},
    )
    match_result = matched.get("result", {}) if matched["ok"] else {}
    job_result = job.get("result", {}) if job["ok"] else {}
    extracted = job_result.get("extraction", {}).get("record", {})
    destination = _resolve_destination(
        portal_url=result["result_url"],
        fetched_url=fetched["result"]["url"],
        fetched_application_destination=fetched["result"].get("application_destination"),
        extracted_application_destination=extracted.get("application_destination", {}).get("value"),
    )
    freshness = _freshness_summary(extracted)
    state = match_result.get("decision", "needs_review")
    review_reasons = list(match_result.get("review_reasons", []))
    if freshness["status"] == "expired" and state != "expired":
        state = "expired"
        review_reasons.append("closing date is in the past")
    return {
        "source_id": result["source_id"],
        "source_job_id": result["source_job_id"],
        "job_id": job_id,
        "title": result["title"],
        "company": result["company"],
        "location": result["location"],
        "work_mode": result["work_mode"],
        "state": state,
        "score": match_result.get("score"),
        "coverage": match_result.get("coverage"),
        "review_reasons": review_reasons,
        "link": result["result_url"],
        "portal_link": result["result_url"],
        "canonical_job_url": fetched["result"]["url"],
        "application_destination": destination["application_destination"],
        "destination_resolution": destination,
        "freshness": freshness,
        "description_hash": saved["result"].get("description_hash"),
        "snapshot_artifact_id": saved["result"].get("snapshot_artifact_id"),
        "description_status": fetched["result"]["status"],
        "unknown_fields": job_result.get("extraction", {}).get("unknown_fields", []),
        "warnings": job_result.get("extraction", {}).get("warnings", []),
        "extracted": {
            "title": extracted.get("title", {}).get("value"),
            "company": extracted.get("company", {}).get("value"),
            "experience": extracted.get("experience", {}).get("value"),
            "required": extracted.get("required_qualifications", {}).get("value"),
        },
    }


def _resolve_destination(
    *,
    portal_url: str,
    fetched_url: str,
    fetched_application_destination: str | None,
    extracted_application_destination: str | None,
) -> dict[str, Any]:
    destination = fetched_application_destination or extracted_application_destination or fetched_url
    portal_host = _host(portal_url)
    destination_host = _host(destination)
    return {
        "portal_url": portal_url,
        "canonical_job_url": fetched_url,
        "application_destination": destination,
        "portal_host": portal_host,
        "destination_host": destination_host,
        "separate_from_portal": bool(destination_host and portal_host and destination_host != portal_host),
        "status": "resolved" if destination else "unknown",
    }


def _host(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname


def _freshness_summary(extracted: dict[str, Any], *, stale_after_days: int = 30) -> dict[str, Any]:
    posting_raw = extracted.get("posting_date", {}).get("value")
    closing_raw = extracted.get("closing_date", {}).get("value")
    posting_date = _parse_date(posting_raw)
    closing_date = _parse_date(closing_raw)
    today = datetime.now(UTC).date()
    if closing_date and closing_date < today:
        return {
            "status": "expired",
            "posting_date": posting_raw,
            "closing_date": closing_raw,
            "age_days": (today - posting_date).days if posting_date else None,
            "stale_after_days": stale_after_days,
        }
    if posting_date:
        age_days = (today - posting_date).days
        return {
            "status": "stale" if age_days > stale_after_days else "fresh",
            "posting_date": posting_raw,
            "closing_date": closing_raw,
            "age_days": age_days,
            "stale_after_days": stale_after_days,
        }
    return {
        "status": "unknown",
        "posting_date": posting_raw,
        "closing_date": closing_raw,
        "age_days": None,
        "stale_after_days": stale_after_days,
    }


def _parse_date(value: str | None) -> Any:
    if not value:
        return None
    cleaned = str(value).strip().split()[0].rstrip(",")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _policy_from_profile(response: dict[str, Any]) -> dict[str, Any] | None:
    if not response["ok"]:
        return None
    return response["result"].get("policy")


def _constraint_values(constraints: list[dict[str, Any]], field: str) -> list[str]:
    for constraint in constraints:
        if constraint.get("field") == field:
            values = constraint.get("allowed") or constraint.get("values") or constraint.get("value")
            if isinstance(values, list):
                return [str(value) for value in values]
            if values is not None:
                return [str(values)]
    return []


def _preference_values(preferences: list[dict[str, Any]], field: str) -> list[str]:
    for preference in preferences:
        if preference.get("field") == field:
            values = preference.get("values") or preference.get("preferred") or preference.get("value")
            if isinstance(values, list):
                return [str(value) for value in values]
            if values is not None:
                return [str(values)]
    return []


def _group_rows(rows: list[dict[str, Any]], source_errors: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, Any] = {
        "shortlisted": 0,
        "needs_review": 0,
        "rejected_by_preferences": 0,
        "expired": 0,
        "manual_handoff": 0,
        "source_errors": len(source_errors),
        "total_jobs": len(rows),
    }
    for row in rows:
        state = row["state"]
        grouped[state] = grouped.get(state, 0) + 1
    return grouped


def _store_report(store: SpaceStore, payload: Any, *, filename: str, content_type: str) -> str:
    data = stable_json(payload).encode("utf-8") if isinstance(payload, dict) else payload
    artifact = store.artifacts.put_bytes(data, filename=filename, content_type=content_type, owner="agent_b")
    store.record_artifact(artifact)
    return artifact.artifact_id


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Agent B Discovery Run",
        "",
        f"Run ID: `{payload['run_id']}`",
        f"Created: `{payload['created_at']}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in payload["summary"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Jobs", ""])
    for row in payload["rows"]:
        lines.append(
            f"- **{row['state']}** | {row['title']} | {row['company']} | "
            f"{row.get('location', '')} | score={row.get('score')} | {row['link']}"
        )
    if payload["source_errors"]:
        lines.extend(["", "## Source Errors", ""])
        for error in payload["source_errors"]:
            lines.append(f"- `{error['source_id']}`: {error['error']}")
    return "\n".join(lines) + "\n"


def format_cli_table(result: AgentBRunResult) -> str:
    lines = [
        f"Agent B discovery run: {result.run_id}",
        f"Status: {result.status}",
        "",
        "Summary:",
    ]
    for key, value in result.summary.items():
        if key != "query_plan":
            lines.append(f"  {key}: {value}")
    if result.output_artifact_id:
        lines.append(f"  json_artifact: {result.output_artifact_id}")
    if result.markdown_artifact_id:
        lines.append(f"  markdown_artifact: {result.markdown_artifact_id}")
    if result.rows:
        lines.extend(["", "Jobs:"])
        states = sorted({row["state"] for row in result.rows})
        for state in states:
            lines.extend(["", f"[{state}]", "SCORE  SOURCE               TITLE | COMPANY | LINK", "-" * 92])
            for row in [item for item in result.rows if item["state"] == state]:
                score = "" if row.get("score") is None else str(row["score"])
                lines.append(
                    f"{score[:5]:5}  {row['source_id'][:19]:19} "
                    f"{row['title']} | {row['company']} | {row['link']}"
                )
    if result.summary.get("query_plan"):
        lines.extend(["", "Query plan:"])
        for plan in result.summary["query_plan"]:
            lines.append(
                f"  {plan['source_id']}: {plan['query']} "
                f"locations={','.join(plan['locations'])} modes={','.join(plan['work_modes'])}"
            )
    return "\n".join(lines)


def _audit_run(
    store: SpaceStore,
    run_id: str,
    summary: dict[str, Any],
    output_artifact_id: str,
    markdown_artifact_id: str,
) -> None:
    with store.connect() as db:
        db.execute(
            """
            INSERT INTO audit_events
              (id, actor, event_type, subject_type, subject_id, details_json, created_at)
            VALUES (?, 'agent_b_discovery', 'discovery_run_completed', 'run', ?, ?, ?)
            """,
            (
                new_id("audit"),
                run_id,
                stable_json(
                    {
                        "summary": summary,
                        "output_artifact_id": output_artifact_id,
                        "markdown_artifact_id": markdown_artifact_id,
                    }
                ),
                utc_now(),
            ),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Agent B discovery through MCP tools.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a table.")
    args = parser.parse_args(argv)
    sources = [source.strip() for source in args.sources.split(",") if source.strip()]
    result = run_agent_b_discovery(
        project_root=args.project_root,
        sources=sources,
        max_results=args.max_results,
        preview=args.preview,
    )
    if args.json:
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    else:
        print(format_cli_table(result))
    return 0 if result.status in {"completed", "preview"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
