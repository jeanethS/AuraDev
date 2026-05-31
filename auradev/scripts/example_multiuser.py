#!/usr/bin/env python3
"""Example usage of multi-tenant database layer."""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import database


def example_isolated_mode():
    """Demonstrate isolated mode with multiple users."""
    print("\n" + "=" * 60)
    print("Example: Isolated Mode")
    print("=" * 60)
    
    # Set isolated mode
    os.environ["DB_MODE"] = "isolated"
    os.environ["DB_DIR"] = str(Path.home() / ".auradev")
    
    # Reload to pick up new config
    import importlib
    importlib.reload(database)
    
    print(f"\nMode: {database.DB_MODE}")
    print(f"Database directory: {os.environ['DB_DIR']}")
    
    # Initialize databases for two users
    database.init_db(user_id="alice")
    database.init_db(user_id="bob")
    
    print(f"\nAlice's database: {database.get_db_path('alice')}")
    print(f"Bob's database: {database.get_db_path('bob')}")
    
    # Alice's session
    print("\n--- Alice's coding session ---")
    database.save_cycle(
        session_id="alice_session_1",
        metrics={"wpm": 65.0, "backspace_ratio": 0.08, "cpu_percent": 45.0},
        classification={"state": "flow", "confidence": 0.92, "reason": "High WPM, low backspace"},
        user_id="alice"
    )
    database.save_cycle(
        session_id="alice_session_1",
        metrics={"wpm": 70.0, "backspace_ratio": 0.05, "cpu_percent": 50.0},
        classification={"state": "flow", "confidence": 0.95, "reason": "Very high WPM"},
        user_id="alice"
    )
    
    # Bob's session
    print("--- Bob's coding session ---")
    database.save_cycle(
        session_id="bob_session_1",
        metrics={"wpm": 25.0, "backspace_ratio": 0.30, "cpu_percent": 30.0},
        classification={"state": "stuck", "confidence": 0.75, "reason": "Low WPM, high backspace"},
        user_id="bob"
    )
    
    # Query Alice's data
    print("\n--- Alice's insights ---")
    alice_insights = database.get_insights(user_id="alice")
    print(f"Total cycles: {alice_insights['total_cycles']}")
    print(f"Flow percentage: {alice_insights['avg_flow_pct']}%")
    print(f"Avg WPM by state: {alice_insights['avg_wpm_by_state']}")
    
    # Query Bob's data
    print("\n--- Bob's insights ---")
    bob_insights = database.get_insights(user_id="bob")
    print(f"Total cycles: {bob_insights['total_cycles']}")
    print(f"Flow percentage: {bob_insights['avg_flow_pct']}%")
    print(f"Avg WPM by state: {bob_insights['avg_wpm_by_state']}")


def example_shared_mode():
    """Demonstrate shared mode with multiple users."""
    print("\n" + "=" * 60)
    print("Example: Shared Mode")
    print("=" * 60)
    
    # Set shared mode
    os.environ["DB_MODE"] = "shared"
    os.environ["DB_DIR"] = str(Path.home() / ".auradev")
    
    # Reload to pick up new config
    import importlib
    importlib.reload(database)
    
    print(f"\nMode: {database.DB_MODE}")
    print(f"Database directory: {os.environ['DB_DIR']}")
    
    # Initialize database
    database.init_db(user_id="alice")
    database.init_db(user_id="bob")
    
    print(f"\nShared database: {database.get_db_path('alice')}")
    print(f"(same for all users: {database.get_db_path('bob')})")
    
    # Alice's session
    print("\n--- Alice's coding session ---")
    database.save_cycle(
        session_id="alice_session_1",
        metrics={"wpm": 65.0, "backspace_ratio": 0.08, "cpu_percent": 45.0},
        classification={"state": "flow", "confidence": 0.92, "reason": "High WPM, low backspace"},
        user_id="alice"
    )
    
    # Bob's session
    print("--- Bob's coding session ---")
    database.save_cycle(
        session_id="bob_session_1",
        metrics={"wpm": 25.0, "backspace_ratio": 0.30, "cpu_percent": 30.0},
        classification={"state": "stuck", "confidence": 0.75, "reason": "Low WPM, high backspace"},
        user_id="bob"
    )
    
    # Query Alice's data - won't see Bob's
    print("\n--- Alice's sessions (doesn't see Bob's) ---")
    alice_sessions = database.get_all_sessions(user_id="alice")
    print(f"Alice's sessions: {[s['session_id'] for s in alice_sessions]}")
    
    # Query Bob's data - won't see Alice's
    print("\n--- Bob's sessions (doesn't see Alice's) ---")
    bob_sessions = database.get_all_sessions(user_id="bob")
    print(f"Bob's sessions: {[s['session_id'] for s in bob_sessions]}")
    
    print("\n✅ Data isolation works in shared mode!")


def example_backward_compatibility():
    """Demonstrate backward compatibility without user_id."""
    print("\n" + "=" * 60)
    print("Example: Backward Compatibility")
    print("=" * 60)
    
    os.environ["DB_MODE"] = "isolated"
    os.environ["DB_DIR"] = str(Path.home() / ".auradev")
    
    import importlib
    importlib.reload(database)
    
    print("\nUsing database functions WITHOUT user_id parameter...")
    print("(defaults to user_id='default')")
    
    # Initialize without user_id
    database.init_db()
    
    # Save cycle without user_id
    database.save_cycle(
        session_id="default_session",
        metrics={"wpm": 50.0, "backspace_ratio": 0.15},
        classification={"state": "reviewing", "confidence": 0.80}
    )
    
    # Query without user_id
    cycles = database.get_session_cycles("default_session")
    print(f"\nCycles retrieved: {len(cycles)}")
    print(f"First cycle user_id: {cycles[0]['user_id']}")
    print(f"First cycle state: {cycles[0]['state']}")
    
    insights = database.get_insights()
    print(f"\nInsights for default user:")
    print(f"Total cycles: {insights['total_cycles']}")
    
    print("\n✅ Backward compatibility maintained!")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("AuraDev Multi-Tenant Database Examples")
    print("=" * 60)
    
    print("\nThese examples demonstrate the multi-tenant database layer.")
    print("Database files will be created in ~/.auradev/")
    
    try:
        example_isolated_mode()
        example_shared_mode()
        example_backward_compatibility()
        
        print("\n" + "=" * 60)
        print("Examples completed successfully!")
        print("=" * 60)
        print(f"\nDatabase files created in: {Path.home() / '.auradev'}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
