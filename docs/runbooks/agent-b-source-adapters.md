# Agent B Source Adapter Runbook

Status: Phase 05E local/fixture guidance. Live source enablement still requires review.

## Add a Source Safely

1. Record the source in `config/sources.example.json` with separate capability flags for
   discovery, result-link retrieval, description retrieval, destination resolution, and
   manual handoff.
2. Check official terms, API/feed documentation, account requirements, rate limits, and
   current access permissions. Save the inspection date and URLs in `docs/decisions/`.
3. Prefer official APIs, feeds, user exports, alert imports, or user-pasted pages before any
   browser automation.
4. Add a fixture that represents the source's result and job-detail shape without real user
   data, credentials, cookies, or private screenshots.
5. Implement the adapter behind the project `jobs.search_sources` and
   `jobs.fetch_description` MCP contracts. Do not expose raw third-party tools directly to
   Agent B.
6. Enforce allowed hosts, payload limits, timeouts, redirect limits, source caps, and
   private-network blocking before live read-only retrieval.
7. Return structured unsupported/manual-handoff results when permission, authentication, or
   description retrieval is unavailable.
8. Add regression tests for search, fetch, dedupe, source failure isolation, prompt
   injection in snippets/descriptions, and CLI output.
9. Ensure saved jobs can be mirrored into `private/job_reviews/` after ingestion. The
   readable review files must never replace the database/artifact source of truth.

## Human-Readable Review Output

Agent B users should not need to browse opaque `private/artifacts/artifact_*` and
`private/artifacts/jobdesc_*` directories during normal review. After discovery, generate
or refresh a private review workspace:

```text
private/job_reviews/
  index.md
  <company-slug>/
    <job-title-slug>__<job-id-short>/
      job-details.md
      job-description.txt
      extracted.json
```

Use sanitized, stable slugs for company and title. Keep a short job-ID suffix in each job
folder even when adding a human-friendly ordinal such as `-2`; same-title roles, reposts,
different locations, and cross-posts are common enough that company/title alone is unsafe.

`job-details.md` should include the review summary: title, company, source, portal link,
canonical job URL, application destination, retrieved time, match decision, score, reasons,
warnings, unknown fields, freshness, duplicate signals, `job_id`, `snapshot_artifact_id`,
and description hash. `job-description.txt` should be an exact readable copy of the
preserved description text used for extraction and matching.

Cleanup must be conservative. Rebuilding the readable workspace may update or archive
review files, but must not delete immutable artifacts, database rows, keyword-plan
artifacts, or audit history.

## Candidate Backends

- Jobicy API/MCP: candidate for remote jobs after permission and data handling review.
- Self-hosted `jobsearch-mcp`: candidate wrapper for Adzuna, Remotive, WeWorkRemotely,
  Jobicy, and USAJobs after individual source-key and terms review.
- Self-hosted `jobspy-mcp-server`: candidate wrapper over JobSpy. It claims support for
  Indeed, LinkedIn, ZipRecruiter, Glassdoor, Google, Bayt, and Naukri. Treat it as
  scraper-backed; enable only after per-site permission review and local dependency setup.
- Official MCP Registry AI jobs server: candidate for AI-focused roles after scope and
  freshness review.
- JobsPipe MCP/API: candidate for ATS/job-board feeds after demo/key terms review.
- LinkedIn and Naukri: keep website automation disabled unless a specifically permitted
  route is verified. Use import/manual handoff paths meanwhile.

## JobSpy MCP Setup Notes

`borgius/jobspy-mcp-server` requires Node.js 16+, Python 3.6+, and the JobSpy tool installed
locally. Its MCP tool is `search_jobs`, with parameters such as `site_names`, `search_term`,
`location`, `results_wanted`, `hours_old`, and `linkedin_fetch_description`.

To configure it for this project:

1. Clone and install `borgius/jobspy-mcp-server` outside this repository or under a private
   local tools directory.
2. Install its Node and Python dependencies according to its README.
3. Start its local HTTP/SSE server. The default wrapper endpoint is
   `http://127.0.0.1:9423/api`.
4. If you use another local URL, set `JOBSPY_MCP_URL` in `.env`.
5. Edit `jobspy_mcp_candidate.allowed_site_names` in `config/sources.example.json` to the
   exact sites approved for this project. Keep it empty to block usage.

Do not connect it directly to Agent B. If enabled later, wrap it inside our project
`jobs.search_sources` and `jobs.fetch_description` tools so we can enforce:

- approved site list per run,
- hard caps on results and freshness,
- source attribution and canonical links,
- private data redaction,
- duplicate detection,
- unsupported/manual-handoff outcomes,
- no submission or account activity.
