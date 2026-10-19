"""Placement in rF2 coordinates: rF2 = (x, y, -z) of the centreline, yaw a faces (-sin a, 0, -cos a)."""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from rf2_layout import MARKER, Lap, make_cam, relocate_aiw  # noqa: E402


def square_lap(tmp_path, side=100):
    # Anticlockwise square in OBJ coords (x east, z = -north), starting at the origin heading west (-x).
    pts = []
    for k in range(4 * side):
        s, e = divmod(k, side)
        x, n = [(-e, 0), (-side, -e), (-side + e, -side), (0, -side + e)][s]
        pts.append((k, x, 0.0, -n))
    csv = tmp_path / "c.csv"
    csv.write_text("dist_m,x,y_up,z\n" + "".join(f"{d},{x},{y},{z}\n" for d, x, y, z in pts))
    return Lap(csv)


def facing(yaw):
    return np.array([-math.sin(yaw), 0.0, -math.cos(yaw)])


def test_yaw_points_along_the_lap(tmp_path):
    lap = square_lap(tmp_path)
    p, a = lap.at(10)
    assert np.allclose(p, [-10, 0, 0])
    assert np.allclose(facing(a), [-1, 0, 0], atol=1e-6)  # heading west at the start
    _, a = lap.at(150)  # second side heads south: rF2 z (north) decreasing
    assert np.allclose(facing(a), [0, 0, -1], atol=1e-6)


def test_relocated_spots_sit_on_the_start_straight(tmp_path):
    lap = square_lap(tmp_path)
    tpl = "//hdr\n[Features]\nx=1\n[GRID]\nGridIndex=0\nPos=(9,9,9)\nOri=(0,0,0)\n[PITS]\nTeamIndex=0\n" \
          "[Waypoint]\nwp_pos=(5,5,5)\n"
    out = relocate_aiw(tpl, lap, grid=4, teams=2)
    assert out.startswith("//hdr\n" + MARKER)
    grid = out[out.index("[GRID]"):out.index("[PITS]")]
    pos = [tuple(map(float, l[5:-1].split(","))) for l in grid.splitlines() if l.startswith("Pos=")]
    # The lap reaches the line heading north up the last side (x = 0), so the grid is south of it.
    assert len(pos) == 4 and all(p[2] < 0 and abs(p[0]) <= 2.01 for p in pos)
    pits = out[out.index("[PITS]"):out.index("[Waypoint]")]
    gar = [l for l in pits.splitlines() if l.startswith("GarPos=(0,")]
    assert float(gar[0].split(",")[1]) < 0  # team 0's garage is past the line (west)
    assert out.rstrip().endswith("wp_pos=(5,5,5)")


def test_cameras_off_track_and_looking_at_it(tmp_path):
    lap = square_lap(tmp_path)
    tpl = ("TrackingCam=T\n{\n  Position=(0, 0, 0)\n  Orientation=(0, 0, 0)\n  ActivationLocation=(0, 0, 0)\n"
           "  ActivationRadius=(1)\n}\n")
    cam = make_cam(tpl, lap, count=4)
    blocks = cam.split("TrackingCam=")[1:]
    assert len(blocks) == 4
    for b in blocks:
        p = np.array([float(v) for v in b.split("Position=(")[1].split(")")[0].split(",")])
        t = np.array([float(v) for v in b.split("ActivationLocation=(")[1].split(")")[0].split(",")])
        yaw = float(b.split("Orientation=(")[1].split(",")[1])
        assert np.linalg.norm((p - t)[[0, 2]]) > 15
        look = (t - p) * [1, 0, 1]
        assert facing(yaw) @ (look / np.linalg.norm(look)) > 0.99
