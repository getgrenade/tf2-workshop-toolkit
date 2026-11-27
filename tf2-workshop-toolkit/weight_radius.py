"""Shared surface-distance soft selection for smoothing, transfers and assignment."""
import heapq
from math import inf

import bpy
from bpy.props import BoolProperty, FloatProperty
from . import weight_experimental as weights

_handlers = []
_last_overlay = {}


def displayed_coords(obj, context, base, mode):
    on_cage = any(m.show_viewport and m.show_in_editmode and m.show_on_cage
                  for m in obj.modifiers)
    if mode == 'EDIT' and not on_cage:
        return base
    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
    display = evaluated.to_mesh()
    try:
        if len(display.vertices) != len(base):
            raise ValueError('Disable topology-changing modifiers to preview/use Soft Radius.')
        return [obj.matrix_world @ v.co for v in display.vertices]
    finally:
        evaluated.to_mesh_clear()


def geometry(obj, context, selection_mode=None):
    mode = selection_mode or obj.mode
    if obj.mode == 'EDIT':
        import bmesh
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        coords = [obj.matrix_world @ v.co for v in bm.verts]
        coords = displayed_coords(obj, context, coords, mode)
        edges = [(e.verts[0].index, e.verts[1].index) for e in bm.edges]
        faces = [tuple(v.index for v in f.verts) for f in bm.faces if not f.hide]
        visible = {v.index for v in bm.verts if not v.hide}
        seeds = {v.index for v in bm.verts if v.select and not v.hide}
        return coords, edges, faces, visible, seeds
    mesh = obj.data
    coords = displayed_coords(obj, context, [obj.matrix_world @ v.co for v in mesh.vertices], mode)
    edges = [tuple(e.vertices) for e in mesh.edges]
    faces = [tuple(f.vertices) for f in mesh.polygons if not f.hide]
    visible = {v.index for v in mesh.vertices if not v.hide}
    if mode == 'WEIGHT_PAINT' and mesh.use_paint_mask and not mesh.use_paint_mask_vertex:
        seeds = {i for f in mesh.polygons if f.select and not f.hide for i in f.vertices} & visible
    else:
        seeds = {v.index for v in mesh.vertices if v.select} & visible
    return coords, edges, faces, visible, seeds


def soft_region(coords, edges, visible, seeds, radius):
    """Multi-source Dijkstra: distances follow connected, visible surface edges."""
    neighbors = [[] for _ in coords]
    for a, b in edges:
        if a not in visible or b not in visible:
            continue
        length = (coords[a] - coords[b]).length
        neighbors[a].append((b, length))
        neighbors[b].append((a, length))
    distances = [inf] * len(coords)
    queue = []
    for i in seeds:
        distances[i] = 0.0
        heapq.heappush(queue, (0.0, i))
    while queue:
        distance, i = heapq.heappop(queue)
        if distance != distances[i] or distance >= radius:
            continue
        for j, length in neighbors[i]:
            candidate = distance + length
            if candidate < distances[j]:
                distances[j] = candidate
                heapq.heappush(queue, (candidate, j))
    amounts = []
    for i, distance in enumerate(distances):
        factor = max(0.0, 1.0 - distance / max(radius, 1e-8)) if i in visible else 0.0
        amounts.append(factor * factor * (3.0 - 2.0 * factor))
    smoothing_neighbors = [[(j, 1.0 / max(length, 1e-8)) for j, length in row]
                           for row in neighbors]
    return distances, amounts, smoothing_neighbors


def cutoff_lines(coords, faces, distances, radius):
    result = []
    for face in faces:
        crossings = []
        for a, b in zip(face, face[1:] + face[:1]):
            da, db = distances[a], distances[b]
            if (da < radius) == (db < radius):
                continue
            if db < da:
                a, b, da, db = b, a, db, da
            length = (coords[b] - coords[a]).length
            # Along an edge leaving the affected region, measure the remaining
            # surface distance from the inside endpoint (even if db is infinity).
            factor = min(1, max(0, (radius - da) / max(length, 1e-8)))
            crossings.append(coords[a].lerp(coords[b], factor))
        for i in range(0, len(crossings) - 1, 2):
            result.extend(crossings[i:i + 2])
    return result


