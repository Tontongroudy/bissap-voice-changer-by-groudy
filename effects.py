# effects.py - Tous les effets DSP audio et la chaîne d'effets

import numpy as np
from scipy import signal
from scipy.fft import rfft, irfft
import threading


# ──────────────────────────────────────────────────────────────────────────────
# Classe de base
# ──────────────────────────────────────────────────────────────────────────────

class BaseEffect:
    """Classe de base pour tous les effets audio."""

    def __init__(self, name: str, enabled: bool = False):
        self.name = name
        self.enabled = enabled
        self.params: dict = {}
        self._lock = threading.Lock()

    def process(self, audio: np.ndarray, sr: int) -> np.ndarray:
        if not self.enabled or len(audio) == 0:
            return audio
        try:
            with self._lock:
                return self._process(audio, sr)
        except Exception as e:
            print(f"[Effect:{self.name}] Erreur : {e}")
            return audio

    def _process(self, audio: np.ndarray, sr: int) -> np.ndarray:
        return audio

    def reset(self):
        pass

    def to_dict(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "params": dict(self.params)}

    def from_dict(self, d: dict):
        self.enabled = d.get("enabled", False)
        for k, v in d.get("params", {}).items():
            if k in self.params:
                self.params[k] = v


# ──────────────────────────────────────────────────────────────────────────────
# EFFETS DE PITCH & TONALITÉ
# ──────────────────────────────────────────────────────────────────────────────

class PitchShifter(BaseEffect):
    """Pitch shifting via resample_poly + crossfade inter-blocs."""

    _XFADE = 64

    def __init__(self):
        super().__init__("Pitch Shifter")
        self.params = {"semitones": 0.0}
        self._prev_tail   = None
        self._up = self._down = None
        self._last_steps  = None

    def reset(self):
        self._prev_tail  = None
        self._up = self._down = None
        self._last_steps = None

    def _process(self, audio, sr):
        from fractions import Fraction
        n_steps = self.params["semitones"]
        if abs(n_steps) < 0.01:
            return audio
        factor = 2.0 ** (n_steps / 12.0)
        n = len(audio)

        if self._last_steps != round(n_steps, 3):
            frac = Fraction(factor).limit_denominator(100)
            self._up, self._down = frac.numerator, frac.denominator
            self._last_steps = round(n_steps, 3)

        resampled = signal.resample_poly(audio, self._up, self._down)
        if len(resampled) >= n:
            output = resampled[:n].astype(np.float32)
        else:
            output = np.zeros(n, dtype=np.float32)
            output[:len(resampled)] = resampled

        xf = self._XFADE
        if self._prev_tail is not None and len(self._prev_tail) == xf:
            fade_in = np.linspace(0.0, 1.0, xf, dtype=np.float32)
            output[:xf] = output[:xf] * fade_in + self._prev_tail * (1.0 - fade_in)
        self._prev_tail = output[-xf:].copy()
        return output


class FormantShifter(BaseEffect):
    """Décalage de formants indépendant du pitch (warp spectral)."""

    def __init__(self):
        super().__init__("Formant Shifter")
        self.params = {"shift": 0.0}  # -2.0 à +2.0

    def _process(self, audio, sr):
        shift = self.params["shift"]
        if shift == 0.0:
            return audio
        factor = 2.0 ** (shift / 2.0)
        n = len(audio)
        fd = rfft(audio)
        fl = len(fd)
        out_fd = np.zeros(fl, dtype=complex)
        indices = np.arange(fl)
        src = indices / factor
        valid = (src >= 0) & (src < fl - 1)
        idx_low = src[valid].astype(int)
        frac = src[valid] - idx_low
        out_fd[indices[valid]] = fd[idx_low] * (1 - frac) + fd[idx_low + 1] * frac
        return irfft(out_fd, n=n)


class Vibrato(BaseEffect):
    """Vibrato — modulation de pitch par LFO."""

    _MAX_DEPTH_MS = 25.0  # profondeur max supportée (ms)

    def __init__(self):
        super().__init__("Vibrato")
        self.params = {"rate": 5.0, "depth": 0.5}  # Hz, ms
        self._buf = None  # alloué à taille max au premier appel
        self._phase = 0.0
        self._wpos = 0

    def reset(self):
        self._buf = None
        self._phase = 0.0
        self._wpos = 0

    def _process(self, audio, sr):
        rate = self.params["rate"]
        depth_ms = min(self.params["depth"], self._MAX_DEPTH_MS)
        max_d = max(4, int(sr * self._MAX_DEPTH_MS / 1000.0 * 2))
        # Pré-alloue une fois à taille max, ne réalloue jamais
        if self._buf is None:
            self._buf = np.zeros(max_d * 4)
            self._wpos = 0
        buf = self._buf
        blen = len(buf)
        output = np.empty(len(audio))
        for i, x in enumerate(audio):
            buf[self._wpos % blen] = x
            lfo = (np.sin(2 * np.pi * self._phase) * 0.5 + 0.5)
            self._phase = (self._phase + rate / sr) % 1.0
            delay = lfo * max_d * 0.5
            rpos = self._wpos - delay
            ri = int(rpos) % blen
            frac = rpos - int(rpos)
            ri2 = (ri + 1) % blen
            output[i] = buf[ri] * (1 - frac) + buf[ri2] * frac
            self._wpos = (self._wpos + 1) % blen
        return output


