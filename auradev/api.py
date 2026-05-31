"""FastAPI server for AURADEV session data."""

import json
import os
from pathlib import Path
import getpass

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import get_all_sessions, get_session_cycles, get_insights, get_habits, init_db, save_cycle
from config import API_PORT


def get_current_user(x_user_id: Optional[str] = Header(None)) -> str:
    """Extract user_id from X-User-Id header or fallback to system username.
    
    Args:
        x_user_id: Optional X-User-Id header value
        
    Returns:
        User identifier (header value or system username)
        
    Notes:
        - No 401 errors for local dev (graceful fallback)
        - Header takes precedence when provided
        - Falls back to USER_ID env var, then system username
    """
    if x_user_id:
        return x_user_id
    
    # Fallback to USER_ID env var
    env_user = os.getenv("USER_ID")
    if env_user:
        return env_user
    
    # Final fallback to system username
    try:
        return getpass.getuser()
    except Exception:
        return "default"


# Initialize database on startup with default user
init_db("default")

DASHBOARD_DIR = Path(__file__).resolve().parent / "dashboard"

app = FastAPI(title="AURADEV API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "session_id": getattr(app.state, "session_id", None),
    }


@app.get("/api/sessions")
def sessions(user_id: str = Header(None, alias="X-User-Id")):
    """Get all sessions for the authenticated user."""
    current_user = get_current_user(user_id)
    rows = get_all_sessions(current_user)
    for row in rows:
        row["state_breakdown"] = json.loads(row["state_breakdown"])
    return rows


@app.get("/api/sessions/latest")
def latest_session(user_id: str = Header(None, alias="X-User-Id")):
    """Get latest session cycles for the authenticated user."""
    current_user = get_current_user(user_id)
    rows = get_all_sessions(current_user)
    if not rows:
        return []
    return get_session_cycles(rows[0]["session_id"], current_user)


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str, user_id: str = Header(None, alias="X-User-Id")):
    """Get session details for the authenticated user."""
    current_user = get_current_user(user_id)
    return get_session_cycles(session_id, current_user)


@app.get("/api/insights")
def insights(user_id: str = Header(None, alias="X-User-Id")):
    """Aggregate stats across all sessions for the authenticated user."""
    current_user = get_current_user(user_id)
    return get_insights(current_user)


@app.get("/api/habits")
def habits(user_id: str = Header(None, alias="X-User-Id")):
    """Cross-session behavioral patterns for the authenticated user."""
    current_user = get_current_user(user_id)
    return get_habits(current_user)


# --- Sync endpoint for local app to push data to cloud ---

class CycleData(BaseModel):
    session_id: str
    state: str
    confidence: float = 0.0
    reason: str = ""
    wpm: float = 0.0
    backspace_ratio: float = 0.0
    window_switches: int = 0
    mouse_distance: float = 0.0
    cpu_percent: float = 0.0
    idle_seconds: float = 0.0
    active_window: str = ""


@app.post("/api/sync")
def sync_cycle(data: CycleData, user_id: str = Header(None, alias="X-User-Id")):
    """Receive cycle data from local app and save to cloud DB."""
    current_user = get_current_user(user_id)
    metrics = {
        "wpm": data.wpm,
        "backspace_ratio": data.backspace_ratio,
        "window_switches": data.window_switches,
        "mouse_distance": data.mouse_distance,
        "cpu_percent": data.cpu_percent,
        "idle_seconds": data.idle_seconds,
        "active_window": data.active_window,
    }
    classification = {
        "state": data.state,
        "confidence": data.confidence,
        "reason": data.reason,
    }
    save_cycle(data.session_id, metrics, classification, current_user)
    return {"status": "ok", "session_id": data.session_id, "user_id": current_user}


if DASHBOARD_DIR.is_dir():

    @app.get("/", include_in_schema=False)
    def dashboard_home():
        index = DASHBOARD_DIR / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Dashboard not found")
        return FileResponse(index, media_type="text/html")

    app.mount(
        "/",
        StaticFiles(directory=str(DASHBOARD_DIR), html=True),
        name="dashboard",
    )
