#!/usr/bin/env python3
"""Build a 3D kart-track mesh from a real-world centreline + elevation data.

Inputs
  centreline : .kml (Google Earth path), .gpx, or .geojson (fetch_osm.py output)
  elevation  : optional GeoTIFF DEM - ideally the Environment Agency 1 m LIDAR
               DTM tiles for the site (any CRS; it is reprojected on the fly).
               Without a DEM, KML/GPX altitudes are used if present, else flat.

Outputs (in --out-dir)
  track.obj / track.mtl  road, kerbs, run-off/grass and terrain apron (Y-up,
                         metres, origin at the start/finish line) - import into
                         Blender or 3ds Max as the base for the rFactor 2 scene.
  centreline.csv         distance, x, y(up), z, width, heading - handy for
                         placing objects and checking gradients.
  preview.png            plan + elevation profile (needs matplotlib).

Example
  python tools/build_track.py data/teesside_karting.kml --dem data/lidar_dtm.tif \
      --width 8 --out-dir build
"""
import argparse
import csv
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from pyproj import Transformer

BNG = "EPSG:27700"  # British National Grid - same CRS as EA LIDAR tiles


# --------------------------------------------------------------------------- input

def _strip_ns(tag):
    return tag.rsplit("}", 1)[-1]


def read_kml(path):
    """Return the longest LineString / LinearRing in a KML as [(lon, lat, alt)]."""
    best = []
    for el in ET.parse(path).iter():
        if _strip_ns(el.tag) != "coordinates":
            continue
        pts = []
        for tok in (el.text or "").split():
            parts = [float(v) for v in tok.split(",")]
            pts.append((parts[0], parts[1], parts[2] if len(parts) > 2 else float("nan")))
        if len(pts) > len(best):
            best = pts
    return best


def read_gpx(path):
    pts = []
    for el in ET.parse(path).iter():
        if _strip_ns(el.tag) in ("trkpt", "rtept"):
            ele = next((c.text for c in el if _strip_ns(c.tag) == "ele"), None)
            pts.append((float(el.get("lon")), float(el.get("lat")), float(ele) if ele else float("nan")))
    return pts


def read_geojson(path, way_id=None):
    feats = json.loads(Path(path).read_text())
    feats = feats.get("features", [feats])
    lines = [f for f in feats if f["geometry"]["type"] in ("LineString", "Polygon")]
    if way_id is not None:
        lines = [f for f in lines if f.get("properties", {}).get("osm_id") == way_id]
        if not lines:
            sys.exit(f"way {way_id} not found in {path}")
    if not lines:
        sys.exit(f"no LineString found in {path}")

    def coords(f):
        c = f["geometry"]["coordinates"]
        return c[0] if f["geometry"]["type"] == "Polygon" else c

    best = max(lines, key=lambda f: len(coords(f)))
    return [(c[0], c[1], c[2] if len(c) > 2 else float("nan")) for c in coords(best)]


def read_centreline(path, way_id=None):
    ext = Path(path).suffix.lower()
    if ext == ".kml":
        pts = read_kml(path)
    elif ext == ".gpx":
        pts = read_gpx(path)
    elif ext in (".geojson", ".json"):
        pts = read_geojson(path, way_id)
    else:
        sys.exit(f"unsupported centreline format: {ext}")
    if len(pts) < 3:
        sys.exit("centreline needs at least 3 points")
    return np.array(pts, dtype=float)


# ---------------------------------------------------------------------- geometry

def dedupe(xy, tol=0.05):
    keep = [0]
    for i in range(1, len(xy)):
        if np.linalg.norm(xy[i] - xy[keep[-1]]) > tol:
            keep.append(i)
    return np.array(keep)


def resample(xy, step, closed):
    """Evenly resample a polyline every `step` metres (linear)."""
    pts = np.vstack([xy, xy[:1]]) if closed else xy
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    total = s[-1]
    n = max(int(round(total / step)), 4)
    t = np.linspace(0, total, n, endpoint=not closed)
    return np.column_stack([np.interp(t, s, pts[:, k]) for k in range(pts.shape[1])]), total


