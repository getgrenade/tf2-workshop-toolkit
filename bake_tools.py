"""
Workshop Toolkit – Bake Tools Module
Tangent Normal baking (multi-mesh high→low) and Bevel Normal baking (single mesh).

Bake-set matching
-----------------
Objects are grouped into "bake sets" by stripping the _low / _high suffix
(and any trailing Blender duplicate counter like .001) from their name.

  cube_low          → base "cube",  role LOW
  cube_high         → base "cube",  role HIGH
  cube_high.001     → base "cube",  role HIGH  (floater)
  cone_low          → base "cone",  role LOW
  cone_high         → base "cone",  role HIGH

Each LOW bakes ONLY against its matching HIGHs — no cross-set projection bleed.

Auto-naming
-----------
  Tangent bake  → named from the active object's slot-0 material: {mat}_normal
  Bevel bake    → named from the active object:                    {obj}_bevel

These are resolved at bake time and written back into output_name /
bevel_output_name so the composite section always reflects current values.
"""

import bpy
import os
import re
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty,
    IntProperty, StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup


# ============================================================ #
#                       CONSTANTS / ENUMS                      #
# ============================================================ #

SIZE_ITEMS = [
    ("512",    "512",    ""),
    ("1024",   "1024",   ""),
    ("2048",   "2048",   ""),
    ("4096",   "4096",   ""),
    ("CUSTOM", "Custom", "Enter a custom resolution"),
]
AA_ITEMS = [
    ("NONE", "None", "Bake at target resolution"),
    ("2X",   "2x",   "Bake at 2x then downscale"),
    ("4X",   "4x",   "Bake at 4x then downscale"),
]
DEPTH_ITEMS = [
    ("8",  "8-bit",  ""),
    ("16", "16-bit", ""),
    ("32", "32-bit", ""),
]

BAKE_NODE_LABEL = "_wstk_bake_target"
_DUPE_RE = re.compile(r"\.\d+$")


# ============================================================ #
#                     BAKE-SET GROUPING                        #
# ============================================================ #

def _base_name(obj_name):
    name = _DUPE_RE.sub("", obj_name)
    name = re.sub(r"[_\-](low|high)$", "", name, flags=re.IGNORECASE)
    return name

def _is_high(obj):
    return bool(re.search(r"[_\-]high$", _DUPE_RE.sub("", obj.name), re.IGNORECASE))

def _is_low(obj):
    return bool(re.search(r"[_\-]low$",  _DUPE_RE.sub("", obj.name), re.IGNORECASE))

def _build_bake_sets(objects):
    from collections import defaultdict
    lows, highs, ungrouped = defaultdict(list), defaultdict(list), []
    for obj in objects:
        if   _is_low(obj):  lows [_base_name(obj.name)].append(obj)
        elif _is_high(obj): highs[_base_name(obj.name)].append(obj)
        else:               ungrouped.append(obj)
    sets, orphan_bases = [], []
    for base, low_list in lows.items():
        for low in low_list:
            sets.append({"low": low, "highs": highs.get(base, [])})
    for base in highs:
        if base not in lows:
            orphan_bases.append(base)
    for obj in ungrouped:
        sets.append({"low": obj, "highs": []})
    return sets, orphan_bases


# ============================================================ #
#                    AUTO-NAME HELPERS                         #
# ============================================================ #

def _tangent_name_from_context(context):
    """
    Return the auto-generated tangent bake name from the active object's
    first material.  Falls back to 'normal_bake' if nothing is active.
    """
    obj = context.active_object
    if obj and obj.type == "MESH" and obj.data.materials:
        mat = obj.data.materials[0]
        if mat:
            return f"{mat.name}_normal"
    return "normal_bake"

def _bevel_name_from_context(context):
    """
    Return the auto-generated bevel bake name from the active object's name.
    Falls back to 'bevel_normal_bake'.
    """
    obj = context.active_object
    if obj and obj.type == "MESH":
        return f"{obj.name}_bevel"
    return "bevel_normal_bake"

def _bevel_images_enum(self, context):
    """EnumProperty items callback: all images whose name ends with '_bevel'."""
    items = [
        (img.name, img.name, f"{img.size[0]}x{img.size[1]}")
        for img in bpy.data.images
        if img.name.endswith("_bevel")
    ]
    if not items:
        items = [("__NONE__", "(no bevel bakes found)", "")]
    return items

def _normal_images_enum(self, context):
    """EnumProperty items callback: all images whose name ends with '_normal'."""
    items = [
        (img.name, img.name, f"{img.size[0]}x{img.size[1]}")
        for img in bpy.data.images
        if img.name.endswith("_normal")
    ]
    if not items:
        items = [("__NONE__", "(no normal bakes found)", "")]
    return items


# ============================================================ #
#                       HELPER FUNCTIONS                       #
# ============================================================ #

