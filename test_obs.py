"""Run: QT_QPA_PLATFORM=offscreen .venv/bin/python test_obs.py
Verifies the OBS plugin fixes: change-detector state init (no AttributeError on
every _on_obs_result) and that apply_obs_state fires only on real transitions.
"""
import backend.main as m  # noqa: F401 (validates app imports)
from backend.plugins.obs import OBSPlugin
from backend.core.plugin import PluginRegistry
from backend.core.events import EventBus


# Capture apply_obs_state calls on a minimal overlay stub.
class FakeWindow:
    def __init__(self):
        self.applied = []
        self._obs_state = 0
        self._obs_draw_state = 0
        self._obs_alpha = 0.0

    def apply_obs_state(self, new_state):
        self.applied.append(new_state)
        self._obs_state = new_state

    def update(self):
        pass


cfg = {'plugins': {'obs': {'show_notifications': True}}, '_window_ref': FakeWindow()}
registry = PluginRegistry(EventBus(), cfg)
registry.register(OBSPlugin)
plugin = registry._plugins.get('obs') or OBSPlugin(registry, cfg['plugins']['obs'])
window = FakeWindow()
plugin._window = window

# (a) no AttributeError: change-detector state now initialized in __init__
plugin._on_obs_result(2, True, False)
plugin._on_obs_result(2, True, False)  # same state -> early return, no re-apply

# (b) apply_obs_state invoked for the real (non-same-state) transition
assert plugin._obs_state == 2, plugin._obs_state
assert window.applied == [2], window.applied

# state change 2 -> 1 must apply again
plugin._on_obs_result(1, False, False)
assert window.applied == [2, 1], window.applied

# on_disable must not touch overlay-owned animation objects (no AttributeError)
plugin.on_disable()

print('ALL OBS TESTS PASS')