def execute_soft_smooth(operator, context):
    obj = context.object
    if obj.data.users > 1 or not obj.data.is_editable:
        operator.report({'ERROR'}, 'Soft Smooth needs editable, single-user mesh data.')
        return {'CANCELLED'}
    mode = obj.mode
    try:
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        coords, edges, faces, visible, seeds = geometry(obj, context, mode)
        if not seeds:
            operator.report({'WARNING'}, 'Select vertices to define the full-strength area for Soft Radius.')
            return {'CANCELLED'}
        radius = context.scene.weight_soft_distance
        distances, amounts, neighbors = soft_region(coords, edges, visible, seeds, radius)
        indices = weights.group_indices(obj)
        original = weights.read_weights(obj, indices)
        affected = {i for i, amount in enumerate(amounts) if amount > 0}
        result = weights.smooth_maps(original, neighbors, amounts, context.scene.weight_smooth_iterations)
        plan = weights.final_maps(obj, original, result, affected, indices)
        try:
            weights.write_maps(obj, plan, indices)
        except Exception:
            weights.write_maps(obj, {i: original[i] for i in affected}, indices)
            raise
        operator.report({'INFO'}, f'Soft Smooth: {len(seeds)} selected + {len(affected - seeds)} nearby vertices; '
                        f'radius {radius:g} world units. Normalized, max 3 deform weights.')
        return {'FINISHED'}
    except Exception as error:
        operator.report({'ERROR'}, str(error))
        return {'CANCELLED'}
    finally:
        if obj.mode != mode:
            bpy.ops.object.mode_set(mode=mode)
        context.view_layer.update()


def execute_soft_transfer(operator, context):
    """Native Data Transfer sampling on disposable copies, then radius blending."""
    active = context.object
    selected = list(context.selected_objects)
    meshes = [o for o in selected if o.type == 'MESH']
    mode = active.mode if active else 'OBJECT'
    if active is None or active.type != 'MESH' or len(meshes) < 2:
        operator.report({'ERROR'}, 'Select a reference mesh and at least one target mesh.')
        return {'CANCELLED'}
    source = next((o for o in meshes if o != active), None) if mode == 'EDIT' else active
    targets = [active] if mode == 'EDIT' else [o for o in meshes if o != source]
    if any(t.data.users > 1 or not t.data.is_editable for t in targets):
        operator.report({'ERROR'}, 'Soft Transfer needs editable, single-user target mesh data.')
        return {'CANCELLED'}
    modifiers = [(m, m.show_viewport) for o in [source] + targets for m in o.modifiers if m.type == 'ARMATURE']
    originals, added_groups = {}, []
    temporary = None
    temporary_data = None
    try:
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        masks = {}
        for target in targets:
            coords, edges, _, visible, seeds = geometry(target, context, mode if target == active else 'OBJECT')
            if not seeds:
                raise ValueError(f'Select target vertices on {target.name} to define the full-strength transfer area.')
            _, amounts, _ = soft_region(coords, edges, visible, seeds, context.scene.weight_soft_distance)
            masks[target] = amounts
        for modifier, _ in modifiers:
            modifier.show_viewport = False
        context.view_layer.update()
        source_names = {source.vertex_groups[i].name for i in weights.group_indices(source)}
        if not source_names:
            raise ValueError('The reference mesh has no deform weight groups.')
        plans = {}
        for target in targets:
            temporary = target.copy()
            temporary.data = target.data.copy()
            temporary_data = temporary.data
            temporary.modifiers.clear()
            temporary.hide_viewport = temporary.hide_select = False
            context.scene.collection.objects.link(temporary)
            temporary.hide_set(False)
            bpy.ops.object.select_all(action='DESELECT')
            temporary.select_set(True)
            context.view_layer.objects.active = temporary
            modifier = temporary.modifiers.new('Soft Transfer Sample', 'DATA_TRANSFER')
            modifier.object = source
            modifier.use_vert_data = True
            modifier.data_types_verts = {'VGROUP_WEIGHTS'}
            # Keep native Transfer's mapping/defaults; evaluate rather than apply
            # so shape-key meshes are supported without changing their geometry.
            bpy.ops.object.datalayout_transfer(modifier=modifier.name)
            context.view_layer.update()
            evaluated = temporary.evaluated_get(context.evaluated_depsgraph_get())
            sampled = evaluated.to_mesh(preserve_all_data_layers=True,
                                        depsgraph=context.evaluated_depsgraph_get())
            try:
                mapping = {}
                for name in sorted(source_names):
                    group = target.vertex_groups.get(name)
                    if group is None:
                        group = target.vertex_groups.new(name=name)
                        added_groups.append((target, group))
                    sampled_group = temporary.vertex_groups.get(name)
                    if sampled_group:
                        mapping[sampled_group.index] = group.index
                indices = weights.group_indices(target) | set(mapping.values())
                original = weights.read_weights(target, indices)
                originals[target] = (original, indices)
                affected = {i for i, amount in enumerate(masks[target]) if amount > 0}
                result = [dict(w) for w in original]
                for i in affected:
                    transferred = {mapping[g.group]: g.weight for g in sampled.vertices[i].groups
                                   if g.group in mapping and g.weight > 0}
                    if not transferred:
                        raise ValueError(f'Reference has no weights near vertex {i} on {target.name}.')
                    transferred = weights.constrain(transferred)
                    result[i] = weights.mix(original[i], transferred, masks[target][i])
                plans[target] = weights.final_maps(target, original, result, affected, indices)
            finally:
                evaluated.to_mesh_clear()
            bpy.data.objects.remove(temporary, do_unlink=True)
            temporary = None
            bpy.data.meshes.remove(temporary_data)
            temporary_data = None
        for target, plan in plans.items():
            weights.write_maps(target, plan, originals[target][1])
        operator.report({'INFO'}, f'Soft Transfer: {sum(map(len, plans.values()))} vertices across {len(targets)} targets; '
                        f'radius {context.scene.weight_soft_distance:g}. Normalized, max 3 deform weights.')
        return {'FINISHED'}
    except Exception as error:
        for target, (original, indices) in originals.items():
            weights.write_maps(target, dict(enumerate(original)), indices)
        for target, group in reversed(added_groups):
            target.vertex_groups.remove(group)
        operator.report({'ERROR'}, str(error))
        return {'CANCELLED'}
    finally:
        if temporary is not None:
            bpy.data.objects.remove(temporary, do_unlink=True)
        if temporary_data is not None:
            bpy.data.meshes.remove(temporary_data)
        for modifier, state in modifiers:
            modifier.show_viewport = state
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=mode)
        context.view_layer.update()