class Tremolo(BaseEffect):
    """Tremolo — modulation d'amplitude par LFO sinusoïdal."""

    def __init__(self):
        super().__init__("Tremolo")
        self.params = {"rate": 5.0, "depth": 0.5}
        self._phase = 0.0

    def reset(self):
        self._phase = 0.0

    def _process(self, audio, sr):
        rate = self.params["rate"]
        depth = self.params["depth"]
        n = len(audio)
        phases = 2 * np.pi * rate * (np.arange(n) / sr) + self._phase
        lfo = 1.0 - depth * (1 - np.cos(phases)) * 0.5
        self._phase = (self._phase + 2 * np.pi * rate * n / sr) % (2 * np.pi)
        return audio * lfo


class OctaveDoubler(BaseEffect):
    """Doubler d'octave — voix parallèle une octave en dessous ou au-dessus."""

    def __init__(self):
        super().__init__("Octave Doubler")
        self.params = {"octave": -1, "mix": 0.5}

    def _process(self, audio, sr):
        n_steps = int(self.params["octave"]) * 12.0
        mix = self.params["mix"]
        factor = 2.0 if n_steps > 0 else 0.5  # toujours ±1 octave = ratio entier
        n = len(audio)
        resampled = signal.resample_poly(audio, int(factor * 2), 2) if factor != 1 else audio
        if len(resampled) >= n:
            shifted = resampled[:n].astype(np.float32)
        else:
            shifted = np.zeros(n, dtype=np.float32)
            shifted[:len(resampled)] = resampled
        return audio * (1 - mix) + shifted * mix


# ──────────────────────────────────────────────────────────────────────────────
# EFFETS TEMPORELS
# ──────────────────────────────────────────────────────────────────────────────

class Echo(BaseEffect):
    """Écho avec délai, feedback et mix wet/dry."""

    _MAX_DELAY_MS = 2000.0  # délai max supporté (ms)

    def __init__(self):
        super().__init__("Echo")
        self.params = {"delay_ms": 250.0, "feedback": 0.4, "mix": 0.3}
        self._buf = None  # alloué à taille max au premier appel
        self._wpos = 0

    def reset(self):
        self._buf = None
        self._wpos = 0

    def _process(self, audio, sr):
        delay_ms = min(self.params["delay_ms"], self._MAX_DELAY_MS)
        feedback = np.clip(self.params["feedback"], 0, 0.95)
        mix = self.params["mix"]
        delay_s = max(1, int(delay_ms * sr / 1000.0))
        # Pré-alloue une fois à taille max, ne réalloue jamais
        if self._buf is None:
            max_size = int(self._MAX_DELAY_MS * sr / 1000.0) * 2 + 4096
            self._buf = np.zeros(max_size)
            self._wpos = 0
        buf = self._buf
        blen = len(buf)
        output = np.empty(len(audio))
        for i, x in enumerate(audio):
            rpos = (self._wpos - delay_s) % blen
            delayed = buf[rpos]
            buf[self._wpos % blen] = x + delayed * feedback
            output[i] = x * (1 - mix) + delayed * mix
            self._wpos = (self._wpos + 1) % blen
        return np.clip(output, -1.0, 1.0)


class Reverb(BaseEffect):
    """Reverb algorithmique (design de Schroeder : filtres en peigne + all-pass)."""

    _COMB_DELAYS = [1557, 1617, 1491, 1422]
    _AP_DELAYS = [225, 556]

    def __init__(self):
        super().__init__("Reverb")
        self.params = {"room_size": 0.5, "damping": 0.5, "wet_dry": 0.3}
        self._initialized = False
        self._comb_bufs = []
        self._ap_bufs = []
        self._comb_pos = []
        self._ap_pos = []
        self._damp_state = []

    def reset(self):
        self._initialized = False

    def _init(self, room_size):
        scale = 0.7 + 0.28 * room_size
        self._comb_bufs = [np.zeros(max(2, int(d * scale))) for d in self._COMB_DELAYS]
        self._ap_bufs = [np.zeros(max(2, d)) for d in self._AP_DELAYS]
        self._comb_pos = [0] * 4
        self._ap_pos = [0] * 2
        self._damp_state = [0.0] * 4
        self._initialized = True

    def _process(self, audio, sr):
        room_size = self.params["room_size"]
        damping = self.params["damping"]
        wet = self.params["wet_dry"]
        if not self._initialized:
            self._init(room_size)
        fb = 0.84 - 0.15 * damping
        damp1 = damping * 0.4
        damp2 = 1.0 - damp1
        output = np.empty(len(audio))
        for i, x in enumerate(audio):
            rev = 0.0
            for j in range(4):
                buf = self._comb_bufs[j]
                n = len(buf)
                p = self._comb_pos[j]
                out_j = buf[p]
                self._damp_state[j] = out_j * damp2 + self._damp_state[j] * damp1
                buf[p] = x + self._damp_state[j] * fb
                rev += out_j
                self._comb_pos[j] = (p + 1) % n
            rev *= 0.25
            for j in range(2):
                buf = self._ap_bufs[j]
                n = len(buf)
                p = self._ap_pos[j]
                out_j = buf[p]
                buf[p] = rev + out_j * 0.5
                rev = out_j - rev * 0.5
                self._ap_pos[j] = (p + 1) % n
            output[i] = x * (1 - wet) + rev * wet
        return np.clip(output, -1.0, 1.0)


