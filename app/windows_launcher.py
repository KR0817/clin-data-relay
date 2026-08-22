"""Windows entry point for the shared portable launcher."""

import sys
from pathlib import Path

from app.portable_launcher import (
    UI_CACHE_TOKEN,
    PortablePaths,
    browser_url,
    configure_portable_environment,
    main,
    runtime_identity_matches,
)

__all__ = (
    "UI_CACHE_TOKEN",
    "PortablePaths",
    "browser_url",
    "configure_portable_environment",
    "default_product_mode",
    "main",
    "runtime_identity_matches",
)


def default_product_mode(executable: str | Path | None = None) -> str:
    """Choose the packaged profile without trusting inherited environment state."""
    executable_name = Path(executable or sys.executable).stem.casefold()
    return (
        "lite"
        if executable_name in {"start-clinical-edc-lite", "clinicalreportextractorlite"}
        else "full"
    )


if __name__ == "__main__":
    raise SystemExit(main(default_product_mode=default_product_mode()))
