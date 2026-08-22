# Central Server Deployment: Official-Source Research and Runbook

**Research date:** 2026-08-14  
**Scope:** ClinData Relay plus LibreClinica for an investigator-initiated, multi-centre study  
**Decision:** A synthetic-data pilot can be hosted on a controlled Linux server after the safeguards below are applied. Real participant-data service is **BLOCKED** until the central PostgreSQL repository, institutional approvals, security qualification, validation evidence, and operating procedures are complete.

This note is based only on first-party project documentation and official government or vendor documentation. It is an engineering deployment guide, not legal advice or a claim that the current application is production-ready.

## 1. What can be deployed now

### 1.1 Synthetic-data pilot

The current application can be demonstrated to invited testers with synthetic reports only. Use a dedicated Linux virtual machine, a real domain, Caddy TLS termination, and the existing localhost-only application and LibreClinica containers. Keep every upstream service bound to loopback or a private Docker network; expose only TCP 443 through Caddy.

The pilot is for workflow and interface qualification. It must not contain participant data, real Kimi payloads, a production EDC study, or shared real-world passwords. The repository's portable/sandbox Compose definitions contain development defaults and synthetic seeds; they are not production templates.

### 1.2 Real clinical-data service

Do not deploy the current local profile as a shared real-data server. The companion currently uses a single-host SQLite repository and deliberately fails closed when `COMPANION_DEPLOYMENT_PROFILE=central` is selected. A shared service first needs:

1. a PostgreSQL-backed companion repository with migration, transaction, concurrency, centre-isolation, and backup/restore tests;
2. institution-managed identity, MFA, account lifecycle and least-privilege roles;
3. HTTPS, managed secrets, host hardening, monitoring, alerting, patching and incident response;
4. validated LibreClinica CRFs/OIDs and qualified SOAP/ODM write plus read-back reconciliation;
5. approved ethics, multi-centre data agreement, privacy impact assessment, retention/deletion rules, third-party and cross-border data-flow review;
6. installation qualification, operational qualification, performance qualification, user acceptance, change control, SOPs, training, disaster-recovery tests and release approval.

LibreClinica's official site lists version 1.4 for Debian/Ubuntu, Tomcat 9, OpenJDK 11 and PostgreSQL 16. Its GitHub README has an older PostgreSQL 13/14 table and explicitly describes SOAP as legacy, untested and not actively developed. Resolve that upstream documentation difference and qualify the exact deployed artifact rather than assuming compatibility. Sources: [LibreClinica downloads and requirements](https://www.libreclinica.org/download.html), [LibreClinica repository](https://github.com/reliatec-gmbh/LibreClinica), [LibreClinica documentation and validation warning](https://www.libreclinica.org/documentation/).

## 2. Recommended topology

```text
Researcher browser
        |
        | HTTPS 443
        v
Institution firewall / VPN / allow-list
        |
        v
Caddy reverse proxy
        |-- 127.0.0.1:8000  Companion FastAPI
        `-- 127.0.0.1:8081  LibreClinica web/SOAP
                                  |
                                  `-- private network --> PostgreSQL 16

Backup account --> encrypted off-host backup repository
Monitoring      --> health, capacity, backup and certificate alerts
```

Recommended minimum:

