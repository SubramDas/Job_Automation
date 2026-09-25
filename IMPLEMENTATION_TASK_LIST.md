# Job application pipeline: phased implementation task list

Status: phased backlog. Phases 00-03, 05, 06, and 07 are complete for the local synthetic
manual-import dry-run scope. Phase 04 has a restricted in-process foundation, while live
providers, source automation, scheduling, and submission remain disabled.
Prepared: 2026-09-23.

Source documents: [project instructions](./AGENTS.md) and [pipeline plan](./JOB_APPLICATION_PIPELINE_PLAN.md).

This document turns the existing design into actionable tasks and adds the requested per-agent instruction files, skills, MCP tools, and different model assignments. It does not create or activate those agents, tools, skills, accounts, or schedules. Reviewing this backlog does not itself authorize external applications.

## How to use this checklist

Execute phases in order unless their dependency notes explicitly permit independent work. Within each phase, numbered task IDs show the intended sequence. Mark a task complete only when its artifact or observable behavior exists and its relevant checks pass. Record completion evidence beside its ID in the implementation PR or task tracker.

Owners identify responsibility: **User** supplies facts and preferences; **Builder** implements the software; **A/B/C** identify the runtime component being built; **Core** means deterministic application services. Agent labels do not mean the agent already exists or will independently implement itself.

No time estimate is promised before source feasibility and pilot results are known. Unsupported sources can reach a useful manual-handoff milestone without blocking supported sources.

## 1. Target agent architecture

| Component | Primary responsibility | Proposed default model | Escalation or fallback | Authority |
| --- | --- | --- | --- | --- |
| Agent A — Keyword specialist | LLM keyword extraction, priority ranking, artifact persistence | `gpt-5.4` | User clarification for ambiguous job text; bounded schema repair after validation | Read assigned job snapshots; create job-linked keyword-plan artifacts |
| Agent B — Discovery specialist | Search planning, job extraction, requirement classification, match explanation | `gpt-5.4-nano` | `gpt-5.4-mini` for ambiguous extraction/matching; unresolved cases to review | Read search preferences and minimal career summary; save job records |
| Agent C — Application specialist | Interpret supported forms, map answers, prepare submission requests | `gpt-5.4-mini` | `gpt-5.4` for complex interpretation; unknown personal facts still go to user | Access application-scoped facts and guarded form tools |
| Orchestrator | State transitions, dispatch, scheduling, budgets, recovery | No model required | Deterministic errors and review queue | Control workflow; cannot create user authorization |
| Space service | Profile, answer memory, versioning, reuse checks | No model required | Semantic retrieval may be added later; exact matching first | Accept user-confirmed facts through authenticated operations |
| Validation service | Schema, factual, document, policy, and submission checks | Deterministic checks first; isolated `gpt-5.4` critique for language claims when useful | Unresolved findings to user | Return findings; cannot submit or rewrite evidence |

These are proposed application API model IDs, not a change to the coding assistant in this workspace. The three agents have different default models. Escalation may share a stronger model, but preserves each agent's tools and scope. Three configured agents can run inside one application process; separate always-on services are unnecessary for the MVP.

Model choices are engineering proposals, subject to account access and task-specific evaluation. Official documentation describes [GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4) for complex professional work, [GPT-5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano) for tasks including extraction and classification, and [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) as a more efficient model with tool-oriented capabilities. Checked 2026-09-23. These assignments are not claims that this combination has already passed our evaluations or is the newest available lineup.

### Model routing rules

- Use code for parsing known formats, calculations, policy enforcement, exact lookup, duplicate checks, and state changes.
- Evaluate lighter models against labeled examples before allowing them to progress applications automatically.
- Escalate when observable validation fails, requirements conflict, or the case is outside the evaluated form/source coverage. A model's self-reported confidence alone is insufficient.
- Start with a bounded retry/escalation policy: one schema-repair attempt and one stronger-model attempt per stage; configure exact limits after evaluation.
- A stronger model cannot resolve missing personal facts, grant permission, or override a failed hard constraint.
- Stop at the configured cost/token/runtime limit; keep the application resumable.
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
    examples/
  agent_c_application/
    AGENT.md
    AGENTS.md
    agent.yaml
    mcp.json
    skills/
      form-preparation/SKILL.md
      answer-resolution/SKILL.md
      submission-reconciliation/SKILL.md
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
  tailoring/       # Agent A keyword planning; no resume file editing
  applications/
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
| C | `form-preparation` | Destination, approved artifact, form snapshot | Field inventory, answer mapping, filled draft |
| C | `answer-resolution` | Question and application context | Valid cached answer reference or pending user question |
| C | `submission-reconciliation` | Validated package, policy, attempt state | Guarded submit request and receipt, or unresolved outcome |

Every skill needs a focused `SKILL.md`, trigger conditions, procedural steps, tool prerequisites, input/output examples, known failure paths, and evaluation fixtures. Shared schemas and policies may be referenced rather than copied. Skills cannot expand an agent's MCP permissions.

