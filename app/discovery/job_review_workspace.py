"""Human-readable Agent B job review workspace.

The files written here are a private convenience layer over Space. The SQLite rows and
immutable artifacts remain the source of truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.storage.space import SpacePaths, SpaceStore, stable_json, utc_now


@dataclass(frozen=True)
class ReviewWorkspaceResult:
    root: Path
    index_path: Path
    job_paths: dict[str, Path]


def write_agent_b_review_workspace(
    store: SpaceStore,
    *,
    rows: list[dict[str, Any]],
    run_id: str | None = None,
    summary: dict[str, Any] | None = None,
) -> ReviewWorkspaceResult:
    """Write review files for the jobs in a discovery run."""
    root = review_root(store)
    root.mkdir(parents=True, exist_ok=True)
    job_paths: dict[str, Path] = {}
    index_rows: list[dict[str, Any]] = []
    for row in rows:
        job_id = row.get("job_id")
        if job_id:
            record = load_job_review_record(store, job_id)
            job_dir = job_review_dir(root, record)
            write_job_review_files(job_dir, record, row=row)
            job_paths[job_id] = job_dir
            row["review_path"] = _relative_to_private(store, job_dir)
        index_rows.append(dict(row))
    index_path = write_index(root, store, rows=index_rows, run_id=run_id, summary=summary)
    return ReviewWorkspaceResult(root=root, index_path=index_path, job_paths=job_paths)


def rebuild_job_review_workspace(store: SpaceStore) -> ReviewWorkspaceResult:
    """Rebuild readable files for every saved job without deleting artifacts or rows."""
    root = review_root(store)
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    job_paths: dict[str, Path] = {}
    with store.connect() as db:
        job_rows = db.execute("SELECT id FROM jobs ORDER BY created_at DESC").fetchall()
    for job_row in job_rows:
        record = load_job_review_record(store, job_row["id"])
        job_dir = job_review_dir(root, record)
        row = row_from_record(record)
        row["review_path"] = _relative_to_private(store, job_dir)
        write_job_review_files(job_dir, record, row=row)
        write_latest_keyword_plan_review_file(store, job_id=record["job"]["id"])
        job_paths[record["job"]["id"]] = job_dir
        rows.append(row)
    index_path = write_index(root, store, rows=rows, run_id=None, summary={"total_jobs": len(rows)})
    return ReviewWorkspaceResult(root=root, index_path=index_path, job_paths=job_paths)


def review_root(store: SpaceStore) -> Path:
    return store.paths.private_root / "job_reviews"


def load_job_review_record(store: SpaceStore, job_id: str) -> dict[str, Any]:
    with store.connect() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise ValueError(f"unknown job id: {job_id}")
        extraction = db.execute(
            "SELECT * FROM job_extractions WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        match = db.execute(
            "SELECT * FROM match_results WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        artifact = db.execute(
            "SELECT * FROM artifacts WHERE id = ? ORDER BY version DESC LIMIT 1",
            (job["snapshot_artifact_id"],),
        ).fetchone()
        duplicates = db.execute(
            "SELECT * FROM job_duplicate_signals WHERE job_id = ? ORDER BY created_at",
            (job_id,),
        ).fetchall()
        source_ids = db.execute(
            "SELECT source_id FROM job_source_ids WHERE job_id = ? ORDER BY source_id",
            (job_id,),
        ).fetchall()
    description = ""
    artifact_row = dict(artifact) if artifact is not None else None
    if artifact_row is not None:
        description = Path(artifact_row["storage_path"]).read_text(encoding="utf-8")
    extraction_record = json.loads(extraction["extraction_json"]) if extraction is not None else {}
    match_record = dict(match) if match is not None else None
    return {
        "job": dict(job),
        "description": description,
        "description_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest() if description else None,
        "artifact": artifact_row,
        "extraction": {
            "id": extraction["id"],
            "record": extraction_record,
            "evidence": json.loads(extraction["evidence_json"]),
            "warnings": json.loads(extraction["warnings_json"]),
            "unknown_fields": json.loads(extraction["unknown_fields_json"]),
            "created_at": extraction["created_at"],
        }
        if extraction is not None
        else None,
        "match": _match_payload(match_record),
        "duplicate_signals": [_duplicate_payload(dict(row)) for row in duplicates],
        "source_ids": [row["source_id"] for row in source_ids],
    }


def job_review_dir(root: Path, record: dict[str, Any]) -> Path:
    job = record["job"]
    company_slug = slugify(job.get("employer") or "unknown-company")
    title_slug = slugify(job.get("title") or "unknown-role")
    return root / company_slug / f"{title_slug}__{short_job_id(job['id'])}"


def write_job_review_files(job_dir: Path, record: dict[str, Any], *, row: dict[str, Any] | None = None) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    description = record["description"]
    (job_dir / "job-description.txt").write_text(description, encoding="utf-8")
    (job_dir / "job-details.md").write_text(
        job_details_markdown(record, row=row, include_keyword_plan=(job_dir / "keywords.md").exists()),
        encoding="utf-8",
    )
    extracted_payload = {
        "job": record["job"],
        "source_ids": record["source_ids"],
        "extraction": record["extraction"],
        "match": record["match"],
        "duplicate_signals": record["duplicate_signals"],
        "artifact": _artifact_public(record["artifact"]),
    }
    (job_dir / "extracted.json").write_text(stable_json(extracted_payload) + "\n", encoding="utf-8")


def write_keyword_plan_review_file(
    store: SpaceStore,
    *,
    job_id: str,
    plan: dict[str, Any],
    validation: dict[str, Any],
    artifact_id: str,
    artifact_sha256: str,
) -> Path:
    """Mirror Agent A's latest keyword plan into the human-readable job review folder."""
    root = review_root(store)
    root.mkdir(parents=True, exist_ok=True)
    record = load_job_review_record(store, job_id)
    job_dir = job_review_dir(root, record)
    if not (job_dir / "job-details.md").exists():
        write_job_review_files(job_dir, record)
    keyword_path = job_dir / "keywords.md"
    keyword_path.write_text(
        keyword_plan_markdown(
            plan,
            validation=validation,
            artifact_id=artifact_id,
            artifact_sha256=artifact_sha256,
        ),
        encoding="utf-8",
    )
    (job_dir / "job-details.md").write_text(
        job_details_markdown(record, include_keyword_plan=True),
        encoding="utf-8",
    )
    return keyword_path


