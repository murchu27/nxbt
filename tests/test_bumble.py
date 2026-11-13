#   Python test originally created or extracted from Hannah's work (https://github.com/hannahbee91/nxbt).
#   Some modifications might have been made to adapt to my own project.

import asyncio
import sys
import pytest
from unittest.mock import MagicMock, patch

# Ensure dbus is mocked if not already by conftest
if "dbus" not in sys.modules:
    sys.modules["dbus"] = MagicMock()

from nxbt.backends import BumbleBackend


def _run_async_mock(coro):
    """Mimics BumbleBackend._run_async: await a coroutine and return result."""
    if asyncio.iscoroutine(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    # For mocked async methods (MagicMock), return directly
    return coro


class TestBumbleBackendAliases:
    """Verify ALIASES dict keys match ControllerTypes enum values."""

    def test_alias_keys_are_enum_values(self):
        aliases = BumbleBackend.ALIASES
        from nxbt.controller.controller import ControllerTypes

        assert ControllerTypes.JOYCON_L in aliases
        assert ControllerTypes.JOYCON_R in aliases
        assert ControllerTypes.PRO_CONTROLLER in aliases


def _bare_bumble_backend(run_async):
    backend = BumbleBackend.__new__(BumbleBackend)
    backend.logger = MagicMock()
    backend._device = MagicMock()
    backend._device.public_address = "AA:BB:CC:DD:EE:FF"
    backend._device.random_address = None
    backend._bridges = []
    backend._run_async = run_async
    # Avoid __del__ noise if GC collects during tests.
    backend._transport = None
    backend._loop = None
    backend._loop_thread = None
    return backend


class TestBumbleReconnectErrors:
    """reconnect() must not UnboundLocalError on unhandled HCI failures."""

    def test_unknown_hci_error_raises_oserror(self):
        from bumble.hci import HCI_Error, HCI_CONNECTION_TIMEOUT_ERROR

        def boom(coro):
            if hasattr(coro, "close"):
                coro.close()
            raise HCI_Error(HCI_CONNECTION_TIMEOUT_ERROR)

        backend = _bare_bumble_backend(boom)
        with pytest.raises(OSError, match="Unable to reconnect"):
            backend.reconnect("11:22:33:44:55:66")

    def test_page_timeout_raises_force_repair_oserror(self):
        from bumble.hci import HCI_Error, HCI_PAGE_TIMEOUT_ERROR

        def boom(coro):
            if hasattr(coro, "close"):
                coro.close()
            raise HCI_Error(HCI_PAGE_TIMEOUT_ERROR)

        backend = _bare_bumble_backend(boom)
        with pytest.raises(OSError, match="force to repair"):
            backend.reconnect("11:22:33:44:55:66")
