# Local Setup

Status: local-first profile, job discovery/import, matching, keyword planning, and gated Agent C resume suggestions.
This setup validates configuration and contracts, private profile storage, job import and
matching, Agent A keyword planning, and Space profile utilities using local or
synthetic data. Employer application preparation, browser automation, uploads, submissions,
and recurring schedules are outside the current scope.

## Requirements

- Python 3.12 or newer.
- Optional: `pip` if you want pytest/ruff locally. The core validation command uses only the
  Python standard library.

## Commands

```bash
python3 -m app.core.config --config-dir config
python3 -m unittest discover -s tests
```

Manage user-confirmed reusable answer metadata in Space:

```bash
python3 -m app.profile.space_answers add --key contact.email --question "Email address" --value "name@example.com"
python3 -m app.profile.space_answers list
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

Phase 05G adds a single-link fetch path for public job pages:

```text
Agent B mcp fetch <job-link>
```

Codex should call the configured Fetch MCP to retrieve the page as readable markdown/text,
then pass the fetched content into Agent B's `agent_b_fetch_job_url` tool. A successful
fetch creates the same outputs as manual import: a saved `job_id`,
immutable description artifact, match decision, and readable files under
`private/job_reviews/`. This path is read-only and does not authorize login, browser
automation, form filling, applying, CAPTCHA bypass, or account activity. If the page cannot
be fetched cleanly, paste the JD text and link and use the manual import path.

After Agent B saves a usable description, it returns a `pending_codex_mcp` handoff with the
saved `job_id`. Codex completes it by calling Agent A MCP to read the job, generate keywords
with the current session model, and save the plan. The validated result is then mirrored as
`keywords.md` in the job's review folder. Blocked or manual-handoff pages do not trigger an
Agent A handoff. The same contract applies to pasted imports and normal multi-source discovery.

Some ATS pages, including Workday, may return `Page failed to be simplified from HTML` in
Fetch MCP's simplified mode while still exposing useful JobPosting metadata in raw HTML. In
that case, retry Fetch MCP with raw HTML and pass that raw content to `agent_b_fetch_job_url`;
Agent B normalizes JSON-LD/meta JobPosting data before saving.

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

1. `agent_a_get_job` with the assigned `job_id`.
2. Codex generates the structured keyword plan from the job description only.
3. `agent_a_save_keyword_plan` with the ranked keywords, warnings, and model metadata.

Agent B returns a `pending_codex_mcp` handoff after saving a usable job description. Codex must
complete that handoff in the same workflow using the two Agent A MCP calls above. There is no
local keyword extractor and no direct OpenAI API fallback.

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

## Agent C resume keyword suggestions

Agent C accepts the resume's local `.tex` path directly. It keeps exactly one active source
at `private/inputs/resume.tex` and one generated file at `private/inputs/resume.md`. Giving
it a different path replaces the active pair; giving it the same source reuses the existing
Markdown. The active Codex session generates clean Markdown on first import. Regenerating
the same source requires an explicit request. A local standard-library fallback remains
available if needed:

```bash
python3 -m app.profile.resume_conversion /path/to/resume.tex
python3 -m app.profile.resume_conversion --regenerate
```

The Markdown and its hash manifest stay under `private/inputs/`. Agent C does not edit the
source file at the path you provide. Connect the server as a local stdio MCP in Codex by
adding this table to `~/.codex/config.toml` (or the project `.codex/config.toml`):

```toml
[mcp_servers.job-automation-agent-c]
command = "python3"
args = ["-m", "app.mcp.codex_agent_c_server"]
cwd = "/home/subramd/Job_Automation"
default_tools_approval_mode = "prompt"
enabled_tools = ["agent_c_import_resume", "agent_c_save_resume_markdown", "agent_c_get_suggestion_context", "agent_c_save_suggestions"]
```

Codex's current OpenAI Docs describe local stdio MCP configuration through
`mcp_servers` entries and support `command`, `args`, `cwd`, and tool approval settings.
After adding it, restart/reload Codex and run `codex mcp list` to confirm it is connected.
This server is local stdio; do not expose it as a public HTTP endpoint because it can read
the resume path you provide.

After the provider/privacy decision is approved, give
Agent C the local resume path and job ID; once that job has a saved Agent A keyword plan, it
imports/converts the resume if needed and creates three evidence-based edit options plus a
separate placement recommendation for every plan keyword. The review artifact is saved as
`resume-keyword-suggestions.md` in the job folder. Project edits cite evidence and the same-
project line to replace, and are rejected if the proposed rendered line is longer. Every
keyword gets a suggested location; unsupported terms are marked `needs_confirmation` with
conditional wording. Agent C returns advice only; choose and apply edits to the TeX file
manually.

**Privacy gate:** project decision P00-12 still permits only synthetic candidate data to be
processed by a model. The Agent C MCP tools refuse to return resume text or save suggestions
until model configuration explicitly approves personal-data processing and includes
`resume_keyword_suggestions` in `provider.allowed_stages`. Do not change that setting until
provider data handling, sharing, and retention have been reviewed. The deterministic local
fallback converter does not send data to a model; the preferred MCP conversion does. After
that review, put your approved provider values in the
gitignored `config/models.json` (starting from `config/models.example.json`); the required
provider fields are `status: "approved_for_personal_data_processing"`,
`personal_data_allowed: true`, and `allowed_stages` containing
`"resume_keyword_suggestions"`. The normal config validator checks this local file when it
exists.

### Agent A model configuration

Model choice is controlled by the active Codex session. The project does not use an
`OPENAI_API_KEY`, `AGENT_A_LIVE_LLM`, a local keyword extractor, or a direct provider API for
Agent A keyword generation.

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

Installing dependencies does not enable account connections, employer contact, application
form automation, recurring schedules, or provider use. Those capabilities are outside the
current project scope.

 <!-- Title: Embedded Firmware Engineer
  Company: Schneider Electric
  Link: https://careers.se.com/jobs/135889...
  JD: -->

  <!-- google-chrome     --remote-debugging-port=9222     --user-data-dir=/tmp/codex-visible-chrome -->


  <!-- Things to add -->
  <!-- - After keyword is made, it should take my resume and tell me where should I add those keywords and give 3 suggestions for each words for mandatory, recommended and optional -->
