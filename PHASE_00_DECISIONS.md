# Phase 00 onboarding specification and decision record

Status: complete for the local, synthetic-data draft scope.

This document records non-sensitive product decisions for Phase 00. Candidate documents,
contact details, compensation values, eligibility details, and application history must not
be stored here. Until private storage exists, this file records only whether those inputs are
available and how they will be handled.

Source documents:

- [Project instructions](./AGENTS.md)
- [Pipeline plan](./JOB_APPLICATION_PIPELINE_PLAN.md)
- [Implementation task list](./IMPLEMENTATION_TASK_LIST.md)

## Agreed safety baseline

The following requirements come from the source documents and remain in force unless the
user explicitly narrows the product further:

- Resume claims must be supported by user-approved evidence.
- Unknown facts remain unknown and cannot be filled from model confidence.
- Hard constraints are enforced separately from weighted preferences.
- The first usable milestone is a complete draft workflow with manual job import.
- Live account connections, recurring schedules, employer contact, and job submissions are
  outside Phase 00 and are not authorized by this record.
- Initial operation is draft/review mode. Unattended submission remains disabled until a
  later successful controlled pilot and a separately approved standing policy.
- Restricted sources use manual import or handoff unless current official permissions and
  adapter capabilities support the proposed operation.
- Candidate data, credentials, browser sessions, and application artifacts remain outside
  version control.

## Phase 00 decisions

| ID | Decision | Status | Recorded outcome |
| --- | --- | --- | --- |
| P00-01 | Accept scope and record requested design changes | Complete | Approved as proposed on 2026-09-23; no requested changes |
| P00-02 | Initial role family, seniority, and employment type | Complete | Broad technology scope, initially including all tech-related role families; 1–3 years; full-time permanent roles |
| P00-03 | Hard filters and flexible preferences | Complete | Criteria are flexible except onsite/hybrid roles must be in Bengaluru or Hyderabad; remote roles may be elsewhere |
| P00-04 | Exclusions and reapplication policy | Complete | No current company, agency, role, industry, or arrangement exclusions; every possible reapplication requires manual user review |
| P00-05 | Compensation meaning and disclosure policy | Complete | Compare annual total compensation; a posted range's minimum must exceed current CTC; no stated compensation means no compensation filter; current CTC may be disclosed when required |
| P00-06 | Candidate inputs to collect in private storage | Complete for Phase 00 | LaTeX resume plus supporting links/evidence/history are available and will be inventoried in private storage later |
| P00-07 | Eligibility, notice, and availability renewal rules | Complete | User maintains confirmed facts in the database; no periodic reconfirmation; conflicts and employer-specific declarations still require review |
| P00-08 | Initial source candidates and manual-import fallback | Complete | Manual description/URL import is the universal MVP source; LinkedIn, Naukri, employer sites, ATS postings, and other job sites are candidates, with automated capabilities unverified |
| P00-09 | Local/hosted operation, review interface, notifications, timezone | Complete for MVP | Local laptop, CLI, Asia/Kolkata; no external notification channel selected yet |
| P00-10 | Cost/runtime budgets, processing caps, submission caps, schedule | Complete for MVP | User starts each run manually; no initial automatic schedule, cost/runtime budget, or processing/preparation/submission caps; these are required before unattended or live operation |
| P00-11 | Draft mode and future standing-permission fields | Complete | User reviews every job, resume, answer set, gap, and destination; live and unattended submission disabled initially; standing permission is a later decision |
| P00-12 | Provider data-sharing and retention constraints | Complete for synthetic scope | Provider review deferred; only synthetic data may be processed until provider, sharing, and retention constraints are explicitly approved |
| P00-13 | Evaluation goals and release thresholds | Complete | User approved the initial quality goals listed below |
| P00-14 | Labeling process for 20–30 initial jobs | Complete | User will label each job yes/maybe/no with a reason; preserve a held-out subset for evaluation |

## Approved architecture

- One local-first modular application for the MVP, with three logical runtime roles inside a
  single process where practical.
- Agent A handles evidence-backed resume tailoring; Agent B handles job import, extraction,
  and matching; Agent C handles draft form preparation and later guarded submission.
- Deterministic services own schemas, state transitions, filtering, authorization,
  deduplication, validation, budgets, and audit history.
- The proposed per-agent `AGENT.md`, three focused skills, `agent.yaml`, and scoped `mcp.json`
  layout from the implementation task list.
- The proposed model routing is subject to current availability, pricing, privacy terms, and
  evaluation during implementation. No model choice is accepted merely by accepting the
  overall product design.
- Milestone M3, the end-to-end draft workflow, precedes any live submission capability.

