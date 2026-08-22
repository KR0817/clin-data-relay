# Project-owned identity provider options

Date: 2026-08-23
Status: Technical research note; not a production approval
Scope: ClinData Relay central web identity when no hospital identity provider is available

## Decision

Use a **project-controlled Keycloak realm** as the first implementation path, provided the project can operate it on infrastructure in an approved jurisdiction. Describe the resulting assurance as **project-verified investigator identity**, not hospital or institutional identity.

This path removes the dependency on a hospital SSO while preserving the existing security boundary: the identity provider proves a login and MFA event; ClinData Relay's Study Membership remains the only source of role and centre authorization. The identity provider must never contain participant, report, clinical, or study-result data.

The managed alternatives remain valid fallbacks when an accountable project operator can accept the provider contract, processor/subprocessor chain, and data location. They are operationally easier, but neither Microsoft Entra External ID nor Auth0 public cloud currently offers a mainland-China customer-identity region in the cited documentation. If the project cannot fund and continuously operate Keycloak, a contract-approved managed provider is safer than an unmaintained self-hosted IdP.

## What “no hospital IdP” changes

An OIDC login can prove control of the enrolled account and completion of configured authentication factors. It cannot, by itself, prove employment by a hospital, investigator status, centre assignment, protocol delegation, or authorization to see study data. Those facts require a project-controlled enrolment record and Study Membership approval.

Therefore:

- account creation must be invitation-only after an authorized project administrator checks the investigator against approved study participation or delegation records;
- email ownership is evidence of account control, not proof of professional or institutional status;
- provider groups, email domains, display names, and self-asserted profile fields must not create application roles;
- ClinData Relay must continue to derive its pseudonymous principal from the verified `issuer/provider + subject` pair and look up a separate active Study Membership;
- deactivating Study Membership must invalidate the application session even if the identity-provider account still exists.

## Standards baseline

