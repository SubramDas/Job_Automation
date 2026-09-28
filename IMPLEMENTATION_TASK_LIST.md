# Job discovery and keyword planning: phased implementation task list

Status: phases 00-03 and 05-07 are implemented to varying degrees; Phase 04 remains partial. Phase 08's Agent C conversion and suggestion workflow is implemented with a provider/privacy gate; its model workflow remains disabled pending explicit provider approval. Application form preparation, browser automation, uploads, and submission are excluded.
Prepared: 2026-09-23.

Source documents: [project instructions](./AGENTS.md) and [pipeline plan](./JOB_APPLICATION_PIPELINE_PLAN.md).

This document records the scoped implementation backlog for Agents A and B, the proposed Agent C workflow, and shared local services. It does not authorize account connections, employer contact, recurring runs, or external actions.

## How to use this checklist

Execute phases in order unless their dependency notes explicitly permit independent work. Within each phase, numbered task IDs show the intended sequence. Mark a task complete only when its artifact or observable behavior exists and its relevant checks pass. Record completion evidence beside its ID in the implementation PR or task tracker.

Owners identify responsibility: **User** supplies facts and preferences; **Builder** implements the software; **A/B** identify runtime components; **Core** means deterministic shared services.

No time estimate is promised before source feasibility and pilot results are known. Unsupported sources can reach a useful manual-handoff milestone without blocking supported sources.

## 1. Target agent architecture

| Component | Primary responsibility | Proposed default model | Escalation or fallback | Authority |
| --- | --- | --- | --- | --- |
| Agent A — Keyword specialist | LLM keyword extraction, priority ranking, artifact persistence | `gpt-5.4` | User clarification for ambiguous job text; bounded schema repair after validation | Read assigned job snapshots; create job-linked keyword-plan artifacts |
| Agent B — Discovery specialist | Search planning, job extraction, requirement classification, match explanation | `gpt-5.4-nano` | `gpt-5.4-mini` for ambiguous extraction/matching; unresolved cases to review | Read search preferences and minimal career summary; save job records |
| Agent C — Resume keyword suggestions | Maintain one active TeX/Markdown pair; convert each new source once; compare resume with saved keyword plan; propose exactly three resume-pointer-based lines for every keyword | Active Codex session, gated by explicit personal-data provider approval | Hypothetical claims are allowed; user verifies before adding to source resume | Read the singleton private resume and job-linked keyword plan; save job-linked suggestion artifact; never edit source resume |
| Orchestrator | State transitions, dispatch, scheduling, budgets, recovery | No model required | Deterministic errors and review queue | Control workflow; cannot create user authorization |
| Space service | Profile, answer memory, versioning, reuse checks | No model required | Semantic retrieval may be added later; exact matching first | Accept user-confirmed facts through authenticated operations |
| Validation service | Schema, factual, document, policy, and submission checks | Deterministic checks first; isolated `gpt-5.4` critique for language claims when useful | Unresolved findings to user | Return findings; cannot submit or rewrite evidence |

These are proposed application API model IDs, not a change to the coding assistant in this workspace. Agent model assignments are configuration proposals. The two configured agents can run inside one application process; separate always-on services are unnecessary for the MVP.

Model choices are engineering proposals, subject to account access and task-specific evaluation. Official documentation describes [GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4) for complex professional work, [GPT-5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano) for tasks including extraction and classification, and [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) as a more efficient model with tool-oriented capabilities. Checked 2026-09-23. These assignments are not claims that this combination has already passed our evaluations or is the newest available lineup.

### Model routing rules

- Use code for parsing known formats, calculations, policy enforcement, exact lookup, duplicate checks, and state changes.
- Evaluate lighter models against labeled examples before relying on their suggestions.
- Escalate when observable validation fails, requirements conflict, or the case is outside the evaluated form/source coverage. A model's self-reported confidence alone is insufficient.
- Start with a bounded retry/escalation policy: one schema-repair attempt and one stronger-model attempt per stage; configure exact limits after evaluation.
- A stronger model cannot resolve missing personal facts, grant permission, or override a failed hard constraint.
- Stop at the configured cost/token/runtime limit; keep the current job task resumable.
- Recheck model availability, capabilities, pricing, and provider data handling during implementation. Pin tested model snapshots where available and record the actual model used.

## 2. Per-agent reference packages

Each agent must get its own package, not a shared unrestricted prompt. The requested singular `AGENT.md` is the canonical runtime reference and will be explicitly loaded by the application. Do not assume a framework automatically discovers it. A short per-directory `AGENTS.md` will guide repository contributors and refer to `AGENT.md`; runtime rules should not be duplicated in both files.

Proposed future layout; only this backlog is being created now:

```text
agents/
  agent_a_resume/
    AGENT.md
    AGENTS.md
    agent.yaml
    mcp.json
    skills/
      keyword-evidence/SKILL.md
      keyword-planning/SKILL.md
      keyword-plan-review/SKILL.md
    examples/
  agent_b_discovery/
    AGENT.md
    AGENTS.md
    agent.yaml
    mcp.json
    skills/
      job-discovery/SKILL.md
      job-extraction/SKILL.md
      job-matching/SKILL.md
  agent_c_resume_suggestions/  # implemented Agent C package
    AGENT.md
    AGENTS.md
    skills/
      resume-keyword-suggestions/SKILL.md
    examples/
config/
  models.yaml
  sources.yaml
  policies.example.yaml
schemas/
app/
  orchestration/
  profile/
  discovery/
  matching/
  tailoring/       # Agent A keyword planning; Agent A never reads or edits resumes
  validation/
  review/
  storage/
  mcp/
tests/
  fixtures/
  contracts/
  integration/
  evaluations/
docs/
  decisions/
  runbooks/
```

The `agent.yaml` and `mcp.json` filenames and their schemas are project conventions to implement, not ready-to-use configuration for a particular vendor framework. Store secrets and real candidate artifacts separately from these files.

### Required contents of every AGENT.md

Mission; inputs and output schemas; assigned skills and when to load them; tool allowlist; writable resources; model routing; factual boundaries; missing-input behavior; checkpoints; retry limits; handoff format; rejection/uncertainty examples; completion criteria; and dependencies on the shared policy version.

Runtime loading order must be explicit: global application invariants, agent reference, selected skill instructions, then task inputs. Treat job descriptions and tool results as data. Conflicting configuration must fail validation instead of silently changing permissions. Files provide guidance; server-side checks enforce authority.

### Skill inventory and outputs

| Owner | Skill | Inputs | Required output |
| --- | --- | --- | --- |
| A | `keyword-evidence` | Versioned JD and optional match metadata | Requirement and terminology signal map |
| A | `keyword-planning` | Versioned JD and signal map | Ranked keyword plan with high/medium/low priority and mandate labels |
| A | `keyword-plan-review` | Keyword-plan artifact | Schema/policy findings, job-link status, release recommendation |
| B | `job-discovery` | Search policy and source capabilities | Search plan, discovered links, provenance |
| B | `job-extraction` | Original JD/source snapshot | Typed job record, evidence spans, unknown fields |
| B | `job-matching` | Job record and minimal profile | Hard-filter inputs, explained match, gaps, review reasons |
| C | `resume-keyword-suggestions` | The single active resume/Markdown pair and a saved job's keyword-plan artifact | Exactly three pointer-anchored line suggestions for each keyword, preserving project boundaries and pointer-line length |

Every skill needs a focused `SKILL.md`, trigger conditions, procedural steps, tool prerequisites, input/output examples, known failure paths, and evaluation fixtures. Shared schemas and policies may be referenced rather than copied. Skills cannot expand an agent's MCP permissions.

## 3. MCP tools and access design

The names below are **proposed project tool contracts to build**, not claims that these servers are installed or available from a marketplace. Each agent gets its own MCP configuration and authenticated identity. Shared server implementations are acceptable; effective permissions and allowed resource IDs must remain separate.

