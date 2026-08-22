# Authority EDC adapter contract (Phase 1.2)

The companion creates a `clinical-edc-companion-transfer-v1` package only after a candidate is `human_confirmed`. The package is canonicalized, SHA-256 hashed and frozen with its source hash, subject/event/field references, final value, unit and reviewer identity/time. Package retrieval never rebuilds it from later candidate state.

`POST /api/candidates/{candidate_id}/transfers` creates a `queued` request. The configured adapter determines `mode` and `target`: the default is `simulation/not_configured`; the qualified localhost sandbox is `libreclinica_soap/libreclinica`. The deterministic default idempotency key is candidate ID plus package hash plus target. Exact replay returns the original row; conflicting reuse is rejected. Including the target lets a reviewed candidate receive a new live request after an earlier simulation without mutating or reusing the simulation record.

The separately hashed `clinical-edc-companion-receipt-v1` freezes the original request, not the delivery outcome. It must never be interpreted as proof of Authority-EDC entry. Delivery state lives only in the mutable reconciliation ledger.

For a queued row, `POST /api/transfers/{id}/submit`:

1. verifies the stored JSON against its recorded SHA-256;
2. atomically moves the row to `submitting` and increments `attempt_count`;
3. invokes the configured adapter outside the SQLite transaction;
4. writes either `submitted` with an Authority-EDC reference, response SHA-256 and submission time, or `failed` with a sanitized structured error;
5. appends a companion audit event without rewriting the package or original receipt.

The stored request `mode` and `target` must match the currently configured adapter before step 1 can proceed. A historical simulation request therefore remains permanently non-submittable after LibreClinica is enabled; it cannot be converted into a live write by configuration drift.

The LibreClinica adapter performs a read-only authenticated SOAP probe for readiness. On submit it resolves the existing study-subject OID from the pseudonymous label, maps event/field codes through `config/libreclinica-sandbox-odm-map.json`, and sends one ODM clinical-data import. The normal path never enrolls a subject, schedules a visit or directly writes a LibreClinica table. Missing subjects, unmapped events/fields, remote HTTP targets, invalid credentials, SOAP faults and non-success responses all fail closed.

LibreClinica 1.4 returns single-part MTOM responses and reports successful imports as `Success. n of n forms imported.` Both forms are covered by adapter tests. A successful response is stored only as a SHA-256 plus a bounded Authority reference; raw SOAP and credentials are not stored in the companion database.

`POST /api/transfers/{id}/retry` accepts only `failed` and moves it to `queued`. `POST /api/transfers/{id}/reconcile` accepts only `failed`, requires investigator or central-data-manager authority, and records a bounded human note. A timeout or ambiguous client result must be read back from the Authority EDC before any retry to prevent duplicate updates.

The localhost credentials file is `.runtime/libreclinica-soap-credentials.json`, ignored by version control. The browser never receives it. Production use remains blocked pending institutional deployment approval, a managed secret store, TLS and certificate validation, approved study/site/OID mapping, validated CRFs, backup/restore evidence, SOPs, training and formal interface qualification.
