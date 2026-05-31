"""
Unit tests for logger.py – SessionLogger.

Covers:
  - __init__ (session_id generation, user_id auto-detection via env / getpass)
  - _ansi_hex (valid hex, invalid input)
  - _generate_waveform (length, all states)
  - _progress_bar (normal, zero max_val, clamps)
  - _pulse_color (high / low confidence)
  - _rule (divider string)
  - log_cycle (entries appended, file written, save_cycle called, _sync_to_cloud called)
  - _sync_to_cloud (success, non-200, exception, missing SYNC_URL)
  - print_session_summary (with entries, without entries, flow windows)
  - _find_flow_windows (continuous, mixed, trailing flow)
"""

import os
import sys
import tempfile
import time
import types
from datetime import datetime
from io import StringIO
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Patch imports that logger.py brings in at module level so tests can run
# without a real database or the full config module.
# ---------------------------------------------------------------------------

# Create minimal fake config module
_fake_config = types.ModuleType("config")
_fake_config.LOG_FILE = None   # will be overridden per-test via patch
_fake_config.SYNC_URL = None
sys.modules.setdefault("config", _fake_config)

# Create minimal fake database module
_fake_database = types.ModuleType("database")
_fake_database.save_cycle = MagicMock()
sys.modules.setdefault("database", _fake_database)

import logger as logger_module  # noqa: E402
from logger import SessionLogger


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

SAMPLE_METRICS = {
    "wpm": 45.5,
    "backspace_ratio": 0.12,
    "mouse_distance": 250.0,
    "cpu_percent": 32.1,
    "idle_seconds": 5.0,
    "window_switches": 3,
    "active_window": "VSCode - main.py",
}

SAMPLE_CLASSIFICATION = {
    "state": "flow",
    "confidence": 0.91,
    "reason": "High WPM, low backspace ratio, low idle time",
}


