# Onboard video notes

Source: POV lap video (YouTube `ZO2XAajfucg`), frames in `frames/` at 1 per second.

## Timing and how it was matched

- The kart crosses the start/finish line between 7 s and 8 s (the gantry is visible on the left at 7 s).
- The Alfano dash reads **1:12.71** for the lap, and the scenery repeats about 73 s later (frames 81–83 ≈ 8–10).
- `tools/video_sync.py --lap-time 72.71 --lap-start 7.5` gives each frame a lap distance. To match that
  lap time on the traced 1,629 m layout, the simulation needs 2.5 g of lateral grip. That's normal for a fast
  sprint kart, so the traced length and the lap time agree.
- The simulation's slowest corners (+6, +19–24, +60–62, +64, +70 s into the lap) fall where the frames
  show hairpins (13, 26–28, 66–68, 72, 77 s). So **the trace starts at the real start/finish line and
  runs in the racing direction**.
- Distances below are from that simulation and are good to roughly ±25 m (about ±1 s of video).

## What each part of the lap looks like

"Left" and "right" are as seen by the driver.

| Video (s) | Lap distance (m) | What's there |
|---|---|---|
| 7 | 0 | Start/finish gantry over the track on the left |
| 8–12 | 13–105 | Main straight heading west. Paddock building and blue gazebos on the left behind red/white plastic barriers. Red/white kerb on the left at ~40 m. White edge line on the right |
| 13 | ~130 | Into the left-hander at ~150 m: gravel trap and red-painted tyre stacks on the left, red/white kerb |
| 15–16 | 170–195 | Red/white kerb on the right on the exit |
| 17–20 | 220–300 | Down the east side of the "V": a tall grass bank on the right. The LIDAR puts the track about 4 m below the ground inside the V, which matches |
| 20–21 | 300–320 | Hairpin at the tip of the V, low tyre wall |
| 21–23 | 320–360 | Back up the west side, tyre wall on the left |
| 24–25 | 380–410 | Climbing, bank on the right, red tyre stack on the right at ~410 m |
| 26–28 | 430–470 | Tight chicane/hairpin, red tyre stacks on the left at ~450 m |
| 29–32 | 490–545 | The climb up the hill, red/white kerbs on the right, then the top-left hairpin |
| 33–35 | 565–610 | Tyre wall on the left, red/white kerbs on the left |
| 36–39 | 635–720 | Top straight heading east. Trees and **red/white water-filled plastic barriers on the right**, low tyre wall on the left |
| 40–42 | 750–805 | Long, flat, patched straight. Industrial building in the distance on the right |
| 43–48 | 830–925 | Twisty infield section: red/white kerbs at most apexes, tyre walls on the left at ~905–925 m |
| 49–50 | 945–965 | Short straight towards the buildings |
| 51–54 | 980–1035 | Hairpins with red/white kerbs on the right |
| 56–58 | 1070–1115 | Sponsor banners on the left |
| 59–61 | 1140–1195 | Straight east, tyre wall on the left |
| 62–65 | 1220–1295 | Sweeping right around the east end, tyre wall on the outside |
| 66–68 | 1320–1370 | Hairpin, wide red/white kerbs on the right |
| 72 | ~1445 | Tight left-hander with a black tyre wall on the inside (left) |
| 73–76 | 1465–1530 | Straight with tyre walls both sides |
| 77–78 | 1550–1575 | Hairpin, gazebo on the left |
| 79 | ~1600 | Race control tower on the left |
| 80 | ~1625 | Painted grid boxes (white diagonal lines) just before the line |

## Changes made from this

- **Kerbs only through corners.** The video shows grass, not kerbs, along the straights. `build_track.py` now
  puts kerbs through corners tighter than `--kerb-corners` (40 m) and a grass verge elsewhere.

## Left for Blender (not generated)

- Start/finish gantry (0 m, left) and race control tower (~1600 m, left)
- Grid boxes painted before the line
- Paddock building, gazebos and red/white plastic barriers along the main straight (left)
- Red/white water-filled barriers along the top straight (right, ~635–720 m)
- Gravel trap at the ~150 m left-hander
- Red-painted tyre stacks at the apexes of ~130, ~410 and ~450 m
- Sponsor banners at ~1070–1115 m
- Painted white edge lines on the straights
