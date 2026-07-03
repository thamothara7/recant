---
name: recant-frontend
description: "Design system and build guide for the Recant console — the forensic UI for the CockroachDB × AWS 'Build with Agentic Memory' hackathon entry. ALWAYS consult this skill before writing any frontend code for Recant — components, pages, styling, animation, data viz, the demo/judge-facing UI, or anything described as 'a quick dashboard/console/viewer.' Also use it when recording or preparing the sub-3-minute demo video, wiring the Judge Overlay, Demo Director, or Recording Mode, or making any visual/UX decision in the console/ directory."
---

# Recant Frontend Skill

Extends the general `frontend-design` skill (subject grounding, one signature element, restraint, quality floor, UX writing). Everything here is binding for `console/`. Where this skill is silent, fall back to `frontend-design`; where they conflict, this skill wins.

## 1. Subject, audience, job

Subject: a **forensic evidence console for machine memory** — custody chains, contamination, retraction, time travel. Audience: hackathon judges (first 3 minutes) and incident responders (the fiction we design for). The page's single job: make one poisoned belief's journey — in, spread, recanted, proven — legible in under a minute.

Design stance: this is an **evidence room under UV light**, not a SaaS dashboard. Every visual choice should feel like handling tagged evidence: labeled, stamped, signed, traceable.

## 2. Tokens (use these; do not invent parallel values)

Palette — deliberately not the AI-default looks (cream+terracotta, near-black+acid-green, broadsheet):
- `--ink`        #10161D  — ledger blue-black base (never pure #000)
- `--panel`      #1A222C  — raised surfaces, cards
- `--bond`       #EDE7DA  — bond-paper text
- `--bond-dim`   #9AA3AE  — secondary text, retracted state
- `--uv`         #8B7EF8  — the identity accent: "UV lamp" violet. Interactive elements, provenance reveals, AOST/time-travel mode. Justification: forensic UV light reveals what is hidden; the accent marks exactly those moments.
- Semantic status (data, not decoration — never reuse for branding): `--attested` #3FB27F · `--suspect` #E3B341 · `--quarantined` #E5484D · `--retracted` #6B7480. Status is always **color + glyph + label** (✓ / ⚠ / ⛔ / ∅) — never color alone.

Type — three roles, functionally motivated:
- Display: **Source Serif 4** (600) — the "legal instrument" voice. Incident titles, affidavit headings, the wordmark. Use sparingly.
- UI: **IBM Plex Sans** — controls, labels, body.
- Data: **IBM Plex Mono** — hashes (truncate to 8 chars + copy affordance), timestamps (UTC, `HH:MM:SS.mmm`), SQL peeks, region/node IDs. If it came from the database, it is mono.

Spacing 4px base; radius 6px on panels, **2px on belief cards** (evidence tags are crisp, not friendly); 1px `#2A3442` hairline borders; shadows minimal — depth comes from border + fill, not blur.

## 3. Signature element: the custody thread

One memorable thing, spent here: a continuous **violet thread** that traces provenance. On hover/select of any belief, the thread draws from source → belief → derivations across the DAG (evidence-string-board energy, disciplined). During taint tracing, the thread is the narrative device: it *walks* the explicit edges, then a UV "scan sweep" reveals vector-inferred matches that have no drawn edge — the visual argument that Recant catches what foreign keys cannot. Keep everything around the thread quiet.

## 4. Layout

Desktop-first console at ≥1280px (judges + video). Grid:
- **Left rail (280px):** fleet (3 agents with live state) and sources (with trust tier chips).
- **Center: Provenance Board** — the DAG. Use react-flow with dagre layout, `nodesDraggable=false`, seeded deterministic positions (the video must be reproducible frame-for-frame). Belief cards: status glyph, 8-char hash (mono), author agent, age; perforated left edge (2px dotted border) as the evidence-tag motif.
- **Right drawer (360px): Inspector** — custody chain (ordered list: source → signatures → parents), incident panel, `recant()` action with typed confirmation.
- **Top strip: AOST scrubber** — horizontal timeline; dragging shifts the entire board to that timestamp via `AS OF SYSTEM TIME` queries. Past mode = subtle UV wash over the board + "VIEWING: 14:32:07 UTC" mono badge. A **pin** button freezes a moment for split-screen then/now compare (proof moment 5).
- **Bottom strip:** live changefeed ticker (mono, newest left) + cluster bar showing nodes/regions with health; a killed node renders ⛔ with uptime intact on the query counter (proof moment 6).

