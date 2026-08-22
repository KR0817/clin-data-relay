from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SYNTHETIC_CHECK_SHEET_TEXT = (
    "SYNTHETIC LAB CHECK SHEET - NO PATIENT DATA\n"
    "TEST RESULT RANGE UNIT\n"
    "WBC 4.50 3.5-9.5 10E9/L\n"
    "ALT 31 9-50 U/L\n"
    "K 3.9 3.5-5.3 mmol/L\n"
    "CRP 2.3 0-8 mg/L"
)


def create_synthetic_check_sheet(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (2200, 900), "white")
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 60)
    ImageDraw.Draw(image).text(
        (80, 55),
        SYNTHETIC_CHECK_SHEET_TEXT,
        fill="black",
        font=font,
        spacing=30,
    )
    image.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an obviously synthetic local-OCR check sheet.")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    create_synthetic_check_sheet(args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
