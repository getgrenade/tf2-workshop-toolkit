"""Run after load_dev_addon.py in a disposable Blender session."""
import importlib
import bpy
import bmesh

tools = importlib.import_module('tf2-workshop-toolkit.weight_tools')
weights = importlib.import_module('tf2-workshop-toolkit.weight_experimental')
radius = importlib.import_module('tf2-workshop-toolkit.weight_radius')

# Small targets must survive; the two strongest other influences retain their ratio.
result = tools.assign_bone_map({0: .5, 1: .3, 2: .2}, 3, .01, 1, {})
assert abs(result[3] - .01) < 1e-8 and set(result) == {0, 1, 3}
assert abs(result[0] / result[1] - 5 / 3) < 1e-8
assert tools.assign_bone_map({0: 1}, 1, 1, 1, {}) == {1: 1}
assert tools.assign_bone_map({0: .8, 1: .2}, 1, 0, 1, {}) == {0: 1}
assert tools.assign_bone_map({0: .5, 1: .3, 2: .2}, 3, .25, 1, {2: .2}) == {2: .2, 3: .25, 0: .55}
for original, locked, value in [({}, {}, .25),
                                 ({0: .8, 1: .2}, {0: .8}, .3),
                                 ({0: .4, 1: .3, 2: .3}, {0: .4, 1: .3, 2: .3}, .1)]:
    try:
        tools.assign_bone_map(original, 3, value, 1, locked)
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid assignment was accepted')

bpy.ops.object.select_all(action='DESELECT')
data = bpy.data.meshes.new('Assignment test')
data.from_pydata([(i, 0, 0) for i in range(6)] + [(0.1, 0, 0)],
                 [(i, i + 1) for i in range(5)], [])
obj = bpy.data.objects.new('Assignment test', data)
bpy.context.scene.collection.objects.link(obj)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
for name, value in [('body', .5), ('neck', .3), ('spine', .2)]:
    obj.vertex_groups.new(name=name).add(list(range(7)), value, 'REPLACE')
scene = bpy.context.scene
scene.weight_target_bone = 'bip_head'
scene.weight_assign_value = .25


def select(indices, hidden=()):
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bm = bmesh.from_edit_mesh(data)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        v.hide_set(v.index in hidden)
        v.select_set(v.index in indices)
    bmesh.update_edit_mesh(data)


def apply():
    assert bpy.ops.mesh.assign_selected_bone_weight() == {'FINISHED'}
    assert obj.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    maps = weights.read_weights(obj, weights.group_indices(obj))
    for value in maps:
        assert len(value) <= 3 and abs(sum(value.values()) - 1) < 1e-6
    return maps


original = weights.read_weights(obj, {0, 1, 2})
scene.weight_soft_radius = False
select({0})
result = apply()
head = obj.vertex_groups['bip_head'].index
assert abs(result[0][head] - .25) < 1e-6 and set(result[0]) == {0, 1, head}
assert result[1:] == original[1:]

weights.write_maps(obj, dict(enumerate(original)), {0, 1, 2, head})
scene.weight_soft_radius = True
scene.weight_soft_distance = 2.5
select({0})
preview = radius.geometry(obj, bpy.context)
_, amounts, _ = radius.soft_region(preview[0], preview[1], preview[3], preview[4], 2.5)
result = apply()
for i in range(3):
    assert abs(result[i][head] - .25 * amounts[i]) < 1e-6
assert result[3:] == original[3:]
assert {v.index for v in data.vertices if v.select} == {0}

# Existing target weights fade toward the chosen value (including reductions).
scene.weight_assign_value = .1
select({0})
reduced = apply()
for i in range(3):
    expected = result[i][head] * (1 - amounts[i]) + .1 * amounts[i]
    assert abs(reduced[i][head] - expected) < 1e-6

# A failure on a later vertex must not partially update the earlier one.
scene.weight_soft_radius = False
obj.vertex_groups[0].lock_weight = True
obj.vertex_groups[0].add([1], .95, 'REPLACE')
before = weights.read_weights(obj, {0, 1, 2, head})
scene.weight_assign_value = .2
select({0, 1})
try:
    outcome = bpy.ops.mesh.assign_selected_bone_weight()
    assert outcome == {'CANCELLED'}
except RuntimeError as error:
    assert 'Locked weights' in str(error)
assert obj.mode == 'EDIT'
bpy.ops.object.mode_set(mode='OBJECT')
assert weights.read_weights(obj, {0, 1, 2, head}) == before
obj.vertex_groups[0].lock_weight = False
weights.write_maps(obj, {1: reduced[1]}, {0, 1, 2, head})

# Rig-aware assignments preserve utility/mask groups and reject typo bone names.
rig_data = bpy.data.armatures.new('Assignment Rig')
rig = bpy.data.objects.new('Assignment Rig', rig_data)
bpy.context.scene.collection.objects.link(rig)
obj.select_set(False)
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='EDIT')
for name in ('body', 'neck', 'spine', 'bip_head'):
    bone = rig_data.edit_bones.new(name)
    bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
bpy.ops.object.mode_set(mode='OBJECT')
rig.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
obj.modifiers.new('Rig', 'ARMATURE').object = rig
mask = obj.vertex_groups.new(name='Utility Mask')
mask.add([0], .7, 'REPLACE')
select({0}, hidden={1})
apply()
assert abs(mask.weight(0) - .7) < 1e-6
scene.weight_target_bone = 'typo_head'
select({0})
try:
    outcome = bpy.ops.mesh.assign_selected_bone_weight()
    assert outcome == {'CANCELLED'}
except RuntimeError as error:
    assert 'not a deform bone' in str(error)
assert obj.vertex_groups.get('typo_head') is None and obj.mode == 'EDIT'
bpy.ops.object.mode_set(mode='OBJECT')

# Registration must clean up the new operator and property on reload.
addon = importlib.import_module('tf2-workshop-toolkit')
addon.unregister()
assert not hasattr(bpy.types.Scene, 'weight_assign_value')
addon.register()
assert hasattr(bpy.types.Scene, 'weight_assign_value')
print('PASS: selected bone assignment, target reservation, normalized max-3 weights, '
      'falloff, reduction/removal, locked-group atomicity, utility preservation and registration')
