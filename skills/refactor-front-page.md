---

name: frontend-page-code-organization-refactor
description: Refactor a frontend page into a semantic page folder, extract reusable components and logic, update routes/config/links, and synchronize frontend design documentation.
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# Frontend Page Code Organization Refactor Skill

## 1. Purpose

Use this skill when a frontend page has grown too large, mixes UI rendering with business logic, or lacks reusable components and design documentation.

The goal is to reorganize one specific page into a stable, semantic page module.

This skill must:

1. Create a dedicated page folder based on the actual page meaning.
2. Move the existing page entry logic into `folder/index.tsx`.
3. Extract reusable UI pieces into `folder/components/`.
4. Extract reusable methods, data transforms, API helpers, and calculations into `folder/lib/`.
5. Create additional folders only when the content does not belong to `components` or `lib`.
6. Update all affected routes, configs, imports, links, and navigation references.
7. Update reuse documentation at `F:\dev-repo\mp4-to-word-new\design\front\reuse\reuse.md`.
8. Update frontend infrastructure documentation under `design/front/infra/`.
9. Add a maintenance notice inside `folder/index.tsx`.

## 2. Required Inputs

The agent must inspect the current page code and related project files.

Required information to infer from the codebase:

* Current page file path
* Current route path
* Page title or main UI heading
* Main business purpose of the page
* API calls used by the page
* Components, charts, forms, tables, panels, filters, cards, or dialogs used by the page
* Utility logic embedded inside the page
* Route configuration files
* Navigation config files
* Link references pointing to the old page path
* Existing design docs under `design/front/infra/`
* Existing reuse docs under `design/front/reuse/reuse.md`

Do not use a fixed folder name such as `mock-market`.
The folder name must be inferred from the actual page content.

## 3. Folder Naming Rules

The new folder name must describe the real page meaning.

Use this priority order:

1. Page title or main heading
2. Main business object
3. Main data domain
4. Current route path
5. Existing file name only as fallback

The folder name must:

* Use kebab-case
* Be stable and meaningful
* Represent the page business domain
* Avoid temporary or vague words

Forbidden folder name fragments:

* `mock`
* `temp`
* `demo`
* `test`
* `sample`
* `page`
* `new`
* `old`
* `backup`

Examples:

* A page about market capital flow should become `market-capital-flow`
* A page about sector capital trend should become `sector-capital-trend`
* A page about video transcription records should become `video-transcription-records`
* A page about document export history should become `document-export-history`

If multiple names are possible, choose the one closest to the page’s user-facing purpose.

## 4. Target Folder Structure

Create the page folder near the original page location unless the project already has a standard page directory.

Required structure:

```txt
folder/
  index.tsx
  components/
  lib/
```

Optional structure:

```txt
folder/
  types/
  constants/
  hooks/
  styles/
  config/
```

Only create optional folders when needed.

Folder responsibilities:

```txt
components/
  Reusable UI components used by this page.
  Examples: charts, tables, panels, cards, filters, dialogs, forms.

lib/
  Non-UI logic used by this page.
  Examples: API wrappers, data transforms, calculations, formatters, parsers.

types/
  TypeScript interfaces and types.

constants/
  Static values, option lists, column configs, chart configs.

hooks/
  React hooks with stateful page logic.

styles/
  CSS modules, style files, or page-specific style definitions.

config/
  Page-level configuration that is neither UI nor business logic.
```

## 5. Migration Rules

Move the original page logic into:

```txt
folder/index.tsx
```

After migration, `index.tsx` should mainly:

* Import extracted components
* Import extracted methods/hooks/types/constants
* Compose the page layout
* Connect data to UI
* Keep only page-level orchestration logic

`index.tsx` should not contain:

* Large chart option builders
* Large table column definitions
* Inline API request implementations
* Repeated data formatters
* Complex calculation logic
* Large JSX blocks that can become named components

## 6. Component Extraction Rules

Extract UI blocks into `folder/components/`.

Extract a component when:

* The JSX block has a clear visual responsibility
* The block is larger than a small inline fragment
* The block may be reused by this page or another page
* The block has independent props
* The block represents a chart, panel, table, form, filter, card, or dialog

Component naming rules:

* Use PascalCase
* Name by responsibility, not appearance
* Avoid names like `LeftBlock`, `Box1`, `ChartComp`

Good examples:

```txt
CapitalFlowTrendChart.tsx
SectorFlowPanel.tsx
SearchFilterBar.tsx
RecordTable.tsx
ExportStatusCard.tsx
```

Each extracted component should:

* Receive data through props
* Avoid direct route mutation unless it is a navigation component
* Avoid direct API calls unless explicitly designed as a smart component
* Avoid importing page-only state unless necessary

## 7. Lib Extraction Rules

Extract reusable non-UI code into `folder/lib/`.

Move the following into `lib`:

* API request wrappers
* Data normalization
* Data transformation
* Chart data builders
* Table data builders
* Calculation functions
* Formatters
* Validators
* Query builders

Recommended file names:

```txt
api.ts
transform.ts
format.ts
calculate.ts
buildChartOptions.ts
buildTableColumns.ts
validators.ts
```

Rules:

* Functions in `lib` should be pure whenever possible.
* Functions should not render JSX.
* Functions should not depend on browser DOM unless required.
* API functions should have clear names and typed return values.
* Data transform functions should have input and output types.

