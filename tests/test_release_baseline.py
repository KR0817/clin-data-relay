from __future__ import annotations

import tomllib
from pathlib import Path

from app.version import __version__


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_package_version_and_static_asset_manifest_have_single_explicit_sources() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "app.version.__version__"
    }
    assert __version__ == "0.2.0"
    assert project["tool"]["setuptools"]["package-data"]["app"] == [
        "static/index.html",
        "static/css/*.css",
        "static/js/*.js",
        "static/img/*.webp",
    ]


def test_open_source_release_metadata_uses_agpl_3_only() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    citation = (PROJECT_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    source_offer = (PROJECT_ROOT / "packaging" / "SOURCE-CODE.txt").read_text(
        encoding="utf-8"
    )

    assert project["project"]["license"] == "AGPL-3.0-only"
    assert project["project"]["license-files"] == ["LICENSE"]
    assert license_text.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE\n")
    assert "Version 3, 19 November 2007" in license_text
    assert "license: AGPL-3.0-only" in citation
    assert "version: 0.2.0" in citation
    assert "tree/v0.2.0" in source_offer
