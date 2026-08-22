"""Generate an identifier-free pulmonary-function PDF for portable QA."""

from __future__ import annotations

import argparse
from pathlib import Path

from pypdf import PdfWriter
from pypdf._page import PageObject
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject


REPORT_LINES = (
    "Predicted Measured Percent",
    "VT 0.43 0.92 215.2",
    "BF 20.00 21.88 109.4",
    "MV 8.57 20.17 235.4",
    "VC MAX 4.11 3.92 95.3",
    "IC 3.02 2.00 66.2",
    "FVC 3.96 3.20 80.7",
    "FEV 1 3.09 2.45 79.2",
    "PEF 8.02 5.03 62.8",
    "MEF 75 7.12 3.67 51.5",
    "MEF 50 4.22 1.73 41.1",
    "MEF 25 1.51 0.35 23.3",
    "VBEex 0.06",
    "MVV 116.27 51.69 44.5",
    "TLC-SB 6.74 6.53 96.9",
    "RV-SB 2.44 2.89 118.2",
    "DLCOSB 8.97 3.61 40.3",
    "KCO 1.33 0.56 42.4",
)


def create_pdf(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    page = PageObject.create_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    commands = ["BT", "/F1 10 Tf", "50 740 Td", "14 TL"]
    for line in REPORT_LINES:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.extend((f"({escaped}) Tj", "T*"))
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    page[NameObject("/MediaBox")] = ArrayObject(page[NameObject("/MediaBox")])
    writer.add_page(page)
    with output_path.open("wb") as output:
        writer.write(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic pulmonary-function PDF.")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    create_pdf(args.output)


if __name__ == "__main__":
    main()
