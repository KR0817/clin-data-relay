# Model-provider configuration

ClinData Relay uses an allow-listed OpenAI-compatible multimodal
`/chat/completions` transport. Kimi is the default provider. This configuration
changes only the optional candidate-extraction transport; it does not bypass
de-identification, the field dictionary, human review or the Authority EDC.

## Default Kimi profile

Existing `KIMI_*` variables and recipient key files remain supported. A new
installation needs only the local web key form or the existing packaging
command. No sender key is distributed.

## Approved custom profile

Set process-owned variables before application startup:

```text
MODEL_PROVIDER=approved-provider-alias
MODEL_ENABLED=true
MODEL_BASE_URL=https://approved-model.example.test/v1
MODEL_NAME=approved-vision-model
MODEL_ALLOWED_BASE_URLS=https://approved-model.example.test/v1
MODEL_API_KEY_FILE=/operator-controlled/path/model-api-key.txt
MODEL_API_KEY_REQUIRED=true
MODEL_TIMEOUT_SECONDS=45
MODEL_MAX_RETRIES=2
MODEL_REASONING_EFFORT=
```

`MODEL_ALLOWED_BASE_URLS` is a comma-separated exact allow-list. It is not a
domain suffix list. Remote endpoints require HTTPS. Plain HTTP and keyless mode
are accepted only for `localhost`, `127.0.0.1` or `::1`, and the loopback URL
must still be allow-listed exactly.

The browser key form writes only the credential file already selected by the
process. It cannot set the provider, URL, model or allow-list. Health and audit
records expose provider alias and model only; they never expose an endpoint,
credential path, key or provider response.

## Compatibility and qualification boundary

When a generic variable is absent, the matching legacy `KIMI_*` variable is
used. `app.kimi` remains a compatibility facade for existing imports and
packages.

An endpoint being technically compatible does not make it approved for
participant data. Before any non-synthetic evaluation, independently qualify
the provider's data processing, retention, access controls, regional routing,
model/schema behavior and institutional authorization. Provider failures are
availability outcomes and must not be interpreted as extraction accuracy.
