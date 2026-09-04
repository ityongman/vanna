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

    async def list_conversations(self, user, limit=50, offset=0):
        convs = list(self._convs.values())
        return convs[offset:offset + limit]


class FakeAgent:
    def __init__(self):
        self.user_resolver = CookieEmailUserResolver()
        self.conversation_store = FakeStore()


def make_client():
    app = FastAPI()
    register_conversation_routes(app, FakeAgent())
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
