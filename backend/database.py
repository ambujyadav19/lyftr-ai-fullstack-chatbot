import sqlite3
import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from config import settings

def get_connection() -> sqlite3.Connection:
    db_path = settings.sqlite_db_path
    
    # Ensure directory exists if path has directory components
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        metadata TEXT,
        created_at TEXT NOT NULL
    );
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id);
    """)
    conn.commit()
    conn.close()

def check_db_health() -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        res = cursor.fetchone()
        conn.close()
        return res is not None
    except Exception:
        return False

def get_session_messages(session_id: str) -> Optional[List[Dict[str, Any]]]:
    """
    Returns stored history of one session from SQLite, oldest first, without the system prompt.
    Returns None if the session does not exist (unknown session).
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id ASC;",
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    result = []
    for row in rows:
        item: Dict[str, Any] = {
            "role": row["role"],
            "content": row["content"]
        }
        if row["metadata"]:
            try:
                item["metadata"] = json.loads(row["metadata"])
            except Exception:
                item["metadata"] = row["metadata"]
        result.append(item)
    return result

def get_session_history_for_llm(session_id: str) -> List[Dict[str, str]]:
    """
    Returns existing user and assistant messages for LLM context.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC;",
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"role": row["role"], "content": row["content"]} for row in rows]

def save_message(session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
    conn = get_connection()
    cursor = conn.cursor()
    created_at = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata) if metadata else None
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?);",
        (session_id, role, content, meta_json, created_at)
    )
    conn.commit()
    conn.close()
