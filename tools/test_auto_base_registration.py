"""Run after load_dev_addon.py in a disposable Blender background session."""
import importlib
from pathlib import Path
import tempfile

import addon_utils
import bpy


manager = importlib.import_module("tf2-workshop-toolkit.asset_manager")
assert bpy.app.timers.is_registered(manager._auto_register_base_assets)

with tempfile.TemporaryDirectory(prefix="tf2_base_test_") as directory:
    # Build a small library with the same structure used by Quick Loader.
    root = bpy.data.collections.new("scout")
    lod = bpy.data.collections.new("scout_morphs_low_lod0")
    root.children.link(lod)
    mesh = bpy.data.meshes.new("scout_mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("scout_body", mesh)
    lod.objects.link(obj)
    material = bpy.data.materials.new("original_scout_material")
    mesh.materials.append(material)
    path = str(Path(directory) / "mercs.blend")
    bpy.data.libraries.write(path, {root})
    manager._auto_register_base_assets()
    assert not bpy.context.scene.tf2_assets, "Unlinked library data is not in the scene"
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(lod)
    bpy.data.collections.remove(root)
    bpy.data.meshes.remove(mesh)
    bpy.data.materials.remove(material)

    # Exercise the installed spawner itself, with a temporary library setting.
    loader = addon_utils.enable("tf2_quick_loader", default_set=True)
    assert loader is not None
    prefs = bpy.context.preferences.addons["tf2_quick_loader"].preferences
    old_path = prefs.filepath
    try:
        prefs.filepath = path
        assert bpy.ops.object.spawn_tf2_asset(asset_name="scout") == {"FINISHED"}
    finally:
        prefs.filepath = old_path
    manager._auto_register_base_assets()
    assets = bpy.context.scene.tf2_assets
    assert len(assets) == 1
    assert assets[0].name == assets[0].old_name == "scout"
    assert assets[0].is_library and not assets[0].do_export
    assert bpy.data.materials.get("original_scout_material") is not None
    manager._auto_register_base_assets()
    assert len(assets) == 1, "Repeated scans must not duplicate entries"

    other = bpy.data.scenes.new("Other scene")
    manager._auto_register_base_assets()
    assert not other.tf2_assets, "Do not register mercs from another scene"
    other.collection.children.link(bpy.data.collections["scout"])
    manager._auto_register_base_assets()
    assert len(other.tf2_assets) == 1 and other.tf2_assets[0].is_library

    # Ordinary cosmetics and incomplete collections still require manual setup.
    cosmetic = bpy.data.collections.new("hat_lod0")
    bpy.context.scene.collection.children.link(cosmetic)
    empty = bpy.data.collections.new("medic_morphs_low_lod0")
    bpy.context.scene.collection.children.link(empty)
    manager._auto_register_base_assets()
    assert len(assets) == 1
    # Register when a delayed importer has finished populating the collection.
    empty.objects.link(bpy.data.objects["scout_body"])
    manager._auto_register_base_assets()
    assert {item.name for item in assets} == {"scout", "medic"}
    assert all(item.is_library for item in assets)

    addon_utils.disable("tf2-workshop-toolkit", default_set=False)
    assert not bpy.app.timers.is_registered(manager._auto_register_base_assets)
    print("PASS: actual merc spawner, BASE flags, no duplicates, unchanged materials, "
          "scene isolation, delayed imports, and timer cleanup")
