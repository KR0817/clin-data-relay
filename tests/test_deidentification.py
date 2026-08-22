from pathlib import Path

from PIL import Image

from app.deidentification import LocalImageDeidentifier


class SyntheticTsvOcr:
    def extract_tsv(self, _image_path: Path):
        rows = [
            "page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\ttext",
            "1\t1\t1\t1\t10\t10\t40\t10\t姓名：患者甲",
            "1\t1\t1\t2\t10\t40\t60\t10\t送检医生：张医师",
            "1\t1\t1\t3\t10\t70\t60\t10\t检验者：李技师",
            "1\t1\t1\t4\t10\t100\t60\t10\t审核者：王医师",
            "1\t1\t1\t5\t10\t130\t90\t10\t采样时间：2026-08-05",
            "1\t1\t1\t6\t10\t160\t90\t10\t签收时间：2026-08-05",
            "1\t1\t1\t7\t10\t190\t90\t10\t审核时间：2026-08-05",
        ]
        return type(
            "SyntheticTsvExtraction",
            (),
            {"tsv": "\n".join(rows), "engine_version": "synthetic-tsv-1"},
        )()


def test_deidentifier_masks_patient_staff_and_timestamp_lines(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "redacted.png"
    Image.new("RGB", (240, 240), "white").save(source)

    result = LocalImageDeidentifier(SyntheticTsvOcr()).redact(source, output)

    assert set(result.detected_marker_codes) == {
        "patient_name",
        "collecting_clinician",
        "laboratory_examiner",
        "report_reviewer",
        "sample_timestamp",
        "receipt_timestamp",
        "review_timestamp",
    }
    with Image.open(output) as redacted:
        for y in (15, 45, 75, 105, 135, 165, 195):
            assert redacted.getpixel((20, y)) == (0, 0, 0)
