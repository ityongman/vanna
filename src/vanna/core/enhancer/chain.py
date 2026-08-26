"""
Composite LLM context enhancer that chains multiple enhancers.

Enables compositions such as
``LlmContextEnhancerChain([DefaultLlmContextEnhancer(...), AutoLinkSchemaEnhancer(...)])``:
the system prompt flows through each enhancer in order.
"""

from typing import TYPE_CHECKING, List

from .base import LlmContextEnhancer

if TYPE_CHECKING:
    from ..user.models import User
    from ..llm.models import LlmMessage


class LlmContextEnhancerChain(LlmContextEnhancer):
    """Applies multiple enhancers sequentially."""

    def __init__(self, enhancers: List[LlmContextEnhancer]):
        """Initialize the chain.

        Args:
            enhancers: Enhancers applied in order. ``None`` entries are
                skipped so callers can compose optional enhancers easily.
        """
        self.enhancers = [e for e in enhancers if e is not None]

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: "User"
    ) -> str:
        """Run the system prompt through every enhancer in order."""
        for enhancer in self.enhancers:
            system_prompt = await enhancer.enhance_system_prompt(
                system_prompt, user_message, user
            )
        return system_prompt

    async def enhance_user_messages(
        self, messages: list["LlmMessage"], user: "User"
    ) -> list["LlmMessage"]:
        """Run the messages through every enhancer in order."""
        for enhancer in self.enhancers:
            messages = await enhancer.enhance_user_messages(messages, user)
        return messages
