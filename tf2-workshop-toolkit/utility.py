"""
Workshop Toolkit – Utility Operations Module
Misc helpers: cosmetic base extraction, global pose toggle, armature assignment,
and temp diffuse texture generation for in-game preview.
"""

import bpy
import os
import numpy as np
from bpy.props import StringProperty, EnumProperty, BoolProperty, FloatProperty
from bpy.types import Operator, Panel

BAKE_SIZE  = 1024
EXPORT_SIZE = 512


# ============================================================ #
#                       HELPER FUNCTIONS                       #
# ============================================================ #

def get_target_assets(self, context):
    items = []
    for item in context.scene.tf2_assets:
        if not item.is_library:
            items.append((item.name, item.name, ""))
    if not items:
        items.append(("NONE", "No Registered Assets Found", ""))
    return items


def _collect_asset_materials(asset_name):
    """
    Return the unique materials actually assigned to meshes in
    `<asset_name>_lod0`, in encounter order. Used by the temp-diffuse
    pipeline so it wires into the asset's REAL materials regardless of
    what they're named — the All-Class operator renames asset/collection
    names but deliberately leaves materials alone, so 'A_<asset>' guesses
    no longer hold for class-prefixed assets.
    """
    coll = bpy.data.collections.get(asset_name + "_lod0")
    if not coll:
        return []
    seen = []
    for obj in coll.objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            if slot.material and slot.material not in seen:
                seen.append(slot.material)
    return seen


def _force_show(colls, objs):
    """Unhide collections and objects, return state for restore."""
    coll_state = [(c, c.hide_viewport, c.hide_render) for c in colls]
    obj_state  = [(o, o.hide_viewport, o.hide_render) for o in objs]
    for c in colls:
        c.hide_viewport = False
        c.hide_render   = False
    for o in objs:
        o.hide_viewport = False
        o.hide_render   = False
        o.hide_set(False)
    return coll_state, obj_state


def _restore_show(coll_state, obj_state):
    for c, hv, hr in coll_state:
        c.hide_viewport = hv
        c.hide_render   = hr
    for o, hv, hr in obj_state:
        o.hide_viewport = hv
        o.hide_render   = hr


def _tmp_image(name, w, h, float_buf=True):
    """Create or clear an image for baking into."""
    img = bpy.data.images.get(name)
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, width=w, height=h,
                               alpha=False, float_buffer=float_buf)
    img.colorspace_settings.name = "Non-Color"
    return img


def _inject_bake_node(mat, image):
    """Active+selected Image Texture node in every material slot."""
    if not mat.use_nodes:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    for n in nodes:
        n.select = False
    node = next(
        (n for n in nodes if n.type == "TEX_IMAGE" and n.label == "_wstk_tmp_bake"),
        None,
    )
    if node is None:
        node = nodes.new("ShaderNodeTexImage")
        node.label    = "_wstk_tmp_bake"
        node.location = (-300, -600)
    node.image   = image
    node.select  = True
    nodes.active = node
    return node


def _remove_bake_node(mat):
    if mat and mat.use_nodes:
        for n in list(mat.node_tree.nodes):
            if n.type == "TEX_IMAGE" and n.label == "_wstk_tmp_bake":
                mat.node_tree.nodes.remove(n)


def _prepare(obj, image):
    records = []
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name="UVMap")
    if not obj.data.materials:
        tmp = bpy.data.materials.new(name=f"_tmp_{obj.name}")
        tmp.use_nodes = True
        obj.data.materials.append(tmp)
        _inject_bake_node(tmp, image)
        records.append((tmp, True))
    else:
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                mat = bpy.data.materials.new(name=f"_tmp_slot_{obj.name}")
                mat.use_nodes = True
                slot.material = mat
                _inject_bake_node(mat, image)
                records.append((mat, True))
            else:
                _inject_bake_node(mat, image)
                records.append((mat, False))
    return records


def _cleanup(obj, records):
    slot_mats = {s.material for s in obj.material_slots}
    for mat, was_tmp in records:
        if was_tmp and mat in slot_mats:
            for slot in obj.material_slots:
                if slot.material == mat:
                    slot.material = None
            bpy.data.materials.remove(mat, do_unlink=True)
        else:
            _remove_bake_node(mat)


def _bake(context, objs, image, bake_type, **kwargs):
    """Bake *bake_type* for each obj in *objs* into *image*."""
    records_all = {}
    for obj in objs:
        records_all[obj] = _prepare(obj, image)

    first = True
    for obj in objs:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.bake(
            type=bake_type,
            margin=4,
            use_clear=first,
            **kwargs,
        )
        first = False

    for obj, records in records_all.items():
        _cleanup(obj, records)


def _lighting_from_object_normal(osn_img):
    """
    Compute a static top-down lighting layer from an object-space normal bake.

    Object-space normals are in a consistent world-aligned frame: the Y axis
    (green channel) genuinely means "facing up" regardless of UV layout or
    face orientation, unlike tangent-space normals whose axes are UV-relative.

    Decode green from [0,1] to [-1,1], remap to [0.35, 1.0] so nothing
    goes fully black.  Returns a (H, W) float32 array.
    """
    px = _pixels(osn_img)            # (H, W, 4), float32
    # Blender world up = Z axis = blue channel (index 2) of OSN bake.
    # Green (index 1) = Y = front/back, which caused front-face darkening.
    b  = px[:, :, 2] * 2.0 - 1.0    # decode blue: [0,1] → [-1,1]
    # Remap: top faces (b≈1) → 1.0, bottom faces (b≈-1) → 0.35
    # Half strength: compress range toward neutral (0.5 in decoded space)
    light = 0.675 + 0.325 * b * 0.8
    return np.clip(light, 0.415, 1.0)