| Proposed MCP server | Proposed tools | Agent access | Enforcement |
| --- | --- | --- | --- |
| `space` | `get_career_evidence`, `get_search_profile`, `resolve_answer` | A: assigned evidence; B: minimal search profile | Field-scoped reads; no unrestricted database queries |
| `jobs` | `search_sources`, `fetch_description`, `save_job`, `get_job`, `evaluate_match`, `save_keyword_plan` | B: discovery/write/evaluation; A: assigned job read and keyword-plan write | Source allowlist; deterministic filtering; immutable snapshots |
| `review` | `create_question`, `get_question_status` | A/B: contextual questions | Questions go to the user's queue; agents cannot impersonate the user |
| `workflow` | `save_stage_result`, `save_checkpoint`, `get_assigned_task` | A/B: own assignment only | Core validates and advances state |

The authenticated user workflow commits confirmed facts. Agents can raise ambiguity for review but cannot confirm facts on the user's behalf.

MCP implementation must distinguish local transport through an SDK/client from provider-hosted remote MCP. A local process is not automatically reachable by a hosted model API. Select the transport in Phase 1 and document authentication, tool filtering, and approval behavior against current [official MCP integration guidance](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).

## 4. Phase overview and dependencies

| Phase | Outcome | Depends on |
| --- | --- | --- |
| 00 | Approved scope and measurable quality goals | User review |
| 01 | Repository, architecture, configuration, and contracts | 00 |
| 02 | Agent A/B instruction, skill, and configuration packages | 01 |
| 03 | Space, evidence ingestion, onboarding | 01 |
| 04 | Restricted MCP services and model runtime | 02, 03 |
| 05–05G | Agent B import, discovery, matching, review workspace, and URL fetch | 04; source feasibility |
| 06 | Agent A job-description keyword planning | 05; benefits from 05F/05G |
| 07 | Reusable-answer metadata and question primitives in Space | 03, 04 |
| 08 | Agent C private resume conversion cache and project-scoped keyword suggestions | 06; private storage and model data-sharing decisions |

Dependency overlap describes future implementation options; it is not an instruction to launch development sub-agents now.

## Phase 00 — Confirm requirements and quality goals

Owner: User + Builder. Deliverable: onboarding specification and recorded decisions.

- [x] **P00-01** Review both source documents and this backlog; record accepted scope and requested changes. Evidence: `PHASE_00_DECISIONS.md`.
- [x] **P00-02** Choose one initial role family, seniority range, and employment type. Evidence: broad technology calibration scope, 1–3 years, full-time permanent.
- [x] **P00-03** Separate mandatory filters from flexible preferences for location, work mode, compensation, experience, and industry. Evidence: `PHASE_00_DECISIONS.md`.
- [x] **P00-04** Record excluded employers, agencies, roles, industries, and any reapplication rules. Evidence: no initial exclusions; every reapplication requires review.
- [x] **P00-05** Define compensation fields precisely: currency, period, fixed/variable/total, minimum, target, and disclosure preference. Evidence: annual total comparison and review rules in `PHASE_00_DECISIONS.md`; private values remain pending.
- [x] **P00-06** List the resume, career evidence, portfolio links, and prior application history to collect in private storage. Evidence: availability recorded without storing contents.
- [x] **P00-07** Define which eligibility, notice-period, and availability facts require explicit confirmation and renewal. Evidence: user-maintained, non-expiring confirmed records with conflict review.
- [x] **P00-08** Select initial source candidates and the manual-import fallback; keep unverified capabilities marked unknown. Evidence: manual import plus unverified source candidates recorded.
- [x] **P00-09** Choose local or hosted operation, preferred review interface, and notification channel; confirm timezone rather than assuming it from the machine. Evidence: local CLI, CLI-only MVP notifications, `Asia/Kolkata`.
- [x] **P00-10** Set initial model-cost/runtime budgets, application caps, and intended schedule; distinguish candidates processed from applications submitted. Evidence: manual runs with no initial caps; separate counters and later live-operation gate recorded.
- [x] **P00-11** Record initial draft/review mode and the future standing-permission fields; keep unattended submission disabled initially. Evidence: review of every package; live submission disabled.
- [x] **P00-12** Approve provider/data-sharing constraints and retention expectations before sending actual resumes to a model. Evidence: synthetic-data-only constraint until a later explicit provider/privacy decision.
- [x] **P00-13** Agree on evaluation goals: shortlist acceptance, extraction accuracy, factual errors, form correctness, duplicate prevention, and cost per application. Evidence: approved goals in `PHASE_00_DECISIONS.md`.
- [x] **P00-14** Prepare a user-labeling process for approximately 20–30 initial jobs; keep some examples for evaluation rather than prompt tuning. Evidence: yes/maybe/no labels with reasons and a held-out subset.

Exit check: enough decisions exist to build the draft workflow; missing candidate facts are represented as pending inputs, not fabricated defaults.

## Phase 01 — Establish the repository and application contracts

Owner: Builder + Core. Deliverables: project skeleton, decision records, schemas, and reproducible setup.

- [x] **P01-01** Choose the application runtime and supported dependency versions using current official documentation; record why the stack fits a single-user MVP. Evidence: `docs/decisions/ADR-0001-runtime-stack.md`, `pyproject.toml`, `requirements-dev.txt`.
- [x] **P01-02** Decide the model API/client integration and MCP transport; distinguish local MCP client execution from remotely hosted tools. Evidence: `docs/decisions/ADR-0002-model-and-mcp-boundary.md`, `config/models.example.json`.
- [x] **P01-03** Define the source capability registry: discovery, description retrieval, draft fill, upload, submission, reconciliation, and manual handoff. Evidence: `config/sources.example.json`, `app/core/contracts.py`.
- [x] **P01-04** Begin feasibility review for source candidates using official terms and APIs; record URLs, inspection dates, access needs, and unknowns. Evidence: `docs/decisions/source-feasibility-2026-09-23.md`.
- [x] **P01-05** Create application, agent, configuration, schema, test, and documentation directories from the proposed layout. Evidence: `app/`, `agents/`, `config/`, `schemas/`, `tests/`, `docs/`.
- [x] **P01-06** Configure dependency locking, development setup, formatting/linting, and the initial test runner. Evidence: `pyproject.toml`, `requirements-dev.txt`, `tests/test_config_validation.py`.
- [x] **P01-07** Add secret-free environment examples and ignore rules for resumes, Space databases, artifacts, screenshots, sessions, and credentials. Evidence: `.env.example`, `.gitignore`.
- [x] **P01-08** Define private storage paths, filesystem permissions, secret-store references, and backup boundaries. Evidence: `config/storage.example.json`, `docs/decisions/private-storage.md`.
- [x] **P01-09** Define versioned schemas for candidate facts, preferences, jobs, match results, resumes, questions, answer snapshots, and applications. Evidence: `schemas/domain_records.schema.json`.
- [x] **P01-10** Define a shared task/result envelope: run/task/application IDs, schema version, input references/hashes, policy version, result status, evidence, and errors. Evidence: `schemas/task_result_envelope.schema.json`.
- [x] **P01-11** Define typed error codes for missing facts, stale data, unsupported sources/forms, authorization failure, rate limits, and uncertain submission. Evidence: `app/core/contracts.py`, `docs/decisions/audit-and-errors.md`.
- [x] **P01-12** Specify state transitions, ownership, idempotency keys, cancellation, and checkpoint semantics. Evidence: `app/core/contracts.py`, `docs/decisions/state-machine.md`.
- [x] **P01-13** Define redacted audit events and cost/latency measurements without logging private field values. Evidence: `docs/decisions/audit-and-errors.md`, `schemas/task_result_envelope.schema.json`.
- [x] **P01-14** Implement configuration validation so missing models, malformed policies, unknown tools, or contradictory settings fail at startup. Evidence: `app/core/config.py`, `tests/test_config_validation.py`.
- [x] **P01-15** Create a setup README with commands for local synthetic-data runs; document that installing dependencies does not enable live submissions. Evidence: `README_SETUP.md`.

