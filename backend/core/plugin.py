from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type
import inspect


@dataclass
class PluginMetadata:
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    dependencies: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    enabled_by_default: bool = True


class PluginBase(ABC):
    metadata: PluginMetadata

    def __init__(self, registry: 'PluginRegistry', config: Dict[str, Any]):
        self.registry = registry
        self.config = config
        self._enabled = False

    @abstractmethod
    def on_load(self) -> None:
        """Called when plugin is loaded (before enable)."""

    @abstractmethod
    def on_enable(self) -> None:
        """Called when plugin is enabled. Register UI, timers, handlers here."""

    @abstractmethod
    def on_disable(self) -> None:
        """Called when plugin is disabled. Clean up resources."""

    @abstractmethod
    def on_unload(self) -> None:
        """Called when plugin is unloaded. Final cleanup."""

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _set_enabled(self, value: bool) -> None:
        self._enabled = value


def island_plugin(
    name: str,
    version: str = "1.0.0",
    description: str = "",
    author: str = "",
    dependencies: List[str] = None,
    config_schema: Dict[str, Any] = None,
    enabled_by_default: bool = True,
) -> Callable[[Type[PluginBase]], Type[PluginBase]]:
    """Decorator to register a plugin class."""

    def decorator(cls: Type[PluginBase]) -> Type[PluginBase]:
        if not issubclass(cls, PluginBase):
            raise TypeError(f"{cls.__name__} must inherit from PluginBase")

        cls.metadata = PluginMetadata(
            name=name,
            version=version,
            description=description,
            author=author,
            dependencies=dependencies or [],
            config_schema=config_schema or {},
            enabled_by_default=enabled_by_default,
        )

        # Store original init to wrap
        original_init = cls.__init__

        def wrapped_init(self, registry: 'PluginRegistry', config: Dict[str, Any]):
            original_init(self, registry, config)
            self._set_enabled(False)

        cls.__init__ = wrapped_init
        return cls

    return decorator


class PluginRegistry:
    def __init__(self, event_bus: 'EventBus', config: Dict[str, Any]):
        self.event_bus = event_bus
        self.config = config
        self._plugins: Dict[str, PluginBase] = {}
        self._plugin_classes: Dict[str, Type[PluginBase]] = {}
        self._load_order: List[str] = []

    def register(self, plugin_class: Type[PluginBase]) -> None:
        meta = getattr(plugin_class, 'metadata', None)
        if not meta:
            raise ValueError(f"{plugin_class.__name__} missing @island_plugin decorator")
        if meta.name in self._plugin_classes:
            raise ValueError(f"Plugin '{meta.name}' already registered")
        self._plugin_classes[meta.name] = plugin_class

    def load_all(self) -> None:
        # Topological sort by dependencies
        visited = set()
        temp = set()

        def visit(name: str):
            if name in temp:
                raise ValueError(f"Circular dependency involving '{name}'")
            if name in visited:
                return
            temp.add(name)
            meta = self._plugin_classes[name].metadata
            for dep in meta.dependencies:
                if dep not in self._plugin_classes:
                    raise ValueError(f"Plugin '{name}' depends on missing plugin '{dep}'")
                visit(dep)
            temp.remove(name)
            visited.add(name)
            self._load_order.append(name)

        for name in self._plugin_classes:
            visit(name)

        # Instantiate in load order
        for name in self._load_order:
            plugin_class = self._plugin_classes[name]
            meta = plugin_class.metadata
            plugin_config = self.config.get('plugins', {}).get(name, {})
            # Merge defaults from config_schema
            for key, default in meta.config_schema.items():
                plugin_config.setdefault(key, default)
            plugin = plugin_class(self, plugin_config)
            self._plugins[name] = plugin
            plugin.on_load()

    def enable_all(self) -> None:
        for name in self._load_order:
            self.enable(name)

    def enable(self, name: str) -> bool:
        plugin = self._plugins.get(name)
        if not plugin:
            return False
        if plugin.enabled:
            return True
        # Enable dependencies first
        for dep in plugin.metadata.dependencies:
            self.enable(dep)
        plugin.on_enable()
        plugin._set_enabled(True)
        return True

    def disable(self, name: str) -> bool:
        plugin = self._plugins.get(name)
        if not plugin or not plugin.enabled:
            return False
        # Disable dependents first
        for other_name, other_plugin in self._plugins.items():
            if other_plugin.enabled and name in other_plugin.metadata.dependencies:
                self.disable(other_name)
        plugin.on_disable()
        plugin._set_enabled(False)
        return True

    def unload_all(self) -> None:
        for name in reversed(self._load_order):
            plugin = self._plugins.get(name)
            if plugin:
                if plugin.enabled:
                    plugin.on_disable()
                plugin.on_unload()
        self._plugins.clear()
        self._load_order.clear()

    def get(self, name: str) -> Optional[PluginBase]:
        return self._plugins.get(name)

    def list_plugins(self) -> List[PluginMetadata]:
        return [p.metadata for p in self._plugins.values()]

    def reload_plugin(self, name: str) -> bool:
        """Hot-reload a single plugin."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False
        was_enabled = plugin.enabled
        if was_enabled:
            self.disable(name)
        plugin.on_unload()
        # Re-instantiate
        plugin_class = self._plugin_classes[name]
        meta = plugin_class.metadata
        plugin_config = self.config.get('plugins', {}).get(name, {})
        for key, default in meta.config_schema.items():
            plugin_config.setdefault(key, default)
        new_plugin = plugin_class(self, plugin_config)
        self._plugins[name] = new_plugin
        new_plugin.on_load()
        if was_enabled:
            self.enable(name)
        return True