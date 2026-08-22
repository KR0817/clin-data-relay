# ADR 0013: Keep study authorization outside identity-provider claims

**Status:** Accepted for implementation
**Date:** 2026-08-22

## Context

Hospital identity providers can prove a person's institutional identity and MFA
event, but their group names and lifecycle do not inherently express this
study's approved roles or centre boundaries. Directly trusting a browser header
or provider group would couple clinical authorization to external naming and
could broaden access when provider administration changes.

## Decision

A future qualified OIDC/SAML adapter will produce a verified Institutional
Principal. The Companion will separately match its provider/subject pair to one
application-controlled Study Membership. Only that membership supplies the
study role and centre. Provider group/role claims cannot directly authorize a
Companion session.

## Consequences

- Institution identity lifecycle and MFA remain provider responsibilities.
- Study assignment, least privilege and centre isolation remain explicit
  Companion responsibilities with their own audit/approval lifecycle.
- Provider selection can change without redefining clinical roles.
- Central HTTP remains unavailable until both assertion verification and the
  membership repository are implemented and qualified.
