"""Evaluate synthetic extractor JSON without printing source values."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from app.ocr_evaluation import evaluate_predictions


def _read_fields(path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    fields = payload.get("fields", payload)
    if not isinstance(fields, dict):
        raise ValueError("fields_object_required")
    return {str(code): dict(value) for code, value in fields.items() if isinstance(value, dict)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a synthetic OCR gold/prediction pair.")
    parser.add_argument("gold", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--tolerance", default="0.01")
    args = parser.parse_args()
    metrics = evaluate_predictions(
        _read_fields(args.gold),
        _read_fields(args.predictions),
        numeric_tolerance=Decimal(args.tolerance),
    )
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
