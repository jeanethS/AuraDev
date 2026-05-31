"""
Lyria 2 integration for auradev.
Generates therapeutic ambient music via Google's Lyria API.
"""

import base64
import logging
import os
import random
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_DISK_CACHE_DIR = Path.home() / ".auradev" / "lyria_cache"

import requests

try:
    import pygame
except ImportError:
    pygame = None  # type: ignore

logger = logging.getLogger(__name__)

# Abstract, texture-focused prompts avoid Lyria recitation checks (blocked when
# output resembles copyrighted training material). Avoid BPM, named instruments,
# and conventional song structure in prompts.
LYRIA_PROMPTS = {
    "flow": {
        "prompt": (
            "Abstract ambient soundscape for deep focus, soft layered synthetic "
            "textures, gentle evolving tones, wide spacious reverb, unobtrusive "
            "background atmosphere, instrumental only"
        ),
        "negative_prompt": (
            "vocals, lyrics, recognizable melody, drums, percussion, "
            "sudden changes, popular song structure"
        ),
    },
    "stuck": {
        "prompt": (
            "Slow experimental ambient drone, sparse granular textures, muted "
            "synthetic pads, minimal movement, contemplative sound design, "
            "instrumental only"
        ),
        "negative_prompt": (
            "energetic, fast, rhythmic, vocals, catchy hooks, percussion"
        ),
    },
    "debugging": {
        "prompt": (
            "Minimal electronic texture bed, steady subtle pulse, clean "
            "synthetic tones, structured repetition without melody, focus "
            "soundscape, instrumental only"
        ),
        "negative_prompt": (
            "chaotic, emotional, singing, drums, recognizable tune"
        ),
    },
    "reviewing": {
        "prompt": (
            "Near-silent atmospheric texture, very sparse gentle tones, soft "
            "room ambience, barely audible background pad, reading focus "
            "soundscape, instrumental only"
        ),
        "negative_prompt": (
            "loud, busy, melodic, percussion, vocals, strong rhythm"
        ),
    },
    "context_switching": {
        "prompt": (
            "Calming ambient wash, slow morphing synthetic layers, gentle "
            "transitions between soft tones, grounding background texture, "
            "instrumental only"
        ),
        "negative_prompt": (
            "chaotic, sudden, complex, vocals, drums, catchy melody"
        ),
    },
}

# Even more abstract fallbacks used when recitation checks block the primary prompt.
LYRIA_FALLBACK_PROMPTS = {
    "flow": (
        "Generative ambient drone, slow pad layers, wide stereo field, "
        "no discernible song structure, original instrumental texture"
    ),
    "stuck": (
        "Muted experimental drone, sparse evolving noise textures, "
        "no rhythm section, original instrumental sound design"
    ),
    "debugging": (
        "Minimal synthetic texture loop, subtle tonal pulses, "
        "abstract electronic ambience, no melody"
    ),
    "reviewing": (
        "Ultra-quiet room tone with faint synthetic hum, "
        "nearly silent background texture, no rhythm"
    ),
    "context_switching": (
        "Soft morphing ambient layers, gradual tonal shifts, "
        "abstract background wash, no song form"
    ),
}

LYRIA_RETRY_ATTEMPTS = 3

_project_id: Optional[str] = None
_credentials = None
_cache: Dict[str, bytes] = {}
_cache_lock = threading.Lock()
_last_state: Optional[str] = None
_last_temp_path: Optional[str] = None
_fallback_engine: Any = None
_use_fallback: bool = False

_CLOUD_PLATFORM_SCOPE = ["https://www.googleapis.com/auth/cloud-platform"]


def _disk_cache_path(state: str) -> Path:
    return _DISK_CACHE_DIR / f"{state}.wav"


def _load_disk_cache() -> None:
    """Populate in-memory cache from any WAV files already on disk."""
    _DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for state in LYRIA_PROMPTS:
        path = _disk_cache_path(state)
        if path.exists():
            try:
                data = path.read_bytes()
                with _cache_lock:
                    _cache[state] = data
                logger.info("Lyria disk cache hit for state '%s'", state)
            except OSError:
                logger.warning("Could not read Lyria disk cache for state '%s'", state)


