"""
Unit tests for lyria.py – Lyria 2 / Vertex AI music integration.

Covers:
  - Disk cache helpers (_disk_cache_path, _load_disk_cache, _save_to_disk)
  - init_lyria (project_id + disk cache bootstrap)
  - _get_auth_headers (success, import error, exception)
  - _is_recitation_error (true / false branches)
  - _request_lyria_audio (success, HTTP error, no predictions, missing audio)
  - get_audio_for_state (cache hit, unknown state, API success, retry on recitation,
                         API error, no project_id)
  - play_state (same-state noop, pygame playback, fallback when audio unavailable,
                exception during play, temp file rotation)
  - stop / cleanup (temp file deleted by cleanup)
  - prefetch_next (background threads for un-cached states)
"""

import base64
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Inject a mock pygame module BEFORE importing lyria so the top-level
# ``try: import pygame`` succeeds without a real installation.
# ---------------------------------------------------------------------------
_mock_pygame = MagicMock()
_mock_pygame.mixer.get_init.return_value = True
sys.modules.setdefault("pygame", _mock_pygame)

import lyria as lyria_module  # noqa: E402  (after sys.modules patch)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wav_b64(n_bytes: int = 64) -> str:
    """Return a base64-encoded blob of n_bytes zeros (stands in for a WAV file)."""
    return base64.b64encode(b"\x00" * n_bytes).decode()


def _reset_module_state():
    """Reset all module-level globals so each test starts clean."""
    lyria_module._project_id = None
    lyria_module._credentials = None
    lyria_module._cache.clear()
    lyria_module._last_state = None
    lyria_module._last_temp_path = None
    lyria_module._fallback_engine = None
    lyria_module._use_fallback = False
    _mock_pygame.reset_mock()
    _mock_pygame.mixer.get_init.return_value = True


# ---------------------------------------------------------------------------
# _disk_cache_path
# ---------------------------------------------------------------------------

class TestDiskCachePath:
    def test_returns_path_under_home(self):
        path = lyria_module._disk_cache_path("flow")
        assert isinstance(path, Path)
        assert path.name == "flow.wav"
        assert ".auradev" in str(path)

    def test_different_states_different_paths(self):
        p1 = lyria_module._disk_cache_path("flow")
        p2 = lyria_module._disk_cache_path("stuck")
        assert p1 != p2


# ---------------------------------------------------------------------------
# _load_disk_cache
# ---------------------------------------------------------------------------

class TestLoadDiskCache:
    def setup_method(self):
        _reset_module_state()

    def test_populates_memory_cache_from_existing_files(self, tmp_path):
        with patch.object(lyria_module, "_DISK_CACHE_DIR", tmp_path):
            # Write a fake WAV file for "flow"
            (tmp_path / "flow.wav").write_bytes(b"FAKEAUDIO")

            lyria_module._load_disk_cache()

            assert "flow" in lyria_module._cache
            assert lyria_module._cache["flow"] == b"FAKEAUDIO"

    def test_skips_missing_states(self, tmp_path):
        with patch.object(lyria_module, "_DISK_CACHE_DIR", tmp_path):
            lyria_module._load_disk_cache()
            assert lyria_module._cache == {}

    def test_handles_oserror_gracefully(self, tmp_path):
        with patch.object(lyria_module, "_DISK_CACHE_DIR", tmp_path):
            (tmp_path / "flow.wav").write_bytes(b"data")
            with patch("pathlib.Path.read_bytes", side_effect=OSError("disk fail")):
                lyria_module._load_disk_cache()
            # Cache should remain empty – no crash
            assert "flow" not in lyria_module._cache


# ---------------------------------------------------------------------------
# _save_to_disk
# ---------------------------------------------------------------------------

class TestSaveToDisk:
    def setup_method(self):
        _reset_module_state()

    def test_writes_file_to_disk(self, tmp_path):
        with patch.object(lyria_module, "_DISK_CACHE_DIR", tmp_path):
            lyria_module._save_to_disk("flow", b"WAVDATA")
            assert (tmp_path / "flow.wav").read_bytes() == b"WAVDATA"

    def test_handles_oserror_gracefully(self, tmp_path):
        with patch.object(lyria_module, "_DISK_CACHE_DIR", tmp_path):
            with patch("pathlib.Path.write_bytes", side_effect=OSError("no space")):
                # Should not raise
                lyria_module._save_to_disk("flow", b"WAVDATA")