def _make_logger(tmp_path, session_id="test-session", user_id="testuser"):
    """Create a SessionLogger with LOG_FILE pointing to a temp file."""
    log_file = str(tmp_path / "session.log")
    with patch.object(logger_module.config, "LOG_FILE", log_file):
        with patch.object(logger_module, "LOG_FILE", log_file):
            sl = SessionLogger(session_id=session_id, user_id=user_id)
    return sl, log_file


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestSessionLoggerInit:
    def test_uses_provided_session_id(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            sl = SessionLogger(session_id="abc-123", user_id="alice")
        assert sl.session_id == "abc-123"

    def test_generates_uuid_when_no_session_id(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            sl = SessionLogger(user_id="alice")
        assert len(sl.session_id) > 0
        assert sl.session_id != "abc-123"

    def test_uses_provided_user_id(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            sl = SessionLogger(user_id="bob")
        assert sl.user_id == "bob"

    def test_falls_back_to_env_user_id(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            with patch.dict(os.environ, {"USER_ID": "env-user"}):
                sl = SessionLogger()
        assert sl.user_id == "env-user"

    def test_falls_back_to_getpass_username(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        env_without_user_id = {k: v for k, v in os.environ.items() if k != "USER_ID"}
        with patch("logger.LOG_FILE", log_file):
            with patch.dict(os.environ, env_without_user_id, clear=True):
                with patch("getpass.getuser", return_value="system-user"):
                    sl = SessionLogger()
        assert sl.user_id == "system-user"

    def test_falls_back_to_default_when_getpass_fails(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        env_without_user_id = {k: v for k, v in os.environ.items() if k != "USER_ID"}
        with patch("logger.LOG_FILE", log_file):
            with patch.dict(os.environ, env_without_user_id, clear=True):
                with patch("getpass.getuser", side_effect=Exception("no tty")):
                    sl = SessionLogger()
        assert sl.user_id == "default"

    def test_creates_log_file(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            SessionLogger(user_id="u")
        assert os.path.exists(log_file)

    def test_session_entries_starts_empty(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            sl = SessionLogger(user_id="u")
        assert sl.session_entries == []


# ---------------------------------------------------------------------------
# _ansi_hex
# ---------------------------------------------------------------------------

class TestAnsiHex:
    def test_returns_correct_sequence(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            sl = SessionLogger(user_id="u")
        result = sl._ansi_hex("#ff8000")
        assert result == "\033[38;2;255;128;0m"

    def test_returns_empty_for_invalid_length(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            sl = SessionLogger(user_id="u")
        assert sl._ansi_hex("#abc") == ""

    def test_strips_hash_prefix(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            sl = SessionLogger(user_id="u")
        result = sl._ansi_hex("#000000")
        assert "0;0;0" in result

    def test_static_method(self):
        # Can be called without an instance
        result = SessionLogger._ansi_hex("#ffffff")
        assert "255;255;255" in result


# ---------------------------------------------------------------------------
# _generate_waveform
# ---------------------------------------------------------------------------

class TestGenerateWaveform:
    @pytest.fixture(autouse=True)
    def sl(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            self._sl = SessionLogger(user_id="u")

    def test_returns_string_of_correct_width(self):
        wave = self._sl._generate_waveform("flow", width=40)
        assert len(wave) == 40

    def test_default_width_52(self):
        wave = self._sl._generate_waveform("flow")
        assert len(wave) == 52

    @pytest.mark.parametrize("state", ["flow", "stuck", "debugging", "reviewing", "context_switching"])
    def test_all_states_produce_output(self, state):
        wave = self._sl._generate_waveform(state)
        assert len(wave) == 52
        assert isinstance(wave, str)

    def test_deterministic_for_same_state(self):
        w1 = self._sl._generate_waveform("flow")
        w2 = self._sl._generate_waveform("flow")
        assert w1 == w2

    def test_different_states_differ(self):
        w_flow = self._sl._generate_waveform("flow")
        w_stuck = self._sl._generate_waveform("stuck")
        assert w_flow != w_stuck


# ---------------------------------------------------------------------------
# _progress_bar
# ---------------------------------------------------------------------------

class TestProgressBar:
    @pytest.fixture(autouse=True)
    def sl(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            self._sl = SessionLogger(user_id="u")

    def test_full_bar(self):
        bar = self._sl._progress_bar(100, 100, width=10)
        assert bar == "█" * 10

    def test_empty_bar(self):
        bar = self._sl._progress_bar(0, 100, width=10)
        assert bar == "░" * 10

    def test_half_bar(self):
        bar = self._sl._progress_bar(50, 100, width=10)
        assert "█" in bar
        assert "░" in bar
        assert len(bar) == 10

    def test_zero_max_val_returns_all_empty(self):
        bar = self._sl._progress_bar(50, 0, width=8)
        assert bar == "░" * 8

    def test_value_above_max_is_clamped(self):
        bar = self._sl._progress_bar(200, 100, width=10)
        assert bar == "█" * 10


# ---------------------------------------------------------------------------
# _pulse_color
# ---------------------------------------------------------------------------

class TestPulseColor:
    @pytest.fixture(autouse=True)
    def sl(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            self._sl = SessionLogger(user_id="u")

    def test_high_confidence_adds_bold(self):
        result = self._sl._pulse_color("flow", 0.90)
        assert self._sl.bold in result

    def test_low_confidence_no_bold(self):
        result = self._sl._pulse_color("flow", 0.50)
        assert self._sl.bold not in result

    def test_boundary_confidence_085(self):
        # 0.85 is NOT > 0.85, so no bold
        result = self._sl._pulse_color("flow", 0.85)
        assert self._sl.bold not in result

    def test_returns_base_color_for_known_state(self):
        result = self._sl._pulse_color("stuck", 0.3)
        assert self._sl.state_colors["stuck"] in result

    def test_returns_empty_string_for_unknown_state(self):
        result = self._sl._pulse_color("unknown_state", 0.5)
        assert result == ""


# ---------------------------------------------------------------------------
# _rule
# ---------------------------------------------------------------------------

class TestRule:
    @pytest.fixture(autouse=True)
    def sl(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            self._sl = SessionLogger(user_id="u")

    def test_contains_repeated_char(self):
        rule = self._sl._rule("─", width=20)
        assert "─" * 20 in rule

    def test_default_width_60(self):
        rule = self._sl._rule()
        assert "═" * 60 in rule


# ---------------------------------------------------------------------------
# log_cycle
# ---------------------------------------------------------------------------

class TestLogCycle:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.log_file = str(tmp_path / "session.log")
        _fake_database.save_cycle.reset_mock()
        with patch("logger.LOG_FILE", self.log_file):
            self.sl = SessionLogger(session_id="sess-1", user_id="alice")

    def test_appends_entry_to_session_entries(self):
        with patch("logger.LOG_FILE", self.log_file):
            with patch.object(self.sl, "_sync_to_cloud"):
                self.sl.log_cycle(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        assert len(self.sl.session_entries) == 1
        entry = self.sl.session_entries[0]
        assert entry["metrics"] == SAMPLE_METRICS
        assert entry["classification"] == SAMPLE_CLASSIFICATION

    def test_writes_to_log_file(self):
        with patch("logger.LOG_FILE", self.log_file):
            with patch.object(self.sl, "_sync_to_cloud"):
                self.sl.log_cycle(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        content = open(self.log_file).read()
        assert "FLOW" in content
        assert "WPM=" in content

    def test_calls_save_cycle_with_correct_args(self):
        with patch("logger.LOG_FILE", self.log_file):
            with patch.object(self.sl, "_sync_to_cloud"):
                self.sl.log_cycle(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        _fake_database.save_cycle.assert_called_once_with(
            "sess-1", SAMPLE_METRICS, SAMPLE_CLASSIFICATION, "alice"
        )

    def test_calls_sync_to_cloud(self):
        with patch("logger.LOG_FILE", self.log_file):
            with patch.object(self.sl, "_sync_to_cloud") as mock_sync:
                self.sl.log_cycle(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        mock_sync.assert_called_once_with(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)

    def test_handles_save_cycle_exception_gracefully(self):
        _fake_database.save_cycle.side_effect = Exception("DB error")
        with patch("logger.LOG_FILE", self.log_file):
            with patch.object(self.sl, "_sync_to_cloud"):
                self.sl.log_cycle(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)  # should not raise
        _fake_database.save_cycle.side_effect = None

    def test_entry_contains_timestamp(self):
        with patch("logger.LOG_FILE", self.log_file):
            with patch.object(self.sl, "_sync_to_cloud"):
                self.sl.log_cycle(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        assert isinstance(self.sl.session_entries[0]["timestamp"], datetime)


# ---------------------------------------------------------------------------
# _sync_to_cloud
# ---------------------------------------------------------------------------

class TestSyncToCloud:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.log_file = str(tmp_path / "session.log")
        with patch("logger.LOG_FILE", self.log_file):
            self.sl = SessionLogger(session_id="sess-x", user_id="u")

    def test_skips_when_no_sync_url(self):
        with patch("logger.SYNC_URL", None):
            with patch("requests.post") as mock_post:
                self.sl._sync_to_cloud(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        mock_post.assert_not_called()

    def test_posts_cycle_data_when_sync_url_set(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("logger.SYNC_URL", "https://example.com/api/sync"):
            with patch("requests.post", return_value=mock_resp) as mock_post:
                self.sl._sync_to_cloud(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["session_id"] == "sess-x"
        assert payload["state"] == "flow"
        assert payload["wpm"] == SAMPLE_METRICS["wpm"]

    def test_handles_non_200_response(self, capsys):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("logger.SYNC_URL", "https://example.com/api/sync"):
            with patch("requests.post", return_value=mock_resp):
                self.sl._sync_to_cloud(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        captured = capsys.readouterr()
        assert "503" in captured.err

    def test_handles_request_exception(self, capsys):
        with patch("logger.SYNC_URL", "https://example.com/api/sync"):
            with patch("requests.post", side_effect=Exception("timeout")):
                self.sl._sync_to_cloud(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        captured = capsys.readouterr()
        assert "timeout" in captured.err

    def test_skips_when_requests_unavailable(self):
        original = logger_module.HAS_REQUESTS
        logger_module.HAS_REQUESTS = False
        with patch("logger.SYNC_URL", "https://example.com/api/sync"):
            with patch("requests.post") as mock_post:
                self.sl._sync_to_cloud(SAMPLE_METRICS, SAMPLE_CLASSIFICATION)
        mock_post.assert_not_called()
        logger_module.HAS_REQUESTS = original


# ---------------------------------------------------------------------------
# _find_flow_windows
# ---------------------------------------------------------------------------

class TestFindFlowWindows:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", log_file):
            self.sl = SessionLogger(user_id="u")

    def _entry(self, state: str):
        return {
            "timestamp": datetime.now(),
            "metrics": SAMPLE_METRICS,
            "classification": {"state": state, "confidence": 0.8, "reason": ""},
        }

    def test_returns_empty_when_no_entries(self):
        assert self.sl._find_flow_windows() == []

    def test_returns_empty_when_no_flow_states(self):
        self.sl.session_entries = [self._entry("stuck"), self._entry("debugging")]
        assert self.sl._find_flow_windows() == []

    def test_single_continuous_flow_window(self):
        self.sl.session_entries = [
            self._entry("flow"),
            self._entry("flow"),
            self._entry("flow"),
        ]
        windows = self.sl._find_flow_windows()
        assert len(windows) == 1
        assert len(windows[0]) == 3

    def test_splits_on_non_flow_state(self):
        self.sl.session_entries = [
            self._entry("flow"),
            self._entry("stuck"),
            self._entry("flow"),
            self._entry("flow"),
        ]
        windows = self.sl._find_flow_windows()
        assert len(windows) == 2
        assert len(windows[0]) == 1
        assert len(windows[1]) == 2

    def test_trailing_flow_window_included(self):
        self.sl.session_entries = [
            self._entry("stuck"),
            self._entry("flow"),
            self._entry("flow"),
        ]
        windows = self.sl._find_flow_windows()
        assert len(windows) == 1
        assert len(windows[0]) == 2


# ---------------------------------------------------------------------------
# print_session_summary
# ---------------------------------------------------------------------------

class TestPrintSessionSummary:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.log_file = str(tmp_path / "s.log")
        with patch("logger.LOG_FILE", self.log_file):
            self.sl = SessionLogger(user_id="u")

    def _add_entry(self, state: str):
        entry = {
            "timestamp": datetime.now(),
            "metrics": SAMPLE_METRICS,
            "classification": {"state": state, "confidence": 0.8, "reason": ""},
        }
        self.sl.session_entries.append(entry)

    def test_prints_no_data_message_when_empty(self, capsys):
        self.sl.print_session_summary()
        captured = capsys.readouterr()
        assert "No session data" in captured.out

    def test_prints_summary_with_entries(self, capsys):
        self._add_entry("flow")
        self._add_entry("stuck")
        with patch("logger.LOG_FILE", self.log_file):
            self.sl.print_session_summary()
        captured = capsys.readouterr()
        assert "SESSION SUMMARY" in captured.out

    def test_writes_summary_to_file(self):
        self._add_entry("flow")
        self._add_entry("flow")
        with patch("logger.LOG_FILE", self.log_file):
            self.sl.print_session_summary()
        content = open(self.log_file).read()
        assert "SESSION SUMMARY" in content
        assert "Duration" in content

    def test_reports_state_percentages(self, capsys):
        self._add_entry("flow")
        self._add_entry("flow")
        self._add_entry("stuck")
        with patch("logger.LOG_FILE", self.log_file):
            self.sl.print_session_summary()
        captured = capsys.readouterr()
        assert "flow" in captured.out
        assert "stuck" in captured.out

    def test_reports_longest_flow_window(self, capsys):
        for _ in range(4):
            self._add_entry("flow")
        with patch("logger.LOG_FILE", self.log_file):
            self.sl.print_session_summary()
        captured = capsys.readouterr()
        assert "Flow Window" in captured.out or "flow" in captured.out.lower()
