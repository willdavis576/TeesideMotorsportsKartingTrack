# Teesside Karting for rFactor 2

Tools and a workflow for building the Teesside outdoor kart circuit (Teesside Autodrome,
Middlesbrough) as an rFactor 2 track, using real-world data instead of building it by eye.

```
 layout (OSM / Google Earth / GPS)  ─┐
                                     ├─> tools/build_track.py ─> track.obj ─> Blender ─> rF2 ModDev ─> .rfcmp
 elevation (EA 1 m LIDAR DTM)       ─┘
```

## 1. Get the layout (centreline)

Pick whichever is most accurate. You can try all three and compare the `preview.png` output.

**A. OpenStreetMap (quickest)**
```bash
pip install -r requirements.txt
python tools/fetch_osm.py                      # searches a Teesside bounding box
```
This lists every raceway/karting way it finds with its OSM id and length. Choose the kart circuit
and pass `--way-id` to the build step. OSM kart tracks are often hand-traced, so check them against imagery.

**B. Google Earth Pro (most control)**
1. Open Google Earth Pro (desktop) and find the circuit.
2. Use *View → Historical Imagery* to pick the sharpest, most recent image.
3. *Add → Path*, then click points along the **centre of the track**, roughly every 3–5 m
   (closer together in hairpins). Finish back at your first point.
4. Right-click the path → *Save Place As…* → **.kml** → `data/teesside_karting.kml`.

Google Earth altitudes come from a coarse terrain model that is too rough for a kart
track, so use it for the plan shape only and take elevation from LIDAR (step 2).

**C. GPS log from a real session**
A GPX export from a lap timer or phone app (AiM, Alfano, RaceBox, RaceChrono…) works too.
The racing line isn't the centreline, though, so mainly use it to check A or B.

## 2. Get elevation: Environment Agency LIDAR (recommended)

England has free 1 m-resolution LIDAR under the Open Government Licence. It is far better than
Google Earth or SRTM data.

