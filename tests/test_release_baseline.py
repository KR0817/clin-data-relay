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
    assert __version__ == "0.2.0.dev0"
    assert project["tool"]["setuptools"]["package-data"]["app"] == [
        "static/index.html",
        "static/css/*.css",
        "static/js/*.js",
        "static/img/*.webp",
    ]
