"""Generate deterministic, identifier-free Benchmark v1 source materials."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf._page import PageObject
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject


SEED = 20260901
ALLOCATION_SCHEMA = "clin-data-relay-benchmark-allocation-v1"
CONSTRUCTION_SCHEMA = "clin-data-relay-construction-truth-v1"
ANNOTATION_SCHEMA = "clin-data-relay-annotation-template-v1"
CHALLENGE_TEMPLATES = {
    "clear_scan": ("synthetic_lab_image", "lab_table_clear_v1"),
    "low_dpi_skew": ("synthetic_lab_image", "lab_table_mobile_v1"),
    "vendor_reprint_layout": ("synthetic_lab_image", "lab_vendor_reprint_v1"),
    "margin_handwritten_annotation": ("synthetic_lab_image", "lab_margin_annotation_v1"),
    "reference_boundary_value": ("synthetic_lab_image", "lab_reference_boundary_v1"),
    "cross_centre_unit_variant": ("synthetic_lab_image", "lab_unit_variant_v1"),
    "star_or_footnote_marker": ("synthetic_lab_image", "lab_footnote_v1"),
    "multipage_pulmonary": ("synthetic_pulmonary_pdf", "pulmonary_multipage_v1"),
}

# code, unit, low, high, decimals
LAB_FIELDS = (
    ("WBC", "10E9/L", 3.5, 9.5, 2),
    ("RBC", "10E12/L", 3.8, 5.8, 2),
    ("HB", "g/L", 115.0, 175.0, 0),
    ("PLT", "10E9/L", 125.0, 350.0, 0),
    ("ALT", "U/L", 9.0, 50.0, 0),
    ("AST", "U/L", 15.0, 40.0, 0),
    ("TBIL", "umol/L", 3.4, 20.5, 1),
    ("GGT", "U/L", 7.0, 45.0, 0),
    ("ALB", "g/L", 40.0, 55.0, 1),
    ("CR", "umol/L", 44.0, 97.0, 0),
    ("BUN", "mmol/L", 2.8, 7.9, 1),
    ("K", "mmol/L", 3.5, 5.3, 1),
    ("NA", "mmol/L", 137.0, 147.0, 0),
    ("CA", "mmol/L", 2.1, 2.6, 2),
    ("ESR", "mm/h", 0.0, 20.0, 0),
    ("CRP", "mg/L", 0.0, 8.0, 1),
    ("IGG", "g/L", 7.0, 16.0, 2),
    ("IGA", "g/L", 0.7, 4.0, 2),
    ("IGM", "g/L", 0.4, 2.3, 2),
    ("RF", "IU/mL", 0.0, 20.0, 1),
    ("C3", "g/L", 0.9, 1.8, 2),
    ("C4", "g/L", 0.1, 0.4, 2),
)
UNIT_VARIANTS = {
    "CR": ("mg/dL", 0.5, 1.2, 2),
    "BUN": ("mg/dL", 7.8, 22.1, 1),
    "K": ("mEq/L", 3.5, 5.3, 1),
    "NA": ("mEq/L", 137.0, 147.0, 0),
    "CA": ("mg/dL", 8.4, 10.2, 1),
    "TBIL": ("mg/dL", 0.2, 1.2, 2),
}


class CorpusError(ValueError):
    """Raised when a corpus cannot be generated under the frozen contract."""


def _encoded_json(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _encoded_jsonl(records: list[dict[str, object]]) -> bytes:
    return b"".join(
        (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for record in records
    )


def _artifact(root: Path, path: Path, **metadata: object) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        **metadata,
    }


def _randomizer(report_id: str) -> random.Random:
    digest = hashlib.sha256(f"{SEED}:{report_id}".encode("ascii")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _validate_allocation(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        reports = payload["reports"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise CorpusError("benchmark_v1_corpus_allocation_invalid") from error
    if (
        payload.get("schema_version") != ALLOCATION_SCHEMA
        or payload.get("benchmark_id") != "synthetic-benchmark-v1"
        or payload.get("purpose") != "EXPERIMENT_ALLOCATION_ONLY_NOT_RESULTS"
        or payload.get("seed") != SEED
        or not isinstance(reports, list)
        or len(reports) != 150
    ):
        raise CorpusError("benchmark_v1_corpus_allocation_invalid")
    expected_report_keys = {
        "report_id",
        "split",
        "report_type",
        "template_family",
        "primary_challenge",
        "target_field_count",
        "double_review_required",
        "source_status",
    }
    report_ids: set[str] = set()
    split_counts: Counter[str] = Counter()
    locked_challenges: Counter[str] = Counter()
    double_review_count = 0
    for report in reports:
        if not isinstance(report, dict) or set(report) != expected_report_keys:
            raise CorpusError("benchmark_v1_corpus_allocation_invalid")
        report_id = report["report_id"]
        split = report["split"]
        challenge = report["primary_challenge"]
        if (
            not isinstance(report_id, str)
            or report_id in report_ids
            or split not in {"development", "locked_test"}
            or challenge not in CHALLENGE_TEMPLATES
            or (report["report_type"], report["template_family"]) != CHALLENGE_TEMPLATES[challenge]
            or isinstance(report["target_field_count"], bool)
            or not isinstance(report["target_field_count"], int)
            or not 8 <= report["target_field_count"] <= 15
            or not isinstance(report["double_review_required"], bool)
            or report["source_status"] != "not_generated"
            or (report["double_review_required"] and split != "locked_test")
        ):
            raise CorpusError("benchmark_v1_corpus_allocation_invalid")
        report_ids.add(report_id)
        split_counts[split] += 1
        if split == "locked_test":
            locked_challenges[challenge] += 1
        double_review_count += int(report["double_review_required"])
    if (
        split_counts != Counter({"development": 30, "locked_test": 120})
        or locked_challenges != Counter({challenge: 15 for challenge in CHALLENGE_TEMPLATES})
        or double_review_count != 30
    ):
        raise CorpusError("benchmark_v1_corpus_allocation_invalid")
    return payload


def _validate_lab_field_codes() -> None:
    mapping_path = (
        Path(__file__).resolve().parent.parent / "config" / "synthetic_lab_mapping.v0.1.json"
    )
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        allowed = {str(code) for code in mapping["events"]["WEEK_0"]["allowed_field_codes"]}
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise CorpusError("benchmark_v1_corpus_dictionary_invalid") from error
    if not {field[0] for field in LAB_FIELDS}.issubset(allowed):
        raise CorpusError("benchmark_v1_corpus_dictionary_invalid")


def _format_number(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _lab_rows(report: dict[str, object]) -> list[dict[str, object]]:
    randomizer = _randomizer(str(report["report_id"]))
    target = int(report["target_field_count"])
    selected = list(randomizer.sample(LAB_FIELDS, target))
    challenge = str(report["primary_challenge"])
    if challenge == "cross_centre_unit_variant" and not any(item[0] in UNIT_VARIANTS for item in selected):
        replacement = next(item for item in LAB_FIELDS if item[0] == "CR")
        selected[-1] = replacement
    rows: list[dict[str, object]] = []
    for index, (code, unit, low, high, decimals) in enumerate(selected):
        if challenge == "cross_centre_unit_variant" and code in UNIT_VARIANTS:
            unit, low, high, decimals = UNIT_VARIANTS[code]
        scale = 10**decimals
        low_step = round(low * scale)
        high_step = round(high * scale)
        if challenge == "reference_boundary_value" and index == 0:
            value_step = low_step if randomizer.randrange(2) == 0 else high_step
        else:
            value_step = randomizer.randint(low_step, high_step)
        display_label = f"*{code}" if challenge == "star_or_footnote_marker" and index < 2 else code
        rows.append(
            {
                "field_code": code,
                "displayed_label": display_label,
                "value": _format_number(value_step / scale, decimals),
                "comparator": "",
                "unit": unit,
                "reference_interval": f"{_format_number(low, decimals)}-{_format_number(high, decimals)}",
                "page_number": 1,
            }
        )
    return rows


def _default_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _normalized_region(x: int, y: int, width: int, height: int, image: Image.Image) -> list[float]:
    return [
        round(x / image.width, 6),
        round(y / image.height, 6),
        round(width / image.width, 6),
        round(height / image.height, 6),
    ]


def _render_lab_image(report: dict[str, object], rows: list[dict[str, object]]) -> tuple[bytes, list[dict[str, object]]]:
    challenge = str(report["primary_challenge"])
    compact = challenge == "low_dpi_skew"
    width, height = (900, 700) if compact else (1600, 1000)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _default_font(26 if compact else 38)
    body_font = _default_font(20 if compact else 30)
    small_font = _default_font(16 if compact else 22)
    draw.text((40, 24), f"SYNTHETIC REPORT {report['report_id']}", fill=(18, 36, 60), font=title_font)
    draw.text((40, 62 if compact else 76), "NO PATIENT DATA", fill=(100, 100, 100), font=small_font)

    evidence: dict[str, list[float]] = {}
    if challenge == "vendor_reprint_layout":
        column_width = 760
        top = 145
        row_height = 88
        split_at = (len(rows) + 1) // 2
        for column in range(2):
            x = 35 + column * column_width
            draw.rectangle((x, top - 42, x + 720, top - 4), fill=(40, 58, 80))
            draw.text((x + 12, top - 38), "ANALYTE   UNIT   RESULT   REFERENCE", fill="white", font=small_font)
        for index, row in enumerate(rows):
            column = 0 if index < split_at else 1
            position = index if column == 0 else index - split_at
            x = 35 + column * column_width
            y = top + position * row_height
            draw.text((x + 12, y), str(row["displayed_label"]), fill="black", font=body_font)
            draw.text((x + 200, y), str(row["unit"]), fill="black", font=small_font)
            draw.text((x + 390, y), str(row["value"]), fill="black", font=body_font)
            draw.text((x + 520, y), str(row["reference_interval"]), fill="black", font=small_font)
            evidence[str(row["field_code"])] = _normalized_region(x, y - 5, 720, row_height - 8, image)
    else:
        top = 145 if compact else 165
        row_height = 34 if compact else 49
        positions = (40, 260, 430, 650) if compact else (70, 470, 730, 1080)
        draw.rectangle((positions[0] - 12, top - row_height, width - 45, top - 5), fill=(35, 55, 78))
        for text, x in zip(("TEST", "RESULT", "REFERENCE", "UNIT"), positions, strict=True):
            draw.text((x, top - row_height + 3), text, fill="white", font=small_font)
        for index, row in enumerate(rows):
            y = top + index * row_height
            draw.text((positions[0], y), str(row["displayed_label"]), fill="black", font=body_font)
            draw.text((positions[1], y), str(row["value"]), fill="black", font=body_font)
            draw.text((positions[2], y), str(row["reference_interval"]), fill="black", font=small_font)
            draw.text((positions[3], y), str(row["unit"]), fill="black", font=small_font)
            draw.line((positions[0], y + row_height - 5, width - 55, y + row_height - 5), fill=(220, 225, 230))
            evidence[str(row["field_code"])] = _normalized_region(
                positions[0] - 8, y - 3, width - positions[0] - 45, row_height, image
            )
        if challenge == "margin_handwritten_annotation":
            draw.text((width - 260, height - 90), "CHECK AGAIN", fill=(80, 90, 120), font=small_font)
        if challenge == "star_or_footnote_marker":
            draw.text((40, height - 55), "* instrument flag; result value unchanged", fill=(80, 80, 80), font=small_font)

    if compact:
        image = image.rotate(2.0, resample=Image.Resampling.BICUBIC, expand=False, fillcolor="white")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    construction_rows = [
        {
            **row,
            "evidence_region": None
            if challenge == "low_dpi_skew"
            else evidence[str(row["field_code"])],
        }
        for row in rows
    ]
    return output.getvalue(), construction_rows


def _load_pulmonary_fields() -> list[dict[str, object]]:
    path = Path(__file__).resolve().parent.parent / "config" / "pulmonary-function-field-dictionary.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(item) for item in payload["fields"]]


def _pulmonary_rows(report: dict[str, object]) -> tuple[list[str], list[dict[str, object]], list[int]]:
    definitions = _load_pulmonary_fields()
    by_code = {str(item["field_code"]): item for item in definitions}
    paired_codes = {"PFT_FEV1", "PFT_FEV1_MEASURED_PREDICTED_PERCENT"}
    others = [item for item in definitions if item["field_code"] not in paired_codes]
    randomizer = _randomizer(str(report["report_id"]))
    target = int(report["target_field_count"])
    selected_codes = paired_codes | {
        str(item["field_code"]) for item in randomizer.sample(others, target - len(paired_codes))
    }
    selected = [item for item in definitions if item["field_code"] in selected_codes]
    fev_definition = by_code["PFT_FEV1"]
    row_groups: list[list[dict[str, object]]] = []
    used_codes: set[str] = set()
    for definition in selected:
        code = str(definition["field_code"])
        if code in used_codes:
            continue
        if code in paired_codes:
            row_groups.append([fev_definition, by_code["PFT_FEV1_MEASURED_PREDICTED_PERCENT"]])
            used_codes.update(paired_codes)
        else:
            row_groups.append([definition])
            used_codes.add(code)

    split_at = max(1, len(row_groups) // 2)
    page_numbers = [1 if index < split_at else 2 for index in range(len(row_groups))]
    lines: list[str] = []
    construction: list[dict[str, object]] = []
    for group_index, group in enumerate(row_groups):
        definition = group[0]
        label = str(definition["report_labels"][0])
        if definition["value_selector"] == "single":
            value = f"{randomizer.uniform(0.04, 0.35):.2f}"
            line = f"{label} {value}"
            values = {str(definition["field_code"]): value}
        else:
            predicted = randomizer.uniform(0.8, 8.5)
            measured = predicted * randomizer.uniform(0.55, 1.25)
            predicted_text = f"{predicted:.2f}"
            measured_text = f"{measured:.2f}"
            percent_text = f"{measured / predicted * 100:.1f}"
            line = f"{label} {predicted_text} {measured_text} {percent_text}"
            values = {str(definition["field_code"]): measured_text}
            if len(group) == 2:
                values["PFT_FEV1_MEASURED_PREDICTED_PERCENT"] = percent_text
        lines.append(line)
        for item in group:
            code = str(item["field_code"])
            construction.append(
                {
                    "field_code": code,
                    "displayed_label": label,
                    "value": values[code],
                    "comparator": "",
                    "unit": str(item.get("unit") or ""),
                    "reference_interval": "",
                    "page_number": page_numbers[group_index],
                    "evidence_region": None,
                }
            )
    return lines, construction, page_numbers


def _pdf_page(writer: PdfWriter, font_reference: object, lines: list[str], page_number: int) -> PageObject:
    page = PageObject.create_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    commands = ["BT", "/F1 11 Tf", "48 744 Td", "18 TL"]
    header = [f"SYNTHETIC PULMONARY REPORT - PAGE {page_number}", "NO PATIENT DATA", "Predicted Measured Percent"]
    for line in header + lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.extend((f"({escaped}) Tj", "T*"))
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    page[NameObject("/MediaBox")] = ArrayObject(page[NameObject("/MediaBox")])
    return page


def _render_pulmonary_pdf(report: dict[str, object]) -> tuple[bytes, list[dict[str, object]]]:
    lines, construction, page_numbers = _pulmonary_rows(report)
    writer = PdfWriter()
    writer.add_metadata({"/Producer": "ClinData Relay synthetic benchmark generator v1"})
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    for page_number in (1, 2):
        page_lines = [line for line, assigned_page in zip(lines, page_numbers, strict=True) if assigned_page == page_number]
        writer.add_page(_pdf_page(writer, font_reference, page_lines, page_number))
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue(), construction


def _construction_record(
    report: dict[str, object], source_path: Path, fields: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schema_version": CONSTRUCTION_SCHEMA,
        "benchmark_id": "synthetic-benchmark-v1",
        "report_id": report["report_id"],
        "visit_ref": "BASELINE",
        "report_type": report["report_type"],
        "challenge_classes": [report["primary_challenge"]],
        "privacy_gate_expected": "allow",
        "source_relative_path": source_path.as_posix(),
        "construction_method": report["template_family"],
        "fields": fields,
        "reporting_boundary": "CONSTRUCTION_TRUTH_NOT_ADJUDICATED_GOLD",
    }


def _annotation_templates(
    locked_reports: list[dict[str, object]], source_paths: dict[str, Path]
) -> dict[str, list[dict[str, object]]]:
    assignments: dict[str, set[str]] = {"reviewer_a": set(), "reviewer_b": set()}
    non_double = sorted(
        (report for report in locked_reports if not report["double_review_required"]),
        key=lambda report: str(report["report_id"]),
    )
    for index, report in enumerate(non_double):
        assignments["reviewer_a" if index % 2 == 0 else "reviewer_b"].add(str(report["report_id"]))
    double_ids = {
        str(report["report_id"]) for report in locked_reports if report["double_review_required"]
    }
    assignments["reviewer_a"].update(double_ids)
    assignments["reviewer_b"].update(double_ids)
    report_by_id = {str(report["report_id"]): report for report in locked_reports}
    return {
        reviewer: [
            {
                "schema_version": ANNOTATION_SCHEMA,
                "benchmark_id": "synthetic-benchmark-v1",
                "report_id": report_id,
                "visit_ref": "BASELINE",
                "reviewer_slot": reviewer,
                "source_relative_path": source_paths[report_id].as_posix(),
                "double_review_required": bool(report_by_id[report_id]["double_review_required"]),
                "annotation_status": "not_started",
                "fields": [],
                "reporting_boundary": "VALUE_FREE_TEMPLATE_NOT_ANNOTATION",
            }
            for report_id in sorted(report_ids)
        ]
        for reviewer, report_ids in assignments.items()
    }


def generate_corpus(allocation_path: Path, output_dir: Path) -> dict[str, int | str]:
    if output_dir.exists():
        raise CorpusError("benchmark_v1_corpus_output_exists")
    allocation = _validate_allocation(allocation_path)
    _validate_lab_field_codes()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        source_artifacts: list[dict[str, object]] = []
        construction_by_split: dict[str, list[dict[str, object]]] = {
            "development": [],
            "locked_test": [],
        }
        source_paths: dict[str, Path] = {}
        reports = sorted(allocation["reports"], key=lambda report: str(report["report_id"]))
        for report in reports:
            split = str(report["split"])
            suffix = ".pdf" if report["report_type"] == "synthetic_pulmonary_pdf" else ".png"
            relative_path = Path("sources") / split / f"{report['report_id']}{suffix}"
            destination = temporary / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if suffix == ".pdf":
                content, fields = _render_pulmonary_pdf(report)
                mime_type = "application/pdf"
            else:
                content, fields = _render_lab_image(report, _lab_rows(report))
                mime_type = "image/png"
            if len(fields) != int(report["target_field_count"]):
                raise CorpusError("benchmark_v1_corpus_generation_invalid")
            destination.write_bytes(content)
            source_paths[str(report["report_id"])] = relative_path
            source_artifacts.append(
                _artifact(
                    temporary,
                    destination,
                    report_id=report["report_id"],
                    split=split,
                    report_type=report["report_type"],
                    primary_challenge=report["primary_challenge"],
                    mime_type=mime_type,
                )
            )
            construction_by_split[split].append(
                _construction_record(report, relative_path, fields)
            )

        construction_paths: list[Path] = []
        for split, filename in (("development", "development.jsonl"), ("locked_test", "locked-test.jsonl")):
            path = temporary / "construction-truth" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_encoded_jsonl(construction_by_split[split]))
            construction_paths.append(path)

        locked_reports = [report for report in reports if report["split"] == "locked_test"]
        templates = _annotation_templates(locked_reports, source_paths)
        annotation_paths: list[Path] = []
        for reviewer, filename in (("reviewer_a", "reviewer-a.jsonl"), ("reviewer_b", "reviewer-b.jsonl")):
            path = temporary / "annotation-templates" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_encoded_jsonl(templates[reviewer]))
            annotation_paths.append(path)

        manifest_dir = temporary / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        source_manifest_path = manifest_dir / "source-manifest.json"
        source_manifest_path.write_bytes(
            _encoded_json(
                {
                    "schema_version": "clin-data-relay-source-manifest-v1",
                    "benchmark_id": "synthetic-benchmark-v1",
                    "report_count": len(source_artifacts),
                    "artifacts": source_artifacts,
                    "reporting_boundary": "IDENTIFIER_FREE_SYNTHETIC_SOURCES_NOT_RESULTS",
                }
            )
        )
        construction_manifest_path = manifest_dir / "construction-manifest.json"
        construction_manifest_path.write_bytes(
            _encoded_json(
                {
                    "schema_version": "clin-data-relay-construction-manifest-v1",
                    "benchmark_id": "synthetic-benchmark-v1",
                    "record_count": sum(len(records) for records in construction_by_split.values()),
                    "artifacts": [
                        _artifact(
                            temporary,
                            path,
                            record_count=len(construction_by_split[split]),
                        )
                        for path, split in zip(construction_paths, ("development", "locked_test"), strict=True)
                    ],
                    "reporting_boundary": "CONSTRUCTION_TRUTH_NOT_ADJUDICATED_GOLD",
                }
            )
        )
        annotation_manifest_path = manifest_dir / "annotation-manifest.json"
        annotation_manifest_path.write_bytes(
            _encoded_json(
                {
                    "schema_version": "clin-data-relay-annotation-template-manifest-v1",
                    "benchmark_id": "synthetic-benchmark-v1",
                    "template_count": sum(len(records) for records in templates.values()),
                    "artifacts": [
                        _artifact(temporary, path, record_count=len(templates[reviewer]))
                        for path, reviewer in zip(annotation_paths, ("reviewer_a", "reviewer_b"), strict=True)
                    ],
                    "reporting_boundary": "VALUE_FREE_TEMPLATES_NOT_ANNOTATIONS",
                }
            )
        )
        manifest_path = temporary / "manifest.json"
        manifest_path.write_bytes(
            _encoded_json(
                {
                    "schema_version": "clin-data-relay-benchmark-corpus-package-v1",
                    "benchmark_id": "synthetic-benchmark-v1",
                    "generator_seed": SEED,
                    "artifacts": [
                        _artifact(temporary, path)
                        for path in (
                            source_manifest_path,
                            construction_manifest_path,
                            annotation_manifest_path,
                        )
                    ],
                    "reporting_boundary": "CORPUS_MATERIALS_ONLY_EXPERIMENT_NOT_RUN",
                }
            )
        )
        os.replace(temporary, output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "status": "ok",
        "report_count": 150,
        "construction_record_count": 150,
        "annotation_template_count": 150,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate offline Benchmark v1 source materials.")
    parser.add_argument("--allocation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = generate_corpus(args.allocation, args.output_dir)
    except CorpusError as error:
        print(json.dumps({"status": "error", "code": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
