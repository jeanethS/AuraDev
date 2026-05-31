# AuraDev — Platanus Build Night — Ciudad de México

![AuraDev dashboard](auradev/dashboard/project-logo.png)

**Ambient music engine that adapts to your developer cognitive state in real-time.**

AuraDev samples your coding behavior every 30 seconds, uses Claude AI to classify your cognitive state (flow, stuck, debugging, reviewing, context-switching), and generates matching ambient music via Google's Lyria API.

Hacker: [Jeaneth Sarahi Hernandez Rios](https://github.com/jeanethS) ([@cosmicctxt](https://x.com/cosmicctxt))

---

## 🎵 Features

- **Real-time Cognitive State Detection**: Analyzes WPM, backspace ratio, window switches, mouse movement, CPU usage, and idle time
- **AI Classification**: Claude Opus 4 classifies your state with confidence scores
- **Adaptive Music**: Google Lyria generates unique therapeutic ambient music for each state
- **Live Dashboard**: FastAPI server + HTML dashboard showing session metrics
- **SQLite Logging**: Persistent session history and analytics

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11–3.13
- Anthropic API key (Claude)
- Google Cloud project with Vertex AI enabled
- GCP service account with "Vertex AI User" role

### Installation

```bash
# 1. Clone and navigate
cd auradev

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
cp ../.env.example .env
# Edit .env and add:
#   ANTHROPIC_API_KEY=sk-ant-...
#   LYRIA_PROJECT_ID=your-gcp-project-id
#   GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-service-account.json
```

### Running

```bash
# Normal mode (requires API keys and OS permissions)
python main.py

# Demo mode (no API calls, no permissions needed)
python main.py --demo --interval 5 --max-cycles 10

# Custom interval and drum volume
python main.py --demo --interval 3 --drum-volume 0.7 --no-drums
```

Dashboard: http://localhost:8765

---

## 🔐 Security

**⚠️ Important**: Never commit API keys or service account JSON files!

See [SECURITY.md](SECURITY.md) for:
- What files to never commit
- Pre-commit checklist
- How to handle accidentally committed secrets
- GCP service account best practices

Protected files (already in `.gitignore`):
- `.env` files
- `*service-account*.json`
- `client_secret*.json`
- `session.log`, `*.db`

---

## 📚 Documentation

- [AuraDev Architecture](auradev/CLAUDE.md) - Module contracts, audio rules, state mappings
- [API Server Guide](auradev/OPENCODE_TASK_API_SERVER.md) - FastAPI endpoints and dashboard
- [Lyria Integration](auradev/lyria_integration_prompt.md) - How Lyria replaces procedural audio

---

## 🧪 Testing

```bash
cd auradev
pytest                          # All tests
pytest test_audio.py -v        # Audio synthesis
pytest test_classifier.py -v   # Claude classification
pytest test_api.py -v          # API server
pytest --cov=. --cov-report=term-missing  # With coverage
```

---

## ⚠️ Deploying (Vercel, Render, etc.)

Deploy platforms like **Vercel**, **Render** or **Netlify** can only connect to
repositories **you own** — they can't be granted access to this organization repo.
To deploy while keeping your commits here, mirror your code to a personal repo:

1. Create a **personal** repository on your own GitHub account.
2. Point your local `origin` at **both** repos, so a single `git push` updates each one:
  ```bash
   # this org repo (keep it as a push target)...
   git remote set-url --add --push origin https://github.com/platanus-build-night/platanus-build-night-26-mx-jeanethS.git
   # ...and your personal repo
   git remote set-url --add --push origin https://github.com/<your-user>/<your-repo>.git
  ```
   From now on `git push` sends every commit to **both** repositories.
3. Connect your deploy service (Vercel, Render, …) to your **personal** repo and deploy from there.

Your commits stay mirrored here for judging, while the deploy runs from the repo you control.

Have fun! 🚀