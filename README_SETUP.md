# Local Setup

Status: Phase 03 local Space foundation. This setup validates contracts, synthetic
configuration, agent instruction packages, and private-profile storage using synthetic data
only. It does not connect accounts, process real resumes through providers, schedule runs,
or submit applications.

## Requirements

- Python 3.12 or newer.
- Optional: `pip` if you want pytest/ruff locally. The core validation command uses only the
  Python standard library.

## Commands

```bash
python3 -m app.core.config --config-dir config
python3 -m unittest discover -s tests
```

Phase 03 writes private data only under `private/` by default. The test suite uses temporary
directories and synthetic DOCX/PDF fixtures.

## Agent B fixture discovery

Phase 05E adds a safe local discovery run against fixture portals. It uses MCP tool calls
inside the app, writes private run reports under `private/artifacts`, and does not perform
job submission.

Preview the generated source queries:

```bash
python3 -m app.discovery.agent_b_run --preview
```

Run fixture discovery:

```bash
python3 -m app.discovery.agent_b_run --sources fixture_remote_jobs,fixture_india_jobs --max-results 5
```

Run the Phase 05E exit demo with two fixture portals, the ATS allowlist fixture, and one
manual imported job:

```bash
python3 -m app.discovery.phase05e_exit_demo
```

Run the currently enabled read-only public API source:

```bash
python3 -m app.discovery.agent_b_run --sources jobicy_api_candidate --max-results 10
```

Run JobsPipe after setting `JOBSPIPE_API_KEY` in `.env`:

```bash
python3 -m app.discovery.agent_b_run --sources jobspipe_candidate --max-results 10
```

When using the Codex-facing Agent B MCP server, you do not need to name individual live
sources. Ask Agent B to fetch jobs from the internet; omitted `sources` or `sources:
["auto"]` selects every configured `read_only_enabled` source from `config/sources.json`
or `config/sources.example.json`. Local sources such as JobSpy are auto-selected only when
their health endpoint is already running; fixtures and manual-only sources stay explicit.

For a job link where direct retrieval is unsupported or not allowed, paste the full job
description/details text with the link and ask Agent B to import it. The Codex-facing MCP
tool `agent_b_import_job_text` saves the exact pasted text, extracts fields, evaluates the
match, and refreshes `private/job_reviews/` without scraping the linked site.

Use `--json` for machine-readable CLI output. The detailed JSON and Markdown run reports are
stored as private artifacts and referenced by opaque artifact IDs in the command output.

Agent B also generates a readable review workspace under `private/job_reviews/`. The
intended browsing path is:

```text
private/job_reviews/index.md
private/job_reviews/<company-slug>/<job-title-slug>__<job-id-short>/job-details.md
private/job_reviews/<company-slug>/<job-title-slug>__<job-id-short>/job-description.txt
```

This folder is for human review. The SQLite database, immutable artifacts, description
hashes, and `job_id` values remain the source of truth for duplicate detection, Agent A
handoff, audit history, and future application work.

Rebuild the readable review workspace from already saved Space jobs:

```bash
python3 -m app.discovery.job_review_workspace
```

## Agent A keyword planning

Agent A's preferred workflow is Codex + MCP. You give Codex a saved `job_id`; Codex calls
the project MCP tools to read the job description, uses the current Codex model to create
the ranked keyword plan, and saves that plan back to Space. Agent A does not read, edit,
or approve any resume file.

Use this from Codex:

```text
Run Agent A keyword planning for job_id job_xxx. Read the job through MCP, extract
resume-relevant keywords, rank them high/medium/low, mark mandatory/recommended/optional,
store the keyword plan artifact, and show me the summary.
```

Short form:

```text
Agent A call MCP for job_xxx
```

That short form is treated as permission to read the saved job, generate the ranked
keyword plan, call the MCP save tool, and create/update the readable
`private/job_reviews/.../keywords.md` mirror.

The MCP tool sequence is:

1. `jobs.get_job` with the assigned `job_id`.
2. Codex generates the structured keyword plan from the job description only.
3. `jobs.save_keyword_plan` with the ranked keywords, warnings, and model metadata.

The older direct Python runner remains as a local fallback/testing path. It can use the
deterministic extractor and, if configured, the OpenAI Responses API. It cannot use the
Codex chat model from a plain terminal process.

