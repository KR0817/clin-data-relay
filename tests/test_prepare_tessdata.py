from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import prepare_tessdata


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_prepare_reuses_a_valid_offline_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"valid-traineddata"
    destination = tmp_path / "vendor" / "tessdata_fast"
    destination.mkdir(parents=True)
    (destination / "eng.traineddata").write_bytes(content)
    monkeypatch.setattr(prepare_tessdata, "DESTINATION", destination)
    monkeypatch.setattr(
        prepare_tessdata, "LANGUAGE_FILES", {"eng.traineddata": digest(content)}
    )

    def unexpected_download(name: str, target: Path) -> None:
        raise AssertionError(f"unexpected download for {name} to {target}")

    monkeypatch.setattr(prepare_tessdata, "download", unexpected_download)

    prepare_tessdata.prepare()


def test_prepare_downloads_to_a_temporary_file_and_validates_before_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"new-traineddata"
    destination = tmp_path / "vendor" / "tessdata_fast"
    monkeypatch.setattr(prepare_tessdata, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prepare_tessdata, "DESTINATION", destination)
    monkeypatch.setattr(
        prepare_tessdata, "LANGUAGE_FILES", {"eng.traineddata": digest(content)}
    )
    monkeypatch.setattr(
        prepare_tessdata, "download", lambda _name, target: target.write_bytes(content)
    )

    prepare_tessdata.prepare()

    assert (destination / "eng.traineddata").read_bytes() == content


def test_prepare_rejects_a_download_with_the_wrong_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "vendor" / "tessdata_fast"
    monkeypatch.setattr(prepare_tessdata, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prepare_tessdata, "DESTINATION", destination)
    monkeypatch.setattr(
        prepare_tessdata, "LANGUAGE_FILES", {"eng.traineddata": digest(b"expected")}
    )
    monkeypatch.setattr(
        prepare_tessdata, "download", lambda _name, target: target.write_bytes(b"wrong")
    )

    with pytest.raises(RuntimeError, match="tessdata_digest_mismatch:eng.traineddata"):
        prepare_tessdata.prepare()

    assert not (destination / "eng.traineddata").exists()
