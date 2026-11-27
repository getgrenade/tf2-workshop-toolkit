"""Distance-aware transfer and non-accumulating screen-space smoothing gradient."""
import bpy
from bpy.props import FloatProperty, IntProperty
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_gradient_active = False


def group_indices(obj):
    """Keep utility/mask groups separate when an armature defines deform groups."""
    rigs = [m.object for m in obj.modifiers if m.type == 'ARMATURE' and m.object]
    names = {b.name for rig in rigs for b in rig.data.bones if b.use_deform}
    return {g.index for g in obj.vertex_groups if not rigs or g.name in names}


def read_weights(obj, indices):
    return [{g.group: g.weight for g in v.groups if g.group in indices and g.weight > 0}
            for v in obj.data.vertices]


def constrain(weights, locked=None):
    locked_ids = set(locked or {})
    locked = {g: w for g, w in (locked or {}).items() if w > 0}
    total = sum(locked.values())
    if len(locked) > 3 or total > 1.000001:
        raise ValueError('Locked weights exceed three influences or a total of 1. Unlock groups first.')
    free = sorted(((g, w) for g, w in weights.items() if g not in locked_ids and w > 1e-8),
                  key=lambda pair: (-pair[1], pair[0]))[:3 - len(locked)]
    remaining = max(0.0, 1.0 - total)
    if remaining < 1e-7:
        return locked
    if not free:
        if locked:
            raise ValueError('Cannot normalize these vertices without changing locked groups. Unlock groups first.')
        return {}
    scale = remaining / sum(w for _, w in free)
    return locked | {g: w * scale for g, w in free}


def adjacency(mesh, world):
    coords = [world @ v.co for v in mesh.vertices]
    neighbors = [[] for _ in coords]
    for edge in mesh.edges:
        a, b = edge.vertices
        weight = 1.0 / max((coords[a] - coords[b]).length, 1e-8)
        neighbors[a].append((b, weight))
        neighbors[b].append((a, weight))
    return neighbors


def smooth_maps(original, neighbors, amounts, iterations):
    """Jacobi diffusion; zero-amount vertices remain fixed boundary conditions."""
    current = [dict(weights) for weights in original]
    for _ in range(iterations):
        result = [dict(weights) for weights in current]
        for i, amount in enumerate(amounts):
            if amount <= 0 or not neighbors[i]:
                continue
            valid = [(j, w) for j, w in neighbors[i] if current[j]]
            total = sum(w for _, w in valid)
            if not total:
                continue
            average = {}
            for j, w in valid:
                for group, value in current[j].items():
                    average[group] = average.get(group, 0.0) + value * w / total
            factor = 0.5 * amount
            result[i] = {g: current[i].get(g, 0) * (1 - factor) + average.get(g, 0) * factor
                         for g in current[i].keys() | average.keys()}
        current = result
    return current


def final_maps(obj, original, result, affected, indices):
    locked_ids = {g.index for g in obj.vertex_groups if g.lock_weight and g.index in indices}
    return {i: constrain(result[i], {g: original[i].get(g, 0) for g in locked_ids})
            for i in affected}


def write_maps(obj, maps, indices):
    for index, weights in maps.items():
        for group in indices:
            vg = obj.vertex_groups[group]
            if vg.lock_weight:
                continue
            if group in weights:
                vg.add([index], weights[group], 'REPLACE')
            else:
                vg.remove([index])
    obj.data.update()


def selection(obj, mode):
    masked = mode == 'EDIT' or (mode == 'WEIGHT_PAINT' and
                              (obj.data.use_paint_mask_vertex or obj.data.use_paint_mask))
    if not masked:
        return {v.index for v in obj.data.vertices if not v.hide}
    if mode == 'WEIGHT_PAINT' and obj.data.use_paint_mask and not obj.data.use_paint_mask_vertex:
        return {i for face in obj.data.polygons if face.select and not face.hide
                for i in face.vertices if not obj.data.vertices[i].hide}
    return {v.index for v in obj.data.vertices if v.select and not v.hide}