- One institution-managed Ubuntu 24.04 LTS virtual machine for a small synthetic pilot; use separate application and database hosts for a qualified real-data deployment if the hospital standard requires it.
- A DNS name such as `edc.example-hospital.cn` pointing to the server. Prefer hospital VPN or source-IP allow-listing over unrestricted public access.
- Public inbound ports: 443, and 80 only if required for certificate issuance/redirect. SSH must be reachable only from an administration network or VPN.
- PostgreSQL 5432, FastAPI 8000, Tomcat/LibreClinica 8081, Docker daemon sockets, metrics, and mail-test tools must not be internet-published.
- Store application/database state in named volumes or institution-managed data paths, not in a container writable layer. Docker documents volumes as persistent stores independent of container lifecycle. Source: [Docker volumes](https://docs.docker.com/engine/storage/volumes/).

Do not host this on a researcher's laptop, NAS with consumer remote access, personal cloud account, or Windows Docker Desktop. Linux Docker Engine avoids the recipient-side Desktop/WSL/virtualisation problem and is easier to supervise as a service, but it does not itself make the system compliant.

## 3. Host preparation

### 3.1 Ownership and prerequisites

Before provisioning, assign named owners for the clinical system, database, server, privacy, security, validation and backup restoration. Record the approved domain, network zone, data classification, retention period, recovery-point objective and recovery-time objective.

For a small synthetic pilot, start with at least 4 vCPU, 8 GiB RAM, 100 GiB SSD and a separate encrypted backup target. These are planning estimates, not LibreClinica-certified sizing. Measure CPU, memory, upload size, OCR duration, database growth and concurrent users before production sizing.

### 3.2 Install Docker Engine on Ubuntu

Use Docker's signed apt repository and a pinned, approved version. Docker states that its convenience install script is for testing/development and is not recommended for production. Follow the current commands from [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/), then verify:

```bash
sudo systemctl status docker
sudo docker run --rm hello-world
sudo docker compose version
```

Security implications:

- Docker warns that published container ports can bypass `ufw`/`firewalld` handling. Restrict traffic in the `DOCKER-USER` chain or the institution's upstream firewall and publish internal services to `127.0.0.1` only. Sources: [Ubuntu firewall warning](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations), [packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
- Membership in the `docker` group grants root-level privileges. Give it only to designated administrators, or evaluate Docker rootless mode after testing compatibility. Sources: [Linux post-installation](https://docs.docker.com/engine/install/linux-postinstall/), [rootless mode](https://docs.docker.com/engine/security/rootless/).
- Configure bounded log rotation; Docker notes that the default `json-file` logs can grow until they exhaust disk space. Source: [Linux post-installation](https://docs.docker.com/engine/install/linux-postinstall/#configure-default-logging-driver).
- Pin image versions or digests, retain an SBOM/third-party manifest, scan images, test upgrades in staging, and never mount the Docker socket into application containers.

### 3.3 Secrets

Do not copy passwords, Kimi keys, private keys or SOAP credentials into source, Compose YAML, image layers, command arguments or logs. Docker recommends Compose secrets rather than environment variables for passwords and API keys because environment values can be exposed to processes or logs. Grant each secret only to the service that needs it. Source: [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

Use an institution-managed secret store where available. For a synthetic pilot, root-owned secret files with mode `0600`, stored outside the repository and referenced through Compose secrets, are the minimum fallback. Rotate bootstrap credentials immediately and document recovery without recording secret values.

## 4. TLS and reverse proxy with Caddy

Caddy is the simplest supported reverse-proxy choice for this project. Its official package installs a systemd service; automatic HTTPS obtains and renews qualifying certificates and redirects HTTP to HTTPS. Sources: [Caddy installation](https://caddyserver.com/docs/install), [automatic HTTPS](https://caddyserver.com/docs/automatic-https), [running as a service](https://caddyserver.com/docs/running).

Prerequisites for public certificates:

- a real DNS name pointing to the server;
- inbound TCP 80 and 443 reaching Caddy, subject to institutional approval;
- persistent Caddy data storage for certificates;
- no CDN/proxy header trust unless its IP ranges are explicitly configured.

Illustrative Caddyfile for two hostnames:

```caddyfile
companion.example-hospital.cn {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
}

libreclinica.example-hospital.cn {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8081
}
```

Validate and reload without downtime:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
systemctl status caddy
journalctl -u caddy --no-pager -n 200
```

Caddy passes requests to an HTTP upstream by default; loopback HTTP is acceptable only when Caddy and the upstream share the same controlled host. For separate hosts, use authenticated TLS or an institution-approved private network. Never set `tls_insecure_skip_verify`; Caddy documents that it disables security checks. Source: [Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

The illustrative configuration is not a complete hospital security policy. Add institution-approved request-size limits, timeouts, access-log handling, source restrictions and protective response headers. Logs must not contain Authorization headers, cookies, direct identifiers, OCR text or report payloads.

## 5. Application and LibreClinica deployment

### 5.1 Synthetic pilot procedure

1. Clone or transfer a checksum-verified release bundle to an administrator-owned directory such as `/opt/clinical-edc-companion`; do not deploy a mutable developer working tree.
2. Verify source/image/WAR hashes and third-party notices. The official LibreClinica download page publishes SHA-256 values for the 1.4 web and SOAP WARs.
3. Create new local secrets and accounts. Do not reuse the repository's synthetic database password or any password from a portable ZIP.
4. Build a server-specific Compose overlay that:
   - binds companion and LibreClinica only to loopback;
   - has no host mapping for PostgreSQL;
   - uses persistent named volumes;
   - uses `restart: unless-stopped` and health checks;
   - injects secrets without committing them;
   - removes MailCrab and every demo-only service unless explicitly needed for synthetic testing.
5. Start the exact pinned images and inspect their health:

```bash
sudo docker compose config
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=200
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8081/
```

6. Install Caddy, configure DNS/TLS, and verify that only HTTPS is externally reachable.
7. Create synthetic investigator accounts through the application and LibreClinica administration interfaces; test centre isolation, review, export, submission retry and authority read-back with synthetic records.
8. Exercise a restore on a separate disposable host before inviting users.

### 5.2 Real-data conversion gate

The synthetic stack must not be converted by merely changing a flag or replacing demo subjects. Build and qualify a separate environment. The current companion cannot enter central mode until its PostgreSQL repository is implemented and tested; running multiple Uvicorn workers against its SQLite database or placing the local executable behind Caddy is not a supported shortcut.

For LibreClinica, install the exact approved web and SOAP artifacts, Tomcat/OpenJDK/PostgreSQL versions, configuration and CRF/OID mapping. Treat the SOAP integration as a legacy interface and prove idempotent submission plus authoritative read-back for each supported operation. Never modify LibreClinica tables directly.

## 6. PostgreSQL security and backup

### 6.1 Network and authentication

Keep the database on a private network. PostgreSQL defaults `listen_addresses` to localhost; broaden it only to explicit private interfaces required by approved application hosts. Source: [PostgreSQL connection settings](https://www.postgresql.org/docs/16/runtime-config-connection.html).

Use separate non-superuser roles for the companion, LibreClinica, migration and backup functions. Restrict databases, addresses, users and authentication methods in `pg_hba.conf`; never use `trust` for network access. If database traffic crosses hosts, enable TLS and use `hostssl`; PostgreSQL can require CA-verified client certificates with `clientcert=verify-ca` or `verify-full`. Sources: [pg_hba.conf](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html), [SSL connections](https://www.postgresql.org/docs/current/ssl-tcp.html).

### 6.2 Backup design

PostgreSQL identifies three primary approaches: SQL dump, filesystem-level backup and continuous archiving. `pg_dump` makes a consistent backup of one database while clients continue working; `pg_basebackup` backs up an entire running cluster and can support point-in-time recovery when combined with WAL archiving. Sources: [PostgreSQL backup and restore](https://www.postgresql.org/docs/16/backup.html), [pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html), [pg_basebackup](https://www.postgresql.org/docs/current/app-pgbasebackup.html).

Minimum operating policy:

- nightly encrypted `pg_dump -Fc` of the companion and LibreClinica databases;
- regular full cluster/base backup plus WAL archiving when the approved RPO requires point-in-time recovery;
- encrypted off-host copy in a separate failure domain, with access logged and retention matching the protocol and institutional policy;
- backup job failure and age alerts;
- monthly automated integrity checks and scheduled full restore drills to an isolated environment;
- written proof of the restored database version, row/record checks, application login, audit history and interface reconciliation;
- backup encryption keys stored separately from backups, with tested institutional recovery custody.

A backup file is not evidence of recoverability. Record the last successful restore drill and block production readiness if it is overdue.

## 7. Operations and change control

Before opening access, create:

- service inventory, data-flow map and approved firewall matrix;
- named production, security, privacy, database and clinical-data owners;
- least-privilege account matrix, MFA policy and joiner/mover/leaver procedure;
- immutable or protected audit-log export and time-synchronisation checks;
- daily health/capacity/backup alerts and on-call escalation;
- incident response, breach notification, downtime entry and reconciliation procedures;
- patch window, staging verification, rollback package and database migration/rollback plan;
- change request, release approval, checksum/SBOM and validation evidence for every version;
- annual disaster-recovery exercise and periodic access review.

Do not put clinical values, subject identifiers, OCR text, uploaded filenames, bearer tokens or API keys into reverse-proxy, application, Docker or monitoring logs. Restrict and retain necessary security/audit logs under the approved policy.

## 8. China real-data go-live prerequisites

These are approval gates, not a legal opinion.

### Generally applicable

- Health/medical information is sensitive personal information under the Personal Information Protection Law. The institution must establish a lawful basis, specific and necessary purpose, appropriate notice/consent where applicable, minimal collection, retention/deletion rules, rights handling, access control, encryption, de-identification, training, incident response and a personal-information protection impact assessment for high-risk processing. Source: [Personal Information Protection Law, official CAC text](https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm).
- The Data Security Law requires classification/grading, full-process management, technical safeguards, risk monitoring and incident handling. Whether data is formally “important data” depends on competent-authority catalogues and notification, not an informal project label. Source: [Data Security Law, National People's Congress](https://www.npc.gov.cn/npc/c2/c30834/202106/t20210610_311888.html).
- The Network Data Security Management Regulation requires security measures on top of classified protection, including encryption, backup, access control and authentication; commissioned processing must be contractually bounded and supervised, and related records retained for at least three years. Source: [Network Data Security Management Regulation](https://app.www.gov.cn/govdata/gov/202409/30/520076/article.html).
- A medical institution should have its information/security centre determine the required cybersecurity-classified-protection level, filing, assessment and rectification before network service. Source: [Measures for Cybersecurity Management of Medical and Health Institutions](https://app.www.gov.cn/govdata/gov/202208/31/488953/article.html).
- Research using participants, samples, health records or other information data requires ethics review and continuing governance under the applicable research protocol. Source: [Ethical Review Measures for Life Science and Medical Research Involving Humans](https://www.nhc.gov.cn/wjw/c100375/202302/902b4a1dc3af4aba862a6387e6e376dc.shtml).

### Conditional triggers

- For this investigator-initiated research, the lead and participating institutions should apply their clinical-research governance, scientific/ethics review, contract, quality, records and multi-centre procedures. Source: [Measures for the Administration of Investigator-Initiated Clinical Research in Medical and Health Institutions](https://www.nhc.gov.cn/qjjys/c100016/202409/3a3ad0a7b656420d9580b65f2321a623.shtml).
- Human genetic resources rules apply when the study processes human genes/genome data or covered materials/activities. The implementing rules expressly state that ordinary clinical, imaging, protein and metabolite data are not human genetic-resource information. Source: [Human Genetic Resources implementing rules](https://www.most.gov.cn/xxgk/xinxifenlei/fdzdgknr/fgzc/bmgz/202306/t20230601_186416.html).
- Overseas cloud, logging, backup or AI endpoints may constitute cross-border data provision. Complete the extra notice/consent, impact assessment, contract/provider and applicable outbound-data mechanism review before enabling them. Prefer an approved domestic deployment and keep external Kimi processing disabled for real reports until the exact vendor, region, retention/training terms and data flow are approved. Source: [Provisions on Facilitating and Regulating Cross-Border Data Flows](https://www.cac.gov.cn/2024-03/22/c_1712776611775634.htm).
- If a service is offered from mainland China through a public domain or IP, have the institution and hosting provider confirm ICP filing and any sector pre-approval requirements. Source: [Non-commercial Internet Information Services Filing Measures](https://www.miit.gov.cn/gyhxxhb/jgsj/cyzcyfgs/bmgz/xxtxl/art/2024/art_84a0cfa0ebd049bbbe751dca9a008e56.html).

Production remains **BLOCK** until the lead hospital's ethics committee, clinical-research management department, information centre, privacy/legal function and cybersecurity function approve the exact data flow and sign the go-live record.

## 9. Acceptance checklist

### Synthetic pilot — PASS only if all are true

- [ ] Only synthetic data and synthetic accounts are present.
- [ ] The server is institution-managed; upstream ports bind to loopback/private networks.
- [ ] Only HTTPS 443 is user-accessible; certificate renewal and expiry alert are tested.
- [ ] No repository default passwords are in use; secrets are outside source and images.
- [ ] Centre isolation, role permissions, review, export, transfer and reconciliation are tested.
- [ ] Database and uploaded-file persistence are documented.
- [ ] An off-host encrypted backup has been restored successfully.
- [ ] Logs were inspected and contain no report content, identifiers, tokens or credentials.
- [ ] The interface/version discrepancy and every known warning remain visible.

### Real participant data — BLOCK unless all are true

- [ ] Qualified PostgreSQL companion repository replaces the local SQLite profile.
- [ ] Identity/MFA, least privilege and account lifecycle are institution-managed.
- [ ] Ethics, scientific, privacy, multi-centre and cybersecurity approvals are recorded.
- [ ] Data classification, classified-protection obligations and data-residency/cross-border decisions are recorded.
- [ ] Validated CRF/OID mapping and LibreClinica SOAP/ODM read-back evidence pass.
- [ ] Backup, restore, disaster recovery, monitoring, incident response and downtime reconciliation pass.
- [ ] Installation/operational/performance qualification, UAT, SOPs, training and change control pass.
- [ ] An authorised owner signs the production go-live decision.

## 10. Practical recommendation

Use the current code to run a time-boxed, synthetic-data pilot on one hospital-controlled Ubuntu server behind Caddy. In parallel, implement and qualify the companion PostgreSQL adapter and institutional identity boundary. Only after the real-data checklist is independently approved should the team build a separate production environment. This sequence gives researchers a simple browser URL without misrepresenting a local SQLite demonstration as a multi-user clinical production system.
