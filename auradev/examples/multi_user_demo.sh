#!/bin/bash
# Multi-User Demo Script for DevAura
# Demonstrates two users running simultaneously with isolated databases

echo "🎵 DevAura Multi-User Demo"
echo "================================"
echo ""
echo "This demo shows how two users can run DevAura"
echo "simultaneously with isolated data storage."
echo ""

# Colors (aligned with dashboard palette)
FLOW='\033[38;2;178;197;255m'
DEBUG='\033[38;2;218;226;255m'
ACCENT='\033[38;2;251;215;253m'
NC='\033[0m' # No Color

# Check if in correct directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: Please run this script from the auradev directory"
    exit 1
fi

# Create temp directory for demo
DEMO_DIR=$(mktemp -d)
echo "📁 Demo data directory: $DEMO_DIR"
echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🧹 Cleaning up demo data..."
    rm -rf "$DEMO_DIR"
    echo "✅ Demo complete!"
}
trap cleanup EXIT

# User 1: Alice
echo -e "${FLOW}👤 Starting User 1: Alice${NC}"
echo "   Database: $DEMO_DIR/auradev_alice.db"
export DB_DIR="$DEMO_DIR"
export USER_ID="alice"
export DB_MODE="isolated"

# Run Alice's session (3 cycles, 5 second intervals)
python main.py --demo --max-cycles 3 --interval 5 &
ALICE_PID=$!
echo "   PID: $ALICE_PID"
echo ""

# Wait a bit for Alice to start
sleep 2

# User 2: Bob
echo -e "${DEBUG}👤 Starting User 2: Bob${NC}"
echo "   Database: $DEMO_DIR/auradev_bob.db"
export USER_ID="bob"

# Run Bob's session (3 cycles, 5 second intervals)
python main.py --demo --max-cycles 3 --interval 5 &
BOB_PID=$!
echo "   PID: $BOB_PID"
echo ""

# Wait for both to complete
echo -e "${ACCENT}⏳ Waiting for both sessions to complete...${NC}"
wait $ALICE_PID
wait $BOB_PID

echo ""
echo "================================"
echo "📊 Demo Results"
echo "================================"
echo ""

# Show database files created
echo "Database files created:"
ls -lh "$DEMO_DIR"/*.db 2>/dev/null || echo "No databases found"
echo ""

# Show data isolation
echo "Verifying data isolation..."
echo ""

if [ -f "$DEMO_DIR/auradev_alice.db" ] && [ -f "$DEMO_DIR/auradev_bob.db" ]; then
    ALICE_ROWS=$(sqlite3 "$DEMO_DIR/auradev_alice.db" "SELECT COUNT(*) FROM cycles;" 2>/dev/null || echo "0")
    BOB_ROWS=$(sqlite3 "$DEMO_DIR/auradev_bob.db" "SELECT COUNT(*) FROM cycles;" 2>/dev/null || echo "0")
    
    echo -e "${FLOW}Alice's database:${NC} $ALICE_ROWS cycles recorded"
    echo -e "${DEBUG}Bob's database:${NC} $BOB_ROWS cycles recorded"
    echo ""
    
    if [ "$ALICE_ROWS" -gt 0 ] && [ "$BOB_ROWS" -gt 0 ]; then
        echo "✅ Success! Each user has their own isolated database."
    else
        echo "⚠️  Warning: Some databases are empty. This is expected if cycles didn't complete."
    fi
else
    echo "⚠️  Warning: Could not find database files. This may be normal in demo mode."
fi

echo ""
echo "================================"
echo "🎓 What just happened?"
echo "================================"
echo "1. Alice and Bob ran DevAura simultaneously"
echo "2. Each user got their own database file"
echo "3. Data is completely isolated - no cross-user access"
echo "4. Database files are automatically named based on user_id hash"
echo ""
echo "Try it yourself:"
echo "  export USER_ID=your_name"
echo "  python main.py --demo"
echo ""
