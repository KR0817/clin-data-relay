# ADR 0015: Persist only institutional session-token digests

**Status:** Accepted for implementation
**Date:** 2026-08-23

## Context

The future institutional callback must create a Companion session after MFA and
Study Membership authorization. Storing a bearer token in plaintext would let
a database read become an active-session credential leak. Reusing an IdP token
as the application session would also couple every request to provider-specific
claims and lifetimes.

## Decision

Issue a separate high-entropy Companion bearer token, return it once and persist
only its SHA-256 digest. Cap its expiry by issue time, the provider authentication
event and Study Membership expiry. Resolve every session through its still-active
membership; membership deactivation therefore invalidates sessions immediately.

## Consequences

- Database and audit access cannot directly recover a usable bearer token.
- Lost bearer tokens cannot be displayed or recovered; a new institutional
  login must create a new session.
- The Companion remains responsible for its session revocation and expiry even
  though assertion verification and MFA remain identity-provider duties.
- This does not select an OIDC/SAML provider or enable central HTTP.
