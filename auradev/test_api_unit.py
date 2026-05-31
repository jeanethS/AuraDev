"""
Unit tests for api.py – FastAPI endpoint coverage.

Uses FastAPI's TestClient (via httpx) to test every endpoint in isolation.
All database calls are mocked so no real SQLite is touched.

Covers:
  - GET /api/health
  - GET /api/sessions          (with / without X-User-Id header)
  - GET /api/sessions/latest   (no sessions, with sessions)
  - GET /api/sessions/{id}
  - GET /api/insights
  - GET /api/habits
  - POST /api/sync
  - GET /.well-known/appspecific/com.chrome.devtools.json
  - get_current_user()         (header / env / getpass / default)
"""

import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Patch heavy imports before api.py is imported so tests stay fast.
# ---------------------------------------------------------------------------

# Minimal config stub
_fake_config = types.ModuleType("config")
_fake_config.API_PORT = 8765
_fake_config.LOG_FILE = "test_session.log"
_fake_config.SYNC_URL = None
_fake_config.LYRIA_PROJECT_ID = None
_fake_config.GOOGLE_APPLICATION_CREDENTIALS = None
_fake_config.ANTHROPIC_API_KEY = None
_fake_config.CLASSIFIER_MODEL = "claude-opus-4-7"
_fake_config.SAMPLE_INTERVAL = 30
_fake_config.CROSSFADE_SECONDS = 3.0
_fake_config.VOLUME = 0.35
_fake_config.DB_FILE = ":memory:"
_fake_config.STATES = ["flow", "stuck", "debugging", "reviewing", "context_switching"]
_fake_config.CHORDS = {}
_fake_config.CORS_ORIGINS = ["*"]
sys.modules["config"] = _fake_config

# Comprehensive database stub – overwrite any minimal stub installed by other test files.
_fake_db = types.ModuleType("database")
_fake_db.init_db = MagicMock()
_fake_db.save_cycle = MagicMock()
_fake_db.get_all_sessions = MagicMock(return_value=[])
_fake_db.get_session_cycles = MagicMock(return_value=[])
_fake_db.get_insights = MagicMock(return_value={})
_fake_db.get_habits = MagicMock(return_value={})
sys.modules["database"] = _fake_db

# rate_limiter stub (pass-through middleware) – overwrite any previous stub.
_fake_rl = types.ModuleType("rate_limiter")

async def _pass_through_middleware(request, call_next):
    return await call_next(request)

_fake_rl.rate_limit_middleware = _pass_through_middleware
sys.modules["rate_limiter"] = _fake_rl

import api as api_module  # noqa: E402
from api import app, get_current_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_row(session_id: str = "sess-abc"):
    return {
        "session_id": session_id,
        "start_time": "2026-05-30T10:00:00",
        "end_time": "2026-05-30T11:00:00",
        "total_cycles": 5,
        "state_breakdown": json.dumps({"flow": 3, "stuck": 2}),
    }


def _make_cycle_row():
    return {
        "id": 1,
        "session_id": "sess-abc",
        "timestamp": "2026-05-30T10:00:00",
        "state": "flow",
        "confidence": 0.92,
        "reason": "high wpm",
        "wpm": 60.0,
        "backspace_ratio": 0.05,
        "window_switches": 2,
        "mouse_distance": 100.0,
        "cpu_percent": 20.0,
        "idle_seconds": 1.0,
        "active_window": "VSCode",
    }


