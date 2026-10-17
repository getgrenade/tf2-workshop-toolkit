"""Run after load_dev_addon.py in a disposable Blender background session."""
import bpy


def mesh_object(name, coll, materials):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    for mat in materials:
        mesh.materials.append(mat)
    return obj


scene = bpy.context.scene
root = bpy.data.collections.new("scout")
scene.collection.children.link(root)
lod = bpy.data.collections.new("scout_morphs_low_lod0")
root.children.link(lod)
accessories = bpy.data.collections.new("Arbitrary nested accessories")
root.children.link(accessories)
hat = bpy.data.collections.new("scout_hat_lod0")
scene.collection.children.link(hat)
private = bpy.data.materials.new("scout_private")
private.use_fake_user = True
shared = bpy.data.materials.new("shared_with_hat")
shared_data_mat = bpy.data.materials.new("shared_mesh_material")
overridden = bpy.data.materials.new("overridden_mesh_material")
override = bpy.data.materials.new("object_override_material")
unrelated = bpy.data.materials.new("unrelated_orphan")
body = mesh_object("scout_body", lod, [private, shared])
body_data_name = body.data.name
mesh_object("hat", hat, [shared])
detail = mesh_object("detail", accessories, [overridden])
detail.material_slots[0].link = "OBJECT"
detail.material_slots[0].material = override
linked = mesh_object("linked_source", lod, [shared_data_mat])
survivor = bpy.data.objects.new("linked_survivor", linked.data)
hat.objects.link(survivor)
item = scene.tf2_assets.add()
item.old_name = "scout"
item.is_library = True
item.name = "scout"
assert bpy.ops.tf2.remove_asset(index=0, asset_name="scout") == {"FINISHED"}
assert not scene.tf2_assets
for name in ("scout_private", "overridden_mesh_material", "object_override_material"):
    assert bpy.data.materials.get(name) is None, name
for name in ("shared_with_hat", "shared_mesh_material", "unrelated_orphan"):
    assert bpy.data.materials.get(name) is not None, name
assert bpy.data.meshes.get(body_data_name) is None
assert bpy.data.objects.get("linked_survivor") is not None
assert len(survivor.data.materials) == 1
assert bpy.data.collections.get("scout_hat_lod0") is not None
assert bpy.data.collections.get("Arbitrary nested accessories") is None
print("PASS: BASE deletion removes orphan data and private materials, preserves "
      "shared materials/meshes, unrelated materials, and similarly named assets")