def _ensure_image(name, width, height, is_hdr=False):
    img = bpy.data.images.get(name)
    if img:
        # An image whose source file was deleted on disk ends up with
        # source == 'FILE' and has_data == False (Blender never loaded it).
        # Trying to bake into it with use_clear=True raises:
        #   RuntimeError: Error: Uninitialized image "..." from object "..."
        # Detect this state and recreate the datablock from scratch.
        file_missing = (
            img.source == "FILE"
            and bool(img.filepath)
            and not img.has_data
        )
        wrong_size = (img.size[0] != width or img.size[1] != height)
        if file_missing or wrong_size:
            bpy.data.images.remove(img)
            img = None
    if not img:
        img = bpy.data.images.new(
            name, width=width, height=height,
            alpha=False, float_buffer=is_hdr,
        )
    img.colorspace_settings.name = "Non-Color"
    return img

def _inject_bake_node(mat, image):
    if not mat.use_nodes:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    for n in nodes:
        n.select = False
    node = next(
        (n for n in nodes if n.type == "TEX_IMAGE" and n.label == BAKE_NODE_LABEL),
        None,
    )
    if node is None:
        node = nodes.new("ShaderNodeTexImage")
        node.label    = BAKE_NODE_LABEL
        node.location = (-300, -600)
    node.image   = image
    node.select  = True
    nodes.active = node
    return node

def _remove_bake_nodes(mat):
    if mat and mat.use_nodes:
        for n in list(mat.node_tree.nodes):
            if n.type == "TEX_IMAGE" and n.label == BAKE_NODE_LABEL:
                mat.node_tree.nodes.remove(n)

def _prepare_obj_for_bake(obj, image):
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name="UVMap")
    records = []
    if not obj.data.materials:
        tmp = bpy.data.materials.new(name=f"_bake_tmp_{obj.name}")
        tmp.use_nodes = True
        obj.data.materials.append(tmp)
        _inject_bake_node(tmp, image)
        records.append((tmp, True))
    else:
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                mat = bpy.data.materials.new(name=f"_bake_tmp_slot_{obj.name}")
                mat.use_nodes = True
                slot.material = mat
                _inject_bake_node(mat, image)
                records.append((mat, True))
            else:
                _inject_bake_node(mat, image)
                records.append((mat, False))
    return records

def _cleanup_obj(obj, records):
    slot_mats = {s.material for s in obj.material_slots}
    for mat, was_tmp in records:
        if was_tmp and mat in slot_mats:
            for slot in obj.material_slots:
                if slot.material == mat:
                    slot.material = None
            bpy.data.materials.remove(mat, do_unlink=True)
        else:
            _remove_bake_nodes(mat)

def _resolve_size(props):
    if props.bake_size == "CUSTOM":
        return props.bake_size_custom, props.bake_size_custom
    s = int(props.bake_size)
    return s, s

def _aa_multiplier(props):
    return {"NONE": 1, "2X": 2, "4X": 4}[props.bake_aa]

def _scale_down(image, w, h):
    if image.size[0] != w or image.size[1] != h:
        image.scale(w, h)

def _flip_green(image):
    import numpy as np
    px = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(px)
    px[1::4] = 1.0 - px[1::4]
    image.pixels.foreach_set(px)

def _save_image(image, name):
    if not bpy.data.is_saved:
        return
    bakes_dir = os.path.join(os.path.dirname(bpy.data.filepath), "bakes")
    os.makedirs(bakes_dir, exist_ok=True)
    image.filepath_raw = os.path.join(bakes_dir, f"{name}.tga")
    image.file_format  = "TARGA"
    image.save()



