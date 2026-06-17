# audio_engine.py - Moteur audio : micro → effets → câble virtuel + monitoring séparé

import threading
import numpy as np

try:
    import pyaudio
    PYAUDIO_OK = True
except ImportError:
    PYAUDIO_OK = False

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    SD_OK = False


class AudioEngine:
    """
    Flux audio :
      Micro réel → Effets → OUTPUT DEVICE  (câble virtuel → Discord/Teams/etc.)
                          → MONITOR DEVICE (haut-parleurs, optionnel)

    Pour que les autres entendent :
      1. Installer VB-Audio Virtual Cable
      2. Sélectionner "CABLE Input (VB-Audio)" comme Output Device dans l'app
      3. Activer monitoring si on veut s'entendre soi-même
      4. Dans Discord/Teams : sélectionner "CABLE Output (VB-Audio)" comme micro
    """

    def __init__(self):
        self.sample_rate = 44100
        self.buffer_size = 2048
        self.channels = 1

        self.input_device = None    # index du micro réel
        self.output_device = None   # index du câble virtuel (pour les autres)
        self.monitor_device = None  # index des haut-parleurs (pour soi-même)

        self.input_volume = 1.0
        self.output_volume = 1.0
        self.monitoring = False     # activer pour s'entendre via haut-parleurs

        self.effects_chain = None

        self._running = False
        self._input_stream = None
        self._output_stream = None
        self._monitor_stream = None

        self._in_level = 0.0
        self._out_level = 0.0
        self._level_lock = threading.Lock()

        # Buffer partagé entre les callbacks (input → output + monitor)
        self._processed = np.zeros(self.buffer_size, dtype=np.float32)
        self._proc_lock = threading.Lock()

    # ──────────────────────────────────────────────────────────────────
    # Démarrage / arrêt
    # ──────────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        if SD_OK:
            self._start_sounddevice()
        elif PYAUDIO_OK:
            self._start_pyaudio_duplex()
        else:
            print("[AudioEngine] Aucun backend audio disponible !")

    def stop(self):
        self._running = False
        for stream_attr in ("_input_stream", "_output_stream", "_monitor_stream"):
            s = getattr(self, stream_attr, None)
            if s:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
                setattr(self, stream_attr, None)
        # PyAudio
        if hasattr(self, "_pa") and self._pa:
            try:
                if hasattr(self, "_pa_stream") and self._pa_stream:
                    self._pa_stream.stop_stream()
                    self._pa_stream.close()
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def restart(self):
        self.stop()
        self.start()

    # ──────────────────────────────────────────────────────────────────
    # Backend sounddevice (3 streams séparés)
    # ──────────────────────────────────────────────────────────────────

    def _start_sounddevice(self):
        sr = self.sample_rate
        buf = self.buffer_size

        # Une queue par stream de sortie — chacun consomme son propre flux sans conflit.
        import queue as _queue
        self._audio_q   = _queue.Queue(maxsize=2)  # → câble virtuel
        self._monitor_q = _queue.Queue(maxsize=2)  # → haut-parleurs

        def _push(q, data):
            """Pousse dans la queue ; remplace le plus vieux chunk si pleine."""
            try:
                q.put_nowait(data)
            except _queue.Full:
                try: q.get_nowait()
                except _queue.Empty: pass
                try: q.put_nowait(data)
                except _queue.Full: pass

        def input_cb(indata, frames, time_info, status):
            audio = indata[:, 0].copy() * self.input_volume

            with self._level_lock:
                self._in_level = float(np.sqrt(np.mean(audio ** 2)))

            if self.effects_chain:
                try:
                    processed = self.effects_chain.process(audio, sr)
                except Exception as e:
                    print(f"[AudioEngine] Effects chain error: {e}")
                    processed = audio.copy()
            else:
                processed = audio.copy()

            # Remplace NaN/Inf (effet planté) par 0 pour ne pas tuer le stream
            if not np.isfinite(processed).all():
                processed = np.where(np.isfinite(processed), processed, 0.0)

            # OUT VU = niveau du signal traité, indépendant du volume de sortie
            with self._level_lock:
                self._out_level = float(np.sqrt(np.mean(processed ** 2)))

            processed = np.clip(processed * self.output_volume, -1.0, 1.0).astype(np.float32)

            chunk = processed.copy()
            _push(self._audio_q,   chunk)
            _push(self._monitor_q, chunk)

            with self._proc_lock:
                self._processed = chunk

        def _read_q(q, fallback, frames, outdata):
            """Lit depuis la queue ; fallback sur le buffer partagé si vide."""
            try:
                chunk = q.get_nowait()
            except _queue.Empty:
                with self._proc_lock:
                    chunk = fallback.copy()
            n = min(len(chunk), frames)
            outdata[:n, 0] = chunk[:n]
            if n < frames:
                outdata[n:] = 0

        def output_cb(outdata, frames, time_info, status):
            _read_q(self._audio_q, self._processed, frames, outdata)

        def monitor_cb(outdata, frames, time_info, status):
            if self.monitoring:
                _read_q(self._monitor_q, self._processed, frames, outdata)
            else:
                outdata.fill(0)

        try:
            self._input_stream = sd.InputStream(
                samplerate=sr, blocksize=buf, dtype="float32",
                channels=1, device=self.input_device,
                callback=input_cb,
                latency="low",
            )
            self._input_stream.start()

            self._output_stream = sd.OutputStream(
                samplerate=sr, blocksize=buf, dtype="float32",
                channels=1, device=self.output_device,
                callback=output_cb,
                latency="low",
            )
            self._output_stream.start()

            if self.monitor_device is not None:
                self._monitor_stream = sd.OutputStream(
                    samplerate=sr, blocksize=buf, dtype="float32",
                    channels=1, device=self.monitor_device,
                    callback=monitor_cb,
                    latency="low",
                )
                self._monitor_stream.start()
            elif self.monitoring:
                # Pas de monitor_device explicite → utiliser la sortie par défaut séparément
                self._monitor_stream = sd.OutputStream(
                    samplerate=sr, blocksize=buf, dtype="float32",
                    channels=1, device=None,  # défaut système
                    callback=monitor_cb,
                    latency="low",
                )
                self._monitor_stream.start()

            self._running = True
            print(f"[AudioEngine] sounddevice démarré | in={self.input_device} "
                  f"out(câble)={self.output_device} monitor={self.monitor_device}")

        except Exception as e:
            print(f"[AudioEngine] Erreur sounddevice : {e}")
            self.stop()

    def restart_monitor(self):
        """Redémarre uniquement le stream de monitoring (après changement de device)."""
        if self._monitor_stream:
            try:
                self._monitor_stream.stop()
                self._monitor_stream.close()
            except Exception:
                pass
            self._monitor_stream = None
        if not SD_OK or not self._running:
            return
        sr = self.sample_rate
        buf = self.buffer_size

        import queue as _queue

        def monitor_cb(outdata, frames, time_info, status):
            if self.monitoring:
                try:
                    chunk = self._monitor_q.get_nowait()
                except _queue.Empty:
                    with self._proc_lock:
                        chunk = self._processed.copy()
                n = min(len(chunk), frames)
                outdata[:n, 0] = chunk[:n]
                if n < frames:
                    outdata[n:] = 0
            else:
                outdata.fill(0)

        try:
            self._monitor_stream = sd.OutputStream(
                samplerate=sr, blocksize=buf, dtype="float32",
                channels=1, device=self.monitor_device,
                callback=monitor_cb, latency="high",
            )
            self._monitor_stream.start()
        except Exception as e:
            print(f"[AudioEngine] Erreur monitor stream : {e}")

    # ──────────────────────────────────────────────────────────────────
    # Backend PyAudio (duplex — fallback)
    # ──────────────────────────────────────────────────────────────────

    def _start_pyaudio_duplex(self):
        try:
            self._pa = pyaudio.PyAudio()

            def pa_cb(in_data, frame_count, time_info, status):
                audio = np.frombuffer(in_data, dtype=np.float32).copy() * self.input_volume
                with self._level_lock:
                    self._in_level = float(np.sqrt(np.mean(audio ** 2)))
                if self.effects_chain:
                    processed = self.effects_chain.process(audio, self.sample_rate)
                else:
                    processed = audio
                processed = np.clip(processed * self.output_volume, -1.0, 1.0).astype(np.float32)
                with self._level_lock:
                    self._out_level = float(np.sqrt(np.mean(processed ** 2)))
                with self._proc_lock:
                    self._processed = processed.copy()
                # Avec PyAudio duplex, la sortie va vers output_device
                return (processed.tobytes(), pyaudio.paContinue)

            self._pa_stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                input=True,
                output=True,
                frames_per_buffer=self.buffer_size,
                input_device_index=self.input_device,
                output_device_index=self.output_device,
                stream_callback=pa_cb,
            )
            self._pa_stream.start_stream()
            self._running = True
            print("[AudioEngine] PyAudio démarré (duplex).")
        except Exception as e:
            print(f"[AudioEngine] Erreur PyAudio : {e}")

    # ──────────────────────────────────────────────────────────────────
    # Utilitaires
    # ──────────────────────────────────────────────────────────────────

    @property
    def in_level(self) -> float:
        with self._level_lock:
            return self._in_level

    @property
    def out_level(self) -> float:
        with self._level_lock:
            return self._out_level

    def get_input_devices(self) -> list[dict]:
        return self._get_devices("input")

    def get_output_devices(self) -> list[dict]:
        return self._get_devices("output")

    def _get_devices(self, kind: str) -> list[dict]:
        devices = []
        if SD_OK:
            for i, dev in enumerate(sd.query_devices()):
                key = "max_input_channels" if kind == "input" else "max_output_channels"
                if dev[key] > 0:
                    devices.append({"index": i, "name": dev["name"]})
        elif PYAUDIO_OK and hasattr(self, "_pa") and self._pa:
            pa_key = "maxInputChannels" if kind == "input" else "maxOutputChannels"
            for i in range(self._pa.get_device_count()):
                info = self._pa.get_device_info_by_index(i)
                if info[pa_key] > 0:
                    devices.append({"index": i, "name": info["name"]})
        return devices
