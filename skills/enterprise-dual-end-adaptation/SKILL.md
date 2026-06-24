---
name: enterprise-dual-end-adaptation
description: Enterprise-grade PC + mobile dual-end adaptation for existing frontend pages. Use when a React/Tailwind/shadcn/ui page needs real responsive redesign across desktop and mobile, including layout restructuring, content prioritization, table-to-card adaptation, filter sheets, dialog/drawer changes, overflow fixes, and preserving desktop behavior while improving mobile usability.
---

# Enterprise Dual-End Adaptation

Use this skill to adapt an existing page for both desktop and mobile without flattening the desktop experience.

## Workflow

1. Audit the current page structure, data density, and interaction paths.
2. Classify content as P0, P1, or P2 for mobile.
3. Keep desktop behavior stable unless the page needs a local-only refactor.
4. Redesign mobile layout intentionally; do not just stack desktop content.
5. Fix overflow, touch targets, dialogs, filters, tables, forms, and long text.
6. Check loading, empty, error, disabled, and selected states on both breakpoints.
7. Review the final result for UI consistency and product polish.

## Core Rules

- Keep scope limited to the current page and its local components.
- Preserve business logic, API calls, permissions, and data shape.
- Do not hide core content on mobile without an alternate path.
- Prefer mobile-first layouts with responsive recovery on larger screens.
- Use `min-w-0`, `truncate`, `break-words`, `overflow-x-auto`, and responsive spacing intentionally.
- Convert complex tables to mobile cards when needed.
- Use `Sheet` or `Drawer` for mobile filters and heavy actions when dialogs do not fit well.

## Reference Material

Read the detailed implementation guide in [`references/dual-end-adaptation.md`](references/dual-end-adaptation.md) when you need the full audit checklist, layout patterns, shadcn/ui mapping, and verification standards.