def mix(a, b, factor):
    return {g: a.get(g, 0) * (1 - factor) + b.get(g, 0) * factor for g in a.keys() | b.keys()}


def surface_transfer(source, targets, context):
    """Sample evaluated rest surface, barycentrically interpolating triangle weights."""
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = source.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        mesh.calc_loop_triangles()
        triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
        if not triangles:
            raise ValueError('Reference mesh has no faces to transfer from.')
        coords = [source.matrix_world @ v.co for v in mesh.vertices]
        tree = BVHTree.FromPolygons(coords, triangles, all_triangles=True)
        source_ids = group_indices(source)
        source_maps = [{g.group: g.weight for g in v.groups if g.group in source_ids and g.weight > 0}
                       for v in mesh.vertices]
        if not any(source_maps):
            raise ValueError('Reference mesh has no deform weights.')
        span = max(max(v[axis] for v in coords) - min(v[axis] for v in coords) for axis in range(3))
        samples = {}
        for target in targets:
            values, distances = [], []
            for vertex in target.data.vertices:
                position = target.matrix_world @ vertex.co
                point, _, triangle, distance = tree.find_nearest(position)
                a, b, c = (coords[i] for i in triangles[triangle])
                ab, ac, ap = b - a, c - a, point - a
                aa, bb, cc = ab.dot(ab), ab.dot(ac), ac.dot(ac)
                denominator = aa * cc - bb * bb
                if abs(denominator) < 1e-16:
                    bary = (1.0, 0.0, 0.0)
                else:
                    v = (cc * ap.dot(ab) - bb * ap.dot(ac)) / denominator
                    w = (aa * ap.dot(ac) - bb * ap.dot(ab)) / denominator
                    bary = (1 - v - w, v, w)
                weights = {}
                for index, fraction in zip(triangles[triangle], bary):
                    for group, weight in source_maps[index].items():
                        weights[group] = weights.get(group, 0.0) + weight * max(0, fraction)
                values.append(weights)
                distances.append(distance)
            samples[target] = (values, distances)
        return samples, max(span, 1e-8), source_ids
    finally:
        evaluated.to_mesh_clear()


