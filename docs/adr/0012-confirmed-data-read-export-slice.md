# ADR 0012: Add an explicit confirmed-data read boundary

**Status:** Accepted for implementation
**Date:** 2026-08-22

## Context

Reviewed centre packages can now be imported atomically into SQLite or
PostgreSQL, but the reviewed-recognition workbook still reads SQLite directly.
Enabling central HTTP at this point would either duplicate that SQL or expose an
incomplete repository without institutional identity and transfer persistence.

## Decision

Add a small database-neutral confirmed-data read contract with explicit centre,
subject and visit scope. Implement SQLite and PostgreSQL adapters, then route the
existing SQLite reviewed-recognition export through the contract. Keep workbook
grouping and dictionary display concerns outside the repository.

PostgreSQL imported values are not Authority EDC records. Until the transfer and
read-back domain is migrated, the PostgreSQL adapter always returns
`authority_submitted=false`. Add only the partial index needed by this query and
keep central runtime readiness false.

## Consequences

- Centre isolation becomes an explicit input to the persistence boundary.
- The same clinical read semantics can be exercised against both databases.
- Existing local HTTP and Excel behavior stays compatible.
- Submitted-only export, general candidate workflows, institutional identity
  and operational qualification remain later release gates.
