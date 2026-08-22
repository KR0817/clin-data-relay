"""Runtime profile resolution for local and future central deployments.

The module deliberately exposes only redacted deployment metadata to the HTTP
layer. A central profile must fail closed until its PostgreSQL repository and
operational controls are qualified; silently using SQLite would create an
unsafe multi-writer deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


class RuntimeConfigurationError(RuntimeError):
    """Raised when an unsupported deployment profile is requested."""


DeploymentProfile = Literal["local"]
ProductMode = Literal["full", "lite"]


@dataclass(frozen=True)
class RuntimeConfig:
    """Validated, non-secret runtime settings used by the application factory."""

    environment: str
    product_mode: ProductMode
    deployment_profile: DeploymentProfile
    database_backend: Literal["sqlite"]
    database_path: Path

    @classmethod
    def from_environment(
        cls,
        *,
        database_path: Path | None = None,
        environment: str | None = None,
        product_mode: str | None = None,
    ) -> "RuntimeConfig":
        profile = os.getenv("COMPANION_DEPLOYMENT_PROFILE", "local").strip().lower()
        if profile != "local":
            raise RuntimeConfigurationError(
                "central clinical repository and institutional identity are incomplete; "
                "the postgresql bootstrap preflight does not enable central mode; "
                "refusing to fall back to sqlite"
            )

        resolved_product_mode = (product_mode or os.getenv("COMPANION_PRODUCT_MODE", "full")).strip().lower()
        if resolved_product_mode not in {"full", "lite"}:
            raise RuntimeConfigurationError("unsupported_product_mode")

        resolved_database_path = database_path or Path(
            os.getenv("COMPANION_DATABASE_PATH", "data/companion.db")
        )
        return cls(
            environment=environment or os.getenv("COMPANION_ENV", "development"),
            product_mode=cast(ProductMode, resolved_product_mode),
            deployment_profile="local",
            database_backend="sqlite",
            database_path=resolved_database_path,
        )
