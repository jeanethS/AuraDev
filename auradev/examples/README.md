# AURADEV Examples

This directory contains example scripts and configuration files demonstrating multi-tenant usage.

## Files

### multi_user_demo.sh
Shell script demonstrating two users (Alice and Bob) running auradev simultaneously on the same machine.

**Usage:**
```bash
# Make executable (Linux/Mac)
chmod +x examples/multi_user_demo.sh

# Run the demo
./examples/multi_user_demo.sh
```

**What it does:**
1. Starts the API server on port 8765
2. Launches two auradev instances in demo mode:
   - Alice: 20 cycles at 5-second intervals
   - Bob: 20 cycles at 5-second intervals
3. Each user gets their own isolated database file
4. Shows how to query user-specific data via the API

**Expected output:**
- Two separate database files in `~/.auradev/`
- API accessible at http://localhost:8765
- Dashboard shows different data for Alice vs Bob

### cloud_setup_example.env
Template environment file for cloud deployment with detailed comments.

**Usage:**
```bash
# Copy the template
cp examples/cloud_setup_example.env .env

# Edit with your actual values
nano .env  # or your preferred editor

# Add your Anthropic API key
# Configure database mode and directory
# Set platform-specific settings
```

**Platforms covered:**
- Docker / docker-compose
- Railway
- Render
- Heroku
- Generic cloud hosting

## Quick Start Examples

### Single User (Default)
```bash
# No configuration needed
python main.py --demo
```

### Multi-User on Same Machine
```bash
# Terminal 1 - Alice
export USER_ID=alice
export DB_MODE=isolated
python main.py --demo

# Terminal 2 - Bob  
export USER_ID=bob
export DB_MODE=isolated
python main.py --demo
```

### Cloud Deployment
```bash
# Set environment variables
export DB_MODE=shared
export DB_DIR=/data/auradev
export ANTHROPIC_API_KEY=sk-ant-api03-...

# Start API server
uvicorn api:app --host 0.0.0.0 --port 8765
```

## Testing Multi-User Functionality

### Via Dashboard
1. Start the API: `uvicorn api:app --reload`
2. Open http://localhost:8765
3. Enter user ID in the sidebar (e.g., "alice")
4. Run auradev: `USER_ID=alice python main.py --demo`
5. Refresh dashboard to see Alice's data
6. Change user ID to "bob" and repeat

### Via API (curl)
```bash
# Start API server
uvicorn api:app --reload

# Get Alice's sessions
curl -H "X-User-Id: alice" http://localhost:8765/api/sessions

# Get Bob's sessions
curl -H "X-User-Id: bob" http://localhost:8765/api/sessions

# Get insights for Alice
curl -H "X-User-Id: alice" http://localhost:8765/api/insights

# Sync data as Bob
curl -X POST http://localhost:8765/api/sync \
  -H "Content-Type: application/json" \
  -H "X-User-Id: bob" \
  -d '{
    "session_id": "bob_test_session",
    "state": "flow",
    "confidence": 0.9,
    "reason": "Testing",
    "wpm": 50.0,
    "backspace_ratio": 0.1,
    "window_switches": 2,
    "mouse_distance": 100.0,
    "cpu_percent": 20.0,
    "idle_seconds": 0.0,
    "active_window": "Terminal"
  }'
```

### Via Python API
```python
from database import init_db, save_cycle, get_all_sessions
import os

# Set mode
os.environ['DB_MODE'] = 'isolated'

# User 1: Alice
init_db('alice')
save_cycle(
    session_id='alice_session',
    metrics={'wpm': 50.0, 'backspace_ratio': 0.1},
    classification={'state': 'flow', 'confidence': 0.9, 'reason': 'Focused'},
    user_id='alice'
)

# User 2: Bob
init_db('bob')
save_cycle(
    session_id='bob_session',
    metrics={'wpm': 30.0, 'backspace_ratio': 0.3},
    classification={'state': 'stuck', 'confidence': 0.8, 'reason': 'Struggling'},
    user_id='bob'
)

# Verify isolation
alice_sessions = get_all_sessions('alice')  # Returns only Alice's data
bob_sessions = get_all_sessions('bob')      # Returns only Bob's data

print(f"Alice has {len(alice_sessions)} sessions")
print(f"Bob has {len(bob_sessions)} sessions")
```

## Verifying Data Isolation

### Isolated Mode
```bash
# Check database files exist
ls -lh ~/.auradev/

# Expected output:
# auradev_2bd806c9.db  <- Alice's database
# auradev_81b637d8.db  <- Bob's database

# Query Alice's database directly
sqlite3 ~/.auradev/auradev_2bd806c9.db "SELECT COUNT(*) FROM cycles"

# Query Bob's database directly
sqlite3 ~/.auradev/auradev_81b637d8.db "SELECT COUNT(*) FROM cycles"
```

### Shared Mode
```bash
# Check single database exists
ls -lh ~/.auradev/auradev.db

# Count cycles per user
sqlite3 ~/.auradev/auradev.db "SELECT user_id, COUNT(*) FROM cycles GROUP BY user_id"

# Expected output:
# alice|20
# bob|15
```

## Troubleshooting

**"Permission denied" when running shell script:**
```bash
chmod +x examples/multi_user_demo.sh
```

**"uvicorn: command not found":**
```bash
pip install uvicorn
```

**Tests failing:**
```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run tests
python -m pytest test_multiuser.py -v
```

**Database not found:**
```bash
# Check DB_DIR is set correctly
echo $DB_DIR

# Check database location
ls -la ~/.auradev/

# Verify DB_MODE matches your setup
echo $DB_MODE
```

## Documentation

- Full deployment guide: `../DEPLOYMENT.md`
- Multi-tenant architecture: `../docs/multi-tenant-database.md`
- Quick reference: `../docs/multi-tenant-quick-reference.md`
- API documentation: http://localhost:8765/docs (when API is running)

## Support

For issues or questions:
1. Check the troubleshooting sections in README.md
2. Review DEPLOYMENT.md for platform-specific guidance
3. Open an issue on GitHub with reproduction steps
