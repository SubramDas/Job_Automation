"""Phase 06 Agent A keyword planning.

Agent A runs through Codex + MCP: Codex reads the saved job description through
`jobs.get_job`, generates the ranked keyword plan in-session, then stores that structured
plan through `jobs.save_keyword_plan`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.storage.space import ArtifactRecord, SpaceStore, new_id, stable_json, utc_now

KEYWORD_PLAN_CONTENT_TYPE = "application/vnd.job.keyword-plan+json"
PROMPT_VERSION = "agent-a-keyword-plan-v1"

CATEGORY_BY_TERM = {
    "python": "skill",
    "java": "skill",
    "javascript": "skill",
    "typescript": "skill",
    "sql": "skill",
    "rest api": "responsibility",
    "rest apis": "responsibility",
    "api": "responsibility",
    "apis": "responsibility",
    "backend": "responsibility",
    "software engineer": "seniority_signal",
    "software engineering": "seniority_signal",
    "distributed systems": "domain_term",
    "microservices": "architecture",
    "kubernetes": "platform",
    "docker": "platform",
    "aws": "platform",
    "gcp": "platform",
    "azure": "platform",
    "observability": "responsibility",
    "incident response": "responsibility",
    "incident-response": "responsibility",
    "clickhouse": "tool",
    "postgresql": "tool",
    "postgres": "tool",
    "mysql": "tool",
    "redis": "tool",
    "kafka": "tool",
    "anthropic": "domain_term",
    "llm": "domain_term",
    "large language models": "domain_term",
    "machine learning": "domain_term",
    "data pipelines": "responsibility",
    "etl": "responsibility",
}

STOP_TERMS = {
    "responsibilities",
    "requirements",
    "qualifications",
    "preferred qualifications",
    "about us",
    "benefits",
    "apply",
    "company",
    "location",
    "employment type",
    "work mode",
    "all qualified applicants",
    "equal opportunity",
}

@dataclass(frozen=True)
class KeywordPlanResult:
    status: str
    job_id: str
    keyword_plan_id: str
    artifact: ArtifactRecord
    plan: dict[str, Any]
    validation: dict[str, Any]


def save_keyword_plan(
    store: SpaceStore,
    *,
    job_id: str,
    keywords: list[dict[str, Any]],
    warnings: list[dict[str, Any]] | None = None,
    model: dict[str, Any] | None = None,
    prompt_version: str = PROMPT_VERSION,
) -> KeywordPlanResult:
    """Persist a keyword plan produced by Codex through the MCP tool boundary."""

    job_payload = _load_job_payload(store, job_id)
    description = job_payload["description"]
    normalized_keywords, normalized_warnings = normalize_keyword_items(
        keywords,
        description=description,
        extraction=job_payload.get("extraction", {}),
    )
    merged_warnings = [*(warnings or []), *normalized_warnings]
    model_metadata = {
        "agent_id": "agent_a_resume",
        "stage": "keyword_planning",
        "selected_model": str((model or {}).get("selected_model") or "codex-session-model"),
        "route_status": str((model or {}).get("route_status") or "codex_mcp_in_session"),
        "provider_mode": str((model or {}).get("provider_mode") or "codex_mcp"),
        "input_hash": hashlib.sha256(description.encode("utf-8")).hexdigest(),
        "estimated_tokens": int((model or {}).get("estimated_tokens") or max(1, len(description.split()))),
        "estimated_cost": float((model or {}).get("estimated_cost") or 0.0),
    }
    plan = _base_plan(job_payload, model_metadata, keywords=normalized_keywords, warnings=merged_warnings)
    if "response_id" in (model or {}):
        plan["model"]["response_id"] = model["response_id"]
    plan["llm_prompt"] = {
        "version": prompt_version,
        "system_summary": "Codex session generated keywords from job description only; no resume files were read or edited.",
        "input_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest(),
    }
    validation = validate_keyword_plan(plan)
    artifact = _persist_plan(store, job_id=job_id, plan=plan, validation=validation)
    keyword_plan_id = _record_keyword_plan(store, job_id=job_id, artifact=artifact, plan=plan, validation=validation)
    _write_review_keyword_plan(store, job_id=job_id, artifact=artifact, plan=plan, validation=validation)
    status = "validated" if validation["status"] == "passed" else "validation_failed"
    return KeywordPlanResult(status, job_id, keyword_plan_id, artifact, plan, validation)


def validate_keyword_plan(plan: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    required = {"job_id", "description_hash", "keywords", "priority_counts", "warnings", "model"}
    missing = sorted(required - set(plan))
    if missing:
        findings.append(_finding("schema_missing_fields", "blocking", f"missing fields: {', '.join(missing)}"))
    for index, item in enumerate(plan.get("keywords", [])):
        for field in ("term", "priority", "mandate", "category", "rationale", "review_status"):
            if field not in item:
                findings.append(_finding("keyword_schema_invalid", "blocking", f"keyword {index} missing {field}"))
        if item.get("priority") not in {"high", "medium", "low"}:
            findings.append(_finding("priority_invalid", "blocking", f"keyword {index} has invalid priority"))
        if item.get("mandate") not in {"mandatory", "recommended", "optional"}:
            findings.append(_finding("mandate_invalid", "blocking", f"keyword {index} has invalid mandate"))
        unsafe_text = stable_json(item).lower()
        if any(phrase in unsafe_text for phrase in ("guarantee", "top of the ats", "top ranking", "interview guaranteed")):
            findings.append(_finding("unsafe_outcome_claim", "blocking", f"keyword {index} contains unsafe outcome language"))
    if not plan.get("keywords"):
        findings.append(_finding("no_keywords", "warning", "no resume-relevant keywords were extracted"))
    status = "blocking_failure" if any(f["severity"] == "blocking" for f in findings) else "passed"
    return {"status": status, "findings": findings, "checked_at": utc_now()}


def _load_job_payload(store: SpaceStore, job_id: str) -> dict[str, Any]:
    with store.connect() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise ValueError("unknown job id")
        extraction = db.execute(
            "SELECT * FROM job_extractions WHERE job_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        artifact = db.execute(
            "SELECT * FROM artifacts WHERE id = ? ORDER BY version DESC LIMIT 1",
            (job["snapshot_artifact_id"],),
        ).fetchone()
    description = ""
    if artifact is not None:
        description = Path(artifact["storage_path"]).read_text(encoding="utf-8")
    return {
        "job": dict(job),
        "description": description,
        "extraction": json.loads(extraction["extraction_json"]) if extraction is not None else {},
    }


def normalize_keyword_items(
    keywords: list[dict[str, Any]],
    *,
    description: str,
    extraction: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize MCP-submitted keyword items into the persisted plan schema."""

    normalized: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(keywords):
        if not isinstance(raw, dict):
            warnings.append({"code": "keyword_ignored", "reason": f"keyword {index} was not an object"})
            continue
        term = _normalize_term(str(raw.get("term", "")))
        if not term:
            warnings.append({"code": "keyword_ignored", "reason": f"keyword {index} had an empty term"})
            continue
        lowered = term.lower()
        if lowered in seen or lowered in STOP_TERMS:
            continue
        seen.add(lowered)
        priority = raw.get("priority") if raw.get("priority") in {"high", "medium", "low"} else "low"
        mandate = raw.get("mandate") if raw.get("mandate") in {"mandatory", "recommended", "optional"} else (
            "mandatory" if priority == "high" else "recommended" if priority == "medium" else "optional"
        )
        category = raw.get("category") if raw.get("category") in {"skill", "tool", "platform", "responsibility", "domain_term", "seniority_signal", "architecture"} else _infer_category(term)
        exact = _exact_occurrence(term, description)
        normalized.append(
            {
                "term": term,
                "priority": priority,
                "mandate": mandate,
                "category": category,
                "wording": raw.get("wording") if raw.get("wording") in {"exact", "synonym_or_inferred"} else ("exact" if exact else "synonym_or_inferred"),
                "exact_terms": [str(value) for value in raw.get("exact_terms", []) if str(value).strip()][:5] or ([term] if exact else []),
                "synonyms": [str(value) for value in raw.get("synonyms", []) if str(value).strip()][:5],
                "frequency": int(raw.get("frequency") or len(re.findall(r"\b" + re.escape(term.lower()) + r"\b", description.lower())) or 1),
                "review_status": str(raw.get("review_status") or "ready_for_manual_resume_review"),
                "rationale": str(raw.get("rationale") or _rationale(term, priority, mandate, False, False, False, 1))[:400],
            }
        )
    normalized.sort(key=lambda item: ({"high": 0, "medium": 1, "low": 2}[item["priority"]], item["category"], item["term"].lower()))
    return normalized[:60], warnings



