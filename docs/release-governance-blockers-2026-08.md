# Release Governance Blockers — 2026-08-17

## Status

The original private source-governance baseline is superseded for source-code
distribution by ADR 0022 and `AGPL-3.0-only`. The clinical, operational and
real-data blockers below remain active and are not changed by open sourcing.

## Resolved governance decisions

1. **Project license:** the owner selected `AGPL-3.0-only` on 2026-08-31 before
   accepting external contributions. The earlier proprietary and custom
   source-available decisions are retained only as Git/ADR history.
2. **Version baseline:** the canonical public Git repository is established on
   `main`; the first formal open-source release is `v0.2.0`. Each later package
   must continue to identify its corresponding tagged source.

## Remaining blockers

1. **Package encryption design:** passphrase packages now use scrypt
   `N=2^17,r=8,p=1`, retain read compatibility with the previous `N=2^15`
   envelope and use per-package salt/nonce. Institution public-key encryption
   and optional source signatures still require a key-lifecycle design review.
2. **Central deployment:** SQLite remains a single-workstation profile. A
   multi-writer central service requires the documented PostgreSQL and managed
   identity work; WAL is not a substitute for a network database.
3. **Protocol responsibility:** PI candidate-review permissions remain unchanged
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
