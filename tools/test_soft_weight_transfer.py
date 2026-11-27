"""Run after load_dev_addon.py in a disposable Blender session."""
import bpy
import bmesh
import importlib

weights = importlib.import_module('tf2-workshop-toolkit.weight_experimental')


def mesh(name, points, edges):
    data = bpy.data.meshes.new(name)
    data.from_pydata(points, edges, [])
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


source = mesh('Reference', [(0, 0, 0), (4, 0, 0)], [(0, 1)])
source.vertex_groups.new(name='head').add([0, 1], 1, 'REPLACE')
target = mesh('Scarf', [(i, 0, 0) for i in range(5)] + [(0.1, 0, 0)],
              [(i, i + 1) for i in range(4)])
target.vertex_groups.new(name='neck').add(list(range(6)), 1, 'REPLACE')
target.shape_key_add(name='Basis')
target.shape_key_add(name='Scarf Shape')
for v in target.data.vertices:
    v.select = v.index == 0
bpy.ops.object.select_all(action='DESELECT')
source.select_set(True)
target.select_set(True)
bpy.context.view_layer.objects.active = source
bpy.context.scene.weight_soft_radius = True
bpy.context.scene.weight_soft_distance = 2.5
objects = set(bpy.data.objects)
meshes = set(bpy.data.meshes)
assert bpy.ops.object.quick_weight_transfer() == {'FINISHED'}
result = weights.read_weights(target, weights.group_indices(target))
head, neck = target.vertex_groups['head'].index, target.vertex_groups['neck'].index
assert result[0] == {head: 1}
for i in (1, 2):
    factor = 1 - i / 2.5
    expected = factor * factor * (3 - 2 * factor)
    assert abs(result[i][head] - expected) < 1e-5
    assert abs(result[i][neck] - (1 - expected)) < 1e-5
assert all(result[i] == {neck: 1} for i in (3, 4, 5))
assert len(target.data.shape_keys.key_blocks) == 2
assert bpy.context.object == source and set(bpy.context.selected_objects) == {source, target}
assert set(bpy.data.objects) == objects and set(bpy.data.meshes) == meshes

# Edit Mode keeps active target/selection and uses the same shared radius.
target.vertex_groups['head'].remove(list(range(6)))
target.vertex_groups['neck'].add(list(range(6)), 1, 'REPLACE')
bpy.context.view_layer.objects.active = target
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='DESELECT')
bm = bmesh.from_edit_mesh(target.data)
bm.verts.ensure_lookup_table()
bm.verts[0].select_set(True)
bmesh.update_edit_mesh(target.data)
assert bpy.ops.object.quick_weight_transfer() == {'FINISHED'}
assert target.mode == 'EDIT'
bpy.ops.object.mode_set(mode='OBJECT')
assert abs(target.vertex_groups['head'].weight(1) - result[1][head]) < 1e-5
assert target.vertex_groups['neck'].weight(5) == 1

# Distance Transfer shares the same soft selection and blend, too.
source.data.clear_geometry()
source.data.from_pydata([(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)], [], [(0, 1, 2, 3)])
(source.vertex_groups.get('head') or source.vertex_groups.new(name='head')).add([0, 1, 2, 3], 1, 'REPLACE')
target.vertex_groups['head'].remove(list(range(6)))
target.vertex_groups['neck'].add(list(range(6)), 1, 'REPLACE')
for v in target.data.vertices:
    v.select = v.index == 0
bpy.context.view_layer.objects.active = source
assert bpy.ops.object.distance_weight_transfer() == {'FINISHED'}
experimental = weights.read_weights(target, weights.group_indices(target))
assert all(abs(experimental[i].get(head, 0) - result[i].get(head, 0)) < 1e-5 for i in range(6))

# Transfer's mask follows a stretched On Cage pose, even though the sampling
# itself bypasses armature deformation. Pose/modifier flags must be restored.
rig_data = bpy.data.armatures.new('Transfer Cage')
rig = bpy.data.objects.new('Transfer Cage', rig_data)
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
for obj in (source, target):
    modifier = obj.modifiers.new('On Cage', 'ARMATURE')
    modifier.object = rig
    modifier.show_in_editmode = modifier.show_on_cage = True
target.vertex_groups['head'].remove(list(range(6)))
target.vertex_groups['neck'].add(list(range(6)), 1, 'REPLACE')
bpy.ops.object.select_all(action='DESELECT')
source.select_set(True)
target.select_set(True)
bpy.context.view_layer.objects.active = target
bpy.context.view_layer.update()
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='DESELECT')
bm = bmesh.from_edit_mesh(target.data)
bm.verts.ensure_lookup_table()
bm.verts[0].select_set(True)
bmesh.update_edit_mesh(target.data)
assert bpy.ops.object.quick_weight_transfer() == {'FINISHED'}
assert target.mode == 'EDIT'
bpy.ops.object.mode_set(mode='OBJECT')
assert abs(target.vertex_groups['head'].weight(1) - 0.104) < 1e-5
assert target.vertex_groups['neck'].weight(2) == 1
assert all(m.show_viewport for obj in (source, target) for m in obj.modifiers)
assert rig.pose.bones['head'].location.x == 10

# Turning the shared checkbox off returns to the unmodified native Transfer.
bpy.context.scene.weight_soft_radius = False
bpy.context.view_layer.objects.active = source
# Existing native modifier_apply cannot handle shape keys; test a plain target.
plain = mesh('Plain target', [(i, 1, 0) for i in range(5)], [(i, i + 1) for i in range(4)])
bpy.ops.object.select_all(action='DESELECT')
plain.select_set(True)
source.select_set(True)
bpy.context.view_layer.objects.active = source
assert bpy.ops.object.quick_weight_transfer() == {'FINISHED'}
assert all(abs(plain.vertex_groups['head'].weight(i) - 1) < 1e-5 for i in range(5))
print('PASS: shared radius for Transfer, exact core, partial blend nearby, unchanged outside/disconnected, '
      'shape keys, Edit Mode, selection restoration, no temporary leaks, and native Transfer when disabled')
