"""Conservative coordinate-based parsing for de-identified Chinese laboratory tables."""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError

from app.ocr import LocalOcrFailed, LocalOcrUnavailable, LocalTesseractOcr


class ChineseLabExtractionUnavailable(RuntimeError):
    """Raised when structured local OCR is unavailable."""


class ChineseLabExtractionFailed(RuntimeError):
    """Raised when structured local OCR cannot be completed safely."""


@dataclass(frozen=True)
class ChineseLabExtraction:
    candidates: tuple[tuple[str, str, str | None], ...]
    ambiguous_field_codes: tuple[str, ...]
    engine_version: str


@dataclass(frozen=True)
class AliasRule:
    field_code: str
    aliases: tuple[str, ...]
    reject_if_contains: tuple[str, ...]


NUMERIC_RE = re.compile(r"(?P<operator>[<>≤≥])?\s*(?P<number>-?\d+(?:[.,]\d+)?)")
RANGE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*[-~–—]\s*\d+(?:[.,]\d+)?")


def _normalise_label(value: str) -> str:
    return re.sub(r"[\s:：_\-—–*#（）()\[\]【】.]+", "", value).casefold()


def _numeric_value(token: str) -> str | None:
    normalised = token.replace("《", "<").replace("》", ">").replace("，", ",")
    if RANGE_RE.search(normalised):
        return None
    matches = list(NUMERIC_RE.finditer(normalised))
    if len(matches) != 1:
        return None
    operator = matches[0].group("operator") or ""
    number = matches[0].group("number").replace(",", ".")
    return f"{operator}{number}"


class LocalChineseLabExtractor:
    """Uses exact aliases and word coordinates; it never infers units or ambiguous cell metrics."""

    def __init__(self, ocr_client: LocalTesseractOcr, mapping_path: Path | None = None) -> None:
        self.ocr_client = ocr_client
        resolved_path = mapping_path or (
            Path(__file__).resolve().parent.parent / "config" / "chinese_lab_aliases.v0.1.json"
        )
        try:
            payload = json.loads(resolved_path.read_text(encoding="utf-8"))
            self.mapping_id = str(payload["mapping_id"])
            self.mapping_version = str(payload["mapping_version"])
            self.rules = tuple(
                AliasRule(
                    field_code=str(item["field_code"]).upper(),
                    aliases=tuple(str(alias) for alias in item["aliases"]),
                    reject_if_contains=tuple(str(term) for term in item.get("reject_if_contains", [])),
                )
                for item in payload["field_aliases"]
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ChineseLabExtractionUnavailable("chinese_lab_alias_mapping_unavailable") from error
        if not self.rules or any(not rule.aliases for rule in self.rules):
            raise ChineseLabExtractionUnavailable("chinese_lab_alias_mapping_unavailable")

    def extract(self, image_path: Path) -> ChineseLabExtraction:
        try:
            with Image.open(image_path) as opened_image:
                image = opened_image.convert("L")
        except (OSError, UnidentifiedImageError) as error:
            raise ChineseLabExtractionFailed("image_decode_failed") from error
        if image.width * image.height > 50_000_000:
            raise ChineseLabExtractionFailed("image_dimensions_too_large")
        target_size = (image.width * 2, image.height * 2)
        if target_size[0] * target_size[1] > 50_000_000:
            raise ChineseLabExtractionFailed("preprocessed_image_dimensions_too_large")
        image = image.resize(target_size, Image.Resampling.LANCZOS)
        image = ImageOps.autocontrast(image)
        image = ImageEnhance.Contrast(image).enhance(1.5)

        with tempfile.TemporaryDirectory(prefix="clinical-edc-chinese-lab-") as temporary_directory:
            preprocessed_path = Path(temporary_directory) / "preprocessed.png"
            image.save(preprocessed_path, format="PNG", optimize=True)
            try:
                extraction = self.ocr_client.extract_tsv(preprocessed_path, psm=6)
            except LocalOcrUnavailable as error:
                raise ChineseLabExtractionUnavailable(str(error)) from error
            except LocalOcrFailed as error:
                raise ChineseLabExtractionFailed(str(error)) from error

        grouped: dict[tuple[int, int, int, int], list[dict[str, str]]] = defaultdict(list)
        reader = csv.DictReader(io.StringIO(extraction.tsv), delimiter="\t")
        required = {"page_num", "block_num", "par_num", "line_num", "left", "text"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ChineseLabExtractionFailed("local_ocr_tsv_invalid")
        for row in reader:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            try:
                key = tuple(int(row[column]) for column in ("page_num", "block_num", "par_num", "line_num"))
                int(row["left"])
            except (KeyError, TypeError, ValueError) as error:
                raise ChineseLabExtractionFailed("local_ocr_tsv_invalid") from error
            grouped[key].append(row)

        observations: list[tuple[tuple[int, int, int, int], int, str, str, str | None]] = []
        for line_key, words in grouped.items():
            words.sort(key=lambda word: int(word["left"]))
            normalised_words = [_normalise_label(word["text"]) for word in words]
            compact = ""
            spans: list[tuple[int, int]] = []
            for normalised_word in normalised_words:
                start = len(compact)
                compact += normalised_word
                spans.append((start, len(compact)))
            for rule in self.rules:
                if any(_normalise_label(term) in compact for term in rule.reject_if_contains):
                    continue
                alias_positions = [
                    (compact.find(_normalise_label(alias)), len(_normalise_label(alias)))
                    for alias in rule.aliases
                    if compact.find(_normalise_label(alias)) >= 0
                ]
                if not alias_positions:
                    continue
                alias_start, alias_length = max(alias_positions, key=lambda item: item[1])
                alias_end = alias_start + alias_length
                end_word_index = next(
                    index for index, (_, span_end) in enumerate(spans) if span_end >= alias_end
                )
                label_right = int(words[end_word_index]["left"])
                value: str | None = None
                value_left: int | None = None
                for word in words[end_word_index + 1 :]:
                    word_left = int(word["left"])
                    if word_left - label_right > 700:
                        break
                    candidate_value = _numeric_value(word["text"])
                    if candidate_value is None:
                        continue
                    value = candidate_value
                    value_left = word_left
                    break
                if value is not None and value_left is not None:
                    observations.append((line_key, value_left, rule.field_code, value, None))

        by_code: dict[str, list[tuple[tuple[int, int, int, int], int, str, str, str | None]]] = defaultdict(list)
        for observation in observations:
            by_code[observation[2]].append(observation)
        ambiguous_codes = sorted(
            code for code, values in by_code.items() if len({observation[3] for observation in values}) > 1
        )
        selected = [
            min(values, key=lambda observation: (observation[0], observation[1]))
            for code, values in by_code.items()
            if code not in ambiguous_codes
        ]
        selected.sort(key=lambda observation: (observation[0], observation[1]))
        candidates = tuple((code, value, unit) for _, _, code, value, unit in selected)
        return ChineseLabExtraction(
            candidates=candidates,
            ambiguous_field_codes=tuple(ambiguous_codes),
            engine_version=(
                f"{extraction.engine_version};preprocess=gray2x-autocontrast;psm=6;"
                f"alias={self.mapping_version}"
            ),
        )
