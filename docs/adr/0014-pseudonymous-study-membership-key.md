# ADR 0014: Persist a pseudonymous study-membership key

**Status:** Accepted for implementation
**Date:** 2026-08-22

## Context

The future approved identity adapter must match a verified principal to a
Companion-controlled Study Membership. Persisting the identity provider's raw
subject would retain an external identifier that the authorization database
does not need. Using a username would be mutable and could expose direct
identity information.

## Decision

Derive a namespaced SHA-256 Principal ID from the configured
provider alias and provider-normalized opaque subject. Persist that identifier
and the non-secret provider alias in each Study Membership; keep the raw subject
only in the transient verified principal. Enforce one active membership per
pseudonymous principal and retain deactivated rows as lifecycle history.

Grant and deactivation append to the existing serialized PostgreSQL audit hash
chain in the same transaction. No HTTP membership administration surface is
introduced in this slice.

## Consequences

- The authorization database and its audit details do not contain raw provider
  subjects, usernames, assertions or tokens.
- The identifier is pseudonymous, not anonymous or encryption. A party with a
  candidate provider/subject pair can recompute it, so database and provider
  configuration access controls remain required.
- Changing the provider alias or subject requires a new membership grant after
  the old membership is deactivated.
- Central startup remains blocked until a qualified approved provider
  adapter and session composition are implemented and validated.
