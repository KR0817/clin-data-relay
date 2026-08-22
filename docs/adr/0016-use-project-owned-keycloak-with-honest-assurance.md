# ADR 0016: Use project-owned Keycloak with honest assurance

**Status:** Accepted for implementation
**Date:** 2026-08-23

## Context

No hospital identity provider is available. The central application still
needs a standards-based authenticator for an enrolled person's account and MFA
event, but an OIDC login cannot prove hospital employment, investigator status,
protocol delegation, study role or centre assignment.

Building a local password service or parsing JWTs in application code would add
credential, key-rotation and protocol risk. Managed providers reduce operations
but require a contracting entity, approved processing terms and acceptable data
locations.

## Decision

Use a project-controlled, invitation-only Keycloak realm as the first OIDC
implementation target. Describe its assurance as project-verified investigator
identity, never hospital or institutional identity.

Use Authorization Code Flow through a maintained OIDC client. Require exact
issuer and audience validation, recent authentication and an MFA ACR configured
and enforced in Keycloak. Keycloak groups, realm roles, email domains and
profile attributes cannot supply Companion role or centre; the existing Study
Membership remains the only authorization source.

Keep provider tokens transient, client credentials outside Git and application
records, and Keycloak operationally separate with HTTPS, a production database,
backups, patching, monitoring and controlled administrator access.

## Consequences

- The project can progress without hospital SSO while preserving explicit
  centre isolation and study authorization.
- The accountable study entity must operate enrolment, offboarding, recovery,
  two-administrator coverage and the Keycloak service lifecycle.
- A successful OIDC test or MFA prompt is not production qualification.
  Central access remains blocked until callback security, membership/session
  invalidation, backup/restore, incident response and governance evidence pass.
- If the project cannot sustain Keycloak operations, a contract-approved
  managed OIDC provider is preferred over an unmaintained self-hosted service.
- Existing internal `Institutional*` names are legacy compatibility names and
  will not be used as a user-facing assurance claim.

## Evidence

The supporting comparison and official sources are recorded in
`docs/research/project-owned-identity-provider-options-2026-08.md`.
