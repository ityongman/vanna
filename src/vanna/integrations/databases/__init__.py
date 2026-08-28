"""SqlRunner integrations, split by database shape
(``relational/`` vs ``warehouse/``).
"""

from .factory import SUPPORTED_SCHEMES, create_sql_runner

__all__ = [
    "create_sql_runner",
    "SUPPORTED_SCHEMES",
]
