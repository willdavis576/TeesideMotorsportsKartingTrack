#!/usr/bin/env python3
"""Save still frames from an onboard/POV video at a fixed interval (no ffmpeg needed).

    pip install opencv-python
    python tools/extract_frames.py lap.mp4                    # one frame per second -> frames/
    python tools/extract_frames.py lap.mp4 --every 0.5 --start 12 --end 75

Each file is named after its timestamp (e.g. t_0063.0s.jpg) so frames can be matched
back to the video. Use --start/--end to keep just one clean lap.
"""
import argparse
import sys
from pathlib import Path

import cv2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--every", type=float, default=1.0, help="seconds between frames (default 1)")
    ap.add_argument("--start", type=float, default=0.0, help="start time in seconds")
    ap.add_argument("--end", type=float, help="end time in seconds (default: end of video)")
    ap.add_argument("--max-width", type=int, default=1280, help="shrink wider frames to this width")
    ap.add_argument("--quality", type=int, default=80, help="JPEG quality 1-100")
    ap.add_argument("-o", "--out-dir", default="frames")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f"could not open {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    end = min(args.end, duration) if args.end else duration

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    saved = 0
    t = args.start
    while t <= end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        if w > args.max_width:
            frame = cv2.resize(frame, (args.max_width, round(h * args.max_width / w)),
                               interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out / f"t_{t:06.1f}s.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
        saved += 1
        t += args.every
    print(f"Saved {saved} frames ({args.start:.1f}-{end:.1f} s of a {duration:.1f} s video) to {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
