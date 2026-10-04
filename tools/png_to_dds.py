#!/usr/bin/env python3
"""Convert PNG/JPG/TGA textures to .dds for rFactor 2, with a full mipmap chain.

Writes uncompressed 32-bit BGRA DDS files (any DirectX game can load them), including every
mipmap level. Mipmaps are the smaller copies the engine uses at a distance; without them
asphalt and grass shimmer. Textures should be power-of-two sizes (256, 512, 1024, ...).

    python tools/png_to_dds.py build/textures              # every image in the folder
    python tools/png_to_dds.py my_texture.png -o out_dir
"""
import argparse
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# DDS header flags (from the DirectX DDS file format reference)
DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PITCH = 0x1, 0x2, 0x4, 0x8
DDSD_PIXELFORMAT, DDSD_MIPMAPCOUNT = 0x1000, 0x20000
DDPF_ALPHAPIXELS, DDPF_RGB = 0x1, 0x40
DDSCAPS_COMPLEX, DDSCAPS_TEXTURE, DDSCAPS_MIPMAP = 0x8, 0x1000, 0x400000


def mip_chain(rgba):
    """Full mipmap chain down to 1x1, each level a 2x2 box-filtered copy of the last."""
    levels = [rgba]
    img = rgba.astype(np.float32)
    while img.shape[0] > 1 or img.shape[1] > 1:
        h, w = max(img.shape[0] // 2, 1), max(img.shape[1] // 2, 1)
        img = img[:h * 2 or 1, :w * 2 or 1]
        img = img.reshape(h, img.shape[0] // h, w, img.shape[1] // w, 4).mean(axis=(1, 3))
        levels.append(np.round(img).astype(np.uint8))
    return levels


def write_dds(rgba, path):
    h, w = rgba.shape[:2]
    levels = mip_chain(rgba)
    header = struct.pack(
        "<4s7I44x" "2I4s5I" "4I4x",
        b"DDS ", 124,
        DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PITCH | DDSD_PIXELFORMAT | DDSD_MIPMAPCOUNT,
        h, w, w * 4, 0, len(levels),
        # pixel format: 32-bit, BGRA byte order
        32, DDPF_RGB | DDPF_ALPHAPIXELS, b"\0\0\0\0", 32,
        0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000,
        DDSCAPS_COMPLEX | DDSCAPS_TEXTURE | DDSCAPS_MIPMAP, 0, 0, 0,
    )
    assert len(header) == 128
    with open(path, "wb") as f:
        f.write(header)
        for level in levels:
            f.write(level[..., [2, 1, 0, 3]].tobytes())  # RGBA -> BGRA
    return len(levels)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="image files or folders")
    ap.add_argument("-o", "--out-dir", help="where to write .dds files (default: next to each image)")
    args = ap.parse_args()

    files = []
    for p in map(Path, args.inputs):
        files += sorted(q for q in p.iterdir() if q.suffix.lower() in (".png", ".jpg", ".jpeg", ".tga")) \
            if p.is_dir() else [p]
    if not files:
        sys.exit("no images found")
    for src in files:
        rgba = np.asarray(Image.open(src).convert("RGBA"))
        h, w = rgba.shape[:2]
        if w & (w - 1) or h & (h - 1):
            print(f"WARNING: {src.name} is {w}x{h}; rF2 textures should be power-of-two sizes", file=sys.stderr)
        dst = (Path(args.out_dir) if args.out_dir else src.parent) / (src.stem + ".dds")
        dst.parent.mkdir(parents=True, exist_ok=True)
        n = write_dds(rgba, dst)
        print(f"{src.name} -> {dst} ({w}x{h}, {n} mip levels)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
