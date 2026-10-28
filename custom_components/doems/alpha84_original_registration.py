"""Non-actuating registration of the original Anker EMS Alpha84 controller.

Reuse the ALREADY LOADED coordinator and controller from the Anker
integration. Never construct a second execution controller, re-attach its
dependencies, or call any physical method through this registration.
"""
from __future__ import annotations

from typing import Any


class OriginalControllerUnavailable(ValueError):
    """The proven original controller and its dependencies are not verified."""


class OriginalAlpha84Registration:
    def __init__(self, hass: Any) -> None:
        self.hass = hass
        self.entry_id: str | None = None
        self.coordinator: Any = None
        self.controller: Any = None

    def clear(self) -> None:
        self.entry_id = None
        self.coordinator = None
        self.controller = None

    def register(self) -> dict[str, Any]:
        """Bind the unique existing coordinator and its own controller."""
        self.clear()
        entries = self.hass.data.get("anker_ems", {})
        if not isinstance(entries, dict) or len(entries) != 1:
            raise OriginalControllerUnavailable(
                "Expected exactly one loaded original Anker EMS coordinator"
            )
        entry_id, coordinator = next(iter(entries.items()))
        if not isinstance(entry_id, str) or not entry_id:
            raise OriginalControllerUnavailable("Original entry identifier invalid")
        controller = getattr(coordinator, "execution", None)
        if controller is None or getattr(controller, "_coordinator", None) is not coordinator:
            raise OriginalControllerUnavailable(
                "Original controller not attached to its original coordinator"
            )
        if getattr(controller, "entry_id", None) != entry_id:
            raise OriginalControllerUnavailable("Original controller entry mismatch")
        if not callable(getattr(controller, "evaluate_final_revalidation", None)):
            raise OriginalControllerUnavailable("Original final validation unavailable")
        for key in ("authority_fence", "physical_test", "plan_store",
                    "control_entity_ids", "async_refresh", "data"):
            if getattr(coordinator, key, None) is None:
                raise OriginalControllerUnavailable(
                    f"Original coordinator dependency missing: {key}"
                )
        if getattr(coordinator.physical_test, "_coordinator", None) is not coordinator:
            raise OriginalControllerUnavailable("Original physical test dependency mismatch")
        if getattr(coordinator, "authority_fence", None) is None:
            raise OriginalControllerUnavailable("Original authority fence absent")
        self.entry_id, self.coordinator, self.controller = entry_id, coordinator, controller
        return {"status": "registered_read_only",
                "entry_id": entry_id, "original_controller_attached": True,
                "physical_execution_enabled": False}

    def verified_controller(self) -> Any:
        entries = self.hass.data.get("anker_ems", {})
        if (self.controller is None or not isinstance(entries, dict)
                or entries.get(self.entry_id) is not self.coordinator
                or getattr(self.coordinator, "execution", None) is not self.controller
                or getattr(self.controller, "_coordinator", None) is not self.coordinator):
            self.clear()
            raise OriginalControllerUnavailable("Original controller no longer live")
        return self.controller
