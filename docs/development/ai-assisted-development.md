# AI-assisted development disclosure

ClinData Relay is developed with AI coding agents under human direction. The
repository keeps `AGENTS.md`, `MEMORY.md`, specifications, ADRs and test
evidence visible so reviewers can inspect that process rather than infer it.

## What agents may do

- inspect the repository and propose bounded specifications;
- implement code, tests, documentation and synthetic fixtures;
- run local and CI checks and report failures;
- identify security, privacy, accessibility and maintainability risks; and
- prepare release artifacts after explicit owner authorization.

## Human-controlled decisions

Agents do not establish clinical truth or institutional authorization. A human
owner remains responsible for:

- research purpose, protocol, ethics, privacy and data-flow approvals;
- the field dictionary, clinical interpretation and benchmark gold standard;
- acceptance of model/OCR candidates and conflict resolution;
- identity, role, centre and production-deployment governance;
- licensing, authorship, citation, release and publication decisions; and
- deciding whether evidence is sufficient to change a safety boundary.

## Controls applied to generated changes

Complex work starts with a PRD, technical specification or ADR. Security and
clinical paths preserve fail-closed defaults, bounded inputs, centre isolation,
append-only provenance and human review. Changes are reviewed against the Git
diff and verified with focused tests, the full suite, compilation/static checks
and synthetic browser or packaged-runtime checks when applicable.

Provider output, agent commentary and passing tests are evidence inputs, not
proof of clinical validity. Real participant data, credentials, private keys
and unchanged source reports are excluded from external-model prompts and the
public repository.

## Known limitation

AI assistance can introduce plausible but incorrect code, tests that mirror an
implementation bug, incomplete edge cases and overstated documentation. The
project therefore keeps production readiness blocked until independent
validation and institutional controls exist. Public review is invited through
issues and pull requests; security findings follow `SECURITY.md`.
