# Audit Events and Error Codes

Status: Phase 01 contract.

Audit events must be useful without exposing private field values. Store IDs, versions,
hashes, redacted diagnostic messages, and timing/cost metrics. Do not log resume text,
contact details, salary values, answers, screenshots, credentials, cookies, or raw form
fields.

Initial typed error codes:

- `missing_fact`
- `stale_fact`
- `conflicting_fact`
- `unsupported_source`
- `authorization_required`
- `authorization_failed`
- `rate_limited`
- `duplicate_risk`
- `schema_invalid`
- `config_invalid`
- `private_data_blocked`

Errors should say whether retry is safe. Do not hide source or extraction uncertainty behind
a generic success result.
