# ClinData Relay Product Context

This context covers the image-assisted data-entry companion for a multicentre investigator-initiated trial. LibreClinica is the authority for clinical records; this companion only produces traceable, human-reviewed candidates from laboratory-report images.

## Language

**Authority EDC**:
The validated LibreClinica deployment that owns the official clinical record, its audit trail, signatures, queries, freezes, and locks.
_Avoid_: primary database, source of truth (when describing the companion)

**Companion**:
The separate application that stores source images, OCR output, Kimi candidates, human review decisions, and EDC transfer receipts.
_Avoid_: EDC, clinical database

**Candidate**:
A proposed field value extracted from a de-identified laboratory-report image that has no clinical-record effect until a reviewer approves it.
_Avoid_: result, confirmed value

**Review decision**:
An authorised person's accept, edit, or reject action on one candidate, with a timestamp and optional reason.
_Avoid_: auto-fill, auto-approval

**Transfer receipt**:
The immutable record showing whether a human-approved candidate was manually entered or submitted through a validated EDC adapter.
_Avoid_: sync success, import log

**Transfer package**:
The canonical, hash-addressed representation of one human-confirmed candidate that is prepared for an EDC adapter. Its preparation has no effect on the Authority EDC.
_Avoid_: auto-fill payload, direct write request

**Sandbox EDC**:
A local LibreClinica installation that contains only synthetic study records and is used to document installation and adapter fit-gap evidence.
_Avoid_: pilot database, production-like database

**Centre**:
One participating study site. Users and candidate records are scoped to exactly one centre unless a centrally authorised role is assigned.
_Avoid_: tenant, customer
