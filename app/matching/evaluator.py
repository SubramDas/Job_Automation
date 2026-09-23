"""Deterministic Phase 05 job matching and B-to-A handoff persistence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.storage.space import SpaceStore, new_id, stable_json, utc_now

_STOP_TERMS = {
    "and",
    "are",
    "for",
    "from",
    "have",
    "must",
    "or",
    "the",
    "to",
    "with",
    "work",
    "working",
    "skills",
    "skill",
    "requirements",
    "required",
}


@dataclass(frozen=True)
class MatchEvaluation:
    match_result_id: str
    handoff_id: str | None
    decision: str
    score: float | None
    coverage: dict[str, Any]
    review_reasons: list[str]


class JobMatcher:
    """Evaluates manual-imported jobs against the current preference policy."""

    def __init__(self, store: SpaceStore) -> None:
        self.store = store

    def evaluate(self, job_id: str) -> MatchEvaluation:
        with self.store.connect() as db:
            job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            extraction_row = db.execute(
                "SELECT * FROM job_extractions WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            policy_row = db.execute(
                """
                SELECT version, hard_constraints_json, weighted_preferences_json, exclusions_json
                FROM preference_policies ORDER BY version DESC LIMIT 1
                """
            ).fetchone()
            profile_version = db.execute(
                """
                SELECT COALESCE(MAX(version), 0) AS version
                FROM candidate_facts
                WHERE confirmation_state = 'confirmed'
                """
            ).fetchone()["version"]
            prior_rows = db.execute(
                "SELECT * FROM prior_applications ORDER BY created_at DESC"
            ).fetchall()
            duplicate_rows = db.execute(
                "SELECT * FROM job_duplicate_signals WHERE job_id = ?",
                (job_id,),
            ).fetchall()
            fact_rows = db.execute(
                """
                SELECT id, field_key, value_type, value_json, source_ref, version
                FROM candidate_facts
                WHERE confirmation_state = 'confirmed'
                  AND sensitivity = 'public'
                  AND (
                    field_key LIKE 'skills.%'
                    OR field_key LIKE 'work_history.%'
                    OR field_key LIKE 'projects.%'
                    OR field_key LIKE 'education.%'
                  )
                ORDER BY field_key, updated_at DESC
                """
            ).fetchall()
        if job is None or extraction_row is None:
            raise ValueError(f"cannot evaluate unknown or unextracted job: {job_id}")

        extraction = json.loads(extraction_row["extraction_json"])
        policy = _policy(policy_row)
        prior_applications = [dict(row) for row in prior_rows]
        duplicate_signals = [dict(row) for row in duplicate_rows]
        profile_evidence = profile_evidence_from_facts([dict(row) for row in fact_rows])
        requirement_coverage = requirement_coverage_for(extraction, profile_evidence)

        hard_results = hard_filter_results(extraction, policy, prior_applications, duplicate_signals)
        preference_scores = preference_scores_for(extraction, policy, requirement_coverage)
        score, coverage = aggregate_score(preference_scores)
        decision, review_reasons, gaps = route_decision(
            hard_results,
            score,
            coverage,
            extraction,
            requirement_coverage,
        )
        explanation = explain_match(
            extraction,
            hard_results,
            preference_scores,
            score,
            coverage,
            gaps,
            requirement_coverage,
            profile_evidence,
        )

        now = utc_now()
        match_result_id = new_id("match")
        handoff_id: str | None = None
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO match_results
                  (id, job_id, policy_version, profile_version, hard_filter_results_json,
                   preference_scores_json, score, coverage_json, decision, gaps_json,
                   review_reasons_json, explanation_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_result_id,
                    job_id,
                    policy["version"],
                    profile_version,
                    stable_json(hard_results),
                    stable_json(preference_scores),
                    score,
                    stable_json(coverage),
                    decision,
                    stable_json(gaps),
                    stable_json(review_reasons),
                    stable_json(explanation),
                    now,
                ),
            )
            if decision == "shortlisted":
                handoff_id = new_id("handoff")
                db.execute(
                    """
                    INSERT INTO b_to_a_handoffs (id, job_id, match_result_id, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        handoff_id,
                        job_id,
                        match_result_id,
                        stable_json(
                            {
                                "job_id": job_id,
                                "job_snapshot_artifact_id": job["snapshot_artifact_id"],
                                "job_description_hash": job["description_hash"],
                                "policy_version": policy["version"],
                                "profile_version": profile_version,
                                "requirements": {
                                    "required": extraction["required_qualifications"]["value"],
                                    "preferred": extraction["preferred_qualifications"]["value"],
                                    "responsibilities": extraction["responsibilities"]["value"],
                                },
                                "requirement_coverage": requirement_coverage,
                                "match_result_id": match_result_id,
                                "score": score,
                                "coverage": coverage,
                                "gaps": gaps,
                                "unresolved_issues": review_reasons,
                            }
                        ),
                        now,
                    ),
                )
            db.execute(
                """
                INSERT INTO audit_events
                  (id, actor, event_type, subject_type, subject_id, details_json, created_at)
                VALUES (?, 'agent_b_discovery', 'match_evaluated', 'job', ?, ?, ?)
                """,
                (
                    new_id("audit"),
                    job_id,
                    stable_json(
                        {
                            "match_result_id": match_result_id,
                            "decision": decision,
                            "score": score,
                            "coverage": coverage,
                            "handoff_id": handoff_id,
                            "review_reason_count": len(review_reasons),
                        }
                    ),
                    now,
                ),
            )
        return MatchEvaluation(
            match_result_id=match_result_id,
            handoff_id=handoff_id,
            decision=decision,
            score=score,
            coverage=coverage,
            review_reasons=review_reasons,
        )


