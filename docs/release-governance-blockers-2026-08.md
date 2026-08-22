# Release Governance Blockers — 2026-08-17

## Status

The private source-governance baseline is established. External source access
or distribution remains prohibited unless the owner grants separate written
authorization under the proprietary root `LICENSE`.

## Resolved governance decisions

1. **Project license:** the owner selected a proprietary license and approved
   the `Copyright (c) 2026 Xinbo Yu` notice. The root `LICENSE` permits only
   separately authorized internal evaluation, review, approved research and
   protocol-bound operation; it is not an open-source license.
2. **Version baseline:** the canonical private Git repository is established on
   `main`, with the initial annotated `v0.2.0.dev0` baseline tag. Each later
   package must continue to embed the commit identifier.

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
