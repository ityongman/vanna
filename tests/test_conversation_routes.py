from fastapi import FastAPI
from fastapi.testclient import TestClient

from vanna.core.storage.base import ConversationStore
from vanna.core.storage.models import Conversation, Message
from vanna.core.user import CookieEmailUserResolver, User
from vanna.servers.fastapi.conversation_routes import register_conversation_routes


class FakeStore(ConversationStore):
    def __init__(self):
        self._convs = {}

    async def create_conversation(self, conversation_id, user, initial_message):
        conv = Conversation(id=conversation_id, user=user,
                            messages=[Message(role="user", content=initial_message)])
        self._convs[conversation_id] = conv
        return conv

    async def get_conversation(self, conversation_id, user):
        return self._convs.get(conversation_id)

    async def update_conversation(self, conversation):
        self._convs[conversation.id] = conversation

    async def delete_conversation(self, conversation_id, user):
        return self._convs.pop(conversation_id, None) is not None

    async def list_conversations(self, user, limit=50, offset=0, business_id=None):
        convs = list(self._convs.values())
        if business_id is not None:
            convs = [
                c for c in convs if c.metadata.get("business_id") == business_id
            ]
        return convs[offset:offset + limit]


class FakeAgent:
    def __init__(self):
        self.user_resolver = CookieEmailUserResolver()
        self.conversation_store = FakeStore()


def make_client(store=None):
    app = FastAPI()
    agent = FakeAgent()
    if store is not None:
        agent.conversation_store = store
    register_conversation_routes(app, agent)
    return TestClient(app)


def test_list_conversations():
    client = make_client()
    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json() == []


def test_delete_conversation():
    client = make_client()
    resp = client.delete("/api/conversations/nope")
    assert resp.status_code == 404


def test_list_conversations_filtered_by_business():
    store = FakeStore()
    store._convs["c1"] = Conversation(
        id="c1",
        user=User(id="anonymous", email=None),
        messages=[],
        metadata={"business_id": "b1"},
    )
    store._convs["c2"] = Conversation(
        id="c2",
        user=User(id="anonymous", email=None),
        messages=[],
        metadata={"business_id": "b2"},
    )
    store._convs["c3"] = Conversation(
        id="c3",
        user=User(id="anonymous", email=None),
        messages=[],
        metadata={},
    )

    client = make_client(store)

    resp = client.get("/api/conversations?business_id=b1")
    assert resp.status_code == 200
    assert [c["id"] for c in resp.json()] == ["c1"]

    resp_all = client.get("/api/conversations")
    assert resp_all.status_code == 200
    assert len(resp_all.json()) == 3

    # An empty business_id must not filter anything out.
    resp_empty = client.get("/api/conversations?business_id=")
    assert resp_empty.status_code == 200
    assert len(resp_empty.json()) == 3


def test_conversation_filter_applied_before_pagination():
    store = FakeStore()
    # Insertion order kept by the fake store; b1 conversations are c1/c4.
    for cid, business_id in [
        ("c1", "b1"),
        ("c2", "b2"),
        ("c3", None),
        ("c4", "b1"),
        ("c5", "b2"),
    ]:
        store._convs[cid] = Conversation(
            id=cid,
            user=User(id="anonymous", email=None),
            messages=[],
            metadata={"business_id": business_id} if business_id else {},
        )

    client = make_client(store)

    # Filtering must happen before pagination: within b1 the second item
    # (offset=1, limit=1) is c4. Paginating first would only yield c2.
    resp = client.get("/api/conversations?business_id=b1&limit=1&offset=1")
    assert resp.status_code == 200
    assert [c["id"] for c in resp.json()] == ["c4"]
