# LibreClinica sandbox release lock

- Official release URL: https://www.libreclinica.org/downloads/LibreClinica-web-1.4.0.war
- Release artifact: `LibreClinica-web-1.4.0.war`
- Pinned SHA-256: `25378635ab396195d2bc8d58ee2988383fccf0699d2c5222800c8a37524179c7`
- Official SOAP/ODM release URL: https://www.libreclinica.org/downloads/LibreClinica-ws-1.4.0.war
- SOAP/ODM release artifact: `LibreClinica-ws-1.4.0rc1.war` (the official download is named `1.4.0`; its embedded/release runtime is `1.4.0rc1`)
- SOAP/ODM pinned SHA-256: `1f57e077d30f39b2f6c7b584ddd405420b3a990d33773fdb122019c0a8083487`
- Official release version: LibreClinica 1.4.0
- Runtime metadata warning: the deployed login-page footer currently reports `1.4.0rc1`. The artifact filename and SHA-256 match the official 1.4.0 download, but the discrepancy remains a qualification blocker until reconciled with the vendor's release information.
- Published: 2025-07-10
- Inspection date: 2026-08-08
- License: LGPL-3.0 (confirm institutional legal obligations before redistribution or modification)

The sandbox deploys the official release artifact only after SHA-256 verification. A separately pinned source snapshot (`lc-develop`, commit `eaa2bf47226d9ddb094ee7d0397d2e476c57a8bc`) supplies the public stock sandbox configuration directory; it is not the deployed application binary. The current development branch builds `1.4.0rc1` and its Dockerfile expects an unversioned WAR path, so it is not used as the sandbox release artifact. The sandbox runs PostgreSQL 16 to match the official 1.4 baseline and is local/synthetic only; it is not a production infrastructure recommendation or a claim of validated installation.