## 8. Route, Config, and Link Updates

After moving the page, update every affected reference.

Check and update:

* Route configuration
* File-based routing references
* Sidebar navigation
* Menu configuration
* Breadcrumb configuration
* Redirect rules
* Link components
* `navigate(...)` calls
* `router.push(...)` calls
* Static URL constants
* Imports pointing to the old page file
* Tests or stories importing the old page

The old page path must not remain as an active implementation unless the project requires a compatibility redirect.

If a redirect is required, keep it minimal and document it in the page detail doc.

## 9. Reuse Documentation Update

Update:

```txt
F:\dev-repo\mp4-to-word-new\design\front\reuse\reuse.md
```

Add a concise section for extracted reusable items.

Required format:

```md
## Page: {Page Display Name}

### Components

#### {ComponentName}
- Path: `{folder}/components/{ComponentName}.tsx`
- Purpose: {What this component renders}
- Reuse Scope: {Current page only | Same domain pages | Global reusable}
- Props Summary:
  - `{propName}`: {meaning}
- Notes: {Important reuse notes}

### Lib Methods

#### {methodName}
- Path: `{folder}/lib/{fileName}.ts`
- Purpose: {What this method does}
- Input: {Short input description}
- Output: {Short output description}
- Reuse Scope: {Current page only | Same domain pages | Global reusable}
```

Only document components and methods that were actually extracted.

Do not over-document trivial one-line helpers.

## 10. Infra Documentation Update

Update:

```txt
design/front/infra/index.md
```

Add or update a page registry item.

Required format:

```md
## {Page Display Name}

- Route: `{route}`
- Module: `{folder}/index.tsx`
- Detail: `./{folder-name}.detail.md`
- Data Source: {short description}
- APIs: {short API list or "None"}
- Components: {main component names}
```

Create a new detail document:

```txt
design/front/infra/{folder-name}.detail.md
```

The detail document must be concise.

Required format:

```md
# {Page Display Name}

## Overview

{One or two sentences describing what this page does.}

## Route

`{route}`

## Module

`{folder}/index.tsx`

## Data Sources

- {Data source 1}
- {Data source 2}

## APIs

- `{api endpoint or function name}`: {short purpose}

## Components

- `{ComponentName}`: {short purpose}
- `{ComponentName}`: {short purpose}

## Lib

- `{methodName}`: {short purpose}
- `{methodName}`: {short purpose}

## Data Flow

{API/source} -> `{lib transform method}` -> `{component}` -> UI rendering.

## Maintenance Notes

Before modifying this page, review:

- `design/front/infra/index.md`
- `design/front/infra/{folder-name}.detail.md`
- `design/front/reuse/reuse.md`

After modifying this page, update the related design documentation if route, data source, API usage, component structure, or reusable logic changes.
```

## 11. Required Comment in `folder/index.tsx`

Add this comment near the top of `folder/index.tsx`:

```tsx
/**
 * Maintenance Notice:
 * Before modifying this page, review the related documentation under:
 * - design/front/infra/index.md
 * - design/front/infra/{folder-name}.detail.md
 * - design/front/reuse/reuse.md
 *
 * If this page's route, data source, API usage, component structure,
 * or reusable logic changes, update the corresponding design documents.
 */
```

Replace `{folder-name}` with the actual folder name.

## 12. Execution Steps

Follow these steps in order:

1. Inspect the current page file.
2. Identify page purpose, route, data source, APIs, UI blocks, and embedded logic.
3. Infer the semantic folder name.
4. Create the new page folder.
5. Move the page entry into `folder/index.tsx`.
6. Extract UI blocks into `folder/components/`.
7. Extract non-UI logic into `folder/lib/`.
8. Create `types`, `constants`, `hooks`, `styles`, or `config` only if needed.
9. Update imports after file movement.
10. Update route config, navigation config, links, redirects, and references.
11. Update `design/front/reuse/reuse.md`.
12. Update `design/front/infra/index.md`.
13. Create `design/front/infra/{folder-name}.detail.md`.
14. Add the maintenance notice to `folder/index.tsx`.
15. Run or reason through TypeScript/import validation.
16. Report all changed files.

## 13. Validation Checklist

Before finishing, verify:

* A semantic page folder was created.
* The folder name does not contain forbidden temporary words.
* The page entry exists at `folder/index.tsx`.
* UI components are under `folder/components/`.
* Logic methods are under `folder/lib/`.
* Extra folders were created only when justified.
* Route config was updated.
* Navigation and links were updated.
* Old imports were removed or redirected.
* `reuse.md` was updated.
* `design/front/infra/index.md` was updated.
* `design/front/infra/{folder-name}.detail.md` was created.
* `folder/index.tsx` contains the required maintenance notice.

## 14. Final Response Format

After completing the refactor, respond with:

```md
## Refactor Summary

- Page: {Page Display Name}
- New Folder: `{folder}`
- Route: `{route}`

## Files Changed

- `{path}`: {change summary}
- `{path}`: {change summary}

## Extracted Components

- `{ComponentName}`: {purpose}

## Extracted Lib Methods

- `{methodName}`: {purpose}

## Documentation Updated

- `design/front/infra/index.md`
- `design/front/infra/{folder-name}.detail.md`
- `design/front/reuse/reuse.md`

## Notes

{Any compatibility notes, unresolved risks, or validation notes.}
```
