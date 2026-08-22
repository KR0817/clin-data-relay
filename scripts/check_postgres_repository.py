from __future__ import annotations

import json

from app.postgres_repository import (
    PostgresConfigurationError,
    PostgresRepositoryBootstrap,
    PostgresRepositoryError,
)


def main() -> int:
    try:
        status = PostgresRepositoryBootstrap.from_environment().prepare()
    except (PostgresConfigurationError, PostgresRepositoryError) as error:
        print(json.dumps({"status": "error", "code": str(error)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ready", **status.public_payload()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
