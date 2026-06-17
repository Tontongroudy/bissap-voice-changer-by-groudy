# audio_engine.py - Moteur audio : micro → effets → câble virtuel + monitoring séparé

import threading
import queue as _queue
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
    Architecture :
      input_cb  → _raw_q → [DSP THREAD] → _audio_q   → output_cb  → câble virtuel
                                         → _monitor_q → monitor_cb → haut-parleurs

    Le DSP tourne dans un thread séparé. Les callbacks audio ne font que copier
    vers/depuis des queues (< 0.1 ms), donc ils ne ratent jamais leur deadline.
    """

    def __init__(self):
        self.sample_rate  = 44100
        self.buffer_size  = 2048
        self.channels     = 1

        self.input_device   = None
        self.output_device  = None
        self.monitor_device = None

        self.input_volume  = 1.0
        self.output_volume = 1.0
        self.monitoring    = False

        self.effects_chain = None

        self._running        = False
        self._input_stream   = None
        self._output_stream  = None
        self._monitor_stream = None
        self._dsp_thread     = None

        self._in_level   = 0.0
        self._out_level  = 0.0
        self._level_lock = threading.Lock()

        self._last_out   = np.zeros(self.buffer_size, dtype=np.float32)
        self._last_lock  = threading.Lock()

    # ─────────────────────────────────────────────────────────────────
    # Démarrage / arrêt
    # ─────────────────────────────────────────────────────────────────

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
        for attr in ("_input_stream", "_output_stream", "_monitor_stream"):
            s = getattr(self, attr, None)
            if s:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        if self._dsp_thread and self._dsp_thread.is_alive():
            self._dsp_thread.join(timeout=1.0)
        self._dsp_thread = None
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

    # ─────────────────────────────────────────────────────────────────
    # Backend sounddevice — 3 streams + 1 thread DSP
    # ─────────────────────────────────────────────────────────────────

    def _start_sounddevice(self):
        sr  = self.sample_rate
        buf = self.buffer_size

        # raw_q  : micro brut   → thread DSP (maxsize élevé = tampon contre les pauses GIL)
        # audio_q : traité       → câble virtuel
        # monitor_q : traité     → haut-parleurs
        self._raw_q     = _queue.Queue(maxsize=8)
        self._audio_q   = _queue.Queue(maxsize=8)
        self._monitor_q = _queue.Queue(maxsize=8)

        def _push(q, data):
            """Pousse dans la queue ; remplace le plus vieux si pleine."""
            try:
                q.put_nowait(data)
            except _queue.Full:
                try:
                    q.get_nowait()
                except _queue.Empty:
                    pass
                try:
                    q.put_nowait(data)
                except _queue.Full:
                    pass

        # ── Callback INPUT : copie seule, aucun DSP ──────────────────
        def input_cb(indata, frames, time_info, status):
            _push(self._raw_q, indata[:, 0].astype(np.float32, copy=True))

        # ── Callback OUTPUT → câble virtuel ──────────────────────────
        def output_cb(outdata, frames, time_info, status):
            try:
                chunk = self._audio_q.get_nowait()
            except _queue.Empty:
                with self._last_lock:
                    chunk = self._last_out
            n = min(len(chunk), frames)
            outdata[:n, 0] = chunk[:n]
            if n < frames:
                outdata[n:] = 0

        # ── Callback MONITOR → haut-parleurs ─────────────────────────
        def monitor_cb(outdata, frames, time_info, status):
            if self.monitoring:
                try:
                    chunk = self._monitor_q.get_nowait()
                except _queue.Empty:
                    with self._last_lock:
                        chunk = self._last_out
                n = min(len(chunk), frames)
                outdata[:n, 0] = chunk[:n]
                if n < frames:
                    outdata[n:] = 0
            else:
                outdata.fill(0)

        # ── Thread DSP : traitement audio hors callback ───────────────
        def dsp_worker():
            while self._running:
                try:
                    raw = self._raw_q.get(timeout=0.05)
                except _queue.Empty:
                    continue

                audio = raw * self.input_volume

                rms_in = float(np.sqrt(np.mean(audio ** 2)))
                with self._level_lock:
                    self._in_level = rms_in

                if self.effects_chain:
                    try:
                        processed = self.effects_chain.process(audio, sr)
                    except Exception as e:
                        print(f"[DSP] Erreur effets : {e}")
                        processed = audio.copy()
                else:
                    processed = audio.copy()

                if not np.isfinite(processed).all():
                    processed = np.where(np.isfinite(processed), processed, 0.0)

                rms_out = float(np.sqrt(np.mean(processed ** 2)))
                with self._level_lock:
                    self._out_level = rms_out

                out = np.clip(processed * self.output_volume, -1.0, 1.0).astype(np.float32)

                with self._last_lock:
                    self._last_out = out

                _push(self._audio_q,   out)
                _push(self._monitor_q, out)

        self._dsp_thread = threading.Thread(
            target=dsp_worker, daemon=True, name="bissap-dsp"
        )
        self._running = True
        self._dsp_thread.start()

        try:
            self._input_stream = sd.InputStream(
                samplerate=sr, blocksize=buf, dtype="float32",
                channels=1, device=self.input_device,
                callback=input_cb, latency="low",
            )
            self._input_stream.start()

            self._output_stream = sd.OutputStream(
                samplerate=sr, blocksize=buf, dtype="float32",
                channels=1, device=self.output_device,
                callback=output_cb, latency="low",
            )
            self._output_stream.start()

            if self.monitor_device is not None or self.monitoring:
                self._monitor_stream = sd.OutputStream(
                    samplerate=sr, blocksize=buf, dtype="float32",
                    channels=1, device=self.monitor_device,
                    callback=monitor_cb, latency="low",
                )
                self._monitor_stream.start()

            print(f"[AudioEngine] démarré | in={self.input_device} "
                  f"out={self.output_device} monitor={self.monitor_device}")

        except Exception as e:
            print(f"[AudioEngine] Erreur sounddevice : {e}")
            self.stop()

    # ─────────────────────────────────────────────────────────────────
    # Restart monitor seul
    # ─────────────────────────────────────────────────────────────────

    def restart_monitor(self):
        if self._monitor_stream:
            try:
                self._monitor_stream.stop()
                self._monitor_stream.close()
            except Exception:
                pass
            self._monitor_stream = None
        if not SD_OK or not self._running:
            return
        sr  = self.sample_rate
        buf = self.buffer_size

        def monitor_cb(outdata, frames, time_info, status):
            if self.monitoring:
                try:
                    chunk = self._monitor_q.get_nowait()
                except _queue.Empty:
                    with self._last_lock:
                        chunk = self._last_out
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
            print(f"[AudioEngine] Erreur monitor : {e}")

    # ─────────────────────────────────────────────────────────────────
    # Backend PyAudio (fallback)
    # ─────────────────────────────────────────────────────────────────

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
                with self._last_lock:
                    self._last_out = processed.copy()
                return (processed.tobytes(), pyaudio.paContinue)

            self._pa_stream = self._pa.open(
                format=pyaudio.paFloat32, channels=1,
                rate=self.sample_rate, input=True, output=True,
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

    # ─────────────────────────────────────────────────────────────────
    # Utilitaires
    # ─────────────────────────────────────────────────────────────────

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