def _save_to_disk(state: str, wav_bytes: bytes) -> None:
    """Write WAV bytes to disk so future sessions skip the API call."""
    try:
        _DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _disk_cache_path(state).write_bytes(wav_bytes)
    except OSError:
        logger.warning("Could not write Lyria disk cache for state '%s'", state)


def init_lyria(project_id: str) -> None:
    """Store project ID, load disk cache, and verify Google Cloud auth. Call once at startup."""
    global _project_id
    _project_id = project_id

    _load_disk_cache()

    if pygame is not None and not pygame.mixer.get_init():
        pygame.mixer.init()

    if not _get_auth_headers():
        logger.error(
            "Lyria auth not configured. Vertex AI requires OAuth, not an API key. "
            "Run 'gcloud auth application-default login' or set "
            "GOOGLE_APPLICATION_CREDENTIALS to a service account JSON file."
        )


def _get_auth_headers() -> Optional[Dict[str, str]]:
    """Return request headers with a fresh Vertex AI OAuth access token."""
    global _credentials

    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError:
        logger.error(
            "google-auth is required for Lyria. Install with: pip install google-auth"
        )
        return None

    try:
        if _credentials is None:
            _credentials, _ = google.auth.default(scopes=_CLOUD_PLATFORM_SCOPE)

        if not _credentials.valid:
            _credentials.refresh(google.auth.transport.requests.Request())

        return {
            "Authorization": f"Bearer {_credentials.token}",
            "Content-Type": "application/json",
        }
    except Exception:
        logger.exception(
            "Failed to obtain Google Cloud access token for Lyria. "
            "Ensure Vertex AI API is enabled and your account has access to project %s.",
            _project_id,
        )
        return None


def _is_recitation_error(response: requests.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        message = response.json().get("error", {}).get("message", "")
    except ValueError:
        message = response.text
    return "recitation" in message.lower()


def _request_lyria_audio(
    prompt: str,
    negative_prompt: str,
    seed: Optional[int] = None,
) -> Tuple[Optional[bytes], Optional[requests.Response]]:
    headers = _get_auth_headers()
    if headers is None or not _project_id:
        return None, None

    url = (
        f"https://us-central1-aiplatform.googleapis.com/v1/projects/{_project_id}"
        f"/locations/us-central1/publishers/google/models/lyria-002:predict"
    )

    instance: Dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
    }
    if seed is not None:
        instance["seed"] = seed

    payload: Dict[str, Any] = {"instances": [instance]}
    if seed is None:
        payload["parameters"] = {"sample_count": 1}

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    if response.status_code != 200:
        return None, response

    data = response.json()
    predictions = data.get("predictions", [])
    if not predictions:
        logger.error("Lyria API response contained no predictions")
        return None, response

    audio_b64 = predictions[0].get("bytesBase64Encoded") or predictions[0].get(
        "audioContent"
    )
    if not audio_b64:
        logger.error(
            "Lyria API prediction missing audio data "
            "(checked bytesBase64Encoded and audioContent)"
        )
        return None, response

    return base64.b64decode(audio_b64), response


def _get_fallback_engine() -> Any:
    global _fallback_engine
    if _fallback_engine is None:
        try:
            from audio import AudioEngine

            _fallback_engine = AudioEngine()
            logger.warning(
                "Lyria unavailable; using procedural audio fallback (audio.py)"
            )
        except Exception:
            logger.exception("Failed to initialize procedural audio fallback")
    return _fallback_engine