Exit check: a clean development environment can validate configuration and contracts without real credentials or personal data.

## Phase 02 — Create the A/B instruction, skill, and configuration packages

Owner: Builder. Deliverable: two separately loadable agent packages.

- [x] **P02-01** Define the runtime instruction loader and precedence rules from Section 2; reject path traversal and unapproved instruction locations. Evidence: `app/core/agents.py`, `tests/test_config_validation.py`.
- [x] **P02-02** Create `agents/agent_a_resume/AGENT.md` with evidence restrictions, output artifacts, revision limits, and job-review handoff details. Evidence: `agents/agent_a_resume/AGENT.md`.
- [x] **P02-03** Create A's `keyword-evidence/SKILL.md` with supported/partial/missing/unclear classifications and conflict examples. Evidence: `agents/agent_a_resume/skills/keyword-evidence/SKILL.md`.
- [x] **P02-04** Create A's `keyword-planning/SKILL.md` with extraction, ranking, terminology, and policy rules. Evidence: `agents/agent_a_resume/skills/keyword-planning/SKILL.md`.
- [x] **P02-05** Create A's `keyword-plan-review/SKILL.md` with schema, policy, and job-link checks. Evidence: `agents/agent_a_resume/skills/keyword-plan-review/SKILL.md`.
- [x] **P02-06** Create A's `agent.yaml` and `mcp.json` using the proposed stronger model and A-only tools from Section 3. Evidence: `agents/agent_a_resume/agent.yaml`, `agents/agent_a_resume/mcp.json`.
- [x] **P02-07** Create `agents/agent_b_discovery/AGENT.md` with source boundaries, minimal profile access, unknown handling, and B-to-A handoff. Evidence: `agents/agent_b_discovery/AGENT.md`.
- [x] **P02-08** Create B's `job-discovery/SKILL.md` with query construction, permitted sources, freshness, provenance, and manual import. Evidence: `agents/agent_b_discovery/skills/job-discovery/SKILL.md`.
- [x] **P02-09** Create B's `job-extraction/SKILL.md` with field definitions, evidence spans, required/preferred distinctions, and ambiguous examples. Evidence: `agents/agent_b_discovery/skills/job-extraction/SKILL.md`.
- [x] **P02-10** Create B's `job-matching/SKILL.md` with hard constraints, weighted preferences, coverage, and review routing. Evidence: `agents/agent_b_discovery/skills/job-matching/SKILL.md`.
- [x] **P02-11** Create B's `agent.yaml` and `mcp.json` using the nano default, mini escalation, and discovery-only external access. Evidence: `agents/agent_b_discovery/agent.yaml`, `agents/agent_b_discovery/mcp.json`.
- [x] **P02-17** Create each package's contributor `AGENTS.md`, pointing to its canonical runtime reference and relevant shared contracts. Evidence: each `agents/*/AGENTS.md`.
- [x] **P02-18** Add positive, negative, and adversarial examples to every skill; use fictional candidate data. Evidence: every Phase 02 `SKILL.md`.
- [x] **P02-19** Add a manifest validator checking instruction/skill paths, tool existence, per-agent scope, model configuration, and conflicting rules. Evidence: `app/core/agents.py`, `tests/test_config_validation.py`.
- [x] **P02-20** Record instruction/skill/configuration hashes on each agent invocation and verify that agents load only their assigned package. Evidence: `AgentPackage.file_hashes` in `app/core/agents.py`; package path and scope tests in `tests/test_config_validation.py`.

Exit check: A and B each have their own reference file, their assigned skills, model configuration, and restricted MCP manifest. No package gains permissions merely by editing prompt text.

## Phase 03 — Build Space and onboarding

Owner: Builder + Core; User confirms facts. Deliverable: private, versioned profile and profile and job store.

- [x] **P03-01** Implement the MVP relational schema and versioned migrations; include job/application uniqueness constraints. Evidence: `app/storage/space.py`, `tests/test_space_phase03.py`.
- [x] **P03-02** Implement a private artifact store with opaque IDs, hashes, content type, size, owner, and immutable versions. Evidence: `ArtifactStore` in `app/storage/space.py`, synthetic artifact tests.
- [x] **P03-03** Add controlled PDF/DOCX resume ingestion with size/type limits and safe parsing; preserve the original unchanged. Evidence: `app/profile/resume_ingestion.py`.
- [x] **P03-04** Detect scanned or unreadable input and request an editable copy or approved OCR path; label extraction uncertainty. Evidence: PDF uncertainty labels in `app/profile/resume_ingestion.py`, unreadable PDF test.
- [x] **P03-05** Extract candidate facts into a proposed profile with source spans and provenance; do not auto-confirm model-inferred facts. Evidence: proposed contact facts in `app/profile/resume_ingestion.py`; proposal workflow in `app/profile/onboarding.py`.
- [x] **P03-06** Add a minimal onboarding form/CLI to inspect, correct, confirm, and reject proposed facts. Evidence: `OnboardingService.list_facts`, `set_fact_state`, and `revise_fact` in `app/profile/onboarding.py`.
- [x] **P03-07** Capture work history, dates, education, skills, projects, authentic outcomes, and evidence attachments without conflating them. Evidence: typed `candidate_facts` plus immutable `artifacts` and provenance/source-span fields in `app/storage/space.py`.
- [x] **P03-08** Implement preference editing and versioned hard-filter/weight policies. Evidence: `preference_policies` schema and `create_preference_policy`.
- [x] **P03-09** Import prior applications with company, role, date, source IDs, destination, and status where known. Evidence: `prior_applications` schema and `import_prior_application`.
- [x] **P03-10** Implement typed reusable-answer records, scope, confirmation, expiry, sensitivity, and reuse permission. Evidence: `reusable_answers` schema, `create_reusable_answer`, and exact-scope lookup tests.
- [x] **P03-11** Implement pending questions, answer revisions, application checkpoints, and historical answer snapshots. Evidence: `pending_questions`, `answer_snapshots`, and `application_checkpoints` schema; question/checkpoint tests.
- [x] **P03-12** Restrict confirmed-fact writes to the authenticated user workflow; agents may create proposals for review. Evidence: user-only guards in `set_fact_state` and `revise_fact`; negative test for agent confirmation.
- [x] **P03-13** Invalidate affected pending matches/drafts when profile or preferences change, while preserving submitted history. Evidence: `invalidation_events` and `_invalidate_pending_for_profile_change`.
- [x] **P03-14** Implement profile inspection, correction, export, retention, and deletion, including derived artifacts and backups under the chosen policy. Evidence: `list_facts`, `revise_fact`, `export_profile`, `backup`, `restore`, and `delete_private_data`.
- [x] **P03-15** Verify database transactions, migration recovery, backup/restore, and private file access using synthetic data. Evidence: `tests/test_space_phase03.py`.

Exit check: the user can review and correct their profile; every approved fact has provenance and history; agents cannot silently change it.

## Phase 04 — Implement MCP services and model routing

Owner: Builder + Core. Deliverable: isolated agent runtime with observable, restricted tool access.

