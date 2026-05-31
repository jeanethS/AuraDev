"""SQLite database module for auradev.

Uses sqlite3 from the stdlib. Supports multi-tenant architecture:
- Isolated mode: separate DB file per user (~/.auradev/auradev_{hash}.db)
- Shared mode: single DB file with user_id filtering (~/.auradev/auradev.db)
"""

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

def get_db_path(user_id: str = "default") -> Path:
    """Get database path based on mode and user_id.
    
    Args:
        user_id: User identifier for multi-tenant support
        
    Returns:
        Path to database file:
        - Isolated mode: ~/.auradev/auradev_{hash}.db (separate file per user)
        - Shared mode: ~/.auradev/auradev.db (single file, all users)
    """
    # Read DB_MODE dynamically to support runtime changes (e.g., in tests)
    db_mode = os.getenv("DB_MODE", "isolated")
    _db_dir = os.getenv("DB_DIR")
    
    if _db_dir:
        base_dir = Path(_db_dir)
    else:
        # Default to ~/.auradev/ directory
        base_dir = Path.home() / ".auradev"
    
    base_dir.mkdir(parents=True, exist_ok=True)
    
    if db_mode == "shared":
        return base_dir / "auradev.db"
    else:  # isolated mode (default)
        # Create hash of user_id for filename
        user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
        return base_dir / f"auradev_{user_hash}.db"


# Legacy global variable for backward compatibility
DB_PATH = get_db_path("default")


def init_db(user_id: str = "default") -> None:
    """Create table if not exists. Call once at startup.
    
    Args:
        user_id: User identifier for multi-tenant support
    """
    db_path = get_db_path(user_id)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cycles (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       TEXT NOT NULL,
                user_id          TEXT NOT NULL DEFAULT 'default',
                timestamp        TEXT NOT NULL,
                state            TEXT NOT NULL,
                confidence       REAL,
                reason           TEXT,
                wpm              REAL,
                backspace_ratio  REAL,
                window_switches  INTEGER,
                mouse_distance   REAL,
                cpu_percent      REAL,
                idle_seconds     REAL,
                active_window    TEXT
            )
            """
        )
        
        # Create index on user_id for shared mode performance
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cycles_user_id 
            ON cycles(user_id)
            """
        )
        
        # Create index on session_id for queries
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cycles_session_id 
            ON cycles(session_id)
            """
        )
        
        # Create composite index for user_id + session_id
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cycles_user_session 
            ON cycles(user_id, session_id)
            """
        )
        
        conn.commit()
    finally:
        conn.close()


