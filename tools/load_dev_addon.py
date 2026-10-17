"""Load the repository copy into a fresh Blender session without installation."""

import importlib
from pathlib import Path
import sys

import addon_utils
import bpy


def main():
    if bpy.app.version[:2] != (5, 2):
        raise RuntimeError("This development launcher requires Blender 5.2.")

    root = Path(__file__).resolve().parents[1]
    module_name = "tf2-workshop-toolkit"
    # Startup may already have enabled an installed release. Unregister it
    # before importing the working copy; never save these preference changes.
    addon_utils.disable(module_name, default_set=False)
    for name in list(sys.modules):
        if name == module_name or name.startswith(module_name + "."):
            del sys.modules[name]
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    module = addon_utils.enable(module_name, default_set=False)
    if module is None:
        raise RuntimeError("Workshop Toolkit development copy failed to load.")
    expected = root / module_name / "__init__.py"
    if Path(module.__file__).resolve() != expected:
        raise RuntimeError(f"Loaded the wrong add-on copy: {module.__file__}")
    print(f"Workshop Toolkit DEV: loaded {module.__file__}")
    # Make the panel easy to find when the saved workspace has a 3D viewport.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.show_region_ui = True


if __name__ == "__main__":
    main()
