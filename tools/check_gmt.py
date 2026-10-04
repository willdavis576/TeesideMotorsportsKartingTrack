#!/usr/bin/env python3
"""Check exported rFactor 2 GMT files against the OBJ they came from.

Each GMT starts with its bounding box (8 corner points). This compares those boxes with the
matching objects in track.obj and reports the scale and axis conversion, so a units mistake
(e.g. everything 100x too big after an FBX round trip) is caught before loading the track.
It also lists the texture files each GMT refers to.

    python tools/check_gmt.py GMT                      # compares with build/track.obj
    python tools/check_gmt.py GMT --obj build/track.obj
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np


def gmt_bbox(path):
    """(min, max) corner of the bounding box stored at the start of a GMT file."""
    data = Path(path).read_bytes()
    corners = np.frombuffer(data[8:8 + 96], dtype="<f4").reshape(8, 3)
    return corners.min(axis=0), corners.max(axis=0)


def gmt_textures(path):
    text = Path(path).read_bytes().decode("latin-1")
    return sorted(set(m.upper() for m in re.findall(r"[A-Za-z0-9_\-]+\.(?:dds|DDS|png|PNG|tga|TGA)", text)))


def obj_bboxes(path):
    """{object name (lower case): (min, max)} for every object in an OBJ file."""
    verts, members, cur = [], {}, None
    for line in open(path):
        if line.startswith("v "):
            verts.append([float(c) for c in line.split()[1:4]])
        elif line.startswith("o "):
            cur = line.split()[1].lower()
        elif line.startswith("f ") and cur:
            members.setdefault(cur, set()).update(int(p.split("/")[0]) - 1 for p in line.split()[1:])
    verts = np.array(verts)
    return {name: (verts[list(idx)].min(axis=0), verts[list(idx)].max(axis=0)) for name, idx in members.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gmt_dir")
    ap.add_argument("--obj", default="build/track.obj")
    args = ap.parse_args()

    gmts = sorted(Path(args.gmt_dir).glob("*.gmt"))
    if not gmts:
        sys.exit(f"no .gmt files in {args.gmt_dir}")
    objs = obj_bboxes(args.obj) if Path(args.obj).exists() else {}

    scales, flips, textures, unmatched = [], [], {}, []
    for g in gmts:
        gmin, gmax = gmt_bbox(g)
        for t in gmt_textures(g):
            textures[t] = textures.get(t, 0) + 1
        o = objs.get(g.stem.lower())
        if o is None:
            unmatched.append(g.name)
            continue
        omin, omax = o
        osize, gsize = omax - omin, gmax - gmin
        ok = osize > 0.5  # skip near-flat axes when working out the scale
        scales.append(np.median(gsize[ok] / osize[ok]))
        s = scales[-1]
        # Which sign maps the OBJ box onto the GMT box on each axis?
        flips.append([int(np.sign(np.round(
            (gmin[i] + gmax[i]) / 2 / ((omin[i] + omax[i]) / 2 * s)))) if abs(omin[i] + omax[i]) > 1 else 0
            for i in range(3)])

    print(f"{len(gmts)} GMT files, {len(gmts) - len(unmatched)} matched to objects in {args.obj}")
    status = 0
    if scales:
        s = float(np.median(scales))
        spread = float(np.max(np.abs(np.array(scales) / s - 1)))
        axes = np.array(flips)
        sign = [int(np.sign(np.sum(axes[:, i]))) or 1 for i in range(3)]
        print(f"Scale GMT/OBJ: {s:.4g} (varies by {spread:.1%} between objects)")
        print(f"Axis mapping: GMT = ({'+' if sign[0] > 0 else '-'}x, {'+' if sign[1] > 0 else '-'}y, "
              f"{'+' if sign[2] > 0 else '-'}z) of the OBJ")
        if abs(s - 1) > 0.02:
            status = 1
            hint = (" Re-export the FBX from Blender with Scale = 0.01." if abs(s - 100) < 2 else
                    " Re-export with Scale = 100." if abs(s - 0.01) < 0.001 else "")
            print(f"PROBLEM: the GMTs are {s:.4g}x the size of the model (should be 1).{hint}")
        else:
            print("OK: sizes match (metres).")
    if unmatched:
        print(f"Not in the OBJ (your own scenery, or renamed): {', '.join(unmatched[:10])}"
              + (" ..." if len(unmatched) > 10 else ""))
    print("Textures referenced: " + ", ".join(f"{t} ({n})" for t, n in sorted(textures.items())))
    return status


if __name__ == "__main__":
    sys.exit(main())
