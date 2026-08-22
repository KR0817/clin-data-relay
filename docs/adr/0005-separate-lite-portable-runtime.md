# Ship a separate local-only Lite runtime

**Status: accepted.** The integrated LibreClinica package remains necessary for Authority-EDC interface qualification, but Docker Desktop, WSL2 and the Linux engine create an avoidable recipient burden when the actual task is only report extraction, human review, local persistence and Excel export. A separate Lite distribution will therefore reuse the companion's existing deep modules while selecting a local-only launcher and presentation adapter.

Lite is not another EDC and is not a fork of the recognition implementation. It forces the fail-closed simulation adapter, removes Authority submission controls from the interface and excludes all Docker/LibreClinica assets from its archive. This keeps the recipient workflow to extract and double-click without weakening the integrated package or implying that locally reviewed values reached LibreClinica.
