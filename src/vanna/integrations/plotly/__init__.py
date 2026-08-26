"""
Deprecated: use vanna.integrations.visualization.plotly instead.

This module is a compatibility shim kept for 1-2 minor versions after the
integrations directory was reorganized by capability (llm / vector /
databases / visualization). It re-exports every public name of the new
package so that ``isinstance`` checks keep working (same class objects).
"""
import warnings

from vanna.integrations.visualization.plotly import *  # noqa: F401,F403
from vanna.integrations.visualization.plotly import __all__  # noqa: F401

warnings.warn(
    "vanna.integrations.plotly is deprecated; "
    "import from vanna.integrations.visualization.plotly instead.",
    DeprecationWarning,
    stacklevel=2,
)
