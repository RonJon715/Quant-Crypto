"""Abstract base class for all data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseProvider(ABC):
    """Every provider must implement ``fetch`` and ``is_available``.

    ``fetch`` is the single async entry-point that downstream code calls.
    ``is_available`` lets the orchestration layer skip providers whose
    prerequisites (API keys, network access, etc.) are not met.
    """

    @abstractmethod
    async def fetch(self, **kwargs: Any) -> list[Any]:
        """Return a list of normalised schema records."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return *True* when the provider can serve requests."""
