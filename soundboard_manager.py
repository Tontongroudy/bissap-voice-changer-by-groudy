# soundboard_manager.py - Gestion du soundboard (lecture de sons)

import threading
import numpy as np
from pathlib import Path

try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    PYGAME_OK = True
except Exception:
    PYGAME_OK = False

try:
    import soundfile as sf
    SF_OK = True
except ImportError:
    SF_OK = False


class SoundSlot:
    """Un slot du soundboard."""

    def __init__(self, index: int):
        self.index = index
        self.name = f"Slot {index + 1}"
        self.file_path: str = ""
        self.shortcut: str = ""
        self.volume: float = 1.0
        self.color: str = "#1f6aa5"
        self.play_to_speakers: bool = True
        self.play_to_mic: bool = False

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "file_path": self.file_path,
            "shortcut": self.shortcut,
            "volume": self.volume,
            "color": self.color,
            "play_to_speakers": self.play_to_speakers,
            "play_to_mic": self.play_to_mic,
        }

    def from_dict(self, d: dict):
        self.name = d.get("name", self.name)
        self.file_path = d.get("file_path", "")
        self.shortcut = d.get("shortcut", "")
        self.volume = d.get("volume", 1.0)
        self.color = d.get("color", "#1f6aa5")
        self.play_to_speakers = d.get("play_to_speakers", True)
        self.play_to_mic = d.get("play_to_mic", False)


class SoundboardManager:
    """Gestion des slots, lecture audio, mode exclusif / overlap."""

    NUM_SLOTS = 24

    def __init__(self):
        self.slots: list[SoundSlot] = [SoundSlot(i) for i in range(self.NUM_SLOTS)]
        self.exclusive_mode = False
        self._active_channels: dict[int, object] = {}  # index -> pygame.Channel
        self._lock = threading.Lock()
        self._progress_callbacks: dict[int, callable] = {}

    # ──────────────────────────────────────────────────────────────────

    def play(self, index: int):
        slot = self.slots[index]
        if not slot.file_path:
            return
        if not PYGAME_OK:
            print("[Soundboard] pygame non disponible.")
            return

        if self.exclusive_mode:
            self.stop_all()

        def _play():
            try:
                sound = pygame.mixer.Sound(slot.file_path)
                sound.set_volume(slot.volume)
                ch = sound.play()
                if ch:
                    with self._lock:
                        self._active_channels[index] = ch
            except Exception as e:
                print(f"[Soundboard] Erreur lecture slot {index}: {e}")

        threading.Thread(target=_play, daemon=True).start()

    def stop(self, index: int):
        with self._lock:
            ch = self._active_channels.pop(index, None)
        if ch:
            try:
                ch.stop()
            except Exception:
                pass

    def stop_all(self):
        if PYGAME_OK:
            pygame.mixer.stop()
        with self._lock:
            self._active_channels.clear()

    def is_playing(self, index: int) -> bool:
        with self._lock:
            ch = self._active_channels.get(index)
        if ch is None:
            return False
        try:
            return ch.get_busy()
        except Exception:
            return False

    def get_progress(self, index: int) -> float:
        """Retourne une progression estimée 0.0–1.0 (approximation)."""
        slot = self.slots[index]
        if not self.is_playing(index) or not slot.file_path:
            return 0.0
        return 0.5  # Approximation sans accès direct à la position pygame

    def add_slot(self):
        idx = len(self.slots)
        self.slots.append(SoundSlot(idx))
        return idx

    # ──────────────────────────────────────────────────────────────────
    # Persistance
    # ──────────────────────────────────────────────────────────────────

    def to_dict(self) -> list:
        return [s.to_dict() for s in self.slots]

    def from_dict(self, data: list):
        for i, slot_data in enumerate(data):
            if i < len(self.slots):
                self.slots[i].from_dict(slot_data)
            else:
                new_slot = SoundSlot(i)
                new_slot.from_dict(slot_data)
                self.slots.append(new_slot)
