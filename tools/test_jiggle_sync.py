"""Run after load_dev_addon.py in a disposable Blender background session."""
import bpy


def make_rig(name, source=False):
    bpy.ops.object.select_all(action='DESELECT')
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    root = data.edit_bones.new('bip_head')
    root.head, root.tail = (0, 0, 1), (0, 0, 2)
    if source:
        parent = root
        for i, bone_name in enumerate(('j_tip', 'jiggle_tip', 'ponpon_j', 'tip_jiggle')):
            bone = data.edit_bones.new(bone_name)
            bone.head, bone.tail = (i + 1, 0, 2), (i + 1, 0, 3)
            bone.parent = parent
            parent = bone
        other = data.edit_bones.new('not_j_extra')
        other.head, other.tail = (0, 0, 1), (0, 0, 2)
        other.parent = root
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


source = make_rig('sniper_ARM', True)
hidden = make_rig('scout_ARM')
excluded = make_rig('soldier_ARM')
hidden.hide_set(True)
hidden.hide_viewport = True
hidden.hide_select = True
coll = bpy.data.collections.new('Excluded rigs')
bpy.context.scene.collection.children.link(coll)
for owner in list(excluded.users_collection):
    owner.objects.unlink(excluded)
coll.objects.link(excluded)
layer = bpy.context.view_layer.layer_collection.children[coll.name]
layer.exclude = True
bpy.ops.object.select_all(action='DESELECT')
source.select_set(True)
bpy.context.view_layer.objects.active = source
bpy.ops.object.mode_set(mode='POSE')
expected = {name: source.data.bones[name].matrix_local.copy()
            for name in ('j_tip', 'jiggle_tip', 'ponpon_j', 'tip_jiggle')}
for repeat in range(2):
    assert bpy.ops.utility.transfer_jiggle_hierarchy() == {'FINISHED'}
    assert source.mode == 'POSE'
    assert bpy.context.view_layer.objects.active == source
    assert hidden.hide_viewport and hidden.hide_select and hidden.hide_get()
    assert layer.exclude
    for target in (hidden, excluded):
        assert set(target.data.bones.keys()) == {'bip_head', *expected}
        for name, matrix in expected.items():
            bone = target.data.bones[name]
            assert bone.parent.name == source.data.bones[name].parent.name
            assert all(abs(bone.matrix_local[i][j] - matrix[i][j]) < 1e-5
                       for i in range(4) for j in range(4))
    assert not any(c.name.startswith('_tf2_jiggle_sync_temp') for c in bpy.data.collections)
print('PASS: active source, suffixes/prefixes, hidden/unselected/excluded targets, '
      'four-bone chain, repeat sync, and mode/visibility restoration')
