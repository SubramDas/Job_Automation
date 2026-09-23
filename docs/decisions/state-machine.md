# Application State Machine

Status: Phase 01 contract.

Normal path:

`discovered -> extracted -> evaluated -> shortlisted -> tailoring -> validated -> preparing -> ready -> submitting -> submitted`

Alternate states:

- `rejected_by_preferences`
- `needs_user_input`
- `needs_review`
- `manual_handoff`
- `expired`
- `retryable_failure`
- `permanent_failure`
- `submission_unknown`
- `cancelled`

Each state transition must produce a redacted audit event with the actor, prior state, next
state, relevant input versions, idempotency key where applicable, and outcome. Later database
implementation must enforce one submission owner per application and prohibit blind retries
from `submission_unknown`.