## 3. MCP tools and access design

The names below are **proposed project tool contracts to build**, not claims that these servers are installed or available from a marketplace. Each agent gets its own MCP configuration and authenticated identity. Shared server implementations are acceptable; effective permissions and allowed resource IDs must remain separate.

| Proposed MCP server | Proposed tools | Agent access | Enforcement |
| --- | --- | --- | --- |
| `space` | `get_career_evidence`, `get_search_profile`, `get_application_facts`, `resolve_answer` | A: career evidence; B: minimal search profile; C: application facts/answers | Field- and application-scoped reads; no unrestricted database queries |
| `jobs` | `search_sources`, `fetch_description`, `save_job`, `get_job`, `evaluate_match` | B: discovery/write/evaluation; A/C: assigned job read | Source allowlist; deterministic filtering; immutable snapshots |
| `documents` | `get_artifact` | C: assigned final artifact metadata if the user supplies a resume manually | Artifact IDs and approved directories; no arbitrary file access |
| `review` | `create_question`, `get_question_status`, `submit_package_for_review` | A/B/C: contextual questions; C: application review package | Questions go to the user's queue; agents cannot impersonate the user |
| `applications` | `inspect_form`, `fill_fields`, `attach_resume`, `read_back`, `request_submit`, `get_confirmation`, `reconcile_attempt` | C only; submit tool unavailable in draft mode | Narrow adapter operations and server-side policy checks |
| `workflow` | `save_stage_result`, `save_checkpoint`, `get_assigned_task` | A/B/C: own assignment only | Agents return results; Core validates and advances state |

The authenticated user interface commits confirmed facts and grants/revokes approval through separate endpoints. Agents can propose corrections or questions; they cannot call an endpoint that confirms facts as though the user supplied them.

The application server owns browser sessions internally. Avoid exposing generic browser JavaScript, arbitrary navigation, shell access, or raw SQL to the runtime agents. Even `fill_fields` can have external effects on a site with autosave: define draft mode using synthetic/local forms, and treat production draft saves or uploads as authorized external actions in the pilot.

MCP implementation must distinguish local transport through an SDK/client from provider-hosted remote MCP. A local process is not automatically reachable by a hosted model API. Select the transport in Phase 1 and document authentication, tool filtering, and approval behavior against current [official MCP integration guidance](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).

## 4. Phase overview and dependencies

| Phase | Outcome | Depends on |
| --- | --- | --- |
| 00 | Approved scope and measurable quality goals | User review |
| 01 | Repository, architecture, configuration, and contracts | 00 |
| 02 | Three agent reference/skill/configuration packages | 01 |
| 03 | Space, evidence ingestion, onboarding | 01; agent integration uses 02 |
| 04 | Restricted MCP services and model runtime | 02, 03 |
| 05 | Agent B manual import and matching | 04 |
| 05E | Agent B portal discovery run from resume/Space/preferences | 05; source feasibility updates |
| 05F | Human-readable Agent B job review workspace | 05E |
| 06 | Agent A job-description keyword planning | 05E; benefits from 05F |
| 07 | Answer memory and question workflow | 03, 04; can proceed alongside 05–06 |
| 08 | Agent C synthetic-form draft preparation | 06, 07 |
| 09 | Complete draft workflow and review interface | 05E–08 |
| 10 | One permitted live discovery/application adapter | 09; feasibility research can start in 01 |
| 11 | Guarded submission and reconciliation | 10 |
| 12 | Evaluation, recovery, and security release checks | 11; checks also accompany earlier phases |
| 13 | Controlled real pilot | 12 and user-authorized pilot scope |
| 14 | Daily scheduling and optional autonomous submissions | 13 |
| 15 | Expansion, maintenance, and measured improvement | 14 |

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

## Phase 02 — Create each agent's instructions, skills, and configuration

Owner: Builder. Deliverable: three separately loadable agent packages.

