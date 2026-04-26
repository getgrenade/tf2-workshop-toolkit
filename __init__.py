bl_info = {
    "name": "Workshop Toolkit",
    "author": "GetGrenade",
    "version": (1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > WS Toolkit",
    "description": "Shortcuts and panels for easier tf2 cosmetic pipeline",
    "category": "Workflow",
}

import bpy
from . import asset_manager
from . import material_manager
from . import utility
from . import weight_tools
from . import preferences
from . import bake_tools

# ============================================================ #
#                   CORE REGISTRATION                          #
# ============================================================ #

addon_keymaps = []

def register():
    asset_manager.register()
    material_manager.register()
    utility.register()
    weight_tools.register()
    bake_tools.register()
    preferences.register()

    # --- Scene Properties ---
    bpy.types.Scene.tf2_assets = bpy.props.CollectionProperty(
        type=asset_manager.TF2AssetItem
    )
    bpy.types.Scene.tf2_pose_state = bpy.props.BoolProperty(default=True)
    bpy.types.Scene.pro_mat_props = bpy.props.PointerProperty(
        type=material_manager.PRO_MAT_Props
    )
    bpy.types.Scene.weight_smooth_iterations = bpy.props.IntProperty(
        name="Smooths",
        description="Number of times to loop the smooth algorithm before limiting/normalizing",
        default=5,
        min=1,
        max=50,
    )
    bpy.types.Scene.weight_target_bone = bpy.props.StringProperty(
        name="Target Bone",
        description="The vertex group to assign 100% weight to",
        default="bip_head",
    )

    # --- Keymaps ---
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.new(name="3D View", space_type="VIEW_3D")

        kmi = km.keymap_items.new("utility.toggle_pose_state", type="F4", value="PRESS")
        addon_keymaps.append((km, kmi))

        kmi_pie = km.keymap_items.new("wm.call_menu_pie", type="Q", value="PRESS", shift=True)
        kmi_pie.properties.name = "WEIGHT_MT_pie_menu"
        addon_keymaps.append((km, kmi_pie))

        print("Workshop Toolkit: Keymaps registered.")


def unregister():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    del bpy.types.Scene.tf2_assets
    del bpy.types.Scene.tf2_pose_state
    del bpy.types.Scene.pro_mat_props
    del bpy.types.Scene.weight_smooth_iterations
    del bpy.types.Scene.weight_target_bone

    preferences.unregister()
    bake_tools.unregister()
    weight_tools.unregister()
    utility.unregister()
    material_manager.unregister()
    asset_manager.unregister()


if __name__ == "__main__":
    register()
