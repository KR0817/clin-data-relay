# ADR 0017: Exchange OIDC callbacks for sessions outside the URL

**Status:** Accepted for implementation
**Date:** 2026-08-24

## Context

After a successful OIDC callback, the application must issue its own
membership-scoped Companion Session. Putting that bearer in a redirect URL
would expose it to browser history, screenshots, proxy/access logs and copied
links. Returning JSON from the callback would leave the user outside the web
application, while persisting a plaintext bearer would turn database access
into an active credential leak.

## Decision

The callback creates a two-minute Login Exchange from a pseudonymous
VerifiedPrincipalLink and redirects with only the opaque exchange code. The
browser must POST that code with the same signed HttpOnly browser session. The
exchange is consumed once before the existing PostgreSQL session repository
issues a Companion bearer.

Persist only SHA-256 digests of the exchange code and browser binding. Persist
the provider alias, pseudonymous Principal ID, bounded username and provider
authentication time needed for subsequent membership authorization. Do not
persist the raw provider subject, any provider token, the opaque codes or the
Companion bearer.

Use Authlib for Authorization Code, PKCE, discovery/JWKS and ID-token handling.
Do not implement JWT parsing or protocol validation in application code.

## Consequences

- Callback URLs cannot be used directly as API bearer credentials.
- A leaked exchange URL is insufficient without the same signed browser
  session and becomes unusable after one successful POST or two minutes.
- If session issuance fails after consumption, the exchange stays consumed and
  the user repeats login. This fail-closed recovery is preferred to replaying a
  partially completed authentication.
- The browser-session signing secret becomes a managed production secret and
  must not be committed, logged or reused as an OIDC client secret.
- The contract does not enable the current central runtime. Keycloak
  registration, TLS, PostgreSQL composition and qualification remain required.
