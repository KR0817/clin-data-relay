# Run a synthetic LibreClinica sandbox and keep the adapter fail-closed

**Status: accepted.** LibreClinica deployment evidence will be gathered only in a local sandbox containing synthetic data. The companion will create hash-addressed transfer packages and record simulated receipts, but it cannot call an Authority EDC or its database. This preserves the Authority EDC boundary while the legacy SOAP interface, the study ODM mapping, authentication, validation protocol, and hosting controls are separately qualified.
