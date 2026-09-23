"""Chat-driven agent loop for the mc-agent bridge."""

from .config import LoopConfig
from .loop import AgentLoop

__version__ = "0.1.0"

__all__ = ["AgentLoop", "LoopConfig", "__version__"]
