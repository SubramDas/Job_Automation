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
live network discovery or job submission.

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

Use `--json` for machine-readable CLI output. The detailed JSON and Markdown run reports are
stored as private artifacts and referenced by opaque artifact IDs in the command output.

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
