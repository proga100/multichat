# multichat — Build Plan

This document is the authoritative spec for the coding agent (Codex). It pairs
with `AGENTS.md` (always-on guardrails); this file is the staged roadmap. Build
the numbered stages in order. **Do not generate everything at once.** Finish a
stage, verify it against its acceptance criteria, then move to the next. Stage 1
(scaffold) already exists — start by confirming it, then build Stage 2 onward.

---

## 0. Project identity & non-negotiables

- **What it is:** a personal, self-hosted multi-model chat orchestrator. One
  prompt → Claude + GPT + Gemini answer in parallel (**Compare**), or critique
  each other across rounds and synthesize (**Debate**).
- **Who it's for:** one user (the owner). **Personal everyday-use software.**
  Not a hackathon project, not for distribution.
- **Keys:** BYOK — the user's own API keys in a local `.env`. No auth, no
  billing, no multi-tenant.
- **Deployment:** **Mac-hosted.** API, providers, SQLite, and the Telegram bot
  all run as one local process on the user's MacBook. No VPS, no public URL.
- **Prime directive:** the **`BaseProvider` abstraction stays front and
  center.** The app must be able to add a 4th model by writing one class.
  Nothing outside a provider file may import or reference a provider SDK.

### Hard constraints

- Python 3.12, **async throughout** (`async`/`await`, async SDK clients). Never
  hand-roll raw HTTP to providers — use official async SDKs.
- Minimal, current dependencies. Pin versions.
- Per-provider error isolation: one provider failing must NEVER break the
  others — it surfaces as an error in that column/stream only.
- Comment the non-obvious async / streaming / SSE parts. Keep code readable.

### Explicitly OUT of scope (do not build, even if tempting)

- Document/Slide/Spreadsheet "studios", image generation, file export.
- Built-in web-research mode and auto fact-check/verification mode.
  - Leave a **hook** for these via `BaseProvider` (a future web-search-capable
    provider is just another subclass), but build none of it now.

---

## 1. Stack (use exactly this)

| Layer | Choice |
|---|---|
| Backend | Python 3.12 + FastAPI, async; SSE via `StreamingResponse` |
| Frontend | React + Tailwind CSS (Vite) |
| Storage | SQLite (single file, single user) |
| Config | `pydantic-settings` loading `.env` — the ONE config place |
| Anthropic | `anthropic` (AsyncAnthropic) |
| OpenAI | `openai` (AsyncOpenAI) |
| Gemini | `google-genai` (async via `client.aio.*`) — the newer unified SDK |
| Telegram | `python-telegram-bot` v22+ (async, long-polling) |

**Version policy:** at build time, check the latest published version of each
SDK and pin it. The scaffold pinned: `anthropic==0.109.2`, `openai==2.41.1`,
`google-genai==2.8.0`, `fastapi==0.137.1`, `python-telegram-bot==22.6`. Re-verify
before installing; bump if newer stable exists.

**Model strings are NOT trustworthy from memory.** Before writing any provider
call (Stages 2 & 4), verify the current model names and the exact streaming
method signatures against each SDK's installed version / current docs. The
`.env.example` placeholders (`claude-sonnet-4-6`, `gpt-5-mini`,
`gemini-2.5-flash`, etc.) are starting points to confirm, not facts to rely on.

---

## 2. Architecture decisions (already made — do not re-litigate)

### 2.1 The abstraction

- `BaseProvider` (abstract) exposes:
  - `async def stream(self, messages: list[Message]) -> AsyncIterator[str]`
    — yields plain text deltas. (Primary method.)
  - `async def complete(self, messages) -> str` — default impl drains `stream`;
    used by Stage 2 to verify a provider before SSE exists.
- Each provider subclass translates the shared `Message` list into its own SDK
  format and yields **text only** — never SDK-specific objects.
- A **factory** maps `(ProviderName, premium: bool) -> BaseProvider`, resolving
  the model string from settings. Callers never construct providers directly or
  know model strings.

### 2.2 Shared message format & system-prompt placement

- Shared `Message { role: Role, content: str }`, `Role ∈ {system, user, assistant}`.
- **Each provider places SYSTEM text where its SDK wants it:**
  - Anthropic → top-level `system` param.
  - OpenAI → a system message in the messages array.
  - Gemini → `system_instruction`; and map roles `assistant → "model"`.
- This translation lives **inside each provider**, nowhere else.

### 2.3 Two topologies × swappable role-prompt templates

The "many modes" are NOT many code paths. They are:

