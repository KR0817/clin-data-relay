# LibreClinica is the authority EDC; the custom application is an AI companion

**Status: accepted.** The IIT has no existing EDC, but it requires mature trial workflows such as site roles, queries, source-data verification, signatures, audit, freezing, and locking. LibreClinica 1.4 will own those formal records. The custom application will contain only image/OCR/Kimi candidates, human review decisions, and transfer receipts; it will never write LibreClinica tables directly. A validated ODM or Web Service adapter may be enabled only after separate verification.

## Considered options

- Build the whole EDC from scratch: rejected for the initial release because the clinical workflow and validation surface are much larger than the OCR/Kimi feature.
- Use clinicedc as the initial EDC: retained only as a fallback if LibreClinica fit-gap testing fails and the institution accepts the GPL-3.0 and long-term Django ownership costs.
