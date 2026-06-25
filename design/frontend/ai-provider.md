# AI Provider frontend design

> Maintenance rule: before changing the AI Provider settings page, route, or API payload shape, read this document first. After code changes, update this document in the same change set.

## Purpose

The AI Provider settings page lets users manage model connections and route product features to providers without code changes.

The page has two responsibilities:

- Provider switchboard: create, view, edit, and delete concrete providers.
- Routing matrix: choose which provider and optional model override each capability uses.

## Route

- URL route: `settings/ai-provider`
- Page component: `frontend/src/views/settings/ai-provider/index.tsx`
- Router registration: `frontend/src/router/index.tsx`
- Sidebar registration: `frontend/src/config/sidebar.ts`

## Data Flow

The page loads four backend resources:

- `fetchAiCapabilities()`: capability rows shown in Routing matrix.
- `fetchAiProviderTypes()`: provider type options and defaults.
- `fetchAiProviders()`: provider rows shown in Provider switchboard.
- `fetchAiBindings()`: capability to provider mappings.

When provider type changes in the modal, the page fills empty default fields from `fetchAiProviderTypes()`:

- `base_url`
- `default_model`
- `api_key_env`
- `group_id_env`

It does not overwrite values that the user already typed.

## Provider Types

Provider types are backend-driven from `GET /api/ai/provider-types`; do not hard-code new options in the page.

Current types:

- `minimax`
- `openai_compatible`
- `deepseek`

DeepSeek default values are supplied by the backend:

- base URL: `https://api.deepseek.com`
- default model: `deepseek-v4-flash`
- API key env: `DEEPSEEK_API_KEY`

## Frontend Code Map

- `frontend/src/views/settings/ai-provider/index.tsx`
  - Main settings page, modal, provider table, and routing matrix.
- `frontend/src/lib/api.ts`
  - AI Provider frontend API types and request helpers.
- `frontend/src/router/index.tsx`
  - Route registration.
- `frontend/src/config/sidebar.ts`
  - Settings navigation entry.
- `frontend/src/components/ui/input.tsx`
  - Global input visual style.
- `frontend/src/components/ui/select.tsx`
  - Global select trigger visual style.

## UX Rules

- `New provider` opens a modal.
- Provider connection fields are edited only inside the modal.
- Routing matrix changes only capability bindings and model overrides.
- Provider type options come from the backend.
- Inputs and selects use the global borderless, muted-background style.

## Change Checklist

When changing this area:

1. Update backend contracts first if payload shape or provider types change.
2. Update `frontend/src/lib/api.ts` types.
3. Update `frontend/src/views/settings/ai-provider/index.tsx`.
4. Run targeted lint for touched frontend files.
5. Update this document and `design/backend/ai-provider.md`.

