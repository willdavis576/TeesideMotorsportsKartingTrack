#!/usr/bin/env python3
"""Match onboard-video frames to positions on the track.

A simple lap simulation (grip-limited corners, acceleration and braking limits) is
tuned so its lap time matches the real one, then used to turn video time into lap
distance. Accuracy is typically within a few tens of metres - enough to tell which
corner or straight a frame shows.

    python tools/video_sync.py --lap-time 72.71 --lap-start 7.5
    python tools/video_sync.py --lap-time 72.71 --lap-start 7.5 --frames frames --every 1

Outputs (in --out-dir, default build/):
  video_sync.csv  video time, lap time, distance, speed and local x/z for each frame
  video_map.png   track map labelled with the video time at each frame
It also prints the lateral grip the simulation needed; ~2-2.7 g is normal for a sprint kart,
so a value far outside that suggests the lap length or lap time is wrong.
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np


def load_centreline(path):
    rows = list(csv.DictReader(open(path)))
    d = np.array([float(r["dist_m"]) for r in rows])
    x = np.array([float(r["x"]) for r in rows])
    z = np.array([float(r["z"]) for r in rows])
    heading = np.radians([float(r["heading_deg"]) for r in rows])
    return d, x, z, heading


def corner_radius(heading, step, window=9):
    dh = np.diff(heading, append=heading[0])
    dh = (dh + np.pi) % (2 * np.pi) - np.pi
    pad = window // 2
    dh = np.convolve(np.concatenate([dh[-pad:], dh, dh[:pad]]), np.ones(window) / window, "valid")
    return step / np.maximum(np.abs(dh), 1e-6)


def simulate(radius, step, grip, vmax, accel, brake):
    """Speed at each sample of a closed lap, and cumulative time to reach it."""
    n = len(radius)
    v = np.minimum(np.sqrt(grip * radius), vmax)
    for _ in range(2):  # two passes so the limits carry across the start/finish line
        for i in range(2 * n):
            a, b = i % n, (i + 1) % n
            drag = 1 - v[a] ** 2 / vmax ** 2  # acceleration fades towards top speed
            v[b] = min(v[b], np.sqrt(v[a] ** 2 + 2 * accel * drag * step))
        for i in range(2 * n, 0, -1):
            a, b = i % n, (i - 1) % n
            v[b] = min(v[b], np.sqrt(v[a] ** 2 + 2 * brake * step))
    t = np.concatenate([[0], np.cumsum(step / v)])
    return v, t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--centreline", default="build/centreline.csv")
    ap.add_argument("--lap-time", type=float, required=True, help="real lap time in seconds")
    ap.add_argument("--lap-start", type=float, required=True,
                    help="video time (s) when the kart crosses the start/finish line")
    ap.add_argument("--video-end", type=float, help="last video time to map (default: one lap)")
    ap.add_argument("--every", type=float, default=1.0, help="seconds between mapped frames")
    ap.add_argument("--vmax", type=float, default=110.0, help="top speed, km/h")
    ap.add_argument("--accel", type=float, default=4.5, help="peak acceleration, m/s^2")
    ap.add_argument("--brake", type=float, default=12.0, help="braking, m/s^2")
    ap.add_argument("--out-dir", default="build")
    args = ap.parse_args()

    d, x, z, heading = load_centreline(args.centreline)
    step = d[1] - d[0]
    radius = corner_radius(heading, step)
    vmax = args.vmax / 3.6

    lo, hi = 2.0, 60.0  # bisect the lateral grip until the simulated lap matches
    for _ in range(50):
        grip = (lo + hi) / 2
        v, t = simulate(radius, step, grip, vmax, args.accel, args.brake)
        lo, hi = (grip, hi) if t[-1] > args.lap_time else (lo, grip)
    v, t = simulate(radius, step, grip, vmax, args.accel, args.brake)
    if abs(t[-1] - args.lap_time) > 0.5:
        sys.exit(f"could not match a {args.lap_time:.2f} s lap (closest {t[-1]:.2f} s); "
                 f"try a different --vmax")
    print(f"Lap matched with {grip / 9.81:.2f} g lateral grip; "
          f"speed {v.min() * 3.6:.0f}-{v.max() * 3.6:.0f} km/h")

    lap_len = len(d) * step
    end = args.video_end if args.video_end is not None else args.lap_start + args.lap_time
    times = np.arange(np.ceil(args.lap_start / args.every) * args.every, end + 1e-9, args.every)
    lap_t = (times - args.lap_start) % args.lap_time
    dist = np.interp(lap_t, t, np.arange(len(t)) * step) % lap_len
    idx = np.clip(np.round(dist / step).astype(int), 0, len(d) - 1)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "video_sync.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["video_s", "lap_s", "dist_m", "speed_kmh", "x", "z"])
        for vt, lt, dd, i in zip(times, lap_t, dist, idx):
            w.writerow([f"{vt:.1f}", f"{lt:.1f}", f"{dd:.0f}", f"{v[i] * 3.6:.0f}", f"{x[i]:.1f}", f"{z[i]:.1f}"])

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, (ax, ax2) = plt.subplots(2, 1, figsize=(13, 10), gridspec_kw={"height_ratios": [2.2, 1]})
        sc = ax.scatter(x, -z, c=v * 3.6, s=4, cmap="viridis")
        fig.colorbar(sc, ax=ax, shrink=0.8, label="simulated speed (km/h)")
        for vt, i in zip(times, idx):
            ax.annotate(f"{vt:.0f}", (x[i], -z[i]), fontsize=6.5, ha="center", va="center",
                        bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "0.6", "lw": 0.4})
        ax.set_aspect("equal")
        ax.set_title("Video time (s) at each point of the lap (north up, metres)")
        ax2.plot(np.arange(len(v)) * step, v * 3.6)
        ax2.set_xlabel("lap distance (m)")
        ax2.set_ylabel("km/h")
        ax2.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out / "video_map.png", dpi=100)
    except ImportError:
        pass
    print(f"Wrote {out / 'video_sync.csv'} and {out / 'video_map.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