def smooth(values, window, closed):
    """Moving-average smoothing (window in samples, odd)."""
    if window <= 1:
        return values
    k = np.ones(window) / window
    pad = window // 2
    if closed:
        ext = np.concatenate([values[-pad:], values, values[:pad]])
    else:
        ext = np.concatenate([np.repeat(values[:1], pad, 0), values, np.repeat(values[-1:], pad, 0)])
    if values.ndim == 1:
        return np.convolve(ext, k, mode="valid")
    return np.column_stack([np.convolve(ext[:, i], k, mode="valid") for i in range(values.shape[1])])


def tangents(xy, closed):
    if closed:
        d = np.roll(xy, -1, 0) - np.roll(xy, 1, 0)
    else:
        d = np.gradient(xy, axis=0)
    return d / np.linalg.norm(d, axis=1, keepdims=True)


# --------------------------------------------------------------------- elevation

class DEM:
    def __init__(self, path):
        import rasterio
        self.ds = rasterio.open(path)
        self.band = self.ds.read(1, masked=True)
        # EA .asc tiles often ship without a .prj; they are always British National Grid.
        self.to_dem = Transformer.from_crs(BNG, self.ds.crs or BNG, always_xy=True)

    def sample(self, e, n):
        """Bilinear sample at BNG easting/northing arrays."""
        x, y = self.to_dem.transform(np.asarray(e), np.asarray(n))
        col, row = ~self.ds.transform * (x, y)
        col, row = np.asarray(col) - 0.5, np.asarray(row) - 0.5
        c0 = np.clip(np.floor(col).astype(int), 0, self.band.shape[1] - 2)
        r0 = np.clip(np.floor(row).astype(int), 0, self.band.shape[0] - 2)
        fc, fr = np.clip(col - c0, 0, 1), np.clip(row - r0, 0, 1)
        b = self.band.filled(np.nan)
        z = (b[r0, c0] * (1 - fc) * (1 - fr) + b[r0, c0 + 1] * fc * (1 - fr)
             + b[r0 + 1, c0] * (1 - fc) * fr + b[r0 + 1, c0 + 1] * fc * fr)
        return z


def fill_nan(z):
    z = np.array(z, dtype=float)
    bad = np.isnan(z)
    if bad.all():
        return np.zeros_like(z)
    if bad.any():
        idx = np.arange(len(z))
        z[bad] = np.interp(idx[bad], idx[~bad], z[~bad])
    return z


# -------------------------------------------------------------------------- mesh

class Mesh:
    def __init__(self):
        self.v, self.vt, self.groups = [], [], {}

    def strip(self, name, material, left, right, u_left, u_right, v_coord, closed):
        """Quad strip between two rows of 3D points (N x 3), same length."""
        base = len(self.v)
        tbase = len(self.vt)
        n = len(left)
        for i in range(n):
            self.v += [left[i], right[i]]
            self.vt += [(u_left, v_coord[i]), (u_right, v_coord[i])]
        faces = []
        last = n if closed else n - 1
        for i in range(last):
            j = (i + 1) % n
            a, b, c, d = base + 2 * i, base + 2 * i + 1, base + 2 * j + 1, base + 2 * j
            ta, tb, tc, td = tbase + 2 * i, tbase + 2 * i + 1, tbase + 2 * j + 1, tbase + 2 * j
            # Wind counter-clockwise when viewed from above (+Y up).
            faces.append(((a, ta), (b, tb), (c, tc), (d, td)))
        self.groups.setdefault((name, material), []).extend(faces)

    def write(self, obj_path, materials):
        obj_path = Path(obj_path)
        mtl = obj_path.with_suffix(".mtl")
        with open(mtl, "w") as f:
            for name, rgb in materials.items():
                f.write(f"newmtl {name}\nKd {rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f}\nKa 0 0 0\nKs 0 0 0\n"
                        f"map_Kd textures/{name}.png\n\n")
        with open(obj_path, "w") as f:
            f.write(f"# Generated by build_track.py - units: metres, Y up\nmtllib {mtl.name}\n")
            for x, y, z in self.v:
                f.write(f"v {x:.4f} {y:.4f} {z:.4f}\n")
            for u, v in self.vt:
                f.write(f"vt {u:.4f} {v:.4f}\n")
            for (name, material), faces in self.groups.items():
                f.write(f"o {name}\nusemtl {material}\n")
                for face in faces:
                    f.write("f " + " ".join(f"{vi + 1}/{ti + 1}" for vi, ti in face) + "\n")


