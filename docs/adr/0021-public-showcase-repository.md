# ADR 0021: Public source-available showcase repository

**Status:** Accepted for implementation
**Date:** 2026-08-31

## Context

The repository now has a real feature-by-feature Git history, a tested
synthetic sandbox and a documented Authority EDC boundary. External reviewers
need a stable way to inspect the work, but the project is not an open-source
clinical product and is not qualified for real participant data or production
deployment.

ADR 0008 selected a private remote while licensing and release review were
unresolved. Those two prerequisites can now be addressed without changing the
clinical or security architecture.

## Decision

Publish the existing repository history as a source-available evaluation
showcase after a release check, full test run, visual inspection and passing
remote CI. Use an evaluation license that permits public inspection,
noncommercial review and GitHub forks while reserving production, clinical and
commercial rights.

Show only synthetic localhost screenshots and a rendered explanatory demo.
Keep runtime state, credentials, participant data, databases, source reports,
private endpoints and deployment evidence outside Git. Retain the explicit
research-prototype, human-review and Authority EDC boundaries in the public
landing page.

## Consequences

- Public visibility improves technical review and portfolio value without
  representing the software as OSI open source or production ready.
- Existing commit provenance is retained; no artificial showcase history is
  created.
- GitHub forks are permitted for evaluation under the same notice, but public
  visibility does not authorize clinical, commercial or hosted-service use.
- Future open-source relicensing or production authorization remains a separate
  owner decision and requires another legal, security and release review.

This ADR supersedes ADR 0008 only where that ADR required a private GitHub
remote by default. Its source hygiene and runtime-secret exclusions remain in
force.
