"""
Workshop Toolkit – Weight Tools Module
Vertex weight operations: smooth/limit/normalize, transfer, copy/paste, bone assign.
"""

import bpy
from bpy.types import Operator, Panel, Menu


# ============================================================ #
#                       MODULE-LEVEL STATE                     #
# ============================================================ #

# Stores a single vertex's weight map for the copy/paste operators.
copied_weights: dict = {}


# ============================================================ #
#                          OPERATORS                           #
# ============================================================ #

class WEIGHT_OT_smooth_limit_normalize(bpy.types.Operator):
    """Smooth (variable), Limit (3), and Normalize selected vertices"""
    bl_idname = "object.weight_smooth_limit_normalize"
    bl_label = "Automated Weight Cleanup"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != "MESH":
            self.report({"ERROR"}, "Active object must be a mesh")
            return {"CANCELLED"}
        if not obj.vertex_groups:
            self.report({"ERROR"}, "Mesh has no vertex groups")
            return {"CANCELLED"}

        original_mode = obj.mode
        bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
        obj.data.use_paint_mask_vertex = True
        iterations = context.scene.weight_smooth_iterations

        try:
            bpy.ops.object.vertex_group_smooth(
                group_select_mode="ALL", factor=1.0, repeat=iterations
            )
            bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=3)
            bpy.ops.object.vertex_group_normalize_all(
                group_select_mode="ALL", lock_active=False
            )
        except Exception as e:
            self.report({"ERROR"}, f"Operation failed: {str(e)}")
            bpy.ops.object.mode_set(mode=original_mode)
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode=original_mode)
        self.report({"INFO"}, f"Smoothed ({iterations}x), Limited (3), and Normalized.")
        return {"FINISHED"}


class WEIGHT_OT_assign_target_bone(bpy.types.Operator):
    """Assign all vertices to the specified target bone and clear from other groups"""
    bl_idname = "object.assign_target_bone"
    bl_label = "Assign All to Target Bone"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target_vg_name = context.scene.weight_target_bone
        if not target_vg_name.strip():
            self.report({"WARNING"}, "Target bone name cannot be empty")
            return {"CANCELLED"}

        selected_meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
        if not selected_meshes:
            self.report({"WARNING"}, "No mesh objects selected")
            return {"CANCELLED"}

        for obj in selected_meshes:
            target_vg = obj.vertex_groups.get(target_vg_name)
            if not target_vg:
                target_vg = obj.vertex_groups.new(name=target_vg_name)
            all_verts = [v.index for v in obj.data.vertices]
            if not all_verts:
                continue
            target_vg.add(all_verts, 1.0, "REPLACE")
            for vg in obj.vertex_groups:
                if vg.name != target_vg_name:
                    vg.remove(all_verts)

        self.report(
            {"INFO"},
            f"Assigned 100% {target_vg_name} to {len(selected_meshes)} object(s)",
        )
        return {"FINISHED"}


class WEIGHT_OT_quick_weight_transfer(bpy.types.Operator):
    """Transfer weights safely by temporarily bypassing active poses"""
    bl_idname = "object.quick_weight_transfer"
    bl_label = "Quick Weight Transfer"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected = context.selected_objects
        active_obj = context.active_object
        meshes = [obj for obj in selected if obj.type == "MESH"]

        if len(meshes) < 2:
            self.report({"ERROR"}, "Select at least two meshes")
            return {"CANCELLED"}

        is_edit_mode = active_obj and active_obj.mode == "EDIT"

        if is_edit_mode:
            target = active_obj
            sources = [obj for obj in meshes if obj != target]
            if not sources:
                self.report(
                    {"ERROR"},
                    "No source found. Shift-select Reference before Tabbing into Edit Mode.",
                )
                return {"CANCELLED"}
            source = sources[0]
            targets = [target]
        else:
            source = active_obj
            targets = [obj for obj in meshes if obj != source]
            if not targets:
                self.report({"ERROR"}, "No valid target mesh objects found")
                return {"CANCELLED"}

        involved_objs = [source] + targets
        armature_states = {}
        for obj in involved_objs:
            armature_states[obj] = {}
            for mod in obj.modifiers:
                if mod.type == "ARMATURE":
                    armature_states[obj][mod.name] = mod.show_viewport
                    mod.show_viewport = False

        try:
            if is_edit_mode:
                bpy.ops.object.mode_set(mode="OBJECT")
                selected_verts = [v.index for v in target.data.vertices if v.select]

                if not selected_verts:
                    self.report(
                        {"WARNING"},
                        "No vertices selected! Aborting to prevent full overwrite.",
                    )
                    bpy.ops.object.mode_set(mode="EDIT")
                    return {"CANCELLED"}

                temp_vg = target.vertex_groups.new(name="_temp_wt_mask")
                temp_vg.add(selected_verts, 1.0, "REPLACE")

                mod = target.modifiers.new(name="DataTransfer", type="DATA_TRANSFER")
                mod.object = source
                mod.use_vert_data = True
                mod.data_types_verts = {"VGROUP_WEIGHTS"}
                mod.vertex_group = temp_vg.name

                bpy.ops.object.select_all(action="DESELECT")
                target.select_set(True)
                context.view_layer.objects.active = target

                bpy.ops.object.datalayout_transfer(modifier=mod.name)
                bpy.ops.object.modifier_apply(modifier=mod.name)
                target.vertex_groups.remove(target.vertex_groups.get("_temp_wt_mask"))

                bpy.ops.object.select_all(action="DESELECT")
                source.select_set(True)
                target.select_set(True)
                context.view_layer.objects.active = target
                bpy.ops.object.mode_set(mode="EDIT")

                self.report(
                    {"INFO"},
                    f"Transferred perfectly to {len(selected_verts)} posed vertices!",
                )
            else:
                for t_obj in targets:
                    bpy.ops.object.select_all(action="DESELECT")
                    t_obj.select_set(True)
                    context.view_layer.objects.active = t_obj

                    mod = t_obj.modifiers.new(name="DataTransfer", type="DATA_TRANSFER")
                    mod.object = source
                    mod.use_vert_data = True
                    mod.data_types_verts = {"VGROUP_WEIGHTS"}

                    bpy.ops.object.datalayout_transfer(modifier=mod.name)
                    bpy.ops.object.modifier_apply(modifier=mod.name)

                bpy.ops.object.select_all(action="DESELECT")
                for t_obj in targets:
                    t_obj.select_set(True)
                source.select_set(True)
                context.view_layer.objects.active = source

                self.report(
                    {"INFO"},
                    f"Transferred weights from {source.name} to {len(targets)} object(s)",
                )
        finally:
            for obj, mods in armature_states.items():
                for mod_name, state in mods.items():
                    if mod_name in obj.modifiers:
                        obj.modifiers[mod_name].show_viewport = state

        return {"FINISHED"}