# ---------------------------------------------------------------------------
# init_lyria
# ---------------------------------------------------------------------------

class TestInitLyria:
    def setup_method(self):
        _reset_module_state()

    def test_sets_project_id(self, tmp_path):
        with patch.object(lyria_module, "_DISK_CACHE_DIR", tmp_path):
            with patch.object(lyria_module, "_get_auth_headers", return_value=None):
                lyria_module.init_lyria("my-project-123")
        assert lyria_module._project_id == "my-project-123"

    def test_calls_pygame_init_when_mixer_not_ready(self, tmp_path):
        _mock_pygame.mixer.get_init.return_value = False
        with patch.object(lyria_module, "_DISK_CACHE_DIR", tmp_path):
            with patch.object(lyria_module, "_get_auth_headers", return_value={"Authorization": "Bearer tok"}):
                lyria_module.init_lyria("proj")
        _mock_pygame.mixer.init.assert_called()

    def test_logs_error_when_auth_fails(self, tmp_path, caplog):
        import logging
        with patch.object(lyria_module, "_DISK_CACHE_DIR", tmp_path):
            with patch.object(lyria_module, "_get_auth_headers", return_value=None):
                with caplog.at_level(logging.ERROR, logger="lyria"):
                    lyria_module.init_lyria("proj")
        assert any("auth" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# _get_auth_headers
# ---------------------------------------------------------------------------

class TestGetAuthHeaders:
    def setup_method(self):
        _reset_module_state()

    def test_returns_headers_when_credentials_valid(self):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "my-token"

        with patch("google.auth.default", return_value=(mock_creds, "project")):
            headers = lyria_module._get_auth_headers()

        assert headers is not None
        assert "Bearer my-token" in headers["Authorization"]
        assert headers["Content-Type"] == "application/json"

    def test_refreshes_expired_credentials(self):
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.token = "refreshed-token"
        lyria_module._credentials = mock_creds

        with patch("google.auth.transport.requests.Request"):
            headers = lyria_module._get_auth_headers()

        mock_creds.refresh.assert_called_once()
        assert headers is not None

    def test_returns_none_when_google_auth_missing(self):
        lyria_module._credentials = None
        with patch.dict(sys.modules, {"google.auth": None, "google": None}):
            # Force ImportError inside the function
            import builtins
            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name in ("google.auth", "google.auth.transport.requests"):
                    raise ImportError("not installed")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = lyria_module._get_auth_headers()
        assert result is None

    def test_returns_none_on_exception(self):
        lyria_module._credentials = None
        with patch("google.auth.default", side_effect=Exception("network error")):
            result = lyria_module._get_auth_headers()
        assert result is None


# ---------------------------------------------------------------------------
# _is_recitation_error
# ---------------------------------------------------------------------------

class TestIsRecitationError:
    def _make_response(self, status_code: int, body: dict):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = body
        mock_resp.text = str(body)
        return mock_resp

    def test_true_for_400_with_recitation_in_message(self):
        resp = self._make_response(
            400, {"error": {"message": "Recitation check failed for your request."}}
        )
        assert lyria_module._is_recitation_error(resp) is True

    def test_false_for_non_400_status(self):
        resp = self._make_response(
            500, {"error": {"message": "recitation"}}
        )
        assert lyria_module._is_recitation_error(resp) is False

    def test_false_for_400_without_recitation(self):
        resp = self._make_response(400, {"error": {"message": "bad request"}})
        assert lyria_module._is_recitation_error(resp) is False

    def test_handles_json_decode_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.side_effect = ValueError("no JSON")
        mock_resp.text = "recitation blocked"
        assert lyria_module._is_recitation_error(mock_resp) is True

    def test_case_insensitive_check(self):
        resp = self._make_response(400, {"error": {"message": "RECITATION POLICY"}})
        assert lyria_module._is_recitation_error(resp) is True


# ---------------------------------------------------------------------------
# _request_lyria_audio
# ---------------------------------------------------------------------------

class TestRequestLyriaAudio:
    def setup_method(self):
        _reset_module_state()
        lyria_module._project_id = "test-project"

    def _mock_post(self, status_code: int, body: dict):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = body
        mock_resp.text = str(body)
        return mock_resp

    def test_returns_wav_bytes_on_success(self):
        audio_data = b"FAKEAUDIO"
        encoded = base64.b64encode(audio_data).decode()
        mock_resp = self._mock_post(200, {"predictions": [{"bytesBase64Encoded": encoded}]})

        with patch.object(lyria_module, "_get_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("requests.post", return_value=mock_resp):
                wav, resp = lyria_module._request_lyria_audio("prompt", "negative")

        assert wav == audio_data
        assert resp is mock_resp

    def test_uses_audioContent_field_as_fallback(self):
        audio_data = b"FAKEAUDIO2"
        encoded = base64.b64encode(audio_data).decode()
        mock_resp = self._mock_post(200, {"predictions": [{"audioContent": encoded}]})

        with patch.object(lyria_module, "_get_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("requests.post", return_value=mock_resp):
                wav, resp = lyria_module._request_lyria_audio("prompt", "negative")

        assert wav == audio_data

    def test_returns_none_wav_on_non_200(self):
        mock_resp = self._mock_post(503, {})
        with patch.object(lyria_module, "_get_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("requests.post", return_value=mock_resp):
                wav, resp = lyria_module._request_lyria_audio("prompt", "negative")
        assert wav is None
        assert resp is mock_resp

    def test_returns_none_when_no_predictions(self):
        mock_resp = self._mock_post(200, {"predictions": []})
        with patch.object(lyria_module, "_get_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("requests.post", return_value=mock_resp):
                wav, resp = lyria_module._request_lyria_audio("prompt", "negative")
        assert wav is None

    def test_returns_none_when_audio_field_missing(self):
        mock_resp = self._mock_post(200, {"predictions": [{"someOtherField": "data"}]})
        with patch.object(lyria_module, "_get_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("requests.post", return_value=mock_resp):
                wav, resp = lyria_module._request_lyria_audio("prompt", "negative")
        assert wav is None

    def test_returns_none_none_when_no_headers(self):
        with patch.object(lyria_module, "_get_auth_headers", return_value=None):
            wav, resp = lyria_module._request_lyria_audio("prompt", "negative")
        assert wav is None
        assert resp is None

    def test_passes_seed_in_instance(self):
        audio_data = b"X"
        encoded = base64.b64encode(audio_data).decode()
        mock_resp = self._mock_post(200, {"predictions": [{"bytesBase64Encoded": encoded}]})

        with patch.object(lyria_module, "_get_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("requests.post", return_value=mock_resp) as mock_post:
                lyria_module._request_lyria_audio("prompt", "negative", seed=42)

        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["instances"][0]["seed"] == 42
        assert "parameters" not in payload  # no sample_count when seed is set

    def test_no_seed_adds_parameters(self):
        audio_data = b"X"
        encoded = base64.b64encode(audio_data).decode()
        mock_resp = self._mock_post(200, {"predictions": [{"bytesBase64Encoded": encoded}]})

        with patch.object(lyria_module, "_get_auth_headers", return_value={"Authorization": "Bearer t"}):
            with patch("requests.post", return_value=mock_resp) as mock_post:
                lyria_module._request_lyria_audio("prompt", "negative", seed=None)

        _, kwargs = mock_post.call_args
        assert "parameters" in kwargs["json"]


# ---------------------------------------------------------------------------
# get_audio_for_state
# ---------------------------------------------------------------------------

class TestGetAudioForState:
    def setup_method(self):
        _reset_module_state()
        lyria_module._project_id = "test-project"

    def test_returns_cached_bytes_without_api_call(self):
        lyria_module._cache["flow"] = b"CACHED"
        with patch.object(lyria_module, "_request_lyria_audio") as mock_req:
            result = lyria_module.get_audio_for_state("flow")
        assert result == b"CACHED"
        mock_req.assert_not_called()

    def test_returns_none_for_unknown_state(self):
        result = lyria_module.get_audio_for_state("nonexistent_state")
        assert result is None

    def test_returns_none_when_no_project_id(self):
        lyria_module._project_id = None
        result = lyria_module.get_audio_for_state("flow")
        assert result is None

    def test_returns_audio_on_successful_api_call(self):
        audio = b"FRESHWAV"
        with patch.object(lyria_module, "_request_lyria_audio", return_value=(audio, MagicMock())):
            with patch.object(lyria_module, "_save_to_disk"):
                result = lyria_module.get_audio_for_state("flow")
        assert result == audio
        assert lyria_module._cache["flow"] == audio

    def test_retries_with_seed_on_recitation_error(self):
        recitation_resp = MagicMock()
        recitation_resp.status_code = 400
        recitation_resp.json.return_value = {"error": {"message": "recitation check"}}

        audio = b"RETRIED"
        side_effects = [
            (None, recitation_resp),   # attempt 1: recitation
            (audio, MagicMock()),       # attempt 2: success
        ]
        with patch.object(lyria_module, "_request_lyria_audio", side_effect=side_effects):
            with patch.object(lyria_module, "_save_to_disk"):
                result = lyria_module.get_audio_for_state("flow")
        assert result == audio

    def test_returns_none_on_non_recitation_api_error(self):
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.json.return_value = {}
        error_resp.text = "server error"
        with patch.object(lyria_module, "_request_lyria_audio", return_value=(None, error_resp)):
            result = lyria_module.get_audio_for_state("flow")
        assert result is None

    def test_returns_none_when_request_returns_none_none(self):
        with patch.object(lyria_module, "_request_lyria_audio", return_value=(None, None)):
            result = lyria_module.get_audio_for_state("flow")
        assert result is None

    def test_caches_result_after_successful_fetch(self):
        audio = b"NEWWAV"
        with patch.object(lyria_module, "_request_lyria_audio", return_value=(audio, MagicMock())):
            with patch.object(lyria_module, "_save_to_disk"):
                lyria_module.get_audio_for_state("stuck")
        assert lyria_module._cache.get("stuck") == audio

    def test_saves_to_disk_after_successful_fetch(self):
        audio = b"DISKWAV"
        with patch.object(lyria_module, "_request_lyria_audio", return_value=(audio, MagicMock())):
            with patch.object(lyria_module, "_save_to_disk") as mock_save:
                lyria_module.get_audio_for_state("flow")
        mock_save.assert_called_once_with("flow", audio)

    def test_handles_exception_gracefully(self):
        with patch.object(lyria_module, "_request_lyria_audio", side_effect=RuntimeError("boom")):
            result = lyria_module.get_audio_for_state("flow")
        assert result is None


# ---------------------------------------------------------------------------
# play_state
# ---------------------------------------------------------------------------

class TestPlayState:
    def setup_method(self):
        _reset_module_state()
        lyria_module._project_id = "test-project"

    def test_noop_when_state_unchanged(self):
        lyria_module._last_state = "flow"
        with patch.object(lyria_module, "get_audio_for_state") as mock_get:
            lyria_module.play_state("flow")
        mock_get.assert_not_called()

    def test_plays_audio_via_pygame(self, tmp_path):
        audio = b"RIFF" + b"\x00" * 60  # Fake WAV bytes
        lyria_module._last_state = None

        with patch.object(lyria_module, "get_audio_for_state", return_value=audio):
            lyria_module.play_state("flow")

        _mock_pygame.mixer.music.load.assert_called()
        _mock_pygame.mixer.music.play.assert_called_with(-1)
        assert lyria_module._last_state == "flow"

    def test_temp_file_is_created_and_tracked(self):
        audio = b"WAVDATA"
        lyria_module._last_state = None
        lyria_module._last_temp_path = None

        with patch.object(lyria_module, "get_audio_for_state", return_value=audio):
            lyria_module.play_state("flow")

        assert lyria_module._last_temp_path is not None
        # The file should exist on disk (written during play_state)
        assert os.path.exists(lyria_module._last_temp_path)
        # Cleanup
        os.remove(lyria_module._last_temp_path)

    def test_deletes_previous_temp_file_on_state_change(self):
        audio = b"WAVDATA"

        # Create a real temp file to act as the previous one
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            prev_path = f.name

        lyria_module._last_state = "stuck"
        lyria_module._last_temp_path = prev_path

        with patch.object(lyria_module, "get_audio_for_state", return_value=audio):
            lyria_module.play_state("flow")

        assert not os.path.exists(prev_path)
        # Cleanup new temp file
        if lyria_module._last_temp_path and os.path.exists(lyria_module._last_temp_path):
            os.remove(lyria_module._last_temp_path)

    def test_uses_fallback_when_audio_unavailable(self):
        lyria_module._last_state = None
        mock_engine = MagicMock()

        with patch.object(lyria_module, "get_audio_for_state", return_value=None):
            with patch.object(lyria_module, "_get_fallback_engine", return_value=mock_engine):
                lyria_module.play_state("debugging")

        mock_engine.play_state.assert_called_with("debugging")
        assert lyria_module._use_fallback is True

    def test_uses_existing_fallback_engine_when_flag_set(self):
        lyria_module._use_fallback = True
        lyria_module._last_state = "flow"  # different from "stuck"
        mock_engine = MagicMock()
        lyria_module._fallback_engine = mock_engine

        with patch.object(lyria_module, "_get_fallback_engine", return_value=mock_engine):
            lyria_module.play_state("stuck")

        mock_engine.play_state.assert_called_with("stuck")

    def test_stops_pygame_when_no_audio_and_no_fallback(self):
        lyria_module._last_state = None
        with patch.object(lyria_module, "get_audio_for_state", return_value=None):
            with patch.object(lyria_module, "_get_fallback_engine", return_value=None):
                lyria_module.play_state("reviewing")

        _mock_pygame.mixer.music.stop.assert_called()

    def test_cleans_up_temp_file_on_exception(self):
        lyria_module._last_state = None
        audio = b"BADWAV"

        _mock_pygame.mixer.music.load.side_effect = Exception("pygame crash")

        with patch.object(lyria_module, "get_audio_for_state", return_value=audio):
            lyria_module.play_state("flow")  # should not raise

        # After exception, music.stop() should be called
        _mock_pygame.mixer.music.stop.assert_called()
        assert lyria_module._last_state == "flow"


# ---------------------------------------------------------------------------
# stop / cleanup
# ---------------------------------------------------------------------------

class TestStopCleanup:
    def setup_method(self):
        _reset_module_state()

    def test_stop_calls_pygame_music_stop(self):
        lyria_module.stop()
        _mock_pygame.mixer.music.stop.assert_called()

    def test_stop_calls_fallback_engine_stop(self):
        mock_engine = MagicMock()
        lyria_module._fallback_engine = mock_engine
        lyria_module.stop()
        mock_engine.stop.assert_called_once()

    def test_cleanup_deletes_last_temp_file(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name

        lyria_module._last_temp_path = tmp
        lyria_module.cleanup()

        assert not os.path.exists(tmp)
        assert lyria_module._last_temp_path is None

    def test_cleanup_handles_missing_temp_file_gracefully(self):
        lyria_module._last_temp_path = "/nonexistent/path/file.wav"
        lyria_module.cleanup()  # Should not raise
        assert lyria_module._last_temp_path is None

    def test_cleanup_calls_fallback_cleanup(self):
        mock_engine = MagicMock()
        lyria_module._fallback_engine = mock_engine
        lyria_module.cleanup()
        mock_engine.cleanup.assert_called_once()

    def test_cleanup_stops_pygame(self):
        lyria_module.cleanup()
        _mock_pygame.mixer.music.stop.assert_called()

    def test_stop_when_mixer_not_init(self):
        _mock_pygame.mixer.get_init.return_value = False
        lyria_module.stop()  # Should not crash


# ---------------------------------------------------------------------------
# prefetch_next
# ---------------------------------------------------------------------------

class TestPrefetchNext:
    def setup_method(self):
        _reset_module_state()
        lyria_module._project_id = "test-project"

    def test_fetches_all_states_except_current(self):
        fetched = []

        def mock_get(state):
            fetched.append(state)
            return None

        with patch.object(lyria_module, "get_audio_for_state", side_effect=mock_get):
            lyria_module.prefetch_next("flow")
            # Give background thread time to run
            time.sleep(0.3)

        assert "flow" not in fetched
        for state in lyria_module.LYRIA_PROMPTS:
            if state != "flow":
                assert state in fetched

    def test_skips_already_cached_states(self):
        lyria_module._cache["stuck"] = b"CACHED"
        lyria_module._cache["debugging"] = b"CACHED"
        fetched = []

        def mock_get(state):
            fetched.append(state)
            return None

        with patch.object(lyria_module, "get_audio_for_state", side_effect=mock_get):
            lyria_module.prefetch_next("flow")
            time.sleep(0.3)

        assert "stuck" not in fetched
        assert "debugging" not in fetched

    def test_runs_in_daemon_thread(self):
        captured_threads = []

        original_thread_class = threading.Thread

        class CapturingThread(original_thread_class):
            def start(self):
                captured_threads.append(self)
                super().start()

        with patch("threading.Thread", CapturingThread):
            with patch.object(lyria_module, "get_audio_for_state", return_value=None):
                lyria_module.prefetch_next("flow")
                time.sleep(0.1)

        assert len(captured_threads) == 1
        assert captured_threads[0].daemon is True