class WEIGHT_OT_distance_transfer(bpy.types.Operator):
    """Experimental: precise surface weights near the reference, increasing topology smoothing farther away. Object Mode: active mesh is source. Edit Mode: active mesh is target; selected vertices only"""
    bl_idname = 'object.distance_weight_transfer'
    bl_label = 'Distance Transfer (Experimental)'
    bl_options = {'REGISTER', 'UNDO'}
    near_percent: FloatProperty(name='Keep Exact Within (%)', default=0.2, min=0, max=100,
                               description='Percentage of reference world-space size with no smoothing')
    far_percent: FloatProperty(name='Full Smoothing At (%)', default=6, min=0.001, max=100,
                              description='Percentage of reference world-space size where smoothing reaches full strength')
    strength: FloatProperty(name='Smoothing Strength', default=1, min=0, max=1)
    iterations: IntProperty(name='Iterations', default=5, min=1, max=50)

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'MESH' and context.mode in {'OBJECT', 'EDIT_MESH', 'PAINT_WEIGHT'}

    def invoke(self, context, event):
        self.iterations = context.scene.weight_smooth_iterations
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        active = context.object
        mode = active.mode
        selected = list(context.selected_objects)
        meshes = [o for o in selected if o.type == 'MESH']
        if mode == 'EDIT':
            source = next((o for o in meshes if o != active), None)
            targets = [active]
        else:
            source, targets = active, [o for o in meshes if o != active]
        if source is None or not targets:
            self.report({'ERROR'}, 'Select reference and scarf. In Object Mode make the reference active; in Edit Mode make the scarf active.')
            return {'CANCELLED'}
        if self.far_percent <= self.near_percent:
            self.report({'ERROR'}, 'Full Smoothing distance must be larger than Keep Exact distance.')
            return {'CANCELLED'}
        if any(t.data.users > 1 or not t.data.is_editable for t in targets):
            self.report({'ERROR'}, 'Targets must have editable, single-user mesh data. Make a single-user copy first.')
            return {'CANCELLED'}
        modifiers = [(m, m.show_viewport) for o in [source] + targets for m in o.modifiers if m.type == 'ARMATURE']
        originals, created_groups = {}, []
        try:
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            affected = {o: selection(o, mode) for o in targets}
            radius_amounts = {}
            if context.scene.weight_soft_radius:
                from .weight_radius import geometry, soft_region
                for target in targets:
                    coords, edges, _, visible, seeds = geometry(target, context, mode if target == active else 'OBJECT')
                    if not seeds:
                        raise ValueError(f'Select target vertices on {target.name} to define the Soft Radius core.')
                    _, radius_amounts[target], _ = soft_region(coords, edges, visible, seeds,
                                                               context.scene.weight_soft_distance)
                    affected[target] = {i for i, value in enumerate(radius_amounts[target]) if value > 0}
            if not all(affected.values()):
                raise ValueError('No target vertices selected; nothing was overwritten.')
            for modifier, _ in modifiers:
                modifier.show_viewport = False
            context.view_layer.update()
            samples, span, source_ids = surface_transfer(source, targets, context)
            plans = {}
            for target in targets:
                mapping = {}
                for index in source_ids:
                    name = source.vertex_groups[index].name
                    group = target.vertex_groups.get(name)
                    if group is None:
                        group = target.vertex_groups.new(name=name)
                        created_groups.append((target, group))
                    mapping[index] = group.index
                indices = group_indices(target) | set(mapping.values())
                original = read_weights(target, indices)
                originals[target] = (original, indices)
                values, distances = samples[target]
                initial = [dict(w) for w in original]
                for i in affected[target]:
                    transferred = {mapping[g]: w for g, w in values[i].items()}
                    if not transferred:
                        raise ValueError(f'Reference has no weights near vertex {i} of {target.name}.')
                    initial[i] = transferred
                near, far = span * self.near_percent / 100, span * self.far_percent / 100
                amounts = []
                for i, distance in enumerate(distances):
                    ramp = max(0, min(1, (distance - near) / (far - near)))
                    amounts.append(ramp * ramp * (3 - 2 * ramp) * self.strength if i in affected[target] else 0)
                result = smooth_maps(initial, adjacency(target.data, target.matrix_world), amounts, self.iterations)
                if target in radius_amounts:
                    result = [mix(original[i], value, radius_amounts[target][i])
                              for i, value in enumerate(result)]
                plans[target] = final_maps(target, original, result, affected[target], indices)
            for target, plan in plans.items():
                write_maps(target, plan, originals[target][1])
            self.report({'INFO'}, f'Distance transfer: {sum(map(len, affected.values()))} vertices. Exact within {near:.3g}; full smoothing at {far:.3g} world units. Normalized, max 3 deform weights.')
        except Exception as error:
            for target, (original, indices) in originals.items():
                write_maps(target, dict(enumerate(original)), indices)
            for target, group in reversed(created_groups):
                target.vertex_groups.remove(group)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            for modifier, state in modifiers:
                modifier.show_viewport = state
            context.view_layer.objects.active = active
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=mode)
            context.view_layer.update()
        return {'FINISHED'}


def gradient_amounts(points, start, end, strength, affected):
    direction = end - start
    length = direction.length_squared
    return [max(0, min(1, (point - start).dot(direction) / length)) * strength
            if point is not None and i in affected and length > 1 else 0
            for i, point in enumerate(points)]