class Chorus(BaseEffect):
    """Chorus — plusieurs voix légèrement désaccordées et déphasées."""

    _MAX_VOICES = 8

    def __init__(self):
        super().__init__("Chorus")
        self.params = {"voices": 3, "depth": 8.0, "rate": 1.5, "mix": 0.5}
        self._bufs = []   # alloué au premier appel
        self._phases = []
        self._wpos = 0

    def reset(self):
        self._bufs = []

    def _process(self, audio, sr):
        voices = max(1, min(self._MAX_VOICES, int(self.params["voices"])))
        depth_ms = self.params["depth"]
        rate = self.params["rate"]
        mix = self.params["mix"]
        max_delay = max(4, int(sr * 0.04))
        # Pré-alloue toujours MAX_VOICES buffers, ne réalloue jamais
        if not self._bufs:
            self._bufs = [np.zeros(max_delay * 2) for _ in range(self._MAX_VOICES)]
            self._phases = [i / self._MAX_VOICES for i in range(self._MAX_VOICES)]
            self._wpos = 0
        blen = len(self._bufs[0])
        depth_s = depth_ms * sr / 1000.0
        output = np.copy(audio)
        for i, x in enumerate(audio):
            for j in range(voices):
                self._bufs[j][self._wpos % blen] = x
                lfo = np.sin(2 * np.pi * self._phases[j]) * 0.5 + 0.5
                self._phases[j] = (self._phases[j] + rate / sr) % 1.0
                delay = max(1, min(int(depth_s * (0.5 + lfo * 0.5)), blen - 1))
                rpos = (self._wpos - delay) % blen
                output[i] += self._bufs[j][rpos] * mix / voices
            self._wpos = (self._wpos + 1) % blen
        return np.clip(output, -1.0, 1.0)


class Flanger(BaseEffect):
    """Flanger — délai court modulé par LFO avec feedback."""

    def __init__(self):
        super().__init__("Flanger")
        self.params = {"delay_ms": 5.0, "depth": 0.7, "feedback": 0.5, "rate": 0.5, "mix": 0.5}
        self._buf = None
        self._phase = 0.0
        self._wpos = 0

    def reset(self):
        self._buf = None
        self._phase = 0.0
        self._wpos = 0

    def _process(self, audio, sr):
        delay_ms = self.params["delay_ms"]
        depth = self.params["depth"]
        feedback = np.clip(self.params["feedback"], -0.9, 0.9)
        rate = self.params["rate"]
        mix = self.params["mix"]
        max_d = max(4, int(sr * 0.05))
        if self._buf is None:
            self._buf = np.zeros(max_d * 2)
        buf = self._buf
        blen = len(buf)
        center = max(1, int(delay_ms * sr / 1000.0))
        mod_d = max(1, int(center * depth))
        output = np.empty(len(audio))
        for i, x in enumerate(audio):
            lfo = np.sin(2 * np.pi * self._phase)
            self._phase = (self._phase + rate / sr) % 1.0
            delay = max(1, min(center + int(lfo * mod_d), blen - 1))
            rpos = (self._wpos - delay) % blen
            delayed = buf[rpos]
            buf[self._wpos % blen] = x + delayed * feedback
            output[i] = x * (1 - mix) + delayed * mix
            self._wpos = (self._wpos + 1) % blen
        return np.clip(output, -1.0, 1.0)


class Phaser(BaseEffect):
    """Phaser — chaîne de filtres all-pass à fréquence modulée."""

    def __init__(self):
        super().__init__("Phaser")
        self.params = {"stages": 4, "rate": 0.5, "depth": 0.7, "mix": 0.5}
        self._phase = 0.0
        self._ap_states = []

    def reset(self):
        self._ap_states = []
        self._phase = 0.0

    def _process(self, audio, sr):
        stages = max(2, min(12, int(self.params["stages"])))
        rate = self.params["rate"]
        depth = self.params["depth"]
        mix = self.params["mix"]
        if len(self._ap_states) != stages:
            self._ap_states = [[0.0, 0.0] for _ in range(stages)]
        output = np.empty(len(audio))
        for i, x in enumerate(audio):
            lfo = np.sin(2 * np.pi * self._phase)
            self._phase = (self._phase + rate / sr) % 1.0
            freq = 200.0 + 3000.0 * (lfo * depth * 0.5 + 0.5)
            w0 = 2 * np.pi * freq / sr
            tan_w = np.tan(w0 / 2)
            coeff = (tan_w - 1) / (tan_w + 1)
            sig = x
            for j in range(stages):
                x0, y0 = self._ap_states[j]
                y = coeff * sig + x0 - coeff * y0
                self._ap_states[j] = [sig, y]
                sig = y
            output[i] = x * (1 - mix) + sig * mix
        return output