class WEIGHT_OT_copy_vertex_weights(bpy.types.Operator):
    """Copy Vertex Weights"""
    bl_idname = "mesh.copy_vertex_weights"
    bl_label = "Copy Vertex Weights"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        global copied_weights
        obj = context.object
        if obj.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
            copied_weights = {}
            for v in obj.data.vertices:
                if v.select:
                    for group in obj.vertex_groups:
                        try:
                            weight = group.weight(v.index)
                            if weight > 0:
                                copied_weights[group.name] = weight
                        except RuntimeError:
                            continue
                    break
            bpy.ops.object.mode_set(mode="EDIT")
            self.report({"INFO"}, "Weights copied.")
        return {"FINISHED"}


class WEIGHT_OT_paste_vertex_weights(bpy.types.Operator):
    """Paste Vertex Weights"""
    bl_idname = "mesh.paste_vertex_weights"
    bl_label = "Paste Vertex Weights"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        global copied_weights
        obj = context.object
        if obj.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
            for v in obj.data.vertices:
                if v.select:
                    for group in obj.vertex_groups:
                        group.remove([v.index])
            for group_name, weight in copied_weights.items():
                if group_name not in [g.name for g in obj.vertex_groups]:
                    obj.vertex_groups.new(name=group_name)
                group = obj.vertex_groups[group_name]
                for v in obj.data.vertices:
                    if v.select:
                        group.add([v.index], weight, "REPLACE")
            bpy.ops.object.mode_set(mode="EDIT")
            self.report({"INFO"}, "Weights pasted.")
        return {"FINISHED"}


# ============================================================ #
#                        PANEL & PIE MENU                      #
# ============================================================ #

class WEIGHT_PT_Main(bpy.types.Panel):
    bl_label = "Weight Tools"
    bl_idname = "WEIGHT_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WS Toolkit"

    def draw(self, context):
        layout = self.layout

        # Row 1: Copy | Paste | [bone icon] [target bone field]
        row = layout.row(align=True)
        row.operator(
            WEIGHT_OT_copy_vertex_weights.bl_idname, text="Copy", icon="COPYDOWN"
        )
        row.operator(
            WEIGHT_OT_paste_vertex_weights.bl_idname, text="Paste", icon="PASTEDOWN"
        )
        row.operator(
            WEIGHT_OT_assign_target_bone.bl_idname, text="", icon="BONE_DATA"
        )
        row.prop(context.scene, "weight_target_bone", text="")

        # Row 2: Transfer | Smooth [count]
        row = layout.row(align=True)
        row.operator(
            WEIGHT_OT_quick_weight_transfer.bl_idname,
            text="Transfer",
            icon="MOD_DATA_TRANSFER",
        )
        row.operator(
            WEIGHT_OT_smooth_limit_normalize.bl_idname,
            text="Smooth",
            icon="MOD_SMOOTH",
        )
        sub = row.row(align=True)
        sub.scale_x = 0.55
        sub.prop(context.scene, "weight_smooth_iterations", text="")


class WEIGHT_MT_pie_menu(bpy.types.Menu):
    bl_label = "Weight Tools"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        pie.operator("object.quick_weight_transfer", text="Quick Transfer", icon="MOD_DATA_TRANSFER")
        pie.operator("object.weight_smooth_limit_normalize", text="Smooth", icon="MOD_SMOOTH")
        pie.operator("object.assign_target_bone", text="Assign Target Bone", icon="BONE_DATA")
        col = pie.column()
        col.operator("mesh.copy_vertex_weights", text="Copy Weight", icon="COPYDOWN")
        col.operator("mesh.paste_vertex_weights", text="Paste Weight", icon="PASTEDOWN")


# ============================================================ #
#                       REGISTRATION                           #
# ============================================================ #

classes = (
    WEIGHT_OT_smooth_limit_normalize,
    WEIGHT_OT_assign_target_bone,
    WEIGHT_OT_quick_weight_transfer,
    WEIGHT_OT_copy_vertex_weights,
    WEIGHT_OT_paste_vertex_weights,
    WEIGHT_PT_Main,
    WEIGHT_MT_pie_menu,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
