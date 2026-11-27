"""Real CPU bakes; run after load_dev_addon.py in a disposable Blender session."""
import importlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import bpy

reproject = importlib.import_module('tf2-workshop-toolkit.reproject')
utility = importlib.import_module('tf2-workshop-toolkit.utility')


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    node = mat.node_tree.nodes.new('ShaderNodeTexImage')
    node.label = '$basetexture test'
    node.image = bpy.data.images.new(name, width=8, height=8)
    node.image.generated_color = color
    shader = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    mat.node_tree.links.new(node.outputs['Color'], shader.inputs['Base Color'])
    return mat, node


def snapshot(mat):
    return ([(n.name, n.type, n.image.name if n.type == 'TEX_IMAGE' and n.image else None)
             for n in mat.node_tree.nodes],
            [(l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name)
             for l in mat.node_tree.links])


with tempfile.TemporaryDirectory(prefix='tf2_reproject_') as folder:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_plane_add(size=2)
    source = bpy.context.object
    source.name = 'Reference'
    source_mat, source_tex = material('Reference Red', (1, 0, 0, 1))
    source.data.materials.append(source_mat)
    bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, .01))
    target = bpy.context.object
    target.name = 'Cosmetic'
    target_mat, diffuse = material('Cosmetic Original', (0, 0, 1, 1))
    target.data.materials.append(target_mat)
    # A second face/material covers the multi-material destination case.
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.subdivide(number_cuts=1)
    bpy.ops.object.mode_set(mode='OBJECT')
    second, _ = material('Cosmetic Second', (0, 1, 0, 1))
    target.data.materials.append(second)
    target.data.polygons[0].material_index = 1
    # Object-linked material override must also be respected while sampling.
    target.material_slots[1].link = 'OBJECT'
    # Another object shares the first material: applying must isolate the cosmetic.
    bpy.ops.mesh.primitive_plane_add(location=(10, 0, 0))
    other = bpy.context.object
    other.data.materials.append(target_mat)
    bpy.ops.object.select_all(action='DESELECT')
    source.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.context.scene.cycles.device = 'CPU'
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(folder) / 'reprojection.blend'))
    # The confirmation/options dialog must open even for just one source material.
    dialogs = []
    dialog_context = SimpleNamespace(selected_objects=[source, target], active_object=target,
        window_manager=SimpleNamespace(invoke_props_dialog=lambda op, **kwargs:
            dialogs.append(kwargs) or {'RUNNING_MODAL'}))
    assert utility.UTILITY_OT_ReprojectDiffuse.invoke(SimpleNamespace(), dialog_context, None) == {'RUNNING_MODAL'}
    assert dialogs == [{'width': 420}]
    before_source = snapshot(source_mat)
    before_target = snapshot(target_mat)
    before_second = snapshot(second)
    original_engine = bpy.context.scene.render.engine
    original_samples = bpy.context.scene.cycles.samples
    counts = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    native_bake = bpy.ops.object.bake

    # Explicit distances/padding reach Blender. No application leaves materials intact.
    bpy.context.scene.bake_props.bake_padding = 16
    def checked_bake(**kwargs):
        assert kwargs['margin'] == 16 and kwargs['margin_type'] == 'EXTEND'
        assert abs(kwargs['cage_extrusion'] - .02) < 1e-6
        assert abs(kwargs['max_ray_distance'] - .1) < 1e-6
        assert not kwargs['use_cage'] and kwargs['cage_object'] == ''
        return native_bake(**kwargs)
    def bake_api(bake):
        return SimpleNamespace(data=bpy.data, app=bpy.app, ops=SimpleNamespace(
            object=SimpleNamespace(bake=bake, select_all=bpy.ops.object.select_all)))
    with patch.object(reproject, 'bpy', bake_api(checked_bake)):
        assert bpy.ops.utility.reproject_diffuse(apply_result=False, show_preview=False,
                    ray_extrusion=.02, max_ray_distance=.1) == {'FINISHED'}
    assert snapshot(source_mat) == before_source
    assert snapshot(target_mat) == before_target
    assert snapshot(second) == before_second
    assert counts == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    previous = bpy.data.images['Cosmetic_reproj_diffuse']
    assert max(previous.pixels[0::4]) > .9
    assert (Path(folder) / 'bakes' / 'Cosmetic_reproj_diffuse.tga').is_file()

    assert bpy.ops.utility.reproject_diffuse(apply_result=True, show_preview=False,
                ray_extrusion=.02, max_ray_distance=.1) == {'FINISHED'}
    result = bpy.data.images['Cosmetic_reproj_diffuse.001']
    assert bpy.data.images.get(previous.name) == previous  # prior image stays valid
    assert target.material_slots[0].material != target_mat
    assert other.material_slots[0].material == target_mat
    assert snapshot(target_mat) == before_target
    assert snapshot(source_mat) == before_source
    for slot in target.material_slots:
        shader = next(n for n in slot.material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        node = shader.inputs['Base Color'].links[0].from_node
        assert node.type == 'TEX_IMAGE' and node.image == result
        assert len([n for n in slot.material.node_tree.nodes if n.type == 'TEX_IMAGE']) == 1

    # Failed rebakes preserve the applied result, source graph and all scene state.
    baseline = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials), len(bpy.data.images))
    before_apply = [snapshot(s.material) for s in target.material_slots]
    def failed_bake(**kwargs):
        raise RuntimeError('Intentional failure')
    with patch.object(reproject, 'bpy', bake_api(failed_bake)):
        try:
            status = bpy.ops.utility.reproject_diffuse(apply_result=True, show_preview=False)
            assert status == {'CANCELLED'}
        except RuntimeError as error:
            assert 'Intentional failure' in str(error)
    assert baseline == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials), len(bpy.data.images))
    assert before_apply == [snapshot(s.material) for s in target.material_slots]
    assert snapshot(source_mat) == before_source
    assert bpy.context.active_object == target
    assert set(bpy.context.selected_objects) == {source, target}
    assert bpy.context.scene.render.engine == original_engine
    assert bpy.context.scene.cycles.device == 'CPU'
    assert bpy.context.scene.cycles.samples == original_samples
    print('PASS: real multi-material reprojection, optional application, shared material isolation, '
          'object-linked slots, repeat bakes, projection controls and failure cleanup')
