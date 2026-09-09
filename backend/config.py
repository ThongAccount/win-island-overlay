# win-island-overlay config

from pathlib import Path

ROOT = Path(__file__).parent
VENVDIR = ROOT / ".venv"
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)