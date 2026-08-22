# ADR 0011: Migrate reviewed-package import as one clinical transaction

**Status:** Accepted for implementation  
**Date:** 2026-08-22

## Context

The PostgreSQL package ledger proves infrastructure and idempotency, but moving
only its receipt into the active central path would split one clinical import
between PostgreSQL and SQLite. The centre package already contains authorised,
pseudonymous, human-reviewed values; importing it is the smallest complete
clinical write slice that includes provenance, quality and audit behavior.

## Decision

Create a reviewed-import repository whose small interface imports one validated
package command and lists the values created by that import. Both adapters own
the entire transaction: package claim, source metadata, candidate deduplication,
quality findings, chained audit events and terminal attempt log.

PostgreSQL migration 3 adds only the tables and constraints needed for this
slice. Serialize audit-tail calculation with a transaction advisory lock and
enforce active-candidate equivalence with a partial unique index. Keep encrypted
package content in approved source storage, not the database or repository
command.

## Consequences

- No clinical import can commit a receipt without its candidates, quality,
  audit and terminal log in the same database transaction.
- Existing SQLite HTTP behavior can use the same domain seam exercised by the
  PostgreSQL contract tests.
- This is not a complete central repository. General candidate workflows,
  institutional identity, TLS termination, backup qualification and Authority
  EDC controls remain separate release gates.
