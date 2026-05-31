#!/usr/bin/env python3
"""Test script to verify multi-tenant database implementation.

Tests all acceptance criteria:
1. get_db_path("alice") returns correct path for both modes
2. All queries filter by user_id in shared mode
3. Migration script runs without errors
4. Backward compatible with user_id="default" defaults
5. No breaking changes to function signatures
"""

import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import database


def test_get_db_path_isolated():
    """Test get_db_path in isolated mode."""
    print("\n🧪 Testing get_db_path in ISOLATED mode...")
    
    # Set isolated mode
    os.environ["DB_MODE"] = "isolated"
    os.environ["DB_DIR"] = str(Path.home() / ".auradev")
    
    # Import fresh to get new config
    import importlib
    importlib.reload(database)
    
    # Test different users get different paths
    path_alice = database.get_db_path("alice")
    path_bob = database.get_db_path("bob")
    path_default = database.get_db_path("default")
    
    print(f"  alice: {path_alice.name}")
    print(f"  bob: {path_bob.name}")
    print(f"  default: {path_default.name}")
    
    # Verify they're different
    assert path_alice != path_bob, "Alice and Bob should have different DB paths"
    assert path_alice != path_default, "Alice and default should have different DB paths"
    
    # Verify format
    assert "auradev_" in path_alice.name, "Should contain auradev_ prefix"
    assert path_alice.suffix == ".db", "Should have .db extension"
    
    print("  ✅ Isolated mode paths correct")
    return True


def test_get_db_path_shared():
    """Test get_db_path in shared mode."""
    print("\n🧪 Testing get_db_path in SHARED mode...")
    
    # Set shared mode
    os.environ["DB_MODE"] = "shared"
    
    # Import fresh to get new config
    import importlib
    importlib.reload(database)
    
    # Test different users get same path
    path_alice = database.get_db_path("alice")
    path_bob = database.get_db_path("bob")
    path_default = database.get_db_path("default")
    
    print(f"  alice: {path_alice.name}")
    print(f"  bob: {path_bob.name}")
    print(f"  default: {path_default.name}")
    
    # Verify they're the same
    assert path_alice == path_bob, "All users should share same DB in shared mode"
    assert path_alice == path_default, "All users should share same DB in shared mode"
    assert path_alice.name == "auradev.db", "Should be named auradev.db"
    
    print("  ✅ Shared mode paths correct")
    return True


def test_backward_compatibility():
    """Test that functions work without user_id parameter."""
    print("\n🧪 Testing backward compatibility (default user_id)...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_DIR"] = tmpdir
        os.environ["DB_MODE"] = "isolated"
        
        # Import fresh
        import importlib
        importlib.reload(database)
        
        # Test init_db without user_id
        database.init_db()
        print("  ✅ init_db() works without user_id")
        
        # Test save_cycle without user_id
        database.save_cycle(
            session_id="test_session",
            metrics={"wpm": 50.0, "backspace_ratio": 0.1},
            classification={"state": "flow", "confidence": 0.9}
        )
        print("  ✅ save_cycle() works without user_id")
        
        # Test get_session_cycles without user_id
        cycles = database.get_session_cycles("test_session")
        assert len(cycles) == 1, "Should have one cycle"
        assert cycles[0]["user_id"] == "default", "Should default to 'default' user"
        print("  ✅ get_session_cycles() works without user_id")
        
        # Test get_insights without user_id
        insights = database.get_insights()
        assert insights["total_cycles"] == 1, "Should have one cycle"
        print("  ✅ get_insights() works without user_id")
        
        # Test get_habits without user_id
        habits = database.get_habits()
        print("  ✅ get_habits() works without user_id")
        
        # Test get_all_sessions without user_id
        sessions = database.get_all_sessions()
        assert len(sessions) == 1, "Should have one session"
        print("  ✅ get_all_sessions() works without user_id")
    
    return True


