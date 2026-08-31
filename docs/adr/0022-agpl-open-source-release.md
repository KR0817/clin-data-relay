# ADR 0022: AGPL open-source release

**Status:** Accepted
**Date:** 2026-08-31

## Context

The public source-available showcase is useful for review but creates avoidable
friction for research reuse, portfolio evaluation and an eventual research
software publication. The project owner selected `AGPL-3.0-only` before any
external contribution was accepted.

Clinical and production safety cannot be implemented as extra field-of-use
restrictions on an OSI-approved license. Those boundaries already exist in the
application, release gates and governance documentation.

## Decision

Release all first-party repository content under the unmodified GNU Affero
General Public License version 3 unless a file states a compatible independent
license. Use the exact SPDX identifier `AGPL-3.0-only` in package and citation
metadata.

Distributed binaries include the AGPL text and a route to the corresponding
tagged source. Public network deployments must preserve the source offer
required by AGPL section 13. Third-party components remain governed by their
own notices and licenses.

Keep the synthetic-data, human-review, privacy, Authority EDC and production
BLOCK statements as product and governance boundaries. Do not represent them
as additional license restrictions.

## Consequences

- The repository can accurately describe itself as OSI-approved open source.
- Commercial use is not prohibited; covered distribution and network-service
  modifications must comply with AGPL obligations.
- JOSS license eligibility is possible, but public development duration,
  research use and community evidence remain separate future requirements.
- Future dual or proprietary licensing of external contributions would require
  rights not granted by an ordinary inbound AGPL contribution. No such model is
  introduced in this release.
- ADR 0021's public-review decision remains historical; its custom-license
  decision is superseded. Its secret, participant-data and synthetic-showcase
  controls remain in force.