def _pixels(img):
    """Return (H, W, 4) float32 array from image."""
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    return px.reshape((h, w, 4))


def _write_pixels(img, arr):
    img.pixels.foreach_set(arr.reshape(-1).astype(np.float32))
    img.update()
    img.update_tag()


def _gaussian_blur(arr, radius):
    """Separable Gaussian blur on a 2-D float array."""
    if radius <= 0:
        return arr
    sigma = radius / 2.0
    kw    = max(1, int(np.ceil(3 * sigma)))
    x     = np.arange(2 * kw + 1, dtype=np.float32) - kw
    k     = np.exp(-0.5 * (x / sigma) ** 2)
    k    /= k.sum()
    out = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 1, arr)
    out = np.apply_along_axis(lambda c: np.convolve(c, k, mode="same"), 0, out)
    return np.clip(out, 0.0, 1.0)


def _save_tga(image, out_path, resize_to=None):
    """Save *image* (optionally resized) as TGA to *out_path*."""
    import numpy as np

    if resize_to and (image.size[0] != resize_to or image.size[1] != resize_to):
        # Copy pixels into a fresh 8-bit image at the target size.
        # image.copy().scale() can silently zero out pixel data on non-float
        # images in some Blender versions — safer to resample in numpy.
        sw, sh = image.size[0], image.size[1]
        px = np.empty(sw * sh * 4, dtype=np.float32)
        image.pixels.foreach_get(px)
        px = px.reshape((sh, sw, 4))

        # Nearest-neighbour resample (fast, sufficient for 1024→512)
        tw, th = resize_to, resize_to
        y_idx = (np.arange(th) * sh // th).astype(np.int32)
        x_idx = (np.arange(tw) * sw // tw).astype(np.int32)
        resampled = px[np.ix_(y_idx, x_idx)].reshape(-1).astype(np.float32)

        img = bpy.data.images.new("_tmp_save_resize", width=tw, height=th,
                                  alpha=False, float_buffer=False)
        img.colorspace_settings.name = "Non-Color"
        img.pixels.foreach_set(resampled)
        img.update()
    else:
        img = image

    img.filepath_raw = out_path
    img.file_format  = "TARGA"
    img.save()

    if img is not image:
        bpy.data.images.remove(img)


# ============================================================ #
#                          OPERATORS                           #
# ============================================================ #

class UTILITY_OT_GenTempDiffuse(Operator):
    """Bake a shaded diffuse preview texture and save it to /textures/{asset}_temp/ for in-engine testing."""
    bl_idname  = "utility.gen_temp_diffuse"
    bl_label   = "Generate Temp Diffuse"
    bl_options = {"REGISTER", "UNDO"}

    asset_name: EnumProperty(name="Asset", items=get_target_assets)

    @classmethod
    def poll(cls, context):
        return bool(context.scene.tf2_assets) and bpy.data.is_saved

    def invoke(self, context, event):
        assets = [i.name for i in context.scene.tf2_assets if not i.is_library]
        if not assets:
            self.report({"ERROR"}, "No registered assets found.")
            return {"CANCELLED"}
        if len(assets) == 1:
            self.asset_name = assets[0]
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        name = self.asset_name
        if not name or name == "NONE":
            self.report({"ERROR"}, "No asset selected.")
            return {"CANCELLED"}

        if not bpy.data.is_saved:
            self.report({"ERROR"}, "Save the .blend file first.")
            return {"CANCELLED"}

        # Gather low meshes from _lod0
        low_coll = bpy.data.collections.get(name + "_lod0")
        if not low_coll:
            self.report({"ERROR"}, f"Collection '{name}_lod0' not found.")
            return {"CANCELLED"}
        low_meshes = [o for o in low_coll.objects if o.type == "MESH"]
        if not low_meshes:
            self.report({"ERROR"}, f"No meshes in '{name}_lod0'.")
            return {"CANCELLED"}

        # Force-show lod0 only (highs not needed for diffuse)
        coll_state, obj_state = _force_show([low_coll], low_meshes)

        scene  = context.scene
        cycles = scene.cycles
        prev_engine  = scene.render.engine
        prev_device  = cycles.device
        prev_samples = cycles.samples
        prev_sel     = list(context.selected_objects)
        prev_active  = context.view_layer.objects.active

        scene.render.engine = "CYCLES"
        cycles.device        = "GPU"

        W = BAKE_SIZE

        try:
            # ── Per-material pipeline ─────────────────────────────────── #
            # Group low meshes by their slot-0 material so that meshes
            # sharing the same material (common with Z_ body-part splits)
            # bake into one shared image rather than recreating and freeing
            # the same image datablock on each pass (which causes a
            # ReferenceError when the save loop tries to use the freed ref).
            cycles.samples = 1

            # Collect asset materials for the normal-map search later
            asset_mats = _collect_asset_materials(name)

            # Build ordered {mat_stem: [obj, ...]} — insertion order preserved
            from collections import OrderedDict
            mat_groups = OrderedDict()
            for obj in low_meshes:
                mat      = obj.data.materials[0] if obj.data.materials else None
                mat_stem = mat.name if mat else obj.name
                mat_groups.setdefault(mat_stem, []).append(obj)

            # (mat_stem, diff_img) pairs accumulated for the save step
            low_results = []

            for mat_stem, group_objs in mat_groups.items():

                # ── 1. OSN bake — all meshes of this material, isolated ── #
                osn_img   = _tmp_image(f"_tmp_{mat_stem}_osn", W, W)
                other_lows = [o for o in low_meshes if o not in group_objs]

                first_in_group = True
                for obj in group_objs:
                    # Hide every low that isn't in this material group
                    saved_hide = [(o, o.hide_viewport, o.hide_render) for o in other_lows]
                    for o in other_lows:
                        o.hide_viewport = True
                        o.hide_render   = True

                    records = _prepare(obj, osn_img)
                    bpy.ops.object.select_all(action="DESELECT")
                    obj.select_set(True)
                    context.view_layer.objects.active = obj
                    bpy.ops.object.bake(
                        type="NORMAL",
                        normal_space="OBJECT",
                        margin=4,
                        use_clear=first_in_group,
                    )
                    first_in_group = False
                    _cleanup(obj, records)

                    for o, hv, hr in saved_hide:
                        o.hide_viewport = hv
                        o.hide_render   = hr

                # ── 2. Read base color from material BSDF ────────────── #
                # default_value on the Base Color socket always holds the
                # raw RGB the user set in the node editor, even when a
                # texture is connected — so this works correctly both on
                # first bake and on re-bake when _tmp_diffuse_tex is already
                # wired in.  We only use it when Base Color is either
                # unconnected or driven by our own temp node; if it's driven
                # by some other real texture node we leave tint as white so
                # we don't double-apply an arbitrary color.
                base_color = (1.0, 1.0, 1.0)
                group_mat = group_objs[0].data.materials[0] if group_objs[0].data.materials else None
                if group_mat and group_mat.use_nodes:
                    bsdf_pre = next(
                        (n for n in group_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"),
                        None,
                    )
                    if bsdf_pre:
                        bc_input = bsdf_pre.inputs["Base Color"]
                        # Check what (if anything) is driving Base Color
                        driving_link = next(
                            (lnk for lnk in group_mat.node_tree.links
                             if lnk.to_node == bsdf_pre
                             and lnk.to_socket.name == "Base Color"),
                            None,
                        )
                        use_default = (
                            driving_link is None  # nothing connected
                            or (                  # our own temp node connected
                                driving_link.from_node.type == "TEX_IMAGE"
                                and driving_link.from_node.label == "_tmp_diffuse_tex"
                            )
                        )
                        if use_default:
                            r, g, b, _ = bc_input.default_value
                            base_color = (r, g, b)

                # ── 3. Composite in numpy (per-material group) ────────── #
                osn_px = _pixels(osn_img)
                light  = _lighting_from_object_normal(osn_img)  # (H,W)

                osn_rgb  = osn_px[:, :, :3]
                osn_mag  = np.sqrt(np.sum(osn_rgb ** 2, axis=2))
                osn_blur = _gaussian_blur(osn_mag, 3)
                cavity   = osn_mag - osn_blur
                c_min, c_max = cavity.min(), cavity.max()
                if c_max > c_min:
                    cavity = (cavity - c_min) / (c_max - c_min)
                else:
                    cavity = np.zeros_like(cavity)
                cavity_shadow = cavity * 0.45

                lit_final = np.clip(0.75 * light - cavity_shadow, 0.0, 1.0)

                linear_r = lit_final * base_color[0]
                linear_g = lit_final * base_color[1]
                linear_b = lit_final * base_color[2]

                # Convert linear → sRGB so the saved TGA looks correct in
                # external apps (Photoshop etc.) that assume sRGB input.
                # Blender works in linear internally, so without this the
                # file looks very dark when opened outside Blender.
                def _to_srgb(c):
                    c = np.clip(c, 0.0, 1.0)
                    return np.where(
                        c <= 0.0031308,
                        c * 12.92,
                        1.055 * np.power(c, 1.0 / 2.4) - 0.055,
                    )

                result_px = np.ones((W, W, 4), dtype=np.float32)
                result_px[:, :, 0] = _to_srgb(linear_r)
                result_px[:, :, 1] = _to_srgb(linear_g)
                result_px[:, :, 2] = _to_srgb(linear_b)

                # OSN no longer needed after pixel extraction
                bpy.data.images.remove(osn_img)

                # ── 4. Create persistent diffuse image for this material ─ #
                diff_img_name = f"{mat_stem}_temp_diffuse"
                diff_img = bpy.data.images.get(diff_img_name)
                if diff_img:
                    bpy.data.images.remove(diff_img)
                diff_img = bpy.data.images.new(diff_img_name, width=W, height=W,
                                               alpha=False, float_buffer=False)
                diff_img.colorspace_settings.name = "Non-Color"
                _write_pixels(diff_img, result_px)

                # ── 5. Wire into every mesh in this group's material ───── #
                # All objects in the group share mat_stem as slot-0 material,
                # so we only need to wire it once via the material itself.
                # group_mat already resolved above in the base-color step.
                if group_mat and group_mat.use_nodes:
                    nodes = group_mat.node_tree.nodes
                    links = group_mat.node_tree.links
                    bsdf  = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
                    if bsdf:
                        img_node = next(
                            (n for n in nodes if n.type == "TEX_IMAGE"
                             and n.label == "_tmp_diffuse_tex"), None
                        )
                        if img_node is None:
                            img_node = nodes.new("ShaderNodeTexImage")
                            img_node.label    = "_tmp_diffuse_tex"
                            img_node.location = (bsdf.location.x - 320,
                                                 bsdf.location.y + 200)
                        img_node.image = diff_img
                        already_linked = any(
                            lnk.to_node == bsdf
                            and lnk.to_socket.name == "Base Color"
                            and lnk.from_node == img_node
                            for lnk in links
                        )
                        if not already_linked:
                            links.new(img_node.outputs["Color"],
                                      bsdf.inputs["Base Color"])

                low_results.append((mat_stem, diff_img))

            # ── 5. Collect normal map images (one per material) ───────── #
            normal_imgs = []
            seen_normal_names = set()
            for mat in asset_mats:
                if not mat or not mat.use_nodes:
                    continue
                for node in mat.node_tree.nodes:
                    if (node.type == "TEX_IMAGE"
                            and node.label == "_asset_normal_tex"
                            and node.image
                            and node.image.name not in seen_normal_names):
                        normal_imgs.append(node.image)
                        seen_normal_names.add(node.image.name)

            # Last-resort fallback using material/asset name patterns
            if not normal_imgs:
                candidates = [f"{m.name}_normal" for m in asset_mats]
                candidates.extend([f"A_{name}_normal", f"{name}_normal"])
                for cand in candidates:
                    img = bpy.data.images.get(cand)
                    if img and cand not in seen_normal_names:
                        normal_imgs.append(img)
                        seen_normal_names.add(cand)

            # ── 6. Save all outputs ───────────────────────────────────── #
            blend_dir = os.path.dirname(bpy.data.filepath)
            out_dir   = os.path.join(blend_dir, "textures", f"{name}_temp")
            os.makedirs(out_dir, exist_ok=True)

            saved_diffuse = []
            for mat_stem, diff_img in low_results:
                diff_path = os.path.join(out_dir, f"{mat_stem}_temp.tga")
                _save_tga(diff_img, diff_path, resize_to=EXPORT_SIZE)
                saved_diffuse.append(diff_path)

            saved_normals = []
            for norm_img in normal_imgs:
                if not norm_img.has_data:
                    norm_img.reload()
                if norm_img.has_data:
                    norm_stem = norm_img.name.replace("_normal", "")
                    norm_path = os.path.join(out_dir, f"{norm_stem}_normal_temp.tga")
                    _save_tga(norm_img, norm_path, resize_to=EXPORT_SIZE)
                    saved_normals.append(norm_path)

            if saved_normals:
                self.report({"INFO"},
                            f"Saved {len(saved_diffuse)} diffuse + "
                            f"{len(saved_normals)} normal(s) to {out_dir}")
            elif saved_diffuse:
                self.report({"WARNING"},
                            f"Saved {len(saved_diffuse)} diffuse(s) to {out_dir}. "
                            f"No normal map found — bake the normal first.")
            else:
                self.report({"WARNING"}, "Nothing saved — check your asset setup.")

        finally:
            # OSN images are removed inline above; guard against any
            # remaining if an exception occurred mid-loop.
            for mat_stem in (
                (obj.data.materials[0].name if obj.data.materials and obj.data.materials[0]
                 else obj.name)
                for obj in low_meshes
            ):
                leftover = bpy.data.images.get(f"_tmp_{mat_stem}_osn")
                if leftover:
                    bpy.data.images.remove(leftover)

            _restore_show(coll_state, obj_state)
            scene.render.engine = prev_engine
            cycles.device        = prev_device
            cycles.samples       = prev_samples
            bpy.ops.object.select_all(action="DESELECT")
            for o in prev_sel:
                try: o.select_set(True)
                except Exception: pass
            context.view_layer.objects.active = prev_active

        return {"FINISHED"}


class UTILITY_OT_ExtractCosmeticBase(Operator):
    bl_idname = "utility.extract_cosmetic_base"
    bl_label = "Extract Cosmetic Base"
    bl_description = (
        "Duplicates selection, cleans data, applies adjustable normal displacement, "
        "routes to asset folder, and applies material"
    )
    bl_options = {"REGISTER", "UNDO"}

    target_asset: EnumProperty(name="Send To", items=get_target_assets)
    displacement: FloatProperty(
        name="Displacement", default=0.02, soft_min=0.0, soft_max=0.2,
        precision=4, subtype='DISTANCE', unit='LENGTH',
        description="Offset the extracted mesh along its normals in object-space units. Positive moves outward, zero keeps the original surface, negative moves inward; default 0.02 matches the previous extraction")

    @classmethod
    def poll(cls, context):
        return (
            context.active_object
            and context.active_object.mode == "EDIT"
            and context.active_object.type == "MESH"
        )

    def invoke(self, context, event):
        items = [item.name for item in context.scene.tf2_assets if not item.is_library]
        if len(items) == 1:
            self.target_asset = items[0]
        elif not items:
            self.target_asset = "NONE"
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        if any(not item.is_library for item in context.scene.tf2_assets):
            layout.prop(self, 'target_asset')
        else:
            layout.label(text='No asset folder; extract into the current collection.')
        layout.prop(self, 'displacement')
        layout.label(text='Positive = outward; 0 = unchanged; negative = inward.')

    def execute(self, context):
        orig_obj = context.active_object

        try:
            bpy.ops.mesh.duplicate()
            bpy.ops.mesh.separate(type="SELECTED")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to separate: {e}")
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode="OBJECT")

        new_obj = None
        for obj in context.selected_objects:
            if obj != orig_obj:
                new_obj = obj
                break

        if not new_obj:
            self.report({"WARNING"}, "Nothing was selected to separate!")
            bpy.ops.object.mode_set(mode="EDIT")
            return {"CANCELLED"}

        bpy.ops.object.select_all(action="DESELECT")
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj
        new_obj.name = "Cosmetic_Base_Mesh"

        if new_obj.data.shape_keys:
            new_obj.shape_key_clear()

        try:
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        except Exception:
            pass

        new_obj.data.materials.clear()
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

        if self.displacement != 0:
            mod = new_obj.modifiers.new(name="Base_Displace", type="DISPLACE")
            mod.direction = 'NORMAL'
            mod.strength = self.displacement
            mod.mid_level = 0.0
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except Exception as e:
                self.report({"WARNING"}, f"Could not apply displace modifier: {e}")

        if self.target_asset and self.target_asset != "NONE":
            target_col_name = self.target_asset + "_lod0"
            target_col = bpy.data.collections.get(target_col_name)

            # Resolve the asset's primary material from its lod0 meshes
            # rather than guessing 'A_<asset>' — All-Class-prefixed assets
            # share the original (unprefixed) material name.
            asset_mats = _collect_asset_materials(self.target_asset)
            target_mat = asset_mats[0] if asset_mats else None
            if target_mat:
                new_obj.data.materials.append(target_mat)
            else:
                self.report(
                    {"WARNING"},
                    f"No material found on '{self.target_asset}' lod0. "
                    f"Mesh left without material.",
                )

            if target_col:
                for col in new_obj.users_collection:
                    col.objects.unlink(new_obj)
                target_col.objects.link(new_obj)
                self.report(
                    {"INFO"},
                    f"Cosmetic Base extracted, material applied, & sent to {target_col_name}",
                )
            else:
                self.report(
                    {"WARNING"},
                    f"Collection {target_col_name} not found! Left in current location.",
                )
        else:
            self.report({"INFO"}, "Cosmetic Base extracted (no asset folder to route to)")

        bpy.ops.object.select_all(action="DESELECT")
        orig_obj.select_set(True)
        context.view_layer.objects.active = orig_obj
        bpy.ops.object.mode_set(mode="EDIT")

        return {"FINISHED"}


class UTILITY_OT_toggle_pose_state(Operator):
    bl_idname = "utility.toggle_pose_state"
    bl_label = "Toggle Global Pose"
    bl_description = "Switch all armatures between Pose and Rest position"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        scene.tf2_pose_state = not scene.tf2_pose_state
        target_state = "POSE" if scene.tf2_pose_state else "REST"
        for obj in bpy.data.objects:
            if obj.type == "ARMATURE":
                obj.data.pose_position = target_state
        self.report({"INFO"}, f"Global State: {target_state}")
        return {"FINISHED"}


class UTILITY_OT_AddArmatureModifier(Operator):
    """Adds an Armature modifier to selected meshes. Replaces existing ones."""
    bl_idname = "utility.add_armature_modifier"
    bl_label = "Add Armature Modifier"
    bl_options = {"REGISTER", "UNDO"}

    armature_name: bpy.props.EnumProperty(
        name="Select Armature",
        description="Choose the armature to use as the target",
        items=lambda self, context: [
            (obj.name, obj.name, "")
            for obj in context.scene.objects
            if obj.type == "ARMATURE"
        ],
    )

    def execute(self, context):
        target_arm = bpy.data.objects.get(self.armature_name)
        if not target_arm:
            self.report({"ERROR"}, "Selected armature no longer exists.")
            return {"CANCELLED"}

        selected_meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
        if not selected_meshes:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        for obj in selected_meshes:
            for mod in obj.modifiers:
                if mod.type == "ARMATURE":
                    obj.modifiers.remove(mod)
            arm_mod = obj.modifiers.new(name="Armature", type="ARMATURE")
            arm_mod.object = target_arm

        self.report(
            {"INFO"},
            f"Armature '{target_arm.name}' assigned to {len(selected_meshes)} meshes.",
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        armatures = [obj for obj in context.scene.objects if obj.type == "ARMATURE"]
        if not armatures:
            self.report({"WARNING"}, "No armatures found in the scene.")
            return {"CANCELLED"}
        if len(armatures) == 1:
            self.armature_name = armatures[0].name
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self)



class UTILITY_OT_ExportPreviewFBX(Operator):
    """Export checked LOD0 meshes and the first reference merc for Substance Painter. Keeps the current pose, without a skeleton. Writes to /bakes/ beside your saved .blend"""
    bl_idname  = "utility.export_preview_fbx"
    bl_label   = "Painter Preview FBX"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if not bpy.data.is_saved:
            cls.poll_message_set("Save your .blend before exporting a Painter preview")
            return False
        if not context.scene.tf2_assets:
            cls.poll_message_set("Create a cosmetic asset or spawn a reference merc first")
            return False
        return True

    def execute(self, context):
        if not bpy.data.is_saved:
            self.report({"ERROR"}, "Save the .blend file first.")
            return {"CANCELLED"}

        scene = context.scene

        # Collect objects to export
        export_objs = []

        # 1. Flagged assets — meshes from their _lod0 collection
        for item in scene.tf2_assets:
            if item.is_library or not item.do_export:
                continue
            coll = bpy.data.collections.get(item.name + "_lod0")
            if not coll:
                continue
            for obj in coll.objects:
                if obj.type == "MESH":
                    export_objs.append(obj)

        # 2. Reference/library asset — meshes from _morphs_low_lod0
        for item in scene.tf2_assets:
            if not item.is_library:
                continue
            coll = bpy.data.collections.get(item.name + "_morphs_low_lod0")
            if not coll:
                continue
            for obj in coll.objects:
                if obj.type == "MESH":
                    export_objs.append(obj)
            break  # only the first library asset

        if not export_objs:
            self.report({"WARNING"},
                        "Nothing to export — flag at least one asset for export "
                        "or register a library/reference asset.")
            return {"CANCELLED"}

        # Force-show all objects so the exporter can see them
        prev_hide = [(o, o.hide_viewport, o.hide_render) for o in export_objs]
        for obj in export_objs:
            obj.hide_viewport = False
            obj.hide_render   = False
            obj.hide_set(False)

        # Select only our export objects
        prev_sel    = list(context.selected_objects)
        prev_active = context.view_layer.objects.active

        bpy.ops.object.select_all(action="DESELECT")
        for obj in export_objs:
            obj.select_set(True)
        if export_objs:
            context.view_layer.objects.active = export_objs[0]

        # Export
        blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
        out_dir    = os.path.join(os.path.dirname(bpy.data.filepath), "bakes")
        os.makedirs(out_dir, exist_ok=True)
        fbx_path   = os.path.join(out_dir, f"{blend_name}_substance.fbx")

        bpy.ops.export_scene.fbx(
            filepath        = fbx_path,
            use_selection   = True,
            object_types    = {"MESH"},   # no armature
            bake_anim       = False,
            use_mesh_modifiers = True,    # default fbx behaviour
        )

        # Restore selection and visibility
        bpy.ops.object.select_all(action="DESELECT")
        for o in prev_sel:
            try: o.select_set(True)
            except Exception: pass
        context.view_layer.objects.active = prev_active

        for obj, hv, hr in prev_hide:
            obj.hide_viewport = hv
            obj.hide_render   = hr

        self.report({"INFO"},
                    f"Preview FBX exported: {len(export_objs)} meshes → {fbx_path}")
        if not bpy.app.background:
            bpy.ops.tf2.export_result("INVOKE_DEFAULT", directory=out_dir,
                                     message=f"Exported Painter preview ({len(export_objs)} meshes)")
        return {"FINISHED"}


# ============================================================ #
#              REPROJECT DIFFUSE — TWO-BUTTON APPROACH         #
# ============================================================ #

REPROJECT_MAP_TYPES = (
    ('DIFFUSE', 'Diffuse', 'Reproject reference base color'),
    ('NORMAL', 'Normal', 'Rebake reference normals into the cosmetic tangent space'),
    ('SPECULAR', 'Specular', 'Reproject the reference normal texture alpha channel as a grayscale specular map'),
)


class UTILITY_OT_ReprojectDiffuse(Operator):
    """Reproject diffuse, normal, or normal-alpha Specular from the reference onto the active cosmetic"""
    bl_idname  = "utility.reproject_diffuse"
    bl_label   = "Reproject Texture"
    bl_options = {"REGISTER", "UNDO"}

    map_type: EnumProperty(name='Map', items=REPROJECT_MAP_TYPES, default='DIFFUSE')
    source_mesh: StringProperty(
        name='Source Mesh',
        description='Reference mesh to project from. Hidden meshes and meshes in hidden or excluded collections can be used; the active mesh is the cosmetic target')

    apply_result: BoolProperty(
        name="Apply to Cosmetic", default=True,
        description="Connect the result to the matching cosmetic input: Base Color, Normal, or Specular IOR Level; shared materials are copied")
    show_preview: BoolProperty(
        name="Open Texture Preview", default=True,
        description="Open the finished texture in a separate Image Editor window")
    ray_extrusion: FloatProperty(
        name="Extrusion", default=1.0, min=0, soft_max=5, subtype='DISTANCE', unit='LENGTH',
        description="Move ray origins outward along cosmetic normals. Use the smallest distance that covers the reference; large values can hit nearby overlapping surfaces")
    max_ray_distance: FloatProperty(
        name="Max Ray Distance", default=0.0, min=0, soft_max=10, subtype='DISTANCE', unit='LENGTH',
        description="Limit how far projection rays can search. Zero is unlimited; smaller values can reduce distant surface bleeding but may leave unbaked gaps")

    @classmethod
    def poll(cls, context):
        if not bpy.data.is_saved:
            cls.poll_message_set("Save your .blend file before reprojection")
            return False
        if context.mode != 'OBJECT':
            cls.poll_message_set("Switch to Object Mode for reprojection")
            return False
        if (context.active_object is None or context.active_object.type != 'MESH'
                or context.active_object not in context.selected_objects):
            cls.poll_message_set("Select the cosmetic mesh; choose a reference in the Source Mesh picker")
            return False
        return True

    def invoke(self, context, event):
        sources = [o for o in context.selected_objects if o.type == 'MESH' and o != context.active_object]
        if len(sources) == 1:
            self.source_mesh = sources[0].name
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop_search(self, 'source_mesh', context.scene, 'objects', text='Source Mesh')
        layout.label(text=f"Cosmetic: {context.active_object.name}", icon='MESH_DATA')
        layout.prop(self, 'map_type')
        if self.map_type == 'NORMAL':
            layout.prop(context.scene.bake_props, 'swizzle_y', text='Normal Y')
        elif self.map_type == 'SPECULAR':
            layout.label(text='Source: normal texture alpha channel')
        layout.prop(self, 'apply_result')
        layout.prop(self, 'show_preview')
        layout.separator()
        layout.prop(context.scene.bake_props, 'bake_padding', text='Padding (px)')
        layout.prop(self, 'ray_extrusion')
        layout.prop(self, 'max_ray_distance')
        col = layout.column(align=True)
        col.label(text='For bleeding, try smaller projection distances.')
        col.label(text='Too small can leave gaps. Ray distance 0 = unlimited.')

    def execute(self, context):
        from . import reproject
        return reproject.execute(self, context)


class UTILITY_OT_TransferJiggleHierarchy(Operator):
    """Sync j_ / jiggle_ prefixes and _j / _jiggle suffixes across rigs, including hidden rigs. Select the source rig first; its bones take priority. Restores selection and mode"""
    bl_idname  = "utility.transfer_jiggle_hierarchy"
    bl_label   = "Sync Jiggle Bones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        armatures = [obj for obj in bpy.data.objects
                     if obj.type == 'ARMATURE' and obj.is_editable and obj.data.is_editable]
        if len(armatures) < 2:
            self.report({'WARNING'}, "Need at least two editable armature objects. Mesh vertex groups are not target rigs.")
            return {'CANCELLED'}

        active = context.view_layer.objects.active
        selected = list(context.selected_objects)
        mode = active.mode if active else 'OBJECT'
        states = [(arm, arm.hide_viewport, arm.hide_select,
                   arm.hide_get() if arm.name in context.view_layer.objects else False)
                  for arm in armatures]
        temporary = None
        created = 0
        updated = 0
        try:
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            # Read rest bones without entering Edit Mode. Prefer the active
            # source rig if other rigs already contain older copies.
            jiggle_registry = {}
            for arm in sorted(armatures, key=lambda obj: obj == active):
                for bone in arm.data.bones:
                    if (bone.name.startswith(("jiggle_", "j_"))
                            or bone.name.endswith(("_j", "_jiggle"))) and bone.parent:
                        jiggle_registry[bone.name] = {
                            'parent_name': bone.parent.name,
                            'rel_matrix': bone.parent.matrix_local.inverted() @ bone.matrix_local,
                            'length': bone.length,
                        }
            if not jiggle_registry:
                self.report({'WARNING'}, "No parented jiggle bones found. Use j_name, jiggle_name, name_j or name_jiggle.")
                return {'CANCELLED'}

            temporary = bpy.data.collections.new('_tf2_jiggle_sync_temp')
            context.scene.collection.children.link(temporary)
            for arm in armatures:
                temporary.objects.link(arm)
                arm.hide_viewport = False
                arm.hide_select = False
            context.view_layer.update()
            for arm in armatures:
                arm.hide_set(False)

            for arm in armatures:
                # Isolate the target: an active object alone does not reliably
                # enter Edit Mode, and multi-object editing can affect other rigs.
                bpy.ops.object.select_all(action='DESELECT')
                arm.select_set(True)
                context.view_layer.objects.active = arm
                bpy.ops.object.mode_set(mode='EDIT')
                edit_bones = arm.data.edit_bones
                applicable = {}
                pending = dict(jiggle_registry)
                while pending:
                    progress = False
                    for name, data in list(pending.items()):
                        if data['parent_name'] not in edit_bones:
                            continue
                        if name not in edit_bones:
                            edit_bones.new(name)
                            created += 1
                        applicable[name] = data
                        del pending[name]
                        progress = True
                    if not progress:
                        break
                for name, data in pending.items():
                    self.report({'WARNING'}, f"Skipped {name} on {arm.name}: parent {data['parent_name']} is missing.")
                # Resolve parents before children, including longer jiggle chains.
                ordered = []
                pending = dict(applicable)
                while pending:
                    ready = [name for name, data in pending.items()
                             if data['parent_name'] not in pending]
                    if not ready:
                        break
                    for name in ready:
                        ordered.append((name, pending.pop(name)))
                for name, data in ordered:
                    bone = edit_bones[name]
                    bone.use_connect = False
                    bone.parent = edit_bones[data['parent_name']]
                    bone.matrix = bone.parent.matrix @ data['rel_matrix']
                    bone.length = data['length']
                if applicable:
                    updated += 1
                bpy.ops.object.mode_set(mode='OBJECT')
        finally:
            if context.object and context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            for obj in selected:
                obj.select_set(True)
            context.view_layer.objects.active = active
            if active and mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=mode)
            for arm, hidden_viewport, hidden_select, hidden in states:
                if arm.name in context.view_layer.objects:
                    arm.hide_set(hidden)
                arm.hide_viewport = hidden_viewport
                arm.hide_select = hidden_select
            if temporary:
                bpy.data.collections.remove(temporary)
            context.view_layer.update()

        self.report({'INFO'}, f"Jiggle sync: created {created} bones; synced {len(jiggle_registry)} names across {updated} rigs.")
        return {'FINISHED'}


