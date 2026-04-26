Workshop Toolkit

A Blender addon for the TF2 cosmetic creation pipeline. Adds panels, shortcuts, and automation for the most repetitive parts of the workflow — LOD management, weight painting, baking, and material setup — all from the `WS Toolkit` tab in the 3D viewport sidebar.

**Blender 5.0+ required**
https://github.com/getgrenade/Player-Model-Quick-Loader required for correct work of most functions.
---

## Installation

1. Download the latest release zip
2. In Blender: `Edit → Preferences → Add-ons → Install`
3. Select the zip and enable **Workshop Toolkit**

---

## Panels

The addon lives in `View3D → Sidebar (N) → WS Toolkit`. It's split into four panels.

---

### Workshop Asset Manager

Manages the LOD collection structure for your cosmetics and handles FBX export.

**Initialize** — Creates the standard LOD collection setup for a new asset (`_lod0`, `_lod1`, `_lod2`, `_high`) and registers it in the asset list. This is your starting point for any new cosmetic.

**All-Class** — Duplicates a registered asset into per-class variants, spacing them out along the X axis so you can work on all nine at once without them overlapping.

**Export Flagged** — FBX-exports every asset you've checked for export. Meshes are merged per LOD, modifiers applied, shape keys baked, and each LOD is re-centered to world origin before export. Files land in a `/mesh/` folder next to your `.blend`. Only LOD0 includes the armature.

**Register Selected (↺ icon)** — Scans the scene and registers any collections that match the expected naming convention but aren't in the list yet. Useful if you set up your scene manually or imported an existing project.

Each registered asset in the list shows:
- **LOD visibility toggles** (eye icons for lod0/lod1/lod2/high)
- **Triangle count on hover** — hover over a LOD toggle to see current tri count vs. the TF2 limit, shown as a percentage with over/under status
- **Export flag checkbox**
- **Bake Normal Map** button — bakes a tangent normal directly from the asset's `_lod0` and `_high` collections using the settings in the Bake Tools panel

> **LOD tri limits:** lod0 = 1,400 · lod1 = 1,000 · lod2 = 700

---

### Utility Operations

Miscellaneous helpers that don't fit elsewhere.

**Set Armature** — Adds an Armature modifier to all selected meshes pointing at a chosen armature. If any of them already have one, it gets replaced. If there's only one armature in the scene it skips the picker dialog.

**Pose toggle button (armature icon)** — Switches all armatures in the scene between Pose and Rest position simultaneously. Also mapped to **`F4`**.

**Extract Cosmetic Base** — In Edit Mode, extracts selected faces into a new mesh object, applies the active asset's material, and automatically routes it to the correct LOD collection. Good for blocking out shapes from an existing reference.

**Sync Jiggle Bones** — Copies jiggle bone positions and hierarchy from one armature to others. Select the source armature last (active), with target armatures also selected.

**Export Preview FBX** — Exports flagged asset meshes (no armature, no animation) to `/bakes/<blend_name>_substance.fbx` for use in Substance Painter. Reference/library assets are included automatically.

**Reproject Diffuse** — Bakes the diffuse color from a reference mesh onto the active mesh using object-space normals. Useful for transferring base color from a TF2 reference model. Shift-select the reference first, then the target, then run.

**Generate Preview Texture** — Bakes a quick flat-color + bevel-shaded preview texture at 512px for in-game testing without a real PBR texture.

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

**Right-click options on a material:**
- Assign to selection (faces in Edit Mode, objects in Object Mode)
- Delete material from project
- Clean selected mesh (removes all materials from selected objects)

**Clean Unused** — Removes all zero-user materials from the project (confirmation required).

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

**Transfer** — Transfers vertex weights from one mesh to others using a Data Transfer modifier, applied and cleaned up automatically. Armature modifiers are temporarily disabled during transfer to avoid pose interference.

- **Object Mode:** active object is the source, other selected meshes are targets
- **Edit Mode:** shift-select the source, tab into the target, select verts — only selected vertices are overwritten

**Smooth** — Runs smooth → limit (max 3 influences) → normalize on the active mesh. The number field next to it sets how many smooth passes to run (default 5, max 50).

---

## File Output Locations

| Output | Path |
|---|---|
| LOD FBX exports | `<blend_dir>/mesh/<asset>_<lod>.fbx` |
| Substance preview FBX | `<blend_dir>/bakes/<blend>_substance.fbx` |
| Baked textures | `<blend_dir>/bakes/<name>.png` |

---

## Notes

- The addon uses Cycles for all baking. GPU rendering is enabled automatically during bakes and restored afterward.
- All-Class variants share the same materials as the original asset — they are not duplicated.
- Shape keys are fully supported in export; they're baked into geometry per-LOD before the FBX is written.
- The jiggle bone sync works across multiple armatures in one pass — useful when your All-Class variants each have their own armature.
