"""
Deprecated: use vanna.integrations.llm.anthropic instead.

This module is a compatibility shim kept for 1-2 minor versions after the
integrations directory was reorganized by capability (llm / vector /
databases / visualization). It re-exports every public name of the new
package so that ``isinstance`` checks keep working (same class objects).
"""
import warnings

from vanna.integrations.llm.anthropic import *  # noqa: F401,F403
from vanna.integrations.llm.anthropic import __all__  # noqa: F401

warnings.warn(
    "vanna.integrations.anthropic is deprecated; "
    "import from vanna.integrations.llm.anthropic instead.",
    DeprecationWarning,
    stacklevel=2,
)
