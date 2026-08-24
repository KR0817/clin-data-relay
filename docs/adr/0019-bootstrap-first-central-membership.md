# ADR 0019: Bootstrap only the first central membership out of band

**Status:** Implemented; post-login containment extended by ADR 0020
**Date:** 2026-08-24

## Context

The central membership administration API must require a Central Data Manager
session, but no such session can exist until an active Central Data Manager
Study Membership exists. Reusing the local SQLite password account would create
a second identity system and trusting an OIDC username, email, group or role
would collapse identity and study authorization.

## Decision

Provide one OS/database-operator JSON-stdin command for the first Central Data
Manager membership. Under an externally witnessed procedure, it accepts the
exact OIDC subject observed under the qualified project client, derives the
pseudonymous Principal ID in memory and passes only that identifier into the
PostgreSQL repository. The command does not authenticate the caller-supplied
operator label, prove a witness or verify the external subject mapping.

The repository serializes bootstrap with the existing audit advisory lock. It
fixes the role and centre, writes the membership and bootstrap-marked grant
event atomically, and rejects bootstrap after any Companion Session history.
The command never copies the supplied subject, a local password, a provider
token or a provider authorization claim into persistence or audit details;
controlled operator labels and reasons must not contain identity material.

Permit one narrow correction path only before first successful Companion
Session issuance. It may roll back a bootstrap-marked membership with a reason
and audit event; it cannot touch normal memberships, and the entire correction
path is unavailable after any Companion Session history. Only that dedicated
rollback event reopens bootstrap; generic membership deactivation does not.

## Consequences

- The first administrator cycle is broken without a second account system or a
  new table.
- Operators handle an investigator identity value briefly, so the action must
  be witnessed through an external approved record and use a protected stdin
  workflow that avoids a persistent temporary file where possible.
- An IdP administration user ID is not assumed to equal the client-specific
  OIDC subject. Their equality or mapping must be demonstrated with synthetic
  qualification evidence before bootstrap. The evidence must bind provider
  alias, issuer, client ID and subject-mapper mode; changing one requires a new
  alias and membership qualification.
- Routine membership administration remains a later CDM-authenticated API.
  Central-role lifecycle remains an operator-governed action until a real
  dual-approval design exists.
- A mistaken binding discovered after any Companion Session cannot use the
  unused-bootstrap rollback. ADR 0020 adds audited emergency deactivation for
  containment only; it does not reopen bootstrap or provision replacement
  authority.
- An invitation-token flow is deferred. It would reduce operator subject
  handling but would add a transferable authorization secret, new schema and
  issuance/revocation/claim lifecycle before there is an active administrator.
