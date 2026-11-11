# AGENTS.md — nxbt

Python library/CLI that emulates Nintendo Switch controllers (Joy-Con L/R, Pro Controller) over Bluetooth so a PC can control a Switch via **web UI**, **TUI**, **macros**, or the **Python API**.

This tree is a maintained fork of Brikwerk’s original project. Default Bluetooth stack is **Bumble** (not BlueZ). Packaging uses **uv** + `pyproject.toml`; binaries are built with **Nuitka**.

## Architecture (read this first)

```
CLI / TUI / Web  →  Nxbt (multiprocessing API in nxbt/nxbt.py)
                         →  _ControllerManager
                         →  ControllerServer process (nxbt/controller/server.py)
                              → Backend (Bumble | BlueZ)
                              → ControllerProtocol + InputParser
                              → HID L2CAP (~50-byte reports @ ~120–132 Hz)
```

| Path | Role |
|------|------|
| `nxbt/nxbt.py` | Public API: create/remove controllers, macros, direct input, adapters |
| `nxbt/cli.py` | Entry point (`nxbt` / `python -m nxbt`) |
| `nxbt/tui.py` | Blessed keyboard TUI |
| `nxbt/web/` | Starlette + Socket.IO webapp (includes gamepad + macro recording UI) |
| `nxbt/macro_recorder.py` | Packet → macro DSL recorder (used by webapp) |
| `nxbt/backends/` | `Backend` ABC; `bumble.py` (default); `bluez.py` (Linux); `internal/` helpers |
| `nxbt/controller/` | Server loop, protocol replies, input/macros, SDP |
| `nxbt/setcap.py` | Linux file/process capability helpers |
| `tests/` | pytest (mocked Bluetooth; no live Switch required) |
| `scripts/` | **Unmaintained** reference only (`scripts/README.txt`) |
| `docker/` | Nuitka onefile images: `gnu`, `musl`, `msys2` |
| `docs/` | Macros, sticks, pairing notes; treat Win/macOS VM doc as partly legacy |

## Public API surface

From `nxbt/__init__.py`: `Nxbt`, `Buttons`, `Sticks`, `JOYCON_L` / `JOYCON_R` / `PRO_CONTROLLER`, plus controller/protocol/backend types.

Important `Nxbt` methods: `create_controller`, `remove_controller`, `wait_for_connection`, `macro` / `press_buttons` / `tilt_stick`, `set_controller_input` / `create_input_packet`, `get_available_adapters`, `get_switch_addresses`, `state`.

**Pass a backend class, not an instance**, into `Nxbt(backend=...)` (pickling across processes).

## CLI commands

`webapp`, `demo`, `macro`, `tui`, `remote_tui`, `addresses`, `test`

Common flags: `-b/--backend` (`bumble` default), `-r/--reconnect`, `-a/--address`, `-d/--debug`.

## Bluetooth backends

| Backend | Transport | OS | Caps |
|---------|-----------|----|------|
| Bumble HCI socket (`hci-socket:N`) | Raw HCI user channel | Linux | `cap_net_admin` |
| Bumble USB (`usb:N`) | libusb | Linux / Windows | usually none |
| BlueZ | D-Bus + native L2CAP | Linux only | `cap_net_admin` + `cap_net_bind_service`; may restart `bluetoothd --noplugin=*` |

Prefer HCI socket when available (avoids fighting system Bluetooth). Windows path is Bumble USB (WinUSB/Zadig), not BlueZ.

Adapter auto-pick (`get_available_adapters`): prefers `hci-socket:` as a normal user; prefers `usb:` when root (can detach kernel `btusb`). Capability checks in `setcap.py` consider file caps, process/ambient caps, and `geteuid() == 0`.

## Macros

DSL documented in `docs/Macros.md`; parsed in `nxbt/controller/input.py`.

- Buttons + duration: `A B 0.1s`
- Wait: `1s`
- Sticks: `L_STICK@+000+127` / `R_STICK@...` (3-digit axes)
- `LOOP N` with tab/4-space indent; `#` comments

**Recording (webapp):** Record/Stop in the web UI samples live keyboard/gamepad `input` packets via `MacroRecorder`, writing timestamped files under `~/.nxbt/macros/` (respects `HOME`; under `sudo`, chowns to `SUDO_UID`/`SUDO_GID`). Stick axes are deadzoned/quantized to keep long takes compact. Replay from CLI: `nxbt macro -c ~/.nxbt/macros/<file>.txt` (often with `-r`).

## Dev workflow

```bash
uv sync --group dev          # Python >=3.10,<3.15
uv run nxbt --help
uv run pytest                # testpaths = tests
# lint: ruff / pylint are in dependency-groups.dev; no Makefile lint target
make install-deps && make    # Nuitka onefile → release/nxbt[.exe]
```

`pyproject.toml` default uv index is a Tsinghua mirror — expect that in lock/CI/Docker.

## Docs priority (token hygiene)

1. **This file** + `README.md` (fork status, backends, permissions)
2. `README.old.md` — fuller original user/API guide
3. `docs/Macros.md`, `docs/Miscellaneous Notes.md` when touching input/pairing
4. Avoid loading whole: `docs/Example Pairing Session.md`, `docs/Analog Stick Input.md` (large RE dumps), `nxbt/web/static/js/socket.io.js(.map)`, `uv.lock`

## Do not casually edit

- Vendor Socket.IO: `nxbt/web/static/js/socket.io.js*` — app JS is `main.js`
- `scripts/` — reference only
- `SWITCH_CONTROLLER_SDP` / SPI flash tables in protocol — pairing breaks easily
- Generated/runtime (gitignored): certs, `secrets.txt`, `release/`

## Known gaps / fork roadmap (from README)

Done: cleanup, uv/pyproject, Bumble rewrite, preliminary Windows USB, webapp macro recording.  
Open: broader webapp behavior fixes, TUI macro recording, pywebview native GUI, Android support.

## Agent gotchas

- Controllers run in **separate processes**; shared state is a manager dict.
- Python 3.14 often defaults to `forkserver`: do **not** pass `Nxbt` or nested functions into `multiprocessing.Process`. TUI direct-input uses a daemon **thread** (`_direct_input_worker` in `tui.py`).
- TUI input: Wayland and root/sudo cannot rely on `pynput`; `InputTUI` forces Blessed `term.inkey` (`remote_input_loop`) in those environments.
- Tests mock dbus/BlueZ; `tests/test_bluez.py` may hardcode an absolute path — fix to repo-relative if touching it.
- No pytest/lint GitHub Actions; CI is Docker/Nuitka image build + cache clear.
- Webapp is less stable than CLI/API (README TODO), but gamepad passthrough + recording are usable.
- First pair needs Switch **Change Grip/Order**; reconnect uses saved address (`-r` / `-a`).
- Bumble USB may unbind `btusb`; rebind via sysfs or use HCI socket as a non-root user when possible.
- Runtime macros dir `~/.nxbt/macros/` is user data (not in-repo).