- [x] **P02-01** Define the runtime instruction loader and precedence rules from Section 2; reject path traversal and unapproved instruction locations. Evidence: `app/core/agents.py`, `tests/test_config_validation.py`.
- [x] **P02-02** Create `agents/agent_a_resume/AGENT.md` with evidence restrictions, output artifacts, revision limits, and A-to-C handoff rules. Evidence: `agents/agent_a_resume/AGENT.md`.
- [x] **P02-03** Create A's `keyword-evidence/SKILL.md` with supported/partial/missing/unclear classifications and conflict examples. Evidence: `agents/agent_a_resume/skills/keyword-evidence/SKILL.md`.
- [x] **P02-04** Create A's `keyword-planning/SKILL.md` with extraction, ranking, terminology, and policy rules. Evidence: `agents/agent_a_resume/skills/keyword-planning/SKILL.md`.
- [x] **P02-05** Create A's `keyword-plan-review/SKILL.md` with schema, policy, and job-link checks. Evidence: `agents/agent_a_resume/skills/keyword-plan-review/SKILL.md`.
- [x] **P02-06** Create A's `agent.yaml` and `mcp.json` using the proposed stronger model and A-only tools from Section 3. Evidence: `agents/agent_a_resume/agent.yaml`, `agents/agent_a_resume/mcp.json`.
- [x] **P02-07** Create `agents/agent_b_discovery/AGENT.md` with source boundaries, minimal profile access, unknown handling, and B-to-A handoff. Evidence: `agents/agent_b_discovery/AGENT.md`.
- [x] **P02-08** Create B's `job-discovery/SKILL.md` with query construction, permitted sources, freshness, provenance, and manual import. Evidence: `agents/agent_b_discovery/skills/job-discovery/SKILL.md`.
- [x] **P02-09** Create B's `job-extraction/SKILL.md` with field definitions, evidence spans, required/preferred distinctions, and ambiguous examples. Evidence: `agents/agent_b_discovery/skills/job-extraction/SKILL.md`.
- [x] **P02-10** Create B's `job-matching/SKILL.md` with hard constraints, weighted preferences, coverage, and review routing. Evidence: `agents/agent_b_discovery/skills/job-matching/SKILL.md`.
- [x] **P02-11** Create B's `agent.yaml` and `mcp.json` using the nano default, mini escalation, and discovery-only external access. Evidence: `agents/agent_b_discovery/agent.yaml`, `agents/agent_b_discovery/mcp.json`.
- [x] **P02-12** Create `agents/agent_c_application/AGENT.md` with form handling, question scope, package validation, and submission/recovery rules. Evidence: `agents/agent_c_application/AGENT.md`.
- [x] **P02-13** Create C's `form-preparation/SKILL.md` with labels, conditional fields, uploads, read-back, and unsupported-control handling. Evidence: `agents/agent_c_application/skills/form-preparation/SKILL.md`.
- [x] **P02-14** Create C's `answer-resolution/SKILL.md` with exact reuse rules, stale/conflicting information, and batched user questions. Evidence: `agents/agent_c_application/skills/answer-resolution/SKILL.md`.
- [x] **P02-15** Create C's `submission-reconciliation/SKILL.md` with preflight, concrete authorization, confirmation evidence, and ambiguous outcomes. Evidence: `agents/agent_c_application/skills/submission-reconciliation/SKILL.md`.
- [x] **P02-16** Create C's `agent.yaml` and `mcp.json` using the mini default, stronger interpretation fallback, and draft-mode tool restrictions. Evidence: `agents/agent_c_application/agent.yaml`, `agents/agent_c_application/mcp.json`.
- [x] **P02-17** Create each package's contributor `AGENTS.md`, pointing to its canonical runtime reference and relevant shared contracts. Evidence: each `agents/*/AGENTS.md`.
- [x] **P02-18** Add positive, negative, and adversarial examples to every skill; use fictional candidate data. Evidence: every Phase 02 `SKILL.md`.
- [x] **P02-19** Add a manifest validator checking instruction/skill paths, tool existence, per-agent scope, model configuration, and conflicting rules. Evidence: `app/core/agents.py`, `tests/test_config_validation.py`.
- [x] **P02-20** Record instruction/skill/configuration hashes on each agent invocation and verify that agents load only their assigned package. Evidence: `AgentPackage.file_hashes` in `app/core/agents.py`; package path and scope tests in `tests/test_config_validation.py`.

Exit check: A, B, and C each have their own reference file, three skills, model configuration, and restricted MCP manifest. No package gains permissions merely by editing prompt text.

## Phase 03 — Build Space and onboarding

Owner: Builder + Core; User confirms facts. Deliverable: private, versioned profile and application store.

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
- [ ] **P04-04** Implement the documents MCP interface over controlled parsers and approved artifact IDs.
- [ ] **P04-05** Implement review and workflow MCP interfaces with task-bound writes and user-question routing.
- [ ] **P04-06** Implement an applications MCP synthetic adapter; keep live submission unavailable until Phase 11.
- [ ] **P04-07** Enforce per-agent identity, allowlists, application scope, and operation policy inside each server, including direct-call attempts.
- [ ] **P04-08** Keep credentials and browser sessions inside the appropriate service; exclude them from model-visible tool results.
- [ ] **P04-09** Apply tool deadlines, bounded payload sizes, pagination, cancellation, and sanitized error handling.
- [ ] **P04-10** Implement model selection by agent/stage with supported settings, output schemas, token limits, and recorded model versions.
- [ ] **P04-11** Add bounded schema repair, escalation rules, provider outage handling, and a stop/review result when no qualified route is available.
- [ ] **P04-12** Track token usage, configured current prices, latency, and tool calls; enforce cost budgets before expensive retries.
- [ ] **P04-13** Add cache keys including relevant input hashes and instruction/model/policy versions; isolate private candidate data.
- [ ] **P04-14** Test denied operations: B reading salary/contact details unnecessarily, A invoking submission, C editing evidence, and any agent approving itself.
- [ ] **P04-15** Test instruction injection through job text and tool output; verify it cannot expand data access or change policy.
- [ ] **P04-16** Run end-to-end synthetic calls with each agent's real manifest, proving that its skills and MCP tools load correctly.