- **Two orchestration topologies:**
  1. **Parallel rounds** — all providers run concurrently within a round;
     rounds are sequential barriers (round N+1 cannot start until all of round N
     is fully complete, because each model needs the others' *complete* text).
  2. **Sequential relay** — providers run one after another; each sees the full
     transcript so far appended to its prompt.
- **× role-prompt templates** in `app/prompts/templates.py` (data, not code).

From these, the visible modes fall out:

| Mode | Topology | What's injected |
|---|---|---|
| **Compare** | parallel, 1 round, no cross-talk | nothing |
| **Debate** | parallel rounds + synthesis | others' answers; critique prompt |
| **Expert** | parallel | per-provider role ("a security engineer") |
| **Simulation** | parallel | per-provider persona/scenario |
| **Co-operative / Relay** | sequential | running transcript |

Adding/tweaking a mode should be **editing a template string**, not writing
Python. Build Compare + Debate fully; the others are template presets exposed
once the two topologies exist.

### 2.4 Transport & run model (decided)

- **Create-then-stream**, because `EventSource` can't POST a body:
  - `POST /api/runs` → persist the user message, create a run, return `run_id`.
  - `GET /api/runs/{run_id}/stream` → SSE. Client opens this to receive events.
- **Single multiplexed SSE stream.** Merge the providers' async generators into
  one `asyncio.Queue`; yield events tagged `{type, provider, round, delta}`. The
  client dispatches by `provider`/`round`. One connection serves all columns and
  carries round markers — debate needs that coordination anyway.
- **Event types (suggested):** `delta` (token chunk), `provider_done`,
  `round_start`, `round_done`, `synthesis_delta`, `error` (per-provider),
  `run_done`, and `awaiting_human` (for pausable runs).
- **Pausable / resumable runs (in scope).** A run can halt at a checkpoint
  (between relay speakers, or between debate rounds) and emit `awaiting_human`.
  `POST /api/runs/{run_id}/continue` (optional `content`) resumes, injecting the
  human's steer as a prior turn. Do not design runs as fire-and-forget.

### 2.5 Error isolation

- Wrap each provider's generator so an exception becomes an `error` event on
  THAT provider's stream only (think `gather(..., return_exceptions=True)`-style
  isolation). Other columns keep streaming. The run as a whole still completes.

### 2.6 Relay specifics (defaults — owner may override)

- **Speaker order: user-orderable per run** (default order: Anthropic → OpenAI →
  Gemini). Expose as a request field; don't hardcode.
- **Synthesis: a separate final step** performed by a configured provider
  (`SYNTHESIS_PROVIDER` in `.env`, default `anthropic`), NOT "whoever spoke
  last." Applies to both Debate and Relay when synthesis is requested.

---

## 3. Data model (SQLite)

```sql
threads(
  id INTEGER PK,
  title TEXT,
  mode TEXT NOT NULL,            -- 'compare' | 'debate' | future modes
  created_at TEXT DEFAULT now
)

messages(
  id INTEGER PK,
  thread_id INTEGER FK -> threads(id) ON DELETE CASCADE,
  role TEXT NOT NULL,            -- 'user' | 'assistant' | 'system'
  provider TEXT,                 -- 'anthropic'|'openai'|'gemini'|NULL for user
  model TEXT,                    -- concrete model string used, e.g. 'gpt-5-mini'
  content TEXT NOT NULL,
  round INTEGER,                 -- NULL/0 compare; 1..N debate; N+1 synthesis
  prompt_tokens INTEGER,         -- nullable; fill when SDK returns usage
  output_tokens INTEGER,         -- nullable
  created_at TEXT DEFAULT now
)
```

- `model`, `prompt_tokens`, `output_tokens` exist from the start so the
  ergonomics stage can show tier/spend with no migration.
- A Telegram-triggered run is just a normal run + rows; reopenable in the web UI.

---

## 4. Staged build order

> Each stage ends with **Acceptance criteria** = how to prove it works before
> proceeding. Keep diffs minimal per stage and report how to test.

### Stage 1 — Scaffold ✅ (already built)

Backend (FastAPI app, lifespan with DB init + reserved Telegram hook, `/health`,
`config.py`, `types.py`, `db.py`, `BaseProvider`, factory, three provider stubs,
`prompts/templates.py`) and frontend (Vite + React + Tailwind shell that checks
`/health`). `.env.example`, README, `.gitignore`.

