# multichat

A personal, self-hosted multi-model chat orchestrator. Send one prompt to
Claude, GPT, and Gemini and see their answers side by side (**Compare**), or
have them critique each other across rounds and synthesize a final answer
(**Debate**). BYOK — your own API keys, in a local `.env`. Single user, no auth,
runs on your Mac.

> Status: **Stage 8 complete.** Compare, single-provider streaming, debate,
> relay, persisted thread reopen, and the local Telegram bot front-end are
> implemented.

## Architecture (the part that matters)

Everything is built around one abstraction: **`BaseProvider`**
(`backend/app/providers/base.py`). Each model is a subclass that translates the
shared `Message` format into its own SDK's format and yields text deltas. The
rest of the app never touches provider-specific code — so adding a fourth model
later is writing one class.

```
shared Message  ->  BaseProvider.stream()  ->  text deltas
                         ^
        AnthropicProvider / OpenAIProvider / GeminiProvider
```

Two discussion **topologies** (parallel rounds / sequential relay) combined with
swappable **role-prompt templates** (`backend/app/prompts/templates.py`) give
the discussion modes (Debate, Expert, Simulation, Co-operative). Modes are
mostly config, not code — edit a template to add or tweak one.

## Project structure

```
multichat/
├── backend/
│   ├── requirements.txt
│   ├── .env.example          # copy to .env and fill in
│   └── app/
│       ├── main.py           # FastAPI app, lifespan (DB init + Telegram hook), /health
│       ├── core/
│       │   ├── config.py     # pydantic-settings — the ONE config place
│       │   ├── types.py      # shared Message / Role / ProviderName
│       │   └── db.py         # SQLite schema + connection
│       ├── providers/
│       │   ├── base.py       # BaseProvider abstract class  <-- the abstraction
│       │   ├── factory.py    # (provider, tier) -> instance; resolves model strings
│       │   ├── anthropic_provider.py  # stub -> implemented step 2/3
│       │   ├── openai_provider.py     # stub -> implemented step 4
│       │   └── gemini_provider.py     # stub -> implemented step 4
│       ├── orchestrator/     # compare/debate/relay loops
│       ├── api/              # run, SSE, and thread endpoints
│       ├── telegram/         # long-polling Telegram front-end
│       └── prompts/
│           └── templates.py  # editable mode/role prompts
└── frontend/
    ├── package.json
    ├── vite.config.js        # proxies /api and /health -> :8000
    ├── tailwind.config.js
    └── src/
        ├── App.jsx           # step-1 shell: backend connection check
        ├── components/       # (real UI built step 3/5)
        └── lib/
```

## Prerequisites

- Python 3.12
- Node 18+ (for Vite)
- API keys for Anthropic, OpenAI, Google (Gemini)

## Setup & run

### 1. Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — paste in your three API keys

uvicorn app.main:app --reload --port 8000
```

Verify it's up:

```bash
curl http://127.0.0.1:8000/health
# -> {"status":"ok","anthropic_model":"...","openai_model":"...",...}
```

### 2. Frontend (separate terminal)

```bash
cd frontend
npm install
npm run dev
# open http://localhost:5173
```

You should see the **multichat** shell with a green "● connected" and the three
configured model names — that confirms the frontend is reaching the backend.

## Configuration

All settings live in `backend/.env` (see `.env.example`). To switch any model,
edit the `*_MODEL_DEFAULT` / `*_MODEL_PREMIUM` values — that's the single place.
Model names are starting points; confirm them against each provider's current
docs before first real use.

For Telegram, create a bot with `@BotFather`, set `TELEGRAM_BOT_TOKEN`, and set
`TELEGRAM_ALLOWED_USER_ID` to your numeric Telegram user id. The bot ignores all
other users. Supported messages:

```text
compare: your prompt
debate 2: your prompt
relay: your prompt
```

## Deployment

Mac-hosted: the API, providers, SQLite, and Telegram bot all run as one local
process on your Mac. The Telegram front-end lets you trigger discussions from
your phone whenever your Mac is awake and the app is running. No server, no
public URL; keys stay in your local `.env`.

## Building with Codex

This repo is set up for OpenAI Codex:

- `AGENTS.md` (repo root) — always-on guardrails Codex reads every session
  (setup/test commands, the `BaseProvider` rule, "one stage at a time"). Keep it
  unchanged during a session.
- `BUILD-PLAN.md` — the staged roadmap (Stages 1–10), each with acceptance
  criteria. `AGENTS.md` tells Codex to read this per stage.

Kick off in the repo with something like:
*"Read AGENTS.md and BUILD-PLAN.md. Confirm Stage 1 runs, then build Stage 2 and
stop."* Codex works stage by stage, running each stage's acceptance checks.

## Build order

1. **Scaffold** — structure, deps, config, run instructions. ✅
2. `BaseProvider` + `AnthropicProvider`, non-streaming: one prompt, one answer. ✅
3. SSE streaming for Anthropic; single column streams live. ✅
4. Add `OpenAIProvider` + `GeminiProvider` behind the same interface. ✅
5. **Compare mode**: three concurrent streaming columns. ✅
6. **Debate mode**: rounds + cross-model context injection + synthesis. ✅
7. SQLite persistence + thread list / reopen. ✅
8. Telegram bot front-end (long-polling, your-user-only). ✅
9. *(optional)* Mac packaging (menu-bar or Tauri).
```
