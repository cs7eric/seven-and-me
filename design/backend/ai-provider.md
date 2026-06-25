# AI Provider backend design

> Maintenance rule: before changing AI provider routing, provider types, database tables, or adapter behavior, read this document first. After code changes, update this document in the same change set.

## Purpose

AI calls are routed by capability instead of hard-coded provider calls. Feature code asks for a capability such as `text_polish` or `auction_analysis`; the backend resolves the active provider and model from the database, then dispatches through a provider adapter.

This lets operators move one feature from MiniMax to DeepSeek, OpenAI-compatible endpoints, or future providers through Settings > AI Provider without editing feature code.

## Runtime Flow

1. Feature service calls `get_ai_router().chat_completion(...)` with a capability and fallback model.
2. `AIAdapterRouter` loads the binding from `app.ai_usage_bindings`.
3. The binding points to one row in `app.ai_providers`.
4. The router builds `AIProviderConfig` from DB fields and env fallbacks.
5. The concrete adapter sends a chat completion request.

Fallback behavior:

- If the database is unavailable during resolution, the router falls back to `MINIMAX_API_KEY` / `MINIMAX_GROUP_ID`.
- If a configured provider has no API key from DB or env, the request fails with a clear error.
- `model_override` on the binding wins over provider `default_model`.

## Provider Types

Provider types are declared in `backend/repositories/ai_provider_repo.py`.

Current types:

- `minimax`: MiniMax native endpoints. Streaming requires `group_id`.
- `openai_compatible`: Generic OpenAI-style `/v1/chat/completions` provider.
- `deepseek`: DeepSeek OpenAI-compatible provider. Defaults:
  - base URL: `https://api.deepseek.com`
  - chat endpoint: `/chat/completions`
  - default model: `deepseek-v4-flash`
  - env key: `DEEPSEEK_API_KEY`

DeepSeek uses an OpenAI-compatible chat completion API, but it is kept as a separate provider type so future DeepSeek-specific parameters can be added without changing saved generic OpenAI-compatible providers.

- `anthropic_compatible`: Anthropic Messages API (`/v1/messages`). Uses `x-api-key` header and `anthropic-version: 2023-06-01`. Response content is extracted from `content[0].text`.

## Database

Tables:

- `app.ai_providers`: provider connection settings, secrets or secret env names, default model, timeout, extra JSON.
- `app.ai_usage_bindings`: capability to provider mapping, optional model override.

Migrations:

- `alembic/versions/s2t3u4v5w6x7_create_ai_provider_tables.py`
- `alembic/versions/t3u4v5w6x7y8_seed_deepseek_ai_provider.py`
- `alembic/versions/u4v5w6x7y8z9_add_ai_providers_models.py`
- `alembic/versions/v5w6x7y8z9a1_seed_mimo_ai_provider.py`

Seed data:

- `minimax-default` is bound to all current capabilities by the initial migration.
- `deepseek-default` is created but not bound automatically. Bind individual capabilities in Settings > AI Provider.
- `mimo-default` is created with Anthropic-compatible adapter. Bind individual capabilities in Settings > AI Provider.

## Backend Code Map

- `backend/services/ai_adapter_service.py`
  - Adapter interface and concrete provider adapters.
  - Register new provider adapters in `AIAdapterRouter._adapters`.
- `backend/repositories/ai_provider_repo.py`
  - Capability list, provider type list, CRUD serialization, binding resolution.
- `backend/api/ai_providers.py`
  - HTTP CRUD endpoints for providers, bindings, capabilities, and provider types.
- `backend/models/ai_provider.py`
  - SQLAlchemy models for provider registry tables.
- `backend/services/ai_provider_service.py`
  - Shared `get_ai_router()` entrypoint.
- `polisher.py`
  - MP4 polish, summary, metadata, and QA capability calls.
- `backend/services/stock/application_analysis_service.py`
  - Stock application analysis capability calls.
- `backend/services/stock/auction_ai_analysis_service.py`
  - Auction analysis capability calls.

## Adding A Provider

For a provider that follows the generic OpenAI `/v1/chat/completions` contract, add a row from the UI using `openai_compatible`; no code change is required.

For a provider that needs a different endpoint, auth style, request shape, response parsing, or special defaults:

1. Add a provider type to `PROVIDER_TYPES`.
2. Add an adapter class in `ai_adapter_service.py`.
3. Register the adapter in `AIAdapterRouter._adapters`.
4. Add a seed migration only if the provider should exist by default.
5. Update this document and `design/frontend/ai-provider.md`.

## API Endpoints

- `GET /api/ai/capabilities`
- `GET /api/ai/provider-types`
- `GET /api/ai/providers`
- `POST /api/ai/providers`
- `PATCH /api/ai/providers/<provider_id>`
- `DELETE /api/ai/providers/<provider_id>`
- `GET /api/ai/bindings`
- `PATCH /api/ai/bindings`

