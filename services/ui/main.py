import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from draft_builder_lib import build_and_save_draft
from draft_engine import apply_human_pick, init_state, load_state, save_state

DRAFTS_DIR    = Path(os.getenv("DRAFTS_DIR",    "/drafts"))
IMAGE_DIR     = Path(os.getenv("IMAGE_CACHE_DIR", "/cache/images"))
DATABASE_URL  = os.getenv("DATABASE_URL", "postgresql://cubesim:cubesim@db:5432/cubesim")

app = FastAPI()


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _draft_summary(draft_dir: Path) -> dict:
    state = load_state(draft_dir)
    if state:
        status        = state["status"]
        current_pack  = state.get("current_pack", 1)
        drafted_count = len(state["drafted"].get("0", []))
    elif (draft_dir / "drafted" / "player_1.json").exists():
        status        = "complete"
        current_pack  = 4
        data          = json.loads((draft_dir / "drafted" / "player_1.json").read_text())
        drafted_count = data.get("total_drafted", 0)
    else:
        status        = "not_started"
        current_pack  = 1
        drafted_count = 0

    created_at = None
    draft_id   = draft_dir.name
    manifest   = draft_dir / "sealed" / "manifest.json"
    if manifest.exists():
        try:
            m          = json.loads(manifest.read_text())
            created_at = m.get("created_at")
            draft_id   = m.get("draft_id", draft_dir.name)
        except Exception:
            pass

    return {
        "draft_id":          draft_id,
        "name":              draft_dir.name,
        "created_at":        created_at,
        "status":            status,
        "current_pack":      current_pack,
        "cards_drafted_human": drafted_count,
    }


def _find_draft_dir(draft_name: str) -> Path:
    """Accept either the full directory name or the UUID portion."""
    direct = DRAFTS_DIR / draft_name
    if direct.is_dir():
        return direct
    matches = [d for d in DRAFTS_DIR.iterdir() if d.is_dir() and draft_name in d.name]
    if not matches:
        raise HTTPException(404, f"Draft not found: {draft_name}")
    return matches[0]


def _state_to_response(state: dict) -> dict:
    packs = state.get("current_player_packs", [[]])
    human_pack = packs[0] if packs else []
    return {
        "draft_id":              state["draft_id"],
        "status":                state["status"],
        "current_pack":          state.get("current_pack"),
        "current_pass":          state.get("current_pass"),
        "picks_per_pass":        state.get("picks_per_pass"),
        "human_picks_remaining": state.get("human_picks_remaining", 0),
        "current_pack_cards":    human_pack if state["status"] == "in_progress" else [],
        "drafted_human":         state["drafted"].get("0", []),
    }


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.get("/api/drafts")
def list_drafts():
    if not DRAFTS_DIR.exists():
        return []
    dirs = sorted(
        (d for d in DRAFTS_DIR.iterdir() if d.is_dir() and d.name.startswith("draft-")),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return [_draft_summary(d) for d in dirs]


@app.post("/api/drafts")
def create_draft():
    draft_dir = build_and_save_draft(DATABASE_URL, DRAFTS_DIR)
    return _draft_summary(draft_dir)


@app.get("/api/drafts/{draft_name}")
def get_draft(draft_name: str):
    draft_dir = _find_draft_dir(draft_name)
    state = load_state(draft_dir)
    if state:
        return _state_to_response(state)
    return _draft_summary(draft_dir)


@app.post("/api/drafts/{draft_name}/start")
def start_draft(draft_name: str):
    draft_dir = _find_draft_dir(draft_name)
    state = load_state(draft_dir)
    if state and state["status"] != "not_started":
        return _state_to_response(state)
    state = init_state(draft_dir)
    save_state(draft_dir, state)
    return _state_to_response(state)


class PickRequest(BaseModel):
    card_id: str


@app.post("/api/drafts/{draft_name}/pick")
def pick_card(draft_name: str, body: PickRequest):
    draft_dir = _find_draft_dir(draft_name)
    state = load_state(draft_dir)
    if not state or state["status"] != "in_progress":
        raise HTTPException(400, "Draft is not in progress")

    human_pack = state["current_player_packs"][0]
    if not any(c["id"] == body.card_id for c in human_pack):
        raise HTTPException(400, "Card not in current pack")

    state = apply_human_pick(state, body.card_id, draft_dir)
    return _state_to_response(state)


@app.get("/api/drafts/{draft_name}/pool")
def get_pool(draft_name: str):
    draft_dir = _find_draft_dir(draft_name)
    pool_path = draft_dir / "drafted" / "player_1.json"
    if pool_path.exists():
        return json.loads(pool_path.read_text())
    state = load_state(draft_dir)
    if state and state["status"] == "complete":
        cards = state["drafted"].get("0", [])
        return {
            "draft_id":      state["draft_id"],
            "player":        1,
            "is_human":      True,
            "total_drafted": len(cards),
            "cards":         cards,
        }
    raise HTTPException(404, "Draft not complete")


@app.get("/api/images/{card_id}")
def get_image(card_id: str):
    if "/" in card_id or ".." in card_id:
        raise HTTPException(400, "Invalid card ID")
    path = IMAGE_DIR / f"{card_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "Image not cached")
    return FileResponse(path, media_type="image/jpeg")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".js", ".css", ".html")) or path == "/":
        response.headers["Cache-Control"] = "no-store"
    return response


# Static files — must be mounted last
app.mount("/", StaticFiles(directory="static", html=True), name="static")
