# Enterprise Dual-End Adaptation

This document is the detailed operating guide for the skill.

## Scope

Use this skill for existing frontend pages that need real PC + mobile adaptation in React, Tailwind CSS, or shadcn/ui projects.

## Principles

- Preserve desktop behavior.
- Redesign mobile intentionally.
- Keep business logic unchanged.
- Limit changes to the current page and its local components.
- Do not hide core content without an alternate mobile path.

## Audit Checklist

- Page structure
- Information hierarchy
- Core interaction path
- Overflow risks
- State completeness
- Desktop breakage risk

## Mobile Priority Model

- P0: must stay visible
- P1: can be collapsed or deferred
- P2: can be moved into more menus or secondary views

## Common Patterns

- Desktop table, mobile card list
- Desktop dialog, mobile sheet or drawer
- Desktop multi-column form, mobile single-column form
- Desktop filter bar, mobile filter sheet
- Desktop sidebar, mobile top nav or menu

## Verification

Check:

- 360px
- 390px
- 414px
- 768px
- 1024px
- 1440px

Confirm:

- no horizontal scroll
- touch targets are usable
- dialogs and drawers scroll and close correctly
- loading, empty, error, disabled, and selected states still work
- desktop layout remains stable

