"""Compact, on-demand workflow guidance and an inspectable example asset."""
import bpy
import bmesh
from bpy.props import EnumProperty, StringProperty
from . import bl_info
from .asset_manager import _activate_asset_lod0


HELP_TEXT = {
    "WEIGHTS": (
        "Transfer keeps the original Data Transfer workflow.",
        "Distance Transfer is experimental: close = precise; far = smooth.",
        "Object Mode: select targets, then make the reference active.",
        "Edit Mode: active mesh is target; select vertices to affect.",
        "Distances are percentages of reference size, not scene units.",
        "Smooth Gradient: drag from zero to full smoothing.",
        "Blue circle START = unchanged; orange square END = maximum.",
        "Release to preview; wheel adjusts strength; redraw to retry.",
        "Enter applies; Esc/right-click restores original weights.",
        "Uses the Smooth pass count and current selection masks.",
        "Affects projected front/back vertices; mask to isolate an area.",
        "New tools normalize and limit to 3 deform weights.",
        "Assign Selected: set Bone and Weight, then apply in Edit Mode.",
        "Target weight is kept; strongest other bones share the remainder.",
        "Soft Radius is shared by Assign Selected, Smooth and transfers.",
        "Transfer blends nearby old/new weights; core gets full transfer.",
        "On Cage Edit Mode: radius follows the deformed surface.",
        "Select the core, adjust Radius; yellow outline is the cutoff.",
        "Locked groups stay fixed; incompatible locks report an error.",
    ),
    "ASSETS": (
        "An asset is a cosmetic's LOD collections.",
        "1. Spawn a reference merc with Player Model Quick Loader.",
        "2. New Asset creates folders; add your meshes to LOD0.",
        "3. Put simpler versions in LOD1 and LOD2.",
        "4. Check the asset's export icon, then click Game FBX.",
        "Game FBX: rest pose, LODs, LOD0 skeleton; /mesh/.",
        "Painter Preview: current pose, meshes only; /bakes/.",
        "Both folders are beside your saved .blend file.",
        "All Classes creates cosmetic variants for each merc.",
    ),
    "BASE": (
        "BASE means reference merc, not your cosmetic.",
        "Mercs register automatically when their meshes arrive.",
        "Painter Preview includes the first reference merc.",
        "Leave its export icon unchecked for normal game exports.",
        "Deleting BASE removes its objects and unused materials.",
    ),
    "UTILITY": (
        "Set Armature binds selected meshes to a skeleton.",
        "The armature icon toggles rest/pose display (F4).",
        "Extract: select faces on the reference merc in Edit Mode.",
        "Extraction dialog: Displacement sets the normal offset (default 0.02).",
        "Painter Preview exports checked LOD0s and a reference merc.",
        "Reproject: select cosmetic; choose Source Mesh in the dialog.",
        "The source can stay hidden, even in an excluded collection.",
        "Choose Diffuse, Normal, or Specular in the dropdown.",
        "Specular is the reference normal texture's alpha channel.",
        "Its dialog offers Apply to Cosmetic and a texture preview.",
        "For bleeding: reduce Extrusion; try a finite Max Ray Distance.",
        "Too short leaves gaps; Padding extends UV island borders.",
        "It keeps the current pose and exports no skeleton.",
        "Save your .blend first; output goes to /bakes/ beside it.",
        "Expand the arrow to see names for the compact buttons.",
    ),
    "MATERIALS": (
        "Select a material, then Assign to apply it to your selection.",
        "Object Mode: selected meshes. Edit Mode: selected faces.",
        "The eye toggle includes reference-merc materials in the list.",
        "New Asset creates A_ and optionally Z_ materials.",
        "Game export sorts material slots alphabetically.",
        "Clean Unused removes materials with no users.",
    ),
    "BAKE": (
        "Tangent Normal bakes high-poly detail onto a low-poly mesh.",
        "Select matching name_low and name_high meshes.",
        "Or use an asset's bake icon for its LOD0/high collections.",
        "Bevel Normal: select one mesh to bake rounded edges.",
        "Composite blends a bevel bake into a tangent normal map.",
        "Use Y- for TF2. Save your .blend to write textures to disk.",
    ),
}


