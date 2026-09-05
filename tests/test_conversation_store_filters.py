"""Behavior lock tests for the real conversation store implementations.

Verifies that business_id filtering happens inside the stores and is
applied before offset/limit pagination, for the Memory, SQLite and
FileSystem stores alike. The FileSystem store additionally locks the
persistence of conversation metadata (Addendum A5-4).
"""

from datetime import datetime, timedelta

import pytest

from vanna.core.storage.models import Conversation, Message
from vanna.core.user import User
from vanna.integrations.local.file_system_conversation_store import (
    FileSystemConversationStore,
)
from vanna.integrations.local.sqlite_conversation_store import SQLiteConversationStore
from vanna.integrations.local.storage import MemoryConversationStore

USER = User(id="u1", email=None)


@pytest.fixture(params=["memory", "sqlite", "fs"])
def store(request, tmp_path):
    if request.param == "memory":
        yield MemoryConversationStore()
    elif request.param == "sqlite":
        sqlite_store = SQLiteConversationStore(db_path=str(tmp_path / "test.db"))
        yield sqlite_store
        sqlite_store.close()
    else:
        yield FileSystemConversationStore(base_dir=str(tmp_path / "convs"))


def _make_conversation(cid, business_id, updated_at=None):
    return Conversation(
        id=cid,
        user=USER,
        messages=[],
        metadata={"business_id": business_id} if business_id else {},
        **({"updated_at": updated_at} if updated_at else {}),
    )


async def _seed(store, base):
    # Insertion order is also the updated_at order (increasing), so the
    # most recently updated conversation (c3) sorts first in listings.
    await store.update_conversation(_make_conversation("c1", "b1", base))
    await store.update_conversation(
        _make_conversation("c2", None, base + timedelta(seconds=1))
    )
    await store.update_conversation(
        _make_conversation("c3", "b1", base + timedelta(seconds=2))
    )


@pytest.mark.asyncio
async def test_business_id_filter_applied_before_pagination(store):
    base = datetime.now().astimezone()
    await _seed(store, base)

    # Filtered listing returns only the two b1 conversations.
    filtered = await store.list_conversations(USER, business_id="b1")
    assert {c.id for c in filtered} == {"c1", "c3"}

    # Pagination is applied after filtering: limit=1/offset=1 on b1 is
    # the second b1 item, never a conversation of another business.
    paged = await store.list_conversations(USER, limit=1, offset=1, business_id="b1")
    assert len(paged) == 1
    assert paged[0].id in {"c1", "c3"}
    assert paged[0].id == filtered[1].id

    # Without a business_id everything is returned.
    all_conversations = await store.list_conversations(USER)
    assert {c.id for c in all_conversations} == {"c1", "c2", "c3"}


@pytest.mark.asyncio
async def test_filesystem_store_persists_conversation_metadata(tmp_path):
    store = FileSystemConversationStore(base_dir=str(tmp_path / "convs"))
    conversation = Conversation(
        id="c1",
        user=USER,
        messages=[Message(role="user", content="hi")],
        metadata={"business_id": "b1", "title": "Hello"},
    )
    await store.update_conversation(conversation)

    reloaded = await store.get_conversation("c1", USER)
    assert reloaded is not None
    assert reloaded.metadata == {"business_id": "b1", "title": "Hello"}