**Acceptance:** `uvicorn app.main:app --reload` boots; `curl /health` returns
configured models; `npm run dev` shows the shell with green "● connected".

**Action:** confirm the scaffold runs as-is (or regenerate to match Section 2's
structure). Do not change architecture.

### Stage 2 — AnthropicProvider, NON-streaming

- Implement `AnthropicProvider` using `AsyncAnthropic`. Translate `Message`s
  (SYSTEM → top-level `system`). Verify model name + method signature first.
- `POST /api/chat/once` (or similar): body `{prompt, premium?}` → calls
  `provider.complete()` → returns `{provider, model, content}`.
- Frontend: one input box + one column that shows the full answer.
- **Acceptance:** type a prompt in the browser, get Claude's full answer
  rendered in one column. No streaming yet. Errors return a clean JSON error.

### Stage 3 — SSE streaming for Anthropic

- Implement `AnthropicProvider.stream()` (verify the streaming API shape).
- Add `POST /api/runs` (persist user msg, create run) + `GET /api/runs/{id}/stream`
  (SSE). For now a single provider; emit `delta` / `provider_done` / `run_done`.
- Frontend: a small SSE client in `src/lib/` (use `fetch`+reader or `EventSource`
  per the chosen transport in 2.4); the single column streams live token-by-token.
- **Acceptance:** the column fills in progressively as tokens arrive, not all at
  once. Reconnect/refresh doesn't crash the server.

### Stage 4 — OpenAIProvider + GeminiProvider

- Implement both behind `BaseProvider`. Verify model names + streaming
  signatures. OpenAI: system message in array. Gemini: `system_instruction`,
  `assistant→"model"`, async via `client.aio.*`.
- **Acceptance:** a debug switch lets you point the single-column stream at each
  provider; all three stream live, one at a time. Each handles a bad key / bad
  model with a clean per-provider `error` (no crash).

### Stage 5 — Compare mode (3 concurrent live columns)

- Orchestrator: fan out the three providers concurrently; merge into one
  multiplexed SSE stream tagged by `provider`. Slow model must not block others.
- Apply per-provider error isolation (2.5): a failing provider shows an error in
  its column; the other two keep streaming.
- Frontend: three columns side by side, each updating independently in real time.
- **Acceptance:** one prompt → three columns stream simultaneously; kill one
  provider's key and only that column errors.

### Stage 6 — Debate mode (rounds + synthesis) and the relay topology

- Implement **parallel-rounds** orchestration:
  - Round 1: all three answer independently (template `DEBATE_ROUND1`).
  - Rounds 2..N: inject the other two models' *complete* previous-round answers
    (`DEBATE_CRITIQUE`); barrier between rounds.
  - Synthesis (round N+1): the `SYNTHESIS_PROVIDER` produces one combined answer
    explicitly noting **agreements / disagreements / final recommendation**
    (`DEBATE_SYNTHESIS`). Persist synthesis as its own message.
- Implement **sequential-relay** orchestration sharing the same providers and
  templates (`RELAY_CONTINUE`); user-orderable speaker order.
- Wire **pausable/resumable** runs (2.4): emit `awaiting_human` at checkpoints;
  `POST /api/runs/{id}/continue` resumes with optional injected steer.
- Let the user pick **number of rounds**.
- Frontend: round markers in the stream; synthesis rendered as a distinct final
  block. Relay rendered as a single growing transcript (not columns).
- **Acceptance:** run a 3-round debate end to end; round 2 visibly references
  round-1 content; synthesis names agreements/disagreements/recommendation. Run
  a relay; stop mid-chain, inject a steer, and confirm later speakers see it.

### Stage 7 — SQLite persistence + thread list / reopen

- Persist every run's messages with `provider/model/round/tokens`. Capture token
  usage when the SDK returns it.
- Endpoints: list threads, fetch a thread's messages. Reopen a past thread and
  continue it (multi-turn within a thread is a **first-class path** — switching
  model/tier or even mode within a thread must work).
- Frontend: a thread sidebar; clicking reopens and renders prior rounds.
- **Acceptance:** create several threads across modes, restart the server,
  reopen each, continue one with a follow-up.

### Stage 8 — Telegram bot front-end

- `python-telegram-bot`, **long-polling**, launched as an asyncio task inside
  FastAPI's lifespan (same process, same event loop, same DB).
- **Allowlist of exactly one user** (`TELEGRAM_ALLOWED_USER_ID`); ignore everyone
  else (protects BYOK credits).