# ============================================================ #
#                            PANEL                             #
# ============================================================ #

class UTILITY_PT_Main(Panel):
    bl_label = "Utility Operations"
    bl_idname = "UTILITY_PT_Main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WS Toolkit"

    def draw_header(self, context):
        self.layout.operator("tf2.workflow_help", text="", icon="QUESTION", emboss=False).topic = "UTILITY"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Row 1: always visible — Set Armature + pose toggle
        row = layout.row(align=True)
        row.operator(
            "utility.add_armature_modifier", icon="MOD_ARMATURE", text="Set Armature"
        )
        row.operator(
            "utility.toggle_pose_state",
            text="",
            icon="ARMATURE_DATA",
            depress=scene.tf2_pose_state,
        )

        # Row 2: icon strip + expand toggle arrow on the right
        has_assets = any(not i.is_library for i in scene.tf2_assets)
        expanded   = scene.utility_expanded

        row = layout.row(align=True)

        if not expanded:
            sub = row.row(align=True)
            sub.enabled = bool(context.active_object and context.active_object.mode == "EDIT")
            sub.operator("utility.extract_cosmetic_base", text="", icon="MOD_THICKNESS")

            sub = row.row(align=True)
            sub.enabled = has_assets and bpy.data.is_saved
            sub.operator("utility.gen_temp_diffuse", text="", icon="IMAGE_DATA")

            sub = row.row(align=True)
            sub.enabled = bpy.data.is_saved and bool(scene.tf2_assets)
            sub.operator("utility.export_preview_fbx", text="", icon="EXPORT")

            sub = row.row(align=True)
            sub.enabled = UTILITY_OT_ReprojectDiffuse.poll(context)
            sub.operator("utility.reproject_diffuse", text="", icon="UV_SYNC_SELECT").map_type = scene.reproject_map_type

            sub = row.row(align=True)
            sub.operator("utility.transfer_jiggle_hierarchy", text="", icon="BONE_DATA")

        row.prop(
            scene, "utility_expanded",
            text="",
            icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
            emboss=False,
        )

        # Expanded: full labelled buttons
        if expanded:
            row = layout.row()
            row.enabled = bool(context.active_object and context.active_object.mode == "EDIT")
            row.operator("utility.extract_cosmetic_base", text="Extract Cosmetic Base", icon="MOD_THICKNESS")

            row = layout.row()
            row.enabled = has_assets and bpy.data.is_saved
            row.operator("utility.gen_temp_diffuse", text="Generate Temp Diffuse", icon="IMAGE_DATA")

            row = layout.row()
            row.enabled = bpy.data.is_saved and bool(scene.tf2_assets)
            row.operator("utility.export_preview_fbx", text="Painter Preview FBX", icon="EXPORT")

            row = layout.row(align=True)
            row.prop(scene, 'reproject_map_type', text='')
            sub = row.row(align=True)
            sub.enabled = UTILITY_OT_ReprojectDiffuse.poll(context)
            sub.operator("utility.reproject_diffuse", text="Reproject", icon="UV_SYNC_SELECT").map_type = scene.reproject_map_type

            row = layout.row()
            row.operator("utility.transfer_jiggle_hierarchy", text="Sync Jiggle Bones", icon="BONE_DATA")


# ============================================================ #
#                       REGISTRATION                           #
# ============================================================ #

classes = (
    UTILITY_OT_ExtractCosmeticBase,
    UTILITY_OT_toggle_pose_state,
    UTILITY_OT_AddArmatureModifier,
    UTILITY_OT_GenTempDiffuse,
    UTILITY_OT_ExportPreviewFBX,
    UTILITY_OT_ReprojectDiffuse,
    UTILITY_OT_TransferJiggleHierarchy,
    UTILITY_PT_Main,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.utility_expanded = bpy.props.BoolProperty(
        name="Expand Utility Ops", default=False
    )
    bpy.types.Scene.reproject_map_type = EnumProperty(name='Reproject Map', items=REPROJECT_MAP_TYPES, default='DIFFUSE')


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.utility_expanded
    del bpy.types.Scene.reproject_map_type
