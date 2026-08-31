"""Backward-compatible Kimi names for the generic model-provider boundary."""

from app.model_provider import (
    ModelCandidate,
    ModelConfigurationError,
    ModelProviderSettings,
    ModelServiceError,
    OpenAICompatibleClient,
    write_local_api_key,
)


KimiCandidate = ModelCandidate
KimiConfigurationError = ModelConfigurationError
KimiSettings = ModelProviderSettings
KimiServiceError = ModelServiceError
KimiClient = OpenAICompatibleClient


__all__ = [
    "KimiCandidate",
    "KimiClient",
    "KimiConfigurationError",
    "KimiServiceError",
    "KimiSettings",
    "write_local_api_key",
]
