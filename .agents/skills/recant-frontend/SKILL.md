---
name: recant-frontend
description: "Design system and build guide for the Recant console, the judge-facing UI for the CockroachDB x AWS 'Build with Agentic Memory' hackathon entry. ALWAYS consult this skill before writing any frontend code for Recant: components, pages, styling, animation, data viz, the demo/judge-facing UI, or anything described as 'a quick dashboard/console/viewer.' Also use it when recording or preparing the sub-3-minute demo video, wiring the Judge Overlay, Demo Director, or Recording Mode, or making any visual/UX decision in the console/ directory."
---

# Recant Frontend Skill

Extends the general `frontend-design` skill (subject grounding, restraint, quality floor, UX writing). Everything here is binding for `console/`. Where this skill is silent, fall back to `frontend-design`; where they conflict, this skill wins.

History note (2026-07-10): the original dark "UV forensic" theme was retired on user feedback (it read as AI-generated). The console is now authentic **Material 3**. Do not reintroduce the old look: no dark-by-default, no violet accent, no glow, no grain, no serif display type, no perforated evidence-tag motifs.

## 1. Subject, audience, job

Subject: a console for the chain of custody of machine memory: beliefs in, contamination spreading, one-click recant, proof after. Audience: hackathon judges (first 3 minutes) and incident responders (the fiction we design for). The page's single job: make one poisoned belief's journey (in, spread, recanted, proven) legible in under a minute.

Design stance: a **real product, the way a Google workspace app looks**. Credibility comes from disciplined Material 3, familiar patterns, and plain language, not from atmosphere. If a screen would not pass as a shipped Google product surface, simplify until it would.

## 2. Tokens (generated; do not invent parallel values)

All color tokens are M3 roles, HCT-derived from seed **#0B57D0** by `console/scripts/gen-m3-tokens.mjs` (official `@material/material-color-utilities`), pasted into `console/src/index.css` as `--md-*` variables and mirrored in `tailwind.config.ts`. Light is default; the dark scheme lives under `:root[data-theme="dark"]` (TopBar theme toggle). Regenerate with the script when the seed changes; never hand-edit hex values, never use raw hex in components.

- Use role utilities only: `bg-surface`, `bg-surface-container(-low/-high/...)`, `text-on-surface(-variant)`, `border-outline-variant`, `bg-primary` / `text-on-primary`, `bg-secondary-container`, and so on.
- Semantic status (data, never branding), via `STATUS_META` in `src/lib/format.ts`: always **icon + label + color**, rendered as tonal chips. active/Healthy = success roles + `check_circle`; suspect/Looks wrong = warning roles + `warning`; quarantined/Blocked = error roles + `block`; retracted/Withdrawn = outline/neutral + `do_not_disturb_on`. success/warning are M3 custom colors harmonized to the seed.
- Type: M3 scale on **Roboto** via Tailwind roles `text-display-sm` through `text-label-sm` (weight 500 via `font-medium` on title-md/sm and labels). **Roboto Mono** for anything from the database: hashes (8 chars + copy affordance), timestamps (UTC `HH:MM:SS.mmm`), SQL peeks, node/region ids. No uppercase letterspaced microcaps: M3 is sentence case.
- Icons: **Material Symbols Rounded** (self-hosted `material-symbols` package) through the `Icon` primitive. Never unicode glyphs, never emojis.
- Shape scale: `rounded-md3-xs/sm/md/lg/xl` = 4/8/12/16/28px. Cards 12, panels/sheets 16, dialogs 28, buttons and nav indicators full, chips 8.
- Elevation: `shadow-elevation-1/2/3`; depth primarily from tonal surface steps, borders are `outline-variant`. No decorative shadows, gradients, glows, or noise.
- Interaction: every interactive surface gets `state-layer` (hover 8% / press 12% wash) and the free 3px primary `:focus-visible` ring.
- Shared primitives in `src/components/m3.tsx` (`Icon`, `Button` filled/tonal/outlined/text/elevated with `tone="error"` for destructive, `IconButton`, `Chip`). Never hand-roll a button.

## 3. Signature element: the custody thread

One memorable thing, spent here: a continuous **primary-colored thread** that traces provenance. On hover/select of any belief, the thread lights the derivation path source to belief to descendants (`rf-edge-active`). Explicit edges are `outline` solid; vector-inferred edges are `tertiary` dashed, the visual argument that Recant catches what foreign keys cannot. Keep everything around the thread quiet.

## 4. Layout

Desktop-first console at >=1280px (judges + video). Gmail-style shell: chrome sits directly on `surface-container` (body background); the board is the hero, a large `rounded-md3-lg` `bg-surface` card.