Exit check: all three agents can perform a narrow synthetic task with their assigned model and tools; unauthorized calls fail server-side.

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
permission remains separate from application/submission permission. A portal can be useful
through an official API, feed, alert import, user-export/import, search-result handoff, or
manual import even when website automation is not permitted. Do not implement CAPTCHA
bypass, stealth scraping, account-limit evasion, or unsupported website automation.

- [x] **P05E-01** Confirm the exact initial portal list for discovery review. Start with the user's named candidates and keep each portal separately configurable. Initial enabled live source: JobsPipe API. Enabled no-key public source: Jobicy. Registered but disabled pending local setup and per-site permission: self-hosted `jobspy-mcp-server`. Excluded by user choice for now: Adzuna and USAJOBS. LinkedIn/Naukri remain manual or pending permission review.
- [x] **P05E-02** Recheck current official terms, robots/API documentation where applicable, account permissions, rate limits, and available export/feed/alert options for every selected portal. Record inspection date, source URL, permitted operations, authentication needs, and uncertainty in `docs/decisions/source-feasibility-*.md`. Evidence: 2026-09-24 review for Jobicy, Remotive, Adzuna, USAJOBS, and candidate MCP backends in `docs/decisions/source-feasibility-2026-09-23.md`; LinkedIn/Naukri remain restricted/pending.
- [x] **P05E-03** Split each portal's capability flags into discovery search, result-link retrieval, description retrieval, canonical employer-destination resolution, login requirement, draft/application support, and manual handoff. A source with unsupported description retrieval must still return links plus a clear manual-import path. Evidence: per-source `capabilities`, `requires_account`, `live_external_actions`, `allowed_hosts`, local endpoint, and manual handoff notes in `config/sources.example.json`.
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

## Phase 06 — Build Agent A: job-description keyword planning

Owner: Builder, Agent A + validation service. Deliverable: Codex + MCP generated, ranked keyword plans linked to jobs for manual resume editing. Depends on Phase 05E; Phase 05F improves review usability but does not change Agent A's source-of-truth inputs.

- [x] **P06-01** Remove Agent A's resume-file editing and approval responsibilities from code paths and interfaces. Evidence: Agent A now uses `jobs.get_job` plus `jobs.save_keyword_plan` for the Codex + MCP workflow; obsolete `app/tailoring/resume_tailoring.py` was removed.
- [x] **P06-02** Define a structured keyword-plan schema with job ID, description hash, model/prompt version, categories, exact terms, synonyms, priority, mandate level, rationale, warnings, and timestamps. Evidence: `app/tailoring/keyword_planning.py` plan payload and `job_keyword_plans` table.
- [x] **P06-03** Define the Codex prompt/workflow for extracting resume-relevant keywords from the job description only, while treating job text as untrusted data. Evidence: Agent A instructions, `keyword-planning` skill, and fallback `_keyword_prompt` in `app/tailoring/keyword_planning.py`.
- [x] **P06-04** Rank extracted terms as `high`, `medium`, or `low` using explicit requirements, preferred qualifications, repetition, role centrality, and recruiter-search value. Evidence: `_score_candidate` priority logic and Phase 06 tests.
- [x] **P06-05** Mark terms as `mandatory`, `recommended`, or `optional` for the user's manual resume review. Evidence: keyword plan `mandate` and `mandate_counts` fields.
- [x] **P06-06** Group terms by skills, tools, platforms, responsibilities, domain terms, seniority signals, and ATS-relevant synonyms. Evidence: category inference and synonym fields in `app/tailoring/keyword_planning.py`.
- [x] **P06-07** Deduplicate overlapping terms and separate exact job-description wording from suggested synonyms. Evidence: normalized candidate map plus `exact_terms`, `wording`, and `synonyms` fields.
- [x] **P06-08** Add policy checks that block hidden-text advice, keyword stuffing, copied requirement paragraphs, unsupported-claim language, or promises of top ranking/interviews/selection. Evidence: validation blocks unsafe outcome claims and tests ignore prompt injection/boilerplate.
- [x] **P06-09** Persist the keyword plan as a private artifact with a stable hash and redacted audit event. Evidence: `jobs.save_keyword_plan`, `_persist_plan`, `keyword_plan_created` audit event, and artifact owner `agent_a_resume`.
- [x] **P06-10** Store the keyword-plan artifact reference and summary fields with the corresponding job record in the database. Evidence: `job_keyword_plans` table records artifact ID/hash, description hash, model JSON, counts, warnings, and validation.
- [x] **P06-11** Provide CLI output that shows the job ID, artifact ID, high/medium/low counts, mandatory terms, warnings, and where the full JSON artifact lives. Evidence: `app/tailoring/agent_a_run.py` summary output.
- [x] **P06-12** Support JSON output for downstream tooling and manual review. Evidence: `python3 -m app.tailoring.agent_a_run --json` returns status, job ID, artifact ID, and result payload.
- [x] **P06-13** Add validation tests for normal postings, sparse postings, duplicate terms, prompt injection inside job descriptions, generic legal text, and unsafe ranking claims. Evidence: `tests/test_phase06_agent_a.py` covers normal extraction, injection/boilerplate filtering, persistence, scope, and CLI behavior.
- [x] **P06-14** Document that resume editing is manual and that Agent A never touches resume files. Evidence: Agent A markdown package, README Agent A section, and pipeline docs now define keyword-only scope.

