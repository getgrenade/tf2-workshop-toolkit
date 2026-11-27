"""Diffuse, tangent normal and normal-alpha reprojection on disposable copies."""
import os

import bpy


def base_texture(material):
    if not material or not material.use_nodes or 'eye' in material.name.lower():
        return None
    return next((n for n in material.node_tree.nodes if n.type == 'TEX_IMAGE'
                 and n.image and n.label.lower().startswith('$basetexture')), None)


def upstream_image(socket):
    visited = set()
    queue = [link.from_node for link in socket.links]
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        if node.type == 'TEX_IMAGE' and node.image:
            return node
        queue.extend(link.from_node for input in node.inputs for link in input.links)
    return None


def normal_texture(material):
    if not material or not material.use_nodes or 'eye' in material.name.lower():
        return None
    nodes = material.node_tree.nodes
    for node in nodes:
        if node.type == 'NORMAL_MAP':
            texture = upstream_image(node.inputs['Color'])
            if texture:
                return texture
    return next((n for n in nodes if n.type == 'TEX_IMAGE' and n.image and
                 (n.label.lower().startswith(('$bumpmap', '$normalmap')) or
                  n.label == '_asset_normal_tex')), None)


def configure_normal(nodes, links, texture, normal, directx):
    normal.space = 'TANGENT'
    if hasattr(normal, 'convention'):
        normal.convention = 'DIRECTX' if directx else 'OPENGL'
        links.new(texture.outputs['Color'], normal.inputs['Color'])
    elif directx:
        flip = next((n for n in nodes if n.label == '_reproject_normal_flip_g'), None)
        if flip is None:
            flip = nodes.new('ShaderNodeVectorMath')
            flip.label = '_reproject_normal_flip_g'
            flip.operation = 'MULTIPLY_ADD'
            flip.inputs[1].default_value = (1, -1, 1)
            flip.inputs[2].default_value = (0, 1, 0)
        links.new(texture.outputs['Color'], flip.inputs[0])
        links.new(flip.outputs['Vector'], normal.inputs['Color'])
    else:
        links.new(texture.outputs['Color'], normal.inputs['Color'])


def apply_image(material, image, map_type='DIFFUSE', directx=True):
    """Update the selected texture channel without changing the other channels."""
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    shaders = [n for n in nodes if n.type == 'BSDF_PRINCIPLED']
    if not shaders:
        shader = nodes.new('ShaderNodeBsdfPrincipled')
        output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
        if output is None:
            output = nodes.new('ShaderNodeOutputMaterial')
        links.new(shader.outputs['BSDF'], output.inputs['Surface'])
        shaders = [shader]
    socket_name = {'DIFFUSE': 'Base Color', 'NORMAL': 'Normal', 'SPECULAR': 'Specular IOR Level'}[map_type]
    node = next((upstream_image(shader.inputs[socket_name]) for shader in shaders
                 if upstream_image(shader.inputs[socket_name]) is not None), None)
    if node is None:
        node = (base_texture(material) if map_type == 'DIFFUSE' else
                normal_texture(material) if map_type == 'NORMAL' else
                next((n for n in nodes if n.type == 'TEX_IMAGE' and n.label == 'Specular'), None))
    if node is not None and any(
            upstream_image(shader.inputs[other]) == node
            for shader in shaders for other in ('Base Color', 'Normal', 'Specular IOR Level')
            if other != socket_name):
        # A TF2 normal node often also supplies alpha to Specular. Updating one
        # channel must not swap the image used by the other channel.
        node = None
    if node is None:
        node = nodes.new('ShaderNodeTexImage')
        node.location = (shaders[0].location.x - 320, shaders[0].location.y)
    node.label = {'DIFFUSE': '$basetexture Reprojected Diffuse',
                  'NORMAL': '_asset_normal_tex', 'SPECULAR': 'Specular'}[map_type]
    node.image = image
    output = node.outputs['Color']
    if map_type == 'NORMAL':
        normal = next((link.from_node for shader in shaders for link in shader.inputs['Normal'].links
                       if link.from_node.type == 'NORMAL_MAP'), None)
        if normal is None:
            normal = nodes.new('ShaderNodeNormalMap')
            normal.label = '_reproject_normal_map'
            normal.location = (shaders[0].location.x - 160, shaders[0].location.y - 200)
        configure_normal(nodes, links, node, normal, directx)
        normal.inputs['Strength'].default_value = 1.0
        normal.uv_map = ''
        output = normal.outputs['Normal']
    for shader in shaders:
        links.new(output, shader.inputs[socket_name])
    nodes.active = node


