# Windows Lite Portable Distribution

**Status:** local research-validation utility; not an EDC  
**Target:** Windows 10/11 x64; no container runtime

## Recipient workflow

Extract `ClinicalReportExtractorLite-windows-x64.zip` to a writable local folder and double-click the branded `Start-Clinical-EDC-Lite.exe` (blue shield/report icon). `compatibility/Start-Clinical-EDC-Lite.cmd` remains the secondary entry point if local policy requires a command script. The package includes the Python application, Tesseract runtime, PDF parser and Excel exporter. Docker Desktop, WSL2, a Linux engine and LibreClinica are neither required nor included.

Kimi is optional. `Configure-Kimi.cmd` stores a recipient-provided key under the bundle-local ACL-restricted `.runtime` directory. Local pulmonary-function PDF extraction does not use Kimi or the network.

## Data and authority boundary

The Lite workflow stores source files, candidates and human decisions in its local SQLite companion database and exports only reviewed recognition values. It has no Authority-EDC write path and does not claim that local values reached LibreClinica. The distributed archive contains no sender database, uploads, credentials or logs.

## Centre-specific Windows packages

Use the centre builder after the verified generic Lite base exists:

```powershell
.\scripts\build_windows_centre_package.ps1 `
  -CentreCode SITE_A `
  -Username site-a-investigator@example.test `
  -VerificationPort 8021 `
  -SkipBaseBuild
```

Omit `-SkipBaseBuild` when the generic Lite base has not been rebuilt from the current source. Repeat with a different uppercase centre code, unique username and free verification port for each centre.

The output is `dist/ClinicalReportExtractorLite-<CENTRE>-windows-x64.zip` plus a sibling verification JSON. The ZIP contains one non-secret `centre-profile.json` and no database or password. On first launch the browser shows only the packaged centre identity and blocks login until the investigator generates or enters a strong password. The password is stored only as a salted scrypt hash.

The builder tests the freshly created ZIP, not the build folder: it extracts the archive into an isolated directory, starts the packaged EXE, completes first-run setup, rejects demo and other-centre logins, parses the synthetic pulmonary PDF, reviews 18 values, exports Excel and decrypts the generated centre package to confirm its centre code and SHA-256. QA data is removed after the run.

Before delivery, replace `.example.test` usernames with approved centre account names by rebuilding the corresponding package. Never rename or edit `centre-profile.json` after the manifest is generated.

## Build

```powershell
.\scripts\build_windows_lite.ps1
```

The build creates its own identifier-free pulmonary-function PDF fixture. It verifies the Lite health contract and the packaged PDF-to-review-to-Excel flow before writing the ZIP, manifest and verification JSON.
