# GitHub landscape and reuse recommendations

**Evidence cut-off:** 2026-08-13  
**Product:** ClinData Relay  
**Scope:** first-party repositories, first-party documentation, release pages, and repository metadata only. This is an engineering landscape review, not a legal opinion, clinical validation, vendor qualification, or authorization to process participant data.

## Executive decision

Keep the current product boundary and architecture: LibreClinica remains the authority EDC, while the FastAPI/SQLite companion performs local preparation, de-identification review, OCR/Kimi-assisted candidate creation, human review, frozen-package submission, reconciliation, and Excel export.

The strongest reusable ideas are not whole replacement products. They are:

1. ODK's versioned-form, offline-submission, resumable-transfer, and server-audit patterns.
2. Docling's typed document graph and page/bounding-box provenance.
3. PaddleOCR's multilingual, layout-aware OCR as an optional benchmarked engine behind the existing extraction contract.
4. OpenTelemetry's vendor-neutral trace and metric vocabulary, initially exported locally with sensitive attributes suppressed.
5. PyInstaller's native-per-platform build discipline, software-bill-of-materials checks, and black-box packaged-artifact tests.

Do **not** replace the application with OpenClinica CE, OpenMRS, ODK Central, or `clinicedc`; do **not** add Celery/Redis to the local single-user product; and do **not** integrate Surya until its code and model-weight licensing is resolved in writing.

## Selection criteria

Projects were assessed for:

- fit with a multi-centre investigator-initiated study;
- local/offline operation and recipient installation cost;
- explicit APIs and stable data contracts;
- auditability, idempotency, role isolation, and evidence provenance;
- Chinese report/PDF/image extraction relevance;
- license and model-weight distribution risk;
- maintenance signal visible in an official release or repository page.

GitHub activity is only a maintenance signal. It does not prove security, regulatory compliance, fitness for clinical use, or long-term support.

## EDC and clinical-data platforms