def write_latest_keyword_plan_review_file(store: SpaceStore, *, job_id: str) -> Path | None:
    """Backfill the readable keyword plan file from the latest stored Agent A artifact."""
    with store.connect() as db:
        row = db.execute(
            """
            SELECT * FROM job_keyword_plans
            WHERE job_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        artifact = db.execute(
            "SELECT * FROM artifacts WHERE id = ? ORDER BY version DESC LIMIT 1",
            (row["artifact_id"],),
        ).fetchone()
    if artifact is None:
        return None
    payload = json.loads(Path(artifact["storage_path"]).read_text(encoding="utf-8"))
    return write_keyword_plan_review_file(
        store,
        job_id=job_id,
        plan=payload["keyword_plan"],
        validation=payload["validation"],
        artifact_id=row["artifact_id"],
        artifact_sha256=row["artifact_sha256"],
    )


def write_index(
    root: Path,
    store: SpaceStore,
    *,
    rows: list[dict[str, Any]],
    run_id: str | None,
    summary: dict[str, Any] | None,
) -> Path:
    index_path = root / "index.md"
    lines = [
        "# Agent B Job Reviews",
        "",
        f"Updated: `{utc_now()}`",
    ]
    if run_id:
        lines.append(f"Run ID: `{run_id}`")
    if summary:
        lines.extend(["", "## Summary", ""])
        for key, value in summary.items():
            lines.append(f"- `{key}`: {value}")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("state") or "unknown"), []).append(row)
    lines.extend(["", "## Jobs", ""])
    if not rows:
        lines.append("No jobs were available when this index was generated.")
    for state in sorted(grouped):
        lines.extend(["", f"### {state}", ""])
        for row in grouped[state]:
            title = row.get("title") or "Unknown title"
            company = row.get("company") or "Unknown company"
            score = row.get("score")
            score_text = "unknown" if score is None else str(score)
            source = row.get("source_id") or "unknown_source"
            link = row.get("application_destination") or row.get("canonical_job_url") or row.get("link") or ""
            review_path = row.get("review_path")
            review_link = f"[details]({_index_link(review_path)}/job-details.md)" if review_path else "details unavailable"
            lines.append(f"- {review_link} | **{title}** | {company} | score={score_text} | source={source} | {link}")
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path


def row_from_record(record: dict[str, Any]) -> dict[str, Any]:
    job = record["job"]
    extraction = (record.get("extraction") or {}).get("record", {})
    match = record.get("match") or {}
    destination = _field_value(extraction, "application_destination") or job.get("canonical_url")
    return {
        "job_id": job["id"],
        "title": job.get("title"),
        "company": job.get("employer"),
        "state": match.get("decision") or job.get("status") or "unknown",
        "score": match.get("score"),
        "source_id": ", ".join(record.get("source_ids", [])),
        "link": job.get("canonical_url"),
        "canonical_job_url": job.get("canonical_url"),
        "application_destination": destination,
        "description_hash": job.get("description_hash"),
        "snapshot_artifact_id": job.get("snapshot_artifact_id"),
    }


def job_details_markdown(
    record: dict[str, Any],
    *,
    row: dict[str, Any] | None = None,
    include_keyword_plan: bool = False,
) -> str:
    job = record["job"]
    extraction = (record.get("extraction") or {}).get("record", {})
    match = record.get("match") or {}
    row = row or row_from_record(record)
    lines = [
        f"# {job.get('title') or 'Unknown Role'}",
        "",
        "## Review Summary",
        "",
        f"- Company: {job.get('employer') or 'Unknown'}",
        f"- Job ID: `{job['id']}`",
        f"- Source IDs: {', '.join(record.get('source_ids', [])) or 'Unknown'}",
        f"- State: {row.get('state') or match.get('decision') or job.get('status') or 'Unknown'}",
        f"- Score: {_text(row.get('score') if row.get('score') is not None else match.get('score'))}",
        f"- Retrieved At: `{job.get('retrieved_at') or 'Unknown'}`",
        f"- Canonical URL: {_link(job.get('canonical_url'))}",
        f"- Portal Link: {_link(row.get('portal_link') or row.get('link'))}",
        f"- Application Destination: {_link(row.get('application_destination') or _field_value(extraction, 'application_destination'))}",
        f"- Snapshot Artifact ID: `{job.get('snapshot_artifact_id') or 'Unknown'}`",
        f"- Description Hash: `{job.get('description_hash') or 'Unknown'}`",
        "",
        "## Files",
        "",
        "- [Exact job description](job-description.txt)",
        "- [Extracted JSON](extracted.json)",
    ]
    if include_keyword_plan:
        lines.append("- [Keyword plan](keywords.md)")
    lines.extend(["", "## Match", ""])
    for reason in row.get("review_reasons") or match.get("review_reasons") or []:
        lines.append(f"- {reason}")
    if not (row.get("review_reasons") or match.get("review_reasons")):
        lines.append("- No review reasons were recorded.")
    lines.extend(["", "## Freshness", ""])
    for key, value in (row.get("freshness") or {}).items():
        lines.append(f"- {key}: {_text(value)}")
    if not row.get("freshness"):
        lines.append("- No run freshness summary was recorded.")
    lines.extend(["", "## Extracted Details", ""])
    for key in (
        "title",
        "company",
        "locations",
        "work_arrangement",
        "seniority",
        "employment_type",
        "experience",
        "required_qualifications",
        "preferred_qualifications",
        "responsibilities",
        "compensation",
        "posting_date",
        "closing_date",
        "application_destination",
    ):
        lines.append(f"- {key}: {_text(_field_value(extraction, key))}")
    lines.extend(["", "## Warnings", ""])
    warnings = (record.get("extraction") or {}).get("warnings") or row.get("warnings") or []
    if warnings:
        for warning in warnings:
            lines.append(f"- `{warning.get('code', 'warning')}`: {warning.get('message', '')}")
    else:
        lines.append("- None")
    lines.extend(["", "## Unknown Fields", ""])
    unknowns = (record.get("extraction") or {}).get("unknown_fields") or row.get("unknown_fields") or []
    if unknowns:
        for unknown in unknowns:
            lines.append(f"- {unknown}")
    else:
        lines.append("- None")
    lines.extend(["", "## Duplicate Signals", ""])
    duplicates = record.get("duplicate_signals") or []
    if duplicates:
        for signal in duplicates:
            lines.append(
                f"- {signal.get('risk')}: {signal.get('signal_type')} = `{signal.get('signal_value')}`"
            )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def keyword_plan_markdown(
    plan: dict[str, Any],
    *,
    validation: dict[str, Any],
    artifact_id: str,
    artifact_sha256: str,
) -> str:
    model = plan.get("model") or {}
    prompt = plan.get("llm_prompt") or {}
    lines = [
        "# Keyword Plan",
        "",
        f"- Job ID: `{plan.get('job_id') or 'Unknown'}`",
        f"- Description Hash: `{plan.get('description_hash') or 'Unknown'}`",
        f"- Keyword Plan Artifact: `{artifact_id}`",
        f"- Keyword Plan SHA256: `{artifact_sha256}`",
        f"- Validation: `{validation.get('status') or 'unknown'}`",
        f"- Model: `{model.get('selected_model') or 'Unknown'}`",
        f"- Route: `{model.get('route_status') or 'Unknown'}`",
        f"- Provider Mode: `{model.get('provider_mode') or 'Unknown'}`",
        f"- Prompt Version: `{prompt.get('version') or 'Unknown'}`",
        f"- Created At: `{plan.get('created_at') or 'Unknown'}`",
        "",
        "## Priority Counts",
        "",
    ]
    for priority in ("high", "medium", "low"):
        lines.append(f"- {priority.title()}: {int((plan.get('priority_counts') or {}).get(priority) or 0)}")
    lines.extend(["", "## Mandate Counts", ""])
    for mandate in ("mandatory", "recommended", "optional"):
        lines.append(f"- {mandate.title()}: {int((plan.get('mandate_counts') or {}).get(mandate) or 0)}")
    for heading, mandate in (
        ("Mandatory Keywords", "mandatory"),
        ("Recommended Keywords", "recommended"),
        ("Optional Keywords", "optional"),
    ):
        lines.extend(["", f"## {heading}", ""])
        matching = [item for item in plan.get("keywords", []) if item.get("mandate") == mandate]
        if not matching:
            lines.append("- None")
            continue
        for item in matching:
            term = item.get("term") or "Unknown"
            priority = item.get("priority") or "unknown"
            category = item.get("category") or "unknown"
            rationale = item.get("rationale") or "No rationale recorded."
            lines.append(f"- **{term}** - {priority}, {category}: {rationale}")
            exact_terms = item.get("exact_terms") or []
            synonyms = item.get("synonyms") or []
            if exact_terms:
                lines.append(f"  - Exact terms: {', '.join(str(value) for value in exact_terms)}")
            if synonyms:
                lines.append(f"  - Synonyms: {', '.join(str(value) for value in synonyms)}")
    lines.extend(["", "## Warnings", ""])
    warnings = plan.get("warnings") or []
    if warnings:
        for warning in warnings:
            lines.append(f"- `{warning.get('code', 'warning')}`: {warning.get('reason') or warning.get('message') or ''}")
    else:
        lines.append("- None")
    lines.extend(["", "## Validation Findings", ""])
    findings = validation.get("findings") or []
    if findings:
        for finding in findings:
            lines.append(
                f"- `{finding.get('severity', 'unknown')}` `{finding.get('code', 'finding')}`: "
                f"{finding.get('message', '')}"
            )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def slugify(value: str, *, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    if not slug:
        slug = "unknown"
    return slug[:max_length].rstrip("-") or "unknown"


def short_job_id(job_id: str) -> str:
    suffix = job_id.split("_", 1)[-1]
    return suffix[:12] if suffix else job_id[:12]


def _match_payload(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if match is None:
        return None
    return {
        "id": match["id"],
        "policy_version": match["policy_version"],
        "profile_version": match["profile_version"],
        "hard_filter_results": json.loads(match["hard_filter_results_json"]),
        "preference_scores": json.loads(match["preference_scores_json"]),
        "score": match["score"],
        "coverage": json.loads(match["coverage_json"]),
        "decision": match["decision"],
        "gaps": json.loads(match["gaps_json"]),
        "review_reasons": json.loads(match["review_reasons_json"]),
        "explanation": json.loads(match["explanation_json"]),
        "created_at": match["created_at"],
    }


def _duplicate_payload(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_type": signal["signal_type"],
        "signal_value": signal["signal_value"],
        "matched_job_id": signal["matched_job_id"],
        "risk": signal["risk"],
        "details": json.loads(signal["details_json"]),
        "created_at": signal["created_at"],
    }


def _artifact_public(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "id": artifact["id"],
        "version": artifact["version"],
        "sha256": artifact["sha256"],
        "content_type": artifact["content_type"],
        "size_bytes": artifact["size_bytes"],
        "owner": artifact["owner"],
        "created_at": artifact["created_at"],
    }


def _field_value(extraction: dict[str, Any], key: str) -> Any:
    value = extraction.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _link(value: Any) -> str:
    if not value:
        return "Unknown"
    text = str(value)
    return f"[{text}]({text})" if text.startswith(("http://", "https://")) else text


def _text(value: Any) -> str:
    if value is None or value == "":
        return "Unknown"
    if isinstance(value, (dict, list)):
        return f"`{stable_json(value)}`"
    return str(value)


def _relative_to_private(store: SpaceStore, path: Path) -> str:
    try:
        return path.relative_to(store.paths.private_root).as_posix()
    except ValueError:
        return path.as_posix()


def _index_link(review_path: str) -> str:
    prefix = "job_reviews/"
    return review_path.removeprefix(prefix)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Agent B readable job review files.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    store = SpaceStore(SpacePaths.from_project_root(args.project_root))
    store.migrate()
    result = rebuild_job_review_workspace(store)
    print(
        stable_json(
            {
                "root": str(result.root),
                "index_path": str(result.index_path),
                "job_count": len(result.job_paths),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