1. Go to the DEFRA Survey Data Download portal: <https://environment.data.gov.uk/survey>
2. Draw a box around the circuit and choose **LIDAR Composite DTM, 1 m** (*DTM* is bare ground.
   Don't use *DSM*, which includes trees and buildings.)
3. Download the tiles. If there are several, merge them:
   `gdal_merge.py -o data/lidar_dtm.tif tile1.tif tile2.tif` (or *Raster → Merge* in QGIS).

Any GeoTIFF DEM works. The script reprojects from whatever CRS it uses.

## 3. Build the base mesh

```bash
# from Google Earth
python tools/build_track.py data/teesside_karting.kml --dem data/lidar_dtm.tif --out-dir build

# from OSM
python tools/build_track.py data/osm_raceways.geojson --way-id 123456789 --dem data/lidar_dtm.tif
```

Useful options:

| option | default | purpose |
|---|---|---|
| `--width` | 10 | track width (m). Measure it in Google Earth with the ruler tool. |
| `--kerb` / `--kerb-height` | 0.6 / 0.04 | kerb strip each side (0 disables) |
| `--kerb-corners` | 40 | kerbs only through corners tighter than this radius (m), grass verge elsewhere. 0 = kerbs all the way round |
| `--runoff` | 4 | grass/run-off each side, blended from road height down to the terrain |
| `--terrain` | 40 | with `--dem`: LIDAR ground mesh reaching this far beyond the track (0 disables). It sits just under the road and run-off, so it never pokes through |
| `--terrain-res` | 2 | terrain grid spacing (m). 1 matches the LIDAR but is 4× the polygons |
| `--apron` | 0 | old-style terrain strip along each side. Superseded by `--terrain`; it overlaps where track sections run close together |
| `--smooth-xy` | 4 | removes wobble from hand-traced paths |
| `--smooth-z` | 15 | removes LIDAR noise (parked cars, etc.) from the road surface |
| `--despike` | 11 | running-median window (m) that removes short bumps such as tyre walls or parked vehicles in the LIDAR |
| `--flatten START:END` | – | ignore the DEM between two lap distances and ramp straight across. Can be repeated, and can wrap past the start line (e.g. `1580:40`) |
| `--tyre-corners` | 30 | tyre walls on the outside of every corner tighter than this radius (m). 0 disables |
| `--tyre-extend` | 10 | carry each tyre wall this far before and after the corner (m) |
| `--tyre-gap` | 0.5 | gap between the edge of the run-off and the tyres (m) |
| `--reverse` | off | flip the driving direction |
| `--start-offset` | 0 | move the start/finish line (and the origin) along the lap |

Output in `build/`:
- `track.obj` / `track.mtl` — separate objects for `road`, `kerbL/R`, `runoffL/R`, `terrain` (the LIDAR ground grid),
  `tyrewall` (stacks of three tyres on the outside of corners) and `tyrewall_collision` (a simple 1 m wall along the
  track-facing side of the tyres). In rF2 the collision wall should be invisible but collidable, so the karts hit a
  clean surface instead of 12-sided cylinders. Tyres are left out wherever another part of the track runs close by.
  Also five invisible gates rF2 requires: `xfinish` (start/finish line), `xsector1`/`xsector2` (sector lines,
  default thirds of the lap, `--sectors`) and `xpitin`/`xpitout` (pit entry/exit, `--pits`). These are never split into tiles.
  Units are metres, Y is up, and the origin is at the start/finish line. It imports into Blender
  with the default OBJ settings.
- `textures/` — simple starter textures (asphalt, red/white kerb, grass, terrain) matching the UV layout. Existing files are never overwritten, so you can drop real textures in with the same names.
- `scene_instances.txt` — every object with its recommended rF2 `.scn` flags (collision, HAT, render).
- `centreline.csv` — distance, local XYZ, heading and British National Grid coordinates for every metre.
- `summary.json` — lap length, elevation range, max gradient, tightest corner radius.
- `preview.png` — plan view labelled every 100 m (too-tight corners circled), and the elevation profile showing raw DEM vs. final road surface. Use the distance labels to match a bump in the profile to a spot on the track, then check it in Google Earth.

Check `summary.json` against the real circuit's published lap length. Run-off and apron automatically narrow on the
inside of tight corners. If you get a warning that the *road* folds, the centreline has a kink tighter than half the
track width: re-trace that corner with more, evenly spaced points or increase `--smooth-xy`.

Run the tests with `python -m pytest tests`.

## Onboard video (optional)

Stills from a POV lap are useful for placing tyre walls, kerbs, signs and buildings. Download the video
(e.g. with `yt-dlp`), then save a frame every second. No ffmpeg is needed:
```bash
yt-dlp -f "bv*[ext=mp4][height<=720]" -o lap.mp4 "<video url>"
python tools/extract_frames.py lap.mp4 --every 1 --start 10 --end 75   # just one clean lap
```
Frames are saved to `frames/`, named by timestamp. To find where each frame is on the track, give the real
lap time (e.g. from the dash) and the video time at which the kart crosses the line:
```bash
python tools/video_sync.py --lap-time 72.71 --lap-start 7.5
```
This writes `build/video_sync.csv` (video time → lap distance) and `build/video_map.png` (map labelled with
video times). Notes from the current video are in [`docs/video_notes.md`](docs/video_notes.md).

## 4. Detail it in Blender

The generated mesh is the base. The rest is normal track modelling:
- Real textures (tarmac, kerbs, grass). Material names are already split by surface type.
- Tyre walls, barriers, fencing, the pit/paddock area, buildings and trees. Use your own photos, and
  Google Earth or Street View for reference.
- A start/finish gantry, marshal posts and timing line markings.
- Keep the road as one clean, continuous mesh. rF2 physics reads it directly, so seams and bumps can be felt.

## 5. Get it into rFactor 2

`track.obj` is already split into 100 m tiles (`--tile`), named `<object>_<col>_<row>`, so each piece
stays small (the largest Teesside piece is ~17k vertices). Game engines cull and load small pieces much better.

Tools:
- **rFactor 2 ModDev**: free with rF2 on Steam. Runs your track in dev mode, has the AIW editor, and ModMgr packages the mod.
- **3DSimED3** (Mesh Development, paid): converts OBJ/FBX to rF2's `.gmt` mesh format, sets the rF2 shaders and
  writes the `.scn`. This is the route current Blender-only tutorials use; Studio 397's own exporter is a 3ds Max plugin.
- **gJED**: viewer/editor for existing `.scn`/`.gmt` files. Useful for checking the result.

Steps:
1. In Blender, finish the scenery and export to OBJ or FBX (keep one object per tile).
2. In 3DSimED (step-by-step: [`docs/rf2_export_guide.md`](docs/rf2_export_guide.md)), import the model, assign rF2 shaders to the materials (road, kerb, grass, terrain, tyre), export the
   GMTs and the `.scn`. Mark the road, kerb, verge, run-off and terrain objects as drivable/collidable, mark
   `tyrewall_collision` as collidable but not rendered, and mark the tyre stacks as visual only.
3. Run `python tools/make_track_folder.py --out "<rF2>/ModDev/Locations"` (details: [`docs/rf2_export_guide.md`](docs/rf2_export_guide.md) section D). It puts the GMTs, textures and `.scn` in a track folder under ModDev, with `.gdb` (track info), `.tdf` (surface
   physics, keyed on material names) and `.cam` copied from an existing unencrypted track and edited.
4. Load it in ModDev. In the AIW editor, drive laps to record the racing line, then set the start/finish, sectors,
   pit lane, garages and grid.
5. Package it with ModMgr into `.mas` files and an installable `.rfcmp`.

The Teesside lap is 1:12.7 in a fast kart (see `docs/video_notes.md`). That's a useful target for checking the
grip and surface settings.

## Licensing and permission

- EA LIDAR and OSM data are open (OGL / ODbL). Credit them if you release the track.
- Don't redistribute Google Earth imagery as textures. Tracing the layout for reference is fine.
- Ask the circuit for permission before releasing publicly. Most venues are happy to agree,
  and they may give you a CAD plan or drone survey, which beats any of the data above.
