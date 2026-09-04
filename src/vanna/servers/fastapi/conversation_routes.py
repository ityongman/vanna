"""FastAPI routes exposing the conversation store for the web UI."""

from fastapi import FastAPI, HTTPException, Query, Request

from .auth import resolve_user


def register_conversation_routes(app: FastAPI, agent) -> None:
    store = agent.conversation_store

    @app.get("/api/conversations")
    async def list_conversations(
        http_request: Request,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        user = await resolve_user(agent, http_request)
        conversations = await store.list_conversations(user, limit=limit, offset=offset)
        return [c.model_dump(mode="json") for c in conversations]

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str, http_request: Request):
        user = await resolve_user(agent, http_request)
        conversation = await store.get_conversation(conversation_id, user)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation.model_dump(mode="json")

    @app.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str, http_request: Request):
        user = await resolve_user(agent, http_request)
        deleted = await store.delete_conversation(conversation_id, user)
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"deleted": True}
