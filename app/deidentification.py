"""Local, human-reviewed redaction drafts for synthetic laboratory-report fixtures."""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, UnidentifiedImageError

from app.ocr import LocalOcrFailed, LocalOcrUnavailable, LocalTesseractOcr


class LocalDeidentificationUnavailable(RuntimeError):
    """Raised when the local redaction runtime is unavailable."""


class LocalDeidentificationFailed(RuntimeError):
    """Raised when a local redaction draft cannot be produced safely."""


@dataclass(frozen=True)
class LocalRedactionResult:
    detected_marker_codes: tuple[str, ...]
    engine_version: str


DIRECT_IDENTIFIER_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("patient_name", ("姓名", "患者姓名", "patient name")),
    ("inpatient_number", ("住院号", "住院号码", "inpatient no")),
    ("outpatient_number", ("门诊号", "门诊号码", "outpatient no")),
    ("medical_record_number", ("病历号", "病案号", "medical record", "mrn")),
    ("national_id", ("身份证", "证件号", "national id")),
    ("phone_number", ("手机号", "手机", "联系电话", "电话", "phone")),
    ("birth_date", ("出生日期", "出生年月", "date of birth")),
    ("patient_id", ("患者编号", "患者id", "patient id")),
    ("bed_number", ("床号", "床位号", "bed no")),
    ("collecting_clinician", ("送检医生", "送检医师", "requesting physician")),
    ("laboratory_examiner", ("检验者", "检验员", "检验师", "laboratory examiner")),
    ("report_reviewer", ("审核者", "审核员", "审核医师", "report reviewer")),
    ("sample_timestamp", ("采样时间", "采集时间", "sample time")),
    ("receipt_timestamp", ("签收时间", "接收时间", "received time")),
    ("review_timestamp", ("审核时间", "review time")),
)


def _normalise_marker_text(value: str) -> str:
    return re.sub(r"[\s:：_\-]+", "", value).casefold()


class LocalImageDeidentifier:
    """Creates a local PNG draft with entire OCR lines containing known markers covered."""

    def __init__(self, ocr_client: LocalTesseractOcr) -> None:
        self.ocr_client = ocr_client

    def redact(self, image_path: Path, output_path: Path) -> LocalRedactionResult:
        try:
            extraction = self.ocr_client.extract_tsv(image_path)
        except LocalOcrUnavailable as error:
            raise LocalDeidentificationUnavailable(str(error)) from error
        except LocalOcrFailed as error:
            raise LocalDeidentificationFailed(str(error)) from error

        lines: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
        reader = csv.DictReader(io.StringIO(extraction.tsv), delimiter="\t")
        required_columns = {"block_num", "par_num", "line_num", "left", "top", "width", "height", "text"}
        if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
            raise LocalDeidentificationFailed("local_ocr_tsv_invalid")
        for row in reader:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            key = (
                row.get("page_num", "0"),
                row.get("block_num", "0"),
                row.get("par_num", "0"),
                row.get("line_num", "0"),
            )
            lines[key].append(row)

        redactions: list[tuple[int, int, int, int]] = []
        detected_codes: set[str] = set()
        for words in lines.values():
            line_text = " ".join((word.get("text") or "").strip() for word in words)
            normalised_line = _normalise_marker_text(line_text)
            line_codes = {
                code
                for code, markers in DIRECT_IDENTIFIER_MARKERS
                if any(_normalise_marker_text(marker) in normalised_line for marker in markers)
            }
            if not line_codes:
                continue
            try:
                left = min(int(word["left"]) for word in words)
                top = min(int(word["top"]) for word in words)
                bottom = max(int(word["top"]) + int(word["height"]) for word in words)
            except (KeyError, TypeError, ValueError) as error:
                raise LocalDeidentificationFailed("local_ocr_tsv_invalid") from error
            redactions.append((left, top, bottom))
            detected_codes.update(line_codes)

        try:
            with Image.open(image_path) as opened_image:
                image = opened_image.convert("RGB")
        except (OSError, UnidentifiedImageError) as error:
            raise LocalDeidentificationFailed("image_decode_failed") from error
        if image.width * image.height > 50_000_000:
            raise LocalDeidentificationFailed("image_dimensions_too_large")

        draw = ImageDraw.Draw(image)
        for left, top, bottom in redactions:
            margin = max(8, (bottom - top) // 4)
            draw.rectangle(
                (max(0, left - margin), max(0, top - margin), image.width, min(image.height, bottom + margin)),
                fill="black",
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="PNG", optimize=True)
        return LocalRedactionResult(
            detected_marker_codes=tuple(sorted(detected_codes)),
            engine_version=extraction.engine_version,
        )