def _rasterize_selected_faces_uv(obj, width, height):
    """
    Return a float32 (height, width) mask: 1.0 inside selected faces' UVs, 0.0 elsewhere.

    Reads selection and UV data directly from obj.data (MeshPolygon / MeshLoopUVLayer)
    via foreach_get — bypasses bmesh entirely so it works reliably after a
    mode_set(OBJECT) call within the same operator execution.
    """
    import numpy as np

    mesh = obj.data
    if not mesh.uv_layers.active:
        return np.ones((height, width), dtype=np.float32)  # no UV → allow all

    n_polys = len(mesh.polygons)
    if n_polys == 0:
        return np.ones((height, width), dtype=np.float32)

    # Read polygon selection flags
    poly_sel = np.zeros(n_polys, dtype=bool)
    mesh.polygons.foreach_get("select", poly_sel)

    # Read loop starts and totals for each polygon
    loop_start = np.zeros(n_polys, dtype=np.int32)
    loop_total = np.zeros(n_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", loop_start)
    mesh.polygons.foreach_get("loop_total", loop_total)

    # Read all UV coordinates (flattened: u0,v0, u1,v1, ...)
    n_loops = len(mesh.loops)
    uv_flat = np.zeros(n_loops * 2, dtype=np.float32)
    mesh.uv_layers.active.data.foreach_get("uv", uv_flat)
    uvs = uv_flat.reshape((n_loops, 2))

    mask = np.zeros((height, width), dtype=np.float32)

    for pi in range(n_polys):
        if not poly_sel[pi]:
            continue

        ls = loop_start[pi]
        lt = loop_total[pi]
        if lt < 3:
            continue

        face_uvs = uvs[ls:ls + lt]  # shape (lt, 2)

        # Fan triangulation from vertex 0.
        # Blender stores image pixels bottom-row-first and UV V=0 is also
        # the bottom, so y = v * height with NO flip is correct.
        for i in range(1, lt - 1):
            ax = face_uvs[0,   0] * width;  ay = face_uvs[0,   1] * height
            bx = face_uvs[i,   0] * width;  by = face_uvs[i,   1] * height
            cx = face_uvs[i+1, 0] * width;  cy = face_uvs[i+1, 1] * height

            min_x = max(0,          int(np.floor(min(ax, bx, cx))))
            max_x = min(width  - 1, int(np.ceil (max(ax, bx, cx))))
            min_y = max(0,          int(np.floor(min(ay, by, cy))))
            max_y = min(height - 1, int(np.ceil (max(ay, by, cy))))

            if min_x > max_x or min_y > max_y:
                continue

            xs = np.arange(min_x, max_x + 1, dtype=np.float32) + 0.5
            ys = np.arange(min_y, max_y + 1, dtype=np.float32) + 0.5
            gx, gy = np.meshgrid(xs, ys)

            # Inline edge function — avoids closure / rebinding issues
            e0 = (gx - ax) * (by - ay) - (gy - ay) * (bx - ax)
            e1 = (gx - bx) * (cy - by) - (gy - by) * (cx - bx)
            e2 = (gx - cx) * (ay - cy) - (gy - cy) * (ax - cx)

            inside = ((e0 >= 0) & (e1 >= 0) & (e2 >= 0)) |                      ((e0 <= 0) & (e1 <= 0) & (e2 <= 0))

            mask[min_y:max_y+1, min_x:max_x+1][inside] = 1.0

    return mask


# ============================================================ #
#                         PROPERTIES                           #
# ============================================================ #

class BAKE_Props(PropertyGroup):

    # Shared
    bake_size: EnumProperty(name="Resolution", items=SIZE_ITEMS, default="2048")
    bake_size_custom: IntProperty(
        name="Custom Size", default=2048, min=64, max=16384,
        description="Custom bake resolution (power-of-two recommended)",
    )
    bake_depth: EnumProperty(name="Bit Depth", items=DEPTH_ITEMS, default="8")
    bake_padding: IntProperty(name="Padding", default=8, min=0, max=256,
                              description="UV island margin in pixels")
    bake_aa: EnumProperty(name="Anti-Aliasing", items=AA_ITEMS, default="NONE",
                          description="Supersample then downscale for smoother edges")
    swizzle_y: EnumProperty(
        name="Y Channel",
        items=[
            ("PLUS",  "Y+ OpenGL",  "Standard Blender/OpenGL convention"),
            ("MINUS", "Y- DirectX", "Unreal/DirectX – flips green channel"),
        ],
        default="MINUS",
    )

    # Tangent Normal — output_name is auto-set at bake time; stored so the
    # composite section and save buttons can reference it without needing context
    cage_extrusion: FloatProperty(name="Cage Extrusion",
                                  default=0.5, min=0.0, max=10.0, step=1, precision=4)
    ray_distance: FloatProperty(name="Max Ray Distance",
                                default=0.0, min=0.0, max=10.0, step=1, precision=4)
    output_name: StringProperty(name="Output Name", default="")
    save_external: BoolProperty(name="Save to Disk", default=True,
                                description="Save PNG to /bakes/ next to .blend")

    # Bevel Normal — bevel_output_name is auto-set at bake time
    bevel_samples: IntProperty(name="Bevel Samples", default=16, min=2, max=32,
                               description="Rays used by the Bevel shader")
    bevel_radius: FloatProperty(name="Bevel Radius",
                                default=0.1, min=0.0, max=1.0, step=1, precision=4)
    bevel_output_name: StringProperty(name="Last Bevel Bake", default="")
    bevel_save_external: BoolProperty(name="Save to Disk", default=True)

    # Composite
    composite_base_pick: EnumProperty(
        name="Base Normal Image",
        items=_normal_images_enum,
        description="Which _normal image to composite the bevel onto",
    )

    composite_bevel_pick: EnumProperty(
        name="Bevel Image",
        items=_bevel_images_enum,
        description="Which _bevel image to composite onto the base normal map",
    )

    composite_save_external: BoolProperty(
        name="Auto-save after composite",
        default=False,
        description="Write the result to /bakes/ immediately after compositing",
    )
    mask_blur_radius: IntProperty(
        name="Mask Blur",
        default=0, min=0, max=64,
        description=(
            "Gaussian blur radius applied to the bevel detection mask before "
            "compositing, in pixels. 0 = hard edge (no blur). Higher values "
            "expand the stamped region outward and feather its edges, exactly "
            "like Photoshop's Feather on a selection. 4-12 px is usually enough."
        ),
    )
    geo_mask_padding: IntProperty(
        name="Geo Mask Padding",
        default=0, min=0, max=128,
        description=(
            "Expand the face-selection mask outward by this many pixels. "
            "Useful when bevel edges sit just outside the UV boundary of the "
            "selected faces. 0 = exact face boundaries, higher = grows outward."
        ),
    )



def _run_bake_sets(operator, context, bake_sets, img_name, props):
    """
    Core bake execution shared by BAKE_OT_TangentNormal and TF2_OT_BakeAssetNormal.
    bake_sets: list of {"low": obj, "highs": [obj, ...]}
    img_name:  name for the output image datablock
    props:     context.scene.bake_props
    Returns {"FINISHED"} or {"CANCELLED"}.
    """
    import numpy as np  # needed for _flip_green

    scene  = context.scene
    cycles = scene.cycles

    target_w, target_h = _resolve_size(props)
    aa_mult = _aa_multiplier(props)
    bake_w  = target_w * aa_mult
    bake_h  = target_h * aa_mult
    is_hdr  = props.bake_depth == "32"

    bake_img = _ensure_image(img_name, bake_w, bake_h, is_hdr=is_hdr)

    prev_engine  = scene.render.engine
    prev_device  = cycles.device
    prev_samples = cycles.samples
    prev_sel     = list(context.selected_objects)
    prev_active  = context.view_layer.objects.active

    scene.render.engine = "CYCLES"
    cycles.device        = "GPU"
    cycles.samples       = 1

    first_set   = True
    all_records = {}

    for bset in bake_sets:
        low   = bset["low"]
        highs = bset["highs"]

        records = _prepare_obj_for_bake(low, bake_img)
        all_records[low] = records

        bpy.ops.object.select_all(action="DESELECT")

        if highs:
            for h in highs:
                h.select_set(True)
            low.select_set(True)
            context.view_layer.objects.active = low

            bpy.ops.object.bake(
                type                   = "NORMAL",
                normal_space           = "TANGENT",
                use_selected_to_active = True,
                cage_extrusion         = props.cage_extrusion,
                max_ray_distance       = props.ray_distance,
                margin                 = props.bake_padding,
                use_clear              = first_set,
            )
        else:
            low.select_set(True)
            context.view_layer.objects.active = low
            _prepare_obj_for_bake(low, bake_img)

            bpy.ops.object.bake(
                type         = "NORMAL",
                normal_space = "TANGENT",
                margin       = props.bake_padding,
                use_clear    = first_set,
            )

        first_set = False

    if props.swizzle_y == "MINUS":
        _flip_green(bake_img)
    if aa_mult > 1:
        _scale_down(bake_img, target_w, target_h)
    if props.save_external:
        _save_image(bake_img, img_name)

    for obj, records in all_records.items():
        _cleanup_obj(obj, records)

    scene.render.engine = prev_engine
    cycles.device        = prev_device
    cycles.samples       = prev_samples
    bpy.ops.object.select_all(action="DESELECT")
    for o in prev_sel:
        try: o.select_set(True)
        except Exception: pass
    context.view_layer.objects.active = prev_active

    operator.report({"INFO"},
                    f"Baked {len(bake_sets)} set(s) → '{img_name}' "
                    f"({target_w}x{target_h})")
    return {"FINISHED"}


# ============================================================ #
#                          OPERATORS                           #
# ============================================================ #

class BAKE_OT_TangentNormal(Operator):
    """Bake tangent-space normal from selection. Pairs _low with matching _high objects; output named {mat}_normal."""
    bl_idname  = "bake.tangent_normal"
    bl_label   = "Bake Tangent Normal"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.selected_objects
                and any(o.type == "MESH" for o in context.selected_objects))

    def execute(self, context):
        props = context.scene.bake_props

        all_meshes = [o for o in context.selected_objects if o.type == "MESH"]
        bake_sets, orphans = _build_bake_sets(all_meshes)

        if not bake_sets:
            self.report({"ERROR"}, "No valid bake sets found in selection.")
            return {"CANCELLED"}
        if orphans:
            self.report({"WARNING"},
                        f"HIGHs with no matching LOW (skipped): {', '.join(orphans)}")

        img_name = _tangent_name_from_context(context)
        props.output_name = img_name
        props.composite_base_pick = img_name

        return _run_bake_sets(self, context, bake_sets, img_name, props)