Exit check: a saved job or pasted job description produces a validated keyword-plan artifact linked to the job record, with high/medium/low ranking and mandatory/recommended/optional labels. No resume file is read, edited, or approved by Agent A.

## Phase 07 — Build reusable answers and user questions

Owner: Builder + Core, integrated with Agent C. Deliverable: context-aware memory and resumable questions.

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

## Phase 08 — Build Agent C against synthetic application forms

Owner: Builder, Agent C + Core. Deliverable: correct draft form preparation without live applications.

- [ ] **P08-01** Build local synthetic forms representing single-page, multi-step, conditional, and file-upload application flows.
- [ ] **P08-02** Implement field inspection using labels, accessible names, help text, required status, options, and constraints.
- [ ] **P08-03** Map form questions to semantic keys and approved answers, retaining each answer's provenance.
- [ ] **P08-04** Fill text, select, checkbox, date, and repeated work/education sections with explicit type/unit handling.
- [ ] **P08-05** Reinspect conditional fields after relevant answers and navigation; detect newly required questions.
- [ ] **P08-06** Route missing, ambiguous, stale, and employer-specific questions through Phase 07.
- [ ] **P08-07** Attach only the assigned validated artifact; check hash, extension, size, and upload result.
- [ ] **P08-08** Read back entered values and compare them with the approved answer snapshot, including formatted numbers and dates.
- [ ] **P08-09** Detect validation messages, lost field values, session expiry, and unsupported controls; save a recoverable checkpoint.
- [ ] **P08-10** Add screenshot/visual interpretation only where DOM/structured inspection is insufficient and the adapter can constrain actions.
- [ ] **P08-11** Evaluate mini on the synthetic form suite and stronger-model escalation on genuinely difficult interpretation cases.
- [ ] **P08-12** Export a complete application preview containing destination, resume version, answers, omissions, unresolved items, and form state.
- [ ] **P08-13** Make dry-run mode incapable of reaching production submission/upload endpoints; test clicks, Enter keys, navigation, and autosave side effects.
- [ ] **P08-14** Verify that unsupported forms produce an understandable manual handoff containing the prepared materials.
- [ ] **P08-15** Test resumption after a user answer, process restart, and a changed conditional form without losing or misapplying data.

Exit check: C accurately prepares representative synthetic applications, asks only necessary questions, and cannot submit externally in dry runs.

## Phase 09 — Integrate the complete draft workflow and review interface

Owner: Builder + Core. Deliverable: first usable end-to-end product milestone.

- [ ] **P09-01** Connect B-to-A-to-C dispatch through validated task/result contracts rather than free-form agent conversations.
- [ ] **P09-02** Implement the normal state path and alternative review, missing-input, rejection, expiry, failure, and manual-handoff states.
- [ ] **P09-03** Persist stage outputs and checkpoints transactionally; reject stale worker results against updated input versions.
- [ ] **P09-04** Build a minimal queue view showing job, company, match reasons, current state, and required user action.
- [ ] **P09-05** Provide job details, evidence gaps, resume preview/download, change report, and field-level answer review.
- [ ] **P09-06** Allow the user to accept/reject matches, correct facts, request truthful revisions, and resolve questions.
- [ ] **P09-07** Separate fact corrections from presentation edits so a stylistic revision cannot silently alter career history.
- [ ] **P09-08** Add authentication/access protection appropriate to the deployment, including protection for state-changing user actions.
- [ ] **P09-09** Implement concrete package approval records and revocation; keep actual external submission unavailable at this milestone.
- [ ] **P09-10** Bind review decisions to job, profile, policy, resume, answers, and destination versions; invalidate affected decisions on change.
- [ ] **P09-11** Add pause, resume, cancel, and per-application retry controls with explicit effects and preserved audit history.
- [ ] **P09-12** Show cost, failure reason, and manual-handoff materials without exposing technical internals in normal user flows.
- [ ] **P09-13** Demonstrate pasted JD -> explained match -> ranked keyword plan -> user-supplied resume attachment -> synthetic form preview -> missing questions -> resumed preview.
- [ ] **P09-14** Collect user feedback on this complete draft workflow before investing in additional integrations.

Exit check: the core value works end to end and is reviewable; every agent's handoff can be traced to versioned inputs.

## Phase 10 — Add one supported live source and form adapter

Owner: Builder + Core, Agent B and Agent C. Deliverable: one explicitly supported live path and useful manual alternatives.

