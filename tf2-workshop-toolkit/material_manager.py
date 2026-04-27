"""
Workshop Toolkit – Material Manager Module
Quick material operations without leaving the 3D viewport.
"""

import bpy
import bmesh
from bpy.props import IntProperty, StringProperty, BoolProperty, FloatProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList


# ============================================================ #
#                       HELPER FUNCTIONS                       #
# ============================================================ #

def get_pbr_node(mat):
    if mat and mat.use_nodes:
        for n in mat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                return n
    return None


def get_bevel_node(mat):
    if mat and mat.use_nodes:
        for n in mat.node_tree.nodes:
            if n.type == "BEVEL":
                return n
    return None


def _count_visible_mats(props):
    """
    Count how many materials will pass the UIList filter so we can size the
    list to fit exactly — no wasted empty rows, no fixed-height oversizing.
    Mirrors the logic in MATERIAL_UL_pro_list.filter_items().
    """
    mats = bpy.data.materials
    if not props.hide_lib_mats:
        return len(mats)

    import bpy as _bpy

    hidden = set()
    lib_prefixes = tuple(
        item.name for item in _bpy.context.scene.tf2_assets if item.is_library
    )

    if lib_prefixes:
        lib_mat_names = set()
        for obj in _bpy.data.objects:
            if obj.type == "MESH":
                in_lib = any(
                    coll.name.startswith(lib_prefixes)
                    for coll in obj.users_collection
                )
                if in_lib:
                    for slot in obj.material_slots:
                        if slot.material:
                            hidden.add(slot.material)
                            lib_mat_names.add(slot.material.name)
                    if obj.data:
                        for mat in obj.data.materials:
                            if mat:
                                hidden.add(mat)
                                lib_mat_names.add(mat.name)

        tf2_sfx = ["_red", "_blue", "_blu", "_zombie", "_invun", "_uber", "_boss"]
        base_names = set()
        for name in lib_mat_names:
            base = name.lower()
            for sfx in tf2_sfx:
                if sfx in base:
                    base = base.split(sfx)[0]
                    break
            base_names.add(base)

        for mat in mats:
            if mat in hidden or mat.name.startswith(("A_", "Z_")):
                continue
            mat_lower = mat.name.lower()
            for base in base_names:
                if mat_lower.startswith(base) and any(sfx in mat_lower for sfx in tf2_sfx):
                    hidden.add(mat)
                    break
            if mat not in hidden:
                for pref in lib_prefixes:
                    pref_base = pref.split("_")[0].lower()
                    if mat_lower.startswith(pref_base) and any(sfx in mat_lower for sfx in tf2_sfx):
                        hidden.add(mat)
                        break

    return sum(1 for m in mats if m not in hidden)


# ============================================================ #
#                         PROPERTIES                           #
# ============================================================ #

class PRO_MAT_Props(PropertyGroup):
    material_id: IntProperty(name="Index", default=0)

    hide_lib_mats: BoolProperty(
        name="Hide Library Mats",
        default=True,
        description=(
            "Hide materials belonging to registered Library/Reference assets "
            "(including Blue/Zombie skins)"
        ),
    )

    def _get_pbr_input(self, input_index):
        mats = bpy.data.materials
        if self.material_id < len(mats):
            pbr = get_pbr_node(mats[self.material_id])
            if pbr:
                return pbr.inputs[input_index].default_value
        return 0.0

    def _set_pbr_input(self, input_index, value):
        mats = bpy.data.materials
        if self.material_id < len(mats):
            pbr = get_pbr_node(mats[self.material_id])
            if pbr:
                pbr.inputs[input_index].default_value = value

    metallic_proxy: FloatProperty(
        name="Metallic",
        get=lambda self: self._get_pbr_input(1),
        set=lambda self, value: self._set_pbr_input(1, value),
        min=0.0, max=1.0, step=10, precision=2,
    )
    roughness_proxy: FloatProperty(
        name="Roughness",
        get=lambda self: self._get_pbr_input(2),
        set=lambda self, value: self._set_pbr_input(2, value),
        min=0.0, max=1.0, step=10, precision=2,
    )

    def get_radius(self):
        mats = bpy.data.materials
        if self.material_id < len(mats):
            bevel = get_bevel_node(mats[self.material_id])
            return bevel.inputs[0].default_value if bevel else 0.0
        return 0.0

    def set_radius(self, value):
        mats = bpy.data.materials
        if self.material_id < len(mats):
            bevel = get_bevel_node(mats[self.material_id])
            if bevel:
                bevel.inputs[0].default_value = value

    bevel_radius_proxy: FloatProperty(
        name="Bevel Radius",
        get=get_radius,
        set=set_radius,
        min=0.0, step=1, precision=3,
    )


