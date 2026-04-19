"""High-level Spectra Watermaker protocol operations — standalone, no HA imports."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .client import SpectraClient
from .models import SpectraUIState, WatermakerState

_LOGGER = logging.getLogger(__name__)

# Timeout waiting for a page transition after sending a command
_PAGE_WAIT_TIMEOUT = 5.0

# Command delay already enforced in client (1500ms), but page transitions
# may need additional wait
_SEQUENCE_SETTLE = 0.5


class SpectraProtocol:
    """High-level operations wrapping SpectraClient.

    Provides start/stop/flush sequences with page verification and rollback.
    """

    def __init__(self, client: SpectraClient) -> None:
        self._client = client
        self._current_ui: SpectraUIState = SpectraUIState()
        self._page_event: asyncio.Event = asyncio.Event()
        self._command_in_progress: bool = False
        self._command_lock: asyncio.Lock = asyncio.Lock()

    @property
    def current_ui(self) -> SpectraUIState:
        """Get the last known UI state."""
        return self._current_ui

    @property
    def command_in_progress(self) -> bool:
        """Whether a command sequence is currently executing."""
        return self._command_in_progress

    def update_ui_state(self, state: SpectraUIState) -> None:
        """Called by coordinator when a new UI message arrives."""
        self._current_ui = state
        self._page_event.set()

    async def _wait_for_page(
        self, expected_pages: set[str], timeout: float = _PAGE_WAIT_TIMEOUT
    ) -> bool:
        """Wait until UI state reaches one of the expected pages.

        Returns True if expected page was reached, False on timeout.
        """
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if self._current_ui.page in expected_pages:
                return True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            self._page_event.clear()
            try:
                await asyncio.wait_for(self._page_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return self._current_ui.page in expected_pages

    async def _wait_for_page_change(
        self, timeout: float = _PAGE_WAIT_TIMEOUT
    ) -> str:
        """Wait for any page change. Returns the new page."""
        current = self._current_ui.page
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if self._current_ui.page != current:
                return self._current_ui.page
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return self._current_ui.page
            self._page_event.clear()
            try:
                await asyncio.wait_for(self._page_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return self._current_ui.page

    def _find_button_by_label(self, label_text: str) -> str | None:
        """Find a button number by its label text (case-insensitive).

        Returns 'BUTTON0', 'BUTTON1', etc. or None if not found.
        """
        ui = self._current_ui
        label_lower = label_text.lower()
        for i in range(4):
            btn_label = getattr(ui, f"button{i}", "")
            if btn_label and label_lower in btn_label.lower():
                return f"BUTTON{i}"
        return None

    async def start(self, duration_hours: float) -> bool:
        """Execute the full start sequence.

        Returns True on success, False on failure.
        Sequence: dismiss screensaver -> START -> AUTORUN -> set hours -> set duration -> OK
        """
        async with self._command_lock:
            if self._command_in_progress:
                _LOGGER.warning("Command already in progress, rejecting start")
                return False
            self._command_in_progress = True

        try:
            return await self._execute_start(duration_hours)
        finally:
            self._command_in_progress = False

    async def _execute_start(self, duration_hours: float) -> bool:
        """Internal start sequence implementation."""
        page = self._current_ui.page

        # Step 1: Dismiss screensaver/prompt if on page 10
        if page == "10":
            _LOGGER.debug("Dismissing screensaver/prompt on page 10")
            await self._client.send_command("10", "BUTTON0")
            if not await self._wait_for_page({"4", "37", "39", "40", "48", "49"}):
                _LOGGER.warning("Failed to dismiss screensaver, stuck on page %s", self._current_ui.page)
                return False

        page = self._current_ui.page

        # Step 2: Press START from idle page
        if page in {"4", "39", "48", "49"}:
            # Find START button by label
            start_btn = self._find_button_by_label("START")
            if not start_btn:
                # Fallback: BUTTON1 on page 4, BUTTON0 on others
                start_btn = "BUTTON1" if page == "4" else "BUTTON0"
                _LOGGER.debug("START button not found by label, using fallback %s", start_btn)

            _LOGGER.debug("Pressing %s on page %s", start_btn, page)
            await self._client.send_command(page, start_btn)

            if not await self._wait_for_page({"37", "40", "29"}):
                _LOGGER.warning(
                    "Expected page 37/40/29 after START, got page %s",
                    self._current_ui.page,
                )
                await self._try_rollback()
                return False
        elif page not in {"37", "40", "29"}:
            _LOGGER.warning("Cannot start from page %s", page)
            return False

        page = self._current_ui.page

        # Step 3: Select AUTORUN on page 37/40
        if page in {"37", "40"}:
            # On Newport 1000, BUTTON0 is AUTORUN (only option)
            autorun_btn = self._find_button_by_label("AUTORUN")
            if not autorun_btn:
                autorun_btn = "BUTTON0"

            _LOGGER.debug("Selecting AUTORUN (%s) on page %s", autorun_btn, page)
            await self._client.send_command(page, autorun_btn)

            if not await self._wait_for_page({"29"}):
                _LOGGER.warning(
                    "Expected page 29 after AUTORUN, got page %s",
                    self._current_ui.page,
                )
                await self._try_rollback()
                return False

        # Step 4: On page 29 — select hours, set duration, press OK
        page = self._current_ui.page
        if page == "29":
            # Select "hours" mode (BUTTON2)
            _LOGGER.debug("Selecting hours mode on page 29")
            await self._client.send_command("29", "BUTTON2")
            await asyncio.sleep(_SEQUENCE_SETTLE)

            # Open input field (LABEL0) to go to page 12
            _LOGGER.debug("Opening duration input (LABEL0) on page 29")
            await self._client.send_command("29", "LABEL0")

            # Wait for page 12 (text input)
            if await self._wait_for_page({"12"}, timeout=5.0):
                # Send the duration value
                duration_str = f"{duration_hours:.1f}"
                _LOGGER.debug("Setting duration to %s hours on page 12", duration_str)
                await self._client.send_data("12", duration_str)

                # Wait for return to page 29
                if not await self._wait_for_page({"29"}, timeout=5.0):
                    _LOGGER.warning(
                        "Stuck on page %s after setting duration, sending CANCEL",
                        self._current_ui.page,
                    )
                    await self._client.send_command(self._current_ui.page, "CANCEL")
                    await asyncio.sleep(_SEQUENCE_SETTLE)
            else:
                _LOGGER.warning(
                    "Page 12 not reached for duration input (on page %s), "
                    "using Spectra's last value",
                    self._current_ui.page,
                )

            # Press OK (BUTTON3) on page 29
            page = self._current_ui.page
            if page == "29":
                _LOGGER.debug("Pressing OK (BUTTON3) on page 29")
                await self._client.send_command("29", "BUTTON3")

                # Wait for running page (via page 10 countdown)
                if not await self._wait_for_page(
                    {"10", "5", "6", "30", "31", "32"}, timeout=10.0
                ):
                    _LOGGER.warning(
                        "Start sequence did not reach running state, on page %s",
                        self._current_ui.page,
                    )
                    return False

                # If on page 10 (countdown), wait for actual running page
                if self._current_ui.page == "10":
                    await self._wait_for_page({"5", "6", "30", "31", "32"}, timeout=15.0)

                _LOGGER.info("Watermaker start sequence completed, on page %s", self._current_ui.page)
                return True

        _LOGGER.warning("Start sequence failed at unexpected page %s", self._current_ui.page)
        return False

    async def stop(self) -> bool:
        """Stop the watermaker. Works from running or flushing pages.

        Returns True if stop command was sent.
        """
        async with self._command_lock:
            if self._command_in_progress:
                _LOGGER.warning("Command already in progress, rejecting stop")
                return False
            self._command_in_progress = True

        try:
            page = self._current_ui.page
            if page in {"2", "5", "6", "30", "31", "32"}:
                _LOGGER.info("Sending STOP on page %s", page)
                await self._client.send_command(page, "BUTTON0")
                return True
            _LOGGER.warning("Cannot stop from page %s (not running/flushing)", page)
            return False
        finally:
            self._command_in_progress = False

    async def flush(self) -> bool:
        """Trigger manual freshwater flush from idle.

        Returns True if flush command was sent.
        """
        async with self._command_lock:
            if self._command_in_progress:
                _LOGGER.warning("Command already in progress, rejecting flush")
                return False
            self._command_in_progress = True

        try:
            page = self._current_ui.page

            # Dismiss screensaver if needed
            if page == "10":
                await self._client.send_command("10", "BUTTON0")
                if not await self._wait_for_page({"4", "39", "48", "49"}):
                    _LOGGER.warning("Cannot reach idle for flush, on page %s", self._current_ui.page)
                    return False
                page = self._current_ui.page

            if page in {"4", "39", "48", "49"}:
                # Find FLUSH button by label
                flush_btn = self._find_button_by_label("FLUSH")
                if not flush_btn:
                    flush_btn = "BUTTON0"  # Default on page 4

                _LOGGER.info("Sending FLUSH (%s) on page %s", flush_btn, page)
                await self._client.send_command(page, flush_btn)
                return True

            _LOGGER.warning("Cannot flush from page %s (not idle)", page)
            return False
        finally:
            self._command_in_progress = False

    async def dismiss_prompts(self) -> bool:
        """Auto-dismiss boot prompts and screensaver.

        Handles:
        - Page 10 POWER INTERRUPT -> BUTTON0
        - Page 10 AUTOSTORE -> BUTTON0
        - Pages 1/44/45 chemical prompts -> find "No" button
        - Page 101 -> wait

        Returns True if system reached idle.
        """
        max_attempts = 10
        for _ in range(max_attempts):
            page = self._current_ui.page
            label0 = self._current_ui.label0.lower()

            if page in {"4", "39", "48", "49"}:
                _LOGGER.debug("System is idle on page %s", page)
                return True

            if page == "101":
                _LOGGER.debug("System initializing (page 101), waiting...")
                await asyncio.sleep(2.0)
                continue

            if page == "10":
                if "power interrupt" in label0:
                    _LOGGER.info("Dismissing POWER INTERRUPT on page 10")
                    await self._client.send_command("10", "BUTTON0")
                elif "autostore" in label0:
                    _LOGGER.info("Dismissing AUTOSTORE screensaver on page 10")
                    await self._client.send_command("10", "BUTTON0")
                elif "starting" in label0:
                    # "System starting : 8" countdown — just wait
                    _LOGGER.debug("System starting countdown on page 10")
                    await asyncio.sleep(2.0)
                    continue
                else:
                    _LOGGER.info("Dismissing page 10 prompt: %s", self._current_ui.label0)
                    await self._client.send_command("10", "BUTTON0")

                await asyncio.sleep(2.0)
                continue

            if page in {"1", "44", "45"}:
                if "chemical" in label0 or "stored" in label0:
                    # Find the "No" button
                    no_btn = self._find_button_by_label("No")
                    if no_btn:
                        _LOGGER.info("Answering 'No' to chemical prompt (%s)", no_btn)
                        await self._client.send_command(page, no_btn)
                    else:
                        # Fallback: try BUTTON1 (typically "No" is second)
                        _LOGGER.info("Chemical prompt — 'No' not found, trying BUTTON1")
                        await self._client.send_command(page, "BUTTON1")
                else:
                    _LOGGER.info("Dismissing prompt page %s: %s", page, self._current_ui.label0)
                    await self._client.send_command(page, "BUTTON0")

                await asyncio.sleep(2.0)
                continue

            # Unknown page during boot — wait
            _LOGGER.debug("Waiting on unexpected page %s during boot", page)
            await asyncio.sleep(2.0)

        _LOGGER.warning(
            "Could not reach idle after %d prompt dismissal attempts (page %s)",
            max_attempts,
            self._current_ui.page,
        )
        return False

    async def toggle_destination(self) -> bool:
        """Toggle water destination (tank/overboard) while running.

        Returns True if toggle command was sent.
        """
        page = self._current_ui.page
        if page in {"5", "6", "30", "31", "32"}:
            _LOGGER.info("Toggling water destination on page %s", page)
            await self._client.send_command(page, "BUTTON3")
            return True
        _LOGGER.warning("Cannot toggle destination from page %s (not running)", page)
        return False

    def detect_state(self, data: Any = None) -> WatermakerState:
        """Determine watermaker state from UI page + sensor data.

        Port 9001 data (p_flow, feed_p) is ground truth for running.
        Port 9000 page provides details.
        """
        ui = self._current_ui

        # Cross-reference with port 9001 data if available
        if data and hasattr(data, "is_running") and data.is_running:
            return WatermakerState.RUNNING

        # Flushing pages
        if ui.is_flushing_page:
            return WatermakerState.FLUSHING

        # Check label0 for state hints
        label0 = ui.label0.upper()
        if "AUTORUN" in label0:
            return WatermakerState.RUNNING
        if "FLUSH" in label0:
            return WatermakerState.FLUSHING

        # Running pages (fallback if label check missed)
        if ui.is_running_page:
            return WatermakerState.RUNNING

        # Idle pages
        if ui.is_idle_page:
            return WatermakerState.IDLE

        # Startup/screensaver
        if ui.is_startup_page:
            label0_lower = ui.label0.lower()
            if "starting" in label0_lower:
                return WatermakerState.STARTING
            return WatermakerState.PROMPT

        # Prompt/warning pages
        if ui.is_prompt_page:
            return WatermakerState.PROMPT

        # Connection pending
        if ui.page == "102":
            return WatermakerState.BOOTING

        # Display updating
        if ui.page == "101":
            return WatermakerState.BOOTING

        # Settings/menu pages — system is idle but user is navigating
        if ui.page:
            return WatermakerState.IDLE

        return WatermakerState.OFF

    async def _try_rollback(self) -> None:
        """Attempt to navigate back to idle from an intermediate page."""
        page = self._current_ui.page
        _LOGGER.warning("Attempting rollback from page %s", page)

        # Try BUTTON4 (back) first
        if page in {"37", "40", "29", "12"}:
            await self._client.send_command(page, "BUTTON4")
            await asyncio.sleep(2.0)

        # Try CANCEL
        if self._current_ui.page not in {"4", "39", "48", "49"}:
            await self._client.send_command(self._current_ui.page, "CANCEL")
            await asyncio.sleep(2.0)

        _LOGGER.info("Rollback result: on page %s", self._current_ui.page)
