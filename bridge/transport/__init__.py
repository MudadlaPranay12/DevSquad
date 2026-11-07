"""Transport selection."""

from __future__ import annotations

import logging
from ..config import transport_mode
from .base import Transport, TransportError
from .local import LocalTransport
from .switch import SwitchTransport, switch_configured

LOGGER = logging.getLogger(__name__)


def get_transport() -> Transport:
    """Return a transport, falling back to LocalRunner when Switch is unavailable."""
    mode = transport_mode()
    if mode == "switch":
        if not switch_configured():
            LOGGER.info(
                "Switch transport unavailable or blocked; running via LocalRunner."
            )
            return LocalTransport()
        try:
            return SwitchTransport()
        except Exception:
            LOGGER.info(
                "Switch transport unavailable or blocked; running via LocalRunner."
            )
            return LocalTransport()
    return LocalTransport()


__all__ = [
    "Transport",
    "TransportError",
    "LocalTransport",
    "SwitchTransport",
    "get_transport",
    "switch_configured",
]
