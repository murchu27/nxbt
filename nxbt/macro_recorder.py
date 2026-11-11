"""Record direct-input packets as nxbt macro DSL text."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Optional


# Stable emission order (matches docs/Macros.md control table).
_BUTTONS = (
    "Y",
    "X",
    "B",
    "A",
    "JCL_SR",
    "JCL_SL",
    "R",
    "ZR",
    "MINUS",
    "PLUS",
    "R_STICK_PRESS",
    "L_STICK_PRESS",
    "HOME",
    "CAPTURE",
    "DPAD_DOWN",
    "DPAD_UP",
    "DPAD_RIGHT",
    "DPAD_LEFT",
    "JCR_SR",
    "JCR_SL",
    "L",
    "ZL",
)

# Gamepad axes jitter near center; quantize so long recordings stay compact.
_STICK_DEADZONE = 10
_STICK_STEP = 5


def default_macros_dir() -> Path:
    """Return ~/.nxbt/macros, respecting HOME (including under sudo -E)."""
    home = os.environ.get("HOME") or str(Path.home())
    return Path(home) / ".nxbt" / "macros"


def _sudo_owner() -> Optional[tuple[int, int]]:
    """Return (uid, gid) of the user who invoked sudo, if running as root."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None
    uid = os.environ.get("SUDO_UID")
    gid = os.environ.get("SUDO_GID")
    if uid is None or gid is None:
        return None
    try:
        return int(uid), int(gid)
    except ValueError:
        return None


def _chown_like_sudo_user(path: Path) -> None:
    owner = _sudo_owner()
    if owner is None:
        return
    try:
        os.chown(path, owner[0], owner[1])
    except OSError:
        pass


def _mkdir_owned(directory: Path) -> None:
    """Create directory parents and chown newly created dirs to the sudo user."""
    to_create: list[Path] = []
    current = directory
    while not current.exists():
        to_create.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    directory.mkdir(parents=True, exist_ok=True)
    for path in reversed(to_create):
        if path.exists():
            _chown_like_sudo_user(path)


def _clamp_axis(value: Any) -> int:
    try:
        axis = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(-100, min(100, axis))


def _quantize_axis(value: Any) -> int:
    """Clamp, apply deadzone, then round to nearest stick step."""
    axis = _clamp_axis(value)
    if abs(axis) < _STICK_DEADZONE:
        return 0
    stepped = int(round(axis / _STICK_STEP) * _STICK_STEP)
    return max(-100, min(100, stepped))


def _format_axis(value: int) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value):03d}"


def _stick_axes(stick: Mapping[str, Any], left: bool) -> tuple[int, int]:
    """Resolve stick X/Y from explicit values or keyboard direction flags."""
    x_value = _quantize_axis(stick.get("X_VALUE", 0))
    y_value = _quantize_axis(stick.get("Y_VALUE", 0))
    if left:
        left_flag, right_flag, up_flag, down_flag = (
            "LS_LEFT",
            "LS_RIGHT",
            "LS_UP",
            "LS_DOWN",
        )
    else:
        left_flag, right_flag, up_flag, down_flag = (
            "RS_LEFT",
            "RS_RIGHT",
            "RS_UP",
            "RS_DOWN",
        )

    # Prefer active keyboard direction flags (TUI); otherwise use X/Y values.
    if any(stick.get(flag) for flag in (left_flag, right_flag, up_flag, down_flag)):
        x_value = 0
        y_value = 0
        if stick.get(left_flag):
            x_value -= 100
        if stick.get(right_flag):
            x_value += 100
        if stick.get(up_flag):
            y_value += 100
        if stick.get(down_flag):
            y_value -= 100
        return _clamp_axis(x_value), _clamp_axis(y_value)

    return x_value, y_value


def packet_signature(packet: Mapping[str, Any]) -> tuple:
    """Return a hashable snapshot of active inputs for change detection."""
    buttons = tuple(name for name in _BUTTONS if _is_pressed(packet, name))
    left = packet.get("L_STICK") or {}
    right = packet.get("R_STICK") or {}
    lx, ly = _stick_axes(left, left=True)
    rx, ry = _stick_axes(right, left=False)
    sticks = (
        ("L_STICK", lx, ly),
        ("R_STICK", rx, ry),
    )
    return buttons, sticks