# ============================================================ #
#                           UI LIST                            #
# ============================================================ #

class MATERIAL_UL_pro_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        sel = row.operator("pro_mat.select_specific", text="", icon="SELECT_SET")
        sel.mat_name = item.name
        assign = row.operator("pro_mat.assign_specific", text="", icon="CHECKMARK")
        assign.mat_name = item.name
        row.prop(item, "name", text="", emboss=False, icon_value=layout.icon(item))
        row.alignment = "RIGHT"
        if item.use_fake_user:
            row.label(text="F")
        row.label(text=str(item.users))
        delete = row.operator("pro_mat.delete_specific", text="", icon="TRASH")
        delete.mat_name = item.name

    def filter_items(self, context, data, propname):
        mats = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item] * len(mats)
        flt_neworder = []

        if context.scene.pro_mat_props.hide_lib_mats:
            hidden_mats = set()
            lib_prefixes = tuple(
                item.name for item in context.scene.tf2_assets if item.is_library
            )

            if lib_prefixes:
                lib_mat_names = set()

                for obj in bpy.data.objects:
                    if obj.type == "MESH":
                        in_lib = any(
                            coll.name.startswith(lib_prefixes)
                            for coll in obj.users_collection
                        )
                        if in_lib:
                            for slot in obj.material_slots:
                                if slot.material:
                                    hidden_mats.add(slot.material)
                                    lib_mat_names.add(slot.material.name)
                            if obj.data:
                                for mat in obj.data.materials:
                                    if mat:
                                        hidden_mats.add(mat)
                                        lib_mat_names.add(mat.name)

                tf2_sfx = ["_red", "_blue", "_blu", "_zombie", "_invun", "_uber", "_boss"]
                base_names = set()

                for name in lib_mat_names:
                    base = name.lower()
                    for sfx in tf2_sfx:
                        if sfx in base:
                            base = base.split(sfx)[0]
                            break
                    base_names.add(base)

                for mat in mats:
                    if mat in hidden_mats:
                        continue
                    if mat.name.startswith(("A_", "Z_")):
                        continue

                    mat_lower = mat.name.lower()
                    is_alt_skin = False

                    for base in base_names:
                        if mat_lower.startswith(base) and any(sfx in mat_lower for sfx in tf2_sfx):
                            is_alt_skin = True
                            break

                    if not is_alt_skin:
                        for pref in lib_prefixes:
                            pref_base = pref.split("_")[0].lower()
                            if mat_lower.startswith(pref_base) and any(sfx in mat_lower for sfx in tf2_sfx):
                                is_alt_skin = True
                                break

                    if is_alt_skin:
                        hidden_mats.add(mat)

            for idx, mat in enumerate(mats):
                if mat in hidden_mats:
                    flt_flags[idx] &= ~self.bitflag_filter_item

        return flt_flags, flt_neworder


# ============================================================ #
#                          OPERATORS                           #
# ============================================================ #

