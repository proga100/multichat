# AGENTS.md

Project instructions for OpenAI Codex. This file is always-on context; the
staged roadmap lives in `BUILD-PLAN.md`. Read `BUILD-PLAN.md` at the start of
each stage. Keep THIS file unchanged during a session.

## Setup

Backend:
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste in the three API keys
uvicorn app.main:app --reload --port 8000
```

Frontend (separate terminal):
```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

## Test / verify (run these — do not assume; demonstrate)

```bash
# backend up + models configured
curl -s http://127.0.0.1:8000/health

# python imports clean (from backend/, venv active)
python -c "from app.main import app; from app.providers.factory import make_provider; print('ok')"

# frontend builds
cd frontend && npm run build
```

Each stage in `BUILD-PLAN.md` has its own **Acceptance criteria**. After a stage,
RUN that stage's checks and paste the actual output. The instruction is loaded ≠
the behavior happened — prove it with real command output, never a claim.

## How to work in this repo

- **Build in stages from `BUILD-PLAN.md`, in order. One stage at a time.** Do not
  generate everything at once. Finish a stage, prove it against its acceptance
  criteria, then continue. Keep each stage's diff minimal.
- **Stage 1 (scaffold) already exists.** Confirm it runs before changing
  anything. Do not restructure the architecture.
- **Stop and wait for the owner after Stage 1.** From Stage 2 on, proceed but
  report the exact test commands the owner should run.

## Prime directive (do not violate)

The `BaseProvider` abstraction stays front and center. Adding a 4th model must be
writing ONE subclass. **No file outside `app/providers/` may import or reference a
provider SDK** (`anthropic`, `openai`, `google-genai`). All provider SDK
translation — including system-prompt placement — lives inside each provider
class only.

## Rules

- **Async throughout.** Official async SDK clients only; never hand-roll HTTP to
  providers. Comment non-obvious async/streaming/SSE code.
- **Never trust model strings or SDK method shapes from memory.** Before writing
  any provider call, verify the current model name and exact (streaming) method
  signature against the installed SDK version. `.env.example` model names are
  placeholders to confirm, not facts.
- **Per-provider error isolation is mandatory.** One provider failing surfaces as
  an `error` event on that provider's stream only; the others keep streaming; the
  run still completes.
- **Modes are config, not code.** New/changed discussion modes = editing a
  template in `app/prompts/templates.py`, layered on the two topologies (parallel
  rounds / sequential relay). No new code path per mode.
- **Keys never leave the local `.env`.** Mac-hosted only; no VPS, no public URL.
  Never commit `.env` or `*.db`.
- **Ask before adding any new production dependency** beyond those already in
  `requirements.txt` / `package.json`.

## Decisions already made — do not re-litigate

- Transport: create-then-stream (`POST /api/runs` → `GET /api/runs/{id}/stream`
  SSE); single multiplexed stream tagged `{type, provider, round, delta}`.
- Runs are pausable/resumable (`awaiting_human` + `POST /api/runs/{id}/continue`),
  not fire-and-forget.
- Debate: parallel rounds with barriers; synthesis is a separate final step by
  `SYNTHESIS_PROVIDER`, emitting agreements / disagreements / recommendation.
- Relay: sequential; user-orderable speaker order (default anthropic→openai→gemini).
- Schema carries `model`, `round`, nullable `prompt_tokens`/`output_tokens`.

## Out of scope (do not build)

Document/slide/spreadsheet export, image generation, built-in web-research mode,
auto fact-check/verification. Leave only a `BaseProvider`-shaped hook for a
future search-capable provider.
```