- Commands/parse: e.g. `compare: <prompt>` / `debate N: <prompt>`. Bot acks
  immediately, runs in the background, posts **round-complete / final results**
  as messages (Telegram is a **degraded linear view** — no token streaming, no
  columns). Synthesis posted as its own message.
- A Telegram run is a normal persisted run; reopenable in the web UI.
- **Acceptance:** from the phone, send `debate 2: ...`; receive round results +
  synthesis back; a non-allowlisted account gets no response; the same run shows
  up in the web thread list.

### Stage 9 — Mac packaging (optional)

- v1: a menu-bar app (`rumps`) or a `launchd` agent that runs the backend +
  Telegram poller in the background; open `localhost` for the rich UI.
- Later: wrap the React frontend in **Tauri** with the Python backend as a
  sidecar for a real app window.
- **Acceptance:** launching the app starts everything; quitting stops it cleanly.
  (Skip until Stages 1–8 are solid.)

### Stage 10 — Ergonomics (after core works)

Pure frontend/UX, no architecture impact: keyboard send, copy a column,
regenerate one provider without rerunning all three, per-run token/cost counter
(read the token columns), edit-last-prompt-and-rerun.

### Stage 11 — Super Mind unified + individual view

- Implement **Super Mind** as parallel individual answers followed by a separate
  synthesis pass from `SYNTHESIS_PROVIDER`.
- Persist individual answers as round 1 and the unified response as round 2.
- Frontend: show a segmented `Unified | Individual` view. `Unified` defaults to
  the synthesized answer; `Individual` shows raw provider outputs.
- Telegram: support `supermind: <prompt>` with individual completion followed
  by the unified response.
- **Acceptance:** run a Super Mind prompt end to end; individual provider
  responses stream first, then the unified response appears; thread history
  stores all four assistant messages.

---

## 5. Suggested file/module layout

```
backend/app/
  main.py                 # FastAPI app, lifespan (DB init + Telegram task), routers
  core/
    config.py             # pydantic-settings — the ONE config place
    types.py              # Message, Role, ProviderName
    db.py                 # schema + connection helpers
  providers/
    base.py               # BaseProvider (the abstraction)
    factory.py            # (provider, tier) -> instance
    anthropic_provider.py
    openai_provider.py
    gemini_provider.py
  orchestrator/
    compare.py            # parallel fan-out, one round
    debate.py             # parallel rounds + synthesis
    relay.py              # sequential chain
    stream.py             # merge generators -> multiplexed SSE event queue
  api/
    runs.py               # POST /runs, GET /runs/{id}/stream, POST /runs/{id}/continue
    threads.py            # list/reopen (Stage 7)
  prompts/
    templates.py          # editable mode/role prompts
  telegram/
    bot.py                # long-polling, allowlist, command parse (Stage 8)
frontend/src/
  App.jsx
  lib/sse.js              # SSE client
  lib/api.js              # fetch wrappers
  components/             # ColumnView, TranscriptView, ThreadSidebar, Composer, ...
```

---

## 6. Gotchas to respect

- **`EventSource` can't POST or set headers** — that's why runs are
  create-then-stream. If using `fetch`+reader for SSE instead, parse the
  `text/event-stream` framing yourself.
- **Vite dev proxy:** `/api` and `/health` proxy to `:8000` (already configured).
  Ensure SSE passes through the proxy (no buffering); disable response buffering
  on the `StreamingResponse` (`media_type="text/event-stream"`, and send
  periodic comments/heartbeats if a proxy times out idle streams).
- **Round barriers in debate:** a model must receive the *complete* prior-round
  answers of the others — gather the round to completion before composing the
  next round's prompts.
- **SQLite + async:** connections are short-lived per operation;
  `check_same_thread=False`; keep writes simple. Don't share one connection
  across concurrent provider tasks.
- **Gemini role mapping:** `assistant → "model"`, and system text goes in
  `system_instruction`, not the contents list.
- **Token usage** isn't always present on streamed responses — capture it from
  the final usage object when the SDK exposes it; leave columns NULL otherwise.
- **Verify model strings and streaming signatures at build time** — do not trust
  any model name or method shape from memory.

---

## 7. The one decision the owner still controls

Section 2.6 sets **defaults** (relay order user-orderable, default A→O→G;
synthesis a separate step by `SYNTHESIS_PROVIDER`). These are the recommended
choices and the plan builds them as such. If the owner wants last-speaker
synthesis or a fixed order instead, change only Stage 6 + the relevant template;
nothing else in the plan depends on it.