class PRO_MAT_OT_SelectSpecific(Operator):
    """Select all objects (or faces in Edit Mode) using this material. Shift-click to extend selection."""
    bl_idname = "pro_mat.select_specific"
    bl_label = "Select by Material"
    bl_options = {"REGISTER", "UNDO"}
    mat_name: StringProperty()
    extend: BoolProperty(default=False)

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        mat = bpy.data.materials.get(self.mat_name)
        if not mat:
            return {"CANCELLED"}
        obj = context.active_object
        if obj and obj.mode == "EDIT":
            bm = bmesh.from_edit_mesh(obj.data)
            slot_idx = obj.material_slots.find(self.mat_name)
            if slot_idx != -1:
                if not self.extend:
                    for f in bm.faces:
                        f.select = False
                for f in bm.faces:
                    if f.material_index == slot_idx:
                        f.select = True
                bmesh.update_edit_mesh(obj.data)
        else:
            if not self.extend:
                bpy.ops.object.select_all(action="DESELECT")
            for o in context.visible_objects:
                if o.type == "MESH" and mat.name in o.data.materials:
                    o.select_set(True)
        return {"FINISHED"}


class PRO_MAT_OT_NewMaterial(Operator):
    """Create a new blank PBR material."""
    bl_idname = "pro_mat.new_material"
    bl_label = "New PBR Material"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mat = bpy.data.materials.new(name="Material")
        mat.use_nodes = True
        context.scene.pro_mat_props.material_id = len(bpy.data.materials) - 1
        return {"FINISHED"}


class PRO_MAT_OT_NewBevelMaterial(Operator):
    """Create a new PBR material with a Bevel shader pre-wired to the normal input."""
    bl_idname = "pro_mat.new_bevel_material"
    bl_label = "New Bevel Material"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mat = bpy.data.materials.new(name="Bevel_Material")
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = get_pbr_node(mat)
        if bsdf:
            bevel = nodes.new(type="ShaderNodeBevel")
            bevel.samples = 16
            bevel.inputs[0].default_value = 0.090
            bevel.location = (bsdf.location.x - 300, bsdf.location.y - 300)
            links.new(bevel.outputs[0], bsdf.inputs["Normal"])
        context.scene.pro_mat_props.material_id = len(bpy.data.materials) - 1
        return {"FINISHED"}


class PRO_MAT_OT_AssignSpecific(Operator):
    """Assign this material to selected faces (Edit Mode) or selected objects (Object Mode)."""
    bl_idname = "pro_mat.assign_specific"
    bl_label = "Assign to Selection"
    bl_options = {"REGISTER", "UNDO"}
    mat_name: StringProperty()

    def execute(self, context):
        mat = bpy.data.materials.get(self.mat_name)
        obj = context.active_object
        if not mat:
            return {"CANCELLED"}

        # Edit Mode: face-level assign on the active mesh
        if obj and obj.mode == "EDIT":
            bm = bmesh.from_edit_mesh(obj.data)
            sel = [f for f in bm.faces if f.select]
            target_faces = sel if sel else bm.faces
            slot_idx = obj.material_slots.find(self.mat_name)
            if slot_idx == -1:
                obj.data.materials.append(mat)
                slot_idx = len(obj.material_slots) - 1
            for f in target_faces:
                f.material_index = slot_idx
            bmesh.update_edit_mesh(obj.data)
            return {"FINISHED"}

        # Object Mode: assign to every selected mesh, not just the active one
        meshes = [o for o in context.selected_objects if o.type == "MESH"]
        if not meshes and obj and obj.type == "MESH":
            meshes = [obj]
        if not meshes:
            return {"CANCELLED"}

        for m_obj in meshes:
            if m_obj.material_slots:
                m_obj.active_material = mat
            else:
                m_obj.data.materials.append(mat)

        self.report({"INFO"},
                    f"Assigned '{mat.name}' to {len(meshes)} mesh(es).")
        return {"FINISHED"}


class PRO_MAT_OT_CleanSelected(Operator):
    """Remove all materials from selected meshes (clears face assignments in Edit Mode)."""
    bl_idname = "pro_mat.clean_selected"
    bl_label = "Clean Mesh Materials"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type != "MESH":
                continue
            if obj.mode == "EDIT":
                bm = bmesh.from_edit_mesh(obj.data)
                for f in bm.faces:
                    if f.select:
                        f.material_index = 0
                used_indices = set(f.material_index for f in bm.faces)
                for i in range(len(obj.material_slots) - 1, 0, -1):
                    if i not in used_indices:
                        obj.data.materials.pop(index=i)
                bmesh.update_edit_mesh(obj.data)
            else:
                obj.data.materials.clear()
        self.report({"INFO"}, "Cleaned materials from selected meshes.")
        return {"FINISHED"}


