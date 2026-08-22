# Build the Lite runtime natively for each macOS architecture

**Status: accepted.** Apple computers need the same Docker-free report extraction, human review and Excel workflow as Windows. The application will keep one shared Lite domain/runtime implementation and add a native macOS packaging boundary rather than creating a second product fork.

PyInstaller is not a cross-compiler, so Windows cannot produce or qualify a macOS executable. Separate `arm64` and `x86_64` builds run on matching macOS hosts and must each pass the existing synthetic PDF-to-review-to-Excel black-box verifier. Runtime state is stored under the user's Application Support directory so the signed application bundle remains immutable.

Ad-hoc signatures are internal QA artifacts only. External double-click distribution requires the owner's Apple Developer ID and notarization. Those credentials remain outside source control and are referenced only through an installed signing identity and Keychain profile during a native macOS build.
