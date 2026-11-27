"""Run after load_dev_addon.py; real bakes from a hidden, excluded, posed reference."""
from pathlib import Path
import tempfile

import bpy


with tempfile.TemporaryDirectory(prefix='tf2_hidden_source_') as folder:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.object.armature_add()
    rig = bpy.context.object
    rig.pose.bones[0].location.x = 3
    bpy.ops.mesh.primitive_plane_add(size=2)
    source = bpy.context.object
    source.name = 'Hidden Reference'
    group = source.vertex_groups.new(name=rig.data.bones[0].name)
    group.add(list(range(4)), 1, 'REPLACE')
    source.modifiers.new('Pose', 'ARMATURE').object = rig
    material = bpy.data.materials.new('Hidden Reference Material')
    material.use_nodes = True
    source.data.materials.append(material)
    for label, color in [('$basetexture', (1, 0, 0, 1)), ('$bumpmap', (.5, .5, 1, .3))]:
        node = material.node_tree.nodes.new('ShaderNodeTexImage')
        node.label = label
        node.image = bpy.data.images.new(label, width=8, height=8, alpha=True)
        node.image.generated_color = color
        if label == '$bumpmap':
            node.image.colorspace_settings.name = 'Non-Color'
    hidden_collection = bpy.data.collections.new('Excluded Reference')
    bpy.context.scene.collection.children.link(hidden_collection)
    for obj in (source, rig):
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        hidden_collection.objects.link(obj)
    bpy.ops.mesh.primitive_plane_add(size=2, location=(3, 0, .01))
    target = bpy.context.object
    target.name = 'Visible Cosmetic'
    bpy.ops.object.select_all(action='DESELECT')
    target.select_set(True)
    source.hide_set(True)
    source.hide_viewport = source.hide_render = source.hide_select = True
    rig.hide_set(True)
    rig.hide_viewport = rig.hide_render = rig.hide_select = True
    hidden_collection.hide_viewport = hidden_collection.hide_render = True
    layer = bpy.context.view_layer.layer_collection.children[hidden_collection.name]
    layer.exclude = True
    bpy.context.scene.cycles.device = 'CPU'
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(folder) / 'hidden.blend'))
    counts = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    assert bpy.ops.utility.reproject_diffuse.poll()
    for kind, expected in [('DIFFUSE', (1, 0, 0)), ('NORMAL', (.5, .5, 1)), ('SPECULAR', (.3, .3, .3))]:
        assert bpy.ops.utility.reproject_diffuse(source_mesh=source.name, map_type=kind,
            apply_result=False, show_preview=False, ray_extrusion=.02, max_ray_distance=.1) == {'FINISHED'}
        image = bpy.data.images[f'{target.name}_reproj_{kind.lower()}']
        center = (512 * image.size[0] + 512) * 4
        values = tuple(image.pixels[center:center + 3])
        assert all(abs(a - b) < .015 for a, b in zip(values, expected)), (kind, values, expected)
        assert bpy.context.active_object == target
        assert set(bpy.context.selected_objects) == {target}
        assert layer.exclude and hidden_collection.hide_viewport and hidden_collection.hide_render
        assert all(o.hide_viewport and o.hide_render and o.hide_select for o in (source, rig))
        assert counts == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    layer.exclude = False
    hidden_collection.hide_viewport = False
    # Exclusion itself recreates Blender's view-layer bases. Set eye hides again
    # to check that baking also preserves them with a non-excluded collection.
    source.hide_set(True)
    rig.hide_set(True)
    assert bpy.ops.utility.reproject_diffuse(source_mesh=source.name, map_type='DIFFUSE',
        apply_result=False, show_preview=False, ray_extrusion=.02, max_ray_distance=.1) == {'FINISHED'}
    assert source.hide_get() and rig.hide_get()
    print('PASS: single selected cosmetic, explicit hidden source, excluded collection, hidden posed rig, '
          'all three maps, original visibility/selection and temporary-data cleanup')
