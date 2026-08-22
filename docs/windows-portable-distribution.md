# Windows Integrated Portable Distribution

**Status:** synthetic-data localhost qualification; not a validated production EDC  
**Target:** Windows 10/11 x64 with WSL2 and Docker Desktop

## Deliverables

- `ClinicalEdcCompanion/Start-Clinical-EDC.cmd`: single startup entry point.
- `ClinicalEdcCompanion/ClinicalEdcCompanion.exe`: bundled companion runtime; normally invoked by the entry point.
- `ClinicalEdcCompanion/libreclinica/`: Compose definition, subject-free seed and pinned offline Docker image archive.
- `ClinicalEdcCompanion/runtime/tesseract/`: local OCR runtime.
- `ClinicalEdcCompanion/Show-LibreClinica-Login.cmd`: current-user DPAPI login display.
- `ClinicalEdcCompanion/Diagnose-This-PC.cmd`: credential-free virtualization/WSL/Docker diagnosis.
- `ClinicalEdcCompanion/Repair-Docker-Prerequisites.cmd`: explicit elevated Windows-feature repair; BIOS and VDI host settings remain manual/IT-controlled.
- `ClinicalEdcCompanion/MANIFEST.sha256`: distributed-file hashes.
- `ClinicalEdcCompanion-windows-x64.zip`: transferable archive.

## Recipient workflow

1. Install Docker Desktop with WSL2. `Install-Docker-Desktop.cmd` opens the official page when needed; the installer is not redistributed.
2. Extract the complete archive to a writable local directory.
3. Run `Start-Clinical-EDC.cmd` and enter a recipient-specific Kimi key. The launcher starts Docker Desktop automatically when its Linux engine is stopped; Docker's first-run agreement remains a visible recipient action.
4. The launcher verifies offline hashes, loads images, restores a subject-free LibreClinica template, generates a local LibreClinica password, configures predefined accounts, starts the companion and opens both localhost pages.
5. Later starts reuse the local configuration. `Stop-LibreClinica.cmd` stops services without deleting the Docker volume.

Before any Docker image or Compose operation, the launcher verifies firmware/hypervisor virtualization, SLAT, Virtual Machine Platform, WSL and Docker engine readiness. When only the engine is stopped, it uses Docker Desktop's supported CLI or documented installation location and waits up to 180 seconds. Raw named-pipe errors such as `dockerDesktopLinuxEngine ... 500 Internal Server Error` are reduced to stable `EDC-HOST-*` codes. The generated `.runtime/portable-host-diagnostic.json` contains capability booleans, bounded auto-start metadata and remediation steps but no raw Docker response, executable path or credential.

`Repair-Docker-Prerequisites.cmd` enables Microsoft's WSL and Virtual Machine Platform features and sets the Windows hypervisor to launch automatically. A restart is required. It cannot change BIOS/UEFI settings and cannot expose nested virtualization inside an institution-managed VM/VDI; those changes require the device owner or IT administrator.

The recipient does not need Python, Node.js or Tesseract. No Kimi key, reusable LibreClinica password, SOAP credential, SQLite database, upload, audit record or sender Docker volume is distributed.

## Security and license boundary

The local LibreClinica browser password is encrypted with Windows DPAPI and can be decrypted only by the Windows user who performed setup. The legacy SOAP adapter receives only the required SHA-1 representation through a current-user ACL-protected local file. The startup script applies that digest to the predefined clean-seed accounts through PostgreSQL stdin, never through process arguments.

Docker Desktop is a prerequisite, not part of the archive. Docker's current Subscription Service Agreement describes the Desktop license as non-transferable and restricts third-party distribution; Docker images may be bundled with the product under their corresponding terms. Organizations remain responsible for Docker Desktop subscription eligibility.

## Build and verification

Run from the project root:

```powershell
.\scripts\build_windows_portable.ps1
```

The build runs focused tests, creates the PyInstaller onedir app, builds and saves the pinned LibreClinica stack, copies the verified clean seed, creates both manifests, and performs two isolated checks. The first proves the raw EXE remains fail-closed without credentials. The second restores a new Docker volume on separate ports, configures generated local credentials, starts the EXE with Kimi enabled, performs OCR and human review, provisions a synthetic subject, submits one value through LibreClinica SOAP and verifies the authority database value. The QA Compose project and volume are removed afterward.

## Production boundary

The artifact is unsigned and intended for synthetic localhost evaluation. Before institutional or real-patient use, add code signing, malware scanning, a complete SBOM/license review, approved identity and secrets management, TLS, backup/restore policy, validation evidence, study approvals and institution-approved Docker/Kimi agreements.