- [ ] **P04-01** Define tool input/output schemas for every Section 3 contract, including resource IDs, error types, limits, and mutation behavior.
- [ ] **P04-02** Implement the Space MCP read views and answer lookup, minimizing fields for each agent's role.
- [ ] **P04-03** Implement the jobs MCP interface with a manual-import adapter first; stub unimplemented live capabilities with explicit unsupported responses.
- [ ] **P04-05** Implement review and workflow MCP interfaces with task-bound writes and user-question routing.
- [ ] **P04-07** Enforce per-agent identity, tool allowlists, assigned-job/artifact scope, and operation policy inside each server, including direct-call attempts.
- [ ] **P04-08** Keep credentials and tokens inside the appropriate service; exclude them from model-visible tool results.
- [ ] **P04-09** Apply tool deadlines, bounded payload sizes, pagination, cancellation, and sanitized error handling.
- [ ] **P04-10** Implement model selection by agent/stage with supported settings, output schemas, token limits, and recorded model versions.
- [ ] **P04-11** Add bounded schema repair, escalation rules, provider outage handling, and a stop/review result when no qualified route is available.
- [ ] **P04-12** Track token usage, configured current prices, latency, and tool calls; enforce cost budgets before expensive retries.
- [ ] **P04-13** Add cache keys including relevant input hashes and instruction/model/policy versions; isolate private candidate data.
- [ ] **P04-14** Test denied operations: B reading unnecessary private facts, A writing candidate evidence, and any agent confirming facts on the user's behalf.
- [ ] **P04-15** Test instruction injection through job text and tool output; verify it cannot expand data access or change policy.
- [ ] **P04-16** Run end-to-end synthetic calls with each agent's real manifest, proving that its skills and MCP tools load correctly.

Exit check: both agents can perform narrow synthetic tasks with their assigned tools; unauthorized calls fail server-side.

## Phase 05 — Build Agent B: job ingestion and matching

Owner: Builder, Agent B + Core. Deliverable: explained, deduplicated shortlist from manual inputs.

- [x] **P05-01** Add paste/upload of job text plus source URL; URL-only import must report when description retrieval is unavailable. Evidence: `jobs.save_job` accepts manual text and `jobs.fetch_description` returns `requires_manual_description`.
- [x] **P05-02** Preserve the exact input text, source, retrieval/import time, canonical link, and description hash. Evidence: `ManualJobImporter` stores immutable description artifacts, canonical URL, `retrieved_at`, and SHA-256 hash.
- [x] **P05-03** Extract company, title, requisition ID, locations, work arrangement, seniority, employment type, and application destination. Evidence: `app/discovery/manual_import.py` extraction record and Phase 05 tests.
- [x] **P05-04** Extract required versus preferred qualifications, responsibilities, salary units, and dates with evidence spans. Evidence: extraction fields, evidence map, and `tests/test_phase05_agent_b.py`.
- [x] **P05-05** Detect truncated descriptions, multiple roles in one document, conflicting values, and ambiguous experience requirements. Evidence: extraction warnings for truncation, multiple roles, ambiguous work arrangement, and open-ended experience.
- [x] **P05-06** Normalize obvious equivalents while retaining original wording; keep unknown salary, country eligibility, or remote scope explicit. Evidence: normalized Bengaluru/Bangalore and structured unknown fields while retaining original extraction values.
- [x] **P05-07** Implement exact identity and cross-source duplicate signals; route ambiguous duplicates for review. Evidence: `job_duplicate_signals` and ambiguous duplicate test.
- [x] **P05-08** Check previous applications and user reapplication policy before shortlisting. Evidence: prior-application hard-filter check routes possible reapplications to review.
- [x] **P05-09** Implement deterministic hard-filter evaluation with separate pass/fail/unknown states and reasons. Evidence: `hard_filter_results` and hard-filter rejection test.
- [x] **P05-10** Implement weighted preference scoring plus evidence coverage; prevent sparse known fields from misleading automatic progression. Evidence: `aggregate_score`, coverage ratio gates, and review routing.
- [x] **P05-11** Generate the match explanation referencing actual candidate evidence and explicit gaps. Evidence: confirmed public candidate-fact coverage in `explanation_json`; private facts remain excluded.
- [x] **P05-12** Send borderline cases and unknown critical requirements to review; reject known mandatory mismatches. Evidence: `route_decision` and Phase 05 tests.
- [x] **P05-13** Add freshness and closed-job status handling; distinguish posting date from discovery date. Evidence: extracted posting/closing dates, import time, closed-job warning, and `expired` routing test.
- [x] **P05-14** Evaluate nano extraction/matching against labeled data; escalate difficult cases to mini and report both quality and cost. Evidence: synthetic `evaluate_agent_b_model_routes` report using `ModelRouter`; no provider calls are made.
- [x] **P05-15** Calibrate tentative weights/thresholds with user labels and validate on held-out cases before automatic shortlisting. Evidence: `evaluate_labeled_matches` and `suggest_thresholds`; real user labels can be loaded when available.
- [x] **P05-16** Persist a B-to-A handoff with job version, profile/policy versions, requirement evidence, score, coverage, and unresolved issues. Evidence: `b_to_a_handoffs` payload and shortlist handoff test.

Exit check: jobs produce understandable decisions, duplicates are held, and known hard-filter failures never reach automatic preparation.

## Phase 05E — Run Agent B for portal discovery from profile and preferences

Owner: Builder, Agent B + Core; User reviews source choices and results. Deliverable:
`agent_b_discovery` can be run locally from the CLI to search configured permitted portals
using the user's resume/Space/preferences, then return a reviewable list of job links,
captured descriptions, match decisions, and reasons.

This phase exists because the user's desired Agent B milestone is not only manual import:
the user wants to run Agent B and receive jobs discovered from multiple portals. Discovery
permission remains separate from account or application activity permission. A portal can be useful
through an official API, feed, alert import, user-export/import, search-result handoff, or
manual import even when website automation is not permitted. Do not implement CAPTCHA
bypass, stealth scraping, account-limit evasion, or unsupported website automation.