Save a job description locally when you want to run Agent A without an existing Agent B job:

```bash
mkdir -p private/inputs
$EDITOR private/inputs/job.txt
```

Run Agent A directly from a job description file:

```bash
python3 -m app.tailoring.agent_a_run \
  --job-description-file private/inputs/job.txt \
  --job-url "https://example.com/job-posting"
```

Use JSON output when you want artifact IDs and keyword details in a machine-readable form:

```bash
python3 -m app.tailoring.agent_a_run \
  --job-description-file private/inputs/job.txt \
  --job-url "https://example.com/job-posting" \
  --json
```

If Agent B already saved the job, run Agent A with the existing job ID:

```bash
python3 -m app.tailoring.agent_a_run \
  --job-id job_xxx
```

Agent B run reports show `job_id` values in their detailed JSON artifacts. To inspect recent
private JSON artifacts for saved job IDs:

```bash
python3 - <<'PY'
import json
from pathlib import Path

for path in sorted(Path("private/artifacts").glob("artifact_*/v*.json"))[-10:]:
    data = json.loads(path.read_text())
    for row in data.get("rows", []):
        if row.get("job_id"):
            print(row["job_id"], "-", row.get("title"), "-", row.get("company"), "from", path)
PY
```

Agent A prints and stores the keyword-plan artifact ID, the job ID, priority counts, and any
warnings. The keyword plan is linked to the job record so you can manually update your own
resume using the high/medium/low terms.

### Agent A model configuration

For the preferred Codex + MCP workflow, model choice is controlled by the Codex session you
are using. The project does not need an `OPENAI_API_KEY` for that path.

The fallback Python runner is configured for optional OpenAI keyword planning in
`config/models.example.json`:

- `gpt-5.5` is the current fallback-runner default in this workspace because the user wants
  a low-cost model where available.
- `gpt-5.6-terra` is the fallback for ambiguous postings or schema repair.
- Provider use is limited to `keyword_planning`; Agent A must not send resumes or candidate
  private facts to the provider.

Set your key and live flag in `.env` only if you want the fallback runner to use the
OpenAI Responses API directly:

```bash
OPENAI_API_KEY=your_key_here
AGENT_A_LIVE_LLM=true
```

Live calls use structured JSON output, `store: false`, and send only the job description. If
the API call fails, Agent A records a `live_llm_fallback` warning and uses the deterministic
local extractor so the run still produces a reviewable keyword plan. Keep
`AGENT_A_LIVE_LLM=false` when you want local-only behavior.

Jobicy does not require an API key, but its source attribution and canonical URL must be
preserved in any displayed listing. Other candidates such as Adzuna and USAJOBS require API
keys before they can be enabled.

`jobspy_mcp_candidate` is registered but disabled by default. To use it later, install and
run `borgius/jobspy-mcp-server` locally, set `JOBSPY_MCP_URL` if it is not running at
`http://127.0.0.1:9423/api`, and choose an explicit allowed site list in
`config/sources.example.json`. Do not enable LinkedIn or Naukri through JobSpy unless you
approve the site-specific scraping/terms risk.

Build the JobSpy Docker image once:

```bash
scripts/setup-jobspy-image.sh
```

Then use the wrapper script whenever you want Agent B to search through JobSpy. It starts the
local JobSpy MCP server if needed and then runs Agent B:

```bash
scripts/run-agent-b-jobspy.sh --max-results 3
```

If the Docker image is missing and you want the wrapper to build it automatically:

```bash
JOBSPY_AUTOBUILD=1 scripts/run-agent-b-jobspy.sh --max-results 3
```

Record a review label/action after inspecting a result:

```bash
python3 -m app.discovery.review_actions --run-id agent_b_run_x --job-id job_x --action label --label maybe --reason "worth a closer look"
```

Summarize saved yes/maybe/no labels for calibration:

```bash
python3 -m app.discovery.review_actions --evaluate-labels
```

Optional development tools:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
pytest
ruff check .
ruff format .
```

Installing dependencies does not enable live submissions. Live discovery, account login,
uploads, form submission, scheduling, and provider use remain later-phase work requiring
separate approval.

 <!-- Title: Embedded Firmware Engineer
  Company: Schneider Electric
  Link: https://careers.se.com/jobs/135889...
  JD: -->
