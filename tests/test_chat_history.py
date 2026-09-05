"""Tests for chat history persistence: rich components, empty-session
skipping, title generation and business isolation (C1-C4)."""

import pytest

from vanna.core.llm import LlmService
from vanna.core.llm.models import LlmRequest, LlmResponse, LlmStreamChunk
from vanna.core.storage.base import ConversationStore
from vanna.core.storage.models import Conversation, Message
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver


class FakeStore(ConversationStore):
    """In-memory conversation store for agent tests."""

    def __init__(self):
        self._convs = {}

    async def create_conversation(self, conversation_id, user, initial_message):
        conv = Conversation(
            id=conversation_id,
            user=user,
            messages=[Message(role="user", content=initial_message)],
        )
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
        return convs[offset : offset + limit]


class SimpleUserResolver(UserResolver):
    """Always resolves to the same test user."""

    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(id="test_user", email="test@example.com")


class FakeLlmService(LlmService):
    """Configurable fake LLM.

    ``reply`` is streamed for every chat turn; ``title`` is returned by
    ``send_request`` when the request metadata carries
    ``purpose == "conversation_title"``. ``fail_title`` makes title
    generation raise, exercising the fallback path.
    """

    def __init__(self, reply="Hello from the agent", title=None, fail_title=False):
        self.reply = reply
        self.title = title
        self.fail_title = fail_title

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        if request.metadata.get("purpose") == "conversation_title":
            if self.fail_title:
                raise RuntimeError("title LLM unavailable")
            return LlmResponse(content=self.title or "")
        return LlmResponse(content=self.reply)

    async def stream_request(self, request: LlmRequest):
        if self.reply:
            yield LlmStreamChunk(content=self.reply)

    async def validate_tools(self, tools):
        return []


def make_agent(llm_service, store):
    """Build an agent wired to the given fake store and LLM."""
    from vanna import Agent, AgentConfig
    from vanna.core.registry import ToolRegistry
    from vanna.integrations.local.agent_memory import DemoAgentMemory

    return Agent(
        llm_service=llm_service,
        tool_registry=ToolRegistry(),
        user_resolver=SimpleUserResolver(),
        agent_memory=DemoAgentMemory(max_items=1000),
        conversation_store=store,
        config=AgentConfig(),
    )


async def _run_agent(agent, message="Who is the top artist?", metadata=None):
    """Send one message through the agent, returning all components."""
    request_context = RequestContext(cookies={}, headers={}, metadata=metadata or {})
    components = []
    async for component in agent.send_message(request_context, message):
        components.append(component)
    return components


def test_message_rich_field_defaults_to_empty_list():
    msg = Message(role="assistant", content="hello")
    assert msg.rich == []


def test_message_rich_field_roundtrip_json():
    rich = [{"id": "r1", "type": "table", "data": {"columns": ["a"]}}]
    msg = Message(role="assistant", content="hello", rich=rich)
    dumped = msg.model_dump(mode="json")
    assert dumped["rich"] == rich
    reloaded = Message.model_validate(dumped)
    assert reloaded.rich == rich


@pytest.mark.asyncio
async def test_agent_persists_rich_components_on_assistant_message():
    store = FakeStore()
    agent = make_agent(FakeLlmService(reply="Iron Maiden sold the most."), store)

    components = await _run_agent(agent)
    assert components, "expected streamed components"

    convs = list(store._convs.values())
    assert len(convs) == 1
    assistant_msgs = [m for m in convs[0].messages if m.role == "assistant"]
    assert assistant_msgs, "expected an assistant message"

    rich = assistant_msgs[-1].rich
    assert rich, "expected rich components persisted on the assistant message"
    text_comps = [r for r in rich if r.get("type") == "text"]
    assert any(
        r.get("data", {}).get("content") == "Iron Maiden sold the most."
        for r in text_comps
    ), "expected the final text component to be persisted"