class WEIGHT_OT_smooth_gradient(bpy.types.Operator):
    """Drag from no smoothing to full smoothing. Release to preview, scroll for strength, Enter to apply, Esc/right-click to cancel. Normalizes and limits to 3 deform weights; respects selection masks and locked groups"""
    bl_idname = 'object.weight_smooth_gradient'
    bl_label = 'Smooth Gradient'
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}
    strength: FloatProperty(name='Strength', default=0.5, min=0, max=1)

    @classmethod
    def poll(cls, context):
        return (context.area is not None and context.area.type == 'VIEW_3D' and
                context.object is not None and context.object.type == 'MESH' and
                context.mode in {'OBJECT', 'EDIT_MESH', 'PAINT_WEIGHT'})

    def invoke(self, context, event):
        self.obj = context.object
        self.mode = self.obj.mode
        self.area = context.area
        self.region = next((r for r in self.area.regions if r.type == 'WINDOW'), None)
        if (self.region is None or not self.obj.vertex_groups or self.obj.data.users > 1
                or not self.obj.data.is_editable):
            self.report({'ERROR'}, 'Use a single-user mesh with existing vertex weights in a 3D View.')
            return {'CANCELLED'}
        if self.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        self.indices = group_indices(self.obj)
        self.original = read_weights(self.obj, self.indices)
        self.affected = selection(self.obj, self.mode)
        if not self.affected or not any(self.original):
            self.report({'WARNING'}, 'No weighted vertices or no vertices selected.')
            if self.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=self.mode)
            return {'CANCELLED'}
        # Project the visible, posed surface when topology is unchanged.
        evaluated = self.obj.evaluated_get(context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            if len(mesh.vertices) != len(self.obj.data.vertices):
                self.report({'ERROR'}, 'Disable topology-changing modifiers before using Smooth Gradient.')
                if self.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode=self.mode)
                return {'CANCELLED'}
            self.points = [location_3d_to_region_2d(self.region, self.area.spaces.active.region_3d,
                           self.obj.matrix_world @ v.co) for v in mesh.vertices]
        finally:
            evaluated.to_mesh_clear()
        self.neighbors = adjacency(self.obj.data, self.obj.matrix_world)
        self.iterations = context.scene.weight_smooth_iterations
        self.start = self.end = None
        self.dragging = False
        if self.mode == 'WEIGHT_PAINT':
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        self.handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_line, (), 'WINDOW', 'POST_PIXEL')
        global _gradient_active
        _gradient_active = True
        context.window_manager.modal_handler_add(self)
        self.area.header_text_set('Smooth Gradient: drag 0 → full | wheel: strength | Enter: apply | Esc: cancel')
        return {'RUNNING_MODAL'}

    def preview(self):
        amounts = gradient_amounts(self.points, self.start, self.end, self.strength, self.affected)
        result = smooth_maps(self.original, self.neighbors, amounts, self.iterations)
        affected = {i for i in self.affected if amounts[i] > 0}
        plan = final_maps(self.obj, self.original, result, affected, self.indices)
        # Restore baseline first so moving the line never compounds smoothing.
        write_maps(self.obj, {i: self.original[i] for i in self.affected}, self.indices)
        write_maps(self.obj, plan, self.indices)

    def draw_line(self):
        if bpy.context.area != self.area or self.start is None:
            return
        import gpu
        import blf
        from gpu_extras.batch import batch_for_shader
        from math import cos, sin, tau
        cold, hot = (0.1, 0.75, 1, 1), (1, 0.45, 0.08, 1)
        direction = self.end - self.start
        length = direction.length
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')

        def lines(points, color):
            shader.bind()
            shader.uniform_float('color', color)
            batch_for_shader(shader, 'LINES', {'pos': points}).draw(shader)

        def label(point, text, color):
            blf.size(0, 14)
            width, height = blf.dimensions(0, text)
            x = max(8, min(self.region.width - width - 8, point.x))
            y = max(8, min(self.region.height - height - 8, point.y))
            # Dark backing keeps the labels readable on any paint color.
            shader.bind()
            shader.uniform_float('color', (0.015, 0.02, 0.025, 0.9))
            batch_for_shader(shader, 'TRIS', {'pos': [(x - 5, y - 5), (x + width + 5, y - 5),
                (x + width + 5, y + height + 5), (x - 5, y - 5),
                (x + width + 5, y + height + 5), (x - 5, y + height + 5)]}).draw(shader)
            blf.color(0, *color)
            blf.position(0, x, y, 0)
            blf.draw(0, text)

        gpu.state.blend_set('ALPHA')
        try:
            # A thick dark outline and a blue-to-orange ramp show direction.
            gpu.state.line_width_set(5)
            lines([self.start, self.end], (0.01, 0.01, 0.01, 1))
            gpu.state.line_width_set(3)
            ramp_shader = gpu.shader.from_builtin('SMOOTH_COLOR')
            ramp_shader.bind()
            batch_for_shader(ramp_shader, 'LINES', {'pos': [self.start, self.end],
                             'color': [cold, hot]}).draw(ramp_shader)
            if length > 1:
                unit = direction / length
                side = Vector((-unit.y, unit.x))
                tip = self.start + direction * 0.6
                lines([tip - unit * 15 + side * 8, tip,
                       tip, tip - unit * 15 - side * 8], hot)
                # Start = hollow circle; end = square with a cross.
                circle = [self.start + Vector((cos(i * tau / 32), sin(i * tau / 32))) * 9 for i in range(33)]
                lines([p for a, b in zip(circle, circle[1:]) for p in (a, b)], cold)
                square = [self.end + Vector(p) for p in ((-9, -9), (9, -9), (9, 9), (-9, 9), (-9, -9))]
                lines([p for a, b in zip(square, square[1:]) for p in (a, b)], hot)
                lines([self.end - Vector((5, 0)), self.end + Vector((5, 0)),
                       self.end - Vector((0, 5)), self.end + Vector((0, 5))], hot)
            label(self.start + Vector((12, 22)), 'START: NO SMOOTHING', cold)
            label(self.end + Vector((12, -30)), f'END: MAX {self.strength:.0%}', hot)
            label(Vector((20, 42)), 'Blue circle = unchanged   →   Orange square = strongest smoothing', (1, 1, 1, 1))
            label(Vector((20, 18)), 'Drag to redraw  |  Wheel: strength  |  Enter: apply  |  Esc: cancel', (1, 1, 1, 1))
        finally:
            gpu.state.line_width_set(1)
            gpu.state.blend_set('NONE')

    def finish(self, cancel=False):
        global _gradient_active
        try:
            if cancel:
                write_maps(self.obj, {i: self.original[i] for i in self.affected}, self.indices)
        finally:
            _gradient_active = False
            if self.handler is not None:
                bpy.types.SpaceView3D.draw_handler_remove(self.handler, 'WINDOW')
                self.handler = None
            self.area.header_text_set(None)
            if self.obj.mode != self.mode:
                bpy.ops.object.mode_set(mode=self.mode)
            self.area.tag_redraw()

    def modal(self, context, event):
        try:
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                self.finish(cancel=True)
                return {'CANCELLED'}
            point = Vector((event.mouse_x - self.region.x, event.mouse_y - self.region.y))
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                if not (0 <= point.x < self.region.width and 0 <= point.y < self.region.height):
                    return {'RUNNING_MODAL'}
                self.start, self.end = point.copy(), point.copy()
                self.dragging = True
            elif event.type == 'MOUSEMOVE' and self.dragging:
                self.end = point
            elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and self.dragging:
                self.end = point
                self.dragging = False
                self.preview()
            elif event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                self.strength = max(0, min(1, self.strength + (0.05 if event.type == 'WHEELUPMOUSE' else -0.05)))
                if self.start is not None and not self.dragging:
                    self.preview()
            elif event.type in {'RET', 'NUMPAD_ENTER'} and self.start is not None:
                if (self.end - self.start).length_squared <= 1:
                    return {'RUNNING_MODAL'}
                self.preview()
                self.finish()
                return {'FINISHED'}
            self.area.tag_redraw()
            return {'RUNNING_MODAL'}
        except Exception as error:
            self.finish(cancel=True)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

    def cancel(self, context):
        self.finish(cancel=True)


classes = (WEIGHT_OT_distance_transfer, WEIGHT_OT_smooth_gradient)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