def save_cycle(session_id: str, metrics: dict, classification: dict, user_id: str = "default") -> None:
    """Insert a cycle row. Called from SessionLogger.log_cycle().
    
    Args:
        session_id: Session identifier
        metrics: Telemetry metrics dictionary
        classification: State classification dictionary
        user_id: User identifier for multi-tenant support
    """
    db_path = get_db_path(user_id)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO cycles
            (session_id, user_id, timestamp, state, confidence, reason,
             wpm, backspace_ratio, window_switches, mouse_distance,
             cpu_percent, idle_seconds, active_window)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                datetime.now().isoformat(),
                classification.get("state", "reviewing"),
                classification.get("confidence", 0.0),
                classification.get("reason", ""),
                metrics.get("wpm", 0.0),
                metrics.get("backspace_ratio", 0.0),
                metrics.get("window_switches", 0),
                metrics.get("mouse_distance", 0.0),
                metrics.get("cpu_percent", 0.0),
                metrics.get("idle_seconds", 0.0),
                metrics.get("active_window", ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_session_cycles(session_id: str, user_id: str = "default") -> list[dict]:
    """Return all rows for a session, ordered by timestamp ASC.
    
    Args:
        session_id: Session identifier
        user_id: User identifier for multi-tenant support
        
    Returns:
        List of cycle dictionaries for the specified session
    """
    db_path = get_db_path(user_id)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        db_mode = os.getenv("DB_MODE", "isolated")
        if db_mode == "shared":
            # Filter by both session_id and user_id in shared mode
            cursor.execute(
                """
                SELECT * FROM cycles 
                WHERE session_id = ? AND user_id = ? 
                ORDER BY timestamp ASC
                """,
                (session_id, user_id),
            )
        else:
            # In isolated mode, each user has their own DB, so no user_id filter needed
            cursor.execute(
                """
                SELECT * FROM cycles WHERE session_id = ? ORDER BY timestamp ASC
                """,
                (session_id,),
            )
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_insights(user_id: str = "default") -> dict:
    """
    Aggregate stats across all sessions for a user:
    - avg_flow_pct: percentage of cycles in 'flow' state
    - avg_wpm_by_state: dict mapping state -> avg wpm
    - peak_hours: list of hours (0-23) ranked by flow rate
    - total_sessions, total_cycles, avg_session_duration_minutes
    
    Args:
        user_id: User identifier for multi-tenant support
        
    Returns:
        Dictionary with aggregate insights
    """
    db_path = get_db_path(user_id)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Build WHERE clause for user filtering in shared mode
        db_mode = os.getenv("DB_MODE", "isolated")
        where_clause = "WHERE user_id = ?" if db_mode == "shared" else ""
        params = (user_id,) if db_mode == "shared" else ()

        # Total cycles and flow percentage
        cursor.execute(f"SELECT COUNT(*) as total FROM cycles {where_clause}", params)
        total_cycles = cursor.fetchone()["total"]
        if total_cycles == 0:
            return {
                "total_sessions": 0,
                "total_cycles": 0,
                "avg_flow_pct": 0.0,
                "avg_wpm_by_state": {},
                "peak_hours": [],
                "avg_session_duration_minutes": 0.0,
            }

        cursor.execute(
            f"SELECT COUNT(*) as flow_count FROM cycles {where_clause} {'AND' if where_clause else 'WHERE'} state = 'flow'",
            params
        )
        flow_count = cursor.fetchone()["flow_count"]
        avg_flow_pct = round((flow_count / total_cycles) * 100, 1)

        # Avg WPM by state
        cursor.execute(
            f"""
            SELECT state, AVG(wpm) as avg_wpm
            FROM cycles
            {where_clause}
            GROUP BY state
            """,
            params
        )
        avg_wpm_by_state = {row["state"]: round(row["avg_wpm"], 1) for row in cursor.fetchall()}

        # Peak hours: extract hour from ISO timestamp, calc flow rate per hour
        cursor.execute(
            f"""
            SELECT
                CAST(SUBSTR(timestamp, 12, 2) AS INTEGER) as hour,
                COUNT(*) as total,
                SUM(CASE WHEN state = 'flow' THEN 1 ELSE 0 END) as flow_count
            FROM cycles
            {where_clause}
            GROUP BY hour
            ORDER BY (CAST(flow_count AS REAL) / total) DESC
            """,
            params
        )
        peak_hours = [
            {"hour": row["hour"], "flow_rate": round(row["flow_count"] / row["total"] * 100, 1)}
            for row in cursor.fetchall()
        ]

        # Session count and avg duration
        cursor.execute(
            f"""
            SELECT COUNT(DISTINCT session_id) as session_count FROM cycles {where_clause}
            """,
            params
        )
        total_sessions = cursor.fetchone()["session_count"]

        cursor.execute(
            f"""
            SELECT
                session_id,
                MIN(timestamp) as started_at,
                MAX(timestamp) as ended_at
            FROM cycles
            {where_clause}
            GROUP BY session_id
            """,
            params
        )
        durations = []
        for row in cursor.fetchall():
            try:
                start = datetime.fromisoformat(row["started_at"])
                end = datetime.fromisoformat(row["ended_at"])
                durations.append((end - start).total_seconds() / 60.0)
            except (ValueError, TypeError):
                pass
        avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

        return {
            "total_sessions": total_sessions,
            "total_cycles": total_cycles,
            "avg_flow_pct": avg_flow_pct,
            "avg_wpm_by_state": avg_wpm_by_state,
            "peak_hours": peak_hours,
            "avg_session_duration_minutes": avg_duration,
        }
    finally:
        conn.close()


def get_habits(user_id: str = "default") -> dict:
    """
    Cross-session patterns for a user:
    - flow_by_day: {0-6 (Mon-Sun)} -> flow rate
    - flow_by_hour: {0-23} -> flow rate
    - window_correlations: which active_window values correlate with flow
    
    Args:
        user_id: User identifier for multi-tenant support
        
    Returns:
        Dictionary with habit patterns
    """
    db_path = get_db_path(user_id)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Build WHERE clause for user filtering in shared mode
        db_mode = os.getenv("DB_MODE", "isolated")
        where_clause = "WHERE user_id = ?" if db_mode == "shared" else ""
        params = (user_id,) if db_mode == "shared" else ()

        cursor.execute(f"SELECT COUNT(*) as total FROM cycles {where_clause}", params)
        total = cursor.fetchone()["total"]
        if total == 0:
            return {
                "flow_by_day": {},
                "flow_by_hour": {},
                "window_correlations": [],
            }

        # Flow rate by day of week (0=Monday, 6=Sunday)
        # SQLite strftime %w: 0=Sunday, so we adjust
        cursor.execute(
            f"""
            SELECT
                CAST(strftime('%w', timestamp) AS INTEGER) as dow,
                COUNT(*) as total,
                SUM(CASE WHEN state = 'flow' THEN 1 ELSE 0 END) as flow_count
            FROM cycles
            {where_clause}
            GROUP BY dow
            """,
            params
        )
        flow_by_day_raw = {}
        for row in cursor.fetchall():
            # Convert SQLite %w (0=Sun) to ISO (0=Mon)
            dow_sqlite = row["dow"]
            dow_iso = (dow_sqlite + 6) % 7  # Sun=6, Mon=0, Tue=1, etc.
            flow_by_day_raw[dow_iso] = round(row["flow_count"] / row["total"] * 100, 1)
        flow_by_day = dict(sorted(flow_by_day_raw.items()))

        # Flow rate by hour
        cursor.execute(
            f"""
            SELECT
                CAST(SUBSTR(timestamp, 12, 2) AS INTEGER) as hour,
                COUNT(*) as total,
                SUM(CASE WHEN state = 'flow' THEN 1 ELSE 0 END) as flow_count
            FROM cycles
            {where_clause}
            GROUP BY hour
            ORDER BY hour
            """,
            params
        )
        flow_by_hour = {
            row["hour"]: round(row["flow_count"] / row["total"] * 100, 1)
            for row in cursor.fetchall()
        }

        # Window correlations: which active_window values have highest flow rate
        # Only include windows with >= 3 cycles (statistical significance)
        cursor.execute(
            f"""
            SELECT
                active_window,
                COUNT(*) as total,
                SUM(CASE WHEN state = 'flow' THEN 1 ELSE 0 END) as flow_count,
                AVG(wpm) as avg_wpm
            FROM cycles
            {where_clause} {'AND' if where_clause else 'WHERE'} active_window != ''
            GROUP BY active_window
            HAVING COUNT(*) >= 3
            ORDER BY (CAST(flow_count AS REAL) / total) DESC
            LIMIT 20
            """,
            params
        )
        window_correlations = [
            {
                "window": row["active_window"],
                "flow_rate": round(row["flow_count"] / row["total"] * 100, 1),
                "total_cycles": row["total"],
                "avg_wpm": round(row["avg_wpm"], 1),
            }
            for row in cursor.fetchall()
        ]

        return {
            "flow_by_day": flow_by_day,
            "flow_by_hour": flow_by_hour,
            "window_correlations": window_correlations,
        }
    finally:
        conn.close()


def get_all_sessions(user_id: str = "default") -> list[dict]:
    """
    Return distinct session_ids for a user with:
    - started_at (first timestamp)
    - ended_at (last timestamp)
    - cycle_count
    - state_breakdown as JSON string: {"flow": 5, "stuck": 3, ...}
    Ordered by started_at DESC.
    
    Args:
        user_id: User identifier for multi-tenant support
        
    Returns:
        List of session dictionaries
    """
    db_path = get_db_path(user_id)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Build WHERE clause for user filtering in shared mode
        db_mode = os.getenv("DB_MODE", "isolated")
        where_clause = "WHERE user_id = ?" if db_mode == "shared" else ""
        params = (user_id,) if db_mode == "shared" else ()
        
        cursor.execute(
            f"""
            SELECT
                session_id,
                MIN(timestamp) as started_at,
                MAX(timestamp) as ended_at,
                COUNT(*) as cycle_count
            FROM cycles
            {where_clause}
            GROUP BY session_id
            ORDER BY started_at DESC
            """,
            params
        )
        session_rows = cursor.fetchall()

        result: list[dict] = []
        for row in session_rows:
            sid = row["session_id"]
            
            if db_mode == "shared":
                cursor.execute(
                    """
                    SELECT state, COUNT(*) as cnt
                    FROM cycles
                    WHERE session_id = ? AND user_id = ?
                    GROUP BY state
                    """,
                    (sid, user_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT state, COUNT(*) as cnt
                    FROM cycles
                    WHERE session_id = ?
                    GROUP BY state
                    """,
                    (sid,),
                )
            
            state_rows = cursor.fetchall()
            breakdown = {r["state"]: r["cnt"] for r in state_rows}
            result.append(
                {
                    "session_id": sid,
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "cycle_count": row["cycle_count"],
                    "state_breakdown": json.dumps(breakdown),
                }
            )

        return result
    finally:
        conn.close()
