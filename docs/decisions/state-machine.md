# Job Workflow State Contract

Status: Phase 01 contract, scoped to discovery and keyword planning.

Normal progression:

`discovered -> extracted -> evaluated -> shortlisted -> keyword_planning -> complete`

Alternate outcomes include `rejected_by_preferences`, `needs_review`, `manual_handoff`,
`expired`, `retryable_failure`, `permanent_failure`, and `cancelled`.

Each transition records a redacted audit event with actor, prior and next state, relevant input
versions, idempotency key where applicable, and outcome. External employer application actions
are outside this workflow.
