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

**Project Identity Provider**:
An OIDC provider approved and operated by the accountable study entity when no hospital identity provider is available. It proves control of an enrolled project account and an MFA event; it does not prove hospital employment, professional status, study delegation, role, or centre assignment.
_Avoid_: hospital SSO, institutional identity, investigator registry

**Verified Principal**:
A person whose project account and MFA event have already been verified by an approved identity-provider adapter. Existing internal `Institutional*` type and table names are legacy implementation names and do not assert hospital affiliation.
_Avoid_: local account, request-header user, study role, hospital-verified user

**Study Membership**:
The Companion-controlled authorization that assigns one Verified Principal to one active study role and, for a site investigator, one Centre.
_Avoid_: identity-provider group, login claim, account

**Principal ID**:
A pseudonymous Companion identifier derived from the configured provider alias and the provider-normalized opaque subject. It links a verified principal to a Study Membership without persisting the raw provider subject.
_Avoid_: username, employee number, reversible identifier

**Companion Session**:
A short-lived Companion session issued only after a Verified Principal and an effective Study Membership have both been verified.
_Avoid_: identity-provider token, permanent login, local account

**Login Exchange**:
A short-lived, browser-bound, one-use code that carries no session credential and can be exchanged once for a Companion Session after an OIDC callback. Only its digest is persisted.
_Avoid_: access token, refresh token, login URL token, reusable code

**Central Membership Bootstrap**:
A pre-login action run by an OS/database operator under an externally witnessed procedure to grant the first Central Data Manager Study Membership from the exact qualified-client OIDC subject. The command does not authenticate the operator or validate the external subject mapping; it only avoids persisting or returning the supplied subject.
_Avoid_: local admin password, email lookup, Keycloak group mapping, ordinary account creation
