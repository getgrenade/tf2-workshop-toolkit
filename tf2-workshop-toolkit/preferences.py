"""
Workshop Toolkit – Addon Preferences Module
Exposes hotkey remapping in the addon preferences panel.
"""

import bpy


class Toolkit_Preferences(bpy.types.AddonPreferences):
    # __package__ resolves to 'Workshop_Toolkit' when loaded as a package
    bl_idname = __package__

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Hotkey Settings", icon="PREFERENCES")

        wm = context.window_manager
        kc = wm.keyconfigs.addon
        if not kc:
            return

        km = kc.keymaps.get("3D View")
        if not km:
            return

        # F4 – Toggle Pose
        kmi_pose = next(
            (i for i in km.keymap_items if i.idname == "utility.toggle_pose_state"),
            None,
        )
        if kmi_pose:
            row = layout.row(align=True)
            row.label(text="Toggle Pose Shortcut:")
            row.prop(kmi_pose, "type", text="", full_event=True)

        # Shift + Q – Weight Pie Menu
        kmi_pie = next(
            (
                i
                for i in km.keymap_items
                if i.idname == "wm.call_menu_pie"
                and i.properties.name == "WEIGHT_MT_pie_menu"
            ),
            None,
        )
        if kmi_pie:
            row = layout.row(align=True)
            row.label(text="Weight Pie Menu Shortcut:")
            row.prop(kmi_pie, "type", text="", full_event=True)


classes = (Toolkit_Preferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
