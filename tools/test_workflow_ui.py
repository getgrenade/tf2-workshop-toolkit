"""Run after load_dev_addon.py in a disposable Blender background session."""
from pathlib import Path
import tempfile

import bpy


scene = bpy.context.scene
original_objects = set(bpy.data.objects)
assert bpy.ops.tf2.initialize_asset(asset_name="empty_cosmetic") == {"FINISHED"}
assert bpy.context.view_layer.active_layer_collection.name == "empty_cosmetic_lod0"
assert bpy.ops.tf2.create_example() == {"FINISHED"}
assert original_objects.issubset(set(bpy.data.objects))
assert bpy.context.object.name == "example_hat_lod0"
assert bpy.context.view_layer.active_layer_collection.name == "example_hat_lod0"
assert scene.tf2_assets["example_hat"].do_export
assert not scene.tf2_assets["example_hat"].is_library
counts = []
for suffix in ("_lod0", "_lod1", "_lod2", "_high"):
    coll = bpy.data.collections["example_hat" + suffix]
    obj = coll.objects[0]
    assert [mat.name for mat in obj.data.materials] == ["A_example_hat", "Z_example_hat"]
    assert obj.data.uv_layers
    assert set(face.material_index for face in obj.data.polygons) == {0, 1}
    counts.append(sum(len(face.vertices) - 2 for face in obj.data.polygons))
    assert coll.hide_viewport == (suffix != "_lod0")
assert counts[0] > counts[1] > counts[2]
assert counts[3] > counts[0]
assert "Wider" in bpy.context.object.data.shape_keys.key_blocks
assert bpy.ops.tf2.create_example() == {"FINISHED"}
assert scene.tf2_assets.get("example_hat_2") is not None
assert bpy.data.objects.get("example_hat_lod0") is not None

with tempfile.TemporaryDirectory(prefix="tf2_workflow_test_") as directory:
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(directory) / "example.blend"))
    scene.tf2_assets["example_hat_2"].do_export = False
    assert bpy.ops.tf2.quick_export() == {"FINISHED"}
    assert len(list((Path(directory) / "mesh").glob("*.fbx"))) == 3
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(Path(directory) / "mesh" / "example_hat_lod0.fbx"))
    imported = set(bpy.data.objects) - before
    mesh = next(obj for obj in imported if obj.type == "MESH")
    assert "Wider" in mesh.data.shape_keys.key_blocks
print("PASS: active LOD0, non-destructive examples, unique names, LOD complexity, "
      "materials, UVs, visibility, and example FBX round-trip")