class PRO_MAT_OT_DeleteSpecific(Operator):
    """Permanently delete this material from the project."""
    bl_idname = "pro_mat.delete_specific"
    bl_label = "Delete Material"
    bl_options = {"REGISTER", "UNDO"}
    mat_name: StringProperty()

    def execute(self, context):
        mat = bpy.data.materials.get(self.mat_name)
        if mat:
            bpy.data.materials.remove(mat, do_unlink=True)
        return {"FINISHED"}


class PRO_MAT_OT_CleanUnused(Operator):
    """Delete all materials with zero users from the project."""
    bl_idname = "pro_mat.clean_unused"
    bl_label = "Clean Project (Unused Mats)"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        cleaned = 0
        for mat in list(bpy.data.materials):
            if mat.users == 0:
                bpy.data.materials.remove(mat)
                cleaned += 1
        self.report({"INFO"}, f"Cleaned {cleaned} unused materials.")
        return {"FINISHED"}


# ============================================================ #
#                            PANEL                             #
# ============================================================ #

class PRO_MAT_PT_Main(Panel):
    bl_label = "Material Manager"
    bl_idname = "PRO_MAT_PT_Main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WS Toolkit"

    def draw(self, context):
        layout = self.layout
        props = context.scene.pro_mat_props
        mats = bpy.data.materials

        # ── Single top row: new buttons + material properties ─────────── #
        row = layout.row(align=True)

        # New mat / new bevel mat — small fixed-width icons
        row.operator("pro_mat.new_material",      text="", icon="ADD")
        row.operator("pro_mat.new_bevel_material", text="", icon="FACE_CORNER")

        row.separator()

        # Material properties — only shown when a valid mat with PBR is active
        if mats and props.material_id < len(mats):
            target_mat = mats[props.material_id]
            pbr   = get_pbr_node(target_mat)
            bevel = get_bevel_node(target_mat)

            if pbr:
                # Color swatch — narrowed so it doesn't dominate the row
                sub = row.row(align=True)
                sub.scale_x = 0.5
                sub.prop(pbr.inputs[0], "default_value", text="")

                row.prop(props, "metallic_proxy",  text="M")
                row.prop(props, "roughness_proxy",  text="R")
                if bevel:
                    row.prop(props, "bevel_radius_proxy", text="B")

        # ── Hide-lib toggle + list label ──────────────────────────────── #
        row = layout.row()
        row.label(text="Materials:", icon="MATERIAL")
        row.prop(
            props,
            "hide_lib_mats",
            text="",
            icon="HIDE_ON" if props.hide_lib_mats else "HIDE_OFF",
            emboss=False,
        )

        # ── Dynamic-height material list ──────────────────────────────── #
        # Count visible mats and size the list to fit exactly, clamped
        # to a minimum of 2 and a maximum of 12 rows.
        try:
            visible = _count_visible_mats(props)
        except Exception:
            visible = len(mats)

        rows = max(2, min(visible, 12))

        layout.template_list(
            "MATERIAL_UL_pro_list", "",
            bpy.data, "materials",
            props, "material_id",
            rows=rows,
        )

        # ── Clean buttons ─────────────────────────────────────────────── #
        row = layout.row(align=True)
        row.operator("pro_mat.clean_selected", text="Selected", icon="TRASH")
        row.operator("pro_mat.clean_unused",   text="Unused",   icon="TRASH")


# ============================================================ #
#                       REGISTRATION                           #
# ============================================================ #

classes = (
    PRO_MAT_Props,
    MATERIAL_UL_pro_list,
    PRO_MAT_OT_SelectSpecific,
    PRO_MAT_OT_NewMaterial,
    PRO_MAT_OT_NewBevelMaterial,
    PRO_MAT_OT_AssignSpecific,
    PRO_MAT_OT_CleanSelected,
    PRO_MAT_OT_DeleteSpecific,
    PRO_MAT_OT_CleanUnused,
    PRO_MAT_PT_Main,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
