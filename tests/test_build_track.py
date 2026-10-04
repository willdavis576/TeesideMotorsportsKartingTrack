"""Smoke test: synthetic kart layout + synthetic sloped DEM -> mesh with upward faces."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]


def make_kml(path):
    # Rounded "kidney" loop roughly 700 m long, near Middlesbrough.
    t = np.linspace(0, 2 * np.pi, 120, endpoint=False)
    x = 110 * np.cos(t) + 25 * np.cos(3 * t)
    y = 60 * np.sin(t) + 15 * np.sin(2 * t)
    to_ll = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(452000 + x, 520500 + y)
    coords = " ".join(f"{a:.7f},{b:.7f},0" for a, b in zip(lon, lat))
    path.write_text(f'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark>'
                    f'<LineString><coordinates>{coords}</coordinates></LineString></Placemark></kml>')


def make_dem(path):
    import rasterio
    from rasterio.transform import from_origin
    w, h = 600, 400
    xs = np.arange(w)[None, :].repeat(h, 0)
    z = (10 + 0.02 * xs).astype("float32")  # 2% slope rising to the east
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32",
                       crs="EPSG:27700", transform=from_origin(451700, 520700, 1, 1)) as ds:
        ds.write(z, 1)


def test_build(tmp_path):
    kml, dem, out = tmp_path / "t.kml", tmp_path / "dem.tif", tmp_path / "build"
    make_kml(kml)
    make_dem(dem)
    subprocess.run([sys.executable, str(ROOT / "tools/build_track.py"), str(kml), "--dem", str(dem),
                    "--out-dir", str(out)], check=True)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["closed_loop"]
    assert 600 < summary["length_m"] < 900
    assert summary["elevation_source"] == "DEM"
    assert 2 < summary["elevation_range_m"] < 8  # ~270 m east-west span at 2%

    v, faces, cur = [], {}, None
    for line in (out / "track.obj").read_text().splitlines():
        if line.startswith("v "):
            v.append([float(c) for c in line.split()[1:]])
        elif line.startswith("o "):
            cur = line.split()[1]
        elif line.startswith("f "):
            faces.setdefault(cur, []).append([int(p.split("/")[0]) - 1 for p in line.split()[1:]])
    v = np.array(v)
    for name, fs in faces.items():
        f = np.array(fs)
        nrm = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
        assert (nrm[:, 1] > 0).mean() > 0.98, f"{name} faces should point up (+Y)"
    assert {"road", "kerbL", "kerbR", "runoffL", "runoffR", "apronL", "apronR"} <= set(faces)