OpenID Connect Discovery defines provider metadata, including endpoint locations and `jwks_uri`; OIDC Core requires the relying party to validate the ID Token and defines `state`, `nonce`, issuer, subject, audience, expiry, authentication time, and authentication-context claims. Authorization Code Flow keeps tokens out of the browser-facing authorization response and is the appropriate web-application baseline. See the [OpenID Connect Discovery 1.0 specification](https://openid.net/specs/openid-connect-discovery-1_0-final.html) and [OpenID Connect Core 1.0 specification](https://openid.net/specs/openid-connect-core-1_0-final.html).

Authlib's maintained Starlette integration supports `server_metadata_url`, Authorization Code redirect/callback handling, and automatic ID-token parsing for OIDC clients. It is a smaller integration surface than building discovery, JWKS rotation, and token parsing directly. See the [Authlib Starlette OIDC client documentation](https://docs.authlib.org/en/latest/oauth2/client/web/starlette.html). Library use does not remove the application's obligation to enforce the configured issuer, client audience, callback URI, nonce/state, authentication age, and required MFA assurance.

## Option comparison

| Concern | Project-controlled Keycloak | Microsoft Entra External ID | Auth0 Customer Identity Cloud |
| --- | --- | --- | --- |
| Identity model | A project-owned realm and invitation-only local accounts. This is independent of hospital directories. | A dedicated external tenant is a managed CIAM directory. A workforce tenant with B2B guests may better match a small, known investigator cohort, but still requires a tenant operator. | A managed CIAM tenant with local or federated accounts. |
| MFA | TOTP/HOTP, WebAuthn/passkeys, recovery codes, required actions, and configurable authentication flows. MFA is not guaranteed merely by enabling a factor; the flow must require it and the client must verify the resulting assurance. [Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/) | Conditional Access can require MFA for an external tenant; documented factors include email OTP, SMS add-on, and FIDO2 passkeys, including step-up scenarios. [MFA in external tenants](https://learn.microsoft.com/en-us/entra/external-id/customers/concept-multifactor-authentication-customers) | Policies can require MFA always or adaptively; factors include OTP, WebAuthn, push, SMS/voice, and recovery codes, with availability depending on the plan. [Auth0 MFA factors](https://auth0.com/docs/secure/multi-factor-authentication/multi-factor-authentication-factors) |
| OIDC discovery and keys | Publishes realm discovery and JWKS/certificate endpoints and supports standard OIDC flows. [Keycloak OIDC layers](https://www.keycloak.org/securing-apps/oidc-layers) | Publishes standard OIDC metadata and signed tokens. The relying party must validate tokens with a supported library. [Microsoft identity platform OIDC](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc) | Publishes `/.well-known/openid-configuration` and `jwks_uri`; official guidance covers caching keys and one bounded refresh for rotation. [Auth0 JWKS discovery](https://dev.auth0.com/docs/secure/tokens/json-web-tokens/locate-json-web-key-sets) |
| Account lifecycle | Administrators can create, disable, delete, reset credentials, manage sessions, and revoke tokens. Keycloak documents that signing out all sessions does not by itself invalidate every already-issued access token for every client, so short token lifetimes and application-side membership checks remain necessary. [Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/) | External-tenant administrators can create, update, disable, and delete customer accounts. The project must still coordinate directory disablement with Study Membership deactivation. [Manage customer accounts](https://learn.microsoft.com/en-us/entra/external-id/customers/how-to-manage-customer-accounts) | Dashboard and Management API support create/update/delete; blocking is persistent until explicitly reversed. [Block and unblock users](https://dev.auth0.com/docs/manage-users/user-accounts/block-and-unblock-users) and [Management API user operations](https://dev.auth0.com/docs/manage-users/user-accounts/manage-users-using-the-management-api) |
| Operational burden | Highest. The project owns TLS, hostname/proxy configuration, database, secrets, patching, backups, restore drills, monitoring, capacity, incident response, and availability. Keycloak's production guide calls for secure communication, a production database, reverse-proxy controls, health checks, overload protection, and typically multiple instances for availability. [Production configuration](https://www.keycloak.org/server/configuration-production) | Lowest infrastructure burden; Microsoft operates the identity service. The project still owns tenant configuration, administrators, enrolment/offboarding, Conditional Access, logs, contracts, and application validation. | Low infrastructure burden in public cloud. The project still owns tenant configuration, administrators, lifecycle, logs, plan-dependent security features, contracts, and application validation. |
| Data location | Determined by the selected server, database, backups, logs, email/SMS services, and operators. Self-hosting removes a Keycloak SaaS processor, but the hosting, backup, messaging, and support vendors may still be processors. This is an architectural inference, not a legal conclusion. | External tenants allow a geographic choice, but Microsoft states that China cloud does not currently support external tenants; Go-Local for external tenants is currently listed for Australia and Japan. Some MFA operational data can be stored in North America and/or the tenant geography. [Entra data residency](https://learn.microsoft.com/en-us/entra/fundamentals/data-residency) | Public-cloud regions are documented as Australia, Canada, Europe, Japan, United Kingdom, and United States; no mainland-China public region is listed. [Auth0 tenant regions](https://auth0.com/docs/get-started/auth0-overview/create-tenants) |
| Processor contract | Keycloak software is self-operated, but each infrastructure/support vendor needs its own approved role and agreement where applicable. | Microsoft publishes a products-and-services DPA, but the subscribing legal entity must confirm the selected service and processing arrangement are covered. [Microsoft licensing documents](https://www.microsoft.com/licensing/docs) | Auth0 states that customers are generally controllers and Auth0 is a processor; enterprise use is governed through the subscription agreement and DPA, while self-service terms differ. [Auth0 GDPR responsibilities](https://auth0.com/docs/secure/data-privacy-and-compliance/gdpr) and [Auth0/Okta DPA access](https://support.auth0.com/center/s/article/DPA) |

## Why Keycloak is the selected first path

The project already owns the Study Membership and PostgreSQL session boundary, so it does not need hospital groups or provider-side application roles. What it lacks is a standards-conformant authenticator that can produce a verified `issuer + subject`, recent authentication time, and MFA assurance.

Keycloak is the most direct replacement when all of the following are true:

1. investigators are invited and verified by the project rather than discovered from a hospital directory;
2. deployment and backups can remain in an approved location;
3. at least two named administrators can operate identity recovery and offboarding;
4. the project accepts responsibility for patching, monitoring, backup/restore, and incident response.

Managed OIDC should replace Keycloak if condition 3 or 4 cannot be met. That substitution is safe at the application boundary because discovery, OIDC validation, pseudonymous principal derivation, Study Membership, and local session policy remain provider-neutral.

## Concrete implementation path

### 1. Define the assurance honestly

Rename user-facing and governance language from “institutional identity” to “project-verified investigator identity.” Internal module names can be migrated separately, but no document or UI should imply that the hospital authenticated or endorsed the user.

Create a controlled enrolment SOP with:

- two-person approval for principal-investigator and central-data-manager accounts;
- verification against approved study participation/delegation records;
- one account per natural person, with no shared accounts;
- recorded centre code and role in ClinData Relay Study Membership, not in the IdP profile;
- expiry aligned to the delegation period;
- documented recovery, suspension, role change, and departure procedures.

### 2. Deploy the identity service separately

Deploy a pinned supported Keycloak release with its own PostgreSQL database/user and encrypted backups. Use a fixed public HTTPS hostname, a reverse proxy with a minimal public path set, unexposed management port, health checks, rate limiting, and monitoring. Keycloak documents the supported database configuration and warns that database files, write-ahead logs, and backups require equivalent encryption protection; it also requires database backup before upgrades. See [Keycloak database configuration](https://www.keycloak.org/server/db) and the [Keycloak upgrading guide](https://www.keycloak.org/docs/latest/upgrading/).

Use separate development, qualification, and production realms or deployments. Do not copy real production users into development. Do not place the Keycloak administrator console on the unrestricted public path; require a restricted administrative network path and MFA for administrators.

For availability, use the smallest topology that meets the approved recovery-time objective. Keycloak describes two or more instances as typical for continued login after a node failure and publishes separate high-availability architectures. A single node may be acceptable only if planned identity downtime is explicitly accepted and restore evidence meets the approved objective; it must not be described as highly available. See the [Keycloak high-availability overview](https://www.keycloak.org/high-availability/introduction).

### 3. Configure invitation-only strong authentication

- Disable public self-registration and social identity providers.
- Create users only after project enrolment approval.
- Require password replacement on first use and require registration of WebAuthn or TOTP.
- Configure the browser authentication flow so the second-factor subflow is required, not merely conditional on a factor already existing.
- Prefer WebAuthn/passkeys; retain TOTP and single-use recovery codes as controlled fallbacks.
- Configure a minimum ACR for the ClinData Relay client and an AMR mapper; request a bounded `max_age`/`auth_time`; have the adapter reject a login unless the expected ACR/AMR evidence and recent authentication time are present. Keycloak explicitly warns that a default ACR alone does not reliably enforce a level and recommends a minimum ACR plus client-side verification. [Keycloak authentication-level guidance](https://www.keycloak.org/docs/latest/server_admin/)
- Use short identity-provider token lifetimes. ClinData Relay should not persist provider access or refresh tokens after the callback completes.

### 4. Add one confidential OIDC web client

Register one confidential web client with:

- Authorization Code Flow only;
- exact HTTPS callback and post-logout redirect URIs;
- no wildcard redirects;
- `openid` plus only the minimum claims needed for authentication;
- a server-side client credential stored outside Git, logs, database rows, and audit details;
- discovery metadata from the fixed issuer and JWKS key rotation support.

Implement the adapter with Authlib's Starlette client. At callback, require validation of `state`, `nonce`, signature, expected issuer, expected audience/client ID, `exp`, `iat`, `auth_time`, and the configured MFA ACR/AMR. Reject missing, ambiguous, stale, or unexpected claims. Never authorize from email, display name, realm roles, or groups.

After validation, construct the existing verified-principal object, derive the pseudonymous principal ID, require an active Study Membership, and create the existing hashed institutional-session token. Provider tokens and raw provider responses must be discarded after this step.

### 5. Coordinate lifecycle and session invalidation

Provisioning order:

1. verify the investigator and delegation record;
2. create the Keycloak account and complete MFA enrolment;
3. grant the ClinData Relay Study Membership with centre and expiry;
4. perform a witnessed first-login test.

Offboarding order:

1. deactivate Study Membership first so application sessions fail immediately;
2. disable the Keycloak account;
3. end Keycloak user sessions and apply the documented token-revocation procedure;
4. retain only the required audit evidence under the approved schedule.

Enable and retain Keycloak user/admin events under a documented policy, but do not treat provider logs as a replacement for ClinData Relay's append-only membership and session audit chain. Keycloak exposes user-session administration, token revocation, and user/admin event mechanisms in its [Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/).

## Production qualification boundary

The following are useful evidence but **do not independently qualify production use**:

- Keycloak running in production mode;
- successful OIDC discovery or JWKS validation;
- an OIDC conformance statement;
- an MFA prompt during a demonstration;
- an Auth0/Microsoft DPA or compliance certificate;
- synthetic login tests;
- successful unit, integration, or CI tests.

Production activation remains blocked until the accountable project entity approves and records at least:

1. the project identity assurance claim and enrolment/offboarding SOP;
2. named service owner, two administrators, and least-privilege administrative access;
3. hosting location, data inventory, retention, processor/subprocessor contracts, and transfer analysis;
4. threat model for callback, token, session, account recovery, administrator compromise, and denial of service;
5. negative OIDC tests for issuer, audience, signature, nonce/state, expiry, authentication age, MFA assurance, redirect URI, and key rotation;
6. demonstrated membership deactivation and session invalidation;
7. encrypted backup plus timed restore evidence for both Keycloak and PostgreSQL;
8. patching and rollback procedure with a tested upgrade rehearsal;
9. monitoring, alerting, audit retention, incident response, and emergency-access drills;
10. separation and reconciliation of development, qualification, and production configuration;
11. application security review and approved release/change records;
12. ethics, privacy, data-flow, and organizational authorization applicable to the actual deployment and users.

If no accountable organization or project entity can approve these controls and enter necessary service/hosting agreements, no identity-provider choice can turn the central web deployment into a qualified production clinical system. In that case, keep central access non-production and continue the already approved centre-local/offline encrypted-package workflow.

## Managed-provider fallback rule

Choose Microsoft Entra or Auth0 instead of Keycloak only after a written gate confirms:

- the contracting project entity and subscription owner;
- exact service/plan and mandatory MFA features;
- selected tenant geography and all relevant processing locations;
- DPA, subprocessors, breach terms, deletion/export, and exit plan;
- administrator recovery and account lifecycle responsibilities;
- a non-production tenant for integration and qualification.

For a small set of known investigators, an Entra workforce tenant with B2B guests can be evaluated before External ID CIAM, because External ID is positioned for customer-facing applications. This is a managed alternative, not evidence of hospital affiliation. Auth0 is technically straightforward, but its public-cloud geography and plan-specific MFA terms require the same written review.

## Sources reviewed

Only primary specifications and vendor documentation were used:

- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0-final.html)
- [OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0-final.html)
- [Authlib Starlette OIDC client](https://docs.authlib.org/en/latest/oauth2/client/web/starlette.html)
- [Keycloak OIDC layers](https://www.keycloak.org/securing-apps/oidc-layers)
- [Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/)
- [Keycloak production configuration](https://www.keycloak.org/server/configuration-production)
- [Keycloak database configuration](https://www.keycloak.org/server/db)
- [Keycloak high availability](https://www.keycloak.org/high-availability/introduction)
- [Keycloak upgrading guide](https://www.keycloak.org/docs/latest/upgrading/)
- [Microsoft Entra External ID overview](https://learn.microsoft.com/en-us/entra/external-id/customers/overview-customers-ciam)
- [Microsoft Entra MFA for external tenants](https://learn.microsoft.com/en-us/entra/external-id/customers/concept-multifactor-authentication-customers)
- [Microsoft Entra data residency](https://learn.microsoft.com/en-us/entra/fundamentals/data-residency)
- [Microsoft licensing documents](https://www.microsoft.com/licensing/docs)
- [Auth0 JWKS discovery](https://dev.auth0.com/docs/secure/tokens/json-web-tokens/locate-json-web-key-sets)
- [Auth0 MFA factors](https://auth0.com/docs/secure/multi-factor-authentication/multi-factor-authentication-factors)
- [Auth0 user lifecycle](https://dev.auth0.com/docs/manage-users/user-accounts/manage-users-using-the-management-api)
- [Auth0 tenant regions](https://auth0.com/docs/get-started/auth0-overview/create-tenants)
- [Auth0 data processing and controller/processor roles](https://auth0.com/docs/secure/data-privacy-and-compliance/gdpr)
