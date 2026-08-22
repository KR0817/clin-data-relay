"""Native macOS entry point that always selects the local-only Lite profile."""

from app.portable_launcher import main


DEFAULT_PRODUCT_MODE = "lite"


if __name__ == "__main__":
    raise SystemExit(main(default_product_mode=DEFAULT_PRODUCT_MODE))
