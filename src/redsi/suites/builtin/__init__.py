"""Built-in suites. Importing this package registers them."""

from redsi.suites.builtin import (
    agent,
    factuality,
    rag,
    reasoning,
    reliability,
    robustness,
    security,
)

__all__ = ["agent", "factuality", "rag", "reasoning", "reliability", "robustness", "security"]