# -------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("centreline", help=".kml / .gpx / .geojson")
    ap.add_argument("--way-id", type=int, help="OSM way id to use from a GeoJSON with several")
    ap.add_argument("--dem", help="GeoTIFF elevation model (EA LIDAR DTM recommended)")
    ap.add_argument("--width", type=float, default=8.0, help="track width in metres (default 8)")
    ap.add_argument("--kerb", type=float, default=0.6, help="kerb width each side, 0 to disable")
    ap.add_argument("--kerb-height", type=float, default=0.04)
    ap.add_argument("--runoff", type=float, default=4.0, help="grass/run-off width each side")
    ap.add_argument("--apron", type=float, default=25.0, help="terrain apron beyond run-off, 0 to disable")
    ap.add_argument("--step", type=float, default=1.0, help="mesh spacing along the track (m)")
    ap.add_argument("--smooth-xy", type=float, default=4.0, help="plan smoothing window (m)")
    ap.add_argument("--smooth-z", type=float, default=15.0, help="road elevation smoothing window (m)")
    ap.add_argument("--reverse", action="store_true", help="reverse driving direction")
    ap.add_argument("--start-offset", type=float, default=0.0,
                    help="move the start/finish (and origin) this many metres along the track")
    ap.add_argument("--out-dir", default="build")
    args = ap.parse_args()

    raw = read_centreline(args.centreline, args.way_id)
    if args.reverse:
        raw = raw[::-1]

    to_bng = Transformer.from_crs("EPSG:4326", BNG, always_xy=True)
    e, n = to_bng.transform(raw[:, 0], raw[:, 1])
    en = np.column_stack([e, n])
    keep = dedupe(en)
    en, alt = en[keep], raw[keep, 2]

    closed = np.linalg.norm(en[0] - en[-1]) < max(args.width, 5.0)
    if closed and np.linalg.norm(en[0] - en[-1]) < 0.5:
        en, alt = en[:-1], alt[:-1]

    # Resample, smooth plan shape, resample again so spacing is exact.
    pts, _ = resample(np.column_stack([en, alt]), args.step, closed)
    win = max(1, int(round(args.smooth_xy / args.step)) | 1)
    pts[:, :2] = smooth(pts[:, :2], win, closed)
    pts, length = resample(pts, args.step, closed)

    if args.start_offset:
        shift = int(round(args.start_offset / args.step)) % len(pts)
        if not closed:
            sys.exit("--start-offset only applies to closed loops")
        pts = np.roll(pts, -shift, axis=0)

    dem = DEM(args.dem) if args.dem else None
    if dem:
        zc = fill_nan(dem.sample(pts[:, 0], pts[:, 1]))
        source = "DEM"
    elif not np.isnan(pts[:, 2]).all() and np.nanmax(pts[:, 2]) - np.nanmin(pts[:, 2]) > 0:
        zc = fill_nan(pts[:, 2])
        source = "centreline altitudes"
    else:
        zc = np.zeros(len(pts))
        source = "flat (no elevation data)"
    zwin = max(1, int(round(args.smooth_z / args.step)) | 1)
    zc = smooth(zc, zwin, closed)

    # Local frame: origin at start/finish; x = east, y = up, z = -north (OBJ / Blender-friendly).
    origin_en = pts[0, :2].copy()
    origin_z = zc[0]
    t = tangents(pts[:, :2], closed)
    nrm = np.column_stack([-t[:, 1], t[:, 0]])  # left-hand normal in (east, north)

    def to_local(en_xy, z):
        return np.column_stack([en_xy[:, 0] - origin_en[0], z - origin_z, -(en_xy[:, 1] - origin_en[1])])

    def offset(d):
        return pts[:, :2] + nrm * d

    def terrain(d, fallback):
        if dem is None:
            return fallback
        z = dem.sample(*offset(d).T)
        return np.where(np.isnan(z), fallback, z)

    half = args.width / 2
    vdist = np.arange(len(pts)) * args.step / 5.0  # texture repeats every 5 m along track
    mesh = Mesh()

    # Road: flat across its width (no camber) at smoothed centreline height.
    mesh.strip("road", "road", to_local(offset(half), zc), to_local(offset(-half), zc), 0, 1, vdist, closed)

    edge = half
    if args.kerb > 0:
        zk = zc + args.kerb_height
        for side, sgn in (("L", 1), ("R", -1)):
            inner, outer = to_local(offset(sgn * half), zk), to_local(offset(sgn * (half + args.kerb)), zk)
            a, b = (outer, inner) if sgn > 0 else (inner, outer)
            mesh.strip(f"kerb{side}", "kerb", a, b, 0, 1, vdist, closed)
        edge = half + args.kerb

    # Run-off blends from road height to the measured terrain.
    for side, sgn in (("L", 1), ("R", -1)):
        z_out = terrain(sgn * (edge + args.runoff), zc)
        z_out = smooth(z_out, zwin, closed) if dem else z_out
        inner = to_local(offset(sgn * edge), zc)
        outer = to_local(offset(sgn * (edge + args.runoff)), z_out)
        a, b = (outer, inner) if sgn > 0 else (inner, outer)
        mesh.strip(f"runoff{side}", "grass", a, b, 0, args.runoff / 5, vdist, closed)
        if args.apron > 0:
            d_far = sgn * (edge + args.runoff + args.apron)
            far = to_local(offset(d_far), terrain(d_far, z_out))
            a, b = (far, outer) if sgn > 0 else (outer, far)
            mesh.strip(f"apron{side}", "terrain", a, b, 0, args.apron / 5, vdist, closed)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mesh.write(out / "track.obj", {"road": (0.25, 0.25, 0.27), "kerb": (0.8, 0.1, 0.1),
                                    "grass": (0.25, 0.5, 0.2), "terrain": (0.35, 0.45, 0.25)})

    local = to_local(pts[:, :2], zc)
    heading = np.degrees(np.arctan2(t[:, 0], t[:, 1])) % 360
    with open(out / "centreline.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dist_m", "x", "y_up", "z", "width_m", "heading_deg", "easting", "northing"])
        for i, (p, h) in enumerate(zip(local, heading)):
            w.writerow([f"{i * args.step:.2f}", f"{p[0]:.3f}", f"{p[1]:.3f}", f"{p[2]:.3f}",
                        f"{args.width:.2f}", f"{h:.1f}", f"{pts[i, 0]:.2f}", f"{pts[i, 1]:.2f}"])

    grade = np.diff(zc) / args.step * 100
    dh = np.diff(np.unwrap(np.arctan2(t[:, 1], t[:, 0])))
    radius = args.step / np.maximum(np.abs(dh), 1e-9)
    min_radius = float(radius.min())
    if min_radius < edge + args.runoff:
        at = int(radius.argmin()) * args.step
        print(f"WARNING: tightest corner radius {min_radius:.1f} m at {at:.0f} m is smaller than the "
              f"track half-width + kerb + run-off ({edge + args.runoff:.1f} m); the inside edge will fold "
              f"over itself there. Increase --smooth-xy, reduce --runoff, or fix it by hand in Blender.",
              file=sys.stderr)
    summary = {
        "length_m": round(float(len(pts) * args.step if closed else length), 1),
        "closed_loop": bool(closed),
        "elevation_source": source,
        "elevation_range_m": round(float(zc.max() - zc.min()), 2),
        "max_grade_pct": round(float(np.abs(grade).max()) if len(grade) else 0.0, 2),
        "min_corner_radius_m": round(min_radius, 1),
        "origin_bng": [round(float(origin_en[0]), 2), round(float(origin_en[1]), 2)],
        "origin_alt_m": round(float(origin_z), 2),
        "vertices": len(mesh.v),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5), gridspec_kw={"width_ratios": [1.2, 1]})
        for d in (half, -half):
            o = to_local(offset(d), zc)
            ax1.plot(o[:, 0], -o[:, 2], "k-", lw=0.8)
        ax1.plot(local[:, 0], -local[:, 2], "r--", lw=0.6)
        ax1.plot(0, 0, "go", label="start/finish (origin)")
        ax1.annotate("", xy=(local[3, 0], -local[3, 2]), xytext=(0, 0), arrowprops={"arrowstyle": "->"})
        ax1.set_aspect("equal")
        ax1.set_title("Plan (m, north up)")
        ax1.legend(loc="best", fontsize=8)
        ax2.plot(np.arange(len(zc)) * args.step, zc)
        ax2.set_title(f"Elevation profile ({source})")
        ax2.set_xlabel("distance (m)")
        ax2.set_ylabel("height (m)")
        fig.tight_layout()
        fig.savefig(out / "preview.png", dpi=110)
    except ImportError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
