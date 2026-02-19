# Agent Council

Multi-agent local AI collaboration using LM Studio + FastAPI.

## Current Behavior (Stable Main Flow)

The main app at `http://localhost:8000/` now runs in a **stable, non-stream rendering mode**:

- Each agent response is generated as a full completion (not token-by-token UI streaming).
- Responses are rendered one card after another and stay in place.
- Moderator output is rendered as a final card at the end.
- The page supports full conversation scrolling, so long sessions remain readable.

This was implemented to resolve UI issues where streamed chunks from some LM Studio/model combinations produced incomplete or invisible responses.

## Features

- Multi-agent council strategies: `debate`, `pipeline`, `vote`
- LM Studio model load/unload integration
- Stable WebSocket session endpoint: `ws://localhost:8000/ws/council`
- Simple, reliable frontend rendering path in `static/index.html` + `static/app.js`

## Architecture

- Backend: `server.py` (FastAPI + REST + WebSocket)
- Core orchestration: `council/`
  - `engine.py` for council orchestration
  - `agent.py` for prompt/message construction
  - `lm_studio.py` for LM Studio API calls
  - `strategies/` for debate/pipeline/vote strategy logic
- Frontend: `static/index.html`, `static/app.js`, `static/styles.css`

## Run

```bash
cd "/Users/sathwikreddy/Projects/Agent Council"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Open:

- App: `http://localhost:8000/`
- API docs: `http://localhost:8000/docs`
- Render test page: `http://localhost:8000/test`

## WebSocket Contract

### Client -> Server

```json
{
  "type": "task",
  "council": "general",
  "task": "Your question",
  "settings": {
    "temperature": 0.7,
    "max_tokens": 1024,
    "debate_rounds": 2
  },
  "model_overrides": {
    "0": "phi4-mini",
    "moderator": "qwen-7b"
  }
}
```

`settings` and `model_overrides` are optional.

### Server -> Client (event types)

- `status`
- `round_start`
- `model_loading`
- `model_loaded`
- `agent_start`
- `agent_done`
- `round_done`
- `moderator_start`
- `moderator_done`
- `council_done`
- `error`

Notes:

- In the stable main flow, frontend rendering is based on `agent_done` and `moderator_done` full content.
- `agent_chunk`/`moderator_chunk` are not required for visible output in the current UI path.

## REST Endpoints

- `GET /` -> main web UI
- `GET /test` -> render test UI
- `GET /api/health`
- `GET /api/config`
- `GET /api/councils`
- `GET /api/models`
- `GET /api/models/lm-studio`
- `POST /api/models/load`
- `POST /api/models/unload`

## Configuration

Edit `config.yaml`:

- `models` section defines LM Studio model IDs.
- `councils` section defines agents, personas, strategy, moderator.
- `defaults` sets default council and generation settings.

## Troubleshooting

- `LM Studio disconnected`: ensure LM Studio local server is running on `http://127.0.0.1:1234`.
- Blank/short answers: verify model identifiers in `config.yaml` match LM Studio IDs.
- Slow responses: reduce `max_tokens`, reduce rounds, or use smaller models.

## Cleanup Notes

Recent cleanup integrated the temporary V2 path into the main app. The following were removed:

- Separate V2 static files
- Separate V2 route and WebSocket endpoint

Main path (`/` + `/ws/council`) is now the supported stable flow.

## Incident: Invisible Responses

### Summary

An issue caused council sessions to complete while showing little or no visible answer text in the UI. Users would see model loading/status events and `council_done`, but response cards appeared empty or partially filled.

### Timeline (high level)

1. Symptom observed in production UI:
- Early tokens occasionally appeared, but later model outputs were not visible.
- In several runs, only model/status rows were visible even after completion.

2. Isolation:
- `/test` render path worked, confirming base DOM rendering was not fundamentally broken.
- The problem concentrated in main-session event/content handling and scroll/readability behavior.

3. Temporary stabilization:
- A parallel stable path was created to validate non-stream full-response rendering.

4. Final integration:
- Stable behavior was merged back into main path (`/` + `/ws/council`).
- Temporary parallel path was removed.

### Root Cause

The previous flow depended heavily on streaming chunk visibility and UI behavior that was sensitive to payload shape and viewport behavior:

- Some model/server combinations produced content in forms that were not consistently visible through the old chunk-first rendering path.
- Conversation readability suffered when long outputs appeared to be replaced/obscured by later cards due to scroll behavior.

Net effect: session lifecycle completed, but user-visible text was unreliable.

### What Changed

1. Rendering strategy:
- Main UI now renders reliable full-turn outputs from `agent_done` and `moderator_done`.

2. Session behavior:
- Main `/ws/council` uses a stable non-stream full-response path for display reliability.

3. Readability:
- Full-page conversation scroll behavior keeps outputs reviewable in order.

4. Fallback messaging:
- Explicit fallback text is shown when a model returns empty/whitespace content.

### Prevention / Operational Guidance

- Treat `agent_done`/`moderator_done` as the source of truth for visible answer cards.
- Keep `/test` available as a rendering sanity check when debugging UI regressions.
- If future streaming UI is reintroduced, gate it behind a feature flag and keep non-stream full-response mode as the default fallback.
- Preserve scroll/readability behavior in UI reviews (long-output test cases should be part of acceptance checks).