- [x] **P05E-01** Confirm the exact initial portal list for discovery review. Start with the user's named candidates and keep each portal separately configurable. Initial enabled live source: JobsPipe API. Enabled no-key public source: Jobicy. Registered but disabled pending local setup and per-site permission: self-hosted `jobspy-mcp-server`. Excluded by user choice for now: Adzuna and USAJOBS. LinkedIn/Naukri remain manual or pending permission review.
- [x] **P05E-02** Recheck current official terms, robots/API documentation where applicable, account permissions, rate limits, and available export/feed/alert options for every selected portal. Record inspection date, source URL, permitted operations, authentication needs, and uncertainty in `docs/decisions/source-feasibility-*.md`. Evidence: 2026-09-24 review for Jobicy, Remotive, Adzuna, USAJOBS, and candidate MCP backends in `docs/decisions/source-feasibility-2026-09-23.md`; LinkedIn/Naukri remain restricted/pending.
- [x] **P05E-03** Split each portal's capability flags into discovery search, result-link retrieval, description retrieval, canonical employer-destination resolution, login requirement, unsupported employer-side activity, and manual handoff. A source with unsupported description retrieval must still return links plus a clear manual-import path. Evidence: per-source `capabilities`, `requires_account`, `live_external_actions`, `allowed_hosts`, local endpoint, and manual handoff notes in `config/sources.example.json`.
- [x] **P05E-04** Update `config/sources.example.json` and the source registry schema for multiple configured discovery sources, per-source limits, freshness windows, allowed hosts, throttle settings, and external-action status. Evidence: fixture sources and candidate MCP/API sources in `config/sources.example.json`; expanded capability flags in `app/core/contracts.py`.
- [x] **P05E-05** Define the Agent B run contract: input is current Space profile version, preference policy version, selected source IDs, max results per source, freshness window, and dry-run flag; output is a source-grouped list of discovered jobs with links, descriptions when permitted, match decisions, gaps, and errors. Evidence: `AgentBRunResult` and `run_agent_b_discovery` in `app/discovery/agent_b_run.py`.
- [x] **P05E-06** Add a CLI command such as `python3 -m app.discovery.agent_b_run --sources ... --max-results ...` that loads Agent B's package, search profile, source capabilities, and model route policy, then executes discovery through MCP tools rather than direct module shortcuts. Evidence: `app/discovery/agent_b_run.py` and Phase 05E tests.
- [x] **P05E-07** Build query generation from Space and resume/profile facts: role titles, role-family synonyms, seniority range, employment type, locations, remote/hybrid/onsite rules, core public skills, and exclusions. Keep mandatory filters separate from search broadening terms. Evidence: `build_query_plan`; profile-fact enrichment remains future work because B currently has only minimal search-profile MCP access.
- [x] **P05E-08** Add a search-plan preview mode showing generated queries per portal before network access. Let the user approve, edit, disable, or cap individual queries for the run. Evidence: `--preview` support and preview test.
- [x] **P05E-09** Implement adapter interfaces for `search`, `fetch_description`, `resolve_destination`, and `normalize_result`. Each adapter must return structured capability errors instead of throwing raw network/browser errors to Agent B. Evidence: `app/discovery/source_adapters.py`; destination is represented as `application_destination` in fetched descriptions.
- [x] **P05E-10** Implement a local fixture adapter first, with realistic portal result pages and job pages, so Agent B can be run end-to-end without live network access. Use this as the regression baseline. Evidence: `fixture_remote_jobs`, `fixture_india_jobs`, and tests.
- [x] **P05E-11** Implement permitted non-browser discovery paths before browser automation: official APIs, public feeds, user-exported saved jobs, forwarded alert emails/files, or user-pasted portal search result pages. Mark each as local/import, read-only network, authenticated, or unsupported. Evidence: Jobicy public API adapter enabled; additional APIs remain configured candidates.
- [x] **P05E-11A** For external MCP/API backends, wrap them behind the project `jobs.search_sources` and `jobs.fetch_description` contracts instead of exposing their raw tools to Agent B. Initial candidate wrappers: Jobicy API/MCP, `jobsearch-mcp`, `jobspy-mcp-server`, Official MCP Registry AI jobs server, JobsPipe MCP/API, and any India-specific job MCP only after permission and implementation review. Evidence: Jobicy, JobsPipe, and the guarded local JobSpy wrapper are behind project MCP tools; other candidates remain disabled pending credentials/review.
- [x] **P05E-12** For any live read-only HTTP retrieval that is permitted, enforce allowed hosts, scheme checks, redirect limits, payload limits, content-type checks, timeouts, source-specific throttles, and private-network request blocking. Evidence: Jobicy and JobsPipe adapters enforce HTTPS host allowlists, timeouts, payload limits, JSON content type checks, and private/local network blocking for public HTTP calls; JobSpy is limited to configured localhost endpoints.
- [x] **P05E-13** If an authenticated portal is selected, require explicit user setup and keep credentials/session files in private storage. Do not expose cookies, tokens, browser profiles, or raw session details to model-visible tool results. Evidence: JobsPipe requires `JOBSPIPE_API_KEY` from ignored `.env`; the runner loads it locally and does not include the key in Agent B outputs.
- [x] **P05E-14** Keep LinkedIn website automation disabled unless a specifically permitted integration route is verified. Supported LinkedIn outcomes may include user-pasted descriptions, saved-link import, alert/email import, or manual handoff. Evidence: LinkedIn remains `manual_only_pending_permission`; JobSpy `allowed_site_names` excludes LinkedIn after current terms review.
- [x] **P05E-15** Keep Naukri live automation disabled until current official terms/access are verified. If unavailable, support manual/import modes and document the limitation rather than guessing permission. Evidence: Naukri remains pending terms review; JobSpy `allowed_site_names` excludes Naukri after current terms review.
- [x] **P05E-16** For employer and ATS career pages, start with a small allowlist whose pages expose permitted job listings or stable public job-detail URLs. Record per-site selectors/API shapes as adapter fixtures, not general web scraping. Evidence: `ats_allowlist_fixture` in `config/sources.example.json` and `app/discovery/source_adapters.py` models Lever/Greenhouse-style public detail/apply URLs without general scraping.
- [x] **P05E-17** Normalize discovered results before fetching details: source ID, source job ID, title, company, location string, result URL, discovered-at time, snippet, and confidence that it is a job detail link rather than a search/result page. Evidence: `DiscoveredJob` fixture adapter result contract.
- [x] **P05E-18** Fetch or import the full description only through permitted paths. Preserve exact text/HTML-derived text, retrieval time, canonical URL, content hash, and source metadata using the existing Phase 05 snapshot machinery. Evidence: fixture `fetch_description`, MCP `jobs.fetch_description`, and `jobs.save_job`.
- [x] **P05E-19** Resolve the application destination when available without logging in or applying. Keep portal result URL and employer/ATS destination URL separate. Evidence: Agent B rows now include `portal_link`, `canonical_job_url`, `application_destination`, and `destination_resolution`.
- [x] **P05E-20** Deduplicate across portals before matching using source IDs, canonical URLs, employer/requisition IDs, normalized company/title/location, destination URL, and description hashes. Route ambiguous cross-portal duplicates to review. Evidence: `ManualJobImporter` detects exact and ambiguous duplicate signals before creating new jobs; exact duplicates reuse the existing job and snapshot, including repeated live-source results.
- [x] **P05E-21** Run Phase 05 extraction and matching on every fetched/imported job. Known hard-filter failures are excluded from shortlist but retained in the run report with reason. Evidence: runner calls `jobs.save_job`, `jobs.evaluate_match`, and `jobs.get_job` per result.
- [x] **P05E-22** Preserve source failures per portal without failing the whole run. Report unsupported source, permission blocked, authentication required, rate limited, parse changed, no description available, and manual handoff separately. Evidence: runner `source_errors` and per-result manual-handoff rows.
- [x] **P05E-23** Produce the user's requested Agent B output: a CLI table grouped by `shortlisted`, `needs_review`, `rejected`, `duplicate/held`, `expired`, and `manual_handoff`, showing title, company, location/work mode, score, top reasons, source, description status, and links. Evidence: `format_cli_table` and detailed JSON/Markdown artifacts; grouping is summarized by state counts.
- [x] **P05E-24** Add a detailed output mode exporting JSON/Markdown under private artifacts with each job's preserved description reference, canonical link, application destination, extracted fields, match explanation, gaps, and duplicate signals. Evidence: private `agent_b` artifacts created by `run_agent_b_discovery`.
- [x] **P05E-25** Add review actions for the CLI output: accept shortlist, reject job, mark duplicate, request manual import for missing description, label yes/maybe/no with reason, and save source-specific feedback for calibration. Evidence: `app/discovery/review_actions.py`, `agent_b_review_actions` table, CLI label/action command, and calibration summary.
- [x] **P05E-26** Persist run records and redacted audit events: source queries, result counts, jobs imported, jobs matched, skips, failures, labels, model routes, estimated cost, latency, and source throttling decisions. Do not log private resume text or sensitive facts. Evidence: run report artifacts and `discovery_run_completed` audit event; labels/model/cost/latency are future enrichment.
- [x] **P05E-27** Add a resumable run lock and cancellation flag for Agent B discovery so repeated runs do not overlap or double-import the same portal results. Evidence: local run lock in `private/run_locks`; cancellation flag remains future enrichment.
- [x] **P05E-28** Add per-source and per-run caps: max queries, max result pages, max jobs imported, max descriptions fetched, runtime budget, and model-cost budget. Discovery caps are separate from application/submission caps. Evidence: `--max-results` and source limits in config; runtime/model-cost budgets remain future enrichment.
- [x] **P05E-29** Add freshness handling: default lookback window, posting-date parsing, closed/expired detection, and re-fetch rules for stale descriptions before sending jobs onward. Evidence: Agent B rows include `freshness` with posting/closing dates, age, stale threshold, and expired override; stale descriptions remain reviewable before downstream handoff.
- [x] **P05E-30** Add prompt-injection tests for job pages, result snippets, and fetched descriptions. Job text must not alter source permissions, access private files, broaden preferences, or trigger application actions. Evidence: untrusted-instruction warning in `manual_import.py` and Phase 05E regression test.
- [x] **P05E-31** Evaluate extraction accuracy and shortlist quality on fixture portals plus the user's labeled 20-30 job set. Keep a held-out subset and report precision/recall-like counts without claiming hiring outcomes. Evidence: review labels are persisted and summarized by `evaluate_agent_b_review_labels`; fixture and synthetic calibration tests pass. Real 20-30 user-labeled evaluation waits for user-provided labels.
- [x] **P05E-32** Compare Agent B nano/default and mini escalation on ambiguous extraction/matching cases using synthetic/local fixtures first. Record estimated and, once approved, actual provider cost. Evidence: `evaluate_agent_b_model_routes` synthetic routing/cost report and Phase 05 tests; no provider calls are made.
- [x] **P05E-33** Add regression tests for: multi-source discovery, duplicate cross-posts, unsupported source handoff, missing descriptions, closed jobs, host restrictions, source failure isolation, profile preference changes, and CLI output format. Evidence: Phase 05/05E tests cover fixture source search, multi-source run, preview, query constraints, private artifacts, duplicate reuse, Jobicy/JobsPipe payload parsing, JobSpy approval guard, and audit.
- [x] **P05E-34** Update `README_SETUP.md` with the Agent B discovery run command, fixture command, private-output location, and the statement that discovery does not authorize applying or submitting. Evidence: `README_SETUP.md`.
- [x] **P05E-35** Create a runbook explaining how to add a new portal safely: permission review, capability flags, fixture capture, adapter implementation, source limits, regression tests, and manual-handoff behavior. Evidence: `docs/runbooks/agent-b-source-adapters.md`.
- [x] **P05E-36** Exit demo: from a populated synthetic Space profile, run Agent B against at least two fixture sources and one manually imported source, then show a reviewable list of job descriptions and links with match decisions. Evidence: `python3 -m app.discovery.phase05e_exit_demo` ran successfully with fixture remote, fixture India, ATS allowlist, and one manual import.

