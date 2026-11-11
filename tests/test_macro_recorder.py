from pathlib import Path

from nxbt.macro_recorder import (
    MacroRecorder,
    default_macro_path,
    default_macros_dir,
    format_macro_line,
    packet_signature,
    _quantize_axis,
)
from nxbt.nxbt import DIRECT_INPUT_PACKET
import copy


def _idle_packet():
    return copy.deepcopy(DIRECT_INPUT_PACKET)


def test_packet_signature_idle():
    buttons, sticks = packet_signature(_idle_packet())
    assert buttons == ()
    assert sticks == (("L_STICK", 0, 0), ("R_STICK", 0, 0))


def test_packet_signature_buttons_and_stick_flags():
    packet = _idle_packet()
    packet["A"] = True
    packet["B"] = True
    packet["L_STICK"]["LS_RIGHT"] = True
    packet["L_STICK"]["LS_UP"] = True

    buttons, sticks = packet_signature(packet)
    assert buttons == ("B", "A")
    assert sticks[0] == ("L_STICK", 100, 100)


def test_packet_signature_stick_press():
    packet = _idle_packet()
    packet["L_STICK"]["PRESSED"] = True
    packet["R_STICK"]["PRESSED"] = True

    buttons, _sticks = packet_signature(packet)
    assert buttons == ("R_STICK_PRESS", "L_STICK_PRESS")


def test_quantize_axis_deadzone_and_step():
    assert _quantize_axis(0) == 0
    assert _quantize_axis(9) == 0
    assert _quantize_axis(-9) == 0
    assert _quantize_axis(10) == 10
    assert _quantize_axis(12) == 10
    assert _quantize_axis(13) == 15
    assert _quantize_axis(-47) == -45
    assert _quantize_axis(100) == 100


def test_packet_signature_quantizes_analog_values():
    packet = _idle_packet()
    packet["L_STICK"]["X_VALUE"] = 8  # inside deadzone
    packet["L_STICK"]["Y_VALUE"] = 52  # rounds to 50
    packet["R_STICK"]["X_VALUE"] = -3
    packet["R_STICK"]["Y_VALUE"] = -88

    _buttons, sticks = packet_signature(packet)
    assert sticks == (("L_STICK", 0, 50), ("R_STICK", 0, -90))


def test_format_macro_line_idle_and_inputs():
    idle = packet_signature(_idle_packet())
    assert format_macro_line(idle, 1.234) == "1.23s"

    packet = _idle_packet()
    packet["A"] = True
    packet["L_STICK"]["X_VALUE"] = -50
    packet["L_STICK"]["Y_VALUE"] = 0
    line = format_macro_line(packet_signature(packet), 0.1)
    assert line == "A L_STICK@-050+000 0.1s"


def test_default_macro_path_uses_nxbt_macros_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_macros_dir() == tmp_path / ".nxbt" / "macros"
    path = default_macro_path()
    assert path.parent == tmp_path / ".nxbt" / "macros"
    assert path.name.startswith("nxbt_macro_")
    assert path.suffix == ".txt"


def test_recorder_writes_compressed_macro(tmp_path: Path):
    path = tmp_path / "demo.txt"
    recorder = MacroRecorder(output_path=path, time_resolution=0.01)

    t0 = 1000.0
    recorder.start()
    # Force deterministic segment timing via sample(now=...)
    recorder._segment_start = t0
    recorder._last_signature = None

    idle = _idle_packet()
    press = _idle_packet()
    press["A"] = True

    recorder.sample(idle, now=t0)
    recorder.sample(press, now=t0 + 0.5)
    recorder.sample(idle, now=t0 + 0.7)
    out = recorder.stop(now=t0 + 1.0)

    text = out.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    assert lines == ["0.5s", "A 0.2s", "0.3s"]
    assert not recorder.is_recording


def test_recorder_mints_new_path_on_subsequent_start(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    recorder = MacroRecorder(time_resolution=0.01)

    first = recorder.start()
    recorder.stop()
    second = recorder.start()
    recorder.stop()

    assert first != second
    assert first.exists()
    assert second.exists()
    assert first.parent == tmp_path / ".nxbt" / "macros"
    assert second.parent == first.parent


def test_chown_like_sudo_user(monkeypatch, tmp_path: Path):
    from nxbt import macro_recorder as mr

    calls = []

    monkeypatch.setattr(mr.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("SUDO_GID", "1000")
    monkeypatch.setattr(
        mr.os, "chown", lambda path, uid, gid: calls.append((str(path), uid, gid))
    )

    target = tmp_path / "owned.txt"
    target.write_text("x", encoding="utf-8")
    mr._chown_like_sudo_user(target)
    assert calls == [(str(target), 1000, 1000)]


def test_mkdir_owned_chowns_created_dirs(monkeypatch, tmp_path: Path):
    from nxbt import macro_recorder as mr

    calls = []
    monkeypatch.setattr(mr.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("SUDO_GID", "1001")
    monkeypatch.setattr(
        mr.os, "chown", lambda path, uid, gid: calls.append((Path(path), uid, gid))
    )

    macros = tmp_path / ".nxbt" / "macros"
    mr._mkdir_owned(macros)
    assert macros.is_dir()
    owned = {path.name for path, uid, gid in calls}
    assert owned == {".nxbt", "macros"}
    assert all(uid == 1000 and gid == 1001 for _, uid, gid in calls)
