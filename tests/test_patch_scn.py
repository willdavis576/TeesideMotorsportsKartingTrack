"""patch_scn.py sets the right flags per object type and leaves everything else alone."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from patch_scn import patch  # noqa: E402

SCN = """// exported scene
Instance=road_e0_s1
{
  MeshFile=road_e0_s1.gmt CollTarget=False HATTarget=False
  ShadowReceiver=True
}
Instance=kerbL_w2_n0 { MeshFile=kerbL_w2_n0.gmt }
Instance=tyrewall_e1_n0 { MeshFile=tyrewall_e1_n0.gmt CollTarget=True HATTarget=True }
Instance=tyrewall_collision_e1_n0 { MeshFile=tyrewall_collision_e1_n0.gmt CollTarget=True }
Instance=grandstand { MeshFile=grandstand.gmt CollTarget=True }
"""


def block(text, name):
    start = text.index(f"Instance={name}")
    return text[start:text.index("}", start) + 1]


def test_flags_per_object_type():
    new, changes = patch(SCN)
    road = block(new, "road_e0_s1")
    assert "CollTarget=True" in road and "HATTarget=True" in road and "Response=VEHICLE,TERRAIN" in road
    assert "ShadowReceiver=True" in road and "MeshFile=road_e0_s1.gmt" in road  # untouched settings kept
    kerb = block(new, "kerbL_w2_n0")
    assert "CollTarget=True" in kerb and "HATTarget=True" in kerb
    tyres = block(new, "tyrewall_e1_n0 ")
    assert "CollTarget=False" in tyres and "HATTarget=False" in tyres
    wall = block(new, "tyrewall_collision_e1_n0")
    assert "Render=False" in wall and "CollTarget=True" in wall and "HATTarget=False" in wall
    assert block(new, "grandstand") == block(SCN, "grandstand")  # unknown scenery untouched
    assert changes == {"drivable": 2, "tyrewall": 1, "tyrewall_collision": 1}
    assert new.startswith("// exported scene")


def test_idempotent_and_backup(tmp_path):
    scn = tmp_path / "t.scn"
    scn.write_text(SCN)
    subprocess.run([sys.executable, str(ROOT / "tools/patch_scn.py"), str(scn)], check=True)
    once = scn.read_text()
    assert (tmp_path / "t.scn.bak").read_text() == SCN
    assert patch(once) == (once, {})
