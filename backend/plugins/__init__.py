from pathlib import Path
from importlib import import_module
from typing import List
from backend.core.plugin import PluginBase, PluginRegistry


def discover_plugins(registry: PluginRegistry) -> List[str]:
    """Auto-discover and register all plugins in this directory."""
    plugin_dir = Path(__file__).parent
    loaded = []

    for py_file in plugin_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        module_name = f"backend.plugins.{py_file.stem}"
        try:
            module = import_module(module_name)
            # Find PluginBase subclasses in module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, PluginBase)
                    and attr is not PluginBase
                    and hasattr(attr, 'metadata')
                ):
                    registry.register(attr)
                    loaded.append(attr.metadata.name)
        except Exception as e:
            print(f"[plugins] Failed to load {module_name}: {e}")

    return loaded


__all__ = ['discover_plugins']