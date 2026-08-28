"""
SQLite conversation store implementation.

This module provides a SQLite-backed implementation of the ConversationStore
interface that persists conversations to a single database file, suitable for
local development and single-node deployments.
"""

import json
import sqlite3
import threading
from typing import List, Optional

from vanna.core.storage import Conversation, ConversationStore, Message
from vanna.core.user import User


class SQLiteConversationStore(ConversationStore):
    """SQLite-backed conversation store.

    Stores each conversation as a single row: indexed columns for user
    scoping and updated_at ordering, with the full conversation (including
    messages) serialized as JSON for lossless round-tripping through the
    pydantic models.
    """

    def __init__(self, db_path: str = "conversations.db") -> None:
        """Initialize the SQLite conversation store.

        Args:
            db_path: Path to the SQLite database file. Parent directories
                are created automatically.
        """
        import os

        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                data TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user_updated "
            "ON conversations (user_id, updated_at DESC)"
        )
        self._conn.commit()

    def _serialize(self, conversation: Conversation) -> str:
        """Serialize a conversation to a JSON string."""
        return conversation.model_dump_json()

    def _deserialize(self, data: str) -> Conversation:
        """Deserialize a conversation from a JSON string."""
        return Conversation.model_validate(json.loads(data))

    async def create_conversation(
        self, conversation_id: str, user: User, initial_message: str
    ) -> Conversation:
        """Create a new conversation with the specified ID."""
        conversation = Conversation(
            id=conversation_id,
            user=user,
            messages=[Message(role="user", content=initial_message)],
        )
        await self.update_conversation(conversation)
        return conversation

    async def get_conversation(
        self, conversation_id: str, user: User
    ) -> Optional[Conversation]:
        """Get conversation by ID, scoped to user."""
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, data FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()

        if not row or row[0] != user.id:
            return None

        try:
            return self._deserialize(row[1])
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Failed to load conversation {conversation_id}: {e}")
            return None

    async def update_conversation(self, conversation: Conversation) -> None:
        """Update conversation with new messages."""
        data = self._serialize(conversation)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO conversations (id, user_id, created_at, updated_at, data)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    user_id = excluded.user_id,
                    updated_at = excluded.updated_at,
                    data = excluded.data
                """,
                (
                    conversation.id,
                    conversation.user.id,
                    conversation.created_at.isoformat(),
                    conversation.updated_at.isoformat(),
                    data,
                ),
            )
            self._conn.commit()

    async def delete_conversation(self, conversation_id: str, user: User) -> bool:
        """Delete conversation."""
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()

            if not row or row[0] != user.id:
                return False

            self._conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            self._conn.commit()
            return True

    async def list_conversations(
        self, user: User, limit: int = 50, offset: int = 0
    ) -> List[Conversation]:
        """List conversations for user, most recently updated first."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT data FROM conversations
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (user.id, limit, offset),
            ).fetchall()

        conversations = []
        for (data,) in rows:
            try:
                conversations.append(self._deserialize(data))
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Failed to deserialize conversation: {e}")
                continue
        return conversations

    def close(self) -> None:
        """Close the underlying database connection."""
        with self._lock:
            self._conn.close()
