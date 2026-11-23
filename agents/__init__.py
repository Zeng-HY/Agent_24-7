"""Desktop assistants: one module each, one list in registry.py."""

from .base import Agent, AgentError, NotFound, UnknownAgent, Unsupported
from . import registry

__all__ = ["Agent", "AgentError", "NotFound", "UnknownAgent", "Unsupported", "registry"]
