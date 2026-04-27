"""
Workshop Toolkit – Utility Operations Module
Misc helpers: cosmetic base extraction, global pose toggle, armature assignment,
and temp diffuse texture generation for in-game preview.
"""

import bpy
import os
import numpy as np
from bpy.props import StringProperty, EnumProperty
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
        "Duplicates selection, cleans data, applies 0.98 midlevel displacement, "
        "routes to asset folder, and applies material"
    )
    bl_options = {"REGISTER", "UNDO"}

    target_asset: EnumProperty(name="Send To", items=get_target_assets)

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
            return self.execute(context)
        elif len(items) > 1:
            return context.window_manager.invoke_props_dialog(self)
        else:
            self.target_asset = "NONE"
            return self.execute(context)

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

        mod = new_obj.modifiers.new(name="Base_Displace", type="DISPLACE")
        mod.strength = 1.0
        mod.mid_level = 0.98
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
    """FBX export for Substance Painter — exports flagged asset lod0 meshes to /bakes/{blend}_substance.fbx."""
    bl_idname  = "utility.export_preview_fbx"
    bl_label   = "Export Preview FBX"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bpy.data.is_saved and bool(context.scene.tf2_assets)

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
        return {"FINISHED"}


# ============================================================ #
#              REPROJECT DIFFUSE — TWO-BUTTON APPROACH         #
# ============================================================ #

def _reproj_mat_items(self, context):
    """Enum items: non-eye materials on the reference mesh (first selected,
    non-active) that have a '$basetexture [texture]' Image Texture node."""
    sel = [o for o in context.selected_objects if o.type == "MESH"]
    active = context.active_object
    ref = next((o for o in sel if o != active), None)
    if not ref:
        # Fallback: active itself
        ref = active
    if not ref or ref.type != "MESH":
        return [("NONE", "No mesh found", "")]
    items = []
    for slot in ref.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        if "eye" in mat.name.lower():
            continue
        if any(n.type == "TEX_IMAGE" and n.label.lower().startswith("$basetexture")
               for n in mat.node_tree.nodes):
            items.append((mat.name, mat.name, ""))
    return items if items else [("NONE", "No $basetexture material found", "")]


