from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import app.ocr as ocr_module
from app.ocr import LocalOcrFailed, LocalTesseractOcr


def test_tesseract_output_is_read_from_a_bounded_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"synthetic")
    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic")

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="tesseract 5.5\n", stderr="")
        kwargs["stdout"].write(b"ALT: 31 U/L\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ocr_module.subprocess, "run", fake_run)

    result = LocalTesseractOcr(executable=executable).extract(image)

    assert result.text == "ALT: 31 U/L\n"
    assert result.engine_version == "tesseract 5.5;lang=eng"


def test_tesseract_output_limit_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"synthetic")
    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic")

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="tesseract 5.5\n", stderr="")
        kwargs["stdout"].write(b"too-large")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ocr_module.subprocess, "run", fake_run)
    monkeypatch.setattr(ocr_module, "MAX_OCR_OUTPUT_BYTES", 1)

    with pytest.raises(LocalOcrFailed, match="local_ocr_output_too_large"):
        LocalTesseractOcr(executable=executable).extract(image)
