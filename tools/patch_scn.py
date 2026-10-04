#!/usr/bin/env python3
"""Set the collision / HAT / render flags in an rFactor 2 .scn file exported by 3DSimED.

Each `Instance=<name> { ... }` block gets the flags for its object type, copied from the
ModDev sample track: road, kerb, verge, run-off and terrain are drivable; the tyre stacks are
visual only; the tyre collision wall is invisible but solid; xfinish/xsector1/xsector2 and
xpitin/xpitout are invisible timing and pit gates. Other settings in each block are kept.
Instances with names this script doesn't recognise (your own scenery) are left alone.

    python tools/patch_scn.py path/to/teesside.scn            # writes teesside.scn, keeps teesside.scn.bak
    python tools/patch_scn.py path/to/teesside.scn --dry-run  # just report what would change
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

DRIVABLE = ("kerbL", "kerbR", "vergeL", "vergeR", "runoffL", "runoffR", "apronL", "apronR", "terrain")
TIMING = ("xfinish", "xsector1", "xsector2")
PITS = ("xpitin", "xpitout")

# Flags copied from the ModDev sample track (Joesville): its race surface is
# "Deformable=True CollTarget=True HATTarget=True", other drivable ground "CollTarget=True HATTarget=True",
# walls "CollTarget=True HATTarget=False", and the timing/pit gates are invisible with a TIMING or
# PITSTOP response.
FLAGS = {
    "road": {"Deformable": "True", "CollTarget": "True", "HATTarget": "True"},
    "drivable": {"CollTarget": "True", "HATTarget": "True"},
    "tyrewall": {"CollTarget": "False", "HATTarget": "False"},
    "tyrewall_collision": {"Render": "False", "CollTarget": "True", "HATTarget": "False"},
    "timing": {"Render": "False", "CollTarget": "True", "HATTarget": "False", "Response": "VEHICLE,TIMING"},
    "pits": {"Render": "False", "CollTarget": "True", "HATTarget": "False", "Response": "VEHICLE,PITSTOP"},
}
# Keys to take out (an earlier version of this script added Response=VEHICLE,TERRAIN, which the sample
# track doesn't use on its surfaces).
REMOVE = {"road": ("Response",), "drivable": ("Response",)}
TILE = re.compile(r"_[ew]\d+_[ns]\d+$")


def kind(name):
    base = TILE.sub("", name)
    if base == "road":
        return "road"
    if base in DRIVABLE:
        return "drivable"
    if base in TIMING:
        return "timing"
    if base in PITS:
        return "pits"
    return base if base in FLAGS else None


def patch_block(body, flags, remove=()):
    """Set key=value pairs inside one instance block, replacing existing ones or adding them,
    and delete the keys in `remove`."""
    trailing = body[len(body.rstrip()):]  # keep the block's original line break / spacing before "}"
    body = body.rstrip()
    for key in remove:
        body = re.sub(rf"[ \t]*(?<![A-Za-z]){key}\s*=\s*[^\s}}]+", "", body)
    for key, value in flags.items():
        pattern = re.compile(rf"(?<![A-Za-z]){key}\s*=\s*[^\s}}]+")
        if pattern.search(body):
            body = pattern.sub(f"{key}={value}", body)
        else:
            body += f" {key}={value}"
    return body + trailing


def patch(text):
    out, pos, changes = [], 0, {}
    for m in re.finditer(r"Instance\s*=\s*([^\s{]+)\s*\{", text):
        if m.start() < pos:
            continue  # inside a block we already handled
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        if depth:
            raise ValueError(f"unclosed block for instance {m.group(1)}")
        name, body = m.group(1), text[m.end():i - 1]
        k = kind(name)
        out.append(text[pos:m.end()])
        if k:
            new = patch_block(body, FLAGS[k], REMOVE.get(k, ()))
            if new != body:
                changes[k] = changes.get(k, 0) + 1
            body = new
        out.append(body + "}")
        pos = i
    out.append(text[pos:])
    return "".join(out), changes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scn")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.scn)
    text = path.read_text(errors="replace")
    new, changes = patch(text)
    total = sum(changes.values())
    found = len(re.findall(r"Instance\s*=", text))
    print(f"{found} instances in {path.name}; {total} updated: "
          + (", ".join(f"{n} {k}" for k, n in sorted(changes.items())) or "nothing to change"))
    if total and not args.dry_run:
        shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
        path.write_text(new)
        print(f"Saved. Original kept as {path.name}.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