# ------------------------------------------------------------------ #

class BAKE_OT_BevelNormal(Operator):
    """Bake a Bevel-shader normal map on the active mesh; output named {obj}_bevel."""
    bl_idname  = "bake.bevel_normal"
    bl_label   = "Bake Bevel Normal"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "MESH" and len(context.selected_objects) == 1

    def execute(self, context):
        props  = context.scene.bake_props
        scene  = context.scene
        cycles = scene.cycles
        obj    = context.active_object

        # Resolve output name from active object
        img_name = _bevel_name_from_context(context)
        props.bevel_output_name = img_name

        target_w, target_h = _resolve_size(props)
        aa_mult = _aa_multiplier(props)
        bake_w  = target_w * aa_mult
        bake_h  = target_h * aa_mult
        is_hdr  = props.bake_depth == "32"

        bake_img = _ensure_image(img_name, bake_w, bake_h, is_hdr=is_hdr)

        if not obj.data.uv_layers:
            obj.data.uv_layers.new(name="UVMap")

        prev_engine    = scene.render.engine
        prev_device    = cycles.device
        prev_samples   = cycles.samples
        prev_mat_names = [
            (s.material.name if s.material else None) for s in obj.material_slots
        ]

        scene.render.engine = "CYCLES"
        cycles.device        = "GPU"
        cycles.samples       = props.bevel_samples

        bevel_mat = bpy.data.materials.new(name="_wstk_bevel_tmp")
        bevel_mat.use_nodes = True
        nodes = bevel_mat.node_tree.nodes
        links = bevel_mat.node_tree.links
        for n in list(nodes):
            nodes.remove(n)

        img_node          = nodes.new("ShaderNodeTexImage")
        img_node.image    = bake_img
        img_node.label    = BAKE_NODE_LABEL
        img_node.location = (-300, 300)

        bevel_node                         = nodes.new("ShaderNodeBevel")
        bevel_node.samples                 = props.bevel_samples
        bevel_node.inputs[0].default_value = props.bevel_radius
        bevel_node.location                = (-500, 0)

        bsdf          = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (-200, 0)
        out           = nodes.new("ShaderNodeOutputMaterial")
        out.location  = (100, 0)

        links.new(bevel_node.outputs["Normal"], bsdf.inputs["Normal"])
        links.new(bsdf.outputs["BSDF"],         out.inputs["Surface"])

        for n in nodes:
            n.select = False
        img_node.select  = True
        nodes.active     = img_node

        obj.data.materials.clear()
        obj.data.materials.append(bevel_mat)

        success = False
        try:
            bpy.ops.object.bake(
                type         = "NORMAL",
                normal_space = "TANGENT",
                margin       = props.bake_padding,
                use_clear    = True,
            )
            success = True
        except Exception as e:
            self.report({"ERROR"}, f"Bevel bake failed: {e}")

        if success:
            if props.swizzle_y == "MINUS":
                _flip_green(bake_img)
            if aa_mult > 1:
                _scale_down(bake_img, target_w, target_h)
            if props.bevel_save_external:
                _save_image(bake_img, img_name)
            self.report({"INFO"},
                        f"Bevel baked → '{img_name}' ({target_w}x{target_h})")

        obj.data.materials.clear()
        for name in prev_mat_names:
            obj.data.materials.append(
                bpy.data.materials.get(name) if name else None
            )
        bpy.data.materials.remove(bevel_mat, do_unlink=True)

        scene.render.engine = prev_engine
        cycles.device        = prev_device
        cycles.samples       = prev_samples

        return {"FINISHED"} if success else {"CANCELLED"}


