# ADR 0018: Use one project-session HTTP boundary

**Status:** Accepted for implementation
**Date:** 2026-08-24

## Context

The OIDC callback and one-time exchange can issue a digest-backed Companion
Session, but downstream central routes still need a uniform authenticated-user
dependency. Browser-only token deletion also leaves the server session valid
until expiry and cannot provide immediate logout revocation.

## Decision

Add one central-only HTTP module that resolves the existing bearer through
`PostgresInstitutionalSessionRepository` and projects the result into the same
`UserContext` consumed by current route authorization. Add a logout endpoint
that resolves and revokes the current session before returning `204`.

Keep missing authorization, invalid sessions and repository availability as
three bounded outcomes. Do not add refresh tokens, bearer cookies, a parallel
session table, role claims from the identity provider or another dependency.

## Consequences

- Downstream central route modules can use the existing authorization shape
  without knowing PostgreSQL or OIDC details.
- Logout invalidates the server-side session instead of only clearing browser
  state.
- Membership deactivation remains immediately effective because every request
  still resolves through the membership join.
- The current composition does not mount this module. Central runtime remains
  blocked until membership administration, repository-backed route composition
  and operational controls are complete.
