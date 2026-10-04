# Step 2: Blender → 3DSimED → rFactor 2 GMT

This takes the Blender scene to rF2's `.gmt` meshes and a `.scn` scene file.

The rF2 facts here (naming, collision flags, `.scn` syntax) come from Studio 397's documentation and
modding guides; sources are at the bottom. The exact 3DSimED menu names can change between versions, so
where this guide names a menu, check it against the version you have.

## What the build already does for rF2

| Need | Where it comes from |
|---|---|
| Small meshes the engine can cull | `track.obj` is split into 100 m tiles, e.g. `road_e0_s1` (tile 0 east, 1 south). The largest Teesside piece has ~17k vertices. Names use only letters, digits and `_` |
| Surface physics | Material names start with rF2 terrain prefixes: `road_asphalt` (tarmac), `rmbl_kerb` (rumble strip), `gras_verge` (grass), `grxs_terrain` (rough grass). rF2 matches the **start of the material name** against the prefixes in the track's `.tdf` |
| Collision setup | `build/scene_instances.txt` lists every piece with the recommended `.scn` flags |
| Units and axes | Metres, Y up, origin on the start/finish line |

## A. Export from Blender

1. Finish your scenery. Keep each tile as its own object, and don't join the road with scenery.
2. Give any new materials rF2 prefixes too. For example, a gravel trap material should start with `grvl`;
   buildings and barriers can be named freely, because they aren't driven on.
