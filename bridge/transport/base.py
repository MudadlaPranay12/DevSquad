"""Transport interface for DEV-SQUAD investigations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class TransportError(RuntimeError):
    """Raised when a transport cannot complete a real operation."""


class Transport(ABC):
    name: str

    @abstractmethod
    async def submit_case(self, case_id: str) -> Dict[str, Any]:
        """Start an investigation and return a real status result."""

    @abstractmethod
    async def get_events(self, case_id: str) -> List[Dict[str, Any]]:
        """Return live collaboration/status events for a case."""

    @abstractmethod
    async def get_verdict(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Return the current verdict, if one exists."""