def hard_filter_results(
    extraction: dict[str, Any],
    policy: dict[str, Any],
    prior_applications: list[dict[str, Any]],
    duplicate_signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results = [
        _work_arrangement_location_result(extraction),
        _employment_type_result(extraction),
        _experience_result(extraction),
        _compensation_result(extraction, policy),
        _duplicate_result(duplicate_signals),
        _prior_application_result(extraction, prior_applications),
    ]
    for exclusion in policy["exclusions"]:
        result = _exclusion_result(extraction, exclusion)
        if result:
            results.append(result)
    return results


def profile_evidence_from_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = []
    for fact in facts:
        value = json.loads(fact["value_json"])
        terms = sorted(_terms_for_fact(fact["field_key"], value))
        evidence.append(
            {
                "fact_id": fact["id"],
                "field_key": fact["field_key"],
                "value_type": fact["value_type"],
                "source_ref": fact["source_ref"],
                "version": fact["version"],
                "terms": terms,
            }
        )
    return evidence


def requirement_coverage_for(
    extraction: dict[str, Any],
    profile_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    required = extraction["required_qualifications"]["value"]
    coverage_items = []
    for requirement in required:
        matches = []
        requirement_terms = _terms_from_text(requirement)
        for fact in profile_evidence:
            common = requirement_terms & set(fact["terms"])
            if common:
                matches.append(
                    {
                        "fact_id": fact["fact_id"],
                        "field_key": fact["field_key"],
                        "matched_terms": sorted(common),
                    }
                )
        status = "supported" if matches else "missing"
        coverage_items.append({"requirement": requirement, "status": status, "evidence": matches})
    supported = sum(1 for item in coverage_items if item["status"] == "supported")
    total = len(coverage_items)
    return {
        "items": coverage_items,
        "supported": supported,
        "total": total,
        "ratio": round(supported / total, 2) if total else None,
        "profile_evidence_available": bool(profile_evidence),
    }


def preference_scores_for(
    extraction: dict[str, Any],
    policy: dict[str, Any],
    requirement_coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    configured = policy["weighted_preferences"] or _default_preferences()
    scores = []
    for preference in configured:
        field = preference.get("field", "unspecified")
        weight = float(preference.get("weight", 0))
        scores.append(_score_preference(field, weight, extraction, requirement_coverage))
    if not scores:
        scores = [
            _score_preference(item["field"], item["weight"], extraction, requirement_coverage)
            for item in _default_preferences()
        ]
    return scores


def aggregate_score(preference_scores: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any]]:
    known = [item for item in preference_scores if item["state"] == "known"]
    total_weight = sum(float(item["weight"]) for item in preference_scores)
    known_weight = sum(float(item["weight"]) for item in known)
    if not known or total_weight <= 0:
        return None, {"known_weight": 0, "total_weight": total_weight, "ratio": 0}
    score = 100 * sum(float(item["points"]) for item in known) / known_weight
    return round(score, 2), {
        "known_weight": known_weight,
        "total_weight": total_weight,
        "ratio": round(known_weight / total_weight, 2),
    }


def route_decision(
    hard_results: list[dict[str, Any]],
    score: float | None,
    coverage: dict[str, Any],
    extraction: dict[str, Any],
    requirement_coverage: dict[str, Any],
) -> tuple[str, list[str], list[dict[str, Any]]]:
    failures = [item for item in hard_results if item["state"] == "fail"]
    unknowns = [item for item in hard_results if item["state"] == "unknown" and item["critical"]]
    warnings = extraction.get("warnings", [])
    gaps = _gaps(extraction)
    if extraction["job_status"]["value"] == "closed":
        return "expired", ["description indicates the job is closed or unavailable"], gaps
    if failures:
        return "rejected_by_preferences", [item["reason"] for item in failures], gaps
    if unknowns:
        return "needs_review", [item["reason"] for item in unknowns], gaps
    if any(item["risk"] == "ambiguous" for item in hard_results if item["key"] == "duplicate"):
        return "needs_review", ["ambiguous duplicate risk requires review"], gaps
    if warnings:
        return "needs_review", [warning["message"] for warning in warnings], gaps
    if score is None or coverage["ratio"] < 0.5:
        return "needs_review", ["insufficient known fields for automatic shortlisting"], gaps
    if requirement_coverage["profile_evidence_available"] and requirement_coverage["ratio"] is not None:
        if requirement_coverage["ratio"] < 0.5:
            return "needs_review", ["candidate evidence covers less than half of stated requirements"], gaps
    if score >= 80 and coverage["ratio"] >= 0.65:
        return "shortlisted", [], gaps
    if score >= 65:
        return "needs_review", ["borderline match score"], gaps
    return "rejected_by_preferences", ["weighted preference score below review threshold"], gaps


def explain_match(
    extraction: dict[str, Any],
    hard_results: list[dict[str, Any]],
    preference_scores: list[dict[str, Any]],
    score: float | None,
    coverage: dict[str, Any],
    gaps: list[dict[str, Any]],
    requirement_coverage: dict[str, Any],
    profile_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "summary": {
            "company": extraction["company"]["value"],
            "title": extraction["title"]["value"],
            "score": score,
            "coverage": coverage,
        },
        "hard_filters": hard_results,
        "preferences": preference_scores,
        "requirement_coverage": requirement_coverage,
        "gaps": gaps,
        "candidate_evidence_count": len(profile_evidence),
        "candidate_evidence_note": "Only confirmed public skill/work/project/education facts are used by Agent B.",
    }


def _policy(row: Any) -> dict[str, Any]:
    if row is None:
        return {"version": None, "hard_constraints": [], "weighted_preferences": [], "exclusions": []}
    return {
        "version": row["version"],
        "hard_constraints": json.loads(row["hard_constraints_json"]),
        "weighted_preferences": json.loads(row["weighted_preferences_json"]),
        "exclusions": json.loads(row["exclusions_json"]),
    }


def _work_arrangement_location_result(extraction: dict[str, Any]) -> dict[str, Any]:
    arrangement = extraction["work_arrangement"]["value"]
    locations = {_norm_location(item) for item in extraction["locations"]["value"]}
    allowed = {"bengaluru", "hyderabad"}
    if arrangement is None or arrangement == "ambiguous":
        return _hard("work_arrangement_location", "unknown", "work arrangement is unknown or ambiguous")
    if arrangement in {"onsite", "hybrid"}:
        if not locations:
            return _hard("work_arrangement_location", "unknown", "onsite/hybrid location is unknown")
        if locations & allowed:
            return _hard("work_arrangement_location", "pass", "onsite/hybrid role includes Bengaluru or Hyderabad")
        return _hard("work_arrangement_location", "fail", "onsite/hybrid role is outside Bengaluru/Hyderabad")
    return _hard("work_arrangement_location", "pass", "remote role may be elsewhere")


def _employment_type_result(extraction: dict[str, Any]) -> dict[str, Any]:
    employment_type = extraction["employment_type"]["value"]
    if employment_type is None:
        return _hard("employment_type", "unknown", "employment type is unknown")
    if employment_type == "full_time_permanent":
        return _hard("employment_type", "pass", "role is full-time or permanent")
    return _hard("employment_type", "fail", f"role employment type is {employment_type}")


def _experience_result(extraction: dict[str, Any]) -> dict[str, Any]:
    experience = extraction["experience"]["value"]
    if not experience:
        return _hard("experience", "unknown", "experience requirement is unknown")
    minimum = experience.get("minimum_years")
    maximum = experience.get("maximum_years")
    if minimum is not None and minimum > 3:
        return _hard("experience", "fail", "minimum experience is above the 1-3 year target")
    if maximum is not None and maximum < 1:
        return _hard("experience", "fail", "maximum experience is below the 1-3 year target")
    if maximum is None and minimum is not None and minimum <= 3:
        return _hard("experience", "pass", "minimum experience is within target; upper bound unknown")
    return _hard("experience", "pass", "experience range overlaps 1-3 years")


def _compensation_result(extraction: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    compensation = extraction["compensation"]["value"]
    if not compensation:
        return _hard("compensation", "pass", "compensation is unstated; Phase 00 says not to reject")
    if compensation.get("currency") is None or compensation.get("unit") is None:
        return _hard("compensation", "unknown", "compensation is stated but unit or currency is incomplete")
    current = _current_ctc(policy)
    if current is None:
        return _hard("compensation", "unknown", "current CTC is private or unavailable for comparison")
    minimum = compensation.get("minimum")
    if minimum is None:
        return _hard("compensation", "unknown", "compensation minimum is unavailable")
    if minimum > current:
        return _hard("compensation", "pass", "stated minimum exceeds configured current CTC")
    return _hard("compensation", "fail", "stated minimum does not exceed configured current CTC")


def _duplicate_result(duplicate_signals: list[dict[str, Any]]) -> dict[str, Any]:
    risks = {row["risk"] for row in duplicate_signals}
    if "exact" in risks:
        return _hard("duplicate", "fail", "exact duplicate job already exists", critical=True, risk="exact")
    if "ambiguous" in risks:
        return _hard("duplicate", "unknown", "ambiguous duplicate signal found", critical=True, risk="ambiguous")
    return _hard("duplicate", "pass", "no duplicate signal found", critical=True, risk="none")


def _prior_application_result(extraction: dict[str, Any], prior_applications: list[dict[str, Any]]) -> dict[str, Any]:
    company = extraction["company"]["value"]
    title = extraction["title"]["value"]
    if not company or not title:
        return _hard("prior_application", "unknown", "company/title unknown for reapplication check")
    for prior in prior_applications:
        if _same_text(company, prior["company"]) and _same_text(title, prior["role"]):
            return _hard("prior_application", "unknown", "possible reapplication requires manual review")
    return _hard("prior_application", "pass", "no prior application with same company/title found")


def _exclusion_result(extraction: dict[str, Any], exclusion: dict[str, Any]) -> dict[str, Any] | None:
    field = exclusion.get("field")
    value = str(exclusion.get("value", "")).lower()
    if not field or not value:
        return None
    extracted = extraction.get(field, {}).get("value")
    if extracted is None:
        return _hard(f"exclusion:{field}", "unknown", f"exclusion field {field} is unknown")
    haystack = stable_json(extracted).lower()
    if value in haystack:
        return _hard(f"exclusion:{field}", "fail", f"excluded {field} value appears in posting")
    return _hard(f"exclusion:{field}", "pass", f"excluded {field} value not found")


def _score_preference(
    field: str,
    weight: float,
    extraction: dict[str, Any],
    requirement_coverage: dict[str, Any],
) -> dict[str, Any]:
    if field in {"skills", "required_skills", "required skills with evidence"}:
        required = extraction["required_qualifications"]["value"]
        if requirement_coverage["profile_evidence_available"] and requirement_coverage["ratio"] is not None:
            value_score = 45 + 55 * requirement_coverage["ratio"]
            evidence = requirement_coverage["items"]
        else:
            value_score = min(100, 70 + 8 * len(required))
            evidence = required[:5]
        return _score(field, weight, value_score, "known" if required else "unknown", evidence)
    if field in {"responsibilities", "relevant responsibilities and demonstrated work"}:
        responsibilities = extraction["responsibilities"]["value"]
        return _score(field, weight, min(100, 75 + 7 * len(responsibilities)), "known" if responsibilities else "unknown", responsibilities[:5])
    if field in {"seniority", "experience", "seniority and experience alignment"}:
        experience = extraction["experience"]["value"]
        state = "known" if experience else "unknown"
        value_score = 90 if experience else 0
        return _score(field, weight, value_score, state, experience)
    if field in {"location", "work_mode", "work arrangement and location preference"}:
        arrangement = extraction["work_arrangement"]["value"]
        locations = extraction["locations"]["value"]
        state = "known" if arrangement and (arrangement == "remote" or locations) else "unknown"
        value_score = 92 if state == "known" else 0
        return _score(field, weight, value_score, state, {"work_arrangement": arrangement, "locations": locations})
    if field in {"compensation", "compensation preference"}:
        compensation = extraction["compensation"]["value"]
        state = "known" if compensation else "unknown"
        return _score(field, weight, 75 if compensation else 0, state, compensation)
    if field in {"industry", "company", "industry/company preference"}:
        company = extraction["company"]["value"]
        return _score(field, weight, 80 if company else 0, "known" if company else "unknown", company)
    return _score(field, weight, 0, "unknown", None)


def _score(field: str, weight: float, value_score: float, state: str, evidence: Any) -> dict[str, Any]:
    return {
        "field": field,
        "weight": weight,
        "state": state,
        "field_score": value_score if state == "known" else None,
        "points": round(weight * value_score / 100, 2) if state == "known" else 0,
        "evidence": evidence,
    }


def _gaps(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"field": field, "reason": "not stated in description"} for field in extraction.get("unknown_fields", [])]


def _terms_for_fact(field_key: str, value: Any) -> set[str]:
    terms = _terms_from_text(field_key.replace(".", " "))
    if isinstance(value, str):
        terms |= _terms_from_text(value)
    elif isinstance(value, bool):
        if value:
            terms |= _terms_from_text(field_key.split(".")[-1])
    elif isinstance(value, list):
        for item in value:
            terms |= _terms_from_text(str(item))
    elif isinstance(value, dict):
        for item in value.values():
            terms |= _terms_from_text(str(item))
    return terms - _STOP_TERMS


def _terms_from_text(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9+#.]+", value.lower()) if len(term) > 1} - _STOP_TERMS


def _hard(key: str, state: str, reason: str, *, critical: bool = True, risk: str | None = None) -> dict[str, Any]:
    result = {"key": key, "state": state, "reason": reason, "critical": critical}
    if risk is not None:
        result["risk"] = risk
    return result


def _default_preferences() -> list[dict[str, Any]]:
    return [
        {"field": "skills", "weight": 35},
        {"field": "responsibilities", "weight": 25},
        {"field": "experience", "weight": 15},
        {"field": "location", "weight": 10},
        {"field": "compensation", "weight": 10},
        {"field": "company", "weight": 5},
    ]


def _current_ctc(policy: dict[str, Any]) -> float | None:
    for constraint in policy["hard_constraints"]:
        if constraint.get("field") == "current_annual_total_ctc":
            value = constraint.get("value")
            return float(value) if value is not None else None
    return None


def _same_text(left: str, right: str) -> bool:
    return _norm_text(left) == _norm_text(right)


def _norm_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _norm_location(value: str) -> str:
    normalized = _norm_text(value)
    return "bengaluru" if normalized == "bangalore" else normalized