def _normalize_term(term: str) -> str:
    cleaned = re.sub(r"\s+", " ", term.strip(" \t\n\r-•*:.;"))
    cleaned = re.sub(r"^(build|building|design|develop|maintain|own|work with|experience with)\s+", "", cleaned, flags=re.IGNORECASE)
    if not cleaned or cleaned.lower().startswith(("title ", "company ", "job id ")):
        return ""
    known = {
        "rest api": "REST APIs",
        "rest apis": "REST APIs",
        "apis": "APIs",
        "api": "APIs",
        "sql": "SQL",
        "aws": "AWS",
        "gcp": "GCP",
        "llm": "LLM",
        "llms": "LLM",
    }
    return known.get(cleaned.lower(), cleaned[:1].upper() + cleaned[1:] if cleaned.islower() else cleaned)


def _infer_category(term: str) -> str:
    lowered = term.lower()
    if any(token in lowered for token in ("engineer", "senior", "junior")):
        return "seniority_signal"
    if any(token in lowered for token in ("api", "service", "pipeline", "incident", "test", "build")):
        return "responsibility"
    if re.fullmatch(r"[A-Z0-9+#.]{2,}", term):
        return "skill"
    return "domain_term"


def _exact_occurrence(term: str, text: str) -> bool:
    return bool(re.search(r"\b" + re.escape(term) + r"\b", text, flags=re.IGNORECASE))


