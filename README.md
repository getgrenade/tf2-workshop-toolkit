Workshop Toolkit

**Version 1.4.0**

A Blender addon for the TF2 cosmetic creation pipeline. Adds panels, shortcuts, and automation for the most repetitive parts of the workflow — LOD management, weight painting, baking, and material setup — all from the `WS Toolkit` tab in the 3D viewport sidebar.

**Blender 5.0+ required**

[Player Model Quick Loader](https://github.com/getgrenade/Player-Model-Quick-Loader) required for correct work of most functions.
---

## Installation

1. Download the [latest release](https://github.com/getgrenade/tf2-workshop-toolkit/releases) 
2. In Blender: `Edit → Preferences → Add-ons → Install`
3. Select the zip and enable **Workshop Toolkit**

---

## Building an installable ZIP (Windows)

Double-click `build.bat`. It creates or replaces
`dist/tf2-workshop-toolkit.zip`, containing the current add-on source with the
folder structure Blender expects. Python cache files and development tools
are excluded. Only Windows PowerShell is needed to build; Blender can stay closed.

In Blender, open **Edit → Preferences → Add-ons**, use **Install from Disk**
from the menu, and select the ZIP in `dist`. Enable **Workshop Toolkit**.
When updating an installed version, save your work and restart Blender after
installation to load the new code. Build again whenever you want a fresh ZIP.

For command-line builds without the closing pause, run `build.bat --no-pause`.

## Testing changes locally (Windows, Blender 5.2)

Double-click `test-in-blender.cmd` to open standalone Blender 5.2 with the
current repository copy enabled. You can also drag a `.blend` file onto the
launcher to open it with the development add-on. The launcher uses
`C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`; edit
`BLENDER_EXE` in the launcher if your standalone installation moves.

After editing the Python source, save your Blender work, close that test
session, and launch again to load the latest code. No ZIP creation or add-on
reinstallation is needed. Each launch opens a separate Blender process;
it does not update an already open session. The loader does not save
preferences or overwrite your installed add-on. Keep your usual dependency
add-ons enabled, including Player Model Quick Loader.

## Panels

The addon lives in `View3D → Sidebar (N) → WS Toolkit`. It's split into five panels.
Each panel has a small **?** button for a quick guide. Click a **BASE** badge
to learn about reference mercs. Hover compact controls for explanations.

For a working example, open the Asset Manager's **? → Add Example Asset**.
It adds a small example hat with three LODs, two materials, UVs, a shape key,
and a high-poly source. LOD0 is selected; the other versions start hidden.
Save a new `.blend`, then click **Game FBX** to try the export. The example
has no skeleton and demonstrates collection organization.

---

### Workshop Asset Manager

Manages the LOD collection structure for your cosmetics and handles FBX export.

**New Asset** — Creates the standard LOD collection setup for a new asset (`_lod0`, `_lod1`, `_lod2`, `_high`) and registers it in the asset list. LOD0 becomes the active collection for new meshes.

**All Classes** — Duplicates a registered asset into per-class variants, spacing them out along the X axis so you can work on all nine at once without them overlapping.

**Game FBX** — FBX-exports every asset you've checked for export. Files land in a `/mesh/` folder next to your `.blend`. The completion popup includes **Open Folder**.
Uses the rest pose for every LOD and includes the LOD0 armature even when hidden.
Your original pose, visibility, selection, and mode are restored afterward.

**Register Selected (↺ icon)** — Scans the scene and registers any collections that match the expected naming convention but aren't in the list yet. Useful if you set up your scene manually or imported an existing project.

Mercs added with Player Model Quick Loader are automatically registered as BASE
(library) assets once their `_morphs_low_lod0` collection contains a mesh.
This works in new scenes and when opening existing files, without the register button.

Each registered asset in the list shows:
- **LOD visibility toggles** (eye icons for lod0/lod1/lod2/high)
- **Triangle count on hover** — hover over a LOD toggle to see current tri count vs. the TF2 limit, shown as a percentage with over/under status
- **Export flag checkbox**
- **Bake Normal Map** button — bakes a tangent normal directly from the asset's `_lod0` and `_high` collections using the settings in the Bake Tools panel
- 
---

### Utility Operations

Miscellaneous helpers that don't fit elsewhere.

**Set Armature** — Adds an Armature modifier to all selected meshes pointing at a chosen armature. If there is only one armature, it auto picks it.

**Pose toggle button** — Switches all armatures in the scene between Pose and Rest position simultaneously. Mapped to **`F4`**.

**Extract Cosmetic Base** — In Edit Mode, extracts selected faces into a new mesh object, displaces it, applies the active asset's material, and automatically routes it to the correct LOD collection. Useful for copying player geometry fast.

The extraction dialog always opens so you can set **Displacement** before extracting.
The default **0.02** preserves the previous outward offset. Use **0** to keep the
copied surface in place, a larger positive value for more clearance, or a negative
value to move inward. This is an offset along the extracted mesh's normals in
object-space units, so object scale affects the final world-space distance.

**Sync Jiggle Bones** — Copies jiggle bone positions and hierarchy from one armature to others. Detects `jiggle_name`, `j_name`, `name_j`, and `name_jiggle`; the original names are preserved.
Select the source rig first so its bones take priority. Hidden and excluded rigs
are supported; selection, visibility, and mode are restored afterward. The result
reports how many bones were created. Target armatures must exist—mesh vertex
groups alone are not rigs.

**Painter Preview FBX** — Exports checked asset meshes (no armature, no animation) to `/bakes/<blend_name>_substance.fbx` for use in Substance Painter. Reference/library assets are included automatically.
Respects the current pose for posed previews.

**Reproject** — Select **Diffuse**, **Normal**, or **Specular** in the dropdown next
to Reproject (or in its settings dialog). Select the cosmetic, click **Reproject**,
and choose the reference in **Source Mesh**. The source can stay hidden, including
inside a hidden or excluded collection. The bake uses temporary visible copies
and leaves the original source visibility intact. Selecting the reference and
then the cosmetic still works: the dialog prefills Source Mesh from the other
selected mesh.

- **Diffuse** projects the reference's `$basetexture` color.
- **Normal** rebakes the reference normal map into the cosmetic's tangent space,
  accounting for its UV orientation rather than copying RGB values unchanged.
  It recognizes imported Normal Map graphs and `$bumpmap` / `$normalmap` images.
  Existing source Normal Map conventions are preserved; a labelled TF2 normal
  without a Normal Map graph is interpreted as DirectX. **Normal Y** selects
  DirectX (Y-) or OpenGL (Y+) output, shared with Bake Tools.
- **Specular** projects the **normal texture's alpha channel** into a separate
  grayscale texture named `cosmetic-name_reproj_specular.tga`. It does not use
  diffuse alpha. Normal and Specular images use Non-Color data.

Clicking it opens a settings dialog, even with a single reference material:

- **Apply to Cosmetic** puts the result in the matching Image Texture node and
  connects Diffuse to Principled Base Color, Normal through a Normal Map node to
  Normal, or Specular to Specular IOR Level. It reuses existing nodes where possible
  and handles each material slot. Materials shared with other objects
  are copied so those objects keep their appearance. Disable this to only bake/save.
- **Open Texture Preview** opens the finished texture in a separate Image Editor
  window, leaving the main workspace intact.
- **Extrusion** controls how far outward along the cosmetic normals the projection
  rays start. The previous fixed value was 1; it remains the default.
- **Max Ray Distance** limits the ray search distance. The default 0 means unlimited.
  Try reducing Extrusion and setting a finite ray distance when close or intersecting
  surfaces pick up colors from the wrong part of the reference. Distances that are
  too small leave unbaked gaps. True intersections may still need a custom cage or
  isolated baking passes; a distance limit cannot distinguish every overlapping surface.

Reprojection requires Object Mode, a saved .blend, and an existing cosmetic UV map.
Choose a source mesh different from the active cosmetic; it must belong to the scene.
The reference is sampled through temporary copies, leaving its materials intact.
An unsuccessful bake leaves the cosmetic's previously applied texture intact.
Each choice saves its own 1024px TGA in the blend file's **bakes** folder, suffixed
`_reproj_diffuse`, `_reproj_normal`, or `_reproj_specular`.

Reprojection uses **Bake Tools → Pad** for UV island padding in pixels (default 8).
Increase it, for example to 16, to extend edge colors farther outside the UV
islands and reduce texture seams when filtering or viewing lower mip levels.
Set it to 0 for no padding. This extends baked island borders; it does not fill
missing projection details inside an island. Leave enough space between UV islands
for the padding.

**Generate Preview Texture** — Use only after normal map is baked. Creats diffuse and normal map in /textures/temp/ folder for quick preview with importer.

---

### Material Manager

Quick material operations without digging into the Shader Editor.

**+ (New PBR Material)** — Creates a blank Principled BSDF material.

**◇ (New Bevel Material)** — Creates a Principled BSDF material with a Bevel shader pre-wired to the Normal input, ready for bevel-shaded baking.

**Material list** — Shows all project materials. Clicking a material in the list selects objects using it (or faces in Edit Mode). Library/reference asset materials are hidden by default — toggle visibility with the eye icon.

**Top row controls (when a material is selected):**
- Color swatch — sets the base color
- **M** — Metallic value
- **R** — Roughness value
- **B** — Bevel radius (only shown if the material has a Bevel node)
- Assign to selection (faces in Edit Mode, objects in Object Mode)
- Clean selected mesh (removes all materials from selected objects)
- Clean Unused (removes all zero-user materials from the project)

---

### Bake Tools

Tangent normal baking and bevel normal baking, plus a compositor to blend the two together.

#### Shared Settings (top bar)

| Setting | Description |
|---|---|
| Resolution | 512 / 1024 / 2048 / 4096 / Custom |
| Bit Depth | 8-bit or 32-bit float |
| Padding | UV island margin in pixels |
| AA | Anti-aliasing via supersampling (1x / 2x / 4x) |
| Y Channel | **Y+** (OpenGL/Blender) or **Y−** (DirectX/Unreal) — pick Y− for TF2 |

#### Tangent Normal

Bakes a high-to-low tangent space normal map. Select your `_low` and `_high` meshes and hit **Bake Tangent Normal**.

Objects are automatically matched into bake sets by name: `cube_low` bakes against `cube_high` (and any `cube_high.001` floaters). No cross-set bleed.

- **Cage / Ray** — cage extrusion distance and max ray distance for the projection
- Output is named automatically from the active object's slot-0 material: `{material}_normal`
- The 💾 icon toggles saving to disk (saves to `/bakes/` next to your `.blend`)

The live bake-set preview below the button shows exactly which low bakes against which highs before you commit.

#### Bevel Normal

Bakes a bevel shader normal map on a single mesh. Only works with one mesh selected (active).

- **Samples** — ray count for the Bevel shader (2–32)
- **Radius** — bevel radius in Blender units
- Output named `{object}_bevel`

#### Composite

Blends the bevel normal onto the base tangent normal using Reoriented Normal Blending (RNB). This adds soft edge highlights from the bevel bake on top of the high-poly detail from the tangent bake.

- Pick the base (`_normal`) and bevel (`_bevel`) images from the dropdowns
- **Mask Blur** — softens the bevel mask edges (0 = hard, higher = softer transition)
- **Auto-save** — writes the composited result to disk immediately

---

## Hotkeys

| Key | Action |
|---|---|
| `F4` | Toggle all armatures between Pose / Rest |
| `Shift + Q` | Weight Tools pie menu |

Both can be remapped in `Edit → Preferences → Add-ons → Workshop Toolkit`.

---

## Weight Tools

Available in the **Weight Tools** panel and via the **`Shift+Q`** pie menu.

**Copy / Paste** — In Edit Mode, copies the full weight map from one vertex and pastes it onto selected vertices. Good for fixing seams or propagating weights to a nearby vert manually.

**Target Bone field** — The bone name used by the Assign button (defaults to `bip_head`).

**Assign (bone icon)** — Sets 100% weight to the target bone on all vertices of selected meshes, clearing every other group. Handy for starting fresh on a new piece.

**Assign Selected / Weight** — In Edit Mode, select vertices, enter the same Target
Bone name (for example `bip_head`), set **Weight** from 0 to 1, and click
**Assign Selected**. A value of 0.25 sets the selected vertices to exactly 25%
head weight. The strongest remaining bone weights share the other 75%, preserving
their proportions and keeping at most three deform influences total. The target
bone is reserved before limiting, so a small assigned weight is not culled.
Weight 0 removes the target influence; Weight 1 assigns it fully.

With **Soft Radius** enabled, selected vertices receive the specified value and
connected nearby vertices blend from their existing target weight toward it,
using the existing radius preview. Hidden, disconnected, and out-of-radius vertices
stay unchanged. Locked and utility groups are preserved. Incompatible locks or
vertices without other weights to balance a partial assignment cancel the whole
operation without changing weights. The command is undoable and stays in Edit Mode.

**Transfer** — Transfers vertex weights from one mesh to others using a Data Transfer modifier, applied and cleaned up automatically. Armature modifiers are temporarily disabled during transfer to avoid pose interference.

- **Object Mode:** active object is the source, other selected meshes are targets
- **Edit Mode:** shift-select the source, tab into the target, select verts — only selected vertices are overwritten

**Smooth** — Runs smooth → limit (max 3 influences) → normalize on the active mesh. The number field next to it sets how many smooth passes to run (default 5, max 50).

Enable **Soft Radius** to share the same selection falloff between **Assign Selected**, **Smooth**,
**Transfer**, and **Distance Transfer**. It extends the operation beyond the selected
vertices. Adjust **Radius** to set the surface distance: the selection gets full
smoothing, with a smooth falloff to zero at the radius. Distances follow connected,
visible mesh edges, so separate pieces are not affected across empty gaps.
The viewport shows blue selected vertices, orange-to-yellow nearby vertices,
and a yellow cutoff outline. The legend shows the distance and affected count.
Changing the radius updates this preview without changing any weights; click
**Smooth** or a transfer command to apply it. For transfers, selected core vertices
get the full transferred result; nearby vertices blend their previous weights
with the new weights, and vertices at/beyond the cutoff remain unchanged.
If a nearby vertex has no existing weights, the result is normalized to valid
weights rather than leaving a partial unnormalized assignment.
The regular Transfer still samples with Blender's native Data Transfer mapping.
In Weight Paint, enable vertex selection (or face selection)
to define the core area. With everything selected, the whole mesh gets full smoothing.
With **On Cage** enabled in Edit Mode, the indicator and distance calculation
follow the posed/deformed cage. Otherwise Edit Mode uses the original edit cage;
Weight Paint uses the displayed surface. A default radius of 4 world units suits TF2's large coordinate scale.
Soft Radius preserves locked/utility groups, normalizes affected deform weights,
and limits them to three influences. Turning it off keeps the original Smooth
and Transfer commands. In Object Mode the reference remains the active source;
select target vertices beforehand. For a localized transfer with a clear target
preview, use Edit Mode on the target while the reference is also selected.

**Distance Transfer (Experimental)** — Transfers weights from the reference's
nearest surface with triangle interpolation, then smooths along the target's
connected edges. Vertices close to the reference retain the surface result;
farther vertices receive progressively more smoothing. Disconnected pieces
do not smooth into each other. Armature deformation is temporarily bypassed.

Use the same source/target selection order as Transfer. In Edit Mode only
selected vertices are changed. The dialog offers:

- **Keep Exact Within (%)**: no smoothing inside this distance (default 0.2%).
- **Full Smoothing At (%)**: full selected smoothing strength beyond this distance (default 6%).
- **Smoothing Strength** and **Iterations**: maximum smoothing and number of passes.

Distances use the reference's largest world-space dimension, so they scale
with the model. The provided Scout body is about 67 units tall: defaults are
approximately 0.13 units for exact transfer and 4 units for full smoothing.
The result message reports the actual distances. Adjust the defaults for your
scarf; distance alone cannot determine which anatomical region should drive it.
The original Transfer command remains available for close-fitting meshes.

**Smooth Gradient** — Click the button, then drag a line in the 3D View from
**zero smoothing** to **full chosen strength**. Release to preview. Scroll up/down
to adjust strength in 5% steps, or drag another line to replace the gradient.
Press **Enter** to apply; **Esc/right-click** restores the original weights.
The Smooth count sets the number of passes. Previews always start from the
original weights, so repeated adjustments do not accumulate blur.
The **blue hollow circle** is labeled **START: NO SMOOTHING**. The **orange square**
is labeled **END: MAX** with the current strength. An arrow and blue-to-orange
line point toward stronger smoothing; weights beyond the orange end use that
maximum strength. Soft Radius applies to Smooth and the transfer commands, not the gradient;
its overlay is temporarily hidden while drawing a gradient.

In Edit Mode it affects selected vertices; in Weight Paint it respects vertex
or face selection masks. Without a mask it affects the whole mesh, excluding
hidden vertices. The screen-space gradient can affect both front and back
surfaces: use a selection mask to isolate a scarf region. Disable modifiers
that change topology before using the gradient. Weight Paint stays visible
during preview; Edit Mode is temporarily exited and restored afterward.

Both new tools normalize affected weights and keep at most **three deform
influences**. When an armature is assigned, unrelated utility/mask groups are
preserved. Locked groups remain unchanged; impossible normalization/limit
constraints produce an error rather than silently altering locks. Targets
must have single-user mesh data. These commands change weights; they do not
automatically add or change an Armature modifier.

---

## File Output Locations

| Output | Path |
|---|---|
| LOD FBX exports | `<blend_dir>/mesh/<asset>_<lod>.fbx` |
| Substance preview FBX | `<blend_dir>/bakes/<blend>_substance.fbx` |
| Baked textures | `<blend_dir>/bakes/<name>.png` |