- **Top app bar (h-16, transparent):** product chrome only: mark (32px primary tile, `LogoMark.tsx`: a memory dot with the custody thread arcing back around it, one stroke, arrowhead into the gap; `public/favicon.svg` mirrors it, keep in sync), name in title-lg, Story/Explore M3 segmented button, theme toggle, Advanced toggle. No tagline, no demo machinery. The Demo Director (moment buttons 1-6, reset, Judge/Recording toggles) lives in its own docked strip below the app bar, rendered only behind Advanced, so the app bar never reads as a keyboard-macro palette.
- **Left rail (280px, Explore only, transparent):** fleet (3 agents) and sources as M3 list items (h-14, `rounded-full` active indicator = `secondary-container`), trust tiers as chips.
- **Center: Provenance Board.** react-flow + dagre, `nodesDraggable=false`, deterministic positions (the video must be reproducible frame-for-frame). Belief cards: M3 outlined cards (`surface-container-lowest`, `outline-variant` border, 12px radius), agent name label, status chip, 2-line content, source line; hash + clock (mono) behind Advanced. Selected = primary border + elevation-1.
- **Right: Inspector (360px, Explore only, rendered only while a card or source is selected).** An always-open empty panel read as clutter; the board header carries the one-line hint ("Click a card for its full story") instead. `rounded-md3-lg bg-surface` panel: custody chain as an M3 list (source, signatures, parents), status chip + one-line explanation, `recant()` action as a filled error button with typed confirmation dialog (28px radius, `surface-container-high`).
- **AOST scrubber strip:** history icon, label, M3 slider (`aost-range`), value chip; dragging shifts the board to that timestamp. Past mode = 6% primary wash over the board + a `secondary-container` pill: "Viewing the past: 2h ago" with mono UTC clock.
- **Bottom strip (transparent):** live changefeed ticker (mono times, tone icons, right-edge fade instead of hard clipping) left; cluster bar right (Advanced): node chips with `dns` icon, up/down as success/error color plus label, kill/revive preserved. In story mode the strip appears only from the recant step onward: no log noise on the first-run frame. Board-header legend covers edge kinds only (solid copied / dashed reworded); statuses need no legend because every card carries a labeled chip.
- **Story mode:** board + bottom sheet only (`rounded-md3-lg bg-surface` walkthrough card: step progress, title-lg, body-md, filled Next / text Back, filled-error CTA on the recant step).

Mobile: read-only incident summary only (`MobileSummary.tsx`, gated by `min-width: 1024px` in App.tsx; index.html uses device-width viewport). Do not attempt the board on small screens. Deploy target: Vercel static (`console/vercel.json`: SPA rewrite + immutable asset caching).

## 5. Additional functionality (submission assets, not extras)

**Judge Overlay** (toggle `J`, Advanced only, on by default in Recording Mode). Whenever a backend response includes the `X-Recant-Primitive` header, flash a chip styled as an M3 snackbar (`inverse-surface`, elevation-3), docked bottom-leading INSIDE the board card so it can never occlude the rail or the inspector: `SERIALIZABLE TXN | 2 nodes | 41ms`, `VECTOR kNN | 12 matches | 23ms`, `CHANGEFEED -> LAMBDA | 380ms`, `AOST @ -2h`, `ROW TTL EXPIRED`, `MCP TOOL CALL (read-only)`. Chips stack (max 3), persist 4s, and log to a slide-out panel with a one-line SQL peek (mono on `surface-container-low`). This maps one-to-one onto the judging criterion "identify which CockroachDB tools you used and what the agent actually did with them": the highest-leverage component in the repo.

**Demo Director** (keys `1-6` = the six proof moments; `R` = reset to seed). Each key fires a scripted, deterministic scenario and pre-positions selection for that beat. No demo action may depend on live typing or luck.

**Recording Mode** (toggle `V`): hides dev chrome, enforces minimum 14px effective type at 1280x720 export, marks the frame (inset error-colored border), and suppresses any toast that could cover the board. Record the entire hackathon video inside this mode.

## 6. Motion

One orchestrated moment: the **recant sequence**: (1) explicit edges light along the thread, (2) a translucent primary wash sweeps the board revealing inferred matches, (3) statuses flip in a single visual beat with the Judge Overlay chip landing on the same frame. Total <= 2.5s. Everything else: 150-200ms fades, no parallax, no ambient motion. `prefers-reduced-motion`: replace the sequence with a stepped reveal, no sweeps.

## 7. Stack and constraints

React 18 + Vite + TypeScript + Tailwind (M3 tokens as CSS variables in `index.css`, mirrored in Tailwind config). react-flow + dagre for the DAG; framer-motion for the recant sequence only; Radix primitives for dialog/tooltip. Fonts self-hosted via `@fontsource/roboto`, `@fontsource/roboto-mono`, icons via `material-symbols` (no CDN). No heavy component kits, no chart library. All timestamps UTC. All hashes copyable.

## 8. UX writing (inherits frontend-design writing rules)

Voice: plain, beginner-first, product-precise. Buttons say what happens: **"Take back the bad fact"**, **"Recant source"**; confirmations state scope: *"This quarantines 14 beliefs across 3 agents in one transaction. Type the source ID to proceed."* Errors name the failure and the fix. Never "Oops," never apologies, never marketing adjectives. **No em-dashes, no emojis, anywhere** (user rule; applies to UI copy, code comments, and docs).

## 9. Quality floor and self-critique

Visible keyboard focus (3px primary ring); status never conveyed by color alone (icon + label always); reduced motion respected; deterministic layout; Lighthouse a11y >= 90. Before calling any screen done: take a screenshot, apply the frontend-design mirror test (remove one accessory), and verify the screen still reads at 1280x720 in a paused video frame. Extra gate: would this pass as a shipped Google product surface? If it looks themed, decorated, or "designed", strip it back.

## 10. Do / Don't

Do: keep the board the hero; let tonal surface steps carry depth; use the shared m3.tsx primitives everywhere; keep mono strictly for database data.
Don't: reintroduce dark-by-default, violet, glows, grain, or serif display; use primary for statuses; add a second accent; animate node layout; use uppercase microcaps; show more than 60 beliefs on the board at once (cluster the rest behind a count chip); ship any screen that needs narration to be understood.
