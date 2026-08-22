# LibreClinica synthetic-sandbox fit-gap (Phase 1.2)

**Scope:** only the localhost Docker sandbox and generated test material. This is not a production qualification, computer-system validation package, or authorisation to process participant data.

## Verified on 2026-08-09

| Area | Result | Evidence / limit |
| --- | --- | --- |
| Release provenance | PASS_WITH_WARNINGS | The official web WAR SHA-256 is `25378635ab396195d2bc8d58ee2988383fccf0699d2c5222800c8a37524179c7`; the official SOAP/ODM WAR SHA-256 is `1f57e077d30f39b2f6c7b584ddd405420b3a990d33773fdb122019c0a8083487`. The deployed footer reports internal metadata `1.4.0rc1`, which remains a production-qualification blocker. |
| Network exposure | PASS | Web/SOAP is bound to `127.0.0.1:8081`; PostgreSQL has no host port; the test mail catcher is local at `127.0.0.1:1081`. |
| Runtime startup | PASS | The validator confirmed HTTP 200 from the root, the protected-login redirect, and HTTP 200 from `/LibreClinica-ws/ws/dataWsdl.wsdl` with `importRequest`. |
| Generated study/CRF | PASS_WITH_WARNINGS | `Synthetic OCR Laboratory Workflow` (`SYNTHETIC-OCR-LAB-2026-08`) is `Available` only for this sandbox. `SYNTHETIC_LAB_CANDIDATE_MINIMAL` v0.1 contains only generated `SYN_ALT` and `SYN_AST` fields in one non-repeating event. |
| SOAP account | PASS_WITH_WARNINGS | Dedicated local `companion_soap` was created through LibreClinica user management, assigned to the study and authorised for SOAP. Its generated SHA-1 SOAP credential is stored only in the ignored `.runtime` directory. This is not an acceptable production secret store. |
| Authenticated readiness | PASS | The adapter's read-only `listAllByStudy` probe succeeds. The public endpoint reports `ready`, `human_triggered`, study identity and mapping version without exposing credentials. |
| OID mapping | PASS_WITH_WARNINGS | Study, event, form, item-group and ALT/AST item OIDs are frozen in `config/libreclinica-sandbox-odm-map.json`. The mapping covers only the two generated test items and must not be generalized to the full workbook. |
| Companion boundary | PASS | Default mode remains disabled. Live mode rechecks frozen-package SHA-256, requires an explicit second submit action, resolves an existing subject through SOAP and imports only approved OIDs. It never writes LibreClinica tables directly and never enrolls/schedules as part of a value submission. |
| End-to-end synthetic import | PASS_WITH_WARNINGS | `SUBJ001 / WEEK_0` was explicitly prepared through SOAP. Frozen companion packages imported `AST=23` and `ALT=31`; independent read-only verification showed the expected event/form/item OIDs and `companion_soap` owner. The first AST client response was initially misclassified because LibreClinica returns `Success. n of n forms imported.`; that ledger row was reconciled after read-back, the parser was fixed, and ALT then completed as `submitted`. |
| Audit evidence | PASS_WITH_WARNINGS | The companion stores package/receipt hashes, attempts, user/time, errors, reconciliation, Authority reference and response hash. LibreClinica recorded item-data audit rows owned by the SOAP account. Full regulated audit-retention qualification is not run. |

## Not run / still blocked

- Real centres, real users, participant identities, production Kimi, or any clinical data.
- Institution-approved CRF/ODM specification beyond the two generated fields.
- Managed secret storage, TLS/certificate qualification, firewall/SSO/MFA policy, disaster recovery and backup/restore evidence.
- Queries, SDV, electronic signatures, locks, audit retention, time synchronisation, change control, SOPs and training for a hospital deployment.
- Performance, concurrency, ambiguous-timeout reconciliation and full negative-interface qualification against the intended production LibreClinica environment.
- Formal reconciliation of the vendor's `1.4.0` download name with its embedded/runtime `1.4.0rc1` metadata.

## Next controlled phase

1. Obtain institution, ethics/privacy and data-management approval for the exact deployment and data flow.
2. Replace the local credential file with a managed secret store and qualify HTTPS/certificates.
3. Build and approve the full CRF/ODM mapping from the investigator data dictionary; keep unsupported fields blocked.
4. Execute a signed interface-qualification protocol covering positive, negative, retry, timeout, duplicate, update, lock and audit-readback cases before any production release.
