# ADR 0007: Modular monolith with separate centre and central deployments

**Status:** Accepted for implementation  
**Date:** 2026-08-22

## Context

The same application currently supports a centre-bound Lite profile and a
localhost full sandbox. SQLite is appropriate for one workstation but cannot
become a concurrent central repository. The application composition root also
contains browser delivery, authentication and clinical orchestration in one
large module, making a PostgreSQL adapter unsafe to introduce as a flag change.

## Decision

Keep a modular monolith and two deployment shapes:

1. Centre Lite: local SQLite, local OCR/PDF parsing, optional Kimi, human review,
   Excel export and encrypted centre-package exchange.
2. Central web: independently deployed FastAPI application, qualified
   PostgreSQL repository, institutional identity, HTTPS, worker and monitored
   backup/restore. It remains disabled until those adapters and evidence exist.

Extract modules vertically behind small interfaces. The application composition
root wires them together. Do not introduce microservices, Redis, Celery, a new
frontend framework or a general static-directory mount in this phase.

## Consequences

- Centre recipients keep the Docker-free install path.
- Central concurrency cannot accidentally use SQLite.
- Authentication and persistence can gain second adapters at real seams later.
- The first refactor changes code ownership, not HTTP or clinical behavior.
- Formal source distribution still requires an owner-approved license and Git
  baseline; this ADR does not make that legal decision.
