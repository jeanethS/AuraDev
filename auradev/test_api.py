"""Quick integration test for auradev API."""
import json
import threading
import time
import urllib.request

import pytest

from main import auradev

BASE_URL = "http://localhost:8765"


def fetch(path):
    with urllib.request.urlopen(BASE_URL + path, timeout=5) as resp:
        return json.loads(resp.read().decode())


@pytest.fixture(scope="module")
def auradev_app():
    app = auradev(demo_mode=True, sample_interval=2, max_cycles=2)

    def run_app():
        try:
            app.start()
        except SystemExit:
            pass

    thread = threading.Thread(target=run_app)
    thread.start()

    # Wait for server to be ready
    for _ in range(20):
        try:
            with urllib.request.urlopen(BASE_URL + "/api/health", timeout=0.5) as resp:
                if resp.status == 200:
                    break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        pytest.fail("API server failed to start")

    # Wait for the app to finish its demo cycles
    thread.join(timeout=15)

    yield app

    app.stop()


def test_health(auradev_app):
    data = fetch("/api/health")
    assert data.get("status") == "ok"
    assert data.get("session_id") is not None


def test_dashboard_home(auradev_app):
    with urllib.request.urlopen(BASE_URL + "/", timeout=5) as resp:
        html = resp.read().decode()
    assert resp.status == 200
    assert "AURADEV" in html
    assert "Focus Dashboard" in html


def test_sessions(auradev_app):
    sessions = fetch("/api/sessions")
    assert isinstance(sessions, list)
    assert len(sessions) > 0


def test_latest(auradev_app):
    latest = fetch("/api/sessions/latest")
    assert isinstance(latest, list)
    assert len(latest) == 2


def test_insights(auradev_app):
    data = fetch("/api/insights")
    assert "total_sessions" in data
    assert "total_cycles" in data
    assert "avg_flow_pct" in data
    assert "avg_wpm_by_state" in data
    assert "peak_hours" in data
    assert "avg_session_duration_minutes" in data
    assert data["total_cycles"] >= 2  # demo ran 2 cycles


def test_habits(auradev_app):
    data = fetch("/api/habits")
    assert "flow_by_day" in data
    assert "flow_by_hour" in data
    assert "window_correlations" in data
    assert isinstance(data["flow_by_day"], dict)
    assert isinstance(data["flow_by_hour"], dict)
    assert isinstance(data["window_correlations"], list)


def test_chrome_devtools_json(auradev_app):
    data = fetch("/.well-known/appspecific/com.chrome.devtools.json")
    assert "workspace" in data
    assert "root" in data["workspace"]
    assert "uuid" in data["workspace"]
    assert isinstance(data["workspace"]["root"], str)
    assert isinstance(data["workspace"]["uuid"], str)