def get_audio_for_state(state: str) -> Optional[bytes]:
    """
    1. Check cache: if state in _cache, return cached WAV bytes.
    2. Otherwise call Lyria API with prompt for that state.
    3. Decode base64 response to WAV bytes.
    4. Store in _cache[state].
    5. Return WAV bytes.
    """
    with _cache_lock:
        if state in _cache:
            return _cache[state]

    if not _project_id:
        logger.error("Lyria not initialized: missing project_id")
        return None

    prompt_data = LYRIA_PROMPTS.get(state)
    if prompt_data is None:
        logger.error("Unknown state for Lyria: %s", state)
        return None

    negative_prompt = prompt_data["negative_prompt"]
    attempts = [
        (prompt_data["prompt"], None),
        (prompt_data["prompt"], random.randint(1, 2_147_483_647)),
        (LYRIA_FALLBACK_PROMPTS[state], random.randint(1, 2_147_483_647)),
    ][:LYRIA_RETRY_ATTEMPTS]

    try:
        for attempt_index, (prompt, seed) in enumerate(attempts, start=1):
            wav_bytes, response = _request_lyria_audio(prompt, negative_prompt, seed)
            if wav_bytes is not None:
                with _cache_lock:
                    _cache[state] = wav_bytes
                _save_to_disk(state, wav_bytes)
                return wav_bytes

            if response is None:
                return None

            if _is_recitation_error(response):
                logger.warning(
                    "Lyria recitation check blocked state %s (attempt %s/%s)",
                    state,
                    attempt_index,
                    len(attempts),
                )
                if attempt_index < len(attempts):
                    continue

            logger.error(
                "Lyria API error %s: %s", response.status_code, response.text
            )
            return None

        return None

    except Exception:
        logger.exception("Lyria API call failed")
        return None


def play_state(state: str) -> None:
    """
    1. Call get_audio_for_state(state).
    2. Write WAV bytes to a temp file.
    3. Load with pygame.mixer.music.load(path).
    4. Call pygame.mixer.music.play(-1) to loop.
    If state has not changed since last call, do nothing.
    Falls back to procedural audio (audio.py) when Lyria is blocked or fails.
    """
    global _last_state, _last_temp_path, _use_fallback

    if state == _last_state:
        return

    if _use_fallback:
        engine = _get_fallback_engine()
        if engine is not None:
            engine.play_state(state)
            _last_state = state
        return

    wav_bytes = get_audio_for_state(state)
    if wav_bytes is None:
        engine = _get_fallback_engine()
        if engine is not None:
            _use_fallback = True
            engine.play_state(state)
            _last_state = state
            return
        if pygame is not None and pygame.mixer.get_init():
            pygame.mixer.music.stop()
        _last_state = state
        return

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_bytes)
            tmp_path = tmp.name

        if pygame is not None and pygame.mixer.get_init():
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.play(-1)

        previous_temp_path = _last_temp_path
        _last_temp_path = tmp_path
        if previous_temp_path is not None:
            try:
                os.remove(previous_temp_path)
            except OSError:
                pass

        _last_state = state
    except Exception:
        logger.exception("Failed to play Lyria audio")
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        if pygame is not None and pygame.mixer.get_init():
            pygame.mixer.music.stop()
        _last_state = state


def stop() -> None:
    """Stop pygame mixer playback."""
    if _fallback_engine is not None:
        _fallback_engine.stop()
    if pygame is not None and pygame.mixer.get_init():
        pygame.mixer.music.stop()


def cleanup() -> None:
    """Alias for stop() to match AudioEngine interface."""
    global _last_temp_path
    if _fallback_engine is not None and hasattr(_fallback_engine, "cleanup"):
        _fallback_engine.cleanup()
    stop()
    if _last_temp_path is not None:
        try:
            os.remove(_last_temp_path)
        except OSError:
            pass
        _last_temp_path = None


def prefetch_next(state: str) -> None:
    """
    Call get_audio_for_state in a background thread for all states NOT in cache.
    Fire and forget.
    """
    def _prefetch():
        for s in LYRIA_PROMPTS:
            if s == state:
                continue
            with _cache_lock:
                if s in _cache:
                    continue
            get_audio_for_state(s)

    thread = threading.Thread(target=_prefetch, daemon=True)
    thread.start()
