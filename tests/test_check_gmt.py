"""check_gmt.py reads a GMT's bounding box and flags a scale mismatch with the OBJ."""
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def fake_gmt(path, lo, hi):
    # Real GMTs start with 8 bytes, then the 8 corners of the bounding box as float32 x, y, z.
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])],
                       dtype="<f4")
    path.write_bytes(b"\0" * 8 + corners.tobytes() + b"\0" * 64 + b"ROAD_ASPHALT.DDS\0")


def run(tmp_path, scale):
    obj = tmp_path / "t.obj"
    obj.write_text("v 0 0 0\nv 10 1 0\nv 10 1 -20\nv 0 0 -20\no road_e0_n0\nf 1 2 3 4\n")
    gdir = tmp_path / "GMT"
    gdir.mkdir()
    # 3DSimED output: z flipped, multiplied by `scale`
    fake_gmt(gdir / "road_e0_n0.gmt", np.array([0, 0, 0]) * scale, np.array([10, 1, 20]) * scale)
    return subprocess.run([sys.executable, str(ROOT / "tools/check_gmt.py"), str(gdir), "--obj", str(obj)],
                          capture_output=True, text=True)


def test_detects_100x(tmp_path):
    res = run(tmp_path, 100)
    assert res.returncode == 1
    assert "Scale GMT/OBJ: 100" in res.stdout and "Scale = 0.01" in res.stdout
    assert "(+x, +y, -z)" in res.stdout
    assert "ROAD_ASPHALT.DDS (1)" in res.stdout


def test_ok_in_metres(tmp_path):
    res = run(tmp_path, 1)
    assert res.returncode == 0 and "OK: sizes match" in res.stdout
