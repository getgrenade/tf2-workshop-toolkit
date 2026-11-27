"""Run after load_dev_addon.py in a disposable Blender session."""
import importlib
from math import isinf
from mathutils import Vector

import bpy

radius_tools = importlib.import_module('tf2-workshop-toolkit.weight_radius')
weights = importlib.import_module('tf2-workshop-toolkit.weight_experimental')
coords = [Vector((i, 0, 0)) for i in range(7)] + [Vector((0.1, 0, 0))]
edges = [(i, i + 1) for i in range(6)]
distances, amounts, _ = radius_tools.soft_region(coords, edges, set(range(8)), {0}, 2.5)
assert distances[:4] == [0, 1, 2, 3]
assert 1 == amounts[0] > amounts[1] > amounts[2] > 0
assert amounts[3:] == [0] * 5 and isinf(distances[7])
_, hidden_amounts, _ = radius_tools.soft_region(coords, edges, {0, 2, 3, 4, 5, 6, 7}, {0}, 3)
assert hidden_amounts[1:] == [0] * 7
_, scaled, _ = radius_tools.soft_region([v * 10 for v in coords], edges, set(range(8)), {0}, 25)
assert all(abs(a - b) < 1e-6 for a, b in zip(amounts, scaled))
boundary = radius_tools.cutoff_lines([Vector((0, 0, 0)), Vector((4, 0, 0)),
                                    Vector((4, 1, 0)), Vector((0, 1, 0))],
                                   [(0, 1, 2, 3)], [0, 4, 4, 0], 2)
assert len(boundary) == 2 and all(abs(p.x - 2) < 1e-5 for p in boundary)

data = bpy.data.meshes.new('Soft Radius Test')
data.from_pydata(coords, edges, [])
obj = bpy.data.objects.new('Soft Radius Test', data)
bpy.context.scene.collection.objects.link(obj)
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
for name in ('head', 'neck'):
    obj.vertex_groups.new(name=name)
for v in data.vertices:
    obj.vertex_groups[v.index % 2].add([v.index], 1.0, 'REPLACE')
    v.select = v.index == 0
original = weights.read_weights(obj, {0, 1})
bpy.context.scene.weight_soft_radius = True
bpy.context.scene.weight_soft_distance = 2.5
bpy.context.scene.weight_smooth_iterations = 5
assert bpy.ops.object.weight_smooth_limit_normalize() == {'FINISHED'}
result = weights.read_weights(obj, {0, 1})
assert all(result[i] != original[i] for i in (0, 1, 2))
assert all(result[i] == original[i] for i in (3, 4, 5, 6, 7))
for value in result:
    assert len(value) <= 3 and abs(sum(value.values()) - 1) < 1e-5
assert {v.index for v in data.vertices if v.select} == {0}
assert not data.use_paint_mask_vertex  # soft radius must not change paint-mask settings

# Edit Mode selection comes from the edit mesh, not stale object-mode flags.
weights.write_maps(obj, dict(enumerate(original)), {0, 1})
bpy.ops.object.mode_set(mode='EDIT')
import bmesh
bpy.ops.mesh.select_all(action='DESELECT')
bm = bmesh.from_edit_mesh(data)
bm.verts.ensure_lookup_table()
bm.verts[0].select_set(True)
bmesh.update_edit_mesh(data)
display = radius_tools.geometry(obj, bpy.context)
assert display[-1] == {0}
assert bpy.ops.object.weight_smooth_limit_normalize() == {'FINISHED'}
assert obj.mode == 'EDIT'
bpy.ops.object.mode_set(mode='OBJECT')
result = weights.read_weights(obj, {0, 1})
assert all(result[i] == original[i] for i in (3, 4, 5, 6, 7))

# Existing locked weights are held exactly constant while nearby vertices smooth.
weights.write_maps(obj, dict(enumerate(original)), {0, 1})
obj.vertex_groups[0].lock_weight = True
before = weights.read_weights(obj, {0, 1})
assert bpy.ops.object.weight_smooth_limit_normalize() == {'FINISHED'}
after = weights.read_weights(obj, {0, 1})
assert all(abs(before[i].get(0, 0) - after[i].get(0, 0)) < 1e-6 for i in range(8))
print('PASS: surface falloff, adjustable/world-space radius, disconnected/hidden protection, '
      'boundary indicator geometry, nearby smoothing, normalization/limit, Edit Mode, locks and selection restoration')

# On Cage: posed coordinates and distances must be the same in the edit preview
# and when the operator temporarily leaves Edit Mode to write weights.
obj.vertex_groups[0].lock_weight = False
rig_data = bpy.data.armatures.new('Cage Rig')
rig = bpy.data.objects.new('Cage Rig', rig_data)
bpy.context.scene.collection.objects.link(rig)
bpy.ops.object.select_all(action='DESELECT')
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='EDIT')
for name in ('head', 'neck'):
    bone = rig_data.edit_bones.new(name)
    bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
bpy.ops.object.mode_set(mode='OBJECT')
for bone in rig.pose.bones:
    bone.location.x = 10
    bone.scale.x = 2
modifier = obj.modifiers.new('On Cage Pose', 'ARMATURE')
modifier.object = rig
modifier.show_in_editmode = True
modifier.show_on_cage = True
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.context.view_layer.update()
bpy.ops.object.mode_set(mode='EDIT')
preview = radius_tools.geometry(obj, bpy.context)
assert abs(preview[0][0].x - 10) < 1e-4, preview[0][0]
assert abs(preview[0][1].x - 12) < 1e-4, preview[0][1]
_, preview_amounts, _ = radius_tools.soft_region(preview[0], preview[1], preview[3], preview[4], 2.5)
assert preview_amounts[1] > 0 and preview_amounts[2] == 0
bpy.ops.object.mode_set(mode='OBJECT')
applied_geometry = radius_tools.geometry(obj, bpy.context, 'EDIT')
assert all((a - b).length < 1e-4 for a, b in zip(preview[0], applied_geometry[0]))
modifier.show_on_cage = False
rest = radius_tools.geometry(obj, bpy.context, 'EDIT')
assert abs(rest[0][0].x) < 1e-4
print('PASS: posed On Cage positions, scaled surface distances, and preview/apply agreement; cage-off uses original edit coordinates')