# ------------------------------------------------------------------ #

class BAKE_OT_CompositeBevelOntoNormal(Operator):
    """Blend the bevel normal onto the base normal map using Reoriented Normal Blending."""
    bl_idname  = "bake.composite_bevel_onto_normal"
    bl_label   = "Composite Bevel onto Normal"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        props      = context.scene.bake_props
        base_name  = props.composite_base_pick
        base_ok    = (base_name not in ("", "__NONE__")
                      and bpy.data.images.get(base_name) is not None)
        bevel_pick = props.composite_bevel_pick
        bevel_ok   = (bevel_pick not in ("", "__NONE__")
                      and bpy.data.images.get(bevel_pick) is not None)
        return base_ok and bevel_ok

    def execute(self, context):
        import numpy as np

        props     = context.scene.bake_props
        base_img  = bpy.data.images.get(props.composite_base_pick)
        bevel_img = bpy.data.images.get(props.composite_bevel_pick)
        # Hardcoded: any bevel pixel whose blue channel is even slightly below
        # 1.0 counts as non-flat. 1e-4 handles floating-point imprecision without
        # needing the user to think about it.
        threshold = 1e-4
        blur_r    = props.mask_blur_radius

        if base_img is None:
            self.report({"ERROR"}, f"Base image '{props.output_name}' not found.")
            return {"CANCELLED"}
        if bevel_img is None:
            self.report({"ERROR"},
                        f"Bevel image '{props.composite_bevel_pick}' not found.")
            return {"CANCELLED"}

        bw, bh = base_img.size[0], base_img.size[1]

        # Fetch base
        base_raw = np.empty(bw * bh * 4, dtype=np.float32)
        base_img.pixels.foreach_get(base_raw)
        base_px = base_raw.reshape((bh, bw, 4))

        # Fetch bevel (resample if needed)
        # If the image was saved to disk and its in-memory pixel buffer was
        # subsequently cleared (e.g. after a file reload or Blender restart),
        # has_data will be False and pixels will all read as 0.0 / flat.
        # Force a reload from disk so we always get real pixel data.
        if bevel_img.source == "FILE" and bevel_img.filepath and not bevel_img.has_data:
            bevel_img.reload()
        if base_img.source == "FILE" and base_img.filepath and not base_img.has_data:
            base_img.reload()

        if bevel_img.size[0] != bw or bevel_img.size[1] != bh:
            tmp = bevel_img.copy()
            tmp.scale(bw, bh)
            bevel_raw = np.empty(bw * bh * 4, dtype=np.float32)
            tmp.pixels.foreach_get(bevel_raw)
            bpy.data.images.remove(tmp)
        else:
            bevel_raw = np.empty(bw * bh * 4, dtype=np.float32)
            bevel_img.pixels.foreach_get(bevel_raw)
        bevel_px = bevel_raw.reshape((bh, bw, 4))

        # Sanity check: if bevel image is entirely flat, warn the user
        bevel_blue_max = float(bevel_raw[2::4].min())
        if bevel_blue_max > (1.0 - 1e-4):
            self.report({"WARNING"},
                        f"Bevel image '{bevel_img.name}' appears to be entirely flat "
                        f"(all blue values >= 1.0). Check it is the correct image and "
                        f"has been baked.")
            return {"CANCELLED"}

        # --- Build hard binary mask from blue-channel deviation ---
        # A bevel pixel is "not flat" when its blue channel is below (1 - threshold).
        # This gives a clean binary: 1.0 = has bevel detail, 0.0 = flat.
        hard_mask = (bevel_px[:, :, 2] < (1.0 - threshold)).astype(np.float32)

        # --- Optional Gaussian blur — feathers only the FRINGE, not the core ---
        # Problem with naively blurring the binary mask: convolution averages
        # each pixel with its neighbours, so even the solid 1.0 core gets pulled
        # down toward 0 wherever it is near a 0-valued background pixel.
        # Fix: blur the binary mask to get a soft falloff shape, then restore
        # the original hard core with np.maximum(hard_mask, blurred).
        # Result:
        #   core pixels (hard_mask == 1)  → stay at 1.0  → pure bevel replace
        #   fringe pixels just outside    → 0 < w < 1    → smooth lerp transition
        #   fully flat pixels             → 0.0           → pure base, untouched
        if blur_r > 0:
            sigma = blur_r / 2.0
            kw    = max(1, int(np.ceil(3 * sigma)))
            x     = np.arange(2 * kw + 1, dtype=np.float32) - kw
            k     = np.exp(-0.5 * (x / sigma) ** 2)
            k    /= k.sum()

            blurred = np.apply_along_axis(
                lambda row: np.convolve(row, k, mode="same"), axis=1, arr=hard_mask
            )
            blurred = np.apply_along_axis(
                lambda col: np.convolve(col, k, mode="same"), axis=0, arr=blurred
            )
            # Boost the fringe weights before pinning the core.
            # x3 means one composite press covers what previously took ~3 presses.
            # np.minimum clamps the boosted fringe to 1.0 before the core restore.
            mask = np.maximum(hard_mask, np.minimum(blurred * 3.0, 1.0))
        else:
            mask = hard_mask

        # --- Optional Edit Mode face selection mask ---
        # Rasterize selected faces from ALL objects currently in Edit Mode.
        # Blender allows multi-object editing, so we union masks from every
        # mesh that is in Edit Mode, using their active UV map.
        # We do NOT restrict to the bevel-bake object — the user selects faces
        # on the low-poly mesh (the one whose normal map we are writing to),
        # and the UV space of that mesh is the same UV space as the bake images.
        geo_mask = None
        active_obj = context.active_object
        if (active_obj and active_obj.type == "MESH"
                and active_obj.mode == "EDIT"):
            # Collect every mesh object currently in Edit Mode
            edit_objs = [o for o in context.selected_objects
                         if o.type == "MESH" and o.mode == "EDIT"]
            if not edit_objs and active_obj.mode == "EDIT":
                edit_objs = [active_obj]

            bpy.ops.object.mode_set(mode="OBJECT")

            combined = np.zeros((bh, bw), dtype=np.float32)
            for eo in edit_objs:
                m = _rasterize_selected_faces_uv(eo, bw, bh)
                np.maximum(combined, m, out=combined)  # union
            geo_mask = combined

            # Expand geo mask outward by geo_mask_padding pixels
            pad_r = props.geo_mask_padding
            if pad_r > 0:
                sigma = pad_r / 2.0
                kw    = max(1, int(np.ceil(3 * sigma)))
                x     = np.arange(2 * kw + 1, dtype=np.float32) - kw
                k     = np.exp(-0.5 * (x / sigma) ** 2)
                k    /= k.sum()
                padded = np.apply_along_axis(
                    lambda row: np.convolve(row, k, mode="same"), axis=1, arr=combined
                )
                padded = np.apply_along_axis(
                    lambda col: np.convolve(col, k, mode="same"), axis=0, arr=padded
                )
                # Boost blurred fringe to fill outward, pin original region to 1.0
                geo_mask = np.minimum(np.maximum(combined, padded * 8.0), 1.0)

            bpy.ops.object.mode_set(mode="EDIT")

            n_geo     = int((geo_mask > 0).sum())
            n_bevel   = int((hard_mask > 0).sum())
            n_overlap = int(((geo_mask > 0) & (hard_mask > 0)).sum())

            if n_overlap == 0:
                self.report({"WARNING"},
                            f"Geo mask ({n_geo}px) and bevel mask ({n_bevel}px) "
                            f"do not overlap — select faces that contain bevelled edges.")

        if geo_mask is not None:
            mask = mask * geo_mask

        # --- Composite ---
        # core  (mask == 1.0): pure bevel pixel replaces base pixel exactly
        # fringe (0 < mask < 1): smooth lerp for anti-aliased edge
        # flat  (mask == 0.0): base pixel untouched
        w = mask[:, :, np.newaxis]
        result = base_px.copy()
        result[:, :, :3] = base_px[:, :, :3] * (1.0 - w) + bevel_px[:, :, :3] * w
        result[:, :,  3] = base_px[:, :, 3]

        base_img.pixels.foreach_set(result.reshape(-1))
        base_img.update()
        base_img.update_tag()

        n_written = int((mask > 0.0).sum())
        pct = 100.0 * n_written / (bw * bh)
        blur_info = f", blur {blur_r}px" if blur_r > 0 else ""
        geo_info  = " [face mask]" if geo_mask is not None else ""

        if props.composite_save_external:
            _save_image(base_img, props.composite_base_pick)
            self.report({"INFO"},
                        f"Stamped '{props.composite_bevel_pick}' → "
                        f"'{props.output_name}' ({n_written} px / {pct:.1f}%{blur_info}{geo_info}) — saved")
        else:
            self.report({"INFO"},
                        f"Stamped '{props.composite_bevel_pick}' → "
                        f"'{props.output_name}' ({n_written} px / {pct:.1f}%{blur_info}{geo_info})")
        return {"FINISHED"}


