# ADR-0002: Model API and MCP Boundary

Status: accepted for Phase 01 contracts; implementation deferred.

Date: 2026-09-23.

## Decision

Keep model provider use disabled for Phase 01 except for synthetic future tests. The example
model assignments from the backlog are recorded in `config/models.example.json`, but the
provider status remains `deferred_for_privacy_review`.

For MCP, distinguish three cases in later implementation:

- Local in-process or stdio tools used by the local application.
- Local/private MCP exposed through a secure tunnel or environment-bound connection.
- Remote MCP reachable by the model provider.

The application server, not prompts, will enforce tool allowlists, identity, resource scope,
submission mode, and approval state.

## Source Review

OpenAI's current MCP documentation, checked 2026-09-23, distinguishes remote MCP servers from
local/private servers and describes approval behavior and transport choices. The Phase 01
contracts therefore avoid assuming that a local tool is automatically reachable from a hosted
model.

## Consequences

- Agent prompt files in Phase 02 will describe allowed tools, but server-side validation must
  remain authoritative.
- Personal resume/profile data cannot be sent to a model until provider handling, retention,
  and data-sharing constraints are explicitly approved.
- Connector availability does not imply source permission or submission permission.