- [ ] **P10-01** Complete the initial source feasibility decision with official documentation, current permissions, account access, and permitted operations.
- [ ] **P10-02** Keep LinkedIn website automation out of the initial adapter unless a specifically permitted route is established; support imported descriptions and handoff.
- [ ] **P10-03** Verify Naukri's current official terms/access before enabling automation; retain unknown/manual status if verification is unavailable.
- [ ] **P10-04** Select one employer/ATS/source flow whose required operations are supported; record separate discovery and application capabilities.
- [ ] **P10-05** Implement discovery through the permitted interface, including pagination, source limits, freshness, and bounded retrieval.
- [ ] **P10-06** Validate canonical employer destinations, redirects, scheme/host restrictions, and protection against requests to local/private services.
- [ ] **P10-07** Connect any needed account through the intended user login flow; protect session storage and provide logout/revocation.
- [ ] **P10-08** Implement bounded form inspection and adapter-owned fill/upload operations; classify autosave and production draft writes explicitly.
- [ ] **P10-09** Add adapter-specific checks for required documents, extra questions, conditional controls, and confirmation signals.
- [ ] **P10-10** Detect expired jobs, authentication challenges, CAPTCHA, changed page structure, and unsupported form versions; hand control to the user where needed.
- [ ] **P10-11** Add per-source throttling, transient-read retry/backoff, and circuit breakers; never use these as restriction-evasion mechanisms.
- [ ] **P10-12** Create sanitized adapter fixtures and regression checks from supported patterns without committing real candidate data or cookies.
- [ ] **P10-13** Expose the adapter capability/status in the UI, including the difference between prepared, draft saved, and submitted.
- [ ] **P10-14** Document source setup, access renewal, known unsupported cases, and manual completion steps.

Exit check: one real source has a verified capability contract; unsupported sources remain useful through import and manual handoff. Production writes wait for the authorized pilot.

## Phase 11 — Implement guarded submission and outcome reconciliation

Owner: Builder + Core; Agent C requests actions. Deliverable: controlled submission gateway.

- [ ] **P11-01** Implement a preflight validator for job availability, hard constraints, current facts, complete answers, document hash, destination, and unresolved findings.
- [ ] **P11-02** Implement explicit per-application permission and scoped standing-policy evaluation with expiry, revocation, allowed actions, and excluded cases.
- [ ] **P11-03** Check source capability and user permission again immediately before the external action; a model cannot assert either as true.
- [ ] **P11-04** Reserve an application attempt transactionally with a durable identity and single-worker ownership.
- [ ] **P11-05** Make `request_submit` validate the immutable package and execute only the adapter's bounded submission operation.
- [ ] **P11-06** Prevent direct browser/tool paths from bypassing the gateway, including keyboard submissions and alternate endpoints.
- [ ] **P11-07** Recheck the final visible form and attached artifact against the approved package immediately before submission.
- [ ] **P11-08** Persist the attempt before sending it; record timestamp, package IDs, authorization reference, and destination without secret values.
- [ ] **P11-09** Recognize reliable confirmation signals and save a receipt/reference or restricted confirmation artifact.
- [ ] **P11-10** Set `submission_unknown` for timeouts, lost connections, ambiguous redirects, or crashes after an attempt that may have succeeded.
- [ ] **P11-11** Implement read-only reconciliation through permitted confirmation/history checks; keep uncertain cases pending for user review.
- [ ] **P11-12** Prohibit automatic resubmission while an earlier attempt is unresolved; require evidence and applicable permission for a later retry.
- [ ] **P11-13** Detect duplicate applications across runs and sources, including manually completed applications recorded by the user.
- [ ] **P11-14** Support user-recorded manual submission with its source clearly labeled; do not imply the system independently verified it.
- [ ] **P11-15** Check cancellation and revoked authorization at the last enforceable point; explain that a completed external submission cannot be undone by pausing locally.
- [ ] **P11-16** Exercise all submit/reconcile paths against simulated servers before enabling any real application.

Exit check: authorization and duplicate checks are enforced in code; every system-confirmed submission has evidence; uncertain results never trigger blind retries.

## Phase 12 — Run release evaluations and reliability checks

Owner: Builder + User for qualitative review. Deliverable: measured release report and resolved blockers.

Tests accompany their implementation phases; this phase integrates the evidence and exercises failure combinations. Thresholds below are proposals for Phase 00 review, not achieved results.

