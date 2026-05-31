#!/usr/bin/env python3
"""Migration script to add multi-user support to existing auradev database.

This script handles two migration modes:
1. Shared mode: Adds user_id column to existing auradev.db with default 'default' value
2. Isolated mode: Renames existing auradev.db to auradev_{hash}.db for default user

Usage:
    python scripts/migrate_to_multiuser.py [--mode=isolated|shared] [--user-id=default]

Environment:
    DB_MODE: Set to 'isolated' or 'shared' (default: isolated)
    DB_DIR: Custom database directory (default: ~/.auradev)
"""

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def get_db_dir() -> Path:
    """Get the database directory."""
    db_dir = os.getenv("DB_DIR")
    if db_dir:
        return Path(db_dir)
    else:
        return Path.home() / ".auradev"


def get_user_hash(user_id: str) -> str:
    """Get 8-character hash of user_id."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:8]


def backup_database(db_path: Path) -> Path:
    """Create a backup of the database file.
    
    Args:
        db_path: Path to database file
        
    Returns:
        Path to backup file
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}_backup_{timestamp}.db")
    
    if db_path.exists():
        shutil.copy2(db_path, backup_path)
        print(f"✅ Created backup: {backup_path}")
        return backup_path
    else:
        print(f"⚠️  No existing database found at {db_path}")
        return None


def migrate_to_shared(db_dir: Path, default_user_id: str = "default") -> bool:
    """Migrate database to shared mode by adding user_id column.
    
    Args:
        db_dir: Database directory
        default_user_id: Default user ID for existing records
        
    Returns:
        True if migration succeeded
    """
    db_path = db_dir / "auradev.db"
    
    print(f"\n📊 Migrating to SHARED mode...")
    print(f"   Database: {db_path}")
    print(f"   Default user_id: {default_user_id}")
    
    # Backup first
    backup_path = backup_database(db_path)
    
    if not db_path.exists():
        print(f"⚠️  No existing database found. Migration not needed.")
        return True
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if user_id column already exists
        cursor.execute("PRAGMA table_info(cycles)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "user_id" in columns:
            print(f"✅ user_id column already exists. Migration not needed.")
            conn.close()
            return True
        
        # Add user_id column with default value
        print(f"   Adding user_id column...")
        cursor.execute(
            f"""
            ALTER TABLE cycles 
            ADD COLUMN user_id TEXT NOT NULL DEFAULT '{default_user_id}'
            """
        )
        
        # Create index on user_id
        print(f"   Creating index on user_id...")
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cycles_user_id 
            ON cycles(user_id)
            """
        )
        
        # Create composite index for user_id + session_id
        print(f"   Creating composite index...")
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cycles_user_session 
            ON cycles(user_id, session_id)
            """
        )
        
        # Create session_id index if it doesn't exist
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cycles_session_id 
            ON cycles(session_id)
            """
        )
        
        conn.commit()
        
        # Verify migration
        cursor.execute("SELECT COUNT(*) as total FROM cycles")
        total_rows = cursor.fetchone()[0]
        
        cursor.execute(
            f"SELECT COUNT(*) as user_rows FROM cycles WHERE user_id = '{default_user_id}'"
        )
        user_rows = cursor.fetchone()[0]
        
        conn.close()
        
        print(f"✅ Migration completed successfully!")
        print(f"   Total rows: {total_rows}")
        print(f"   Rows with user_id='{default_user_id}': {user_rows}")
        
        if backup_path:
            print(f"\n💾 Backup saved at: {backup_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        
        if backup_path and backup_path.exists():
            print(f"   Restoring from backup...")
            shutil.copy2(backup_path, db_path)
            print(f"   ✅ Database restored from backup")
        
        return False


def migrate_to_isolated(db_dir: Path, default_user_id: str = "default") -> bool:
    """Migrate database to isolated mode by renaming to user-specific file.
    
    Args:
        db_dir: Database directory
        default_user_id: User ID for the existing database
        
    Returns:
        True if migration succeeded
    """
    source_path = db_dir / "auradev.db"
    user_hash = get_user_hash(default_user_id)
    target_path = db_dir / f"auradev_{user_hash}.db"
    
    print(f"\n📊 Migrating to ISOLATED mode...")
    print(f"   Source: {source_path}")
    print(f"   Target: {target_path}")
    print(f"   User ID: {default_user_id}")
    
    # Backup first
    backup_path = backup_database(source_path)
    
    if not source_path.exists():
        print(f"⚠️  No existing database found. Migration not needed.")
        return True
    
    if target_path.exists():
        print(f"⚠️  Target file already exists: {target_path}")
        response = input(f"   Overwrite? (y/N): ")
        if response.lower() != 'y':
            print(f"   Migration cancelled.")
            return False
    
    try:
        # Rename/move the database file
        print(f"   Moving database file...")
        shutil.move(source_path, target_path)
        
        print(f"✅ Migration completed successfully!")
        print(f"   Database moved to: {target_path}")
        
        if backup_path:
            print(f"\n💾 Backup saved at: {backup_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        
        if backup_path and backup_path.exists():
            print(f"   Restoring from backup...")
            shutil.copy2(backup_path, source_path)
            print(f"   ✅ Database restored from backup")
        
        return False


def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(
        description="Migrate auradev database to multi-user support"
    )
    parser.add_argument(
        "--mode",
        choices=["isolated", "shared"],
        default=os.getenv("DB_MODE", "isolated"),
        help="Migration mode: isolated (separate DB per user) or shared (single DB with user_id)",
    )
    parser.add_argument(
        "--user-id",
        default="default",
        help="User ID for existing data (default: 'default')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("AuraDev Multi-User Migration Script")
    print("=" * 60)
    
    db_dir = get_db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nConfiguration:")
    print(f"  Mode: {args.mode}")
    print(f"  Database directory: {db_dir}")
    print(f"  User ID: {args.user_id}")
    print(f"  Dry run: {args.dry_run}")
    
    if args.dry_run:
        print(f"\n🔍 DRY RUN MODE - No changes will be made")
        if args.mode == "shared":
            print(f"   Would add user_id column to {db_dir / 'auradev.db'}")
            print(f"   Would set default value to '{args.user_id}'")
            print(f"   Would create indexes on user_id")
        else:
            user_hash = get_user_hash(args.user_id)
            print(f"   Would rename {db_dir / 'auradev.db'}")
            print(f"   to {db_dir / f'auradev_{user_hash}.db'}")
        return 0
    
    # Confirm before proceeding
    print(f"\n⚠️  This will modify your database.")
    response = input(f"   Continue? (y/N): ")
    if response.lower() != 'y':
        print(f"   Migration cancelled.")
        return 0
    
    # Run migration
    if args.mode == "shared":
        success = migrate_to_shared(db_dir, args.user_id)
    else:
        success = migrate_to_isolated(db_dir, args.user_id)
    
    if success:
        print(f"\n🎉 Migration completed successfully!")
        print(f"\n💡 Next steps:")
        print(f"   1. Set DB_MODE={args.mode} in your environment")
        print(f"   2. Restart your auradev application")
        return 0
    else:
        print(f"\n❌ Migration failed. See errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
