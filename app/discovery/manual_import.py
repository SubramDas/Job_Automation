"""Manual job import, extraction, and persistence for Phase 05."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.storage.space import SpaceError, SpaceStore, new_id, stable_json, utc_now

MAX_DESCRIPTION_CHARS = 50_000


@dataclass(frozen=True)
class ManualImportResult:
    job_id: str
    description_hash: str
    snapshot_artifact_id: str
    extraction_id: str
    duplicate_signals: list[dict[str, Any]]
    extraction: dict[str, Any]


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    stripped = url.strip()
    parts = urlsplit(stripped)
    if not parts.scheme or not parts.netloc:
        return stripped
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def description_hash(description: str) -> str:
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


class ManualJobImporter:
    """Accepts pasted descriptions and stores normalized Agent B records."""

    def __init__(self, store: SpaceStore) -> None:
        self.store = store

    def import_job(self, *, source_id: str, url: str | None, description: str) -> ManualImportResult:
        if not source_id:
            raise SpaceError("source id is required for job ingestion")
        text = description.strip()
        if not text:
            raise SpaceError("manual job description is required")
        if len(text) > MAX_DESCRIPTION_CHARS:
            raise SpaceError("manual job description exceeds Phase 05 payload limit")

        canonical_url = canonicalize_url(url)
        extracted = extract_job_description(text, canonical_url=canonical_url)
        digest = description_hash(text)
        now = utc_now()

        job_id = new_id("job")
        normalized_identity = normalized_job_identity(extracted, canonical_url, digest)
        source_key = source_identity(source_id, canonical_url, extracted, digest)
        with self.store.connect() as db:
            duplicate_signals = detect_duplicate_signals(
                db,
                canonical_url=canonical_url,
                employer=extracted["company"]["value"],
                requisition_id=extracted["requisition_id"]["value"],
                normalized_identity=normalized_identity,
                description_hash=digest,
                title=extracted["title"]["value"],
                locations=extracted["locations"]["value"],
            )
            exact_duplicate = next(
                (signal for signal in duplicate_signals if signal["risk"] == "exact" and signal.get("matched_job_id")),
                None,
            )
            if exact_duplicate is not None:
                existing = db.execute(
                    "SELECT * FROM jobs WHERE id = ?",
                    (exact_duplicate["matched_job_id"],),
                ).fetchone()
                extraction_row = db.execute(
                    "SELECT id, extraction_json FROM job_extractions WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                    (exact_duplicate["matched_job_id"],),
                ).fetchone()
                db.execute(
                    """
                    INSERT INTO audit_events
                      (id, actor, event_type, subject_type, subject_id, details_json, created_at)
                    VALUES (?, 'agent_b_discovery', 'job_duplicate_reused', 'job', ?, ?, ?)
                    """,
                    (
                        new_id("audit"),
                        exact_duplicate["matched_job_id"],
                        stable_json(
                            {
                                "source_id": source_id,
                                "description_hash": digest,
                                "duplicate_signal": exact_duplicate,
                            }
                        ),
                        now,
                    ),
                )
                return ManualImportResult(
                    job_id=exact_duplicate["matched_job_id"],
                    description_hash=existing["description_hash"] if existing is not None else digest,
                    snapshot_artifact_id=existing["snapshot_artifact_id"] if existing is not None else "",
                    extraction_id=extraction_row["id"] if extraction_row is not None else "",
                    duplicate_signals=duplicate_signals,
                    extraction=json.loads(extraction_row["extraction_json"]) if extraction_row is not None else extracted,
                )
            artifact = self.store.artifacts.put_bytes(
                text.encode("utf-8"),
                filename="job-description.txt",
                content_type="text/plain",
                owner="jobs",
                artifact_id=new_id("jobdesc"),
            )
            self.store.record_artifact(artifact)
            db.execute(
                """
                INSERT INTO jobs
                  (id, canonical_url, employer, requisition_id, title, normalized_identity,
                   description_hash, retrieved_at, status, snapshot_artifact_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'extracted', ?, ?)
                """,
                (
                    job_id,
                    canonical_url,
                    extracted["company"]["value"],
                    extracted["requisition_id"]["value"],
                    extracted["title"]["value"],
                    normalized_identity,
                    digest,
                    now,
                    artifact.artifact_id,
                    now,
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO job_source_ids(job_id, source_id) VALUES (?, ?)",
                (job_id, source_key),
            )
            extraction_id = new_id("jobextract")
            db.execute(
                """
                INSERT INTO job_extractions
                  (id, job_id, extraction_json, evidence_json, warnings_json,
                   unknown_fields_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extraction_id,
                    job_id,
                    stable_json(extracted),
                    stable_json(evidence_map(extracted)),
                    stable_json(extracted["warnings"]),
                    stable_json(extracted["unknown_fields"]),
                    now,
                ),
            )
            for signal in duplicate_signals:
                db.execute(
                    """
                    INSERT INTO job_duplicate_signals
                      (id, job_id, signal_type, signal_value, matched_job_id, risk,
                       details_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("dupsig"),
                        job_id,
                        signal["signal_type"],
                        signal["signal_value"],
                        signal.get("matched_job_id"),
                        signal["risk"],
                        stable_json(signal.get("details", {})),
                        now,
                    ),
                )
            db.execute(
                """
                INSERT INTO audit_events
                  (id, actor, event_type, subject_type, subject_id, details_json, created_at)
                VALUES (?, 'agent_b_discovery', 'job_imported', 'job', ?, ?, ?)
                """,
                (
                    new_id("audit"),
                    job_id,
                    stable_json(
                        {
                            "source_id": source_id,
                            "description_hash": digest,
                            "snapshot_artifact_id": artifact.artifact_id,
                            "extraction_id": extraction_id,
                            "duplicate_risks": sorted({signal["risk"] for signal in duplicate_signals}),
                        }
                    ),
                    now,
                ),
            )
        return ManualImportResult(
            job_id=job_id,
            description_hash=digest,
            snapshot_artifact_id=artifact.artifact_id,
            extraction_id=extraction_id,
            duplicate_signals=duplicate_signals,
            extraction=extracted,
        )


def source_identity(source_id: str, canonical_url: str | None, extracted: dict[str, Any], digest: str) -> str:
    requisition_id = extracted["requisition_id"]["value"]
    if requisition_id:
        return f"{source_id}:requisition:{_norm(requisition_id)}"
    if canonical_url:
        return f"{source_id}:url:{canonical_url}"
    return f"{source_id}:hash:{digest}"


def normalized_job_identity(extracted: dict[str, Any], canonical_url: str | None, digest: str) -> str:
    employer = _norm(extracted["company"]["value"] or "unknown")
    req = _norm(extracted["requisition_id"]["value"] or "")
    title = _norm(extracted["title"]["value"] or "unknown")
    locations = ",".join(_norm(location) for location in extracted["locations"]["value"])
    if req and employer != "unknown":
        return f"{employer}|req:{req}"
    if canonical_url:
        return f"url|{canonical_url}"
    return f"{employer}|{title}|{locations}|{digest[:12]}"


def extract_job_description(text: str, *, canonical_url: str | None) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    extraction: dict[str, Any] = {
        "source_url": _field(canonical_url, None),
        "title": _field(_find_label(lines, ("title", "job title", "role")) or _first_title(lines), None),
        "company": _field(_find_label(lines, ("company", "employer", "organization")), None),
        "requisition_id": _field(_find_requisition(text), None),
        "locations": _field(_find_locations(text), None),
        "work_arrangement": _field(_find_work_arrangement(text), None),
        "seniority": _field(_find_seniority(text), None),
        "employment_type": _field(_find_employment_type(text), None),
        "experience": _field(_find_experience(text), None),
        "required_qualifications": _field(_extract_section_items(text, required=True), None),
        "preferred_qualifications": _field(_extract_section_items(text, required=False), None),
        "responsibilities": _field(_extract_responsibilities(text), None),
        "compensation": _field(_find_compensation(text), None),
        "posting_date": _field(_find_date(text, ("posted", "posting date", "date posted")), None),
        "closing_date": _field(_find_date(text, ("closing", "last date", "deadline", "apply by")), None),
        "job_status": _field(_find_job_status(text), None),
        "application_destination": _field(_find_application_destination(text, canonical_url), None),
        "warnings": [],
        "unknown_fields": [],
    }
    _attach_spans(extraction, text)
    _derive_unknowns_and_warnings(extraction, text)
    return extraction


def evidence_map(extraction: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get("evidence")
        for key, value in extraction.items()
        if isinstance(value, dict) and value.get("evidence") is not None
    }


def detect_duplicate_signals(
    db: Any,
    *,
    canonical_url: str | None,
    employer: str | None,
    requisition_id: str | None,
    normalized_identity: str,
    description_hash: str,
    title: str | None,
    locations: list[str],
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    if canonical_url:
        row = db.execute("SELECT id FROM jobs WHERE canonical_url = ?", (canonical_url,)).fetchone()
        if row:
            signals.append(_signal("canonical_url", canonical_url, "exact", row["id"]))
    if employer and requisition_id:
        row = db.execute(
            "SELECT id FROM jobs WHERE lower(employer) = lower(?) AND lower(requisition_id) = lower(?)",
            (employer, requisition_id),
        ).fetchone()
        if row:
            signals.append(_signal("employer_requisition", f"{employer}|{requisition_id}", "exact", row["id"]))
    row = db.execute(
        "SELECT id FROM jobs WHERE normalized_identity = ? AND description_hash = ?",
        (normalized_identity, description_hash),
    ).fetchone()
    if row:
        signals.append(_signal("identity_hash", f"{normalized_identity}|{description_hash}", "exact", row["id"]))
    if employer and title:
        for row in db.execute(
            "SELECT id, employer, title FROM jobs WHERE lower(employer) = lower(?) AND lower(title) = lower(?)",
            (employer, title),
        ).fetchall():
            signals.append(
                _signal(
                    "company_title",
                    f"{employer}|{title}|{','.join(locations)}",
                    "ambiguous",
                    row["id"],
                    {"reason": "same company and title; compare location/requisition before applying"},
                )
            )
    return signals or [_signal("none", "no_existing_signal", "none", None)]


def _signal(
    signal_type: str,
    signal_value: str,
    risk: str,
    matched_job_id: str | None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "signal_type": signal_type,
        "signal_value": signal_value,
        "risk": risk,
        "matched_job_id": matched_job_id,
        "details": details or {},
    }


def _field(value: Any, evidence: dict[str, Any] | None) -> dict[str, Any]:
    return {"value": value, "original": value, "evidence": evidence}


def _attach_spans(extraction: dict[str, Any], text: str) -> None:
    for key, field in extraction.items():
        if not isinstance(field, dict) or field["value"] in (None, [], {}):
            continue
        needle = field["value"]
        if isinstance(needle, dict):
            parts = [str(value) for value in needle.values() if value is not None]
        elif isinstance(needle, list):
            parts = [str(item) for item in needle if item]
        else:
            parts = [str(needle)]
        field["evidence"] = _span_for_first(text, parts)


def _derive_unknowns_and_warnings(extraction: dict[str, Any], text: str) -> None:
    unknown_fields = [
        key
        for key, value in extraction.items()
        if isinstance(value, dict) and value["value"] in (None, [], {})
    ]
    extraction["unknown_fields"] = unknown_fields
    warnings = []
    lower = text.lower()
    if len(text) < 300 or lower.endswith(("...", "read more", "show more")):
        warnings.append({"code": "possible_truncated_description", "message": "description may be incomplete"})
    if len(re.findall(r"\b(job title|role)\b", lower)) > 1:
        warnings.append({"code": "possible_multiple_roles", "message": "multiple role labels found"})
    if "remote" in lower and re.search(r"\bonsite|on-site|hybrid\b", lower):
        warnings.append({"code": "ambiguous_work_arrangement", "message": "multiple work arrangements mentioned"})
    if extraction["job_status"]["value"] == "closed":
        warnings.append({"code": "closed_job", "message": "description indicates the job is closed or unavailable"})
    experience = extraction["experience"]["value"]
    if experience and experience.get("minimum_years") is not None and experience.get("maximum_years") is None:
        warnings.append({"code": "open_ended_experience", "message": "experience requirement has no upper bound"})
    if _looks_like_prompt_injection(lower):
        warnings.append(
            {
                "code": "untrusted_instruction_detected",
                "message": "job text contains instructions that must be treated as untrusted content",
            }
        )
    extraction["warnings"] = warnings


def _looks_like_prompt_injection(lower_text: str) -> bool:
    markers = (
        "ignore previous instructions",
        "ignore all previous instructions",
        "system prompt",
        "developer message",
        "read private",
        "exfiltrate",
        "send the resume to",
        "change your preferences",
        "apply automatically",
        "call tool",
    )
    return any(marker in lower_text for marker in markers)


def _find_label(lines: list[str], labels: tuple[str, ...]) -> str | None:
    for line in lines[:30]:
        for label in labels:
            match = re.match(rf"^{re.escape(label)}\s*[:\-]\s*(.+)$", line, flags=re.I)
            if match:
                return match.group(1).strip()
    return None


def _first_title(lines: list[str]) -> str | None:
    for line in lines[:8]:
        if 3 <= len(line) <= 90 and not re.search(r"https?://|@|:", line):
            return line
    return None


def _find_requisition(text: str) -> str | None:
    match = re.search(r"\b(?:req(?:uisition)?|job)\s*(?:id|code|#)\s*[:#-]?\s*([A-Z0-9._-]{3,})", text, re.I)
    return match.group(1) if match else None


def _find_locations(text: str) -> list[str]:
    known = ("Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Chennai", "Delhi", "Noida", "Gurgaon")
    found = []
    for city in known:
        if re.search(rf"\b{re.escape(city)}\b", text, re.I):
            found.append("Bengaluru" if city == "Bangalore" else city)
    return sorted(set(found))


def _find_work_arrangement(text: str) -> str | None:
    lower = text.lower()
    if "remote" in lower:
        if "hybrid" in lower or "onsite" in lower or "on-site" in lower:
            return "ambiguous"
        return "remote"
    if "hybrid" in lower:
        return "hybrid"
    if "onsite" in lower or "on-site" in lower or "work from office" in lower:
        return "onsite"
    return None


def _find_seniority(text: str) -> str | None:
    lower = text.lower()
    if re.search(r"\b(intern|trainee)\b", lower):
        return "intern"
    if re.search(r"\b(junior|associate|entry[- ]level)\b", lower):
        return "junior"
    if re.search(r"\b(senior|lead|staff|principal)\b", lower):
        return "senior"
    return None


def _find_employment_type(text: str) -> str | None:
    lower = text.lower()
    if re.search(r"\b(full[- ]time|permanent)\b", lower):
        return "full_time_permanent"
    if "contract" in lower:
        return "contract"
    if "internship" in lower:
        return "internship"
    if re.search(r"\bpart[- ]time\b", lower):
        return "part_time"
    return None


def _find_experience(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:(?:-|–|to)\s*(\d+(?:\.\d+)?))?\+?\s*years?",
        text,
        re.I,
    )
    if not match:
        return None
    minimum = float(match.group(1))
    maximum = float(match.group(2)) if match.group(2) else None
    return {
        "minimum_years": int(minimum) if minimum.is_integer() else minimum,
        "maximum_years": int(maximum) if maximum is not None and maximum.is_integer() else maximum,
        "original": match.group(0),
        "ambiguous": maximum is None and "+" not in match.group(0),
    }


def _extract_section_items(text: str, *, required: bool) -> list[str]:
    heading_words = (
        r"(?:requirements?|qualifications?|must have|required skills?)"
        if required
        else r"(?:preferred|nice to have|good to have|bonus)"
    )
    section = _section_after_heading(text, heading_words)
    if not section:
        return []
    return _bullet_items(section)


def _extract_responsibilities(text: str) -> list[str]:
    section = _section_after_heading(text, r"(?:responsibilities|what you.?ll do|role and responsibilities)")
    return _bullet_items(section) if section else []


def _section_after_heading(text: str, heading_words: str) -> str | None:
    pattern = re.compile(rf"^\s*{heading_words}\s*:?\s*$", re.I | re.M)
    match = pattern.search(text)
    if not match:
        return None
    rest = text[match.end() :]
    next_heading = re.search(r"^\s*[A-Z][A-Za-z /&-]{2,40}:?\s*$", rest, re.M)
    return rest[: next_heading.start()] if next_heading else rest[:1200]


def _bullet_items(section: str) -> list[str]:
    items = []
    for line in section.splitlines():
        cleaned = re.sub(r"^\s*[-*•\d.)]+\s*", "", line).strip()
        if cleaned and len(cleaned) > 2:
            items.append(cleaned)
    return items[:20]


def _find_compensation(text: str) -> dict[str, Any] | None:
    pattern = (
        r"(?:(INR|Rs\.?|₹|USD|\$)\s*)?(\d+(?:\.\d+)?)\s*"
        r"(?:(?:-|–|to)\s*(\d+(?:\.\d+)?))?\s*"
        r"(LPA|lakhs?|k|per annum|annually|yearly|monthly|month)?"
    )
    for match in re.finditer(pattern, text, re.I):
        if match.group(1) or match.group(4):
            return {
                "currency": _currency(match.group(1)),
                "minimum": _number(match.group(2)),
                "maximum": _number(match.group(3)),
                "unit": match.group(4),
                "original": match.group(0).strip(),
            }
    return None


def _find_job_status(text: str) -> str | None:
    lower = text.lower()
    closed_markers = (
        "job closed",
        "position closed",
        "applications closed",
        "no longer accepting applications",
        "this job is no longer available",
        "expired",
    )
    if any(marker in lower for marker in closed_markers):
        return "closed"
    return None


def _find_date(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[:\-]\s*([A-Za-z0-9, /\-]+)", text, re.I)
        if match:
            return match.group(1).strip()
    return None


def _find_application_destination(text: str, canonical_url: str | None) -> str | None:
    match = re.search(r"https?://\S+", text)
    return match.group(0).rstrip(").,") if match else canonical_url


def _span_for_first(text: str, needles: list[str]) -> dict[str, Any] | None:
    for needle in needles:
        if not needle:
            continue
        index = text.lower().find(needle.lower())
        if index >= 0:
            return {"start": index, "end": index + len(needle), "text": text[index : index + len(needle)]}
    return None


def _currency(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.lower()
    if value in {"₹", "rs.", "inr"}:
        return "INR"
    if value in {"$", "usd"}:
        return "USD"
    return raw.upper()


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    return float(raw)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
