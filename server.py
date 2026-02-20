"""
Agent Council — FastAPI Server
===============================

This is the main entry point for the Agent Council application.
It provides:
    - A REST API for configuration and model management
    - A WebSocket endpoint for real-time council sessions
    - Static file serving for the web UI

Start the server:
    $ python server.py

Then open http://localhost:8000 in your browser.

API Documentation:
    - Swagger UI: http://localhost:8000/docs
    - ReDoc: http://localhost:8000/redoc
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from council.config import load_config
from council.engine import CouncilEngine

# =============================================================================
# Logging Configuration
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent-council")

# =============================================================================
# Application Setup
# =============================================================================

# Load configuration
config = load_config(
    os.environ.get("COUNCIL_CONFIG", "config.yaml")
)

# Create the council engine
engine = CouncilEngine(config)


# Lifespan context manager (modern replacement for on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the FastAPI app."""
    # --- Startup ---
    status = await engine.check_lm_studio()
    if status["connected"]:
        logger.info(
            f"✅ Connected to LM Studio. "
            f"Available models: {status['models']}"
        )
    else:
        logger.warning(
            "⚠️  Cannot connect to LM Studio! "
            "Make sure LM Studio is running and the local server is started "
            "on port 1234 (Developer tab → Start Server)."
        )

    yield  # App runs here

    # --- Shutdown ---
    await engine.close()
    logger.info("Agent Council server shut down.")


