"""make_track_folder.py lays out a ModDev track folder like the sample track."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPORT_SCN = """
CUBEASF
View=mainview
{ Clear = False }
Instance=road_e0_n0
{
	VisGroups=(32)ReflectPlane=(0.000, 1.000, 0.000, 0.000)
	MeshFile=road_e0_n0.gmt CollTarget=False HATTarget=False
}
""" + "".join(f"Instance={g}\n{{\n\tMeshFile={g}.gmt CollTarget=False HATTarget=False\n}}\n"
              for g in ("xfinish", "xsector1", "xsector2", "xpitin", "xpitout"))


def test_folder_layout(tmp_path):
    gmt = tmp_path / "GMT"
    gmt.mkdir()
    (gmt / "_output.scn").write_text(EXPORT_SCN)
    for name in ("road_e0_n0", "xfinish", "xsector1", "xsector2", "xpitin", "xpitout"):
        (gmt / f"{name}.gmt").write_bytes(b"gmt")
    tex = tmp_path / "textures"
    tex.mkdir()
    (tex / "road_asphalt.dds").write_bytes(b"dds")
    ref = tmp_path / "ref"
    (ref / "Assets" / "GMT").mkdir(parents=True)
    (ref / "Assets" / "Maps").mkdir(parents=True)
    (ref / "Sample.tdf").write_text("[FEEDBACK]\nMaterials=road\n")
    (ref / "Assets" / "GMT" / "skyboxi.gmt").write_bytes(b"sky")
    (ref / "Assets" / "Maps" / "BKA.DDS").write_bytes(b"skytex")
    (ref / "Layout").mkdir()
    (ref / "Layout" / "Sample.AIW").write_text("[Features]\n")
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"origin_bng": [452553.36, 520591.23], "origin_alt_m": 8.55, "length_m": 1629.0}))
    out = tmp_path / "Locations"

    subprocess.run([sys.executable, str(ROOT / "tools/make_track_folder.py"), "--gmt", str(gmt),
                    "--textures", str(tex), "--summary", str(summary), "--reference", str(ref),
                    "--out", str(out)], check=True)

    root = out / "TeessideKarting"
    assert (root / "TeessideKarting.tdf").read_text().startswith("[FEEDBACK]")
    assert (root / "Assets" / "GMT" / "SkyBoxi.gmt").exists()
    assert (root / "Assets" / "GMT" / "road_e0_n0.gmt").exists()
    assert (root / "Assets" / "Maps" / "road_asphalt.dds").exists()
    assert (root / "Assets" / "Maps" / "BKA.DDS").exists()

    scn = (root / "Teesside_Karting" / "Teesside_Karting.scn").read_text()
    assert scn.startswith("CUBEASF")
    assert "SearchPath=TEESSIDEKARTING\\ASSETS\\GMT" in scn and "MASFile=COMMONMAPS.MAS" in scn
    assert scn.count("View=mainview") == 1  # the export's own header isn't duplicated
    road = scn[scn.index("Instance=road_e0_n0"):]
    road = road[:road.index("}")]
    assert "Deformable=True" in road and "CollTarget=True" in road and "HATTarget=True" in road
    assert "VisGroups=(32) ReflectPlane" in road
    assert "Response=VEHICLE,TIMING" in scn and "Response=VEHICLE,PITSTOP" in scn
    assert "Instance=SkyBoxi" in scn

    aiw = root / "Teesside_Karting" / "Teesside_Karting.AIW"
    assert aiw.read_text() == "[Features]\n"  # placeholder from the sample track

    # A real AIW recorded later is never overwritten by a re-run.
    aiw.write_text("recorded")
    subprocess.run([sys.executable, str(ROOT / "tools/make_track_folder.py"), "--gmt", str(gmt),
                    "--textures", str(tex), "--summary", str(summary), "--reference", str(ref),
                    "--out", str(out)], check=True)
    assert aiw.read_text() == "recorded"

    # Exactly one CR per line in the files rF2 parses (a doubled "\r\r\n" made rF2 skip the track).
    for f in ("Teesside_Karting.gdb", "Teesside_Karting.scn"):
        raw = (root / "Teesside_Karting" / f).read_bytes()
        assert b"\r\r" not in raw and raw.count(b"\r\n") == raw.count(b"\n")

    gdb = (root / "Teesside_Karting" / "Teesside_Karting.gdb").read_text()
    assert gdb.startswith("Teesside_Karting")
    assert "TerrainDataFile=..\\TeessideKarting.tdf" in gdb
    assert "Latitude = 54.57" in gdb and "Longitude = -1.18" in gdb
    assert "Length = 1.629 KM" in gdb
    assert "Filter Properties = rFRS TMOD NSCRS IndyCar\r\n" in gdb or "Filter Properties = rFRS TMOD NSCRS IndyCar\n" in gdb