def enabled(context):
    obj = context.object
    return (not weights._gradient_active and getattr(context.scene, 'weight_soft_radius', False) and obj is not None
            and obj.type == 'MESH' and obj.mode in {'OBJECT', 'EDIT', 'WEIGHT_PAINT'})


def draw_region():
    context = bpy.context
    if not enabled(context):
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    key = context.area.as_pointer()
    try:
        coords, edges, faces, visible, seeds = geometry(context.object, context)
        radius = context.scene.weight_soft_distance
        distances, amounts, _ = soft_region(coords, edges, visible, seeds, radius)
        indices = [i for i, value in enumerate(amounts) if value > 0]
        _last_overlay[key] = f'SOFT RADIUS: {radius:g} world units | {len(seeds)} selected + {len(set(indices) - seeds)} nearby'
        if not seeds:
            _last_overlay[key] = 'SOFT RADIUS: select vertices to define the full-strength area'
            return
        colors = [(0.05, 0.8, 1.0, 0.95) if i in seeds else
                  (1.0, 0.25 + 0.6 * (1 - amounts[i]), 0.05, 0.85) for i in indices]
        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.point_size_set(8)
        try:
            shader.bind()
            batch_for_shader(shader, 'POINTS', {'pos': [coords[i] for i in indices], 'color': colors}).draw(shader)
            boundary = cutoff_lines(coords, faces, distances, radius)
            if boundary:
                outline = gpu.shader.from_builtin('UNIFORM_COLOR')
                outline.bind()
                outline.uniform_float('color', (1, 0.9, 0.15, 1))
                gpu.state.line_width_set(2)
                batch_for_shader(outline, 'LINES', {'pos': boundary}).draw(outline)
        finally:
            gpu.state.point_size_set(1)
            gpu.state.line_width_set(1)
            gpu.state.depth_test_set('NONE')
            gpu.state.blend_set('NONE')
    except Exception as error:
        _last_overlay[key] = 'Soft Radius: ' + str(error)


def draw_legend():
    context = bpy.context
    if not enabled(context):
        return
    import blf
    text = _last_overlay.get(context.area.as_pointer(), 'Soft Radius preview')
    left = max(20, next((r.width + 12 for r in context.area.regions if r.type == 'TOOLS'), 20))
    blf.size(0, 13)
    blf.color(0, 1, 1, 1, 1)
    blf.enable(0, blf.SHADOW)
    blf.shadow(0, 5, 0, 0, 0, 1)
    blf.position(0, left, 66, 0)
    blf.draw(0, text)
    blf.position(0, left, 46, 0)
    blf.draw(0, 'Blue = selected/full | Orange → yellow = falloff | Yellow outline = zero-effect cutoff')
    blf.disable(0, blf.SHADOW)


def redraw(self, context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def register():
    bpy.types.Scene.weight_soft_radius = BoolProperty(
        name='Soft Radius', default=False, update=redraw,
        description='Use a shared selection falloff for Assign Selected, Smooth, Transfer and Distance Transfer. Selected vertices get full effect; connected nearby vertices fade to zero at Radius')
    bpy.types.Scene.weight_soft_distance = FloatProperty(
        name='Radius', default=4.0, min=0.001, soft_max=20.0, subtype='DISTANCE', unit='LENGTH', update=redraw,
        description='Surface distance from selected target vertices. Full effect at the selection, fading to zero at this distance; follows On Cage deformation in Edit Mode')
    _handlers.append(bpy.types.SpaceView3D.draw_handler_add(draw_region, (), 'WINDOW', 'POST_VIEW'))
    _handlers.append(bpy.types.SpaceView3D.draw_handler_add(draw_legend, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    for handler in _handlers:
        bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
    _handlers.clear()
    _last_overlay.clear()
    del bpy.types.Scene.weight_soft_radius
    del bpy.types.Scene.weight_soft_distance
