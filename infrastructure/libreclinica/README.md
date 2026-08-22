# LibreClinica synthetic sandbox

This directory creates a localhost-only LibreClinica sandbox for synthetic interface-test records. It contains no patient data or production configuration. The dedicated generated SOAP credential is outside this directory in the ignored `.runtime` folder.

## Preconditions

- Docker Desktop with its engine running.
- Sufficient free disk space for container images, the official release WAR, and the synthetic database volume.
- Do **not** use a network folder that contains source images or clinical exports as a build context or volume mount.

## Build and validate

Run in PowerShell from the `clinical-edc-companion` directory:

```powershell
Copy-Item .\infrastructure\libreclinica\.env.sandbox.example .\infrastructure\libreclinica\.env.sandbox
.\scripts\fetch_libreclinica_release.ps1
.\scripts\validate_libreclinica_sandbox.ps1 -Start -UseCachedImages
```

The web and SOAP/ODM release URLs and expected SHA-256 values are in [upstream.lock.md](./upstream.lock.md). The validator checks both WARs before Docker starts and reports success only after the root, protected-login route and data-import WSDL respond. `-UseCachedImages` avoids a registry rebuild when the verified local image already exists.

After the one-time sandbox account/OID provisioning, prepare the synthetic subject/event fixture and start the connected companion with:

```powershell
.\.venv\Scripts\python.exe -m scripts.bootstrap_libreclinica_synthetic_subject
.\scripts\start_companion_live.ps1
```

This enables only the localhost SOAP/ODM path and never a direct database-write path. Production or real-data use remains prohibited by `docs/preflight.md`.

## Teardown

Stopping containers preserves the synthetic database volume. Removing that volume permanently discards only synthetic sandbox records:

```powershell
docker compose --env-file .\infrastructure\libreclinica\.env.sandbox -f .\infrastructure\libreclinica\compose.sandbox.yaml down
```

Do not run `down --volumes` unless the sandbox data are no longer needed.