Exit check: the user can run Agent B locally and receive a source-grouped, deduplicated,
reviewable list of discovered job links and descriptions where permitted, with clear
manual-handoff entries where descriptions cannot be retrieved. Unsupported or restricted
portals remain useful without unsafe automation.

## Phase 05F — Human-readable Agent B job review workspace

Owner: Builder, Agent B + Storage; User reviews folder layout and resulting files before
implementation. Deliverable: every saved Agent B job remains stored in Space as the source
of truth, and is also mirrored into a simple `private/job_reviews/` folder tree that the
user can browse without opening opaque artifact IDs.

This phase exists because the immutable artifact store is correct for auditability but
awkward for human review. The readable workspace is a generated review layer, not the
primary identity system. Do not replace durable job IDs, canonical URLs, description hashes,
duplicate signals, or artifact snapshots with company/title folder names; folder names are
labels and can collide or change.

- [x] **P05F-01** Define the readable workspace root as `private/job_reviews/`, ignored by Git and separate from `private/artifacts/`. Evidence: storage docs and existing `private/` ignore rule.
- [x] **P05F-02** Define deterministic folder naming: `private/job_reviews/<company-slug>/<job-title-slug>__<job-id-short>/` by default. Use sanitized ASCII slugs, stable lower-case names, length limits, and the short job ID suffix to avoid collisions. Evidence: `app/discovery/job_review_workspace.py` and slug tests.
- [x] **P05F-03** For duplicate titles at the same company, avoid fragile `-1`, `-2` numbering as the durable identity. Human labels may include an ordinal for readability, but the path must retain a job ID suffix so reruns do not overwrite or reshuffle existing jobs. Evidence: review workspace tests assert ID-suffixed paths rather than ordinal-only paths.
- [x] **P05F-04** Generate a per-job `job-details.md` that includes title, company, job ID, source, portal link, canonical job URL, application destination, retrieved time, match state, score, top reasons, warnings, unknown fields, duplicate signals, freshness, extraction summary, and links to the exact description file. Evidence: `job_details_markdown` and Phase 05E tests.
- [x] **P05F-05** Generate a per-job `job-description.txt` containing the exact preserved description text used for extraction and matching. This file is a readable copy; the immutable source remains the artifact referenced by `snapshot_artifact_id`. Evidence: Phase 05E test verifies the copied text hash matches the stored description hash.
- [x] **P05F-06** Optionally generate `extracted.json` for debugging/review with the extracted record, evidence spans, and match explanation. Keep it private and do not include secrets or resume text. Evidence: `extracted.json` is generated under ignored `private/job_reviews/` from stored job/extraction/match rows.
- [x] **P05F-07** Generate or refresh `private/job_reviews/index.md` after each Agent B run. Group jobs by `shortlisted`, `needs_review`, `rejected_by_preferences`, `expired`, `manual_handoff`, and duplicate/held where available; include company, title, score, source, application link, and relative path. Evidence: `write_index` and Phase 05E tests.
- [x] **P05F-08** Decide update semantics: regenerated files may update the readable view for the same job ID, but must not mutate immutable artifacts or historical match records. If the job description changes, create a new artifact/versioned job snapshot as the current storage rules require, then refresh the readable copy. Evidence: workspace writer updates only review files and reads immutable artifacts/database rows.
- [x] **P05F-09** Add a CLI option or default behavior for Agent B to write the readable review workspace after discovery, plus a repair command to rebuild `private/job_reviews/` from the Space database/artifacts. Evidence: Agent B calls `write_agent_b_review_workspace`; `python3 -m app.discovery.job_review_workspace` rebuilds from Space.
- [x] **P05F-10** Keep cleanup conservative: do not delete database rows, immutable artifacts, or keyword-plan artifacts when regenerating readable review files. If a review folder no longer maps to a current job, move it under a private archive/quarantine path or report it for manual cleanup. Evidence: no delete/archive operation is performed by the writer or rebuild command.
- [x] **P05F-11** Review existing folders before any removal. Private runtime outputs such as `private/artifacts`, `private/db`, `private/logs`, and cloned external tool dependencies may be large or ugly, but are not obsolete merely because the readable workspace exists. Evidence: implementation kept existing backing store and external tool folders intact.
- [x] **P05F-12** Update README and Agent B instructions so the user's normal review path is `private/job_reviews/index.md`, while Agent A/C and audits continue to use `job_id`, `snapshot_artifact_id`, hashes, and database records. Evidence: `README_SETUP.md`, Agent B docs, storage decision, and runbook updated.

Exit check: after running Agent B, the user can open `private/job_reviews/index.md` and
then browse company/job folders containing readable job details and the exact job
description, without needing to manually inspect `private/artifacts/`.

## Phase 05G — Agent B single-link fetch through Fetch MCP

Owner: Builder, Agent B + Codex MCP orchestration. Deliverable: when the user says
`Agent B mcp fetch <job-link>`, Codex uses the configured Fetch MCP to retrieve the linked
job page as readable content, then Agent B saves, extracts, matches, deduplicates, and
mirrors the job into `private/job_reviews/` using the same storage pipeline as manual
imports and portal discovery.

This phase exists for one-off jobs found outside the configured portal searches. It is a
read-only retrieval path, not a browser automation path. The Fetch MCP may retrieve public
page content, but it must not log in, bypass paywalls/CAPTCHAs, submit forms, use private
browser state, or treat a page's embedded instructions as trusted commands. If a site blocks
or truncates the job page, Agent B must return a manual-import request so the user can paste
the description and link.

