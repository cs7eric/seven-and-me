---
name: enterprise-dual-end-adaptation
description: Enterprise-grade PC + mobile dual-end adaptation for existing frontend pages. Use when a React/Tailwind/shadcn/ui page needs real responsive redesign across desktop and mobile, including layout restructuring, content prioritization, table-to-card adaptation, filter sheets, dialog/drawer changes, overflow fixes, and preserving desktop behavior while improving mobile usability. Requires applying frontend-design, ui-ux-pro-max, impeccable, and design-taste-frontend-v1 standards before implementation.
---

# Enterprise Dual-End Adaptation

Use this skill to adapt an existing page for both desktop and mobile without flattening the desktop experience.

## Required Companion Skills

Before writing or changing code, apply these companion skills in this order:

1. `frontend-design` for layout concept, type/palette direction, and distinctive structure.
2. `ui-ux-pro-max` for responsive behavior, touch targets, forms, navigation, and interaction rules.
3. `impeccable` for product-page polish, accessibility, spacing, and implementation quality.
4. `design-taste-frontend-v1` for final taste review and anti-slop guardrails.

Treat their standards as mandatory. If any proposed change fails one of those lenses, revise it before shipping.

## Workflow

1. Read the current page and identify the real user task.
2. Run the companion skills mentally as four review passes.
3. Audit the current page structure, data density, and interaction paths.
4. Classify content as P0, P1, or P2 for mobile.
5. Keep desktop behavior stable unless the page needs a local-only refactor.
6. Redesign mobile layout intentionally; do not just stack desktop content.
7. Fix overflow, touch targets, dialogs, filters, tables, forms, and long text.
8. Check loading, empty, error, disabled, and selected states on both breakpoints.
9. Review the final result against the four companion skills again before finishing.

## Core Rules

- Keep scope limited to the current page and its local components.
- Preserve business logic, API calls, permissions, and data shape.
- Do not hide core content on mobile without an alternate path.
- Prefer mobile-first layouts with responsive recovery on larger screens.
- Use `min-w-0`, `truncate`, `break-words`, `overflow-x-auto`, and responsive spacing intentionally.
- Convert complex tables to mobile cards when needed.
- Use `Sheet` or `Drawer` for mobile filters and heavy actions when dialogs do not fit well.
- Favor one clear primary action per surface, with subordinate secondary actions.
- Do not ship a page that passes responsive checks but still feels generic, cramped, or over-decorated.

## Reference Material

Read the detailed implementation guide in [`references/dual-end-adaptation.md`](references/dual-end-adaptation.md) when you need the full audit checklist, layout patterns, shadcn/ui mapping, and verification standards.
