# config_manager.py - Gestion de la configuration JSON

import json
import os
from pathlib import Path


class ConfigManager:
    """Gestion de la configuration persistante de l'application."""

    DEFAULT_CONFIG = {
        "window_geometry": "1300x850",
        "input_device_index": None,
        "output_device_index": None,
        "input_volume": 1.0,
        "output_volume": 1.0,
        "buffer_size": 1024,
        "sample_rate": 44100,
        "bypass_all": False,
        "monitoring": False,
        "soundboard_slots": [],
        "soundboard_exclusive": False,
        "last_profile": None,
    }

    def __init__(self, config_path: str = None):
        if config_path is None:
            base = Path.home() / ".voice_modifier"
            base.mkdir(exist_ok=True)
            config_path = base / "config.json"
        self.config_path = Path(config_path)
        self._data = dict(self.DEFAULT_CONFIG)
        self.load()

    # ------------------------------------------------------------------
    def load(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data.update(loaded)
            except Exception as e:
                print(f"[Config] Erreur de chargement : {e}")

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Erreur de sauvegarde : {e}")

    # ------------------------------------------------------------------
    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def update(self, d: dict):
        self._data.update(d)
        self.save()
