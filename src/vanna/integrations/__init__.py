"""
Integrations module.

This package contains concrete implementations of core abstractions and
capabilities, organized by capability:

- ``llm/``: LlmService implementations (anthropic, openai, ollama, google, ...)
- ``vector/``: AgentMemory / SchemaVectorStore backends (faiss, chroma, ...)
- ``databases/relational/``: relational & embedded SqlRunner implementations
- ``databases/warehouse/``: warehouse / OLAP engine SqlRunner implementations
- ``visualization/``: ChartGenerator implementations
- ``local/``: local built-in implementations (storage, file system, audit, ...)
- ``premium/``: Vanna cloud services

Old flat paths (e.g. ``vanna.integrations.anthropic``) are kept as
re-export shims that emit DeprecationWarning.
"""

from .databases.relational.sqlite import SqliteRunner
from .llm.mock import MockLlmService
from .local import MemoryConversationStore
from .visualization.plotly import PlotlyChartGenerator

__all__ = [
    "MockLlmService",
    "MemoryConversationStore",
    "SqliteRunner",
    "PlotlyChartGenerator",
]
