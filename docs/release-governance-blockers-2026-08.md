# Release Governance Blockers — 2026-08-17

## Status

External source distribution remains blocked even though the review-gate and
audit-integrity code paths are implemented and tested.

## Blocking decisions

1. **Project license:** the project owner must select and approve the project
   license and copyright notice. The application must not invent this legal
   decision. A root `LICENSE` and reviewer terms must exist before source is
   sent to third parties.
2. **Version baseline:** the workspace has no Git metadata. Create a repository,
   commit the reviewed snapshot and tag the review baseline only after the
   license decision. Each later package must embed the commit identifier.
3. **Package encryption design:** passphrase packages now use scrypt
   `N=2^17,r=8,p=1`, retain read compatibility with the previous `N=2^15`
   envelope and use per-package salt/nonce. Institution public-key encryption
   and optional source signatures still require a key-lifecycle design review.
4. **Central deployment:** SQLite remains a single-workstation profile. A
   multi-writer central service requires the documented PostgreSQL and managed
   identity work; WAL is not a substitute for a network database.
5. **Protocol responsibility:** PI candidate-review permissions remain unchanged
   until the protocol and delegation log state whether the PI reviews individual
   candidates or only performs visit-level attestation.

## Stale artifacts

All `dist` artifacts built before this review-gate change are non-current and
must not be distributed as repaired builds. Rebuild only after the full test
suite, package black-box tests, secret scan and manifest verification pass from
one approved version baseline.

## Security boundary

The SHA-256 audit chain detects modification or deletion once its head is
anchored outside the workstation. It is not WORM storage and a privileged local
administrator can rewrite an unanchored chain.