# ------------------------------------------------------------------ #

class BAKE_OT_SaveNormalMap(Operator):
    """Save the base normal map image to /bakes/ next to the .blend"""
    bl_idname  = "bake.save_normal_map"
    bl_label   = "Save Normal Map"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        props = context.scene.bake_props
        name  = props.composite_base_pick
        return (bpy.data.is_saved
                and bool(name) and name != "__NONE__"
                and bpy.data.images.get(name) is not None)

    def execute(self, context):
        props = context.scene.bake_props
        img_name = props.composite_base_pick
        img   = bpy.data.images.get(img_name)
        if img is None:
            self.report({"ERROR"}, f"Image '{img_name}' not found.")
            return {"CANCELLED"}
        _save_image(img, img_name)
        self.report({"INFO"}, f"Saved '{img_name}' to /bakes/")
        return {"FINISHED"}


class BAKE_OT_ViewNormalMap(Operator):
    """Open the base normal map in an Image Editor (splits area if needed)"""
    bl_idname  = "bake.view_normal_map"
    bl_label   = "View"
    bl_options = {"REGISTER"}

    image_name: StringProperty(default="")

    @classmethod
    def poll(cls, context):
        return True   # poll checked per-button via row.enabled

    def execute(self, context):
        img = bpy.data.images.get(self.image_name)
        if img is None:
            self.report({"ERROR"}, f"Image '{self.image_name}' not found.")
            return {"CANCELLED"}
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "IMAGE_EDITOR":
                    area.spaces.active.image = img
                    return {"FINISHED"}
        bpy.ops.screen.area_split(direction="VERTICAL", factor=0.4)
        new_area = context.screen.areas[-1]
        new_area.type = "IMAGE_EDITOR"
        new_area.spaces.active.image = img
        return {"FINISHED"}