def _rationale(term: str, priority: str, mandate: str, in_required: bool, in_preferred: bool, in_responsibility: bool, frequency: int) -> str:
    if in_required:
        return f"{term} appears in required qualifications, so it is a {priority}-priority {mandate} term for manual review."
    if in_preferred:
        return f"{term} appears in preferred qualifications, so it is useful but not mandatory."
    if in_responsibility:
        return f"{term} appears in role responsibilities and can help align relevant experience if truthful."
    if frequency >= 2:
        return f"{term} appears multiple times in the posting, indicating role relevance."
    return f"{term} appears in the posting and may be useful if it matches the user's real experience."


def _base_plan(job_payload: dict[str, Any], model: dict[str, Any], *, keywords: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"high": 0, "medium": 0, "low": 0}
    mandate_counts = {"mandatory": 0, "recommended": 0, "optional": 0}
    for item in keywords:
        counts[item["priority"]] += 1
        mandate_counts[item["mandate"]] += 1
    job = job_payload["job"]
    return {
        "job_id": job["id"],
        "description_hash": job["description_hash"],
        "snapshot_artifact_id": job["snapshot_artifact_id"],
        "created_at": utc_now(),
        "model": model,
        "keywords": keywords,
        "priority_counts": counts,
        "mandate_counts": mandate_counts,
        "warnings": warnings,
        "manual_resume_editing_only": True,
    }


def _persist_plan(store: SpaceStore, *, job_id: str, plan: dict[str, Any], validation: dict[str, Any]) -> ArtifactRecord:
    payload = stable_json({"keyword_plan": plan, "validation": validation}).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    with store.connect() as db:
        existing = db.execute(
            """
            SELECT id FROM artifacts
            WHERE sha256 = ? AND owner = 'agent_a_resume'
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (digest,),
        ).fetchone()
        if existing is not None:
            row = db.execute("SELECT * FROM artifacts WHERE id = ? ORDER BY version DESC LIMIT 1", (existing["id"],)).fetchone()
            return ArtifactRecord(
                artifact_id=row["id"],
                version=row["version"],
                sha256=row["sha256"],
                content_type=row["content_type"],
                size_bytes=row["size_bytes"],
                owner=row["owner"],
                path=Path(row["storage_path"]),
                created_at=row["created_at"],
            )
    artifact = store.artifacts.put_bytes(
        payload,
        filename="keyword-plan.json",
        content_type=KEYWORD_PLAN_CONTENT_TYPE,
        owner="agent_a_resume",
        artifact_id=new_id("kwplan_artifact"),
    )
    store.record_artifact(artifact)
    return artifact


def _record_keyword_plan(store: SpaceStore, *, job_id: str, artifact: ArtifactRecord, plan: dict[str, Any], validation: dict[str, Any]) -> str:
    plan_id = new_id("kwplan")
    now = utc_now()
    with store.connect() as db:
        db.execute(
            """
            INSERT INTO job_keyword_plans
              (id, job_id, artifact_id, artifact_sha256, description_hash, model_json,
               priority_counts_json, mandate_counts_json, warnings_json, validation_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                job_id,
                artifact.artifact_id,
                artifact.sha256,
                plan["description_hash"],
                stable_json(plan["model"]),
                stable_json(plan["priority_counts"]),
                stable_json(plan["mandate_counts"]),
                stable_json(plan["warnings"]),
                stable_json(validation),
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO audit_events
              (id, actor, event_type, subject_type, subject_id, details_json, created_at)
            VALUES (?, 'agent_a_resume', 'keyword_plan_created', 'job', ?, ?, ?)
            """,
            (
                new_id("audit"),
                job_id,
                stable_json(
                    {
                        "keyword_plan_id": plan_id,
                        "artifact_id": artifact.artifact_id,
                        "artifact_sha256": artifact.sha256,
                        "description_hash": plan["description_hash"],
                        "priority_counts": plan["priority_counts"],
                        "validation_status": validation["status"],
                    }
                ),
                now,
            ),
        )
    return plan_id


def _write_review_keyword_plan(
    store: SpaceStore,
    *,
    job_id: str,
    artifact: ArtifactRecord,
    plan: dict[str, Any],
    validation: dict[str, Any],
) -> None:
    from app.discovery.job_review_workspace import write_keyword_plan_review_file

    write_keyword_plan_review_file(
        store,
        job_id=job_id,
        plan=plan,
        validation=validation,
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.sha256,
    )


def _finding(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}
