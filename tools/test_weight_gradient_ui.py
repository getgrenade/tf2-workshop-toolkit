"""GUI regression: launch with --factory-startup --enable-event-simulate.

Run load_dev_addon.py first. Pass an existing output directory after --.
Uses a separate disposable Blender window and quits it when done.
"""
import importlib
import json
from pathlib import Path
import sys
import traceback

import bpy

tools = importlib.import_module('tf2-workshop-toolkit.weight_experimental')
output = Path(sys.argv[sys.argv.index('--') + 1])
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
area.spaces.active.show_region_ui = False
region = next(r for r in area.regions if r.type == 'WINDOW')
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
data = bpy.data.meshes.new('Gradient test')
vertices = [(x - 3, y - 1, 0) for y in range(3) for x in range(7)]
faces = [(y * 7 + x, y * 7 + x + 1, (y + 1) * 7 + x + 1, (y + 1) * 7 + x)
         for y in range(2) for x in range(6)]
data.from_pydata(vertices, [], faces)
obj = bpy.data.objects.new('Gradient test', data)
bpy.context.scene.collection.objects.link(obj)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
for name in ('head', 'neck', 'chest', 'spine'):
    obj.vertex_groups.new(name=name)
for v in data.vertices:
    for group in obj.vertex_groups:
        value = 0.7 if group.index == v.index % 2 else 0.1
        group.add([v.index], value, 'REPLACE')
with bpy.context.temp_override(window=window, area=area, region=region):
    bpy.ops.view3d.view_axis(type='TOP')
    bpy.ops.view3d.view_all(center=True)
    bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
indices = tools.group_indices(obj)
original = tools.read_weights(obj, indices)
step = -1


def invoke():
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.object.weight_smooth_gradient('INVOKE_DEFAULT') == {'RUNNING_MODAL'}


def event(kind, value='PRESS', x=0.5):
    window.event_simulate(type=kind, value=value,
                          x=int(region.x + region.width * x),
                          y=int(region.y + region.height * 0.5))


def tick():
    global step
    try:
        if step == -1:
            event('ESC')  # Dismiss the startup splash before testing viewport input.
        elif step == 0:
            invoke()
        elif step in (1, 9):
            event('LEFTMOUSE', x=0.15)
        elif step in (2, 10):
            event('MOUSEMOVE', 'NOTHING', x=0.85)
        elif step in (3, 11):
            event('LEFTMOUSE', 'RELEASE', x=0.85)
        elif step in (4, 12):
            assert tools.read_weights(obj, indices) != original
            assert obj.mode == 'WEIGHT_PAINT'
            event('WHEELUPMOUSE', x=0.85)
        elif step == 5:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.screen.screenshot(filepath=str(output / 'gradient-preview.png'))
        elif step == 6:
            event('ESC')
        elif step == 7:
            assert tools.read_weights(obj, indices) == original
            assert obj.mode == 'WEIGHT_PAINT'
        elif step == 8:
            invoke()
        elif step == 13:
            event('RET')
        elif step == 14:
            result = tools.read_weights(obj, indices)
            assert result != original
            for before, after in zip(original, result):
                if after != before:
                    assert len(after) <= 3 and abs(sum(after.values()) - 1) < 1e-5
            assert obj.mode == 'WEIGHT_PAINT'
            assert not tools._gradient_active, 'Enter did not finish the gradient'
            bpy.context.scene.weight_soft_radius = True
            bpy.context.scene.weight_soft_distance = 1.5
            data.use_paint_mask_vertex = True
            for v in data.vertices:
                v.select = v.index == 10
            area.tag_redraw()
        elif step == 15:
            radius = importlib.import_module('tf2-workshop-toolkit.weight_radius')
            with bpy.context.temp_override(window=window, area=area, region=region):
                assert radius.enabled(bpy.context), 'Soft-radius overlay should be enabled'
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            text = radius._last_overlay.get(area.as_pointer(), '')
            assert '1 selected' in text and 'nearby' in text, text
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.screen.screenshot(filepath=str(output / 'soft-radius-preview.png'))
            bpy.context.scene.weight_soft_distance = 2.5
            area.tag_redraw()
        elif step == 16:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
                bpy.ops.screen.screenshot(filepath=str(output / 'soft-radius-larger.png'))
                assert bpy.ops.object.weight_smooth_limit_normalize() == {'FINISHED'}
            assert obj.mode == 'WEIGHT_PAINT'
            bpy.ops.object.mode_set(mode='OBJECT')
            rig_data = bpy.data.armatures.new('Visual cage rig')
            rig = bpy.data.objects.new('Visual cage rig', rig_data)
            bpy.context.scene.collection.objects.link(rig)
            bpy.ops.object.select_all(action='DESELECT')
            rig.select_set(True)
            bpy.context.view_layer.objects.active = rig
            bpy.ops.object.mode_set(mode='EDIT')
            for group in obj.vertex_groups:
                bone = rig_data.edit_bones.new(group.name)
                bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
            bpy.ops.object.mode_set(mode='OBJECT')
            for bone in rig.pose.bones:
                bone.location.x = 1
                bone.scale.x = 1.5
            modifier = obj.modifiers.new('On Cage preview', 'ARMATURE')
            modifier.object = rig
            modifier.show_in_editmode = modifier.show_on_cage = True
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.context.view_layer.update()
            bpy.ops.object.mode_set(mode='EDIT')
            area.tag_redraw()
        elif step == 17:
            radius = importlib.import_module('tf2-workshop-toolkit.weight_radius')
            display = radius.geometry(obj, bpy.context)
            assert abs(display[0][10].x - 1) < 1e-4
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
                bpy.ops.screen.screenshot(filepath=str(output / 'soft-radius-on-cage.png'))
            assert '1 selected' in radius._last_overlay[area.as_pointer()]
        elif step == 18:
            (output / 'result.json').write_text(json.dumps({'passed': True,
                'checks': 'actual modal invoke, drag, wheel, escape restoration, enter confirmation, '
                          'Weight Paint preview, normalized/max3, soft-radius overlay, adjustable distance, smooth, and posed On Cage Edit Mode overlay'}))
            bpy.ops.wm.quit_blender()
            return None
        step += 1
        return 0.4
    except Exception:
        (output / 'result.json').write_text(json.dumps({'passed': False, 'step': step,
                                                       'error': traceback.format_exc()}))
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=2.0)
