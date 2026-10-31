# Antigravity prompts: first 90 minutes

Paste each prompt into the Antigravity agent panel in the order shown. Every prompt assumes `DESIGN.md` and `.agent/rules/subscription-system.md` are already in the repo.

## Roles

| Member | Role | Owns |
|---|---|---|
| **A** | Billing core | `apps/catalog` models, `apps/subscriptions` models, all of `apps/billing` (models + services) |
| **B** | Identity, catalog UI, portal | `config/`, `apps/accounts`, `apps/core`, `apps/portal`, views/forms for catalog and subscriptions |
| **C** | Experience and proof | `templates/`, `static/`, `apps/reports`, `seed_demo` |

Pick roles by strength. If backend is newest to you, take **C**: it is the most visible and agent-friendly, and you can still pair on one small service function.

## Before the clock starts (10 minutes, any one person)

1. Create a GitHub repo. Add `DESIGN.md`, `.agent/rules/subscription-system.md`, and `docs/ANTIGRAVITY_PROMPTS.md` to `main`. Invite the other two.
2. Everyone clones and opens the folder in Antigravity. If the Customizations panel asks how the rule should apply, choose **always on**.
3. Everyone runs the same Python version (3.12) and agrees on the chat channel for "I am changing X" announcements.

## Modes and habits

- **Planning mode** for billing, discounts, pricing, permissions, and models. **Fast mode** for CRUD screens, templates, and seed scripts.
- Review each agent's plan Artifact before it codes. Skim the diff before you commit.
- Small tasks beat big ones: one prompt, one commit.
- Branch per prompt: `git checkout -b feat/<short-name>`. Rebase often: `git pull --rebase origin main`. Merge to `main` when green. Never force-push `main`.
- Only the person named in a prompt runs `makemigrations`. If a migration conflict appears, stop and ask Member A.

## Timeline and sync points

| Time | A (billing core) | B (identity + UI) | C (experience + proof) |
|---|---|---|---|
| 0:00-0:15 | A0 read and plan | **B0 scaffold + accounts** | C0 base layout |
| **0:15** | **S0: B pushes scaffold, everyone pulls** | | |
| 0:15-0:45 | **A1 models** | B1 auth flows | C1 dashboard + print templates |
| **0:45** | **S1: A tags `models-frozen`, everyone pulls and migrates** | | |
| 0:45-1:10 | A2 pricing, tax, discounts | B2 RBAC + staff creation | C2 `seed_demo` |
| 1:10-1:30 | A3 billing run | B3 catalog CRUD UI | C3 reports service |
| **1:30** | **S2: merge everything to `main`, run `seed_demo`, `run_billing`, click through** | | |