# ============================================================ #
#                            PANEL                             #
# ============================================================ #

class BAKE_PT_Main(bpy.types.Panel):
    bl_label       = "Bake Tools"
    bl_idname      = "BAKE_PT_Main"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "WS Toolkit"

    def draw(self, context):
        layout = self.layout
        props  = context.scene.bake_props
        obj    = context.active_object

        # ── Shared settings ───────────────────────────────────────────── #
        box = layout.box()

        # Row 1: size (+ custom field if needed) / depth / padding
        row = box.row(align=True)
        row.prop(props, "bake_size", text="")
        if props.bake_size == "CUSTOM":
            row.prop(props, "bake_size_custom", text="px")
        row.prop(props, "bake_depth", text="")
        row.prop(props, "bake_padding", text="Pad")

        # Row 2: AA / swizzle all on one line
        row = box.row(align=True)
        row.prop(props, "bake_aa", text="")
        row.separator()
        row.prop(props, "swizzle_y", expand=True)

        # ── Tangent Normal ────────────────────────────────────────────── #
        box = layout.box()
        box.label(text="Tangent Normal", icon="NORMALS_FACE")

        # Cage + ray on one row
        row = box.row(align=True)
        row.prop(props, "cage_extrusion", text="Cage")
        row.prop(props, "ray_distance",   text="Ray")

        # Output name preview + view icon
        preview_name = _tangent_name_from_context(context)
        row = box.row(align=True)
        row.scale_y = 0.8
        row.label(text=preview_name, icon="IMAGE_DATA")
        if bpy.data.images.get(preview_name):
            op = row.operator(BAKE_OT_ViewNormalMap.bl_idname, text="", icon="HIDE_OFF")
            op.image_name = preview_name

        # Bake button + save icon flush right
        row = box.row(align=True)
        row.scale_y = 1.3
        row.operator(BAKE_OT_TangentNormal.bl_idname,
                     text="Bake Tangent Normal", icon="RENDER_RESULT")
        row.prop(props, "save_external", text="", icon="DISK_DRIVE")

        # Live bake-set preview (compact, only when selection has meshes)
        sel_meshes = [o for o in context.selected_objects if o.type == "MESH"]
        if sel_meshes:
            sets, orphans = _build_bake_sets(sel_meshes)
            col = box.column(align=True)
            col.scale_y = 0.7
            for s in sets:
                h_names = (", ".join(h.name for h in s["highs"])
                           if s["highs"] else "self")
                col.label(text=f"  {s['low'].name}  ←  {h_names}",
                          icon="OUTLINER_OB_MESH")
            for base in orphans:
                col.label(text=f"  No LOW: {base}", icon="ERROR")

        # ── Bevel Normal ──────────────────────────────────────────────── #
        box = layout.box()
        box.label(text="Bevel Normal", icon="MOD_BEVEL")

        row = box.row(align=True)
        row.prop(props, "bevel_samples", text="Samples")
        row.prop(props, "bevel_radius",  text="Radius")

        bevel_preview = _bevel_name_from_context(context)
        row = box.row(align=True)
        row.scale_y = 0.8
        row.label(text=bevel_preview, icon="IMAGE_DATA")
        if bpy.data.images.get(bevel_preview):
            op = row.operator(BAKE_OT_ViewNormalMap.bl_idname, text="", icon="HIDE_OFF")
            op.image_name = bevel_preview

        row = box.row(align=True)
        row.scale_y = 1.3
        row.enabled = bool(obj and obj.type == "MESH"
                           and len(context.selected_objects) == 1)
        row.operator(BAKE_OT_BevelNormal.bl_idname,
                     text="Bake Bevel Normal", icon="RENDER_RESULT")
        row.prop(props, "bevel_save_external", text="", icon="DISK_DRIVE")

        # ── Composite ─────────────────────────────────────────────────── #
        box = layout.box()
        box.label(text="Composite Bevel → Normal", icon="OVERLAY")

        in_edit = bool(obj and obj.type == "MESH" and obj.mode == "EDIT")

        # Base normal picker row
        row = box.row(align=True)
        row.scale_y = 0.8
        normal_images = [img for img in bpy.data.images if img.name.endswith("_normal")]
        if normal_images:
            if in_edit:
                row.label(text=props.composite_base_pick or normal_images[0].name,
                          icon="IMAGE_DATA")
            else:
                row.prop(props, "composite_base_pick", text="", icon="IMAGE_DATA")
            base_picked = bpy.data.images.get(props.composite_base_pick)
            if base_picked:
                op = row.operator(BAKE_OT_ViewNormalMap.bl_idname, text="", icon="HIDE_OFF")
                op.image_name = base_picked.name
        else:
            row.label(text="No *_normal images — bake first", icon="ERROR")

        # Bevel picker row
        row = box.row(align=True)
        row.scale_y = 0.8
        bevel_images = [img for img in bpy.data.images if img.name.endswith("_bevel")]
        if bevel_images:
            if in_edit:
                row.label(text=props.composite_bevel_pick or bevel_images[0].name,
                          icon="MOD_BEVEL")
            else:
                row.prop(props, "composite_bevel_pick", text="", icon="MOD_BEVEL")
            picked = bpy.data.images.get(props.composite_bevel_pick)
            if picked:
                op = row.operator(BAKE_OT_ViewNormalMap.bl_idname, text="", icon="HIDE_OFF")
                op.image_name = picked.name
        else:
            row.label(text="No *_bevel images", icon="ERROR")

        # Blur + geo padding (shown only in edit mode)
        row = box.row(align=True)
        row.prop(props, "mask_blur_radius", text="Blur", slider=True)
        if in_edit:
            row.prop(props, "geo_mask_padding", text="Pad", slider=True)

        if in_edit:
            hint = box.row()
            hint.scale_y = 0.7
            hint.label(text="Selected faces only", icon="EDITMODE_HLT")

        base_name = props.composite_base_pick
        base_img  = bpy.data.images.get(base_name) if base_name not in ("", "__NONE__") else None
        base_ok   = base_img is not None
        bevel_pick = props.composite_bevel_pick
        bevel_ok = (bevel_pick not in ("", "__NONE__")
                    and bpy.data.images.get(bevel_pick) is not None)

        # Composite button + save icon + optional save-to-disk button
        row = box.row(align=True)
        row.scale_y = 1.3
        row.enabled = base_ok and bevel_ok
        row.operator(BAKE_OT_CompositeBevelOntoNormal.bl_idname,
                     text="Composite", icon="OVERLAY")
        row.prop(props, "composite_save_external", text="", icon="DISK_DRIVE")
        if base_img:
            sub = row.row(align=True)
            sub.enabled = bpy.data.is_saved
            sub.operator(BAKE_OT_SaveNormalMap.bl_idname, text="", icon="FILE_TICK")


# ============================================================ #
#                       REGISTRATION                           #
# ============================================================ #

classes = (
    BAKE_Props,
    BAKE_OT_TangentNormal,
    BAKE_OT_BevelNormal,
    BAKE_OT_CompositeBevelOntoNormal,
    BAKE_OT_SaveNormalMap,
    BAKE_OT_ViewNormalMap,
    BAKE_PT_Main,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bake_props = bpy.props.PointerProperty(type=BAKE_Props)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.bake_props
