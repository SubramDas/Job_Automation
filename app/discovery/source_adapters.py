"""Source adapter contracts and local fixture portals for Phase 05E."""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchQuery:
    text: str
    locations: tuple[str, ...]
    work_modes: tuple[str, ...]
    employment_type: str | None
    max_results: int


@dataclass(frozen=True)
class DiscoveredJob:
    source_id: str
    source_job_id: str
    title: str
    company: str
    location: str
    work_mode: str
    result_url: str
    snippet: str
    discovered_at: str
    description_status: str


@dataclass(frozen=True)
class JobDescription:
    source_id: str
    source_job_id: str
    url: str
    description: str
    application_destination: str | None
    retrieved_via: str


class SourceAdapter(Protocol):
    source_id: str

    def search(self, query: SearchQuery) -> list[DiscoveredJob]:
        """Return normalized result links for a source."""

    def fetch_description(self, *, url: str, source_job_id: str | None = None) -> JobDescription:
        """Return a full job description where permitted."""


class AdapterError(ValueError):
    """Source adapter failure with a safe user-facing code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FixturePortalAdapter:
    """Deterministic no-network portal used to exercise Agent B discovery."""

    def __init__(self, source_id: str, jobs: list[dict[str, Any]]) -> None:
        self.source_id = source_id
        self._jobs = jobs

    def search(self, query: SearchQuery) -> list[DiscoveredJob]:
        query_terms = _terms(query.text)
        results: list[DiscoveredJob] = []
        for job in self._jobs:
            haystack = _terms(" ".join([job["title"], job["company"], job["description"]]))
            location_ok = not query.locations or any(
                location.lower() in job["location"].lower() for location in query.locations
            )
            mode_ok = not query.work_modes or job["work_mode"].lower() in {
                mode.lower() for mode in query.work_modes
            }
            if query_terms and not query_terms.intersection(haystack):
                continue
            if not location_ok and job["work_mode"].lower() != "remote":
                continue
            if not mode_ok:
                continue
            results.append(
                DiscoveredJob(
                    source_id=self.source_id,
                    source_job_id=job["source_job_id"],
                    title=job["title"],
                    company=job["company"],
                    location=job["location"],
                    work_mode=job["work_mode"],
                    result_url=job["url"],
                    snippet=job["snippet"],
                    discovered_at=job["discovered_at"],
                    description_status="available",
                )
            )
            if len(results) >= query.max_results:
                break
        return results

    def fetch_description(self, *, url: str, source_job_id: str | None = None) -> JobDescription:
        for job in self._jobs:
            if job["url"] == url or job["source_job_id"] == source_job_id:
                return JobDescription(
                    source_id=self.source_id,
                    source_job_id=job["source_job_id"],
                    url=job["url"],
                    description=job["description"],
                    application_destination=job.get("application_destination"),
                    retrieved_via="fixture",
                )
        raise AdapterError("missing_fact", "fixture job result is unknown")


class JobicyAdapter:
    """Read-only adapter for Jobicy's public remote jobs API."""

    source_id = "jobicy_api_candidate"
    endpoint = "https://jobicy.com/api/v2/remote-jobs"
    _global_cache: dict[str, dict[str, Any]] = {}

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: SearchQuery) -> list[DiscoveredJob]:
        params = {"count": str(max(1, min(query.max_results, 20)))}
        tag = _jobicy_tag(query.text)
        if tag:
            params["tag"] = tag
        if any(mode.lower() == "remote" for mode in query.work_modes):
            params["geo"] = "anywhere"
        payload = self._get_json(f"{self.endpoint}?{urlencode(params)}")
        jobs = payload.get("jobs", [])
        if not isinstance(jobs, list):
            raise AdapterError("schema_invalid", "Jobicy response did not contain a jobs list")
        results = []
        for item in jobs[: query.max_results]:
            if not isinstance(item, dict):
                continue
            source_job_id = str(item.get("id") or item.get("jobId") or item.get("url") or "")
            url = str(item.get("url") or item.get("jobUrl") or "")
            if not source_job_id or not url:
                continue
            self._global_cache[source_job_id] = item
            title = str(item.get("jobTitle") or item.get("title") or "Unknown title")
            company = str(item.get("companyName") or item.get("company") or "Unknown company")
            location = str(item.get("jobGeo") or item.get("location") or "Remote")
            results.append(
                DiscoveredJob(
                    source_id=self.source_id,
                    source_job_id=source_job_id,
                    title=title,
                    company=company,
                    location=location,
                    work_mode="remote",
                    result_url=url,
                    snippet=_plain_text(str(item.get("jobExcerpt") or item.get("excerpt") or ""))[:240],
                    discovered_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    description_status="available",
                )
            )
        return results

    def fetch_description(self, *, url: str, source_job_id: str | None = None) -> JobDescription:
        item = self._global_cache.get(str(source_job_id)) if source_job_id else None
        if item is None:
            # Jobicy's list payload includes the full HTML description, so if the caller did
            # not search first, fetch a small page and find the URL in the returned jobs.
            for result in self._get_json(f"{self.endpoint}?{urlencode({'count': '20'})}").get("jobs", []):
                if isinstance(result, dict) and str(result.get("url") or result.get("jobUrl")) == url:
                    item = result
                    break
        if item is None:
            raise AdapterError("missing_fact", "Jobicy listing is not available in the current API payload")
        title = str(item.get("jobTitle") or item.get("title") or "Unknown title")
        company = str(item.get("companyName") or item.get("company") or "Unknown company")
        location = str(item.get("jobGeo") or item.get("location") or "Remote")
        description = _plain_text(str(item.get("jobDescription") or item.get("description") or item.get("jobExcerpt") or ""))
        if not description:
            description = _plain_text(str(item.get("jobExcerpt") or ""))
        job_id = str(item.get("id") or item.get("jobId") or source_job_id or url)
        canonical_url = str(item.get("url") or item.get("jobUrl") or url)
        full_description = f"""Title: {title}
Company: {company}
Job ID: {job_id}
Location: {location}
Work mode: Remote
Employment type: Full-time permanent
Posted: {item.get("pubDate") or ""}
Apply: {canonical_url}
Source: Jobicy

Responsibilities
- See source description below

Requirements
- {_plain_text(str(item.get("jobIndustry") or "Remote role requirements not separately structured"))}

Preferred
- Preserve canonical Jobicy URL and source attribution

Description
{description}
"""
        return JobDescription(
            source_id=self.source_id,
            source_job_id=job_id,
            url=canonical_url,
            description=full_description,
            application_destination=canonical_url,
            retrieved_via="jobicy_public_api",
        )

    def _get_json(self, url: str) -> dict[str, Any]:
        _ensure_allowed_public_url(url, allowed_hosts={"jobicy.com"})
        request = Request(url, headers={"User-Agent": "Job_Automation/0.1 local discovery"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower():
                    raise AdapterError("schema_invalid", "Jobicy returned a non-JSON response")
                payload = response.read(512_000)
        except TimeoutError as exc:
            raise AdapterError("rate_limited", "Jobicy request timed out") from exc
        except URLError as exc:
            raise AdapterError("unsupported_source", f"Jobicy request failed: {exc.reason}") from exc
        return json.loads(payload.decode("utf-8"))


class JobsPipeAdapter:
    """Read-only adapter for JobsPipe's jobs search API."""

    source_id = "jobspipe_candidate"
    endpoint = "https://api.jobspipe.dev/v1/jobs/search"
    _global_cache: dict[str, dict[str, Any]] = {}

    def __init__(self, *, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.api_key = os.environ.get("JOBSPIPE_API_KEY", "")

    def search(self, query: SearchQuery) -> list[DiscoveredJob]:
        if not self.api_key:
            raise AdapterError("authorization_required", "JOBSPIPE_API_KEY is not configured")
        body = {
            "job_title_or": _title_terms(query.text),
            "limit": max(1, min(query.max_results, 25)),
            "include_total_results": False,
            "posted_at_max_age_days": 14,
        }
        if any(mode.lower() == "remote" for mode in query.work_modes):
            body["remote"] = True
        country_codes = _country_codes_for_locations(query.locations)
        if country_codes:
            body["job_country_code_or"] = country_codes
        payload = self._post_json(self.endpoint, body)
        jobs = payload.get("data", [])
        if not isinstance(jobs, list):
            raise AdapterError("schema_invalid", "JobsPipe response did not contain a data list")
        results: list[DiscoveredJob] = []
        for item in jobs[: query.max_results]:
            if not isinstance(item, dict):
                continue
            source_job_id = str(item.get("id") or item.get("url") or "")
            url = str(item.get("url") or item.get("final_url") or item.get("source_url") or "")
            if not source_job_id or not url:
                continue
            self._global_cache[source_job_id] = item
            results.append(
                DiscoveredJob(
                    source_id=self.source_id,
                    source_job_id=source_job_id,
                    title=str(item.get("job_title") or item.get("normalized_title") or "Unknown title"),
                    company=str(item.get("company") or "Unknown company"),
                    location=str(item.get("location") or item.get("short_location") or item.get("country") or ""),
                    work_mode=_work_mode_from_jobspipe(item),
                    result_url=url,
                    snippet=_plain_text(str(item.get("description") or ""))[:240],
                    discovered_at=str(item.get("discovered_at") or utc_timestamp()),
                    description_status="available" if item.get("description") else "partial",
                )
            )
        return results

    def fetch_description(self, *, url: str, source_job_id: str | None = None) -> JobDescription:
        item = self._global_cache.get(str(source_job_id)) if source_job_id else None
        if item is None:
            raise AdapterError("missing_fact", "JobsPipe listing is not available in the current search cache")
        title = str(item.get("job_title") or item.get("normalized_title") or "Unknown title")
        company = str(item.get("company") or "Unknown company")
        location = str(item.get("location") or item.get("short_location") or item.get("country") or "")
        work_mode = _work_mode_from_jobspipe(item).title()
        employment = ", ".join(item.get("employment_statuses") or []) or "Unknown"
        description = _plain_text(str(item.get("description") or ""))
        skills = item.get("technology_slugs") or item.get("keyword_slugs") or []
        salary = item.get("salary_string") or ""
        canonical_url = str(item.get("url") or item.get("final_url") or item.get("source_url") or url)
        source_url = str(item.get("source_url") or canonical_url)
        full_description = f"""Title: {title}
Company: {company}
Job ID: {item.get("id") or source_job_id or canonical_url}
Location: {location}
Work mode: {work_mode}
Employment type: {employment}
Experience: {item.get("seniority") or ""}
Compensation: {salary}
Posted: {item.get("date_posted") or ""}
Closing: {item.get("closed_at") or item.get("expires_at") or ""}
Apply: {canonical_url}
Source: JobsPipe
Source URL: {source_url}

Responsibilities
- See source description below

Requirements
{_bullets(skills) or "- Requirements not separately structured"}

Preferred
- Preserve source attribution and canonical URL

Description
{description}
"""
        return JobDescription(
            source_id=self.source_id,
            source_job_id=str(item.get("id") or source_job_id or canonical_url),
            url=canonical_url,
            description=full_description,
            application_destination=canonical_url,
            retrieved_via="jobspipe_rest_api",
        )

    def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        _ensure_allowed_public_url(url, allowed_hosts={"api.jobspipe.dev"})
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Job_Automation/0.1 local discovery",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower():
                    raise AdapterError("schema_invalid", "JobsPipe returned a non-JSON response")
                payload = response.read(1_000_000)
        except HTTPError as exc:
            if exc.code == 401:
                raise AdapterError("authorization_failed", "JobsPipe API key was rejected") from exc
            if exc.code == 402:
                raise AdapterError("rate_limited", "JobsPipe monthly quota is exhausted") from exc
            if exc.code == 429:
                raise AdapterError("rate_limited", "JobsPipe rate limit was exceeded") from exc
            raise AdapterError("unsupported_source", f"JobsPipe request failed with HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise AdapterError("rate_limited", "JobsPipe request timed out") from exc
        except URLError as exc:
            raise AdapterError("unsupported_source", f"JobsPipe request failed: {exc.reason}") from exc
        return json.loads(payload.decode("utf-8"))


class JobSpyLocalAdapter:
    """Local wrapper for a user-run jobspy-mcp-server HTTP endpoint."""

    source_id = "jobspy_mcp_candidate"
    _global_cache: dict[str, dict[str, Any]] = {}

    def __init__(self, source: dict[str, Any], *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.endpoint = os.environ.get(source.get("local_endpoint_env", "JOBSPY_MCP_URL")) or source.get(
            "default_local_endpoint",
            "http://127.0.0.1:9423/api",
        )
        self.allowed_sites = tuple(source.get("allowed_site_names") or [])

    def search(self, query: SearchQuery) -> list[DiscoveredJob]:
        if not self.allowed_sites:
            raise AdapterError("authorization_required", "JobSpy MCP has no approved allowed_site_names")
        _ensure_local_jobspy_url(self.endpoint)
        params: dict[str, Any] = {
            "siteNames": ",".join(self.allowed_sites),
            "searchTerm": query.text,
            "location": ", ".join(query.locations) or "remote",
            "resultsWanted": max(1, min(query.max_results, 25)),
            "hoursOld": 168,
            "linkedinFetchDescription": False,
            "format": "json",
        }
        if any(mode.lower() == "remote" for mode in query.work_modes):
            params["isRemote"] = True
        if query.employment_type == "full_time_permanent":
            params["jobType"] = "fulltime"
        if _jobspy_country_for_locations(query.locations):
            params["countryIndeed"] = _jobspy_country_for_locations(query.locations)
        payload = self._request_json(params)
        jobs = _jobspy_jobs(payload)
        results = []
        for index, item in enumerate(jobs[: query.max_results]):
            source_job_id = str(
                item.get("id")
                or item.get("jobId")
                or item.get("job_url")
                or item.get("jobUrl")
                or item.get("url")
                or index
            )
            url = str(
                item.get("job_url")
                or item.get("jobUrl")
                or item.get("url")
                or item.get("job_url_direct")
                or item.get("jobUrlDirect")
                or ""
            )
            if not url:
                continue
            self._global_cache[source_job_id] = item
            self._global_cache[url] = item
            results.append(
                DiscoveredJob(
                    source_id=self.source_id,
                    source_job_id=source_job_id,
                    title=str(item.get("title") or "Unknown title"),
                    company=str(item.get("company") or "Unknown company"),
                    location=str(item.get("location") or ""),
                    work_mode="remote"
                    if str(item.get("is_remote") or item.get("isRemote")).lower() == "true"
                    else "unknown",
                    result_url=url,
                    snippet=_plain_text(str(item.get("description") or ""))[:240],
                    discovered_at=utc_timestamp(),
                    description_status="available" if item.get("description") else "partial",
                )
            )
        return results

    def fetch_description(self, *, url: str, source_job_id: str | None = None) -> JobDescription:
        item = self._global_cache.get(str(source_job_id)) if source_job_id else None
        item = item or self._global_cache.get(url)
        if item is None:
            raise AdapterError(
                "missing_fact",
                "JobSpy descriptions are available only from the current search response",
            )
        title = str(item.get("title") or "Unknown title")
        company = str(item.get("company") or "Unknown company")
        location = str(item.get("location") or "")
        job_url = str(
            item.get("job_url")
            or item.get("jobUrl")
            or item.get("url")
            or item.get("job_url_direct")
            or item.get("jobUrlDirect")
            or url
        )
        direct_url = str(item.get("job_url_direct") or item.get("jobUrlDirect") or job_url)
        description = _plain_text(str(item.get("description") or ""))
        full_description = f"""Title: {title}
Company: {company}
Job ID: {source_job_id or item.get("id") or job_url}
Location: {location}
Work mode: {"Remote" if str(item.get("is_remote") or item.get("isRemote")).lower() == "true" else "Unknown"}
Employment type: {item.get("jobType") or item.get("job_type") or "Unknown"}
Posted: {item.get("datePosted") or item.get("date_posted") or ""}
Apply: {direct_url}
Source: JobSpy MCP

Description
{description}
"""
        return JobDescription(
            source_id=self.source_id,
            source_job_id=str(source_job_id or item.get("id") or job_url),
            url=job_url,
            description=full_description,
            application_destination=direct_url,
            retrieved_via="jobspy_mcp_local",
        )

    def _request_json(self, params: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        parsed = urlparse(self.endpoint)
        if parsed.path.rstrip("/") == "/api":
            request = Request(
                self.endpoint,
                data=json.dumps(params).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Job_Automation/0.1 local discovery",
                },
                method="POST",
            )
        else:
            request = Request(
                f"{self.endpoint}?{urlencode(params)}",
                headers={"User-Agent": "Job_Automation/0.1 local discovery"},
            )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read(1_000_000)
        except URLError as exc:
            raise AdapterError("unsupported_source", f"JobSpy local server request failed: {exc.reason}") from exc
        return json.loads(payload.decode("utf-8"))


class UnsupportedAdapter:
    """Explicit manual-handoff adapter for sources that are not enabled."""

    def __init__(self, source_id: str, reason: str) -> None:
        self.source_id = source_id
        self.reason = reason

    def search(self, query: SearchQuery) -> list[DiscoveredJob]:
        raise AdapterError("unsupported_source", self.reason)

    def fetch_description(self, *, url: str, source_job_id: str | None = None) -> JobDescription:
        raise AdapterError("unsupported_source", self.reason)


def build_adapter(source: dict[str, Any]) -> SourceAdapter:
    source_id = source["id"]
    if source_id == "fixture_remote_jobs":
        return FixturePortalAdapter(source_id, _REMOTE_FIXTURE_JOBS)
    if source_id == "fixture_india_jobs":
        return FixturePortalAdapter(source_id, _INDIA_FIXTURE_JOBS)
    if source_id == "ats_allowlist_fixture":
        return FixturePortalAdapter(source_id, _ATS_ALLOWLIST_FIXTURE_JOBS)
    if source_id == "jobicy_api_candidate":
        return JobicyAdapter()
    if source_id == "jobspipe_candidate":
        return JobsPipeAdapter()
    if source_id == "jobspy_mcp_candidate":
        return JobSpyLocalAdapter(source)
    return UnsupportedAdapter(source_id, f"{source_id} is not enabled for automated discovery")


def _terms(value: str) -> set[str]:
    stop = {"and", "for", "the", "with", "role", "job"}
    return {term for term in value.lower().replace("/", " ").replace("-", " ").split() if term not in stop}


def _jobicy_tag(query: str) -> str | None:
    terms = _terms(query)
    for candidate in ("python", "software", "engineer", "developer", "data", "ai", "machine", "learning"):
        if candidate in terms:
            return "python" if candidate == "python" else candidate
    return None


def _title_terms(query: str) -> list[str]:
    parts = [part.strip() for part in query.split(" OR ") if part.strip()]
    return parts[:5] or [query]


def _country_codes_for_locations(locations: tuple[str, ...]) -> list[str]:
    if not locations:
        return []
    india_terms = {"bengaluru", "bangalore", "hyderabad", "india"}
    if any(location.lower() in india_terms for location in locations):
        return ["IN"]
    return []


def _jobspy_country_for_locations(locations: tuple[str, ...]) -> str | None:
    india_terms = {"bengaluru", "bangalore", "hyderabad", "india"}
    if any(location.lower() in india_terms for location in locations):
        return "India"
    return None


def _work_mode_from_jobspipe(item: dict[str, Any]) -> str:
    if item.get("remote"):
        return "remote"
    if item.get("hybrid"):
        return "hybrid"
    arrangement = str(item.get("work_arrangement") or "").lower()
    if arrangement:
        return arrangement
    return "onsite"


def _bullets(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return ""
    return "\n".join(f"- {value}" for value in values[:12])


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_local_jobspy_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise AdapterError("unsupported_source", "JobSpy MCP wrapper must use a local HTTP endpoint")


def _jobspy_jobs(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    for key in ("jobs", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if cleaned:
            self.parts.append(cleaned)


def _plain_text(value: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(unescape(value))
    text = " ".join(stripper.parts) if stripper.parts else value
    return " ".join(unescape(text).split())


def _ensure_allowed_public_url(url: str, *, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise AdapterError("unsupported_source", "URL is outside the source allowlist")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise AdapterError("unsupported_source", "source host could not be resolved") from exc
    for address in addresses:
        ip = address[4][0]
        if ip.startswith(("10.", "127.", "169.254.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "192.168.")):
            raise AdapterError("unsupported_source", "source resolved to a private or local network address")


_REMOTE_FIXTURE_JOBS: list[dict[str, Any]] = [
    {
        "source_job_id": "REMOTE-101",
        "title": "Remote Python Backend Engineer",
        "company": "Northstar Remote",
        "location": "Remote",
        "work_mode": "remote",
        "url": "https://fixture.remotejobs.test/jobs/remote-101",
        "application_destination": "https://careers.northstar.example/jobs/remote-101",
        "snippet": "Remote full-time Python backend role for 2 years of experience.",
        "discovered_at": "2026-09-23T00:00:00Z",
        "description": """Title: Remote Python Backend Engineer
Company: Northstar Remote
Job ID: REMOTE-101
Location: Remote
Work mode: Remote
Employment type: Full-time permanent
Experience: 2-3 years
Posted: 2026-09-20
Apply: https://careers.northstar.example/jobs/remote-101

Responsibilities
- Build Python REST APIs for customer-facing workflow products
- Maintain SQL data models and observability dashboards

Requirements
- Python
- SQL
- REST APIs

Preferred
- Cloud deployment exposure
""",
    },
    {
        "source_job_id": "REMOTE-102",
        "title": "Senior Platform Engineer",
        "company": "Scale Remote",
        "location": "Remote",
        "work_mode": "remote",
        "url": "https://fixture.remotejobs.test/jobs/remote-102",
        "application_destination": "https://careers.scale.example/jobs/remote-102",
        "snippet": "Senior remote platform role requiring 6 years of experience.",
        "discovered_at": "2026-09-23T00:00:00Z",
        "description": """Title: Senior Platform Engineer
Company: Scale Remote
Job ID: REMOTE-102
Location: Remote
Work mode: Remote
Employment type: Full-time permanent
Experience: 6-8 years
Posted: 2026-09-21
Apply: https://careers.scale.example/jobs/remote-102

Responsibilities
- Own Kubernetes platform reliability

Requirements
- Kubernetes
- Terraform
""",
    },
]

_INDIA_FIXTURE_JOBS: list[dict[str, Any]] = [
    {
        "source_job_id": "IN-201",
        "title": "Software Engineer - Python",
        "company": "Deccan Systems",
        "location": "Bengaluru",
        "work_mode": "hybrid",
        "url": "https://fixture.indiajobs.test/jobs/in-201",
        "application_destination": "https://careers.deccan.example/jobs/in-201",
        "snippet": "Hybrid Bengaluru Python role for 1-3 years.",
        "discovered_at": "2026-09-23T00:00:00Z",
        "description": """Title: Software Engineer - Python
Company: Deccan Systems
Job ID: IN-201
Location: Bengaluru
Work mode: Hybrid
Employment type: Full-time permanent
Experience: 1-3 years
Posted: 2026-09-22
Apply: https://careers.deccan.example/jobs/in-201

Responsibilities
- Build Python services for internal operations tools
- Work with SQL-backed reporting pipelines

Requirements
- Python
- SQL
- APIs

Preferred
- Docker
""",
    },
    {
        "source_job_id": "IN-202",
        "title": "Python Developer",
        "company": "Deccan Systems",
        "location": "Pune",
        "work_mode": "onsite",
        "url": "https://fixture.indiajobs.test/jobs/in-202",
        "application_destination": "https://careers.deccan.example/jobs/in-202",
        "snippet": "Onsite Pune role outside current location hard filter.",
        "discovered_at": "2026-09-23T00:00:00Z",
        "description": """Title: Python Developer
Company: Deccan Systems
Job ID: IN-202
Location: Pune
Work mode: Onsite
Employment type: Full-time permanent
Experience: 1-3 years
Posted: 2026-09-22
Apply: https://careers.deccan.example/jobs/in-202

Responsibilities
- Build Python automation scripts

Requirements
- Python
- SQL
""",
    },
]


_ATS_ALLOWLIST_FIXTURE_JOBS: list[dict[str, Any]] = [
    {
        "source_job_id": "LEVER-301",
        "title": "Python Software Engineer",
        "company": "Allowlist Lever Co",
        "location": "Bengaluru",
        "work_mode": "hybrid",
        "url": "https://jobs.lever.co/allowlist/lever-301",
        "application_destination": "https://jobs.lever.co/allowlist/lever-301/apply",
        "snippet": "Lever-style fixture with stable public detail and apply URLs.",
        "discovered_at": "2026-09-23T00:00:00Z",
        "description": """Title: Python Software Engineer
Company: Allowlist Lever Co
Job ID: LEVER-301
Location: Bengaluru
Work mode: Hybrid
Employment type: Full-time permanent
Experience: 1-3 years
Posted: 2026-09-22
Apply: https://jobs.lever.co/allowlist/lever-301/apply
Source: ATS allowlist fixture

Responsibilities
- Build Python APIs for workflow automation
- Maintain SQL-backed services

Requirements
- Python
- SQL
- REST APIs

Preferred
- Cloud deployment exposure
""",
    },
    {
        "source_job_id": "GREENHOUSE-302",
        "title": "Backend Engineer",
        "company": "Allowlist Greenhouse Co",
        "location": "Hyderabad",
        "work_mode": "hybrid",
        "url": "https://boards.greenhouse.io/allowlist/jobs/greenhouse-302",
        "application_destination": "https://boards.greenhouse.io/allowlist/jobs/greenhouse-302#app",
        "snippet": "Greenhouse-style fixture with stable public detail and application anchors.",
        "discovered_at": "2026-09-23T00:00:00Z",
        "description": """Title: Backend Engineer
Company: Allowlist Greenhouse Co
Job ID: GREENHOUSE-302
Location: Hyderabad
Work mode: Hybrid
Employment type: Full-time permanent
Experience: 2-3 years
Posted: 2026-09-22
Apply: https://boards.greenhouse.io/allowlist/jobs/greenhouse-302#app
Source: ATS allowlist fixture

Responsibilities
- Build backend services and operational dashboards
- Integrate APIs with production monitoring

Requirements
- Python
- SQL
- REST APIs

Preferred
- Observability exposure
""",
    },
]
