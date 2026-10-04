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
| `--width` | 8 | track width (m). Measure it in Google Earth with the ruler tool. |
| `--kerb` / `--kerb-height` | 0.6 / 0.04 | kerb strip each side (0 disables) |
| `--runoff` | 4 | grass/run-off each side, blended from road height down to the terrain |
| `--apron` | 25 | surrounding terrain strip from the DEM |
| `--smooth-xy` | 4 | removes wobble from hand-traced paths |
| `--smooth-z` | 15 | removes LIDAR noise (parked cars, etc.) from the road surface |
| `--reverse` | off | flip the driving direction |
| `--start-offset` | 0 | move the start/finish line (and the origin) along the lap |

Output in `build/`:
- `track.obj` / `track.mtl` — separate objects for `road`, `kerbL/R`, `runoffL/R` and `apronL/R`.
  Units are metres, Y is up, and the origin is at the start/finish line. It imports into Blender
  with the default OBJ settings.
- `centreline.csv` — distance, local XYZ, heading and British National Grid coordinates for every metre.
- `summary.json` — lap length, elevation range, max gradient, tightest corner radius.
- `preview.png` — plan view and elevation profile.

Check `summary.json` against the real circuit's published lap length. If you get a warning about a corner
radius, a hairpin is tighter than half the track width. Fix it with more `--smooth-xy`, a smaller `--runoff`,
or by hand in Blender.

Run the tests with `python -m pytest tests`.

## 4. Detail it in Blender

The generated mesh is the base. The rest is normal track modelling:
- Real textures (tarmac, kerbs, grass). Material names are already split by surface type.
- Tyre walls, barriers, fencing, the pit/paddock area, buildings and trees. Use your own photos, and
  Google Earth or Street View for reference.
- A start/finish gantry, marshal posts and timing line markings.
- Keep the road as one clean, continuous mesh. rF2 physics reads it directly, so seams and bumps can be felt.

## 5. Get it into rFactor 2

You need the **rFactor 2 ModDev** tool (free with rF2 on Steam). Roughly:

1. **Export to GMT.** rF2 uses its own gMotor `.gmt` mesh format. Studio 397's official exporter
   is a 3ds Max plugin. Blender users usually either go through 3ds Max via FBX or use a
   community Blender exporter. Check the Studio 397 forums for what currently works with your Blender version.
2. **Create the track files** in a ModDev track folder:
   - `.scn`: scene file listing every GMT, with collision/HAT flags on drivable surfaces
   - `.gdb`: track info (name, location, length, lat/long, pit speed, etc.)
   - `.tdf`: maps material names (road, kerb, grass…) to surface physics and sounds
   - `.cam`: TV cameras
   Copy these from the sample track that ships with ModDev and edit them. That is the most
   reliable template.
3. **Run the track in ModDev dev mode** to generate and edit the **AIW**: drive laps to record the
   fast path, then set the start/finish, sector lines, pit lane, pit boxes, garages and grid spots in the AIW editor.
4. **Package** with ModMgr into `.mas` files and an installable `.rfcmp`.

Test with an rF2 kart mod. Karts are very sensitive to bumps and track width, so it's worth
taking a lap with a real kart's dimensions in mind before spending time on scenery.

## Licensing and permission

- EA LIDAR and OSM data are open (OGL / ODbL). Credit them if you release the track.
- Don't redistribute Google Earth imagery as textures. Tracing the layout for reference is fine.
- Ask the circuit for permission before releasing publicly. Most venues are happy to agree,
  and they may give you a CAD plan or drone survey, which beats any of the data above.