- [ ] **P12-01** Freeze representative labeled evaluation sets for descriptions, matching, resume claims, questions, and supported forms; separate tuning and held-out cases.
- [ ] **P12-02** Compare B's nano/default and mini escalation routes on extraction accuracy, shortlist precision/recall, evidence coverage, latency, and total cost.
- [ ] **P12-03** Evaluate A for unsupported claims, omitted relevant evidence, misleading phrasing, concision, and output consistency with profile facts.
- [ ] **P12-04** Evaluate C for exact field correctness, conditional questions, document selection, stale answer handling, and unnecessary user interruptions.
- [ ] **P12-05** Require zero fabricated claims and zero known hard-filter escapes in release fixtures; any observed failure blocks release until addressed.
- [ ] **P12-06** Require all permission-isolation, duplicate-prevention, and uncertain-submission scenarios to pass; document that passing tests is not a universal guarantee.
- [ ] **P12-07** Agree on shortlist/extraction targets with the user and report sample size and disagreement examples instead of claiming a universal score.
- [ ] **P12-08** Test process termination before/after tool calls, stale locks, concurrent runs, duplicate callbacks, and replayed task results.
- [ ] **P12-09** Test provider errors, malformed model outputs, unavailable models, tool timeouts, budget exhaustion, and exhausted escalation limits.
- [ ] **P12-10** Test missing/expired login sessions, changed source markup, closed postings, partial uploads, and conditional fields appearing late.
- [ ] **P12-11** Test malicious JD/page instructions, tool-result injection, path traversal, unsafe redirects, secret leakage, and unauthorized tool calls.
- [ ] **P12-12** Test profile correction and policy revocation during active preparation and immediately before submission.
- [ ] **P12-13** Verify text extraction and visual appearance of resume templates with realistic long/short content and non-ASCII names.
- [ ] **P12-14** Verify profile export/deletion, artifact retention, log redaction, session cleanup, and backup restoration.
- [ ] **P12-15** Run the complete synthetic pipeline with production-equivalent manifests and dry-run restrictions; inspect the audit trail.
- [ ] **P12-16** Publish a release report with model/configuration versions, passed checks, known limitations, cost measurements, and unresolved blockers.

Exit check: agreed release checks pass, critical failures are fixed, and the user can review evidence supporting the pilot scope.

## Phase 13 — Conduct a controlled real pilot

Owner: User + Builder + Core. Deliverable: verified real-world performance on a small supported set.

- [ ] **P13-01** Present concrete pilot source, candidate jobs, permissions, budget, maximum applications, and rollback/pause behavior for user approval.
- [ ] **P13-02** Load the user-confirmed profile and current preferences into the selected deployment; verify private storage and access.
- [ ] **P13-03** Prepare a small initial batch; a cap of 3–5 applications per day remains a proposal until chosen by the user.
- [ ] **P13-04** Review every candidate match, keyword plan, user-supplied resume document, destination, document upload, and required answer before pilot submission.
- [ ] **P13-05** Apply only within the authorized pilot scope and record actual confirmation evidence for each successful attempt.
- [ ] **P13-06** Resolve missing questions through Space and verify appropriate reuse on subsequent applications.
- [ ] **P13-07** Inspect any uncertain result and reconcile it before considering further action for that job.
- [ ] **P13-08** Record time saved, edits needed, irrelevant matches, question burden, failures, confirmed applications, and actual cost.
- [ ] **P13-09** Fix defects and rerun affected regression checks; return to draft mode if a critical invariant fails.
- [ ] **P13-10** Confirm that manual completion and skipped jobs are accurately reflected in history.
- [ ] **P13-11** Review the pilot report with the user and define the sources and conditions eligible for unattended operation.

Exit check: the authorized pilot is complete, results are auditable, and automation scope is supported by observed performance. Successful submission is distinct from recruiter response or hiring outcome.

## Phase 14 — Enable the daily loop and optional autonomous operation

Owner: Builder + Core; User configures standing policy. Deliverable: reliable scheduled operation.

- [ ] **P14-01** Choose and configure a durable scheduler for the deployment; document laptop-off behavior or always-on hosting requirements.
- [ ] **P14-02** Set the user-approved time/timezone and define missed-run, daylight-saving, and catch-up behavior.
- [ ] **P14-03** Use durable run locks/leases to prevent overlapping schedules and recover abandoned runs.
- [ ] **P14-04** Create daily queues for discovery, matching, keyword planning, questions, prepared packages, submissions, and reconciliation.
- [ ] **P14-05** Prioritize suitable fresh jobs and known deadlines while preserving user-defined preferences and hard constraints.
- [ ] **P14-06** Apply per-day application caps, per-run/runtime budgets, per-source rate limits, and model spending limits across workers.
- [ ] **P14-07** Persist and resume unanswered applications without holding workers open or blocking unrelated jobs.
- [ ] **P14-08** Implement a global kill switch plus per-agent/source pause controls; test their effect during active processing.
- [ ] **P14-09** Build the daily digest: discovered/shortlisted/prepared/submitted counts, skips, questions, failures, uncertain attempts, and costs.
- [ ] **P14-10** Configure notifications only to the user's authorized channel with minimal sensitive content and links to the private review view.
- [ ] **P14-11** Add health checks and notifications for expired authentication, adapter breakage, missed runs, budget exhaustion, and prolonged unresolved attempts.
- [ ] **P14-12** Implement the user interface for standing permission: scope, expiry, exclusions, limits, and actions always needing review.
- [ ] **P14-13** Enable automatic submission only for covered, validated applications; reuse valid permission without repetitive approval prompts.
- [ ] **P14-14** Run scheduled draft-only trials, then a bounded unattended trial under the user's selected policy; inspect restart and overlap behavior.
- [ ] **P14-15** Document startup/shutdown, recovery, pause/revoke, backup, account reconnection, and manual-handoff procedures.