# Create FastAPI app
app = FastAPI(
    title="Agent Council",
    description=(
        "A multi-agent AI debate and collaboration system. "
        "Run councils of local LLMs that debate, review, and collaborate "
        "to produce higher-quality answers."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware (allow all origins for local development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Middleware to disable caching on static files during development
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)


# =============================================================================
# REST API Endpoints
# =============================================================================


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """
    Serve the main web UI.

    Returns the ``index.html`` file from the static directory.
    """
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse(
        "<h1>Agent Council</h1>"
        "<p>Static files not found. Please ensure the 'static/' directory exists.</p>"
    )


@app.get("/test", response_class=HTMLResponse)
async def serve_test_ui():
    """Serve a minimal inline test page that proves agent card rendering works."""
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>Agent Council - Render Test</title>
<style>
body{background:#0d1117;color:#c9d1d9;font-family:system-ui;padding:20px;}
#output{max-width:700px;margin:0 auto;display:flex;flex-direction:column;gap:12px;}
.agent-card{background:#161b22;border:1px solid #30363d;border-radius:8px;border-left:3px solid #58a6ff;overflow:hidden;}
.agent-card-header{padding:10px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #21262d;}
.agent-avatar{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;color:white;background:#58a6ff;}
.agent-name{font-weight:600;font-size:13px;}
.agent-model{font-size:11px;color:#8b949e;padding:2px 8px;background:#21262d;border-radius:10px;}
.agent-card-body{padding:14px 16px;font-size:14px;line-height:1.7;white-space:pre-wrap;}
.status{font-size:12px;color:#8b949e;}
.round-sep{text-align:center;font-size:12px;color:#58a6ff;padding:4px;border-bottom:1px solid #21262d;}
button{background:#238636;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-size:14px;margin:10px 5px;}
button:hover{background:#2ea043;}
h2{text-align:center;}
#log{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px;margin-top:20px;max-height:200px;overflow-y:auto;font-size:11px;font-family:monospace;color:#8b949e;}
</style></head>
<body>
<h2>🏛️ Agent Council — Render Test</h2>
<div style="text-align:center;">
<button onclick="testLocal()">Test 1: Local Events</button>
<button onclick="testWebSocket()">Test 2: WebSocket Events</button>
</div>
<div id="output"></div>
<div id="log"></div>
<script>
var output = document.getElementById('output');
var logEl = document.getElementById('log');
var currentBody = null;
var currentCard = null;

function log(msg) {
    var d = document.createElement('div');
    d.textContent = new Date().toLocaleTimeString() + ' ' + msg;
    logEl.appendChild(d);
    logEl.scrollTop = logEl.scrollHeight;
    console.log(msg);
}

function addStatus(text) {
    var d = document.createElement('div');
    d.className = 'status';
    d.textContent = text;
    output.appendChild(d);
    log('STATUS: ' + text);
}

function addRound(n) {
    var d = document.createElement('div');
    d.className = 'round-sep';
    d.textContent = 'Round ' + n;
    output.appendChild(d);
    log('ROUND: ' + n);
}

function startCard(role, model) {
    finishCard();
    var card = document.createElement('div');
    card.className = 'agent-card';
    var initials = role.split(' ').map(function(w){return w[0];}).join('').substring(0,2);
    card.innerHTML = '<div class="agent-card-header">' +
        '<div class="agent-avatar">' + initials + '</div>' +
        '<span class="agent-name">' + role + '</span>' +
        '<span class="agent-model">' + (model||'') + '</span>' +
        '</div><div class="agent-card-body"></div>';
    output.appendChild(card);
    currentCard = card;
    currentBody = card.querySelector('.agent-card-body');
    log('CARD CREATED: ' + role + ' body=' + (!!currentBody));
}

function addChunk(text) {
    if (!currentBody) { log('WARN: chunk without body'); return; }
    currentBody.textContent += text;
}

function finishCard() {
    currentCard = null;
    currentBody = null;
}

function handleEvent(evt) {
    var t = evt.type;
    log('EVENT: ' + t + ' agent=' + (evt.agent||''));
    if (t === 'status') addStatus(evt.content);
    else if (t === 'round_start') addRound(evt.round);
    else if (t === 'agent_start') startCard(evt.agent, evt.metadata && evt.metadata.model || '');
    else if (t === 'agent_chunk') { if (!currentBody) startCard(evt.agent||'?',''); addChunk(evt.content); }
    else if (t === 'agent_done') finishCard();
    else if (t === 'moderator_start') startCard('Moderator', '');
    else if (t === 'moderator_chunk') { if (!currentBody) startCard('Moderator',''); addChunk(evt.content); }
    else if (t === 'moderator_done') finishCard();
    else if (t === 'model_loading') addStatus('Loading ' + (evt.agent||'model') + '...');
    else if (t === 'model_loaded') log('model loaded');
    else if (t === 'round_done') finishCard();
    else if (t === 'council_done') { finishCard(); addStatus('✅ Done!'); }
    else log('UNKNOWN: ' + t);
}

function testLocal() {
    output.innerHTML = '';
    logEl.innerHTML = '';
    log('Starting local test...');
    var events = [
        {type:'status',agent:'',content:'Starting council (debate)'},
        {type:'round_start',round:1,metadata:{total_rounds:1}},
        {type:'model_loading',agent:'Analyst',metadata:{model:'phi4-mini'}},
        {type:'model_loaded',agent:'Analyst',metadata:{model:'phi4-mini'}},
        {type:'agent_start',agent:'Analyst',round:1,metadata:{model:'phi4-mini'}},
        {type:'agent_chunk',agent:'Analyst',round:1,content:'The three-body problem '},
        {type:'agent_chunk',agent:'Analyst',round:1,content:'is a classic problem in physics '},
        {type:'agent_chunk',agent:'Analyst',round:1,content:'that has fascinated scientists for centuries.'},
        {type:'agent_done',agent:'Analyst',round:1},
        {type:'agent_start',agent:'Creative Thinker',round:1,metadata:{model:'llama-3b'}},
        {type:'agent_chunk',agent:'Creative Thinker',round:1,content:'From an artistic perspective, '},
        {type:'agent_chunk',agent:'Creative Thinker',round:1,content:'the three-body problem represents chaos and beauty.'},
        {type:'agent_done',agent:'Creative Thinker',round:1},
        {type:'round_done',round:1},
        {type:'moderator_start',agent:'Moderator'},
        {type:'moderator_chunk',agent:'Moderator',content:'After reviewing both perspectives, '},
        {type:'moderator_chunk',agent:'Moderator',content:'here is the synthesized answer.'},
        {type:'moderator_done',agent:'Moderator'},
        {type:'council_done',content:'Session complete'},
    ];
    events.forEach(function(evt,i){
        setTimeout(function(){ handleEvent(evt); }, i*150);
    });
}

function testWebSocket() {
    output.innerHTML = '';
    logEl.innerHTML = '';
    log('Connecting to /ws/test...');
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var ws = new WebSocket(protocol + '//' + location.host + '/ws/test');
    ws.onopen = function() {
        log('Connected, sending trigger');
        ws.send(JSON.stringify({type:'test'}));
    };
    ws.onmessage = function(e) {
        try { var data = JSON.parse(e.data); handleEvent(data); }
        catch(err) { log('ERROR: ' + err.message); }
    };
    ws.onclose = function() { log('WebSocket closed'); };
    ws.onerror = function() { log('WebSocket error'); };
}
</script>
</body></html>""")


@app.get("/api/health")
async def health_check():
    """
    Health check endpoint.

    Returns:
        Server status, LM Studio connectivity, and real system metrics.
    """
    import psutil

    lm_status = await engine.check_lm_studio()

    # Real CPU & RAM metrics
    cpu_pct  = psutil.cpu_percent(interval=None)
    ram      = psutil.virtual_memory()
    ram_pct  = ram.percent

    # GPU / VRAM via LM Studio models endpoint (best-effort)
    gpu_pct  = None
    vram_pct = None
    try:
        import httpx
        r = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: httpx.get("http://localhost:1234/v1/system/stats", timeout=1.0)
            ),
            timeout=1.5
        )
        if r.status_code == 200:
            s = r.json()
            gpu_pct  = s.get("gpu_usage")
            vram_pct = s.get("vram_usage")
    except Exception:
        pass

    return {
        "status": "ok",
        "lm_studio": lm_status,
        "system": {
            "cpu":  round(cpu_pct, 1),
            "ram":  round(ram_pct, 1),
            "gpu":  gpu_pct,
            "vram": vram_pct,
        },
    }


@app.get("/api/councils")
async def list_councils():
    """
    List all available council presets.

    Returns:
        Dictionary of council presets with their configurations.
    """
    return await engine.get_available_councils()


@app.get("/api/models")
async def list_models():
    """
    List all configured models.

    Returns:
        Dictionary of model configurations from config.yaml.
    """
    return await engine.get_available_models()


@app.get("/api/models/lm-studio")
async def list_lm_studio_models():
    """
    List models currently available in LM Studio.

    This queries LM Studio directly to see what models are downloaded
    and/or loaded.

    Returns:
        List of model info from LM Studio.
    """
    models = await engine.client.list_models()
    return {"models": models}


class ModelLoadRequest(BaseModel):
    """Request body for loading/unloading a model."""
    model: str


@app.post("/api/models/load")
async def load_model(request: ModelLoadRequest):
    """
    Load a model in LM Studio.

    Args:
        request: Contains the model identifier to load.

    Returns:
        Success status.
    """
    success = await engine.client.load_model(request.model)
    return {"success": success, "model": request.model}


@app.post("/api/models/unload")
async def unload_model(request: ModelLoadRequest):
    """
    Unload a model from LM Studio.

    Args:
        request: Contains the model identifier to unload.

    Returns:
        Success status.
    """
    success = await engine.client.unload_model(request.model)
    return {"success": success, "model": request.model}


@app.get("/api/config")
async def get_config():
    """
    Get the current council configuration.

    Returns:
        The full configuration including models, councils, and defaults.
    """
    return {
        "lm_studio": {
            "base_url": config.lm_studio.base_url,
        },
        "models": {
            k: {
                "name": v.name,
                "identifier": v.identifier,
                "strengths": v.strengths,
                "size": v.size,
            }
            for k, v in config.models.items()
        },
        "councils": await engine.get_available_councils(),
        "defaults": {
            "temperature": config.defaults.temperature,
            "max_tokens": config.defaults.max_tokens,
            "council": config.defaults.council,
        },
    }


# =============================================================================
# WebSocket Endpoint — Real-Time Council Sessions
# =============================================================================


@app.websocket("/ws/test")
async def test_websocket(websocket: WebSocket):
    """Test WebSocket that sends fake events to verify UI rendering."""
    await websocket.accept()
    logger.info("Test WebSocket client connected")

    try:
        raw = await websocket.receive_text()
        logger.info(f"Test WS received: {raw}")

        test_events = [
            {"type": "status", "agent": "", "round": 0, "content": "Starting Test Council (debate strategy)", "timestamp": "", "metadata": {}},
            {"type": "round_start", "agent": "", "round": 1, "content": "Round 1 of 1", "timestamp": "", "metadata": {"total_rounds": 1}},
            {"type": "model_loading", "agent": "Test Analyst", "round": 0, "content": "Loading model...", "timestamp": "", "metadata": {"model": "phi4-mini"}},
            {"type": "model_loaded", "agent": "Test Analyst", "round": 0, "content": "Model ready", "timestamp": "", "metadata": {"model": "phi4-mini"}},
            {"type": "agent_start", "agent": "Test Analyst", "round": 1, "content": "", "timestamp": "", "metadata": {"model": "phi4-mini"}},
        ]

        for evt in test_events:
            logger.info(f"[Test WS] Sending: {evt['type']} agent={evt['agent']}")
            await websocket.send_json(evt)
            await asyncio.sleep(0.1)

        # Send chunks
        for word in "Hello this is a test response from the fake council session. If you can see this card, WebSocket streaming works! ".split():
            await websocket.send_json({
                "type": "agent_chunk", "agent": "Test Analyst", "round": 1,
                "content": word + " ", "timestamp": "", "metadata": {},
            })
            await asyncio.sleep(0.05)

        await websocket.send_json({"type": "agent_done", "agent": "Test Analyst", "round": 1, "content": "", "timestamp": "", "metadata": {}})
        await asyncio.sleep(0.1)
        await websocket.send_json({"type": "council_done", "agent": "", "round": 0, "content": "Council session complete", "timestamp": "", "metadata": {}})

        logger.info("[Test WS] All test events sent")

    except WebSocketDisconnect:
        logger.info("Test WebSocket disconnected")
    except Exception as e:
        logger.exception(f"Test WebSocket error: {e}")


@app.websocket("/ws/council")
async def council_websocket(websocket: WebSocket):
    await _run_council_websocket_stable(websocket)


async def _run_council_websocket_stable(websocket: WebSocket):
    """
    Stable council endpoint.

    This endpoint avoids token streaming and sends only full responses from each
    agent/moderator turn. It is intentionally simpler and more reliable.
    """
    await websocket.accept()
    logger.info("WebSocket client connected")

    async def send_event(
        event_type: str,
        content: str = "",
        agent: str = "",
        round_num: int = 0,
        metadata: dict[str, Any] | None = None,
    ):
        await websocket.send_json({
            "type": event_type,
            "agent": agent,
            "round": round_num,
            "content": content,
            "timestamp": "",
            "metadata": metadata or {},
        })

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await send_event("error", "Invalid JSON message")
                continue

            if message.get("type") != "task":
                await send_event("error", "Unknown message type. Expected 'task'.")
                continue

            council_key = message.get("council", config.defaults.council)
            task = message.get("task", "").strip()
            settings = message.get("settings", {})
            model_overrides = message.get("model_overrides", {})

            if not task:
                await send_event("error", "Task cannot be empty.")
                continue

            if council_key not in config.councils:
                await send_event(
                    "error",
                    f"Council '{council_key}' not found. Available: {list(config.councils.keys())}",
                )
                continue

            preset = config.councils[council_key]
            if not preset.moderator:
                await send_event("error", f"Council '{council_key}' has no moderator configured.")
                continue

            temperature = settings.get("temperature", config.defaults.temperature)
            max_tokens = settings.get("max_tokens", config.defaults.max_tokens)
            debate_rounds = settings.get("debate_rounds", preset.debate_rounds)

            await send_event(
                "status",
                f"Starting {preset.name} ({preset.strategy.value} strategy)",
                metadata={
                    "council": council_key,
                    "strategy": preset.strategy.value,
                    "debate_rounds": debate_rounds,
                },
            )

            try:
                agents = engine._create_agents(preset.agents, model_overrides if model_overrides else None)
                moderator = engine._create_moderator(preset.moderator, model_overrides if model_overrides else None)

                all_messages: list[dict[str, Any]] = []

                async def run_agent_turn(agent, round_num: int, messages: list[dict[str, str]]):
                    await send_event(
                        "model_loading",
                        f"Loading model {agent.model_identifier}...",
                        agent=agent.role,
                        round_num=round_num,
                        metadata={"model": agent.model_identifier},
                    )
                    await engine.client.ensure_model_loaded(agent.model_identifier)
                    await send_event(
                        "model_loaded",
                        f"Model {agent.model_identifier} ready",
                        agent=agent.role,
                        round_num=round_num,
                        metadata={"model": agent.model_identifier},
                    )

                    await send_event(
                        "agent_start",
                        agent=agent.role,
                        round_num=round_num,
                        metadata={"model": agent.model_key},
                    )
                    response = await engine.client.chat_once(
                        model_identifier=agent.model_identifier,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    if not response.strip():
                        response = "[No response text returned by model]"

                    await send_event(
                        "agent_done",
                        content=response,
                        agent=agent.role,
                        round_num=round_num,
                        metadata={"model": agent.model_key},
                    )
                    return response

                if preset.strategy.value == "debate":
                    for round_num in range(1, debate_rounds + 1):
                        await send_event(
                            "round_start",
                            f"Round {round_num} of {debate_rounds}",
                            round_num=round_num,
                            metadata={"total_rounds": debate_rounds},
                        )
                        for agent in agents:
                            history = all_messages if round_num > 1 else None
                            messages = agent.build_messages(task=task, history=history, round_num=round_num)
                            response = await run_agent_turn(agent, round_num, messages)
                            all_messages.append({
                                "role": agent.role,
                                "content": response,
                                "round": round_num,
                            })
                        await send_event("round_done", f"Round {round_num} complete", round_num=round_num)

                elif preset.strategy.value == "pipeline":
                    await send_event("round_start", "Pipeline processing", round_num=1)
                    previous_output = ""
                    for step_num, agent in enumerate(agents, 1):
                        if step_num == 1:
                            strategy_context = (
                                f"You are step {step_num} of {len(agents)} in a pipeline. "
                                "Create the initial solution."
                            )
                        else:
                            previous_role = agents[step_num - 2].role
                            strategy_context = (
                                f"You are step {step_num} of {len(agents)} in a pipeline. "
                                f"Build upon the previous output from {previous_role}.\n\n"
                                f"Previous output:\n{previous_output}"
                            )
                        messages = agent.build_messages(
                            task=task,
                            round_num=1,
                            strategy_context=strategy_context,
                        )
                        response = await run_agent_turn(agent, step_num, messages)
                        previous_output = response
                        all_messages.append({
                            "role": agent.role,
                            "content": response,
                            "round": step_num,
                        })
                    await send_event("round_done", "Pipeline complete", round_num=1)

                else:
                    await send_event("round_start", "Collecting independent votes", round_num=1)
                    for agent in agents:
                        messages = agent.build_messages(task=task, history=None, round_num=1)
                        response = await run_agent_turn(agent, 1, messages)
                        all_messages.append({
                            "role": agent.role,
                            "content": response,
                            "round": 1,
                        })
                    await send_event("round_done", "All votes collected", round_num=1)

                await send_event("moderator_start", "Synthesizing...", agent="Moderator")
                await send_event(
                    "model_loading",
                    f"Loading model {moderator.model_identifier}...",
                    agent="Moderator",
                    metadata={"model": moderator.model_identifier},
                )
                await engine.client.ensure_model_loaded(moderator.model_identifier)
                await send_event(
                    "model_loaded",
                    f"Model {moderator.model_identifier} ready",
                    agent="Moderator",
                    metadata={"model": moderator.model_identifier},
                )

                moderator_messages = moderator.build_moderator_messages(
                    task=task,
                    all_messages=all_messages,
                    strategy=preset.strategy.value,
                )
                moderator_response = await engine.client.chat_once(
                    model_identifier=moderator.model_identifier,
                    messages=moderator_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if not moderator_response.strip():
                    moderator_response = "[No moderator response text returned]"

                await send_event(
                    "moderator_done",
                    content=moderator_response,
                    agent="Moderator",
                    metadata={"model": moderator.model_key},
                )
                await send_event("council_done", "Council session complete")

            except Exception as session_error:
                logger.exception(f"Council session failed: {session_error}")
                await send_event("error", f"Council session failed: {str(session_error)}")

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")


# =============================================================================
# Entry Point
# =============================================================================


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 60)
    print("  🏛️  Agent Council — Multi-Agent AI System")
    print("=" * 60)
    print(f"  Server:  http://localhost:8000")
    print(f"  API Docs: http://localhost:8000/docs")
    print(f"  Config:  {os.path.abspath('config.yaml')}")
    print("=" * 60 + "\n")

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
