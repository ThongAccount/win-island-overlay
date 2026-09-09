from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Type, TypeVar
import threading


T = TypeVar('T')


@dataclass
class Event:
    """Base event class. Subclass with typed fields."""
    pass


class EventBus:
    def __init__(self):
        self._subscribers: Dict[Type[Event], List[Callable[[Event], None]]] = defaultdict(list)
        self._lock = threading.RLock()
        self._history: List[Event] = []
        self._max_history = 100

    def subscribe(self, event_type: Type[T], handler: Callable[[T], None]) -> Callable[[], None]:
        """Subscribe to an event type. Returns unsubscribe function."""
        with self._lock:
            self._subscribers[event_type].append(handler)

        def unsubscribe():
            with self._lock:
                if handler in self._subscribers[event_type]:
                    self._subscribers[event_type].remove(handler)

        return unsubscribe

    def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            handlers = self._subscribers[type(event)][:]

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"[EventBus] Error in handler for {type(event).__name__}: {e}")

    def publish_async(self, event: Event) -> None:
        """Publish event asynchronously (fire and forget)."""
        import threading
        threading.Thread(target=self.publish, args=(event,), daemon=True).start()

    def get_history(self, event_type: Type[T] = None) -> List[Event]:
        with self._lock:
            if event_type:
                return [e for e in self._history if isinstance(e, event_type)]
            return self._history[:]


# Core events
@dataclass
class PluginLoaded(Event):
    plugin_name: str


@dataclass
class PluginEnabled(Event):
    plugin_name: str


@dataclass
class PluginDisabled(Event):
    plugin_name: str


@dataclass
class ConfigChanged(Event):
    plugin_name: str
    key: str
    old_value: Any
    new_value: Any


@dataclass
class WindowStateChanged(Event):
    state: str  # 'collapsed', 'expanded', 'hover', 'hidden'


@dataclass
class ForegroundWindowChanged(Event):
    hwnd: int
    title: str
    class_name: str
    process_name: str


@dataclass
class MediaSessionChanged(Event):
    playing: bool
    title: str = ""
    artist: str = ""
    album_art: bytes = b""


@dataclass
class OBSStateChanged(Event):
    recording: bool
    streaming: bool


@dataclass
class NotificationReceived(Event):
    app_name: str
    title: str
    body: str
    icon_bytes: bytes = b""
    buttons: List[str] = None