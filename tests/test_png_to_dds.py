"""png_to_dds.py writes valid DDS files: correct pixels, full mip chain, right file size."""
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from png_to_dds import write_dds  # noqa: E402


def test_round_trip(tmp_path):
    rng = np.random.default_rng(0)
    rgba = rng.integers(0, 256, (64, 128, 4), dtype=np.uint8)
    path = tmp_path / "t.dds"
    levels = write_dds(rgba, path)
    assert levels == 8  # 128 -> 64 -> ... -> 1

    data = path.read_bytes()
    magic, size, flags, h, w, pitch, depth, mips = struct.unpack_from("<4s7I", data)
    assert (magic, size, h, w, pitch, mips) == (b"DDS ", 124, 64, 128, 512, 8)
    expected = 128 + sum(max(64 >> i, 1) * max(128 >> i, 1) * 4 for i in range(8))
    assert len(data) == expected

    # An independent reader (Pillow) decodes the top level to the original pixels.
    back = np.asarray(Image.open(path).convert("RGBA"))
    assert np.array_equal(back, rgba)


def test_mips_are_averages(tmp_path):
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[0, 0] = [200, 100, 0, 255]
    rgba[1, 1] = [0, 100, 200, 255]
    path = tmp_path / "t.dds"
    assert write_dds(rgba, path) == 2
    last = path.read_bytes()[-4:]  # the 1x1 level, BGRA: mean of all four pixels (two are transparent black)
    assert list(last) == [50, 50, 50, 128]
