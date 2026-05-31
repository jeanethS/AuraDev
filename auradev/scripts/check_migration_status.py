#!/usr/bin/env python3
"""Check if database needs migration to multi-user format."""

import sqlite3
import sys
from pathlib import Path


def check_database(db_path: Path) -> dict:
    """Check database schema and return status.
    
    Args:
        db_path: Path to database file
        
    Returns:
        Dictionary with status information
    """
    if not db_path.exists():
        return {
            "exists": False,
            "needs_migration": False,
            "message": f"Database not found: {db_path}"
        }
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if cycles table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cycles'"
        )
        if not cursor.fetchone():
            conn.close()
            return {
                "exists": True,
                "needs_migration": False,
                "message": "Database exists but has no cycles table"
            }
        
        # Check columns
        cursor.execute("PRAGMA table_info(cycles)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # Check if user_id column exists
        has_user_id = "user_id" in columns
        
        # Count records
        cursor.execute("SELECT COUNT(*) FROM cycles")
        total_cycles = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "exists": True,
            "has_user_id": has_user_id,
            "needs_migration": not has_user_id,
            "columns": columns,
            "total_cycles": total_cycles,
            "message": "✅ Already migrated" if has_user_id else "⚠️  Needs migration"
        }
        
    except Exception as e:
        return {
            "exists": True,
            "error": str(e),
            "message": f"❌ Error checking database: {e}"
        }


def main():
    """Check database status."""
    print("=" * 60)
    print("Database Migration Status Check")
    print("=" * 60)
    
    # Check project root database
    project_db = Path(__file__).parent.parent / "auradev.db"
    print(f"\nChecking: {project_db}")
    status = check_database(project_db)
    
    print(f"Status: {status['message']}")
    if status.get("exists"):
        if "columns" in status:
            print(f"Columns: {', '.join(status['columns'])}")
        if "total_cycles" in status:
            print(f"Total cycles: {status['total_cycles']}")
        
        if status.get("needs_migration"):
            print("\n" + "=" * 60)
            print("Migration Required")
            print("=" * 60)
            print("\nTo migrate this database, run:")
            print("\n  Shared mode (single DB, all users):")
            print(f"    python scripts/migrate_to_multiuser.py --mode=shared")
            print("\n  Isolated mode (separate DB per user):")
            print(f"    python scripts/migrate_to_multiuser.py --mode=isolated")
            print("\nBoth commands will create a backup before making changes.")
    
    # Check ~/.auradev/ directory
    home_db_dir = Path.home() / ".auradev"
    if home_db_dir.exists():
        print(f"\n" + "=" * 60)
        print(f"Checking ~/.auradev/ directory")
        print("=" * 60)
        
        for db_file in home_db_dir.glob("*.db"):
            print(f"\nChecking: {db_file.name}")
            status = check_database(db_file)
            print(f"Status: {status['message']}")
            if "total_cycles" in status:
                print(f"Total cycles: {status['total_cycles']}")


if __name__ == "__main__":
    main()