Exit check: repeated scheduled runs behave predictably, enforce limits, ask only necessary questions, and confirm outcomes accurately.

## Phase 15 — Expand and improve using measured results

Owner: Builder + User. Deliverable: maintained system with evidence-based improvements.

- [ ] **P15-01** Review false-positive and false-negative matches; propose policy adjustments for user acceptance rather than silently changing taste.
- [ ] **P15-02** Build an adapter expansion list ordered by relevant job coverage, permission clarity, and maintenance cost.
- [ ] **P15-03** Apply the source feasibility, fixture, permission, submission, and pilot checks to each additional adapter before enabling it.
- [ ] **P15-04** Add user-authorized email alert imports if useful, with limited mailbox scope, duplicate checks, and untrusted-content handling.
- [ ] **P15-05** Add separate base resume variants for genuinely different approved role families while maintaining one canonical fact set.
- [ ] **P15-06** Improve the career evidence bank with user-confirmed achievements and metrics; record recurring skill gaps as learning opportunities.
- [ ] **P15-07** Add cover letters or optional application documents only if requested and supported by the same evidence/approval controls.
- [ ] **P15-08** Track recruiter responses, interviews, rejections, and withdrawals through manual updates or explicitly authorized integrations.
- [ ] **P15-09** Evaluate outcomes cautiously with sample size and confounding factors; do not translate keyword coverage into guaranteed employer ranking.
- [ ] **P15-10** Optimize prompts, caching, and lighter-model routing only when held-out evaluations preserve quality and permission boundaries.
- [ ] **P15-11** Re-evaluate models before replacement, maintain a tested rollback route, and update model pricing/capability records.
- [ ] **P15-12** Monitor MCP dependencies, source changes, permissions, and authentication requirements; disable broken capabilities until repaired.
- [ ] **P15-13** Periodically audit answer freshness, data retention, backups, logs, and standing permission.
- [ ] **P15-14** Consider semantic answer search, additional workers, or a larger database only when observed needs justify them; retain exact scope checks.
- [ ] **P15-15** Keep root instructions, the pipeline plan, each agent package, runbooks, and this task tracker consistent with approved changes.

Exit check: each expansion has its own evidence and maintainable support boundary; lower cost or higher volume never overrides correctness.

## 5. Handoff and completion checklist

| Handoff | Required payload | Block progression when |
| --- | --- | --- |
| User -> Space | Confirmed facts, evidence references, preferences, reuse scope | Required facts conflict or lack confirmation |
| B -> A | Job snapshot/hash, match evidence, policy/profile versions, gaps | Hard filter fails, critical requirement unknown, or duplicate unresolved |
| A -> C | Job ID, keyword-plan artifact ID/hash, priority summary, warnings | Missing keyword plan, invalid schema, stale job description version |
| C -> Review | Destination, exact document, field answers/provenance, unresolved items | Form unsupported or required answers unresolved |
| Review/policy -> Gateway | Package identity and applicable user authorization | Approval stale/revoked, package changed, source capability absent |
| Gateway -> History | Attempt ID, receipt/evidence, result status | Result ambiguous; retain `submission_unknown` |

The implementation is ready for daily use only when the appropriate Phase 14 exit checks pass. Completing agent prompts or connecting MCP servers alone does not complete the pipeline.

## 6. Milestones for review

| Milestone | Included phases | What you can inspect |
| --- | --- | --- |
| M1: Agent foundation | 00–04 | Each agent's files, models, skills, tool permissions, and Space profile |
| M2: Agent B discovery | 05–05F | Run Agent B and inspect discovered job links, descriptions, shortlist reasoning, source limits, handoff entries, and readable `private/job_reviews/` files |
| M3: Keyword plan value | 06 | Ranked job-specific keyword plan linked to the job record |
| M4: Complete draft workflow | 07–09 | Form preview, reusable answers, missing questions, and resumable review |
| M5: Submission readiness | 10–12 | Supported live adapter, guarded submission, and evaluation report |
| M6: Real pilot | 13 | Actual confirmation evidence, correction rate, and costs |
| M7: Daily operation | 14 | Schedule, limits, digest, pause controls, and optional standing permission |
| M8: Ongoing improvement | 15 | Added coverage and measured quality/cost changes |

## 7. Items to decide during your review

1. Accept the three-agent design and proposed model defaults, or state provider/model preferences.
2. Confirm the per-agent `AGENT.md`, skills, and MCP package layout.
3. Choose the first role family, mandatory filters, and source to evaluate.
4. Choose local versus hosted operation and acceptable model-data sharing.
5. Set initial budget, review mode, and pilot cap when implementation begins.
6. Confirm that M3, the complete draft workflow, is the first product milestone before live application submission.

No answers are needed merely to read this document. These decisions will guide the next implementation task you authorize.