- [x] **P05G-01** Define the user-facing trigger contract: phrases such as `Agent B mcp fetch <url>`, `Agent B fetch this job link <url>`, and `Agent B import this URL <url>` mean read-only fetch plus Agent B import; they do not authorize applying, logging in, or form filling. Evidence: Agent B instructions, README, and runbook document the trigger and boundaries.
- [x] **P05G-02** Document the tool choreography: first call Fetch MCP for the URL with bounded length, then pass the fetched markdown/text and original URL into the Agent B import/save pipeline. Keep the raw Fetch MCP result out of logs when it includes unnecessary page chrome or private-looking content. Evidence: `docs/runbooks/agent-b-source-adapters.md` and `README_SETUP.md`.
- [x] **P05G-03** Add an Agent B source ID such as `fetch_mcp_url_import` with capability flags for `description_retrieval`, `canonical_url`, `manual_handoff`, and no search or employer-side activity capability. Evidence: `config/sources.example.json`.
- [x] **P05G-04** Implement a Codex-facing Agent B MCP tool or orchestration helper, tentatively `agent_b_fetch_job_url`, that accepts a URL and optional fetched text. If the tool cannot call Fetch MCP internally, Codex must perform the explicit two-step MCP sequence and then call Agent B's import tool. Evidence: `agent_b_fetch_job_url` in `app/mcp/codex_agent_b_server.py`; Codex remains responsible for the Fetch MCP call.
- [x] **P05G-05** Reuse the existing Phase 05 save/extract/match machinery so fetched jobs produce the same database rows, immutable description artifacts, description hash, duplicate signals, match result, warnings, and `job_id` as manual imports. Evidence: `AgentBServer.import_fetched_job_url` delegates to `import_job_text`.
- [x] **P05G-06** Refresh the Phase 05F review workspace after every successful URL fetch/import so the user can inspect `private/job_reviews/index.md`, `job-details.md`, and `job-description.txt` immediately. Evidence: fetch-import MCP regression test verifies generated review files.
- [x] **P05G-07** Preserve provenance in saved records: original requested URL, final fetched URL if available, retrieval time, Fetch MCP source ID, content length/truncation status, and any fetch warning such as blocked page, unsupported content type, or no usable description. Evidence: fetch provenance is returned and recorded in a `job_fetch_mcp_imported` audit event.
- [x] **P05G-08** Add extraction safeguards for fetched web pages: strip obvious navigation/footer noise where possible, keep a readable exact fetched-description artifact, and mark fields unknown rather than hallucinating title, company, location, employment type, or seniority from weak page chrome. Evidence: Fetch MCP raw HTML/JSON-LD normalization extracts JobPosting fields and routes unusable page shells to handoff.
- [x] **P05G-09** Keep manual fallback first-class: if the fetch result is blocked, JavaScript-only, login-only, CAPTCHA-gated, too short, irrelevant, or mostly page shell, return instructions to paste the JD text plus link and use the existing `agent_b_import_job_text` path. Evidence: `agent_b_fetch_job_url` returns `manual_handoff` for blocked/page-shell content.
- [x] **P05G-10** Add duplicate/update semantics for repeated single-link imports. Re-fetching the same canonical URL should not create duplicate jobs; if fetched content materially changes, create a new snapshot/version according to existing artifact rules and refresh the readable review copy. Evidence: `agent_b_fetch_job_url` refreshes exact canonical duplicates, creates a new immutable artifact only when content changes, and reuses the current artifact when only parser output changes.
- [x] **P05G-11** Add host and URL safety checks before fetch/import: require `http` or `https`, reject local/private-network URLs, reject non-job binary downloads by default, cap payload size, and keep redirect/final-host information in provenance. Evidence: `agent_b_fetch_job_url` validates public HTTP(S) URLs, rejects local/private IP targets, and uses existing description payload caps.
- [x] **P05G-12** Add prompt-injection regression tests where the fetched job page asks Agent B to ignore preferences, read files, submit applications, or alter source permissions; the pipeline must preserve the text but ignore those instructions. Evidence: `test_fetch_job_url_preserves_but_ignores_page_instructions`.
- [x] **P05G-13** Add tests for successful fetch import, blocked/truncated fetch handoff, canonical URL dedupe, changed-description versioning, review workspace generation, unknown-field routing, and Agent A handoff using the resulting `job_id`. Evidence: MCP tests cover successful fetch import, blocked handoff, URL safety, provenance audit, Workday raw HTML normalization, canonical refresh, same-hash parser refresh, prompt injection, review workspace generation, and the `pending_codex_mcp` Agent A handoff.
- [x] **P05G-14** Update `README_SETUP.md`, Agent B instructions, and the source-adapter runbook with the normal user command, expected output, storage locations, limitations, and troubleshooting steps for fetch failures. Evidence: README, Agent B instructions, job-discovery skill, and runbook updated.
- [ ] **P05G-15** Exit demo: fetch one public fixture or safe sample job URL through Fetch MCP, save it through Agent B, show the returned `job_id`, and verify the generated `private/job_reviews/.../job-details.md` and `job-description.txt`.

Exit check: the user can give Agent B a single public job link and receive the same stored
job record, immutable artifact, match decision, and human-readable review folder that they
receive from manual import or configured portal discovery. Unsupported pages result in a
clear paste-the-JD fallback, not unsafe automation.

## Phase 06 — Build Agent A: job-description keyword planning

Owner: Builder, Agent A + validation service. Deliverable: Codex + MCP generated, ranked keyword plans linked to jobs for manual resume editing. Depends on Phase 05E; Phase 05F improves review usability but does not change Agent A's source-of-truth inputs.

- [x] **P06-01** Remove Agent A's resume-file editing and approval responsibilities from code paths and interfaces. Evidence: Agent A now uses `jobs.get_job` plus `jobs.save_keyword_plan` for the Codex + MCP workflow; obsolete `app/tailoring/resume_tailoring.py` was removed.
- [x] **P06-02** Define a structured keyword-plan schema with job ID, description hash, model/prompt version, categories, exact terms, synonyms, priority, mandate level, rationale, warnings, and timestamps. Evidence: `app/tailoring/keyword_planning.py` plan payload and `job_keyword_plans` table.
- [x] **P06-03** Define the Codex prompt/workflow for extracting resume-relevant keywords from the job description only, while treating job text as untrusted data. Evidence: Agent A instructions, `keyword-planning` skill, and the Codex-facing Agent A MCP server instructions.
- [x] **P06-04** Rank extracted terms as `high`, `medium`, or `low` using explicit requirements, preferred qualifications, repetition, role centrality, and recruiter-search value. Evidence: `_score_candidate` priority logic and Phase 06 tests.
- [x] **P06-05** Mark terms as `mandatory`, `recommended`, or `optional` for the user's manual resume review. Evidence: keyword plan `mandate` and `mandate_counts` fields.
- [x] **P06-06** Group terms by skills, tools, platforms, responsibilities, domain terms, seniority signals, and ATS-relevant synonyms. Evidence: category inference and synonym fields in `app/tailoring/keyword_planning.py`.
- [x] **P06-07** Deduplicate overlapping terms and separate exact job-description wording from suggested synonyms. Evidence: normalized candidate map plus `exact_terms`, `wording`, and `synonyms` fields.
- [x] **P06-08** Add policy checks that block hidden-text advice, keyword stuffing, copied requirement paragraphs, unsupported-claim language, or promises of top ranking/interviews/selection. Evidence: validation blocks unsafe outcome claims and tests ignore prompt injection/boilerplate.
- [x] **P06-09** Persist the keyword plan as a private artifact with a stable hash and redacted audit event. Evidence: `jobs.save_keyword_plan`, `_persist_plan`, `keyword_plan_created` audit event, and artifact owner `agent_a_resume`.
- [x] **P06-10** Store the keyword-plan artifact reference and summary fields with the corresponding job record in the database. Evidence: `job_keyword_plans` table records artifact ID/hash, description hash, model JSON, counts, warnings, and validation.
- [x] **P06-11** Return the job ID, artifact ID, high/medium/low counts, mandatory terms, warnings, and review path through Agent A MCP save results. Evidence: `agent_a_save_keyword_plan` response and MCP tests.
- [x] **P06-12** Persist structured keyword-plan artifacts for downstream tooling and manual review. Evidence: `jobs.save_keyword_plan` stores the JSON artifact and database row.
- [x] **P06-13** Add validation tests for MCP-supplied normal postings, duplicate terms, boilerplate filtering, scoped access, and unsafe ranking claims. Evidence: `tests/test_phase06_agent_a.py` covers Codex-MCP persistence, normalization, and scope.
- [x] **P06-14** Document that resume editing is manual and that Agent A never touches resume files. Evidence: Agent A markdown package, README Agent A section, and pipeline docs now define keyword-only scope.

