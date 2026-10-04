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
        if name.startswith("tyrewall"):
            continue  # vertical sides and n-gon caps; covered by test_tyre_walls
        f = np.array(fs)
        nrm = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
        assert (nrm[:, 1] > 0).mean() > 0.98, f"{name} faces should point up (+Y)"
    assert {"road", "kerbL", "kerbR", "runoffL", "runoffR", "terrain"} <= set(faces)

    # The terrain grid must never poke through the road: every terrain vertex under the road
    # (within half-width + kerb of the centreline) sits well below the road surface there,
    # and no terrain cell lies entirely under the road.
    import csv
    from scipy.spatial import cKDTree
    cl = np.array([[float(r["x"]), float(r["y_up"]), float(r["z"])]
                   for r in csv.DictReader(open(out / "centreline.csv"))])
    tv = v[np.unique(np.array(faces["terrain"]).ravel())]
    dist, near = cKDTree(cl[:, [0, 2]]).query(tv[:, [0, 2]])
    under = dist <= 5.6  # default 10 m width: 5 m half-width + 0.6 m kerb
    assert under.sum() > 100
    assert (tv[under, 1] < cl[near[under], 1] - 0.2).all()
    tf = np.array(faces["terrain"])
    centre = v[tf].mean(axis=1)
    assert (cKDTree(cl[:, [0, 2]]).query(centre[:, [0, 2]])[0] > 2.0).all()


def test_flatten_removes_mound(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    kml, dem, out = tmp_path / "t.kml", tmp_path / "dem.tif", tmp_path / "build"
    make_kml(kml)
    z = np.full((400, 600), 10.0, dtype="float32")
    z[160:200, 390:440] = 14.0  # 4 m mound across the track near its east end
    with rasterio.open(dem, "w", driver="GTiff", width=600, height=400, count=1, dtype="float32",
                       crs="EPSG:27700", transform=from_origin(451700, 520700, 1, 1)) as ds:
        ds.write(z, 1)

    def run(*extra):
        subprocess.run([sys.executable, str(ROOT / "tools/build_track.py"), str(kml), "--dem", str(dem),
                        "--out-dir", str(out), *extra], check=True)
        return json.loads((out / "summary.json").read_text())

    assert run()["elevation_range_m"] > 1.0
    flat = run("--flatten", "570:60")  # mound straddles the start line, so the range wraps
    assert flat["elevation_range_m"] < 0.05
    assert flat["flattened"] == [[570.0, 60.0]]


def test_tight_hairpins_keep_runoff_unfolded(tmp_path):
    # Stadium shape: two 60 m straights joined by 7 m-radius hairpins (a normal kart hairpin).
    r, L = 7.0, 60.0
    pts = [(x, -r) for x in np.arange(0, L, 1.0)]
    pts += [(L + r * np.sin(a), -r * np.cos(a)) for a in np.arange(0, np.pi, 0.1)]
    pts += [(x, r) for x in np.arange(L, 0, -1.0)]
    pts += [(-r * np.sin(a), r * np.cos(a)) for a in np.arange(0, np.pi, 0.1)]
    to_ll = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(452000 + np.array(pts)[:, 0], 520500 + np.array(pts)[:, 1])
    kml = tmp_path / "hairpin.kml"
    kml.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><LineString><coordinates>'
                   + " ".join(f"{a:.8f},{b:.8f}" for a, b in zip(lon, lat))
                   + "</coordinates></LineString></Placemark></kml>")
    out = tmp_path / "build"
    res = subprocess.run([sys.executable, str(ROOT / "tools/build_track.py"), str(kml), "--out-dir", str(out),
                          "--smooth-xy", "1"], check=True, capture_output=True, text=True)
    assert "WARNING" not in res.stderr  # 7 m radius > 5.6 m half-width + kerb: the road itself is fine

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
        if name.startswith("tyrewall"):
            continue  # vertical sides and n-gon caps; covered by test_tyre_walls
        f = np.array(fs)
        # Both triangles of each quad must face up, otherwise the strip has folded over itself.
        for tri in ((0, 1, 2), (0, 2, 3)):
            nrm = np.cross(v[f[:, tri[1]]] - v[f[:, tri[0]]], v[f[:, tri[2]]] - v[f[:, tri[0]]])
            assert (nrm[:, 1] > -1e-9).all(), f"{name} folds over itself in a hairpin"


def test_tyre_walls(tmp_path):
    kml, dem, out = tmp_path / "t.kml", tmp_path / "dem.tif", tmp_path / "build"
    make_kml(kml)
    make_dem(dem)
    subprocess.run([sys.executable, str(ROOT / "tools/build_track.py"), str(kml), "--dem", str(dem),
                    "--out-dir", str(out)], check=True)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["tyre_stacks"] > 50
    assert summary["tyre_wall_collision_m"] > 20

    import csv
    from scipy.spatial import cKDTree
    v, faces, cur = [], {}, None
    for line in (out / "track.obj").read_text().splitlines():
        if line.startswith("v "):
            v.append([float(c) for c in line.split()[1:]])
        elif line.startswith("o "):
            cur = line.split()[1]
        elif line.startswith("f "):
            faces.setdefault(cur, []).append([int(p.split("/")[0]) - 1 for p in line.split()[1:]])
    v = np.array(v)
    cl = np.array([[float(r["x"]), float(r["y_up"]), float(r["z"])]
                   for r in csv.DictReader(open(out / "centreline.csv"))])
    tree = cKDTree(cl[:, [0, 2]])

    tyre_v = v[np.unique([i for f in faces["tyrewall"] for i in f])]
    # Every tyre is beyond the road, kerb and run-off (5 + 0.6 + 4 m from the centreline).
    assert tree.query(tyre_v[:, [0, 2]])[0].min() > 9.6 - 1e-6
    # Tyres sit at ground level, not floating far above or buried below the track.
    assert tyre_v[:, 1].min() > cl[:, 1].min() - 3

    # Collision quads are vertical and face the track.
    for f in faces["tyrewall_collision"]:
        p = v[f]
        nrm = np.cross(p[1] - p[0], p[3] - p[0])
        assert abs(nrm[1]) < 1e-6 * np.linalg.norm(nrm) + 1e-9
        centre = p.mean(axis=0)
        towards = cl[tree.query(centre[[0, 2]])[1]] - centre
        assert np.dot(nrm[[0, 2]], towards[[0, 2]]) > 0
