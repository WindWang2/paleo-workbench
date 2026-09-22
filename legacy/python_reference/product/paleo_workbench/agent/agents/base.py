"""Abstract Base Agent for Paleo AI GIS Swarm."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from paleo_workbench.agent.planner import TaskNode

_LOG = logging.getLogger("paleo_workbench.agent")


class BaseAgent(ABC):
    """Base class for specialized domain AI agents."""

    def __init__(self, name: str, role: str, description: str) -> None:
        self.name = name
        self.role = role
        self.description = description
        self._history: list[dict[str, Any]] = []

    def log(self, message: str, level: int = logging.INFO) -> None:
        _LOG.log(level, f"[{self.name.upper()}] {message}")
        self._history.append({"agent": self.name, "message": message, "level": level})

    @abstractmethod
    def run(self, task: TaskNode, context: dict[str, Any]) -> dict[str, Any]:
        """Execute the assigned task node using domain tools and return result dictionary."""
        raise NotImplementedError