| Project | License and maintenance signal | Reusable capability | Integration cost | Decision and clinical boundary |
| --- | --- | --- | --- | --- |
| [LibreClinica](https://github.com/reliatec-gmbh/LibreClinica) | LGPL-3.0. The [official download page](https://www.libreclinica.org/download.html) lists LibreClinica 1.4 with Tomcat 9, OpenJDK 11, and PostgreSQL 16; GitHub repository metadata showed a push on 2026-08-13 when checked. | ODM/SOAP submission, study/event/CRF identifiers, roles, audit trail, queries, freeze/lock workflows. | Low for this product because an adapter and sandbox already exist; high for production qualification and operational support. | **Keep as authority EDC.** Continue supported-interface writes and read-back reconciliation. Never write its database tables directly. The current `1.4.0` versus embedded `1.4.0rc1` discrepancy remains a qualification warning. |
| [OpenClinica Community Edition](https://github.com/OpenClinica/OpenClinica) | GNU LGPL according to the repository. The official release page still exposes tag [3.17.2](https://github.com/OpenClinica/OpenClinica/releases/tag/3.17.2) as the latest CE release signal. | Mature CRF, visit, edit-check, audit, signature, import/export, and role concepts. | Very high: overlapping Java stack, database, UI, validation, and study configuration. | **Reference only.** LibreClinica is already the selected successor/authority path. Running two authority EDCs would create reconciliation and governance ambiguity. |
| [clinicedc](https://github.com/clinicedc/clinicedc) and the retired modular [edc repository](https://github.com/clinicedc/edc) | GPL-3.0. The official `edc` README states that development moved to the consolidated `clinicedc` monorepo and currently targets Python 3.12+, Django 5.2+, and MySQL 8+. | Longitudinal visit schedules, subject requisitions, data-review workflow, and trial-specific form composition. | High: adopting it means a Django/MySQL rewrite and GPL distribution review. | **Borrow domain concepts and test cases only.** Do not embed or migrate. Its eSource orientation does not replace the present LibreClinica authority boundary. |
| [ODK Central](https://github.com/getodk/central) and [ODK Collect](https://github.com/getodk/collect) | Apache-2.0. Central published [v2026.1.0](https://github.com/getodk/central/releases); Collect documents an approximately 2–3 month release cycle and operation in unreliable-connectivity environments. | Versioned forms, offline-first capture, submission attachments, resumable synchronization, server audit logs, REST/OpenRosa/OData APIs, and clear stable/development branches. | Medium to high if deployed; low if only its state-machine and API patterns are copied. | **Reuse patterns, not the server.** Add explicit upload/prepare/extract/review/submit state transitions and resumable client-visible receipts. ODK forms are not a substitute for trial CRFs, queries, SDV, signatures, freeze, or lock. |
| [OpenMRS Core](https://github.com/openmrs/openmrs-core) | MPL-2.0 plus the OpenMRS Healthcare Disclaimer. The official repositories page showed `openmrs-core` updated on 2026-07-29; the [official download page](https://openmrs.org/download/) lists Platform 2.8.1 released 2025-10-07 and Reference Application 3.7.1 released 2026-07-13. | Modular clinical concepts, REST/FHIR integration, patient identifiers, encounter/observation modelling, and operational dashboards. | Very high: Java/Tomcat, EMR data model, modules, concepts, and separate governance. | **Do not adopt as an EDC.** OpenMRS is an EMR. Consider a future FHIR export adapter only when a hospital integration is explicitly approved; do not let an EMR identifier become the companion's pseudonymous study ID. |

### EDC conclusion

No reviewed repository justifies replacing LibreClinica or rebuilding the companion on another framework. The useful next step is a capability matrix for each authority adapter: subject provisioning, visit scheduling, value submission, read-back, query visibility, signature/freeze/lock visibility, idempotency behavior, and unsupported states. Each unsupported capability must remain visible and fail closed.

## OCR and document-structure projects

| Project | License and maintenance signal | Reusable capability | Integration cost | Decision and data boundary |
| --- | --- | --- | --- | --- |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Apache-2.0; [v3.7.0](https://github.com/PaddlePaddle/PaddleOCR/releases/tag/v3.7.0) was released 2026-06-11. | Chinese and multilingual recognition, orientation, layout/table pipelines, local JSON/Markdown output, and bounding boxes. | Medium to high: Paddle runtime, model files, larger package, CPU/RAM tests, model/dependency licenses, and native packaging on Windows/macOS. | **Best optional OCR candidate.** Put it behind the current extractor interface and enable it only after a synthetic gold-set comparison. It must receive only a human-confirmed de-identified derivative, remain local, and never bypass deterministic field validation or human review. |
| [docTR](https://github.com/mindee/doctr) | Apache-2.0; [v1.0.1](https://github.com/mindee/doctr/releases/tag/v1.0.1) was released 2026-02-04. Version 1 uses PyTorch; current development documentation targets Python 3.11+. | Multi-page inputs, rotated geometry, nested block/line/word JSON, KIE-style multi-class detection, orientation, and model replacement. | High for the portable product because PyTorch and model artifacts materially enlarge the package; KIE also requires labeled data and training. | **Benchmark alternative, not a default dependency.** It is useful as a second engine or later supervised-training path, but PaddleOCR has the stronger out-of-box Chinese-product fit. |
| [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) | MPL-2.0. Its official release page shows [v17.8.1](https://github.com/ocrmypdf/OCRmyPDF/releases/tag/v17.8.1) released 2026-07-17. | Detecting textless/scanned PDFs, deskew/rotate/clean preprocessing, adding a searchable text layer, sidecar text, PDF/A options, and a public API. | Medium to high: Tesseract, Ghostscript or other native PDF components complicate Windows/macOS redistribution. | **Not a field extractor.** Keep it out of the main recognition chain. Consider it later only for an optional searchable archival derivative, with source preservation and a separate retention policy. Its [official security guidance](https://ocrmypdf.readthedocs.io/en/stable/pdfsecurity.html) also requires treating PDFs as potentially hostile. |
| [Docling](https://github.com/docling-project/docling) | MIT for the codebase, with individual model licenses requiring separate review. [v2.119.0](https://github.com/docling-project/docling/releases/tag/v2.119.0) was released 2026-08-10. | Native-text/OCR mixing, typed document graph, tables, reading order, page/bounding-box provenance, controlled serializers, size/depth budgets, and structured JSON recovery artifacts. | High as a full runtime; low to reuse its output-contract ideas. Rapid release cadence makes version/model pinning and contract tests essential. | **Reuse the schema pattern first.** Add a small internal evidence graph rather than importing Docling now. Benchmark it only for complex tables/layouts that fail the deterministic pulmonary parser and local OCR. Its [official FAQ](https://github.com/docling-project/docling/blob/main/docs/faq/index.md) supports offline use only after models are pre-fetched and local artifact paths are configured. |
| [Surya](https://github.com/datalab-to/surya) | **License ambiguity:** the official README states that code is GPL and model weights use a modified AI Pubs OpenRAIL-M license with commercial thresholds, while GitHub's repository license display reports Apache-2.0. The repository lists `Surya OCR 2` released 2026-05-27. | OCR, layout, reading order, tables, and 90+ languages. | High: PyTorch/model downloads, GPU-preferred workloads, distribution terms, and license review. | **Do not integrate.** A repository badge is not sufficient to resolve the README's code/weight terms. Reconsider only after legal review identifies the exact source and weight licenses for the pinned artifacts. |

### OCR implementation pattern to adopt

Use one versioned engine-neutral result contract for every extractor:

```json
{
  "engine": "paddleocr",
  "engine_version": "pinned-version",
  "model_ids": ["pinned-model"],
  "source_sha256": "...",
  "derivative_sha256": "...",
  "pages": [
    {
      "page": 1,
      "width": 2480,
      "height": 3508,
      "spans": [
        {
          "text": "FEV1",
          "bbox": [100, 200, 240, 250],
          "engine_score": 0.93
        }
      ]
    }
  ],
  "warnings": []
}
```

`engine_score` is evidence metadata, not clinical confidence. Candidate acceptance still depends on the active field dictionary, deterministic value/unit/range checks, visible evidence, and authorized human review.

## Job execution, observability, and offline packaging

| Project | Signal | Pattern worth reusing | Decision |
| --- | --- | --- | --- |
| [Huey](https://github.com/coleifer/huey) | MIT; [v3.2.1](https://github.com/coleifer/huey/releases/tag/v3.2.1) was released 2026-07-09. | A small separate consumer with `SqliteHuey`, retries, locks, results, and timeouts, without requiring Redis. | **Conditional next step only when recognition must continue after the browser/request closes.** Keep the companion job ledger authoritative; enqueue only opaque job/item IDs, never image bytes, OCR text, values, or participant identifiers. Official Huey documentation warns that an executing task may be lost on abrupt power loss, so idempotent recovery remains necessary. |
| [Celery](https://github.com/celery/celery) | New BSD; [v5.6.3](https://github.com/celery/celery/releases/tag/v5.6.3) released 2026-03-26. | Broker-backed workers, retries, routing, scheduling, and failure handling for a real central multi-worker deployment. | **Do not add to Lite/local mode.** Redis/RabbitMQ and worker supervision would increase installation and failure modes. Reassess only when a qualified central PostgreSQL deployment has concurrent workers and measured queue pressure. |
| [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python) | Apache-2.0; [v1.44.0/0.65b0](https://github.com/open-telemetry/opentelemetry-python/releases/tag/v1.44.0) released 2026-07-16. Traces and metrics are stable; logs remain under development. | Trace IDs across prepare/extract/review/submit/reconcile, duration/error counters, and exporter-independent instrumentation. | **Next, locally and minimally.** Start with local metrics and structured diagnostic export. Never record report text, values, identifiers, file paths, raw provider errors, tokens, or credentials as attributes. Remote export stays disabled pending institutional approval. |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | GPL-2.0-or-later with bootloader exception; [v6.20.0](https://github.com/pyinstaller/pyinstaller/releases/tag/v6.20.0) released 2026-04-22. Official documentation confirms it is not a cross-compiler. | Self-contained Python application builds and native per-platform packaging. | **Keep.** Continue native Windows/macOS builds, dependency-license collection, signed/notarized release artifacts, and black-box tests against the packaged executable rather than source-only tests. |
| [pywebview](https://github.com/r0x0r/pywebview) | BSD; [v6.2.1](https://github.com/r0x0r/pywebview/releases/tag/v6.2.1) was released 2026-04-15. | A native Windows WebView2/macOS Cocoa window around the existing HTML/CSS/JavaScript UI, without an Electron runtime. | **Evaluate for Lite only.** It may improve recipient experience while retaining the FastAPI/web UI code. Keep browser mode as a fallback and black-box test both Windows and macOS packages. |
| [Briefcase](https://github.com/beeware/briefcase) | BSD-3-Clause; [0.4.2](https://github.com/beeware/briefcase/releases/tag/v0.4.2) released 2026-05-06. | Platform-native application installers across desktop and mobile. | **Later evaluation only.** It may improve native installer UX, but migrating packaging does not improve OCR or clinical integrity and would duplicate the now-working PyInstaller path. |
| [Tauri](https://github.com/tauri-apps/tauri) | MIT or Apache-2.0. Its official architecture document requires builds on the target OS and supports signed updates. | Signed native shell, constrained webview permissions, updater signatures, and platform installers. | **Do not introduce now.** It would add Rust/Node/webview build systems and a second application shell without removing the Python OCR runtime. Borrow only its signed-update and least-privilege concepts. |

## Prioritized development recommendations

### Must

1. **Freeze a document-evidence contract.** Store engine/model versions, source and derivative hashes, page dimensions, spans, bounding boxes, preprocessing steps, warnings, selected field-dictionary release, and extraction duration. Keep raw source bytes outside the result contract.
2. **Create a representative synthetic gold corpus.** Include born-digital pulmonary PDFs, scanned PDFs, phone photos, rotated/blurred pages, Chinese/English mixed labels, decimal and unit confusions, multi-page uploads, direct identifiers, duplicate files, encrypted PDFs, and malformed inputs. Record field precision/recall, exact numeric match, unit match, false-positive rate, redaction misses, runtime, RAM, and artifact size per pinned engine.
3. **Make extraction idempotent by contract.** Derive a request key from derivative hash, dictionary release, selected fields, extractor/model version, and preprocessing version. A retry must reuse or supersede an attempt explicitly; it must not silently duplicate candidates.
4. **Add an adapter capability/read-back matrix.** Expose supported, unsupported, deferred, and failed states separately for LibreClinica operations. Do not convert an unsupported read-back into success.
5. **Produce a machine-readable third-party manifest for every package.** Include Python packages, native binaries, OCR model files, source URL, exact version/hash, license, and redistribution evidence. This is required before adding any deep-learning OCR engine.
6. **Keep all clinical gates.** De-identification confirmation, field whitelist, deterministic checks, human review, frozen package, explicit submission, and authority read-back remain mandatory regardless of OCR engine accuracy.

### Next

1. Implement an `Extractor` boundary with the current Tesseract/text-layer parsers as defaults and a feature-gated PaddleOCR adapter. Do not change candidate or review APIs when swapping engines.
2. Run PaddleOCR versus the current pipeline on the gold corpus. Ship it only if the measured improvement justifies installation size, cold-start time, RAM, and macOS/Windows support.
3. Add a scanned-PDF classifier. Route born-digital PDFs to the deterministic text parser, scanned PDFs to page rendering plus local OCR, and mixed PDFs page by page. Preserve sources and record every transformation.
4. Add privacy-safe local observability: job duration, queue age, retries, cancellation, per-engine failure codes, candidate counts, reviewer edits, and reconciliation latency. Use correlation IDs already suitable for audit, not participant identifiers.
5. Add a human-readable extraction evidence viewer: page thumbnail/crop, recognized token, candidate value/unit, engine agreement/conflict, and dictionary rule that allowed or blocked it.
6. Add a clean-machine upgrade/rollback test for Windows and native macOS artifacts, including data-directory compatibility and an offline restore check.
7. If recognition must survive browser closure, evaluate a single `SqliteHuey` consumer and PyInstaller `onedir` plus pywebview for Lite; preserve the current database ledger and browser fallback.

### Later

1. Evaluate PostgreSQL plus a separately supervised worker only for a qualified multi-user central deployment. Preserve the same job state machine and atomic claim semantics.
2. Evaluate Docling for difficult layouts/tables after the compact PaddleOCR experiment, using the same gold set and output contract.
3. Evaluate OpenTelemetry export to an institution-managed collector only after privacy/security approval and a documented attribute allowlist.
4. Add FHIR export only for a named hospital integration with approved identifier mapping and consent/data-flow governance. This does not make OpenMRS an EDC dependency.
5. Reassess Briefcase only if signed installer UX or enterprise deployment tooling becomes a measured distribution blocker.

### Do not

1. Do not replace LibreClinica with another EDC/EMR or run two authority databases for the same study workflow.
2. Do not add Celery, Redis, RabbitMQ, Kafka, Kubernetes, Electron, Tauri, or a Java/Django framework to the local/Lite product without a measured requirement.
3. Do not send raw participant reports to any hosted OCR/LLM service, including hosted demos exposed by open-source projects.
4. Do not treat OCR/model confidence as clinical confidence or auto-accept a value solely because two models agree.
5. Do not integrate Surya or any model whose source, weight, or transitive dependency license is unresolved for the intended distribution.
6. Do not overwrite source files with deskewed, redacted, OCR-layered, or compressed derivatives.
7. Do not train or fine-tune on participant reports until consent, ethics, retention, governance, de-identification, and model-release controls are approved.
8. Do not claim Part 11, GCP, GDPR/PIPL, hospital-security, or clinical validation based on repository features or synthetic tests.

## Recommended sequence

The shortest reliable path is:

1. evidence contract and idempotency key;
2. synthetic gold corpus and baseline metrics;
3. optional PaddleOCR adapter behind the existing seam;
4. evidence viewer and local operational metrics;
5. packaged-artifact/SBOM qualification;
6. only then consider a central worker, Docling, FHIR, or alternative packaging.

This sequence improves accuracy, auditability, and recipient usability without changing the authority EDC or multiplying infrastructure prematurely.

## Primary-source index

- LibreClinica: [repository](https://github.com/reliatec-gmbh/LibreClinica), [official download and system requirements](https://www.libreclinica.org/download.html), [official documentation](https://www.libreclinica.org/documentation/)
- OpenClinica CE: [repository](https://github.com/OpenClinica/OpenClinica), [releases](https://github.com/OpenClinica/OpenClinica/releases)
- clinicedc: [monorepo](https://github.com/clinicedc/clinicedc), [retired modular repository and migration notice](https://github.com/clinicedc/edc)
- ODK: [Central](https://github.com/getodk/central), [Central releases](https://github.com/getodk/central/releases), [Collect](https://github.com/getodk/collect), [Central introduction](https://docs.getodk.org/central-intro/)
- OpenMRS: [Core](https://github.com/openmrs/openmrs-core), [downloads/releases](https://openmrs.org/download/), [REST module](https://github.com/openmrs/openmrs-module-webservices.rest), [FHIR2 module](https://github.com/openmrs/openmrs-module-fhir2)
- OCR: [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), [docTR](https://github.com/mindee/doctr), [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF), [Docling](https://github.com/docling-project/docling), [Surya](https://github.com/datalab-to/surya)
- Operations and packaging: [Huey](https://github.com/coleifer/huey), [Celery](https://github.com/celery/celery), [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python), [PyInstaller](https://github.com/pyinstaller/pyinstaller), [pywebview](https://github.com/r0x0r/pywebview), [Briefcase](https://github.com/beeware/briefcase), [Tauri architecture](https://github.com/tauri-apps/tauri/blob/dev/ARCHITECTURE.md)
