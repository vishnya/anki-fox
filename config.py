import json
import os
import stat
from pathlib import Path

CONFIG_DIR = Path.home() / ".anki-fox"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "session_active": False,
    "deck": "",
    "model": {
        "provider": "anthropic",
        "model_name": "claude-sonnet-4-6",
        "base_url": None,
    },
    "api_keys": {
        "anthropic": "",
        "openai": "",
        "groq": "",
        "gemini": "",
    },
    "custom_prompt": "",
    "deck_prompts": {},
    "skip_delete_confirm": False,
}


def load() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        config = _deep_copy(DEFAULT_CONFIG)
        env_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if env_key:
            config["api_keys"]["anthropic"] = env_key
        save(config)
        return config

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    # Forward-fill any missing top-level keys
    for k, v in DEFAULT_CONFIG.items():
        if k not in config:
            config[k] = _deep_copy(v)

    # Forward-fill nested dicts
    for k, v in DEFAULT_CONFIG.get("api_keys", {}).items():
        config["api_keys"].setdefault(k, v)
    for k, v in DEFAULT_CONFIG.get("model", {}).items():
        config["model"].setdefault(k, v)

    return config


def save(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)


def _deep_copy(d):
    return json.loads(json.dumps(d))