The user approved this scope and architecture on 2026-09-23. The MVP will run locally on the
user's laptop and expose a command-line interface. Provider selection and personal-data
handling remain pending and do not inherit approval from the architecture decision.

## Initial operating mode

- Deployment: the user's local laptop.
- Interface: command line.
- Timezone: `Asia/Kolkata`.
- Execution: user-initiated runs only; no initial automatic schedule or missed-run policy.
- Notifications: CLI output only for the MVP; external notifications are a later decision.
- Limits: model-cost budget, runtime budget, candidates processed, packages prepared, and
  future submissions remain unconfigured. They must be decided before any unattended or
  live operation; candidates processed and applications submitted must remain separate
  counters.

## Initial search scope

- Role families: all technology-related families for the initial discovery and labeling
  period. This includes software, AI/ML, data, QA, DevOps/cloud, cybersecurity, technical
  support, IT infrastructure, and other genuinely technical roles.
- Initial named titles: Software Engineer and AI/ML Engineer. Related technology titles are
  also in scope; the user intends to narrow the set using observed matches later.
- Seniority: roles seeking 1–3 years of experience.
- Employment type: full-time permanent.
- Locations: Bengaluru and Hyderabad.
- Accepted work modes: onsite, hybrid, and remote.
- Location rule: onsite and hybrid roles must be in Bengaluru or Hyderabad; remote roles may
  be based elsewhere. Other search criteria are preferences rather than hard exclusions.
- Excluded companies: none at present.
- Other exclusions: no excluded roles, industries, staffing agencies, or contract
  arrangements at present.
- Reapplications: ask the user for every case; do not infer an interval or automatic rule.
- Manual import: support pasted job descriptions with their source URL from any job site.
- Source candidates: LinkedIn, Naukri, employer career pages, ATS-hosted postings, and other
  job sites. Automated discovery, retrieval, form filling, and submission remain separate,
  unverified capabilities for each source.
- Compensation rule: compare annual total compensation in compatible currency and period.
  When a job description gives a range, its minimum must exceed the user's current annual
  total CTC. A description with no compensation is not rejected on compensation grounds.
- Compensation disclosure: the system may disclose the latest user-confirmed current CTC
  when an application requires it. The value and currency will be stored privately later.
- Foreign-currency compensation: normalize the stated range to annual total compensation
  using a recorded exchange rate and rate timestamp, then require user review of the
  conversion before applying the minimum-above-current-CTC rule.

The broad role scope is intentional for initial calibration. Matching and labeling results
must preserve the role family so later narrowing can be based on explicit user feedback.

## Candidate-input readiness and freshness

- A LaTeX resume source is available. Its contents will be supplied later, after provider and
  personal-data handling are approved.
- Supporting links, certificates, project/work evidence, achievement information, work
  samples, and prior-application records are available. Their exact inventory and contents
  will be collected in private storage later.
- The user will inspect and correct changeable facts in the local database. Confirmed notice,
  availability, compensation, work-authorization, and sponsorship records do not expire on a
  timer in the MVP.
- Each fact still needs provenance, confirmation status, and an update timestamp. Conflicting
  records, unknown facts, consent, attestations, and employer-specific declarations cannot be
  silently resolved from a non-expiring general fact.

## Review and calibration policy

- Every initial application package requires user review of the job, match explanation,
  tailored resume, answer set, gaps/warnings, and application destination.
- Initial live and unattended submission are disabled.
- The user will label approximately 20–30 jobs as `yes`, `maybe`, or `no` and give a short
  reason. The implementation must keep part of this set out of prompt/rule tuning and use it
  as held-out evaluation data.
- Later standing permission remains possible but must be a separate, versioned decision with
  source, role, employer, resume-edit, answer-reuse, limit, expiry, and always-review scope.

## Approved initial quality goals

- Zero fabricated resume claims.
- Zero known hard-filter escapes.
- Zero duplicate submissions.
- 100% field correctness on supported synthetic application forms.
- At least 95% accuracy for critical job-extraction fields on the held-out labeled sample.
- At least 80% of shortlisted jobs receive a user label of `yes` or `maybe`.
- Every unknown or ambiguous critical field is surfaced for review.
- Track manual corrections and model cost per prepared application. No cost ceiling is set
  for the manually initiated MVP yet.

## Phase 00 exit check

Phase 00 is complete when the user has approved enough non-sensitive decisions to implement
the draft workflow and all missing candidate facts are recorded as pending private inputs.
Completion of Phase 00 does not authorize account connection, live submission, or scheduling.

This exit check was met on 2026-09-23 for a local CLI implementation using synthetic data.
Real candidate-data processing remains blocked on the provider/privacy decision. Live source
connections, scheduling, form submission, and employer contact remain unauthorized.