def open_preview(context, image):
    """Duplicate an Image Editor into a window without changing the workspace."""
    if bpy.app.background or context.window is None:
        return False
    area = context.area or next(iter(context.window.screen.areas), None)
    if area is None:
        return False
    old_type, old_ui = area.type, area.ui_type
    try:
        area.type = 'IMAGE_EDITOR'
        area.spaces.active.image = image
        with context.temp_override(window=context.window, area=area):
            if bpy.ops.screen.area_dupli('INVOKE_DEFAULT') != {'FINISHED'}:
                return False
        # Fit the texture in the new editor after the new window is available.
        for window in context.window_manager.windows:
            if window == context.window:
                continue
            for editor in window.screen.areas:
                if editor.type == 'IMAGE_EDITOR' and editor.spaces.active.image == image:
                    region = next((r for r in editor.regions if r.type == 'WINDOW'), None)
                    if region:
                        with context.temp_override(window=window, area=editor, region=region):
                            bpy.ops.image.view_all(fit_view=True)
        return True
    finally:
        area.type = old_type
        area.ui_type = old_ui


def execute(operator, context):
    map_type = operator.map_type
    context.scene.reproject_map_type = map_type
    title = map_type.title()
    texture_for = base_texture if map_type == 'DIFFUSE' else normal_texture
    if context.mode != 'OBJECT':
        operator.report({'ERROR'}, 'Use Object Mode for texture reprojection.')
        return {'CANCELLED'}
    selected = list(context.selected_objects)
    meshes = [o for o in selected if o.type == 'MESH']
    target = context.active_object
    if not bpy.data.is_saved or target not in meshes:
        operator.report({'ERROR'}, 'Save the .blend and select the cosmetic as the active mesh.')
        return {'CANCELLED'}
    if operator.source_mesh:
        source = context.scene.objects.get(operator.source_mesh)
    else:
        candidates = [o for o in meshes if o != target]
        source = candidates[0] if len(candidates) == 1 else None
    if source is None or source.type != 'MESH' or source == target:
        operator.report({'ERROR'}, 'Choose a reference mesh in Source Mesh, different from the cosmetic.')
        return {'CANCELLED'}
    if not target.data.uv_layers:
        operator.report({'ERROR'}, 'Unwrap the cosmetic before reprojection; it needs a UV map.')
        return {'CANCELLED'}
    if operator.apply_result and (not target.is_editable or not target.data.is_editable or target.data.users > 1):
        operator.report({'ERROR'}, 'Applying the result needs editable, single-user cosmetic mesh data.')
        return {'CANCELLED'}
    if not any(texture_for(slot.material) for slot in source.material_slots):
        needed = '$basetexture' if map_type == 'DIFFUSE' else '$bumpmap / Normal Map'
        operator.report({'ERROR'}, f'No non-eye material with a loaded {needed} texture found on the reference.')
        return {'CANCELLED'}
    if map_type == 'SPECULAR' and not any(
            node and node.image.channels == 4
            for node in (normal_texture(slot.material) for slot in source.material_slots)):
        operator.report({'ERROR'}, 'The reference normal texture has no alpha channel to reproject as Specular.')
        return {'CANCELLED'}

    scene = context.scene
    engine, device, samples = scene.render.engine, scene.cycles.device, scene.cycles.samples
    temporary_objects, temporary_meshes, temporary_materials, temporary_images = [], [], [], []
    image = None
    success = False
    try:
        image = bpy.data.images.new(f'{target.name}_reproj_{map_type.lower()}', width=1024, height=1024, alpha=False)
        image.colorspace_settings.name = 'sRGB' if map_type == 'DIFFUSE' else 'Non-Color'
        data_images = {}

        def duplicate(obj, source_copy):
            copy = obj.copy()
            temporary_objects.append(copy)
            copy.data = obj.data.copy()
            temporary_meshes.append(copy.data)
            context.scene.collection.objects.link(copy)
            copy.hide_viewport = copy.hide_render = copy.hide_select = False
            copy.hide_set(False)
            # Object-linked slots also need independent materials.
            originals = [slot.material for slot in obj.material_slots] or [None]
            copy.data.materials.clear()
            for original in originals:
                material = original.copy() if original else bpy.data.materials.new('Reprojection Bake')
                temporary_materials.append(material)
                material.use_nodes = True
                copy.data.materials.append(material)
                slot = copy.material_slots[len(copy.data.materials) - 1]
                slot.link = 'DATA'
                slot.material = material
                nodes, links = material.node_tree.nodes, material.node_tree.links
                if source_copy:
                    texture = texture_for(material)
                    if texture and map_type != 'DIFFUSE':
                        original_image = texture.image
                        if original_image not in data_images:
                            data_image = original_image.copy()
                            temporary_images.append(data_image)
                            data_image.colorspace_settings.name = 'Non-Color'
                            data_image.alpha_mode = 'CHANNEL_PACKED'
                            data_images[original_image] = data_image
                        texture.image = data_images[original_image]
                    output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
                    if output is None:
                        output = nodes.new('ShaderNodeOutputMaterial')
                    output.target = 'ALL'
                    if map_type == 'NORMAL':
                        shader = nodes.new('ShaderNodeBsdfPrincipled')
                        if texture:
                            # Preserve an imported normal graph's green-channel convention.
                            normal = next((n for n in nodes if n.type == 'NORMAL_MAP'
                                           and upstream_image(n.inputs['Color']) == texture), None)
                            if normal is None:
                                normal = nodes.new('ShaderNodeNormalMap')
                                configure_normal(nodes, links, texture, normal, directx=True)
                            links.new(normal.outputs['Normal'], shader.inputs['Normal'])
                        links.new(shader.outputs['BSDF'], output.inputs['Surface'])
                    else:
                        emit = nodes.new('ShaderNodeEmission')
                        emit.inputs['Color'].default_value = (0, 0, 0, 1)
                        if texture:
                            channel = 'Alpha' if map_type == 'SPECULAR' else 'Color'
                            links.new(texture.outputs[channel], emit.inputs['Color'])
                        links.new(emit.outputs['Emission'], output.inputs['Surface'])
                else:
                    for node in nodes:
                        node.select = False
                    node = nodes.new('ShaderNodeTexImage')
                    node.image = image
                    node.select = True
                    nodes.active = node
            return copy

        bake_source = duplicate(source, True)
        bake_target = duplicate(target, False)
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = 1
        # Keep the user's CPU/GPU choice rather than requiring an available GPU.
        bpy.ops.object.select_all(action='DESELECT')
        bake_source.select_set(True)
        bake_target.select_set(True)
        context.view_layer.objects.active = bake_target
        outcome = bpy.ops.object.bake(
            type='NORMAL' if map_type == 'NORMAL' else 'EMIT',
            normal_space='TANGENT', normal_r='POS_X', normal_b='POS_Z',
            normal_g='NEG_Y' if scene.bake_props.swizzle_y == 'MINUS' else 'POS_Y',
            use_selected_to_active=True,
            use_cage=False, cage_object='', cage_extrusion=operator.ray_extrusion,
            max_ray_distance=operator.max_ray_distance,
            margin=scene.bake_props.bake_padding, margin_type='EXTEND', use_clear=True)
        if outcome != {'FINISHED'}:
            raise RuntimeError('Blender cancelled the bake.')
        directory = os.path.join(os.path.dirname(bpy.data.filepath), 'bakes')
        os.makedirs(directory, exist_ok=True)
        # Stable output path; keep previous image datablocks valid on repeated bakes.
        image.filepath_raw = os.path.join(directory, f'{target.name}_reproj_{map_type.lower()}.tga')
        image.file_format = 'TARGA'
        image.save()
        success = True
    except Exception as error:
        operator.report({'ERROR'}, f'Reprojection failed: {error}')
    finally:
        for obj in temporary_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in temporary_meshes:
            bpy.data.meshes.remove(mesh)
        for material in temporary_materials:
            bpy.data.materials.remove(material)
        for temporary_image in temporary_images:
            bpy.data.images.remove(temporary_image)
        scene.render.engine = engine
        scene.cycles.device, scene.cycles.samples = device, samples
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = target
        if not success and image is not None:
            bpy.data.images.remove(image)
    if not success:
        return {'CANCELLED'}

    if operator.apply_result:
        if not target.material_slots:
            target.data.materials.append(bpy.data.materials.new(f'{target.name}_material'))
        applied = {}
        for slot in target.material_slots:
            original = slot.material
            key = original.as_pointer() if original else None
            if key not in applied:
                # Leave the reference and other cosmetics sharing a material alone.
                material = original
                if material is None:
                    material = bpy.data.materials.new(f'{target.name}_material')
                elif material.users > 1 or material.library:
                    material = material.copy()
                apply_image(material, image, map_type, scene.bake_props.swizzle_y == 'MINUS')
                applied[key] = material
            slot.material = applied[key]
    if operator.show_preview:
        try:
            if not open_preview(context, image) and not bpy.app.background:
                operator.report({'WARNING'}, 'Baked successfully. Open the result in the Image Editor to preview it.')
        except Exception as error:
            operator.report({'WARNING'}, f'Baked successfully; could not open preview: {error}')
    operator.report({'INFO'}, f'{title} saved{", applied to cosmetic" if operator.apply_result else ""}: {image.filepath_raw}')
    return {'FINISHED'}