class MultiTapDelay(BaseEffect):
    """Délai multi-tap — jusqu'à 4 taps indépendants."""

    def __init__(self):
        super().__init__("Multi-Tap Delay")
        self.params = {
            "tap1_delay": 125.0, "tap1_level": 0.7,
            "tap2_delay": 250.0, "tap2_level": 0.5,
            "tap3_delay": 375.0, "tap3_level": 0.3,
            "tap4_delay": 500.0, "tap4_level": 0.15,
            "mix": 0.3,
        }
        self._buf = None
        self._wpos = 0

    _MAX_TAP_DELAY_MS = 2000.0

    def reset(self):
        self._buf = None
        self._wpos = 0

    def _process(self, audio, sr):
        mix = self.params["mix"]
        taps = [
            (max(1, int(min(self.params["tap1_delay"], self._MAX_TAP_DELAY_MS) * sr / 1000)), self.params["tap1_level"]),
            (max(1, int(min(self.params["tap2_delay"], self._MAX_TAP_DELAY_MS) * sr / 1000)), self.params["tap2_level"]),
            (max(1, int(min(self.params["tap3_delay"], self._MAX_TAP_DELAY_MS) * sr / 1000)), self.params["tap3_level"]),
            (max(1, int(min(self.params["tap4_delay"], self._MAX_TAP_DELAY_MS) * sr / 1000)), self.params["tap4_level"]),
        ]
        # Pré-alloue une fois à taille max, ne réalloue jamais
        if self._buf is None:
            max_size = int(self._MAX_TAP_DELAY_MS * sr / 1000.0) * 2 + 4096
            self._buf = np.zeros(max_size)
            self._wpos = 0
        buf = self._buf
        blen = len(buf)
        output = np.empty(len(audio))
        for i, x in enumerate(audio):
            buf[self._wpos % blen] = x
            wet = sum(buf[(self._wpos - d) % blen] * lvl for d, lvl in taps)
            output[i] = x * (1 - mix) + wet * mix
            self._wpos = (self._wpos + 1) % blen
        return np.clip(output, -1.0, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# EFFETS DE TIMBRE
# ──────────────────────────────────────────────────────────────────────────────

class Distortion(BaseEffect):
    """Distorsion / saturation — tanh soft-clip avec contrôle de tone."""

    def __init__(self):
        super().__init__("Distortion")
        self.params = {"drive": 5.0, "tone": 0.5, "mix": 0.5}
        self._b = self._a = None
        self._last_fc = None
        self._zi = None

    def reset(self):
        self._b = self._a = None
        self._last_fc = None
        self._zi = None

    def _process(self, audio, sr):
        drive = max(1.0, self.params["drive"])
        tone = self.params["tone"]
        mix = self.params["mix"]
        driven = np.tanh(audio * drive) / max(1e-9, np.tanh(drive))
        fc_hz = max(200.0, min(tone * 12000.0, sr / 2.0 * 0.99))
        if self._b is None or self._last_fc != fc_hz:
            self._b, self._a = signal.butter(1, fc_hz / (sr / 2.0), btype="low")
            self._last_fc = fc_hz
        if self._zi is None:
            self._zi = signal.lfilter_zi(self._b, self._a) * driven[0]
        toned, self._zi = signal.lfilter(self._b, self._a, driven, zi=self._zi)
        blended = driven * tone + toned * (1.0 - tone)
        return audio * (1 - mix) + blended * mix


class Bitcrusher(BaseEffect):
    """Bitcrusher — réduction de résolution et de sample rate."""

    def __init__(self):
        super().__init__("Bitcrusher")
        self.params = {"bits": 8.0, "rate_reduction": 4.0}

    def _process(self, audio, sr):
        bits = max(2.0, self.params["bits"])
        rate_red = max(1, int(self.params["rate_reduction"]))
        levels = 2.0 ** bits
        quantized = np.round(audio * levels / 2.0) / (levels / 2.0)
        if rate_red <= 1:
            return quantized
        output = np.empty_like(quantized)
        for i in range(0, len(quantized), rate_red):
            val = quantized[i]
            output[i: i + rate_red] = val
        return output


class RingModulator(BaseEffect):
    """Ring modulation — effet robot par multiplication avec porteuse sinusoïdale."""

    def __init__(self):
        super().__init__("Ring Modulator")
        self.params = {"frequency": 100.0, "mix": 0.7}
        self._phase = 0.0

    def reset(self):
        self._phase = 0.0

    def _process(self, audio, sr):
        freq = max(1.0, self.params["frequency"])
        mix = self.params["mix"]
        t = np.arange(len(audio)) / sr
        carrier = np.sin(2 * np.pi * freq * (t + self._phase))
        self._phase = (self._phase + len(audio) / sr) % (1.0 / freq) if freq > 0 else 0.0
        modulated = audio * carrier
        return audio * (1 - mix) + modulated * mix


class Vocoder(BaseEffect):
    """Vocoder simple — modulation spectrale par bandes de fréquences."""

    def __init__(self):
        super().__init__("Vocoder")
        self.params = {"bands": 16, "mix": 0.8}
        self._carrier_phase = 0.0

    def _process(self, audio, sr):
        bands = max(4, min(32, int(self.params["bands"])))
        mix = self.params["mix"]
        n = len(audio)
        fd = rfft(audio)
        fl = len(fd)
        band_size = max(1, fl // bands)
        output_fd = np.zeros(fl, dtype=complex)
        for b in range(bands):
            start = b * band_size
            end = min(start + band_size, fl)
            energy = np.mean(np.abs(fd[start:end]))
            noise_fd = np.random.randn(end - start) + 1j * np.random.randn(end - start)
            noise_fd /= max(1e-9, np.abs(noise_fd).mean())
            output_fd[start:end] = noise_fd * energy
        vocoded = irfft(output_fd, n=n)
        peak = np.max(np.abs(vocoded))
        if peak > 1e-9:
            vocoded = vocoded / peak * np.max(np.abs(audio))
        return audio * (1 - mix) + vocoded * mix


class WhisperEffect(BaseEffect):
    """Effet chuchotement — randomisation de phase spectrale + bruit."""

    def __init__(self):
        super().__init__("Whisper")
        self.params = {"intensity": 0.8}

    def _process(self, audio, sr):
        intensity = self.params["intensity"]
        fd = rfft(audio)
        magnitude = np.abs(fd)
        rnd_phase = np.random.uniform(-np.pi, np.pi, len(fd))
        whispered_fd = magnitude * np.exp(1j * rnd_phase)
        result = irfft(whispered_fd, n=len(audio))
        peak = np.max(np.abs(result))
        if peak > 1e-9:
            result = result / peak * np.max(np.abs(audio))
        noise = np.random.normal(0, 0.015 * intensity, len(audio))
        return result * (1 - intensity * 0.3) + noise


class GrowlEffect(BaseEffect):
    """Growl / throat — distorsion + filtre résonant bas pour harmoniques graves."""

    def __init__(self):
        super().__init__("Growl")
        self.params = {"drive": 3.0, "freq": 80.0, "mix": 0.4}
        self._b = self._a = None
        self._last_freq = None
        self._zi = None

    def reset(self):
        self._b = self._a = None
        self._last_freq = None
        self._zi = None

    def _process(self, audio, sr):
        drive = max(1.0, self.params["drive"])
        freq = max(20.0, min(self.params["freq"], sr / 2.0 * 0.9))
        mix = self.params["mix"]
        driven = np.tanh(audio * drive)
        if self._b is None or self._last_freq != freq:
            q = 4.0
            w0 = 2 * np.pi * freq / sr
            alpha = np.sin(w0) / (2 * q)
            self._b = [alpha, 0, -alpha]
            self._a = [1 + alpha, -2 * np.cos(w0), 1 - alpha]
            self._last_freq = freq
        if self._zi is None:
            self._zi = signal.lfilter_zi(self._b, self._a) * driven[0]
        filtered, self._zi = signal.lfilter(self._b, self._a, driven, zi=self._zi)
        return audio * (1 - mix) + filtered * mix


class HeliumEffect(BaseEffect):
    """Effet hélium / chipmunk — resample_poly (smooth) + high-shelf IIR stateful."""

    _XFADE = 64

    def __init__(self):
        super().__init__("Helium")
        self.params = {"amount": 0.5}
        self._up = self._down = None
        self._last_amount = None
        self._prev_tail   = None
        self._sos         = None
        self._zi          = None

    def reset(self):
        self._up = self._down = None
        self._last_amount = None
        self._prev_tail   = None
        self._sos         = None
        self._zi          = None

    def _process(self, audio, sr):
        from fractions import Fraction
        amount = self.params["amount"]
        if amount < 0.01:
            return audio

        n_steps = amount * 10.0          # 0 → 10 demi-tons
        factor  = 2.0 ** (n_steps / 12.0)
        n = len(audio)

        # ── Recalcul si amount a changé ──────────────────────────────
        if self._last_amount != round(amount, 3):
            frac = Fraction(factor).limit_denominator(100)
            self._up, self._down = frac.numerator, frac.denominator
            # High-shelf IIR (Audio EQ Cookbook) : booste les formants hauts
            shelf_db = amount * 9.0
            A  = 10 ** (shelf_db / 40.0)
            fc = min(0.45, 2000.0 / (sr / 2))
            w0 = 2 * np.pi * fc
            alpha = np.sin(w0) / np.sqrt(2)  # shelf slope = 1
            b0 =  A*((A+1) + (A-1)*np.cos(w0) + 2*np.sqrt(A)*alpha)
            b1 = -2*A*((A-1) + (A+1)*np.cos(w0))
            b2 =  A*((A+1) + (A-1)*np.cos(w0) - 2*np.sqrt(A)*alpha)
            a0 =    (A+1) - (A-1)*np.cos(w0) + 2*np.sqrt(A)*alpha
            a1 =  2*((A-1) - (A+1)*np.cos(w0))
            a2 =    (A+1) - (A-1)*np.cos(w0) - 2*np.sqrt(A)*alpha
            self._sos = np.array([[b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0]])
            self._zi  = None
            self._last_amount = round(amount, 3)

        # ── 1. Pitch shift via resample_poly ─────────────────────────
        resampled = signal.resample_poly(audio, self._up, self._down)
        if len(resampled) >= n:
            pitched = resampled[:n].astype(np.float32)
        else:
            pitched = np.zeros(n, dtype=np.float32)
            pitched[:len(resampled)] = resampled

        # ── 2. Crossfade inter-blocs ──────────────────────────────────
        xf = self._XFADE
        if self._prev_tail is not None and len(self._prev_tail) == xf:
            fade = np.linspace(0.0, 1.0, xf, dtype=np.float32)
            pitched[:xf] = pitched[:xf] * fade + self._prev_tail * (1 - fade)
        self._prev_tail = pitched[-xf:].copy()

        # ── 3. Formant emphasis — high-shelf IIR stateful ────────────
        if self._zi is None:
            self._zi = signal.sosfilt_zi(self._sos) * pitched[0]
        result, self._zi = signal.sosfilt(self._sos, pitched, zi=self._zi)

        return np.clip(result.astype(np.float32), -1.0, 1.0)


class TelephoneFilter(BaseEffect):
    """Filtre téléphonique — bande passante étroite 300–3400 Hz."""

    def __init__(self):
        super().__init__("Telephone Filter")
        self.params = {"low_cut": 300.0, "high_cut": 3400.0, "distortion": 0.2}
        self._b = self._a = None
        self._last_lo = self._last_hi = None
        self._zi = None

    def reset(self):
        self._b = self._a = None
        self._last_lo = self._last_hi = None
        self._zi = None

    def _process(self, audio, sr):
        nyq = sr / 2.0
        lo = max(100.0, self.params["low_cut"]) / nyq
        hi = min(0.99, self.params["high_cut"] / nyq)
        if lo >= hi:
            return audio
        if self._b is None or self._last_lo != lo or self._last_hi != hi:
            self._b, self._a = signal.butter(4, [lo, hi], btype="band")
            self._last_lo, self._last_hi = lo, hi
        if self._zi is None:
            self._zi = signal.lfilter_zi(self._b, self._a) * audio[0]
        filtered, self._zi = signal.lfilter(self._b, self._a, audio, zi=self._zi)
        dist = self.params["distortion"]
        if dist > 0:
            filtered = np.tanh(filtered * (1 + dist * 4))
        return filtered


class MegaphoneEffect(BaseEffect):
    """Mégaphone / porte-voix — distorsion + boost medium."""

    def __init__(self):
        super().__init__("Megaphone")
        self.params = {"drive": 6.0, "mid_boost_db": 8.0}
        self._b1 = self._a1 = None
        self._b2 = self._a2 = None
        self._zi1 = self._zi2 = None

    def reset(self):
        self._b1 = self._a1 = None
        self._b2 = self._a2 = None
        self._zi1 = self._zi2 = None

    def _process(self, audio, sr):
        drive = max(1.0, self.params["drive"])
        boost = self.params["mid_boost_db"]
        nyq = sr / 2.0
        if self._b1 is None:
            self._b1, self._a1 = signal.butter(4, [400.0 / nyq, 4000.0 / nyq], btype="band")
            self._b2, self._a2 = signal.butter(2, [800.0 / nyq, 3000.0 / nyq], btype="band")
        if self._zi1 is None:
            self._zi1 = signal.lfilter_zi(self._b1, self._a1) * audio[0]
        filtered, self._zi1 = signal.lfilter(self._b1, self._a1, audio, zi=self._zi1)
        distorted = np.tanh(filtered * drive)
        gain = 10 ** (boost / 20.0)
        if self._zi2 is None:
            self._zi2 = signal.lfilter_zi(self._b2, self._a2) * distorted[0]
        mid, self._zi2 = signal.lfilter(self._b2, self._a2, distorted, zi=self._zi2)
        return np.clip(distorted + mid * (gain - 1.0), -1.0, 1.0)


class RadioEffect(BaseEffect):
    """Effet radio — bruit + filtre bande étroite + légère saturation."""

    def __init__(self):
        super().__init__("Radio Effect")
        self.params = {"noise_level": 0.04, "bandwidth": 0.5}
        self._b = self._a = None
        self._last_hi = None
        self._zi = None

    def reset(self):
        self._b = self._a = None
        self._last_hi = None
        self._zi = None

    def _process(self, audio, sr):
        noise_level = self.params["noise_level"]
        bw = self.params["bandwidth"]
        nyq = sr / 2.0
        hi = min(0.99, (400.0 + bw * 2600.0) / nyq)
        lo = 300.0 / nyq
        if lo >= hi:
            lo = 0.01
        if self._b is None or self._last_hi != hi:
            self._b, self._a = signal.butter(4, [lo, hi], btype="band")
            self._last_hi = hi
        if self._zi is None:
            self._zi = signal.lfilter_zi(self._b, self._a) * audio[0]
        filtered, self._zi = signal.lfilter(self._b, self._a, audio, zi=self._zi)
        saturated = np.tanh(filtered * 2.0) * 0.65
        noise = np.random.normal(0, noise_level, len(audio))
        return np.clip(saturated + noise, -1.0, 1.0)


class UnderwaterEffect(BaseEffect):
    """Effet sous-marin — filtre passe-bas profond + modulation lente."""

    def __init__(self):
        super().__init__("Underwater")
        self.params = {"depth": 0.7, "wobble": 0.3, "wobble_rate": 2.0}
        self._phase = 0.0
        self._b = self._a = None
        self._last_cutoff = None
        self._zi = None

    def reset(self):
        self._phase = 0.0
        self._b = self._a = None
        self._last_cutoff = None
        self._zi = None

    def _process(self, audio, sr):
        depth = self.params["depth"]
        wobble = self.params["wobble"]
        rate = self.params["wobble_rate"]
        cutoff = max(100.0, 2000.0 * (1.0 - depth))
        nyq = sr / 2.0
        if self._b is None or self._last_cutoff != round(cutoff, 1):
            self._b, self._a = signal.butter(3, min(cutoff, nyq * 0.99) / nyq, btype="low")
            self._last_cutoff = round(cutoff, 1)
        if self._zi is None:
            self._zi = signal.lfilter_zi(self._b, self._a) * audio[0]
        filtered, self._zi = signal.lfilter(self._b, self._a, audio, zi=self._zi)
        t = np.arange(len(audio)) / sr
        mod = 1.0 + wobble * 0.3 * np.sin(2 * np.pi * rate * (t + self._phase))
        self._phase = (self._phase + len(audio) / sr) % (1.0 / max(rate, 0.01))
        return filtered * mod


# ──────────────────────────────────────────────────────────────────────────────
# FILTRES
# ──────────────────────────────────────────────────────────────────────────────

class LowPassFilter(BaseEffect):
    def __init__(self):
        super().__init__("Low-Pass Filter")
        self.params = {"cutoff": 8000.0, "resonance": 0.707}
        self._b = self._a = None
        self._last_key = None
        self._zi = None

    def reset(self):
        self._b = self._a = None
        self._last_key = None
        self._zi = None

    def _process(self, audio, sr):
        fc = max(20.0, min(self.params["cutoff"], sr / 2.0 * 0.99))
        q = max(0.1, self.params["resonance"])
        key = (round(fc, 1), round(q, 4))
        if self._b is None or self._last_key != key:
            w0 = 2 * np.pi * fc / sr
            alpha = np.sin(w0) / (2 * q)
            a0 = 1 + alpha
            self._b = [(1 - np.cos(w0)) / 2 / a0, (1 - np.cos(w0)) / a0, (1 - np.cos(w0)) / 2 / a0]
            self._a = [1.0, -2 * np.cos(w0) / a0, (1 - alpha) / a0]
            self._last_key = key
        if self._zi is None:
            self._zi = signal.lfilter_zi(self._b, self._a) * audio[0]
        out, self._zi = signal.lfilter(self._b, self._a, audio, zi=self._zi)
        return out


class HighPassFilter(BaseEffect):
    def __init__(self):
        super().__init__("High-Pass Filter")
        self.params = {"cutoff": 200.0, "resonance": 0.707}
        self._b = self._a = None
        self._last_key = None
        self._zi = None

    def reset(self):
        self._b = self._a = None
        self._last_key = None
        self._zi = None

    def _process(self, audio, sr):
        fc = max(20.0, min(self.params["cutoff"], sr / 2.0 * 0.99))
        q = max(0.1, self.params["resonance"])
        key = (round(fc, 1), round(q, 4))
        if self._b is None or self._last_key != key:
            w0 = 2 * np.pi * fc / sr
            alpha = np.sin(w0) / (2 * q)
            a0 = 1 + alpha
            self._b = [(1 + np.cos(w0)) / 2 / a0, -(1 + np.cos(w0)) / a0, (1 + np.cos(w0)) / 2 / a0]
            self._a = [1.0, -2 * np.cos(w0) / a0, (1 - alpha) / a0]
            self._last_key = key
        if self._zi is None:
            self._zi = signal.lfilter_zi(self._b, self._a) * audio[0]
        out, self._zi = signal.lfilter(self._b, self._a, audio, zi=self._zi)
        return out


class BandPassFilter(BaseEffect):
    def __init__(self):
        super().__init__("Band-Pass Filter")
        self.params = {"center": 1000.0, "bandwidth": 500.0}
        self._b = self._a = None
        self._last_key = None
        self._zi = None

    def reset(self):
        self._b = self._a = None
        self._last_key = None
        self._zi = None

    def _process(self, audio, sr):
        center = max(50.0, self.params["center"])
        bw = max(10.0, self.params["bandwidth"])
        nyq = sr / 2.0
        lo = max(0.01, (center - bw / 2) / nyq)
        hi = min(0.99, (center + bw / 2) / nyq)
        if lo >= hi:
            return audio
        key = (round(lo, 5), round(hi, 5))
        if self._b is None or self._last_key != key:
            self._b, self._a = signal.butter(2, [lo, hi], btype="band")
            self._last_key = key
        if self._zi is None:
            self._zi = signal.lfilter_zi(self._b, self._a) * audio[0]
        out, self._zi = signal.lfilter(self._b, self._a, audio, zi=self._zi)
        return out


class Equalizer(BaseEffect):
    """Égaliseur graphique 10 bandes."""

    BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

    def __init__(self):
        super().__init__("10-Band EQ")
        self.params = {f"band_{f}": 0.0 for f in self.BANDS}
        self._zi_bands = {}  # freq -> zi state
        self._last_gains = {}  # freq -> last gain_db

    def reset(self):
        self._zi_bands = {}
        self._last_gains = {}

    def _process(self, audio, sr):
        out = audio.copy()
        nyq = sr / 2.0
        for freq in self.BANDS:
            gain_db = self.params.get(f"band_{freq}", 0.0)
            if abs(gain_db) < 0.1:
                continue
            if freq >= nyq * 0.95:
                continue
            A = 10 ** (gain_db / 40.0)
            w0 = 2 * np.pi * freq / sr
            q = 1.41
            alpha = np.sin(w0) / (2 * q)
            b0 = 1 + alpha * A
            b1 = -2 * np.cos(w0)
            b2 = 1 - alpha * A
            a0 = 1 + alpha / A
            a1 = -2 * np.cos(w0)
            a2 = 1 - alpha / A
            b = [b0 / a0, b1 / a0, b2 / a0]
            a = [1.0, a1 / a0, a2 / a0]
            zi_key = freq
            if zi_key not in self._zi_bands:
                self._zi_bands[zi_key] = signal.lfilter_zi(b, a) * out[0]
            out, self._zi_bands[zi_key] = signal.lfilter(b, a, out, zi=self._zi_bands[zi_key])
        return out


class NoiseGate(BaseEffect):
    """Noise gate avec seuil, attack et release."""

    def __init__(self):
        super().__init__("Noise Gate")
        self.params = {"threshold_db": -40.0, "attack_ms": 5.0, "release_ms": 100.0}
        self._gain = 0.0

    def reset(self):
        self._gain = 0.0

    def _process(self, audio, sr):
        thresh = 10 ** (self.params["threshold_db"] / 20.0)
        att = 1 - np.exp(-1.0 / max(1, self.params["attack_ms"] * sr / 1000.0))
        rel = 1 - np.exp(-1.0 / max(1, self.params["release_ms"] * sr / 1000.0))
        output = np.empty(len(audio))
        for i, x in enumerate(audio):
            if abs(x) > thresh:
                self._gain += att * (1.0 - self._gain)
            else:
                self._gain += rel * (0.0 - self._gain)
            output[i] = x * self._gain
        return output


class Compressor(BaseEffect):
    """Compresseur dynamique — threshold, ratio, attack, release, makeup gain."""

    def __init__(self):
        super().__init__("Compressor")
        self.params = {
            "threshold_db": -20.0,
            "ratio": 4.0,
            "attack_ms": 5.0,
            "release_ms": 50.0,
            "makeup_gain_db": 0.0,
        }
        self._env = 0.0
        self._gain = 1.0

    def reset(self):
        self._env = 0.0
        self._gain = 1.0

    def _process(self, audio, sr):
        thresh_lin = 10 ** (self.params["threshold_db"] / 20.0)
        ratio = max(1.0, self.params["ratio"])
        att = np.exp(-1.0 / max(1, self.params["attack_ms"] * sr / 1000.0))
        rel = np.exp(-1.0 / max(1, self.params["release_ms"] * sr / 1000.0))
        makeup = 10 ** (self.params["makeup_gain_db"] / 20.0)
        output = np.empty(len(audio))
        for i, x in enumerate(audio):
            lvl = abs(x)
            if lvl > self._env:
                self._env = att * self._env + (1 - att) * lvl
            else:
                self._env = rel * self._env + (1 - rel) * lvl
            if self._env > thresh_lin:
                over = self._env / thresh_lin
                target = thresh_lin * (over ** (1.0 / ratio))
                tgain = target / max(1e-9, self._env)
            else:
                tgain = 1.0
            self._gain = self._gain * 0.995 + tgain * 0.005
            output[i] = x * self._gain * makeup
        return output


class DeEsser(BaseEffect):
    """De-esser / expandeur — atténuation des sibilantes (hautes fréquences)."""

    def __init__(self):
        super().__init__("De-Esser")
        self.params = {"threshold_db": -20.0, "frequency": 6000.0, "reduction_db": 6.0}
        self._env = 0.0

    def _process(self, audio, sr):
        thresh = 10 ** (self.params["threshold_db"] / 20.0)
        freq = max(1000.0, min(self.params["frequency"], sr / 2.0 * 0.99))
        reduction = 10 ** (-abs(self.params["reduction_db"]) / 20.0)
        nyq = sr / 2.0
        b, a = signal.butter(2, freq / nyq, btype="high")
        sibilant = signal.lfilter(b, a, audio)
        output = audio.copy()
        att = np.exp(-1.0 / (sr * 0.002))
        rel = np.exp(-1.0 / (sr * 0.05))
        for i in range(len(audio)):
            lvl = abs(sibilant[i])
            if lvl > self._env:
                self._env = att * self._env + (1 - att) * lvl
            else:
                self._env = rel * self._env + (1 - rel) * lvl
            if self._env > thresh:
                output[i] *= reduction
        return output


# ──────────────────────────────────────────────────────────────────────────────
# Chaîne d'effets
# ──────────────────────────────────────────────────────────────────────────────

ALL_EFFECTS_CLASSES = [
    # Pitch & tonalité
    PitchShifter, FormantShifter, Vibrato, Tremolo, OctaveDoubler,
    # Temporels
    Echo, Reverb, Chorus, Flanger, Phaser, MultiTapDelay,
    # Timbre
    Distortion, Bitcrusher, RingModulator, Vocoder, WhisperEffect,
    GrowlEffect, HeliumEffect, TelephoneFilter, MegaphoneEffect,
    RadioEffect, UnderwaterEffect,
    # Filtres
    LowPassFilter, HighPassFilter, BandPassFilter, Equalizer,
    NoiseGate, Compressor, DeEsser,
]


class EffectsChain:
    """Chaîne ordonnée d'effets audio avec bypass global et individuel."""

    def __init__(self):
        self._lock = threading.Lock()
        self.bypass_all = False
        self.effects: list[BaseEffect] = [cls() for cls in ALL_EFFECTS_CLASSES]

    def process(self, audio: np.ndarray, sr: int) -> np.ndarray:
        if self.bypass_all:
            return audio
        with self._lock:
            chain = list(self.effects)
        out = audio.astype(np.float32)
        for effect in chain:
            if effect.enabled:
                out = effect.process(out, sr)
        return out

    def get_effect(self, name: str) -> BaseEffect | None:
        for e in self.effects:
            if e.name == name:
                return e
        return None

    def to_dict(self) -> list:
        with self._lock:
            return [e.to_dict() for e in self.effects]

    def from_dict(self, data: list):
        with self._lock:
            for edict in data:
                effect = self.get_effect(edict.get("name", ""))
                if effect:
                    effect.from_dict(edict)

    def reset_all(self):
        with self._lock:
            for e in self.effects:
                e.reset()

    def reorder(self, new_order: list[str]):
        """Réordonne les effets selon une liste de noms."""
        with self._lock:
            lookup = {e.name: e for e in self.effects}
            ordered = [lookup[n] for n in new_order if n in lookup]
            remaining = [e for e in self.effects if e.name not in new_order]
            self.effects = ordered + remaining
