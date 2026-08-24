# ADR 0020: Contain a used bootstrap mistake by deactivating membership

**Status:** Implemented
**Date:** 2026-08-24

## Context

ADR 0019 intentionally closes bootstrap rollback after any Companion Session
history. If the first Central Data Manager was bound incorrectly and logged in,
the project still needs an immediate containment action. Deleting session rows,
reopening bootstrap or trusting identity-provider roles would erase evidence or
expand authority during an incident.

## Decision

Add one operator JSON-stdin action that can deactivate only an active
bootstrap-created Central Data Manager membership. In one PostgreSQL transaction
under the shared audit lock, verify the bootstrap grant marker, update the
membership lifecycle fields and append a dedicated emergency event with a
bounded external incident reference and reason.

Do not update, revoke or delete historical session rows. Session resolution
already requires an active membership, so all linked bearers fail immediately
after commit while the session evidence remains available. Do not create the
unused-bootstrap rollback marker and do not provide replacement authority.

## Consequences

- The mistaken principal loses Companion access without waiting for provider
  token expiry and without deleting audit evidence.
- The operator label, incident reference and confirmation are controlled
  procedural inputs, not system-authenticated dual approval.
- Emergency deactivation permanently leaves bootstrap closed. Replacement CDM
  authority requires a separately governed membership lifecycle.
- Central HTTP and Centre Lite remain unchanged. Production remains blocked on
  routine membership administration, qualified identity operation and the
  other existing readiness gates.
