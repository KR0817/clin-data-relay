# Portable Runtime Contract

## Recipient workflow

1. Install Docker Desktop with the WSL2 engine. If Docker is missing, `Start-Clinical-EDC.cmd` opens Docker's official Windows installation page; the Desktop installer is not redistributed because Docker's subscription agreement restricts third-party transfer.
2. Extract the archive to a writable local directory.
3. Run `Start-Clinical-EDC.cmd`.
4. On the first run, enter a recipient-specific Kimi API key. A unique localhost LibreClinica password is generated automatically; its browser-login copy is protected with Windows DPAPI and all local credential artifacts have a current-user Windows ACL.
5. The launcher starts Docker Desktop when needed, verifies the offline assets, starts LibreClinica, waits for both the web login and SOAP WSDL, starts the companion, and opens both localhost pages. Docker's first-run agreement is never accepted automatically and remains visible for the recipient.

Subsequent runs reuse the recipient's local configuration and require no repeated entry. `Show-LibreClinica-Login.cmd` decrypts the local browser login only for the same Windows account. `Stop-LibreClinica.cmd` stops the EDC containers without deleting their database volume.

Before image or Compose operations, the launcher writes `.runtime/portable-host-diagnostic.json` and stops with a stable `EDC-HOST-*` code when firmware virtualization, nested virtualization, SLAT, Virtual Machine Platform or WSL2 is unavailable. If only the Docker Linux engine is stopped, the launcher requests Docker Desktop startup and polls for up to 180 seconds; launch failure or timeout remains fail-closed. `Repair-Docker-Prerequisites.cmd` may enable Windows features and requires a reboot; it cannot change BIOS/UEFI or a VDI host.

## Distributed data

The archive contains a synthetic study template, four event CRFs, the 161-item Excel-derived mapping and predefined localhost roles. It contains no subject, event-CRF, item-value, login-audit, API-key, SOAP-credential, sender-password or copied Docker-volume data.

## Network and authority boundaries

- The companion and LibreClinica bind to `127.0.0.1` only.
- Kimi calls use the recipient-provided key and the configured Moonshot endpoint; source images remain subject to the existing de-identification and human-review gates.
- LibreClinica remains the authority record. The companion writes through the validated SOAP adapter and never updates clinical tables directly.
- Local password provisioning is limited to the clean portable seed's predefined accounts and is not a clinical-data write path.
- The package remains synthetic/local qualification software and reports production readiness as `BLOCK`.