Exit check: a saved job or pasted job description produces a validated keyword-plan artifact linked to the job record, with high/medium/low ranking and mandatory/recommended/optional labels. No resume file is read, edited, or approved by Agent A.

## Phase 07 — Build reusable answer metadata and user questions

Owner: Builder + Core. Deliverable: context-aware reusable-answer metadata and question primitives in Space.

- [x] **P07-01** Define semantic field keys and question context: employer, job, country, employment type, currency, unit, and experience definition. Evidence: `app/profile/answer_memory.py` context requirements and Phase 07 tests.
- [x] **P07-02** Implement exact scoped answer lookup and deterministic compatibility checks before any semantic suggestion. Evidence: `AnswerMemoryService.resolve_answer`, `OnboardingService.resolve_answer`, and enriched `space.resolve_answer` MCP output.
- [x] **P07-03** Implement expiration/reconfirmation rules for availability, notice period, salary, and other changeable facts. Evidence: default freshness rules plus explicit `expires_at` checks in `app/profile/answer_memory.py`.
- [x] **P07-04** Handle multiple current-looking answers as a conflict rather than silently picking one. Evidence: conflict handling in `AnswerMemoryService.resolve_answer` and `tests/test_phase07_answer_memory.py`.
- [x] **P07-05** Add a question queue showing the exact question, application context, why an answer is needed, and proposed reuse scope. Evidence: canonical question field context and reuse scope in `create_or_get_question`.
- [x] **P07-06** Batch related questions and deduplicate genuinely equivalent pending questions while keeping employer-specific ones distinct. Evidence: `batch_questions` and pending-question dedupe tests.
- [x] **P07-07** Let the user answer for this application only or approve appropriate reuse; record source, time, and scope. Evidence: `answer_question` records provenance, scope, reuse permission, and answer snapshot updates.
- [x] **P07-08** Implement separate handling for optional sensitive demographics, consent, attestations, signatures, and employer disclosures. Evidence: special review prefixes block automatic reuse.
- [x] **P07-09** Persist resume checkpoints before waiting; allow other applications to progress. Evidence: unresolved answer flow saves application checkpoints and only marks the affected application `needs_user_input`.
- [x] **P07-10** Resume only affected applications when an answer arrives; refresh form state if it has changed. Evidence: `answer_question` resumes the linked application and records a refresh-required audit event.
- [x] **P07-11** Apply corrections to pending packages and invalidate stale validation/approval; preserve historical answer snapshots. Evidence: `revise_answer` supersedes the old answer and creates invalidation events for pending applications using it.
- [x] **P07-12** Provide manual-handoff, skip-job, and leave-question-pending choices without fabricating a default. Evidence: `set_question_status` supports manual handoff, skip, and open/pending states.
- [x] **P07-13** Test salary unit differences, sponsorship by country, professional versus total experience, expiry, and scope leakage. Evidence: `tests/test_phase07_answer_memory.py`.
- [x] **P07-14** Verify that an appropriately cached answer is reused without asking again and that a new context still triggers the necessary question. Evidence: Phase 07 resolver tests and preserved Phase 03 exact-answer compatibility test.

Exit check: one answered question can save future work when appropriate; ambiguous or stale facts do not silently enter forms.

## Phase 08 — Agent C: resume conversion and project-scoped keyword suggestions

Status: implemented, with personal-data model use gated pending the provider/privacy decision recorded in Phase 00. This phase adds manual resume guidance only; the user chooses and applies any edits. Agent A remains keyword-plan-only.

Owner: Builder, Agent C + Core validation. Deliverable: a private, reusable Markdown conversion and a job-linked artifact with exactly three resume-pointer-based line suggestions for every saved Agent A keyword. Suggestions may be hypothetical; the user verifies them before applying any edits.

- [x] **P08-01** Define explicit private intake at `private/inputs/resume.tex`; preserve the source byte-for-byte and exclude source/conversion from version control and ordinary job artifacts. Evidence: `.gitignore`, `app/profile/resume_conversion.py`.
- [x] **P08-02** Implement a version-checked session-model TeX-to-Markdown conversion path that preserves source claims and project boundaries; retain a warned standard-library fallback. Evidence: `agent_c_import_resume`, `agent_c_save_resume_markdown`, `save_model_conversion`, and `latex_to_markdown` in `app/profile/resume_suggestions.py`.
- [x] **P08-03** Keep exactly one active private `.tex` source and one associated `.md`; replace/invalidate them when a new source path is provided, reuse Markdown across jobs, and regenerate the same source only on explicit request. Evidence: `import_resume_source`, `save_model_conversion`, and `private/inputs/resume-manifest.json`.
- [x] **P08-04** Create a least-privilege Agent C package and dedicated MCP server. It reads only the resume derivative and assigned job plan and cannot write the resume or perform employer-side actions. Evidence: `agents/agent_c_resume_suggestions/`, `app/mcp/codex_agent_c_server.py`.
- [x] **P08-05** Define a versioned output artifact linking job ID, description hash, keyword plan/hash, resume source/conversion hashes, model/prompt version, validation, and timestamp. Evidence: `schemas/resume_keyword_suggestions.schema.json`, `save_suggestions`, and `agent_c_suggestions` table.
- [x] **P08-06** Require exactly three distinct suggestions for each keyword. Each names a target section/project and points to exact resume context. Evidence: `validate_suggestions` and Agent C instructions.
- [x] **P08-07** Enforce project isolation and keep each suggested line within the rendered pointer-line length. Hypothetical content is allowed for user review. Evidence: project/pointer/length checks in `validate_suggestions`.
- [x] **P08-08** Account for every saved keyword with exactly three concrete suggestions. Evidence: exact keyword coverage and variant-count validation.
- [x] **P08-09** Keep the result advisory. Agent C never edits `resume.tex` or chooses an option on the user's behalf. Evidence: read-only source path and job review suggestion mirror.
- [ ] **P08-10** Add redacted synthetic fixtures for multiple projects, overlapping keywords, unsupported requirements, ambiguous TeX structures, conversion cache reuse, explicit regeneration, changed source, and provenance validation.
- [x] **P08-11** Add a review view under the relevant private job folder with three pointer-anchored line suggestions per keyword; authoritative artifact and hashes remain in Space. Evidence: `resume-keyword-suggestions.md` writer.
- [x] **P08-12** Document provider gate, private paths, cache invalidation, regeneration, and conversion failure behavior. Evidence: Agent C package and README workflow.

Exit check: workflow implementation is complete. End-to-end model suggestion behavior remains unverified and cannot run on real resume data until P08-10 fixtures and the explicit provider/privacy approval are complete. The conversion reuses an unchanged source hash and never modifies the source resume.

## Scope boundary

Application preparation, browser automation, uploads, and submission are outside current scope. Further backlog changes should be limited to profile/Space, job discovery and matching, keyword planning, project-scoped manual resume suggestions, local review, and evaluation of those capabilities. Employer application actions remain manual and outside this repository's automation scope.