3. **File → Export → FBX (.fbx)**:
   - *Limit to*: everything you want in the track (or *Selected Objects*)
   - *Object Types*: **Mesh** only (leave out the camera and light)
   - *Scale*: **1.00**, *Apply Scalings*: **FBX Units Scale**
   - *Forward*: **-Z Forward**, *Up*: **Y Up** (Blender's defaults; rF2 is Y-up)
   - *Geometry*: tick **Triangulate Faces** (the tyre-stack tops are 12-sided polygons), **Apply Modifiers**
   - *Path Mode*: **Copy**, with the embed button off, so the textures are copied next to the FBX
4. Save it as `export/teesside.fbx` (the folder is ignored by git, like `build/`).

## B. Convert in 3DSimED

1. **Open/import the FBX.** When asked how to name objects, choose **mesh names**, so the tile names carry
   through to the GMT files.
2. **Check scale and orientation.** The road is 10 m wide and the start/finish line is at the origin. If the
   track is lying on its side or 100× too big, re-export from Blender with the settings above.
3. **Assign a simple rF2 shader to each material** with its diffuse texture, keeping the material names exactly as
   they are (the surface physics depends on them). The proper road/kerb shaders come later in ModDev; see
   "Shaders: the two-pass approach" below. rF2 tracks normally use `.dds` textures, so convert the PNGs if your
   version doesn't do it for you.
4. **Set the instance flags** for each object. Open `build/scene_instances.txt` alongside; it lists the
   recommended flags for every piece:

   | Objects | Collide | HAT | Render | Why |
   |---|---|---|---|---|
   | `road_*`, `kerbL/R_*`, `vergeL/R_*`, `runoffL/R_*`, `terrain_*` | ✔ | ✔ | ✔ | Drivable: karts touch it and rest on it |
   | `tyrewall_collision_*` | ✔ | ✘ | ✘ | Invisible wall the karts bump into |
   | `tyrewall_*` | ✘ | ✘ | ✔ | Visual only. 2,000+ cylinders would be expensive and lumpy to collide with |
   | Buildings and other scenery | ✘ | ✘ | ✔ | Unless karts can hit them |

   *HAT* (height above terrain) is what the karts' wheels sit on, so every drivable surface needs it.
5. **Export to rFactor 2 GMT** into a `GMT` folder, and export or save the `.scn`. If you can't find
   the Collide/HAT settings in 3DSimED, skip step 4 and use step 6.
6. **Set the flags automatically.** If 3DSimED didn't set them, run
   ```bash
   python tools/patch_scn.py path/to/teesside.scn
   ```
   It sets Collide/HAT/Render on every road, kerb, verge, run-off, terrain and tyre piece. It keeps every other
   setting, leaves objects it doesn't recognise (your own scenery) alone, and saves the original as `.scn.bak`.
   Add `--dry-run` to see what it would change first.
7. **Compare the `.scn`** with `scene_instances.txt`. Each drivable instance should look like
   ```
   Instance=road_e0_s1 { MeshFile=road_e0_s1.gmt CollTarget=True HATTarget=True Response=VEHICLE,TERRAIN }
   ```
   You can paste lines across if 3DSimED left a flag out.

## Shaders: the two-pass approach

Do the shaders in two passes rather than all at once in 3DSimED.

**Pass 1, in 3DSimED: get it in game with simple materials.** Give every material a basic rF2 shader with just
its diffuse (colour) texture, keeping the material names unchanged, and export. The aim is only a track that
loads with the right textures. Studio 397 documents a fuller Real Road setup in 3DSimED too (several texture
stages and extra UV channels), but it's easier to do that in pass 2.

**Pass 2, in ModDev: switch to the proper rF2 shaders with the Material Editor.** Studio 397 documents a
**Material Editor** that opens while the track is loaded in ModDev's Scene Viewer or Developer Mode. It can change the
shader, settings and texture maps of every loaded material, and saves the result to `.json` files that
**override what's in the GMTs**. So nothing needs re-exporting while you tune.

| Material | Shader | Texture maps |
|---|---|---|
| `road_asphalt` | **L2IBLROAD** (IBL road) | `albedoMap`: road colour, with a roughness mask in the alpha channel · `overlayMap`: fine asphalt detail (RGB multiplies the colour, A adjusts roughness) · `grooveMap`: two-channel mask for the rubbered-in racing line. It also supports Real Road groove, marbles, dust and wet effects |
| `rmbl_kerb` | **L2IBLCURB** (IBL kerb) | As for the road, with the red/white kerb as the albedo |
| `gras_verge`, `grxs_terrain` | A standard (non-road) IBL/PBR shader | Albedo, plus a normal map if you have one |
| `tyrewall`, buildings | Standard IBL/PBR shader | Albedo (+ normal/roughness if available) |

Studio 397's PBR guide and the "Roads Materials (Asphalt / Concrete)" page give suggested values. Use the
real asphalt colour from the video stills as a reference.

## C. Check before moving on

- Open the `.scn` in **gJED** or 3DSimED and confirm all 142 pieces load with textures.
- Look closely at the road surface for gaps or steps between tiles. There shouldn't be any, because the tiles
  share the same vertices.
- Keep the `.fbx`, the `.gmt`s and the `.scn` together. The next step (track folder, `.gdb`, `.tdf`, `.cam`)
  builds on them.

## Sources

- [rFactor 2 Track Technology (Studio 397)](https://www.studio-397.com/wp-content/uploads/2016/12/rF2_Track_Technologyv3.pdf)
- [Common Export Settings – rF2 Developers Guide](https://docs.studio-397.com/display/DG/Common+Export+Settings)
- [Track Creation Cheat Sheet – rF2 Developers Guide](https://docs.studio-397.com/display/DG/Track+Creation+Cheat+Sheet)
- [rFactor 2 Track Development with Blender only (2025)](https://www.patreon.com/posts/143569923)
- [Some help with rFactor material names (OverTake)](https://www.overtake.gg/threads/some-help-with-rfactor-material-names.12452/)
- [IBL Road & Curb Shaders – rF2 Developers Guide](https://docs.studio-397.com/pages/viewpage.action?pageId=37945407)
- [Roads Materials (Asphalt / Concrete) – rF2 Developers Guide](https://docs.studio-397.com/pages/viewpage.action?pageId=37945832)
- [PBR – A Guide in rFactor2 – rF2 Developers Guide](https://docs.studio-397.com/display/DG/PBR+-+A+Guide+in+rFactor2)
- [3DSimED help (PDF)](http://www.sim-garage.co.uk/files/3DSimEDHelp.pdf)
- [3DSimEd – Simwiki](https://www.simwiki.net/wiki/3DSimEd)
- [3DSimEd import/export video tutorial](https://www.youtube.com/watch?v=g8o915_akRw)