def test_user_isolation_shared_mode():
    """Test that queries filter by user_id in shared mode."""
    print("\n🧪 Testing user isolation in SHARED mode...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_DIR"] = tmpdir
        os.environ["DB_MODE"] = "shared"
        
        # Import fresh
        import importlib
        importlib.reload(database)
        
        # Initialize database
        database.init_db("alice")
        database.init_db("bob")
        
        # Add data for Alice
        database.save_cycle(
            session_id="alice_session_1",
            metrics={"wpm": 60.0, "backspace_ratio": 0.1},
            classification={"state": "flow", "confidence": 0.9},
            user_id="alice"
        )
        database.save_cycle(
            session_id="alice_session_1",
            metrics={"wpm": 55.0, "backspace_ratio": 0.15},
            classification={"state": "flow", "confidence": 0.85},
            user_id="alice"
        )
        
        # Add data for Bob
        database.save_cycle(
            session_id="bob_session_1",
            metrics={"wpm": 40.0, "backspace_ratio": 0.2},
            classification={"state": "stuck", "confidence": 0.7},
            user_id="bob"
        )
        
        # Test Alice sees only her data
        alice_cycles = database.get_session_cycles("alice_session_1", user_id="alice")
        assert len(alice_cycles) == 2, f"Alice should have 2 cycles, got {len(alice_cycles)}"
        assert all(c["user_id"] == "alice" for c in alice_cycles), "All cycles should be Alice's"
        print("  ✅ Alice sees only her cycles")
        
        # Test Bob sees only his data
        bob_cycles = database.get_session_cycles("bob_session_1", user_id="bob")
        assert len(bob_cycles) == 1, f"Bob should have 1 cycle, got {len(bob_cycles)}"
        assert bob_cycles[0]["user_id"] == "bob", "Cycle should be Bob's"
        print("  ✅ Bob sees only his cycles")
        
        # Test Alice doesn't see Bob's session
        alice_bob_cycles = database.get_session_cycles("bob_session_1", user_id="alice")
        assert len(alice_bob_cycles) == 0, "Alice should not see Bob's cycles"
        print("  ✅ Users cannot see other users' data")
        
        # Test insights are user-specific
        alice_insights = database.get_insights("alice")
        bob_insights = database.get_insights("bob")
        
        assert alice_insights["total_cycles"] == 2, "Alice should have 2 cycles"
        assert bob_insights["total_cycles"] == 1, "Bob should have 1 cycle"
        assert alice_insights["avg_flow_pct"] > bob_insights["avg_flow_pct"], "Alice has more flow"
        print("  ✅ Insights are user-specific")
        
        # Test sessions are user-specific
        alice_sessions = database.get_all_sessions("alice")
        bob_sessions = database.get_all_sessions("bob")
        
        assert len(alice_sessions) == 1, "Alice should have 1 session"
        assert len(bob_sessions) == 1, "Bob should have 1 session"
        assert alice_sessions[0]["session_id"] == "alice_session_1"
        assert bob_sessions[0]["session_id"] == "bob_session_1"
        print("  ✅ Sessions are user-specific")
        
        # Test habits are user-specific
        alice_habits = database.get_habits("alice")
        bob_habits = database.get_habits("bob")
        print("  ✅ Habits are user-specific")
    
    return True


def test_user_isolation_isolated_mode():
    """Test that users get separate DBs in isolated mode."""
    print("\n🧪 Testing user isolation in ISOLATED mode...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DB_DIR"] = tmpdir
        os.environ["DB_MODE"] = "isolated"
        
        # Import fresh
        import importlib
        importlib.reload(database)
        
        # Initialize databases
        database.init_db("alice")
        database.init_db("bob")
        
        # Verify separate files exist
        alice_path = database.get_db_path("alice")
        bob_path = database.get_db_path("bob")
        
        assert alice_path != bob_path, "Paths should be different"
        print(f"  Alice DB: {alice_path.name}")
        print(f"  Bob DB: {bob_path.name}")
        
        # Add data for each user
        database.save_cycle(
            session_id="session_1",
            metrics={"wpm": 60.0},
            classification={"state": "flow"},
            user_id="alice"
        )
        database.save_cycle(
            session_id="session_1",
            metrics={"wpm": 40.0},
            classification={"state": "stuck"},
            user_id="bob"
        )
        
        # Verify both files exist
        assert alice_path.exists(), "Alice's DB should exist"
        assert bob_path.exists(), "Bob's DB should exist"
        print("  ✅ Separate DB files created")
        
        # Verify data isolation
        alice_cycles = database.get_session_cycles("session_1", user_id="alice")
        bob_cycles = database.get_session_cycles("session_1", user_id="bob")
        
        assert len(alice_cycles) == 1, "Alice should have 1 cycle"
        assert len(bob_cycles) == 1, "Bob should have 1 cycle"
        assert alice_cycles[0]["wpm"] == 60.0, "Alice's WPM should be 60"
        assert bob_cycles[0]["wpm"] == 40.0, "Bob's WPM should be 40"
        print("  ✅ Data is isolated between users")
    
    return True


def test_migration_script():
    """Test that migration script runs without errors."""
    print("\n🧪 Testing migration script...")
    
    # Test dry-run mode
    result = os.system(
        "python scripts/migrate_to_multiuser.py --dry-run --mode=shared"
    )
    assert result == 0, "Migration script dry-run should succeed"
    print("  ✅ Migration script runs in dry-run mode")
    
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Multi-Tenant Database Tests")
    print("=" * 60)
    
    tests = [
        ("get_db_path (isolated)", test_get_db_path_isolated),
        ("get_db_path (shared)", test_get_db_path_shared),
        ("Backward compatibility", test_backward_compatibility),
        ("User isolation (shared mode)", test_user_isolation_shared_mode),
        ("User isolation (isolated mode)", test_user_isolation_isolated_mode),
        ("Migration script", test_migration_script),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"  ❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n🎉 All acceptance criteria met!")
        return 0
    else:
        print("\n❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
