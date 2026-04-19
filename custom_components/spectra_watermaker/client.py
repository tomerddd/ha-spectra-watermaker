"""WebSocket client for Spectra Watermaker — standalone, no HA imports."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import websockets
from websockets.exceptions import (
    ConnectionClosed,
    InvalidHandshake,
    WebSocketException,
)

from .models import SpectraData, SpectraUIState

_LOGGER = logging.getLogger(__name__)

# Reconnection backoff
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0
_BACKOFF_FACTOR = 2.0

# Heartbeat: if no port 9001 message for this many seconds, reconnect
_HEARTBEAT_TIMEOUT = 5.0

# Subprotocol
_SUBPROTOCOL = "dumb-increment-protocol"


def _parse_numeric(value: str) -> float:
    """Parse numeric prefix from a string like '47.95 gph' -> 47.95."""
    try:
        return float(value.split()[0])
    except (ValueError, IndexError, AttributeError):
        return 0.0


def _parse_int(value: str) -> int:
    """Parse integer from string, defaulting to 0."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _parse_spectra_data(raw: dict[str, Any]) -> SpectraData:
    """Parse a port 9001 JSON message into SpectraData."""
    return SpectraData(
        device=raw.get("device", ""),
        product_flow_gph=_parse_numeric(raw.get("p_flow", "0")),
        feed_flow_gph=_parse_numeric(raw.get("f_flow", "0")),
        boost_pressure_psi=_parse_numeric(raw.get("boost_p", "0")),
        feed_pressure_psi=_parse_numeric(raw.get("feed_p", "0")),
        product_tds_ppm=_parse_numeric(raw.get("sal_1", "0")),
        feed_tds_ppm=_parse_numeric(raw.get("sal_2", "0")),
        water_temp_f=_parse_numeric(raw.get("temp_1", "32")),
        water_temp2_f=_parse_numeric(raw.get("temp_2", "32")),
        battery_voltage=_parse_numeric(raw.get("bat_v", "0")),
        reg_5v=_parse_numeric(raw.get("reg_5v", "0")),
        tank_level_1=_parse_numeric(raw.get("tank_lvl_1", "0")),
        tank_level_2=_parse_numeric(raw.get("tank_lvl_2", "0")),
        power=_parse_int(raw.get("power", "0")),
        lock=_parse_int(raw.get("lock", "0")),
    )


def _parse_ui_state(raw: dict[str, Any]) -> SpectraUIState:
    """Parse a port 9000 JSON message into SpectraUIState."""
    return SpectraUIState(
        page=raw.get("page", ""),
        label0=raw.get("label0", ""),
        label1=raw.get("label1", ""),
        label2=raw.get("label2", ""),
        label3=raw.get("label3", ""),
        label4=raw.get("label4", ""),
        label5=raw.get("label5", ""),
        label6=raw.get("label6", ""),
        label7=raw.get("label7", ""),
        label8=raw.get("label8", ""),
        label9=raw.get("label9", ""),
        label10=raw.get("label10", ""),
        label11=raw.get("label11", ""),
        button0=raw.get("button0", ""),
        button1=raw.get("button1", ""),
        button2=raw.get("button2", ""),
        button3=raw.get("button3", ""),
        gauge0=raw.get("gauge0", ""),
        gauge0_label=raw.get("gauge0_label", ""),
        gauge0_mid=raw.get("gauge0_mid", ""),
        gauge1=raw.get("gauge1", ""),
        gauge1_label=raw.get("gauge1_label", ""),
        gauge2=raw.get("gauge2", ""),
        gauge2_label=raw.get("gauge2_label", ""),
        toggle_button=raw.get("toggle_button", ""),
        toggle_tank=raw.get("toggle_tank", ""),
        toggle_level=raw.get("toggle_level", ""),
        nav_hide=raw.get("nav_hide", ""),
        alarm=raw.get("alarm", ""),
        tank=raw.get("tank", ""),
        logout_button=raw.get("logout_button", ""),
    )


