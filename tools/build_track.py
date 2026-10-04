#!/usr/bin/env python3
"""Build a 3D kart-track mesh from a real-world centreline + elevation data.

Inputs
  centreline : .kml (Google Earth path), .gpx, or .geojson (fetch_osm.py output)
  elevation  : optional GeoTIFF DEM - ideally the Environment Agency 1 m LIDAR
               DTM tiles for the site (any CRS; it is reprojected on the fly).
               Without a DEM, KML/GPX altitudes are used if present, else flat.

Outputs (in --out-dir)
  track.obj / track.mtl  road, kerbs, run-off/grass and a LIDAR terrain grid (Y-up,
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
    seg = np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1)  # plan distance; altitude may be NaN
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


def median_filter(values, window, closed):
    """Running median - removes short spikes (tyre walls, parked vehicles) that averaging would smear."""
    if window <= 1:
        return values
    pad = window // 2
    if closed:
        ext = np.concatenate([values[-pad:], values, values[:pad]])
    else:
        ext = np.concatenate([np.repeat(values[:1], pad), values, np.repeat(values[-1:], pad)])
    return np.median(np.lib.stride_tricks.sliding_window_view(ext, window), axis=1)


def flatten_ranges(z, ranges, step, closed):
    """Replace elevation inside each (start, end) distance range with a straight line between its ends."""
    z = z.copy()
    n = len(z)
    for start, end in ranges:
        i0, i1 = int(round(start / step)), int(round(end / step))
        if closed:
            idx = np.arange(i0, i1 + 1 if i1 >= i0 else i1 + n + 1) % n
        else:
            idx = np.arange(max(i0, 0), min(i1, n - 1) + 1)
        if len(idx) > 2:
            z[idx] = np.linspace(z[idx[0]], z[idx[-1]], len(idx))
    return z


def parse_range(text):
    try:
        a, b = (float(v) for v in text.split(":"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected START:END in metres, got {text!r}")
    return a, b


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
        h, w = self.band.shape
        c0 = np.clip(np.floor(col).astype(int), 0, w - 2)
        r0 = np.clip(np.floor(row).astype(int), 0, h - 2)
        fc, fr = np.clip(col - c0, 0, 1), np.clip(row - r0, 0, 1)
        b = self.band.filled(np.nan)
        z = (b[r0, c0] * (1 - fc) * (1 - fr) + b[r0, c0 + 1] * fc * (1 - fr)
             + b[r0 + 1, c0] * (1 - fc) * fr + b[r0 + 1, c0 + 1] * fc * fr)
        # Outside the DEM: no data rather than a smeared edge value.
        outside = (col < -0.5) | (row < -0.5) | (col > w - 0.5) | (row > h - 0.5)
        return np.where(outside, np.nan, z)


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

def build_terrain(dem, pts, zc, edge, runoff, margin, res, sink=0.05, road_sink=0.3):
    """Regular DEM grid around the track that stays just under the road and run-off.

    Returns (east, north, z, valid, hidden) arrays of shape (rows, cols). `hidden` marks points far
    enough inside the road that any grid cell whose corners are all hidden lies entirely under the
    tarmac; those cells are dropped (they would only z-fight with the road). Elsewhere under the
    road and kerbs the ground is pushed `road_sink` below the road surface; across the run-off it follows the same blend from
    road height to measured ground that the run-off strip uses, minus `sink`; beyond that it is
    the raw DEM.
    """
    from scipy.spatial import cKDTree

    e0, n0 = pts[:, 0].min() - margin, pts[:, 1].min() - margin
    e1, n1 = pts[:, 0].max() + margin, pts[:, 1].max() + margin
    east = np.arange(e0, e1 + res, res)
    north = np.arange(n1, n0 - res, -res)  # top row = north
    E, N = np.meshgrid(east, north)
    Z = dem.sample(E.ravel(), N.ravel()).reshape(E.shape)

    dist, nearest = cKDTree(pts[:, :2]).query(np.column_stack([E.ravel(), N.ravel()]))
    dist, z_road = dist.reshape(E.shape), zc[nearest].reshape(E.shape)

    under_road = dist <= edge
    f = np.clip((dist - edge) / max(runoff, 1e-6), 0, 1)
    blended = (1 - f) * z_road + f * Z - sink
    Z = np.where(under_road, z_road - road_sink, np.where(dist < edge + runoff, np.fmin(Z, blended), Z))
    # Points under the track with no DEM value can still take the road height.
    Z = np.where(np.isnan(Z) & (dist < edge + runoff), z_road - road_sink, Z)
    # Every point of a cell is within res/sqrt(2) of one of its corners, and distance to the
    # centreline changes no faster than distance travelled, so this guarantees full coverage.
    hidden = dist < edge - res * 0.71 - 0.1
    return E, N, Z, ~np.isnan(Z), hidden


def write_placeholder_textures(folder, size=512, seed=1):
    """Simple procedural textures matching the OBJ's UV layout. Existing files are left alone,
    so replace them with real photo textures whenever you like."""
    import matplotlib.pyplot as plt
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    def noise(scale):
        # Tileable value noise: blur white noise with a wrapped box filter.
        n = rng.random((size, size))
        k = max(1, size // scale)
        for axis in (0, 1):
            n = sum(np.roll(n, i, axis=axis) for i in range(k)) / k
        return (n - n.min()) / (np.ptp(n) + 1e-9)

    def save(name, rgb):
        path = folder / f"{name}.png"
        if not path.exists():
            plt.imsave(path, np.clip(rgb, 0, 1))

    fine, coarse = noise(256)[..., None], noise(16)[..., None]
    # Road: U runs across the track (0..1 = full width), V along it (1.0 = 5 m).
    save("road", np.array([0.23, 0.23, 0.25]) + 0.10 * (fine - 0.5) + 0.05 * (coarse - 0.5))
    # Kerb: 4 stripes per 5 m (1.25 m each), alternating red/white along the track.
    v = np.arange(size)[:, None, None] / size
    stripes = np.where((v * 4).astype(int) % 2 == 0, [0.75, 0.08, 0.08], [0.92, 0.92, 0.92])
    save("kerb", np.broadcast_to(stripes, (size, size, 3)) * (0.92 + 0.08 * fine))
    save("grass", np.array([0.22, 0.42, 0.16]) + 0.12 * (fine - 0.5) + 0.10 * (coarse - 0.5))
    save("terrain", np.array([0.30, 0.40, 0.20]) + 0.10 * (fine - 0.5) + 0.15 * (coarse - 0.5))
    # Tyre stack: V runs bottom to top over three tyres; dark grooves between them.
    row = np.arange(size)[:, None, None] / size
    groove = (np.abs((row * 3) % 1 - 0.5) > 0.44)
    save("tyre", np.where(groove, 0.02, 0.09) + 0.03 * (fine - 0.5) + np.zeros((size, size, 3)))
    save("collision", np.full((size, size, 3), [0.6, 0.6, 0.9]))


def bool_runs(mask, closed):
    """Index arrays of consecutive True runs; on a closed loop a run may wrap past the end."""
    n = len(mask)
    if mask.all():
        return [np.arange(n)]
    start = int(np.argmin(mask)) if closed else 0  # begin at a False so no run is split
    order = (np.arange(n) + start) % n
    runs, cur = [], []
    for i in order:
        if mask[i]:
            cur.append(i)
        elif cur:
            runs.append(np.array(cur))
            cur = []
    if cur:
        runs.append(np.array(cur))
    return runs


def dilate(mask, k, closed):
    if k <= 0:
        return mask
    ext = np.concatenate([mask[-k:], mask, mask[:k]]) if closed else np.pad(mask, k)
    return np.lib.stride_tricks.sliding_window_view(ext, 2 * k + 1).any(axis=1)


def resample_polyline(xy, spacing):
    seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    if s[-1] < spacing:
        return xy[:1]
    t = np.arange(0, s[-1] + 1e-9, spacing)
    return np.column_stack([np.interp(t, s, xy[:, 0]), np.interp(t, s, xy[:, 1])])


def tyre_stack(cx, cy, z0, radius, height, sides=12):
    """Vertices, UVs and faces of one tyre stack (open-bottom cylinder) in east/north/up."""
    a = np.linspace(0, 2 * np.pi, sides, endpoint=False)
    ring = np.column_stack([cx + radius * np.cos(a), cy + radius * np.sin(a)])
    verts, uvs = [], []
    for z, v in ((z0, 0.0), (z0 + height, 1.0)):
        for i in range(sides + 1):  # duplicate the seam so U runs 0..1
            verts.append((*ring[i % sides], z))
            uvs.append((i / sides, v))
    m = sides + 1
    faces = [(i, i + 1, m + i + 1, m + i) for i in range(sides)]  # CCW ring -> outward normals
    cap0 = len(verts)
    for i in range(sides):
        verts.append((*ring[i], z0 + height))
        uvs.append((0.5 + 0.5 * np.cos(a[i]), 0.5 + 0.5 * np.sin(a[i])))
    faces.append(tuple(range(cap0, cap0 + sides)))  # top cap, CCW from above -> faces up
    return verts, uvs, faces


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

    def grid(self, name, material, xyz, valid, uv_scale, hidden=None):
        """Triangulated height-field from an (rows, cols, 3) array. Cells touching invalid points,
        or with all four corners hidden, are skipped."""
        rows, cols, _ = xyz.shape
        base, tbase = len(self.v), len(self.vt)
        self.v += [tuple(p) for p in xyz.reshape(-1, 3)]
        self.vt += [(p[0] / uv_scale, -p[2] / uv_scale) for p in xyz.reshape(-1, 3)]
        idx = np.arange(rows * cols).reshape(rows, cols)
        faces = []
        for r in range(rows - 1):
            for c in range(cols - 1):
                if not (valid[r, c] and valid[r, c + 1] and valid[r + 1, c] and valid[r + 1, c + 1]):
                    continue
                if hidden is not None and (hidden[r, c] and hidden[r, c + 1]
                                           and hidden[r + 1, c] and hidden[r + 1, c + 1]):
                    continue
                # Row index increases southwards, column eastwards: (r+1,c) -> (r+1,c+1) -> (r,c+1)
                # is counter-clockwise seen from above.
                a, b, cc, d = idx[r + 1, c], idx[r + 1, c + 1], idx[r, c + 1], idx[r, c]
                faces.append(tuple((i + base, i + tbase) for i in (a, b, cc, d)))
        self.groups.setdefault((name, material), []).extend(faces)

    def polys(self, name, material, verts, uvs, faces):
        """Arbitrary polygons; `faces` index into `verts`/`uvs` (same index for both)."""
        base, tbase = len(self.v), len(self.vt)
        self.v += [tuple(p) for p in verts]
        self.vt += [tuple(t) for t in uvs]
        self.groups.setdefault((name, material), []).extend(
            tuple((base + i, tbase + i) for i in f) for f in faces)

    def write(self, obj_path, materials, tile=0.0):
        """Write OBJ + MTL. With `tile` > 0, every object is split into tile x tile metre pieces
        (by face centre) named <object>_<col>_<row>, which game engines cull and load far better
        than one huge mesh. Returns {object name: vertex count}."""
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
            counts = {}
            verts = np.asarray(self.v)
            for (name, material), faces in self.groups.items():
                pieces = {}
                for face in faces:
                    if tile > 0:
                        c = verts[[vi for vi, _ in face]].mean(axis=0)
                        key = f"{name}_{int(np.floor(c[0] / tile)):+d}_{int(np.floor(-c[2] / tile)):+d}"
                    else:
                        key = name
                    pieces.setdefault(key, []).append(face)
                for key, fs in sorted(pieces.items()):
                    f.write(f"o {key}\nusemtl {material}\n")
                    for face in fs:
                        f.write("f " + " ".join(f"{vi + 1}/{ti + 1}" for vi, ti in face) + "\n")
                    counts[key] = len({vi for face in fs for vi, _ in face})
            return counts


# -------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("centreline", help=".kml / .gpx / .geojson")
    ap.add_argument("--way-id", type=int, help="OSM way id to use from a GeoJSON with several")
    ap.add_argument("--dem", help="GeoTIFF elevation model (EA LIDAR DTM recommended)")
    ap.add_argument("--width", type=float, default=10.0, help="track width in metres (default 10)")
    ap.add_argument("--kerb", type=float, default=0.6, help="kerb width each side, 0 to disable")
    ap.add_argument("--kerb-height", type=float, default=0.04)
    ap.add_argument("--kerb-corners", type=float, default=40.0,
                    help="only put kerbs through corners tighter than this radius (m), with a grass verge "
                         "elsewhere; 0 = kerbs along the whole lap")
    ap.add_argument("--runoff", type=float, default=4.0, help="grass/run-off width each side")
    ap.add_argument("--apron", type=float, default=0.0,
                    help="old-style terrain strip beyond the run-off (m); superseded by --terrain, default off")
    ap.add_argument("--terrain", type=float, default=40.0,
                    help="with --dem: LIDAR terrain grid extending this far beyond the track (m), 0 to disable")
    ap.add_argument("--terrain-res", type=float, default=2.0, help="terrain grid spacing (m)")
    ap.add_argument("--step", type=float, default=1.0, help="mesh spacing along the track (m)")
    ap.add_argument("--smooth-xy", type=float, default=4.0, help="plan smoothing window (m)")
    ap.add_argument("--smooth-z", type=float, default=15.0, help="road elevation smoothing window (m)")
    ap.add_argument("--despike", type=float, default=11.0,
                    help="running-median window (m) applied to road elevation before smoothing; 0 disables")
    ap.add_argument("--flatten", type=parse_range, action="append", default=[], metavar="START:END",
                    help="ignore the DEM between these lap distances (m) and ramp straight across; repeatable")
    ap.add_argument("--tyre-corners", type=float, default=30.0,
                    help="tyre walls on the outside of corners tighter than this radius (m); 0 disables")
    ap.add_argument("--tyre-extend", type=float, default=10.0,
                    help="carry tyre walls this far before and after each corner (m)")
    ap.add_argument("--tyre-gap", type=float, default=0.5, help="gap between run-off edge and tyres (m)")
    ap.add_argument("--reverse", action="store_true", help="reverse driving direction")
    ap.add_argument("--start-offset", type=float, default=0.0,
                    help="move the start/finish (and origin) this many metres along the track")
    ap.add_argument("--tile", type=float, default=100.0,
                    help="split every object into tiles this size (m) for the game engine; 0 = one piece each")
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
    t = tangents(pts[:, :2], closed)
    nrm = np.column_stack([-t[:, 1], t[:, 0]])  # left-hand normal in (east, north)

    if dem:
        # Median of several samples across the road width ignores features right at the edge.
        across = np.linspace(-args.width / 2, args.width / 2, 5)
        zs = np.column_stack([dem.sample(*(pts[:, :2] + nrm * d).T) for d in across])
        with np.errstate(all="ignore"):
            zc = np.nanmedian(zs, axis=1)
        missing = float(np.isnan(zc).mean())
        if missing > 0:
            print(f"WARNING: {missing:.0%} of the lap is outside the DEM or has no data; those parts are "
                  f"interpolated. Download the neighbouring LIDAR tiles too.", file=sys.stderr)
        zc = fill_nan(zc)
        source = "DEM"
    elif not np.isnan(pts[:, 2]).all() and np.nanmax(pts[:, 2]) - np.nanmin(pts[:, 2]) > 0:
        zc = fill_nan(pts[:, 2])
        source = "centreline altitudes"
    else:
        zc = np.zeros(len(pts))
        source = "flat (no elevation data)"
    raw_z = zc.copy()
    if args.despike > 0:
        zc = median_filter(zc, max(1, int(round(args.despike / args.step)) | 1), closed)
    zc = flatten_ranges(zc, args.flatten, args.step, closed)
    zwin = max(1, int(round(args.smooth_z / args.step)) | 1)
    zc = smooth(zc, zwin, closed)

    # Local frame: origin at start/finish; x = east, y = up, z = -north (OBJ / Blender-friendly).
    origin_en = pts[0, :2].copy()
    origin_z = zc[0]

    def to_local(en_xy, z):
        return np.column_stack([en_xy[:, 0] - origin_en[0], z - origin_z, -(en_xy[:, 1] - origin_en[1])])

    # Signed curvature (+ = turning left), lightly smoothed so one wobbly trace point doesn't dominate.
    heading_rad = np.arctan2(t[:, 1], t[:, 0])
    if closed:
        dh = np.diff(heading_rad, append=heading_rad[0])
    else:
        dh = np.gradient(np.unwrap(heading_rad))
    dh = (dh + np.pi) % (2 * np.pi) - np.pi  # per-sample turn, wrapped into [-pi, pi)
    kappa = smooth(dh / args.step, max(1, int(round(3 / args.step)) | 1), closed)
    radius = 1 / np.maximum(np.abs(kappa), 1e-9)

    def offset(d):
        """Points offset sideways by d metres (left positive); d may be a scalar or per-sample array."""
        return pts[:, :2] + nrm * np.reshape(d, (-1, 1))

    def inside_clamped(d, floor):
        """Shrink offsets on the inside of tight corners so run-off/terrain strips can't fold over."""
        d = np.broadcast_to(np.asarray(d, dtype=float), radius.shape)
        reach = float(np.abs(d).max())
        # The narrowing has to start before the corner (within `reach` metres) or the strip
        # folds at the corner entry/exit, so take the tightest radius nearby on that side.
        win = max(1, int(round(2 * reach / args.step)) | 1)
        out = d.copy()
        for side in (1, -1):
            r_side = np.where(kappa * side > 0, radius, np.inf)
            pad = win // 2
            ext = np.concatenate([r_side[-pad:], r_side, r_side[:pad]]) if closed else \
                np.pad(r_side, pad, constant_values=np.inf)
            near = np.lib.stride_tricks.sliding_window_view(ext, win).min(axis=1)
            lim = np.maximum(0.85 * near, abs(floor))
            sel = np.sign(d) == side
            out[sel] = side * np.minimum(np.abs(d[sel]), lim[sel])
        return out

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
        if args.kerb_corners > 0:
            # Kerbs through corners only (plus 5 m either side), as on the real track.
            has_kerb = dilate(radius < args.kerb_corners, int(round(5 / args.step)), closed)
        else:
            has_kerb = np.ones(len(pts), dtype=bool)
        # Ramp the kerb height in and out over ~2 m instead of stepping up.
        ramp = smooth(has_kerb.astype(float), max(1, int(round(2 / args.step)) | 1), closed)
        zk = zc + args.kerb_height * ramp
        n = len(pts)
        for side, sgn in (("L", 1), ("R", -1)):
            inner_all = to_local(offset(sgn * half), zk)
            outer_all = to_local(offset(sgn * (half + args.kerb)), zk)
            for flag, name, material in ((True, f"kerb{side}", "kerb"), (False, f"verge{side}", "grass")):
                for run in bool_runs(has_kerb == flag, closed):
                    if len(run) == n:  # the whole lap: one closed strip
                        idx, run_closed = run, closed
                    else:  # include the next sample so the run joins up with its neighbour
                        nxt = (run[-1] + 1) % n
                        idx = np.append(run, nxt) if (closed or run[-1] + 1 < n) else run
                        run_closed = False
                    if len(idx) < 2:
                        continue
                    vd = (run[0] + np.arange(len(idx))) * args.step / 5.0
                    inner, outer = inner_all[idx], outer_all[idx]
                    a, b = (outer, inner) if sgn > 0 else (inner, outer)
                    mesh.strip(name, material, a, b, 0, 1, vd, run_closed)
        edge = half + args.kerb

    # Run-off blends from road height to the measured terrain.
    for side, sgn in (("L", 1), ("R", -1)):
        d_out = inside_clamped(sgn * (edge + args.runoff), floor=edge + 0.3)
        z_out = terrain(d_out, zc)
        z_out = smooth(z_out, zwin, closed) if dem else z_out
        inner = to_local(offset(sgn * edge), zc)
        outer = to_local(offset(d_out), z_out)
        a, b = (outer, inner) if sgn > 0 else (inner, outer)
        mesh.strip(f"runoff{side}", "grass", a, b, 0, args.runoff / 5, vdist, closed)
        if args.apron > 0:
            d_far = inside_clamped(sgn * (edge + args.runoff + args.apron), floor=0)
            d_far = np.sign(d_far) * np.maximum(np.abs(d_far), np.abs(d_out) + 0.3)
            far = to_local(offset(d_far), terrain(d_far, z_out))
            a, b = (far, outer) if sgn > 0 else (outer, far)
            mesh.strip(f"apron{side}", "terrain", a, b, 0, args.apron / 5, vdist, closed)

    terrain_cells = 0
    if dem and args.terrain > 0:
        E, N, Z, valid, hidden = build_terrain(dem, pts, zc, edge, args.runoff, args.terrain, args.terrain_res)
        xyz = np.stack([E - origin_en[0], Z - origin_z, -(N - origin_en[1])], axis=-1)
        before = sum(len(f) for f in mesh.groups.values())
        mesh.grid("terrain", "terrain", np.nan_to_num(xyz), valid, uv_scale=10.0, hidden=hidden)
        terrain_cells = sum(len(f) for f in mesh.groups.values()) - before
        if not valid.all():
            print(f"WARNING: {1 - valid.mean():.0%} of the terrain area has no DEM data and was left out; "
                  f"download the neighbouring LIDAR tiles or reduce --terrain.", file=sys.stderr)

    tyre_stacks, wall_length = 0, 0.0
    if args.tyre_corners > 0:
        from scipy.spatial import cKDTree
        tyre_r, tyre_h = 0.3, 0.6  # stack of three tyres
        tree = cKDTree(pts[:, :2])
        reach = edge + args.runoff + args.tyre_gap + tyre_r
        ext = int(round(args.tyre_extend / args.step))
        tv, tuv, tf, cv, cuv, cf = [], [], [], [], [], []
        for turn in (1, -1):  # left-hand corners get a wall on the right, and vice versa
            corner = dilate((kappa * turn > 0) & (radius < args.tyre_corners), ext, closed)
            side = -turn
            for run in bool_runs(corner, closed):
                if len(run) < 3:
                    continue
                line = pts[run, :2] + nrm[run] * side * reach
                centres = resample_polyline(line, 2 * tyre_r)
                # Don't drop tyres onto another part of the track that runs close by.
                keep = tree.query(centres)[0] > edge + args.runoff
                for short in bool_runs(keep, closed=False):
                    if len(short) < 6:  # drop odd leftover fragments shorter than ~3.5 m
                        keep[short] = False
                z = dem.sample(*centres.T) if dem else np.full(len(centres), np.nan)
                z = np.where(np.isnan(z), zc[tree.query(centres)[1]], z) - 0.05
                for (cx, cy), z0, k in zip(centres, z, keep):
                    if not k:
                        continue
                    v_, uv_, f_ = tyre_stack(cx, cy, z0, tyre_r, tyre_h)
                    tf += [tuple(len(tv) + i for i in f) for f in f_]
                    tv += v_
                    tuv += uv_
                    tyre_stacks += 1
                # Collision wall: a 1 m vertical ribbon along the track-facing side of each
                # unbroken stretch of tyres, facing the track.
                towards = tree.query(centres)[1]
                inward = pts[towards, :2] - centres
                inward /= np.linalg.norm(inward, axis=1, keepdims=True) + 1e-9
                face_line = centres + inward * tyre_r
                for seg in bool_runs(keep, closed=False):
                    if len(seg) < 2:
                        continue
                    for a_, b_ in zip(seg[:-1], seg[1:]):
                        p0, p1 = face_line[a_], face_line[b_]
                        z0, z1 = z[a_], z[b_]
                        quad = [(*p0, z0 - 0.1), (*p1, z1 - 0.1), (*p1, z1 + 1.0), (*p0, z0 + 1.0)]
                        # Wind so the normal points at the track.
                        e1, e2 = np.subtract(quad[1], quad[0]), np.subtract(quad[3], quad[0])
                        if np.dot(np.cross(e1, e2)[:2], inward[a_]) < 0:
                            quad = quad[::-1]
                        cf.append(tuple(range(len(cv), len(cv) + 4)))
                        cv += quad
                        cuv += [(0, 0), (1, 0), (1, 1), (0, 1)]
                        wall_length += float(np.linalg.norm(p1 - p0))
        if tv:
            tv = np.array(tv)
            mesh.polys("tyrewall", "tyre", to_local(tv[:, :2], tv[:, 2]), tuv, tf)
        if cv:
            cv = np.array(cv)
            mesh.polys("tyrewall_collision", "collision", to_local(cv[:, :2], cv[:, 2]), cuv, cf)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        write_placeholder_textures(out / "textures")
    except ImportError:
        pass
    object_verts = mesh.write(out / "track.obj", {"road": (0.25, 0.25, 0.27), "kerb": (0.8, 0.1, 0.1),
                                    "grass": (0.25, 0.5, 0.2), "terrain": (0.35, 0.45, 0.25),
                                    "tyre": (0.05, 0.05, 0.05), "collision": (0.6, 0.6, 0.9)}, tile=args.tile)
    biggest = max(object_verts, key=object_verts.get)
    if object_verts[biggest] > 65535:
        print(f"WARNING: object {biggest} has {object_verts[biggest]} vertices; many game engines cap a mesh "
              f"at 65,535. Use a smaller --tile.", file=sys.stderr)

    local = to_local(pts[:, :2], zc)
    heading = np.degrees(np.arctan2(t[:, 0], t[:, 1])) % 360
    with open(out / "centreline.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dist_m", "x", "y_up", "z", "width_m", "heading_deg", "easting", "northing"])
        for i, (p, h) in enumerate(zip(local, heading)):
            w.writerow([f"{i * args.step:.2f}", f"{p[0]:.3f}", f"{p[1]:.3f}", f"{p[2]:.3f}",
                        f"{args.width:.2f}", f"{h:.1f}", f"{pts[i, 0]:.2f}", f"{pts[i, 1]:.2f}"])

    grade = np.diff(zc) / args.step * 100
    min_radius = float(radius.min())
    # Run-off and terrain are clamped automatically; only the road + kerbs can still fold.
    limit = edge
    tight = []  # (distance, radius) of the tightest point in each run of too-tight samples
    run = []
    for i in list(range(len(radius))) + [None]:
        if i is not None and radius[i] < limit:
            run.append(i)
        elif run:
            k = min(run, key=lambda j: radius[j])
            tight.append((round(k * args.step), round(float(radius[k]), 1)))
            run = []
    if tight:
        where = ", ".join(f"{d} m (r={r} m)" for d, r in tight)
        print(f"WARNING: corners tighter than half-width + kerb ({limit:.1f} m), where the inside edge of "
              f"the road will fold over itself: {where}. Usually a kink in the trace - re-trace those "
              f"corners with more evenly spaced points, or increase --smooth-xy.", file=sys.stderr)
    summary = {
        "length_m": round(float(len(pts) * args.step if closed else length), 1),
        "closed_loop": bool(closed),
        "elevation_source": source,
        "elevation_range_m": round(float(zc.max() - zc.min()), 2),
        "max_grade_pct": round(float(np.abs(grade).max()) if len(grade) else 0.0, 2),
        "min_corner_radius_m": round(min_radius, 1),
        "tight_corners": [{"dist_m": d, "radius_m": r} for d, r in tight],
        "flattened": [list(r) for r in args.flatten],
        "origin_bng": [round(float(origin_en[0]), 2), round(float(origin_en[1]), 2)],
        "origin_alt_m": round(float(origin_z), 2),
        "vertices": len(mesh.v),
        "terrain_cells": terrain_cells,
        "objects": len(object_verts),
        "max_object_vertices": max(object_verts.values()),
        "tyre_stacks": tyre_stacks,
        "tyre_wall_collision_m": round(wall_length, 1),
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
        for i in range(0, len(local), int(round(100 / args.step))):
            ax1.plot(local[i, 0], -local[i, 2], "k.", ms=3)
            ax1.annotate(f"{i * args.step:.0f}", (local[i, 0], -local[i, 2]), fontsize=7,
                         xytext=(nrm[i, 0] * 14, nrm[i, 1] * 14), textcoords="offset points",
                         ha="center", va="center", color="0.3")
        if tight:
            ti = [int(d / args.step) for d, _ in tight]
            ax1.plot(local[ti, 0], -local[ti, 2], "o", mfc="none", mec="m", ms=10, label="road folds here")
        ax1.plot(0, 0, "go", label="start/finish (origin)")
        ax1.annotate("", xy=(local[3, 0], -local[3, 2]), xytext=(0, 0), arrowprops={"arrowstyle": "->"})
        ax1.set_aspect("equal")
        ax1.set_title("Plan (m, north up)")
        ax1.legend(loc="best", fontsize=8)
        dist = np.arange(len(zc)) * args.step
        ax2.plot(dist, raw_z, color="0.55", lw=0.8, label="raw DEM / input")
        ax2.plot(dist, zc, label="road surface")
        for a, b in args.flatten:
            spans = [(a, b)] if b >= a else [(a, dist[-1]), (0, b)]  # wrapped range on a loop
            for i, (x0, x1) in enumerate(spans):
                ax2.axvspan(x0, x1, color="orange", alpha=0.25, label="--flatten" if i == 0 else None)
        ax2.legend(loc="best", fontsize=8)
        ax2.grid(alpha=0.3)
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
