# ADR 0008: Canonical source root and private Git baseline

**Status:** Accepted for implementation  
**Date:** 2026-08-22

## Context

The project has a validated source tree but no Git history. The existing
workspace also contains local databases, credentials, generated packages,
third-party binaries and test outputs that must not become source history.

## Decision

Create a clean canonical checkout at `C:\ClinData Relay`, initialize branch
`main`, commit the verified source baseline and annotate it as
`v0.2.0.dev0`. Host it in a private GitHub repository by default.

The migration copies source material rather than moving or deleting the old
workspace. Runtime state, secrets, databases, backups, build output, virtual
environments, scratch work and redistributable third-party binaries are
excluded. The old workspace remains the rollback copy until the new checkout
has passed dependency installation, the full test suite and repository
inventory checks.

## Consequences

- Future changes gain reviewable provenance and recoverable version tags.
- A private remote does not resolve licensing. Public source release remains
  blocked until the owner selects a root license and completes release review.
- Existing local Kimi and LibreClinica credentials are intentionally not moved;
  the new checkout must receive runtime configuration through approved local
  setup flows.