class TF2_OT_WorkflowHelp(bpy.types.Operator):
    """Show a short guide for this panel without expanding the sidebar"""
    bl_idname = "tf2.workflow_help"
    bl_label = "Workshop Quick Guide"
    topic: EnumProperty(items=[(key, key.title(), "") for key in HELP_TEXT])

    @classmethod
    def description(cls, context, props):
        if props.topic == "BASE":
            return "BASE: reference merc. Click to learn how references differ from cosmetic assets"
        return "Show a short workflow guide for this panel"

    def draw(self, context):
        col = self.layout.column(align=True)
        version = ".".join(str(part) for part in bl_info["version"])
        col.label(text=f"Workshop Toolkit {version}")
        col.separator()
        for line in HELP_TEXT[self.topic]:
            col.label(text=line)
        if self.topic == "ASSETS":
            col.separator()
            col.label(text="Example: three LODs, two materials, a shape key; no rig.")
            col.operator("tf2.create_example", text="Add Example Asset", icon="MESH_UVSPHERE")

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=460)

    def execute(self, context):
        return {"FINISHED"}


class TF2_OT_ExportResult(bpy.types.Operator):
    """Show where the exported files were written"""
    bl_idname = "tf2.export_result"
    bl_label = "Export Complete"
    directory: StringProperty(subtype="DIR_PATH")
    message: StringProperty()

    def draw(self, context):
        self.layout.label(text=self.message, icon="CHECKMARK")
        self.layout.operator("wm.path_open", text="Open Folder", icon="FILE_FOLDER").filepath = self.directory

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=300)

    def execute(self, context):
        return {"FINISHED"}


class TF2_OT_CreateExample(bpy.types.Operator):
    """Add an example cosmetic with three LODs, high-poly source, two materials and a shape key. Your existing objects are kept"""
    bl_idname = "tf2.create_example"
    bl_label = "Add Example Asset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        name = "example_hat"
        index = 2
        while (any(bpy.data.collections.get(name + suffix)
                   for suffix in ("", "_lod0", "_lod1", "_lod2", "_high"))
               or context.scene.tf2_assets.get(name)
               or bpy.data.materials.get("A_" + name)
               or bpy.data.materials.get("Z_" + name)):
            name = f"example_hat_{index}"
            index += 1
        bpy.ops.tf2.initialize_asset(asset_name=name, use_two_mats=True)
        for suffix, segments, rings in (("_lod0", 24, 12), ("_lod1", 16, 8),
                                        ("_lod2", 8, 6), ("_high", 48, 24)):
            mesh = bpy.data.meshes.new(name + suffix)
            bm = bmesh.new()
            bm.loops.layers.uv.verify()
            bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings,
                                      radius=1.0, calc_uvs=True)
            bm.to_mesh(mesh)
            bm.free()
            for vertex in mesh.vertices:
                vertex.co.z = vertex.co.z * 0.35 + 1.8
            mesh.update()
            obj = bpy.data.objects.new(name + suffix, mesh)
            bpy.data.collections[name + suffix].objects.link(obj)
            for prefix in ("A_", "Z_"):
                mesh.materials.append(bpy.data.materials[prefix + name])
            for face in mesh.polygons:
                face.material_index = int(face.center.z < 1.8)
            if suffix == "_lod0":
                obj.shape_key_add(name="Basis")
                key = obj.shape_key_add(name="Wider")
                for vertex in key.data:
                    vertex.co.x *= 1.2
        item = context.scene.tf2_assets.get(name)
        item.do_export = True
        item.show_lod1 = item.show_lod2 = item.show_high = False
        bpy.ops.object.select_all(action="DESELECT")
        obj = bpy.data.objects[name + "_lod0"]
        obj.select_set(True)
        context.view_layer.objects.active = obj
        _activate_asset_lod0(context, name)
        self.report({"INFO"}, f"Added {name}. Inspect its LODs, then save and export Game FBX. This example has no skeleton.")
        return {"FINISHED"}


classes = (TF2_OT_WorkflowHelp, TF2_OT_ExportResult, TF2_OT_CreateExample)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
