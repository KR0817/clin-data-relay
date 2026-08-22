# ADR 0010: Make package idempotency a repository-owned atomic claim

**Status:** Accepted for implementation  
**Date:** 2026-08-22

## Context

The encrypted centre-package route previously checked for a duplicate in one
SQLite transaction and inserted the receipt in a later transaction. The unique
constraints prevented silent duplicate receipts, but two concurrent requests
could both pass the first check and expose an unhandled integrity error during
the final write. Import logs were also embedded as route-level SQL, making the
first PostgreSQL slice difficult to verify without copying behavior.

Moving candidate clinical values to PostgreSQL in the same change would be too
broad. Running a PostgreSQL receipt ledger alongside SQLite candidate writes
would be worse because no database could guarantee the cross-store commit.

## Decision

Define one narrow import-ledger contract for immutable package receipts and
append-only attempt logs. Keep the active HTTP workflow on SQLite, but perform
the final package claim inside the existing candidate transaction. Treat a
failed atomic claim as a duplicate, roll back all writes for that package, and
write the duplicate attempt afterward.

Add the equivalent PostgreSQL adapter and schema as migration 2. Exercise it
against PostgreSQL 16 in CI, but do not route central HTTP traffic to it yet.
The ledger deliberately excludes clinical values, encrypted package content,
passphrases, images and direct identifiers.

## Consequences

- Package idempotency is enforced at the actual write boundary, including the
  race between pre-check and insert.
- SQLite HTTP responses and centre Lite dependencies remain unchanged.
- PostgreSQL receives a real operational, non-clinical slice without creating
  split clinical state or weakening the central fail-closed gate.
- Candidate persistence must later move as a complete vertical slice before
  this PostgreSQL ledger is selected by the central application.