@pytest.fixture(autouse=True)
def reset_db_mocks():
    """Reset all database mocks before each test."""
    _fake_db.init_db.reset_mock()
    _fake_db.save_cycle.reset_mock()
    _fake_db.get_all_sessions.reset_mock()
    _fake_db.get_session_cycles.reset_mock()
    _fake_db.get_insights.reset_mock()
    _fake_db.get_habits.reset_mock()
    _fake_db.get_all_sessions.return_value = []
    _fake_db.get_session_cycles.return_value = []
    _fake_db.get_insights.return_value = {}
    _fake_db.get_habits.return_value = {}


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_ok_status(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_includes_session_id_key(self, client):
        resp = client.get("/api/health")
        assert "session_id" in resp.json()


# ---------------------------------------------------------------------------
# /api/sessions
# ---------------------------------------------------------------------------

class TestSessions:
    def test_returns_empty_list_when_no_sessions(self, client):
        _fake_db.get_all_sessions.return_value = []
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_sessions_for_user(self, client):
        row = _make_session_row()
        _fake_db.get_all_sessions.return_value = [row]
        resp = client.get("/api/sessions", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["session_id"] == "sess-abc"
        assert isinstance(data[0]["state_breakdown"], dict)  # JSON-decoded

    def test_state_breakdown_is_decoded_from_json(self, client):
        row = _make_session_row()
        _fake_db.get_all_sessions.return_value = [row]
        resp = client.get("/api/sessions")
        data = resp.json()
        assert data[0]["state_breakdown"] == {"flow": 3, "stuck": 2}

    def test_user_id_passed_to_db(self, client):
        _fake_db.get_all_sessions.return_value = []
        client.get("/api/sessions", headers={"X-User-Id": "carol"})
        _fake_db.get_all_sessions.assert_called_once_with("carol")


# ---------------------------------------------------------------------------
# /api/sessions/latest
# ---------------------------------------------------------------------------

class TestLatestSession:
    def test_returns_empty_list_when_no_sessions(self, client):
        _fake_db.get_all_sessions.return_value = []
        resp = client.get("/api/sessions/latest")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_cycles_for_most_recent_session(self, client):
        row = _make_session_row("sess-latest")
        _fake_db.get_all_sessions.return_value = [row]
        _fake_db.get_session_cycles.return_value = [_make_cycle_row()]
        resp = client.get("/api/sessions/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["state"] == "flow"

    def test_calls_get_session_cycles_with_first_session_id(self, client):
        row = _make_session_row("first-sess")
        _fake_db.get_all_sessions.return_value = [row]
        _fake_db.get_session_cycles.return_value = []
        client.get("/api/sessions/latest", headers={"X-User-Id": "bob"})
        _fake_db.get_session_cycles.assert_called_once_with("first-sess", "bob")


# ---------------------------------------------------------------------------
# /api/sessions/{session_id}
# ---------------------------------------------------------------------------

class TestSessionDetail:
    def test_returns_cycles_for_session(self, client):
        _fake_db.get_session_cycles.return_value = [_make_cycle_row()]
        resp = client.get("/api/sessions/sess-123", headers={"X-User-Id": "dave"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_user_id_forwarded_to_db(self, client):
        _fake_db.get_session_cycles.return_value = []
        client.get("/api/sessions/sess-xyz", headers={"X-User-Id": "eve"})
        _fake_db.get_session_cycles.assert_called_once_with("sess-xyz", "eve")

    def test_returns_empty_list_for_unknown_session(self, client):
        _fake_db.get_session_cycles.return_value = []
        resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# /api/insights
# ---------------------------------------------------------------------------

class TestInsights:
    def test_returns_insights_payload(self, client):
        expected = {
            "total_sessions": 3,
            "total_cycles": 12,
            "avg_flow_pct": 60.0,
            "avg_wpm_by_state": {"flow": 65.0},
            "peak_hours": [10, 14],
            "avg_session_duration_minutes": 42.0,
        }
        _fake_db.get_insights.return_value = expected
        resp = client.get("/api/insights", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        assert resp.json() == expected

    def test_passes_user_id_to_db(self, client):
        _fake_db.get_insights.return_value = {}
        client.get("/api/insights", headers={"X-User-Id": "frank"})
        _fake_db.get_insights.assert_called_once_with("frank")


# ---------------------------------------------------------------------------
# /api/habits
# ---------------------------------------------------------------------------

class TestHabits:
    def test_returns_habits_payload(self, client):
        expected = {
            "flow_by_day": {"Monday": 40.0},
            "flow_by_hour": {"10": 55.0},
            "window_correlations": [{"window": "VSCode", "flow_pct": 70.0}],
        }
        _fake_db.get_habits.return_value = expected
        resp = client.get("/api/habits", headers={"X-User-Id": "alice"})
        assert resp.status_code == 200
        assert resp.json() == expected

    def test_passes_user_id_to_db(self, client):
        _fake_db.get_habits.return_value = {}
        client.get("/api/habits", headers={"X-User-Id": "grace"})
        _fake_db.get_habits.assert_called_once_with("grace")


# ---------------------------------------------------------------------------
# POST /api/sync
# ---------------------------------------------------------------------------

class TestSyncCycle:
    VALID_PAYLOAD = {
        "session_id": "sync-sess-1",
        "state": "debugging",
        "confidence": 0.75,
        "reason": "high backspace ratio",
        "wpm": 30.0,
        "backspace_ratio": 0.35,
        "window_switches": 5,
        "mouse_distance": 80.0,
        "cpu_percent": 45.0,
        "idle_seconds": 0.0,
        "active_window": "Terminal",
    }

    def test_returns_ok_with_session_and_user_id(self, client):
        resp = client.post(
            "/api/sync",
            json=self.VALID_PAYLOAD,
            headers={"X-User-Id": "henry"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["session_id"] == "sync-sess-1"
        assert data["user_id"] == "henry"

    def test_calls_save_cycle_with_correct_data(self, client):
        client.post(
            "/api/sync",
            json=self.VALID_PAYLOAD,
            headers={"X-User-Id": "henry"},
        )
        _fake_db.save_cycle.assert_called_once()
        args = _fake_db.save_cycle.call_args[0]
        assert args[0] == "sync-sess-1"
        assert args[1]["wpm"] == 30.0
        assert args[2]["state"] == "debugging"
        assert args[3] == "henry"

    def test_uses_default_user_when_no_header(self, client):
        resp = client.post("/api/sync", json=self.VALID_PAYLOAD)
        assert resp.status_code == 200
        # user_id should be a non-empty string (system username or "default")
        assert len(resp.json()["user_id"]) > 0

    def test_missing_required_fields_returns_422(self, client):
        resp = client.post("/api/sync", json={"state": "flow"})  # missing session_id
        assert resp.status_code == 422

    def test_defaults_are_applied_for_optional_fields(self, client):
        minimal = {"session_id": "s", "state": "flow"}
        resp = client.post("/api/sync", json=minimal, headers={"X-User-Id": "u"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /.well-known/appspecific/com.chrome.devtools.json
# ---------------------------------------------------------------------------

class TestChromeDevToolsJson:
    def test_returns_workspace_key(self, client):
        resp = client.get("/.well-known/appspecific/com.chrome.devtools.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "workspace" in data

    def test_workspace_has_root_and_uuid(self, client):
        resp = client.get("/.well-known/appspecific/com.chrome.devtools.json")
        workspace = resp.json()["workspace"]
        assert "root" in workspace
        assert "uuid" in workspace

    def test_uuid_is_stable_across_calls(self, client):
        r1 = client.get("/.well-known/appspecific/com.chrome.devtools.json").json()
        r2 = client.get("/.well-known/appspecific/com.chrome.devtools.json").json()
        assert r1["workspace"]["uuid"] == r2["workspace"]["uuid"]

    def test_root_is_a_string_path(self, client):
        resp = client.get("/.well-known/appspecific/com.chrome.devtools.json")
        root = resp.json()["workspace"]["root"]
        assert isinstance(root, str)
        assert len(root) > 0


# ---------------------------------------------------------------------------
# get_current_user helper
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    def test_returns_header_value_when_provided(self):
        result = get_current_user(x_user_id="my-user")
        assert result == "my-user"

    def test_returns_env_user_id_when_no_header(self):
        with patch.dict(os.environ, {"USER_ID": "env-alice"}):
            result = get_current_user(x_user_id=None)
        assert result == "env-alice"

    def test_returns_getpass_username_as_fallback(self):
        env_without = {k: v for k, v in os.environ.items() if k != "USER_ID"}
        with patch.dict(os.environ, env_without, clear=True):
            with patch("api.getpass.getuser", return_value="sys-user"):
                result = get_current_user(x_user_id=None)
        assert result == "sys-user"

    def test_returns_default_when_getpass_fails(self):
        env_without = {k: v for k, v in os.environ.items() if k != "USER_ID"}
        with patch.dict(os.environ, env_without, clear=True):
            with patch("api.getpass.getuser", side_effect=Exception("no tty")):
                result = get_current_user(x_user_id=None)
        assert result == "default"

    def test_header_takes_precedence_over_env(self):
        with patch.dict(os.environ, {"USER_ID": "env-user"}):
            result = get_current_user(x_user_id="header-user")
        assert result == "header-user"
