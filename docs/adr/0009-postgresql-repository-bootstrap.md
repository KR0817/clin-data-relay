# ADR 0009: Bootstrap PostgreSQL before migrating clinical domains

**Status:** Accepted for implementation  
**Date:** 2026-08-22

## Context

The central deployment needs PostgreSQL, but the current application still has
many SQLite-specific clinical queries. Enabling central mode after only changing
a connection string would produce a partially migrated system and could split
audit or clinical state across databases. Conversely, adding an ORM or a full
parallel schema before a tested seam exists would create a second source of
truth and unnecessary migration risk.

## Decision

Introduce a small PostgreSQL repository-bootstrap module first. It owns DSN
policy, connection handling, a transaction-scoped migration lock, schema-version
ledger and redacted capability result. The first migration records only the
bootstrap ledger and contains no participant or clinical data.

Exercise the module against a real PostgreSQL 16 service in CI. Keep Psycopg in
an optional `central` dependency group so Centre Lite remains unchanged. Keep
central application startup fail-closed until subsequent vertical slices move
complete clinical domains and institutional identity behind tested interfaces.

## Consequences

- PostgreSQL connectivity and migration behavior become executable rather than
  architectural prose.
- No user workflow can accidentally write some data to SQLite and some to
  PostgreSQL.
- Later repository adapters reuse one migration ledger and connection policy.
- A successful bootstrap proves infrastructure compatibility only; it is not
  clinical validation, production qualification or central go-live evidence.
