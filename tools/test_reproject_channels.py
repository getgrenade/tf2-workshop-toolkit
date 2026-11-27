"""Real CPU bakes checking normal tangent conversion and raw normal-alpha Specular."""
import importlib
from math import sqrt
from pathlib import Path
import tempfile

import bpy

reproject = importlib.import_module('tf2-workshop-toolkit.reproject')


def center(image):
    index = (512 * image.size[0] + 512) * 4
    return tuple(image.pixels[index:index + 3])


def near(actual, expected):
    assert all(abs(a - e) < .015 for a, e in zip(actual, expected)), (actual, expected)


with tempfile.TemporaryDirectory(prefix='tf2_reproject_channels_') as folder:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_plane_add(size=2)
    source = bpy.context.object
    source.name = 'Reference'
    mat = bpy.data.materials.new('Reference Material')
    mat.use_nodes = True
    source.data.materials.append(mat)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    tex = nodes.new('ShaderNodeTexImage')
    tex.label = '$bumpmap test'
    normal_image = bpy.data.images.new('Reference Normal + Mask', width=8, height=8, alpha=True)
    source_rgb = (.65, .7, (sqrt(.75) + 1) / 2)
    normal_image.generated_color = (*source_rgb, .25)
    normal_image.colorspace_settings.name = 'Non-Color'
    # Source importer can disable transparency; the alpha must still be extracted.
    normal_image.alpha_mode = 'NONE'
    tex.image = normal_image
    normal = nodes.new('ShaderNodeNormalMap')
    reproject.configure_normal(nodes, links, tex, normal, directx=True)
    shader = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    links.new(normal.outputs['Normal'], shader.inputs['Normal'])
    bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, .01))
    target = bpy.context.object
    target.name = 'Cosmetic'
    target_mat = bpy.data.materials.new('Cosmetic Material')
    target_mat.use_nodes = True
    target.data.materials.append(target_mat)
    target_shader = next(n for n in target_mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    target_shader.inputs['Base Color'].default_value = (.1, .2, .3, 1)
    source.select_set(True)
    bpy.context.scene.cycles.device = 'CPU'
    bpy.context.scene.bake_props.swizzle_y = 'MINUS'
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(folder) / 'channels.blend'))
    before = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))

    def bake(kind, apply=True):
        assert bpy.ops.utility.reproject_diffuse(map_type=kind, apply_result=apply,
            show_preview=False, ray_extrusion=.02, max_ray_distance=.1) == {'FINISHED'}

    # Same tangent basis: the original non-flat normal must survive.
    bake('NORMAL')
    first = bpy.data.images['Cosmetic_reproj_normal']
    near(center(first), source_rgb)
    assert first.colorspace_settings.name == 'Non-Color'
    applied_normal = target_shader.inputs['Normal'].links[0].from_node
    assert applied_normal.type == 'NORMAL_MAP' and applied_normal.convention == 'DIRECTX'
    assert reproject.upstream_image(applied_normal.inputs['Color']).image == first
    assert all(
        abs(a - b) < 1e-6 for a, b in zip(target_shader.inputs['Base Color'].default_value, (.1, .2, .3, 1)))

    # Rotate target UVs 90 degrees. Copying RGB would be wrong; rebaking must rotate XY.
    for uv in target.data.uv_layers.active.data:
        u, v = uv.uv
        uv.uv = (1 - v, u)
    bake('NORMAL')
    rotated = bpy.data.images['Cosmetic_reproj_normal.001']
    near(center(rotated), (.7, .35, source_rgb[2]))
    assert reproject.upstream_image(applied_normal.inputs['Color']).image == rotated
    assert len([n for n in target_mat.node_tree.nodes if n.type == 'NORMAL_MAP']) == 1

    # Specular is linear grayscale alpha, not RGB luminance or sRGB-encoded alpha.
    # Start with the common TF2 layout: one normal image drives Normal and Specular alpha.
    normal_tex = reproject.upstream_image(applied_normal.inputs['Color'])
    target_mat.node_tree.links.new(normal_tex.outputs['Alpha'], target_shader.inputs['Specular IOR Level'])
    bake('SPECULAR')
    specular = bpy.data.images['Cosmetic_reproj_specular']
    near(center(specular), (.25, .25, .25))
    assert specular.colorspace_settings.name == 'Non-Color'
    spec_node = target_shader.inputs['Specular IOR Level'].links[0].from_node
    assert spec_node.label == 'Specular' and spec_node.image == specular
    assert spec_node != normal_tex
    assert reproject.upstream_image(applied_normal.inputs['Color']).image == rotated
    assert (Path(folder) / 'bakes' / 'Cosmetic_reproj_specular.tga').is_file()
    loaded = bpy.data.images.load(specular.filepath_raw, check_existing=False)
    loaded.colorspace_settings.name = 'Non-Color'
    near(center(loaded), (.25, .25, .25))
    bpy.data.images.remove(loaded)

    # Output convention follows Bake Tools; source's convention stays DirectX.
    bpy.context.scene.bake_props.swizzle_y = 'PLUS'
    bake('NORMAL')
    opengl = bpy.data.images['Cosmetic_reproj_normal.002']
    near(center(opengl), (.7, .65, source_rgb[2]))
    assert applied_normal.convention == 'OPENGL'
    assert spec_node.image == specular
    assert normal.convention == 'DIRECTX'
    assert tex.image == normal_image and normal_image.alpha_mode == 'NONE'
    assert before == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    assert all('Reference Normal + Mask.' not in im.name for im in bpy.data.images)
    # A labelled $bumpmap with no imported Normal Map graph gets the TF2 DirectX fallback.
    nodes.remove(normal)
    bpy.context.scene.bake_props.swizzle_y = 'MINUS'
    bake('NORMAL', apply=False)
    near(center(bpy.data.images['Cosmetic_reproj_normal.003']), (.7, .35, source_rgb[2]))
    print('PASS: normal detail, rotated target tangents, DirectX/OpenGL, normal-alpha Specular, '
          'linear saved pixels, per-channel application, node reuse, source preservation and cleanup')
