ClinData Relay - Windows x64 integrated package
========================================================

First start
-----------
1. Extract the complete ZIP to a writable local folder.
2. Install Docker Desktop with WSL2. If Docker is missing, run
   Install-Docker-Desktop.cmd to open Docker's official installation page.
3. Double-click Start-Clinical-EDC.cmd. Do not launch the EXE directly.
4. Enter this computer's Kimi API key when prompted.
5. The launcher starts Docker Desktop when needed. On Docker's first run,
   accept its agreement in the visible Docker window, then wait for both the
   workbench and LibreClinica login page to open.

If startup reports an `EDC-HOST-*` code, run `Diagnose-This-PC.cmd`. When the
code says WSL2 or Virtual Machine Platform is disabled, run
`Repair-Docker-Prerequisites.cmd` as Administrator and restart Windows. When it
says virtualization is disabled, enable Intel VT-x/Virtualization Technology or
AMD SVM Mode in BIOS/UEFI first. A virtual/VDI computer requires IT to enable
nested virtualization on the host.

LibreClinica generates a unique password on this computer. The startup window
shows it once. Run Show-LibreClinica-Login.cmd whenever the same Windows user
needs to display it again. The password is protected with Windows DPAPI and is
not present in this ZIP.

Daily use
---------
- Start both systems: Start-Clinical-EDC.cmd
- Stop both systems without deleting data: Stop-LibreClinica.cmd
- Diagnose this computer: Diagnose-This-PC.cmd
- Enable Windows WSL2 prerequisites: Repair-Docker-Prerequisites.cmd
- Workbench: http://127.0.0.1:8000/
- LibreClinica: http://127.0.0.1:8081/LibreClinica/
- LibreClinica admin username: sandbox_admin

Synthetic workbench login
-------------------------
Central data manager: central-data-manager@example.test
Site investigator: site-a-investigator@example.test
Password: demo-password

Included locally
----------------
- ClinData Relay and Python runtime
- Tesseract OCR with Chinese/English language data
- Excel export fallback
- LibreClinica, PostgreSQL and MailCrab offline Docker images
- Subject-free synthetic study seed and current Excel-derived CRF mapping

Python, Node.js and Tesseract do not need separate installation. Docker Desktop
is not redistributed because its license restricts third-party transfer. The
recipient must obtain Docker Desktop from Docker, accept its terms and ensure
that their organization has the required Docker subscription.

Files created after first start
-------------------------------
- data\companion.db
- data\uploads\
- .runtime\backups\
- current-user protected Kimi and LibreClinica credential artifacts
- .runtime\portable-host-diagnostic.json without credentials or raw Docker errors
- package-scoped Docker volumes containing this computer's synthetic EDC data

Safety boundary
---------------
This package is for synthetic localhost qualification only. Do not upload real
participant material. It is not a validated EDC or production deployment. Kimi
receives only de-identified derivatives that pass the existing privacy gate.
LibreClinica is the authority record and receives reviewed values through SOAP;
the companion never writes clinical tables directly.

Integrity
---------
MANIFEST.sha256 lists the SHA-256 digest of every distributed file except the
manifest itself. The build is unsigned; Windows may display a SmartScreen
warning. Institutional distribution requires code signing, security and
license/SBOM review, formal validation and approved Kimi/Docker terms.

Open-source license
-------------------
This software is licensed under GNU AGPL v3 only. See LICENSE for the complete
terms and SOURCE-CODE.txt for the corresponding source location.
