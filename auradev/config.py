import os
from pathlib import Path


def _load_env_file() -> None:
    """Load .env from auradev/ or repo root if present."""
    base = Path(__file__).resolve().parent
    for env_path in (base / ".env", base.parent / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_env_file()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "claude-opus-4-7")
LYRIA_PROJECT_ID = os.getenv("LYRIA_PROJECT_ID")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# Cloud sync URL - set to your Render deployment
SYNC_URL = os.getenv("AURADEV_SYNC_URL")

_default_origins = "http://localhost:8765,http://localhost:3000"
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]

SAMPLE_INTERVAL = 30
CROSSFADE_SECONDS = 3.0
VOLUME = 0.35
LOG_FILE = "session.log"
DB_FILE = "auradev_sessions.db"
API_PORT = 8765

STATES = [
    "flow",
    "stuck",
    "debugging",
    "reviewing",
    "context_switching",
]

CHORDS = {
    "flow": [261.63, 293.66, 329.63, 392.00, 440.00, 523.25],  # C major pentatonic
    "stuck": [261.63, 311.13, 349.23, 392.00, 466.16],          # C minor pentatonic
    "debugging": [293.66, 329.63, 369.99, 440.00, 493.88],      # D major pentatonic
    "reviewing": [174.61, 196.00, 220.00, 261.63, 293.66],      # F major pentatonic, low drone
    "context_switching": [220.00, 261.63, 293.66, 329.63, 392.00],  # A minor pentatonic, open
}