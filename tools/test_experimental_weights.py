"""Run after load_dev_addon.py in a disposable Blender 5.2 session."""
import importlib
from mathutils import Vector
import bpy

tools = importlib.import_module('tf2-workshop-toolkit.weight_experimental')


def mesh(name, vertices, edges, faces):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, edges, faces)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


source = mesh('Reference', [(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)],
              [], [(0, 1, 2, 3)])
for name in ('head', 'neck'):
    source.vertex_groups.new(name=name)
for v in source.data.vertices:
    a = (5 - v.co.x) / 10
    source.vertex_groups['head'].add([v.index], a, 'REPLACE')
    source.vertex_groups['neck'].add([v.index], 1 - a, 'REPLACE')
coords = [((-1 if i % 2 else 1), (i - 3) * 0.5, 0) for i in range(7)]
near = mesh('Close scarf', coords, [(i, i + 1) for i in range(6)], [])
far = mesh('Far scarf', [(x, y, 5) for x, y, z in coords], [(i, i + 1) for i in range(6)], [])


def transfer(targets):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in [source] + targets:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = source
    return bpy.ops.object.distance_weight_transfer(iterations=8)


assert transfer([near, far]) == {'FINISHED'}
for v in near.data.vertices:
    expected = (5 - v.co.x) / 10
    assert abs(near.vertex_groups['head'].weight(v.index) - expected) < 1e-5
for obj in (near, far):
    for v in obj.data.vertices:
        weights = [g.weight for g in v.groups if g.weight > 0]
        assert len(weights) <= 3 and abs(sum(weights) - 1) < 1e-5
assert sum(abs(far.vertex_groups['head'].weight(i) - 0.5) for i in range(7)) < 0.1

# Edit Mode: only the chosen vertex is overwritten, and mode/active object survive.
bpy.context.view_layer.objects.active = near
for v in near.data.vertices:
    v.select = v.index == 3
near.vertex_groups['head'].add([0], 0.91, 'REPLACE')
near.vertex_groups['neck'].add([0], 0.09, 'REPLACE')
bpy.ops.object.mode_set(mode='EDIT')
import bmesh
bpy.ops.mesh.select_all(action='DESELECT')
edit_mesh = bmesh.from_edit_mesh(near.data)
edit_mesh.verts.ensure_lookup_table()
edit_mesh.verts[3].select_set(True)
bmesh.update_edit_mesh(near.data)
assert bpy.ops.object.distance_weight_transfer() == {'FINISHED'}
assert near.mode == 'EDIT'
bpy.ops.object.mode_set(mode='OBJECT')
assert abs(near.vertex_groups['head'].weight(0) - 0.91) < 1e-5

# Zero-weight locked groups must never get introduced by normalization.
assert tools.constrain({0: 0.7, 1: 0.3}, {0: 0}) == {1: 1.0}
limited = tools.constrain({0: 0.4, 1: 0.3, 2: 0.2, 3: 0.1})
assert len(limited) == 3 and abs(sum(limited.values()) - 1) < 1e-6
try:
    tools.constrain({i: 0.25 for i in range(4)}, {i: 0.25 for i in range(4)})
    raise AssertionError('Impossible locked constraints should fail')
except ValueError:
    pass

# Gradient: direction, clamping, mask, and zero-length protection.
points = [Vector((x, 0)) for x in (-1, 0, 5, 10, 11)]
amounts = tools.gradient_amounts(points, Vector((0, 0)), Vector((10, 0)), 0.8, {0, 1, 2, 3})
assert amounts == [0, 0, 0.4, 0.8, 0]
assert tools.gradient_amounts(points, Vector((0, 0)), Vector((0, 0)), 1, set(range(5))) == [0] * 5

# Preview is computed from baseline each time, and cancel restores it exactly.
from types import SimpleNamespace
original = tools.read_weights(far, tools.group_indices(far))
fake = SimpleNamespace(obj=far, original=original, indices=tools.group_indices(far),
                       points=[Vector((i, 0)) for i in range(7)],
                       start=Vector((0, 0)), end=Vector((6, 0)), strength=0.8,
                       affected={2, 3, 4, 5, 6},
                       neighbors=tools.adjacency(far.data, far.matrix_world), iterations=5)
preview = tools.WEIGHT_OT_smooth_gradient.preview
preview(fake)
first = tools.read_weights(far, fake.indices)
preview(fake)
second = tools.read_weights(far, fake.indices)
assert first == second
assert first[0] == original[0] and first[1] == original[1]
tools.write_maps(far, dict(enumerate(original)), fake.indices)
assert tools.read_weights(far, fake.indices) == original

# Weight Paint supports live updates too, with locks held exactly constant.
bpy.ops.object.select_all(action='DESELECT')
far.select_set(True)
bpy.context.view_layer.objects.active = far
bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
preview(fake)
preview(fake)
tools.write_maps(far, dict(enumerate(original)), fake.indices)
assert tools.read_weights(far, fake.indices) == original
bpy.ops.object.mode_set(mode='OBJECT')
far.vertex_groups['head'].lock_weight = True
preview(fake)
assert all(abs(far.vertex_groups['head'].weight(i) - original[i][far.vertex_groups['head'].index]) < 1e-6
           for i in fake.affected)
far.vertex_groups['head'].lock_weight = False
tools.write_maps(far, dict(enumerate(original)), fake.indices)

# Actual Scout reference: sample its real-world scale, and preserve source pose flags.
path = r'C:\Users\getgr\Downloads\scout_reference_for_chatgpt.blend'
from pathlib import Path
if Path(path).exists():
    with bpy.data.libraries.load(path, link=False) as (available, loaded):
        loaded.objects = ['scout_morphs_low']
    scout = loaded.objects[0]
    bpy.context.scene.collection.objects.link(scout)
    normals = []
    samples = []
    for index in range(0, len(scout.data.vertices), 25):
        vertex = scout.data.vertices[index]
        if vertex.groups:
            samples.append(scout.matrix_world @ vertex.co)
    scarf = mesh('Scout scale test', samples,
                 [(i, i + 1) for i in range(len(samples) - 1)], [])
    flags = [(m, m.show_viewport) for m in scout.modifiers if m.type == 'ARMATURE']
    bpy.ops.object.select_all(action='DESELECT')
    scout.select_set(True)
    scarf.select_set(True)
    bpy.context.view_layer.objects.active = scout
    assert bpy.ops.object.distance_weight_transfer() == {'FINISHED'}
    assert all(m.show_viewport == flag for m, flag in flags)
    for vertex in scarf.data.vertices:
        weights = [g.weight for g in vertex.groups if g.weight > 1e-7]
        assert 0 < len(weights) <= 3 and abs(sum(weights) - 1) < 1e-5
print('PASS: close surface fidelity, far smoothing, normalization/limit, selection, '
      'locked constraints, gradient ramp, non-accumulating preview, cancellation baseline, and Scout scale')
