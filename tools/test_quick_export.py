"""Run after load_dev_addon.py in a disposable --background --factory-startup session."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import importlib

import bpy


with tempfile.TemporaryDirectory(prefix="tf2_export_test_") as directory:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.object.armature_add()
    rig = bpy.context.object
    rig.name = "TestRig"
    bone = rig.data.bones[0].name
    hidden_coll = bpy.data.collections.new("HiddenRigCollection")
    bpy.context.scene.collection.children.link(hidden_coll)
    for coll in list(rig.users_collection):
        coll.objects.unlink(rig)
    hidden_coll.objects.link(rig)
    for lod in range(3):
        coll = bpy.data.collections.new(f"test_lod{lod}")
        bpy.context.scene.collection.children.link(coll)
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        for owner in list(obj.users_collection):
            owner.objects.unlink(obj)
        coll.objects.link(obj)
        group = obj.vertex_groups.new(name=bone)
        group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
        obj.modifiers.new("Rig", "ARMATURE").object = rig
        # Cover both conversion paths and alphabetical material ordering.
        if lod == 1:
            obj.shape_key_add(name="Basis")
            obj.shape_key_add(name="TestShape")
        for name in ("Z_test", "A_test"):
            mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
            obj.data.materials.append(mat)
        for face in obj.data.polygons:
            face.material_index = face.index % 2
    asset = bpy.context.scene.tf2_assets.add()
    asset.old_name = "test"
    asset.name = "test"
    asset.do_export = True
    rig.pose.bones[bone].location.x = 3.0
    rig.data.pose_position = "POSE"
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(directory) / "test.blend"))

    # Hidden object, disabled selection, and hidden collection together.
    rig.hide_set(True)
    rig.hide_viewport = True
    rig.hide_render = True
    rig.hide_select = True
    layer_coll = bpy.context.view_layer.layer_collection.children[hidden_coll.name]
    hidden_coll.hide_viewport = True
    assert bpy.ops.tf2.quick_export() == {"FINISHED"}
    assert rig.data.pose_position == "POSE"
    assert rig.hide_viewport and rig.hide_render and rig.hide_select
    assert hidden_coll.hide_viewport
    hidden_coll.hide_viewport = False
    bpy.context.view_layer.update()
    assert rig.hide_get()

    # Exclusion removes the object's view-layer base (including its hide flag).
    # Verify collection exclusion separately from the per-object hide state.
    layer_coll.exclude = True
    assert bpy.ops.tf2.quick_export() == {"FINISHED"}
    assert layer_coll.exclude
    layer_coll.exclude = False
    bpy.context.view_layer.update()

    # Also run while the user is actually in Pose Mode.
    rig.hide_viewport = rig.hide_render = rig.hide_select = False
    rig.hide_set(False)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    assert bpy.ops.tf2.quick_export() == {"FINISHED"}
    assert rig.mode == "POSE" and rig.data.pose_position == "POSE"
    assert abs(rig.pose.bones[bone].location.x - 3.0) < 1e-6
    bpy.ops.object.mode_set(mode="OBJECT")

    for lod in range(3):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=str(Path(directory) / "mesh" / f"test_lod{lod}.fbx"))
        imported = set(bpy.data.objects) - before
        assert sum(o.type == "ARMATURE" for o in imported) == (1 if lod == 0 else 0)
        mesh = next(o for o in imported if o.type == "MESH")
        xs = [(mesh.matrix_world @ v.co).x for v in mesh.data.vertices]
        assert abs(min(xs) + 1.0) < 1e-4 and abs(max(xs) - 1.0) < 1e-4, xs
        assert [m.name.split('.')[0] for m in mesh.data.materials] == ["A_test", "Z_test"]
        if lod == 1:
            assert "TestShape" in mesh.data.shape_keys.key_blocks
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)
    assert not any(c.name.endswith("_temp") for c in bpy.data.collections)

    # Restoration must also happen when mesh preparation or the exporter fails.
    def fail_export(context):
        assert rig.data.pose_position == "REST"
        assert not rig.hide_get()
        rig.location.x = 42.0
        raise RuntimeError("deliberate export failure")

    rig.hide_set(True)
    matrix = rig.matrix_world.copy()
    operator = importlib.import_module("tf2-workshop-toolkit.asset_manager").TF2_OT_QuickExport
    try:
        operator.execute(SimpleNamespace(_execute_export=fail_export), bpy.context)
        raise AssertionError("Expected export failure")
    except RuntimeError as error:
        assert str(error) == "deliberate export failure"
    assert rig.hide_get() and rig.data.pose_position == "POSE"
    assert rig.matrix_world == matrix
    assert not any(c.name.endswith("_temp") for c in bpy.data.collections)

    # Preview export must continue to evaluate the user's current pose.
    rig.hide_set(False)
    assert bpy.ops.utility.export_preview_fbx() == {"FINISHED"}
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(Path(directory) / "bakes" / "test_substance.fbx"))
    meshes = [o for o in set(bpy.data.objects) - before if o.type == "MESH"]
    assert meshes
    for mesh in meshes:
        xs = [(mesh.matrix_world @ v.co).x for v in mesh.data.vertices]
        assert abs(min(xs) - 2.0) < 1e-4 and abs(max(xs) - 4.0) < 1e-4, xs
    print("PASS: hidden rig, excluded collection, rest geometry in all LODs, "
          "Pose Mode restoration, sorted materials, shape keys, failure restoration, "
          "posed preview, and cleanup")