class UTILITY_OT_ReprojectDiffuse(Operator):
    """Reproject diffuse from active to selected."""
    bl_idname  = "utility.reproject_diffuse"
    bl_label   = "Reproject Diffuse"
    bl_options = {"REGISTER", "UNDO"}

    mat_name: EnumProperty(
        name="Source Material",
        description="Material on the reference mesh to bake from (eyes excluded)",
        items=_reproj_mat_items,
    )

    @classmethod
    def poll(cls, context):
        sel = [o for o in context.selected_objects if o.type == "MESH"]
        return len(sel) == 2 and bpy.data.is_saved

    def invoke(self, context, event):
        items = _reproj_mat_items(self, context)
        if not items or items[0][0] == "NONE":
            self.report({"ERROR"}, "No $basetexture material found on reference mesh.")
            return {"CANCELLED"}
        if len(items) == 1:
            self.mat_name = items[0][0]
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not bpy.data.is_saved:
            self.report({"ERROR"}, "Save the .blend file first.")
            return {"CANCELLED"}

        sel = [o for o in context.selected_objects if o.type == "MESH"]
        if len(sel) != 2:
            self.report({"ERROR"}, "Select exactly 2 meshes.")
            return {"CANCELLED"}

        target_obj = context.view_layer.objects.active
        if target_obj not in sel:
            self.report({"ERROR"}, "Active object must be one of the two selected meshes.")
            return {"CANCELLED"}
        source_obj = sel[0] if sel[1] == target_obj else sel[1]

        # ── Rewire ALL non-eye materials on source to Emission ────────── #
        rewires = []  # [(mat, out_node, prev_target, emit_node, old_surface, base_color_link)]

        for slot in source_obj.material_slots:
            mat = slot.material
            if not mat or not mat.use_nodes:
                continue
            if "eye" in mat.name.lower():
                continue

            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            basetex = next(
                (n for n in nodes
                 if n.type == "TEX_IMAGE" and n.label.lower().startswith("$basetexture")),
                None,
            )
            if not basetex:
                continue

            bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
            out  = next((n for n in nodes
                         if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
            if not out:
                continue

            # Set output target to ALL so Cycles sees it
            prev_target  = out.target
            out.target   = "ALL"

            # Cut BSDF → Output Surface
            old_surface = None
            for lnk in list(links):
                if lnk.to_node == out and lnk.to_socket.name == "Surface":
                    old_surface = (lnk.from_node.name, lnk.from_socket.name)
                    links.remove(lnk)
                    break

            # Cut basetexture → BSDF Base Color
            base_color_link = None
            if bsdf:
                for lnk in list(links):
                    if (lnk.from_node == basetex
                            and lnk.to_node == bsdf
                            and lnk.to_socket.name == "Base Color"):
                        base_color_link = (lnk.from_node.name, lnk.from_socket.name,
                                           lnk.to_node.name,   lnk.to_socket.name)
                        links.remove(lnk)
                        break

            # Wire basetexture → Emission → Output
            emit          = nodes.new("ShaderNodeEmission")
            emit.label    = "_wstk_reproj_emit"
            emit.location = (out.location.x - 220, out.location.y)
            links.new(basetex.outputs["Color"], emit.inputs["Color"])
            links.new(emit.outputs["Emission"], out.inputs["Surface"])
            mat.node_tree.update_tag()

            rewires.append((mat, out, prev_target, emit, old_surface, base_color_link))

        if not rewires:
            self.report({"ERROR"}, "No materials with $basetexture found on source mesh.")
            return {"CANCELLED"}

        # ── Create bake image + inject node into target ───────────────── #
        img_name = f"{target_obj.name}_reproj_diffuse"
        img = bpy.data.images.get(img_name)
        if img:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(img_name, width=1024, height=1024, alpha=False)
        img.colorspace_settings.name = "sRGB"

        if not target_obj.data.uv_layers:
            target_obj.data.uv_layers.new(name="UVMap")

        if not target_obj.data.materials:
            tmp_mat = bpy.data.materials.new(name=f"{target_obj.name}_bake")
            tmp_mat.use_nodes = True
            target_obj.data.materials.append(tmp_mat)

        target_mat = target_obj.data.materials[0]
        if not target_mat.use_nodes:
            target_mat.use_nodes = True

        t_nodes = target_mat.node_tree.nodes
        for n in t_nodes:
            n.select = False

        bake_node = next(
            (n for n in t_nodes
             if n.type == "TEX_IMAGE" and n.label == "_wstk_tmp_bake"), None
        )
        created_bake_node = bake_node is None
        if created_bake_node:
            bake_node          = t_nodes.new("ShaderNodeTexImage")
            bake_node.label    = "_wstk_tmp_bake"
            bake_node.location = (-300, -600)

        bake_node.image  = img
        bake_node.select = True
        t_nodes.active   = bake_node
        target_obj.active_material_index = 0

        # ── Cycles setup ──────────────────────────────────────────────── #
        scene  = context.scene
        cycles = scene.cycles
        prev_engine  = scene.render.engine
        prev_device  = cycles.device
        prev_samples = cycles.samples
        prev_sel     = list(context.selected_objects)
        prev_active  = context.view_layer.objects.active

        scene.render.engine = "CYCLES"
        cycles.device        = "GPU"
        cycles.samples       = 1

        coll_state, obj_state = _force_show([], [source_obj, target_obj])

        bake_ok = False
        try:
            bpy.ops.object.select_all(action="DESELECT")
            source_obj.select_set(True)
            target_obj.select_set(True)
            context.view_layer.objects.active = target_obj

            bpy.ops.object.bake(
                type                   = "EMIT",
                use_selected_to_active = True,
                cage_extrusion         = 1.0,
                margin                 = 4,
                use_clear              = True,
            )
            bake_ok = True

        except Exception as e:
            self.report({"ERROR"}, f"Bake failed: {e}")

        finally:
            # ── Restore source materials ──────────────────────────────── #
            for mat, out, prev_target, emit, old_surface, base_color_link in rewires:
                r_nodes = mat.node_tree.nodes
                r_links = mat.node_tree.links

                for lnk in list(r_links):
                    if lnk.from_node == emit or lnk.to_node == emit:
                        r_links.remove(lnk)
                r_nodes.remove(emit)

                out.target = prev_target

                if old_surface:
                    from_node = r_nodes.get(old_surface[0])
                    if from_node:
                        try:
                            r_links.new(from_node.outputs[old_surface[1]],
                                        out.inputs["Surface"])
                        except Exception:
                            pass

                if base_color_link:
                    fn, fs, tn, ts = base_color_link
                    fn = r_nodes.get(fn)
                    tn = r_nodes.get(tn)
                    if fn and tn:
                        try:
                            r_links.new(fn.outputs[fs], tn.inputs[ts])
                        except Exception:
                            pass

            # ── Remove bake node from target ──────────────────────────── #
            if created_bake_node:
                try:
                    target_mat.node_tree.nodes.remove(bake_node)
                except Exception:
                    pass

            # ── Restore render / selection ────────────────────────────── #
            _restore_show(coll_state, obj_state)
            scene.render.engine = prev_engine
            cycles.device        = prev_device
            cycles.samples       = prev_samples

            bpy.ops.object.select_all(action="DESELECT")
            for o in prev_sel:
                try:
                    o.select_set(True)
                except Exception:
                    pass
            context.view_layer.objects.active = prev_active

        if not bake_ok:
            return {"CANCELLED"}

        # ── Save ──────────────────────────────────────────────────────── #
        blend_dir = os.path.dirname(bpy.data.filepath)
        out_dir   = os.path.join(blend_dir, "bakes")
        os.makedirs(out_dir, exist_ok=True)
        out_path  = os.path.join(out_dir, f"{img_name}.tga")

        img.filepath_raw = out_path
        img.file_format  = "TARGA"
        img.save()

        self.report({"INFO"}, f"Reprojected diffuse saved → {out_path}")
        return {"FINISHED"}


class UTILITY_OT_TransferJiggleHierarchy(Operator):
    """Sync jiggle_ / j_ bones and their hierarchy across all armatures in the scene"""
    bl_idname  = "utility.transfer_jiggle_hierarchy"
    bl_label   = "Sync Jiggle Bones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']

        # 1. SCAN PHASE
        jiggle_registry = {}
        for arm in armatures:
            context.view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode='EDIT')
            for bone in arm.data.edit_bones:
                if (bone.name.startswith("jiggle_") or bone.name.startswith("j_")) and bone.parent:
                    rel_matrix = bone.parent.matrix.inverted() @ bone.matrix
                    jiggle_registry[bone.name] = {
                        'parent_name': bone.parent.name,
                        'rel_matrix':  rel_matrix.copy(),
                        'length':      bone.length,
                    }
            bpy.ops.object.mode_set(mode='OBJECT')

        if not jiggle_registry:
            self.report({'WARNING'}, "No jiggle bones found.")
            return {'CANCELLED'}

        # 2. APPLY PHASE
        for arm in armatures:
            context.view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode='EDIT')
            edit_bones = arm.data.edit_bones

            for b_name in jiggle_registry:
                if b_name not in edit_bones:
                    edit_bones.new(b_name)

            for b_name, data in jiggle_registry.items():
                target_bone = edit_bones[b_name]
                if data['parent_name'] in edit_bones:
                    target_bone.parent = edit_bones[data['parent_name']]
                    target_bone.use_connect = False
                else:
                    self.report({'WARNING'}, f"Parent {data['parent_name']} not found in {arm.name}")

            for _ in range(2):
                for b_name, data in jiggle_registry.items():
                    target_bone = edit_bones[b_name]
                    if target_bone.parent:
                        target_bone.matrix = target_bone.parent.matrix @ data['rel_matrix']
                        target_bone.length = data['length']

            bpy.ops.object.mode_set(mode='OBJECT')

        self.report({'INFO'}, f"Jiggle sync complete — {len(jiggle_registry)} bones.")
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
        sel_meshes = [o for o in context.selected_objects if o.type == "MESH"]
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
            sub.enabled = len(sel_meshes) == 2 and bpy.data.is_saved
            sub.operator("utility.reproject_diffuse", text="", icon="UV_SYNC_SELECT")

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
            row.operator("utility.export_preview_fbx", text="Export Preview FBX", icon="EXPORT")

            row = layout.row()
            row.enabled = len(sel_meshes) == 2 and bpy.data.is_saved
            row.operator("utility.reproject_diffuse", text="Reproject Diffuse", icon="UV_SYNC_SELECT")

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


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.utility_expanded

    """Enum items: non-eye materials on the active object that have a
    '$basetexture [texture]' Image Texture node."""
    obj = context.active_object
    if not obj or obj.type != "MESH":
        return [("NONE", "No mesh active", "")]
    items = []
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        name_lower = mat.name.lower()
        if "eye" in name_lower:
            continue
        if any(n.type == "TEX_IMAGE" and n.label.lower().startswith("$basetexture")
               for n in mat.node_tree.nodes):
            items.append((mat.name, mat.name, ""))
    return items if items else [("NONE", "No $basetexture material found", "")]


