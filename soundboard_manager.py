# soundboard_manager.py - Gestion du soundboard (lecture de sons)

import threading
import numpy as np
from pathlib import Path

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    SD_OK = False

try:
    import soundfile as sf
    SF_OK = True
except ImportError:
    SF_OK = False

try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    PYGAME_OK = True
except Exception:
    PYGAME_OK = False


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
    """Lecture audio multi-slot avec routage vers haut-parleurs et/ou micro virtuel."""

    NUM_SLOTS = 24

    def __init__(self):
        self.slots: list[SoundSlot] = [SoundSlot(i) for i in range(self.NUM_SLOTS)]
        self.exclusive_mode = False
        self._lock = threading.Lock()

        # Indices sounddevice mis à jour par App._apply_devices()
        self.speakers_device = None   # périphérique monitor (haut-parleurs)
        self.virtual_device  = None   # périphérique sortie (câble virtuel)

        # Streams actifs par slot (sounddevice OutputStream)
        self._streams: dict[int, object] = {}

    # ──────────────────────────────────────────────────────────────────

    def play(self, index: int, on_error=None):
        slot = self.slots[index]

        if not slot.file_path:
            if on_error:
                on_error("Aucun fichier — double-clique ✎ pour en choisir un")
            return

        if not Path(slot.file_path).exists():
            if on_error:
                on_error(f"Fichier introuvable :\n{slot.file_path}")
            return

        if self.exclusive_mode:
            self.stop_all()

        def _play():
            # ── Décodage ──────────────────────────────────────────────
            try:
                data, sr = self._decode(slot.file_path)
            except Exception as e:
                if on_error:
                    on_error(str(e))
                return

            if data is None:
                # pygame.mixer.music prend la main (MP3) — lecture déjà démarrée
                return

            # Volume + clip
            pcm = np.clip(data * slot.volume, -1.0, 1.0).astype(np.float32)
            if pcm.ndim == 1:
                pcm = pcm[:, np.newaxis]   # mono → (N, 1)

            # ── Lecture vers haut-parleurs ────────────────────────────
            if slot.play_to_speakers and SD_OK:
                try:
                    self._play_sd(index, pcm, sr, self.speakers_device)
                except Exception as e:
                    if on_error:
                        on_error(f"Haut-parleurs : {e}")

            # ── Lecture vers micro virtuel ────────────────────────────
            if slot.play_to_mic and SD_OK and self.virtual_device is not None:
                try:
                    # Deuxième flux indépendant vers le câble virtuel
                    sd.play(pcm, samplerate=sr, device=self.virtual_device)
                except Exception as e:
                    if on_error:
                        on_error(f"Micro virtuel : {e}")

        threading.Thread(target=_play, daemon=True).start()

    def _play_sd(self, index: int, data: np.ndarray, sr: int, device):
        """Ouvre un OutputStream dédié pour ce slot (permet plusieurs sons en parallèle)."""
        if not SD_OK:
            return

        # Arrêter un éventuel flux précédent sur ce slot
        self.stop(index)

        pos = [0]
        total = len(data)

        def _cb(outdata, frames, time_info, status):
            remaining = total - pos[0]
            n = min(frames, remaining)
            if n > 0:
                outdata[:n] = data[pos[0]:pos[0] + n]
                pos[0] += n
            if n < frames:
                outdata[n:] = 0
            if pos[0] >= total:
                raise sd.CallbackStop()

        stream = sd.OutputStream(
            samplerate=sr,
            channels=data.shape[1],
            dtype='float32',
            device=device,
            callback=_cb,
            finished_callback=lambda: self._on_stream_done(index),
        )
        with self._lock:
            self._streams[index] = stream
        stream.start()

    def _on_stream_done(self, index: int):
        with self._lock:
            self._streams.pop(index, None)

    # ── Décodage audio ────────────────────────────────────────────────

    def _decode(self, path: str):
        """Retourne (numpy float32 array, sample_rate) ou (None, None) si pygame.music."""
        ext = Path(path).suffix.lower()

        # 1. soundfile : WAV, OGG, FLAC, AIFF, etc.
        if SF_OK and ext != '.mp3':
            try:
                data, sr = sf.read(path, dtype='float32', always_2d=False)
                return data, sr
            except Exception:
                pass

        # 2. pygame.sndarray : WAV, OGG (donne le tableau numpy directement)
        if PYGAME_OK and ext != '.mp3':
            try:
                sound = pygame.mixer.Sound(path)
                arr = pygame.sndarray.samples(sound).astype(np.float32)
                # pygame retourne des int16 dans un float array → normaliser
                if arr.max() > 1.5:
                    arr = arr / 32768.0
                if arr.ndim > 1:
                    arr = arr.mean(axis=1)
                sr = pygame.mixer.get_init()[0]
                return arr, sr
            except Exception:
                pass

        # 3. MP3 via pygame.mixer.music (lecture directe, périphérique par défaut)
        if PYGAME_OK:
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(1.0)
                pygame.mixer.music.play()
                return None, None   # déjà en lecture
            except Exception as e:
                raise RuntimeError(f"Impossible de lire le MP3 : {e}")

        raise RuntimeError(
            "Aucun décodeur disponible.\n"
            "Installe : pip install soundfile sounddevice"
        )

    # ── Stop ──────────────────────────────────────────────────────────

    def stop(self, index: int):
        with self._lock:
            stream = self._streams.pop(index, None)
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def stop_all(self):
        with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for s in streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        if PYGAME_OK:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.stop()
            except Exception:
                pass

    def is_playing(self, index: int) -> bool:
        with self._lock:
            stream = self._streams.get(index)
        if stream:
            try:
                return stream.active
            except Exception:
                pass
        return False

    def add_slot(self):
        idx = len(self.slots)
        self.slots.append(SoundSlot(idx))
        return idx

    # ── Persistance ───────────────────────────────────────────────────

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
