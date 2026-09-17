"""Entity-platform-owned runtime wrapper for DOEMS Prices P4."""

from __future__ import annotations

from .prices import DOEMSPricesManager


class DOEMSRegisteredPricesManager(DOEMSPricesManager):
    """Run Prices data logic without creating ad-hoc Home Assistant states.

    Alpha7/7.1 used the manager's legacy direct state publisher. Alpha7.2 moves
    ownership of public states to registered SensorEntity objects. The data
    manager still fetches, normalizes and notifies listeners, but it no longer
    publishes or removes public entity states itself.
    """

    def _publish_states(self) -> None:
        """Intentionally do nothing; SensorEntity owns public state output."""
        return None

    async def async_shutdown(self) -> None:
        """Stop runtime listeners without touching entity-platform states."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self.listeners.clear()