def _is_pressed(packet: Mapping[str, Any], name: str) -> bool:
    if name == "L_STICK_PRESS":
        stick = packet.get("L_STICK") or {}
        return bool(stick.get("PRESSED"))
    if name == "R_STICK_PRESS":
        stick = packet.get("R_STICK") or {}
        return bool(stick.get("PRESSED"))
    return bool(packet.get(name))


def format_macro_line(signature: tuple, duration: float, resolution: float = 0.01) -> str:
    """Convert a packet signature + hold time into one macro DSL line."""
    duration = max(resolution, round(duration / resolution) * resolution)
    # Trim trailing zeros without losing the required trailing "s"
    duration_text = f"{duration:.2f}".rstrip("0").rstrip(".")
    if not duration_text:
        duration_text = "0.01"
    duration_text = f"{duration_text}s"

    buttons, sticks = signature
    tokens = list(buttons)
    for stick_name, x_value, y_value in sticks:
        if x_value == 0 and y_value == 0:
            continue
        tokens.append(f"{stick_name}@{_format_axis(x_value)}{_format_axis(y_value)}")

    if not tokens:
        return duration_text
    return " ".join(tokens) + f" {duration_text}"


def default_macro_path(directory: Optional[Path] = None) -> Path:
    base = Path(directory) if directory is not None else default_macros_dir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = base / f"nxbt_macro_{stamp}.txt"
    if not path.exists():
        return path
    # Same-second collision: include microseconds.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return base / f"nxbt_macro_{stamp}.txt"


class MacroRecorder:
    """Sample direct-input packets and write compressed macro lines to a file."""

    def __init__(
        self,
        output_path: Optional[Path | str] = None,
        time_resolution: float = 0.01,
    ):
        self.output_path = Path(output_path) if output_path else None
        # Constructor path is only used for the first start() without an arg.
        self._use_configured_path = output_path is not None
        self.time_resolution = time_resolution
        self._recording = False
        self._last_signature: Optional[tuple] = None
        self._segment_start = 0.0
        self._line_count = 0
        self._file = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def line_count(self) -> int:
        return self._line_count

    def start(self, output_path: Optional[Path | str] = None) -> Path:
        if self._recording:
            raise RuntimeError("Recording is already in progress")

        if output_path is not None:
            path = Path(output_path)
        elif self._use_configured_path and self.output_path is not None:
            path = self.output_path
            self._use_configured_path = False
        else:
            path = default_macro_path()

        self.output_path = path
        _mkdir_owned(path.parent)

        self._file = path.open("w", encoding="utf-8")
        self._file.write("# nxbt recorded macro\n")
        self._file.write(f"# started {datetime.now().isoformat(timespec='seconds')}\n")
        self._file.flush()
        _chown_like_sudo_user(path)

        self._recording = True
        self._last_signature = None
        self._segment_start = perf_counter()
        self._line_count = 0
        return path

    def sample(self, packet: Mapping[str, Any], now: Optional[float] = None) -> None:
        if not self._recording:
            return

        current = now if now is not None else perf_counter()
        signature = packet_signature(packet)

        if self._last_signature is None:
            self._last_signature = signature
            self._segment_start = current
            return

        if signature == self._last_signature:
            return

        duration = current - self._segment_start
        self._write_line(format_macro_line(self._last_signature, duration, self.time_resolution))
        self._last_signature = signature
        self._segment_start = current

    def stop(self, now: Optional[float] = None) -> Path:
        if not self._recording:
            raise RuntimeError("Recording is not in progress")

        current = now if now is not None else perf_counter()
        if self._last_signature is not None:
            duration = current - self._segment_start
            self._write_line(
                format_macro_line(self._last_signature, duration, self.time_resolution)
            )

        assert self.output_path is not None
        assert self._file is not None
        self._file.write(f"# stopped {datetime.now().isoformat(timespec='seconds')}\n")
        self._file.write(f"# lines {self._line_count}\n")
        self._file.close()
        self._file = None
        self._recording = False
        self._last_signature = None
        return self.output_path

    def _write_line(self, line: str) -> None:
        assert self._file is not None
        self._file.write(line + "\n")
        self._file.flush()
        self._line_count += 1