class SpectraClient:
    """Manages WebSocket connections to both Spectra ports.

    This class is standalone (no Home Assistant imports) for future PyPI extraction.
    """

    def __init__(
        self,
        host: str,
        data_port: int = 9001,
        ui_port: int = 9000,
        on_data: Callable[[SpectraData], None] | None = None,
        on_ui_state: Callable[[SpectraUIState], None] | None = None,
        on_data_connected: Callable[[bool], None] | None = None,
        on_ui_connected: Callable[[bool], None] | None = None,
    ) -> None:
        self._host = host
        self._data_port = data_port
        self._ui_port = ui_port
        self._on_data = on_data
        self._on_ui_state = on_ui_state
        self._on_data_connected = on_data_connected
        self._on_ui_connected = on_ui_connected

        self._ws_data: websockets.WebSocketClientProtocol | None = None
        self._ws_ui: websockets.WebSocketClientProtocol | None = None

        self._data_task: asyncio.Task[None] | None = None
        self._ui_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

        self._last_data_time: float = 0.0
        self._data_connected: bool = False
        self._ui_connected: bool = False
        self._running: bool = False

        self._command_lock = asyncio.Lock()
        self._last_command_time: float = 0.0

    @property
    def data_connected(self) -> bool:
        """Whether port 9001 WebSocket is connected."""
        return self._data_connected

    @property
    def ui_connected(self) -> bool:
        """Whether port 9000 WebSocket is connected."""
        return self._ui_connected

    @property
    def connected(self) -> bool:
        """Whether at least one WebSocket is connected."""
        return self._data_connected or self._ui_connected

    async def connect(self) -> None:
        """Start WebSocket connections to both ports."""
        if self._running:
            return
        self._running = True
        self._data_task = asyncio.create_task(
            self._run_connection("data", self._data_port, self._handle_data_message),
            name="spectra_data_ws",
        )
        self._ui_task = asyncio.create_task(
            self._run_connection("ui", self._ui_port, self._handle_ui_message),
            name="spectra_ui_ws",
        )
        self._heartbeat_task = asyncio.create_task(
            self._run_heartbeat(),
            name="spectra_heartbeat",
        )

    async def disconnect(self) -> None:
        """Close all WebSocket connections."""
        self._running = False
        for task in (self._data_task, self._ui_task, self._heartbeat_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        for ws in (self._ws_data, self._ws_ui):
            if ws:
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001
                    pass

        self._ws_data = None
        self._ws_ui = None
        self._data_task = None
        self._ui_task = None
        self._heartbeat_task = None

        self._set_data_connected(False)
        self._set_ui_connected(False)

    async def send_command(self, page: str, cmd: str) -> None:
        """Send a command on port 9000. Enforces 1500ms spacing."""
        async with self._command_lock:
            now = time.monotonic()
            elapsed = now - self._last_command_time
            delay_needed = 1.5 - elapsed
            if delay_needed > 0:
                await asyncio.sleep(delay_needed)

            if not self._ws_ui or not self._ui_connected:
                _LOGGER.warning("Cannot send command — UI WebSocket not connected")
                return

            msg = json.dumps({"page": page, "cmd": cmd})
            _LOGGER.debug("Sending command: %s", msg)
            try:
                await self._ws_ui.send(msg)
            except WebSocketException as exc:
                _LOGGER.warning("Failed to send command: %s", exc)
            finally:
                self._last_command_time = time.monotonic()

    async def send_data(self, page: str, data: str) -> None:
        """Send data input on port 9000 (e.g., set run duration). Enforces 1500ms spacing."""
        async with self._command_lock:
            now = time.monotonic()
            elapsed = now - self._last_command_time
            delay_needed = 1.5 - elapsed
            if delay_needed > 0:
                await asyncio.sleep(delay_needed)

            if not self._ws_ui or not self._ui_connected:
                _LOGGER.warning("Cannot send data — UI WebSocket not connected")
                return

            msg = json.dumps({"page": page, "data": data})
            _LOGGER.debug("Sending data: %s", msg)
            try:
                await self._ws_ui.send(msg)
            except WebSocketException as exc:
                _LOGGER.warning("Failed to send data: %s", exc)
            finally:
                self._last_command_time = time.monotonic()

    async def _run_connection(
        self,
        name: str,
        port: int,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        """Maintain a WebSocket connection with exponential backoff."""
        backoff = _BACKOFF_BASE
        while self._running:
            uri = f"ws://{self._host}:{port}"
            try:
                _LOGGER.debug("Connecting to %s (%s)", uri, name)
                ws = await websockets.connect(
                    uri,
                    subprotocols=[_SUBPROTOCOL],
                    open_timeout=10,
                    ping_interval=None,  # Spectra doesn't use WS ping/pong
                )

                # Store reference
                if name == "data":
                    self._ws_data = ws
                    self._set_data_connected(True)
                else:
                    self._ws_ui = ws
                    self._set_ui_connected(True)

                # Reset backoff on successful connect
                backoff = _BACKOFF_BASE
                _LOGGER.info("Connected to Spectra %s stream at %s", name, uri)

                async for raw_msg in ws:
                    if not self._running:
                        break
                    try:
                        data = json.loads(raw_msg)
                        handler(data)
                    except json.JSONDecodeError:
                        _LOGGER.warning("Invalid JSON from %s: %s", name, raw_msg[:200])
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("Error handling %s message", name)

            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, InvalidHandshake, OSError, WebSocketException) as exc:
                _LOGGER.debug("Connection %s lost: %s", name, exc)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error on %s connection", name)
            finally:
                if name == "data":
                    self._ws_data = None
                    self._set_data_connected(False)
                else:
                    self._ws_ui = None
                    self._set_ui_connected(False)

            if not self._running:
                break

            _LOGGER.debug("Reconnecting %s in %.1fs", name, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)

    def _handle_data_message(self, raw: dict[str, Any]) -> None:
        """Handle a port 9001 data message."""
        self._last_data_time = time.monotonic()
        parsed = _parse_spectra_data(raw)
        if self._on_data:
            self._on_data(parsed)

    def _handle_ui_message(self, raw: dict[str, Any]) -> None:
        """Handle a port 9000 UI message."""
        parsed = _parse_ui_state(raw)
        if self._on_ui_state:
            self._on_ui_state(parsed)

    async def _run_heartbeat(self) -> None:
        """Monitor port 9001 for staleness; force reconnect if no data for 5s."""
        while self._running:
            await asyncio.sleep(2.0)
            if not self._running:
                break
            if self._data_connected and self._last_data_time > 0:
                elapsed = time.monotonic() - self._last_data_time
                if elapsed > _HEARTBEAT_TIMEOUT:
                    _LOGGER.warning(
                        "No data from port 9001 for %.1fs — forcing reconnect", elapsed
                    )
                    self._set_data_connected(False)
                    # Close the stale connection to trigger reconnect
                    ws = self._ws_data
                    if ws:
                        try:
                            await ws.close()
                        except Exception:  # noqa: BLE001
                            pass

    def _set_data_connected(self, connected: bool) -> None:
        """Update data connection state and notify."""
        if self._data_connected != connected:
            self._data_connected = connected
            if self._on_data_connected:
                self._on_data_connected(connected)

    def _set_ui_connected(self, connected: bool) -> None:
        """Update UI connection state and notify."""
        if self._ui_connected != connected:
            self._ui_connected = connected
            if self._on_ui_connected:
                self._on_ui_connected(connected)