Mobile: read-only incident summary only. Do not attempt the board on small screens.

## 5. Additional functionality (build all three — they are submission assets, not extras)

**Judge Overlay** (toggle `J`, on by default in Recording Mode). Whenever a backend response includes the `X-Recant-Primitive` header, flash a chip top-right: `SERIALIZABLE TXN · 2 nodes · 41ms`, `VECTOR kNN · 12 matches · 23ms`, `CHANGEFEED → LAMBDA · 380ms`, `AOST @ −2h`, `ROW TTL EXPIRED`, `MCP TOOL CALL (read-only)`. Chips stack (max 3), persist 4s, and log to a slide-out panel with a one-line SQL peek per event. This maps one-to-one onto the judging criterion "identify which CockroachDB tools you used and what the agent actually did with them" — it is the highest-leverage component in the repo.

**Demo Director** (keys `1–6` = the six proof moments from the system prompt §7; `R` = reset to seed; `Space` = pause fleet). Each key fires a scripted, deterministic backend scenario and pre-positions the camera (scroll/selection) for that beat. No demo action may depend on live typing or luck.

**Recording Mode** (toggle `V`): hides dev chrome and cursor-adjacent tooltips, enforces minimum 14px effective type at 1280×720 export, raises contrast (`--bond` on `--ink` everywhere), adds a soft cursor halo, shows a 2:55 countdown, and suppresses any toast that could cover the board. Record the entire hackathon video inside this mode.

## 6. Motion

One orchestrated moment: the **recant sequence** — (1) explicit edges pulse along the thread, (2) UV scan sweep reveals inferred matches, (3) statuses flip in a single visual beat with the Judge Overlay chip landing on the same frame. Total ≤ 2.5s. Everything else: 150–200ms fades, no parallax, no ambient motion. `prefers-reduced-motion`: replace the sequence with a three-step stepped reveal, no sweeps.

## 7. Stack and constraints

React 18 + Vite + TypeScript + Tailwind (tokens above as CSS variables in `index.css`, mapped into Tailwind config). react-flow + dagre for the DAG; framer-motion for the recant sequence only; TanStack Query for data; native WebSocket for the ticker; Radix primitives for drawer/dialog/tooltip if needed. No heavy component kits, no chart library unless a real chart earns it (the ticker and board are the data viz). All timestamps UTC. All hashes copyable.

## 8. UX writing (inherits frontend-design writing rules)

Voice: evidence-room precise. Buttons say what happens: **"Recant source"**, confirmation: *"This quarantines 14 beliefs across 3 agents in one transaction. Type the source ID to proceed."* Empty board: *"No incidents. Memory is clean — seed the fleet to begin."* Errors name the failure and the fix: *"Changefeed disconnected — evictions paused. Reconnect or check the fanout Lambda logs."* Never "Oops," never apologies, never marketing adjectives inside the console.

## 9. Quality floor and self-critique

Visible keyboard focus (2px `--uv` ring); status never conveyed by color alone; reduced motion respected; deterministic layout snapshot-tested; Lighthouse a11y ≥ 90. Before calling any screen done: take a screenshot, apply the frontend-design mirror test (remove one accessory), and verify the screen still reads at 1280×720 in a paused video frame — if a judge can't parse it from a still, simplify it.

## 10. Do / Don't

Do: keep the board the hero; put the accent only on interaction and revelation; let mono data textures carry the "forensic" feel. 
Don't: use `--uv` for statuses; add a marketing landing page inside the console; introduce a second accent; animate node layout; use pie charts; show more than 60 beliefs on the board at once (cluster the rest behind a count chip); ship any screen that needs narration to be understood.
