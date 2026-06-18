# main.py - Interface graphique principale (CustomTkinter)

import threading
import json
import os
import sys
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, colorchooser
import tkinter as tk
import numpy as np

try:
    import sounddevice as _sd_check
    SD_OK = True
    del _sd_check
except ImportError:
    SD_OK = False

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    CTK = True
except ImportError:
    import tkinter as ctk
    CTK = False
    print("[UI] customtkinter non disponible, utilisation de tkinter basique.")

try:
    import keyboard as kb
    KB_OK = True
except ImportError:
    KB_OK = False
    print("[UI] keyboard non disponible, raccourcis globaux désactivés.")

from config_manager import ConfigManager
from audio_engine import AudioEngine
from effects import EffectsChain, ALL_EFFECTS_CLASSES
from profile_manager import ProfileManager
from soundboard_manager import SoundboardManager


# ──────────────────────────────────────────────────────────────────────────────
# Widgets personnalisés
# ──────────────────────────────────────────────────────────────────────────────

class VUMeter(tk.Canvas):
    """VU-mètre animé vertical (vert → jaune → rouge)."""

    def __init__(self, parent, width=20, height=120, **kw):
        super().__init__(parent, width=width, height=height, bg="#1a1a1a",
                         highlightthickness=1, highlightbackground="#333", **kw)
        self._level = 0.0
        self._peak = 0.0
        self._peak_hold = 0
        self.bind("<Configure>", lambda e: self._draw())

    def update_level(self, rms: float):
        # RMS → dB → niveau visuel 0–1
        if rms > 1e-6:
            db = 20 * __import__("math").log10(rms)
            level = max(0.0, min(1.0, (db + 60) / 60))
        else:
            level = 0.0
        # Smooth decay
        if level > self._level:
            self._level = level
        else:
            self._level = self._level * 0.85 + level * 0.15
        # Peak hold
        if self._level >= self._peak:
            self._peak = self._level
            self._peak_hold = 60
        else:
            if self._peak_hold > 0:
                self._peak_hold -= 1
            else:
                self._peak = self._peak * 0.95
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            return
        # Background
        self.create_rectangle(0, 0, w, h, fill="#111", outline="")
        bar_h = int(h * self._level)
        if bar_h > 0:
            # Gradient colors
            green_h = int(h * 0.65)
            yellow_h = int(h * 0.85)
            if bar_h <= green_h:
                self.create_rectangle(0, h - bar_h, w, h, fill="#00cc44", outline="")
            elif bar_h <= yellow_h:
                self.create_rectangle(0, h - green_h, w, h, fill="#00cc44", outline="")
                self.create_rectangle(0, h - bar_h, w, h - green_h, fill="#ffcc00", outline="")
            else:
                self.create_rectangle(0, h - green_h, w, h, fill="#00cc44", outline="")
                self.create_rectangle(0, h - yellow_h, w, h - green_h, fill="#ffcc00", outline="")
                self.create_rectangle(0, h - bar_h, w, h - yellow_h, fill="#ff3333", outline="")
        # Peak marker
        pk_y = int(h * (1 - self._peak))
        self.create_line(0, pk_y, w, pk_y, fill="#ffffff", width=1)


class CollapsibleSection(tk.Frame):
    """Section repliable avec titre et contenu."""

    def __init__(self, parent, title: str, collapsed: bool = True, **kw):
        bg = "#1e1e2e" if not CTK else "#1e1e2e"
        super().__init__(parent, bg=bg, bd=1, relief="solid", **kw)
        self._collapsed = collapsed
        self._btn_text = tk.StringVar()

        self.header = tk.Frame(self, bg="#2a2a3e", cursor="hand2")
        self.header.pack(fill="x")

        self._toggle_btn = tk.Label(
            self.header, text=self._indicator(), bg="#2a2a3e", fg="#aaaaff",
            font=("Consolas", 9, "bold"), padx=6, pady=4, anchor="w",
            cursor="hand2"
        )
        self._toggle_btn.pack(side="left")

        self._title_lbl = tk.Label(
            self.header, text=title, bg="#2a2a3e", fg="#ddddff",
            font=("Segoe UI", 10, "bold"), pady=4, anchor="w"
        )
        self._title_lbl.pack(side="left", fill="x", expand=True)

        # Enable checkbox
        self.enabled_var = tk.BooleanVar(value=False)
        self._enable_cb = tk.Checkbutton(
            self.header, text="ON", variable=self.enabled_var,
            bg="#2a2a3e", fg="#88ff88", selectcolor="#1a1a2e",
            activebackground="#2a2a3e", activeforeground="#88ff88",
            font=("Segoe UI", 8), pady=4
        )
        self._enable_cb.pack(side="right", padx=6)

        self.content = tk.Frame(self, bg="#1e1e2e")
        if not collapsed:
            self.content.pack(fill="x", padx=4, pady=(0, 4))

        self.header.bind("<Button-1>", self._toggle)
        self._toggle_btn.bind("<Button-1>", self._toggle)
        self._title_lbl.bind("<Button-1>", self._toggle)

    def _indicator(self):
        return "▶" if self._collapsed else "▼"

    def _toggle(self, event=None):
        self._collapsed = not self._collapsed
        self._toggle_btn.config(text=self._indicator())
        if self._collapsed:
            self.content.pack_forget()
        else:
            self.content.pack(fill="x", padx=4, pady=(0, 4))

    def expand(self):
        if self._collapsed:
            self._toggle()

    def collapse(self):
        if not self._collapsed:
            self._toggle()


class ParamSlider(tk.Frame):
    """Slider + label + saisie numérique directe."""

    def __init__(self, parent, label: str, from_: float, to: float,
                 initial: float, on_change: callable, fmt: str = ".2f",
                 desc: str = "", **kw):
        super().__init__(parent, bg="#1e1e2e", **kw)
        self._on_change = on_change
        self._from = from_
        self._to = to
        self._fmt = fmt

        tk.Label(self, text=label, bg="#1e1e2e", fg="#cccccc",
                 font=("Segoe UI", 8), width=18, anchor="w").pack(side="left")

        self._var = tk.DoubleVar(value=initial)

        if CTK:
            self._slider = ctk.CTkSlider(
                self, from_=from_, to=to, variable=self._var,
                command=self._slider_moved, width=160, height=14
            )
        else:
            self._slider = tk.Scale(
                self, from_=from_, to=to, variable=self._var,
                orient="horizontal", command=self._slider_moved,
                bg="#1e1e2e", fg="#cccccc", length=160,
                showvalue=False, resolution=(to - from_) / 1000
            )
        self._slider.pack(side="left", padx=(4, 4))

        self._entry = tk.Entry(self, textvariable=self._var, width=8,
                               bg="#2a2a3a", fg="#ffffff", insertbackground="white",
                               font=("Consolas", 8), justify="right", bd=1, relief="solid")
        self._entry.pack(side="left")
        self._entry.bind("<Return>", self._entry_changed)
        self._entry.bind("<FocusOut>", self._entry_changed)

        if desc:
            tk.Label(self, text=desc, bg="#1e1e2e", fg="#555577",
                     font=("Segoe UI", 7, "italic")).pack(side="left", padx=(6, 0))

    def _slider_moved(self, val):
        try:
            v = float(val)
            self._on_change(v)
        except ValueError:
            pass

    def _entry_changed(self, event=None):
        try:
            v = float(self._entry.get())
            v = max(self._from, min(self._to, v))
            self._var.set(v)
            self._on_change(v)
        except ValueError:
            self._var.set(self._var.get())

    def get(self) -> float:
        return self._var.get()

    def set(self, v: float):
        self._var.set(float(v))


# ──────────────────────────────────────────────────────────────────────────────
# Onglet Modificateur de voix
# ──────────────────────────────────────────────────────────────────────────────

EFFECT_PARAMS_META = {
    "Pitch Shifter": [
        ("semitones", "Demi-tons", -24.0, 24.0, ".1f", "Monte ou descend la voix en demi-tons (12 = 1 octave)"),
    ],
    "Formant Shifter": [
        ("shift", "Décalage formants", -2.0, 2.0, ".2f", "Change la couleur de la voix sans changer la note"),
    ],
    "Vibrato": [
        ("rate", "Vitesse (Hz)", 0.1, 20.0, ".1f", "Rapidité du tremblement de voix"),
        ("depth", "Profondeur (ms)", 0.1, 20.0, ".1f", "Amplitude du tremblement"),
    ],
    "Tremolo": [
        ("rate", "Vitesse (Hz)", 0.1, 20.0, ".1f", "Rapidité du pulsement du volume"),
        ("depth", "Profondeur", 0.0, 1.0, ".2f", "Intensité du pulsement (0 = rien, 1 = coupures franches)"),
    ],
    "Octave Doubler": [
        ("octave", "Octave (-1/+1)", -1.0, 1.0, ".0f", "-1 = ajoute une voix grave en dessous, +1 = voix aiguë"),
        ("mix", "Mix", 0.0, 1.0, ".2f", "Dosage entre voix originale et voix dupliquée"),
    ],
    "Echo": [
        ("delay_ms", "Délai (ms)", 1.0, 2000.0, ".0f", "Temps avant que l'écho revienne (ms)"),
        ("feedback", "Feedback", 0.0, 0.95, ".2f", "Combien d'échos s'enchaînent (0 = 1 seul, 0.9 = longue traîne)"),
        ("mix", "Mix Wet", 0.0, 1.0, ".2f", "Volume de l'écho par rapport à la voix originale"),
    ],
    "Reverb": [
        ("room_size", "Taille salle", 0.0, 1.0, ".2f", "0 = petite pièce, 1 = grande cathédrale"),
        ("damping", "Damping", 0.0, 1.0, ".2f", "Absorption des hautes fréquences (1 = reverb sombre)"),
        ("wet_dry", "Wet/Dry", 0.0, 1.0, ".2f", "Dosage reverb / voix sèche"),
    ],
    "Chorus": [
        ("voices", "Voix", 1.0, 8.0, ".0f", "Nombre de copies légèrement désaccordées de ta voix"),
        ("depth", "Profondeur (ms)", 0.1, 30.0, ".1f", "Amplitude du désaccordage entre les voix"),
        ("rate", "Vitesse (Hz)", 0.1, 10.0, ".1f", "Rapidité du mouvement entre les voix"),
        ("mix", "Mix", 0.0, 1.0, ".2f", "Dosage effet / voix sèche"),
    ],
    "Flanger": [
        ("delay_ms", "Délai (ms)", 0.1, 20.0, ".1f", "Durée du délai de base (court = effet jet)"),
        ("depth", "Profondeur", 0.0, 1.0, ".2f", "Amplitude de la modulation du délai"),
        ("feedback", "Feedback", -0.9, 0.9, ".2f", "Réinjection du signal (négatif = inverse)"),
        ("rate", "Vitesse LFO (Hz)", 0.01, 10.0, ".2f", "Vitesse de balayage du délai"),
        ("mix", "Mix", 0.0, 1.0, ".2f", "Dosage effet / voix sèche"),
    ],
    "Phaser": [
        ("stages", "Étages", 2.0, 12.0, ".0f", "Nombre de filtres en cascade (plus = effet plus prononcé)"),
        ("rate", "Vitesse (Hz)", 0.01, 10.0, ".2f", "Rapidité du balayage de fréquence"),
        ("depth", "Profondeur", 0.0, 1.0, ".2f", "Amplitude du balayage"),
        ("mix", "Mix", 0.0, 1.0, ".2f", "Dosage effet / voix sèche"),
    ],
    "Multi-Tap Delay": [
        ("tap1_delay", "Tap 1 (ms)", 1.0, 2000.0, ".0f", "Temps du 1er écho"),
        ("tap1_level", "Tap 1 Niveau", 0.0, 1.0, ".2f", "Volume du 1er écho"),
        ("tap2_delay", "Tap 2 (ms)", 1.0, 2000.0, ".0f", "Temps du 2e écho"),
        ("tap2_level", "Tap 2 Niveau", 0.0, 1.0, ".2f", "Volume du 2e écho"),
        ("tap3_delay", "Tap 3 (ms)", 1.0, 2000.0, ".0f", "Temps du 3e écho"),
        ("tap3_level", "Tap 3 Niveau", 0.0, 1.0, ".2f", "Volume du 3e écho"),
        ("tap4_delay", "Tap 4 (ms)", 1.0, 2000.0, ".0f", "Temps du 4e écho"),
        ("tap4_level", "Tap 4 Niveau", 0.0, 1.0, ".2f", "Volume du 4e écho"),
        ("mix", "Mix", 0.0, 1.0, ".2f", "Volume global des échos"),
    ],
    "Distortion": [
        ("drive", "Drive", 1.0, 100.0, ".1f", "Intensité de la saturation (1 = propre, 100 = très saturé)"),
        ("tone", "Tone", 0.0, 1.0, ".2f", "Couleur : 0 = sombre/filtré, 1 = brillant/direct"),
        ("mix", "Mix", 0.0, 1.0, ".2f", "Dosage distorsion / voix sèche"),
    ],
    "Bitcrusher": [
        ("bits", "Bits (résolution)", 2.0, 16.0, ".1f", "Résolution audio : 16 = qualité CD, 4 = son 8-bit rétro"),
        ("rate_reduction", "Réduction SR", 1.0, 32.0, ".0f", "Réduit la fréquence d'échantillonnage (effet lo-fi)"),
    ],
    "Ring Modulator": [
        ("frequency", "Fréquence (Hz)", 1.0, 2000.0, ".0f", "Fréquence de la porteuse (100 Hz = son robotique)"),
        ("mix", "Mix", 0.0, 1.0, ".2f", "Dosage effet / voix sèche"),
    ],
    "Vocoder": [
        ("bands", "Bandes", 4.0, 32.0, ".0f", "Nombre de bandes de fréquences analysées (plus = plus précis)"),
        ("mix", "Mix", 0.0, 1.0, ".2f", "Dosage vocoder / voix sèche"),
    ],
    "Whisper": [
        ("intensity", "Intensité", 0.0, 1.0, ".2f", "Force du chuchotement (1 = presque inaudible mais sibilant)"),
    ],
    "Growl": [
        ("drive", "Drive", 1.0, 20.0, ".1f", "Intensité des harmoniques graves"),
        ("freq", "Fréquence (Hz)", 20.0, 300.0, ".0f", "Fréquence centrale du grognement (graves profonds)"),
        ("mix", "Mix", 0.0, 1.0, ".2f", "Dosage growl / voix sèche"),
    ],
    "Helium": [
        ("amount", "Intensité", 0.0, 1.0, ".2f", "Plus c'est haut, plus tu sonnes comme Alvin"),
    ],
    "Telephone Filter": [
        ("low_cut", "Coupure basse (Hz)", 50.0, 1000.0, ".0f", "Enlève les graves en dessous de cette fréquence"),
        ("high_cut", "Coupure haute (Hz)", 1000.0, 8000.0, ".0f", "Enlève les aigus au-dessus de cette fréquence"),
        ("distortion", "Distorsion", 0.0, 1.0, ".2f", "Ajoute la saturation caractéristique des vieilles lignes"),
    ],
    "Megaphone": [
        ("drive", "Drive", 1.0, 30.0, ".1f", "Intensité de la distorsion du mégaphone"),
        ("mid_boost_db", "Boost médium (dB)", 0.0, 20.0, ".1f", "Amplifie les médiums (donne le côté creux du mégaphone)"),
    ],
    "Radio Effect": [
        ("noise_level", "Niveau bruit", 0.0, 0.3, ".3f", "Quantité de grésil radio en fond"),
        ("bandwidth", "Largeur de bande", 0.0, 1.0, ".2f", "0 = bande très étroite (AM), 1 = plus large (FM)"),
    ],
    "Underwater": [
        ("depth", "Profondeur", 0.0, 1.0, ".2f", "0 = surface, 1 = fond (coupe de plus en plus les aigus)"),
        ("wobble", "Wobble", 0.0, 1.0, ".2f", "Intensité du mouvement aquatique du volume"),
        ("wobble_rate", "Vitesse wobble (Hz)", 0.1, 10.0, ".1f", "Rapidité des vagues sonores"),
    ],
    "Low-Pass Filter": [
        ("cutoff", "Coupure (Hz)", 20.0, 20000.0, ".0f", "Laisse passer tout en dessous, coupe tout au-dessus"),
        ("resonance", "Résonance (Q)", 0.1, 10.0, ".2f", "Amplification autour de la fréquence de coupure"),
    ],
    "High-Pass Filter": [
        ("cutoff", "Coupure (Hz)", 20.0, 20000.0, ".0f", "Laisse passer tout au-dessus, coupe tout en dessous"),
        ("resonance", "Résonance (Q)", 0.1, 10.0, ".2f", "Amplification autour de la fréquence de coupure"),
    ],
    "Band-Pass Filter": [
        ("center", "Centre (Hz)", 50.0, 15000.0, ".0f", "Fréquence centrale de la bande laissée passer"),
        ("bandwidth", "Largeur (Hz)", 10.0, 5000.0, ".0f", "Largeur de la bande autour du centre"),
    ],
    "10-Band EQ": None,  # traitement spécial
    "Noise Gate": [
        ("threshold_db", "Seuil (dB)", -80.0, 0.0, ".1f", "En dessous de ce volume, le son est coupé"),
        ("attack_ms", "Attack (ms)", 0.1, 100.0, ".1f", "Temps pour ouvrir la porte quand la voix commence"),
        ("release_ms", "Release (ms)", 1.0, 1000.0, ".0f", "Temps pour fermer la porte quand la voix s'arrête"),
    ],
    "Compressor": [
        ("threshold_db", "Seuil (dB)", -60.0, 0.0, ".1f", "Au-dessus de ce volume, la compression commence"),
        ("ratio", "Ratio", 1.0, 20.0, ".1f", "Force de compression (4:1 = courant, 20:1 = limiteur)"),
        ("attack_ms", "Attack (ms)", 0.1, 100.0, ".1f", "Temps de réaction quand le volume dépasse le seuil"),
        ("release_ms", "Release (ms)", 1.0, 1000.0, ".0f", "Temps pour relâcher la compression après la baisse"),
        ("makeup_gain_db", "Makeup Gain (dB)", -20.0, 30.0, ".1f", "Compense le volume perdu par la compression"),
    ],
    "De-Esser": [
        ("threshold_db", "Seuil (dB)", -60.0, 0.0, ".1f", "Niveau à partir duquel les sibilantes sont atténuées"),
        ("frequency", "Fréquence (Hz)", 1000.0, 16000.0, ".0f", "Zone de fréquence ciblée (sibilantes ~5-8 kHz)"),
        ("reduction_db", "Réduction (dB)", 0.0, 24.0, ".1f", "Combien les sibilantes sont réduites en volume"),
    ],
}

EQ_BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


# ──────────────────────────────────────────────────────────────────────────────
# Testeur de périphériques audio
# ──────────────────────────────────────────────────────────────────────────────

class DeviceTester(tk.Toplevel):
    """
    Fenêtre qui teste tous les périphériques audio détectés :
    - Entrées : parle et regarde quel VU-mètre bouge → c'est ton micro
    - Sorties  : clique Bip et écoute où tu entends le son → c'est ton HP/câble
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Testeur de périphériques audio")
        self.configure(bg="#0d0d1a")
        self.geometry("820x600")
        self.resizable(True, True)
        self.grab_set()

        self._running = False
        self._input_streams = []
        self._vu_vars: dict[int, tk.DoubleVar] = {}
        self._vu_bars: dict[int, tk.Canvas] = {}
        self._status_vars: dict[int, tk.StringVar] = {}

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._start_monitoring)

    # ──────────────────────────────────────────────────────────────────
    def _build(self):
        header = tk.Label(self, bg="#0d0d1a", fg="#aaaaff",
                          font=("Segoe UI", 11, "bold"),
                          text="Parle dans ton micro → regarde quel niveau monte   |   Clique Bip → écoute d'où vient le son")
        header.pack(fill="x", padx=12, pady=(10, 4))

        paned = tk.PanedWindow(self, orient="horizontal", bg="#0d0d1a",
                               sashwidth=6, sashpad=2)
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        # ── Entrées ──────────────────────────────────────────────────
        in_outer = tk.LabelFrame(paned, text=" 🎙 Entrées (micros) ", bg="#0d0d1a",
                                  fg="#88ff88", font=("Segoe UI", 9, "bold"),
                                  bd=1, relief="solid")
        paned.add(in_outer, minsize=300)

        in_scroll_frame = tk.Frame(in_outer, bg="#0d0d1a")
        in_scroll_frame.pack(fill="both", expand=True)

        in_canvas = tk.Canvas(in_scroll_frame, bg="#0d0d1a", highlightthickness=0)
        in_sb = tk.Scrollbar(in_scroll_frame, orient="vertical", command=in_canvas.yview)
        in_canvas.configure(yscrollcommand=in_sb.set)
        in_sb.pack(side="right", fill="y")
        in_canvas.pack(side="left", fill="both", expand=True)

        self._in_frame = tk.Frame(in_canvas, bg="#0d0d1a")
        cw = in_canvas.create_window((0, 0), window=self._in_frame, anchor="nw")
        self._in_frame.bind("<Configure>", lambda e: in_canvas.configure(
            scrollregion=in_canvas.bbox("all")))
        in_canvas.bind("<Configure>", lambda e: in_canvas.itemconfig(cw, width=e.width))

        # ── Sorties ──────────────────────────────────────────────────
        out_outer = tk.LabelFrame(paned, text=" 🔊 Sorties (HP / câble) ", bg="#0d0d1a",
                                   fg="#ffaa44", font=("Segoe UI", 9, "bold"),
                                   bd=1, relief="solid")
        paned.add(out_outer, minsize=300)

        out_scroll_frame = tk.Frame(out_outer, bg="#0d0d1a")
        out_scroll_frame.pack(fill="both", expand=True)

        out_canvas = tk.Canvas(out_scroll_frame, bg="#0d0d1a", highlightthickness=0)
        out_sb = tk.Scrollbar(out_scroll_frame, orient="vertical", command=out_canvas.yview)
        out_canvas.configure(yscrollcommand=out_sb.set)
        out_sb.pack(side="right", fill="y")
        out_canvas.pack(side="left", fill="both", expand=True)

        self._out_frame = tk.Frame(out_canvas, bg="#0d0d1a")
        cw2 = out_canvas.create_window((0, 0), window=self._out_frame, anchor="nw")
        self._out_frame.bind("<Configure>", lambda e: out_canvas.configure(
            scrollregion=out_canvas.bbox("all")))
        out_canvas.bind("<Configure>", lambda e: out_canvas.itemconfig(cw2, width=e.width))

        # Charger les périphériques
        self._load_devices()

        tk.Button(self, text="✕ Fermer", command=self._on_close,
                  bg="#333355", fg="white", bd=0, padx=16, pady=6,
                  font=("Segoe UI", 9)).pack(pady=8)

    def _load_devices(self):
        try:
            import sounddevice as sd
            devs = sd.query_devices()
        except Exception:
            tk.Label(self._in_frame, text="sounddevice non disponible",
                     bg="#0d0d1a", fg="#ff6666").pack()
            return

        for i, dev in enumerate(devs):
            if dev["max_input_channels"] > 0:
                self._add_input_row(i, dev["name"])
            if dev["max_output_channels"] > 0:
                self._add_output_row(i, dev["name"])

    def _add_input_row(self, idx, name):
        row = tk.Frame(self._in_frame, bg="#111122", bd=1, relief="solid")
        row.pack(fill="x", padx=4, pady=2)

        tk.Label(row, text=f"[{idx}]", bg="#111122", fg="#666688",
                 font=("Consolas", 8), width=4).pack(side="left", padx=(4, 0))

        tk.Label(row, text=name[:38], bg="#111122", fg="#ccccff",
                 font=("Segoe UI", 8), anchor="w", width=34).pack(side="left", padx=4)

        # VU bar
        bar = tk.Canvas(row, width=100, height=14, bg="#222233",
                        highlightthickness=1, highlightbackground="#333355")
        bar.pack(side="left", padx=4, pady=3)
        self._vu_bars[idx] = bar

        lbl = tk.Label(row, text="0.0%", bg="#111122", fg="#888888",
                       font=("Consolas", 7), width=6)
        lbl.pack(side="left")
        self._vu_vars[idx] = lbl

    def _add_output_row(self, idx, name):
        row = tk.Frame(self._out_frame, bg="#1a1100", bd=1, relief="solid")
        row.pack(fill="x", padx=4, pady=2)

        tk.Label(row, text=f"[{idx}]", bg="#1a1100", fg="#886644",
                 font=("Consolas", 8), width=4).pack(side="left", padx=(4, 0))

        tk.Label(row, text=name[:34], bg="#1a1100", fg="#ffddaa",
                 font=("Segoe UI", 8), anchor="w", width=30).pack(side="left", padx=4)

        status = tk.StringVar(value="")
        self._status_vars[idx] = status
        tk.Label(row, textvariable=status, bg="#1a1100", fg="#88ff88",
                 font=("Segoe UI", 7), width=8).pack(side="left")

        tk.Button(row, text="♪ Bip", command=lambda i=idx: self._play_beep(i),
                  bg="#3a2800", fg="#ffcc44", font=("Segoe UI", 8),
                  bd=0, padx=8, pady=2, cursor="hand2").pack(side="right", padx=6, pady=3)

    # ──────────────────────────────────────────────────────────────────
    # Monitoring des entrées en temps réel
    # ──────────────────────────────────────────────────────────────────

    def _start_monitoring(self):
        if not SD_OK:
            return
        self._running = True
        import sounddevice as sd

        self._levels: dict[int, float] = {}

        for idx in list(self._vu_bars.keys()):
            def make_cb(device_idx):
                def cb(indata, frames, t, status):
                    if not self._running:
                        raise sd.CallbackStop()
                    rms = float(np.sqrt(np.mean(indata ** 2)))
                    self._levels[device_idx] = rms
                return cb

            try:
                s = sd.InputStream(
                    device=idx, channels=1, samplerate=44100,
                    blocksize=2048, dtype="float32",
                    callback=make_cb(idx), latency="high",
                )
                s.start()
                self._input_streams.append(s)
            except Exception:
                self._levels[idx] = 0.0

        self._update_vu()

    def _update_vu(self):
        if not self._running:
            return
        for idx, bar in self._vu_bars.items():
            rms = self._levels.get(idx, 0.0)
            # Decay
            self._levels[idx] = rms * 0.85
            # dB → visuel
            if rms > 1e-6:
                import math
                db = 20 * math.log10(rms)
                level = max(0.0, min(1.0, (db + 60) / 60))
            else:
                level = 0.0

            bar.delete("all")
            w = bar.winfo_width() or 100
            h = bar.winfo_height() or 14
            bar.create_rectangle(0, 0, w, h, fill="#222233", outline="")
            if level > 0.01:
                color = "#00cc44" if level < 0.7 else ("#ffcc00" if level < 0.9 else "#ff3333")
                bar.create_rectangle(0, 0, int(w * level), h, fill=color, outline="")

            lbl = self._vu_vars.get(idx)
            if lbl:
                lbl.config(text=f"{level*100:.0f}%")

        self.after(50, self._update_vu)

    # ──────────────────────────────────────────────────────────────────
    # Test de sortie : joue un bip
    # ──────────────────────────────────────────────────────────────────

    def _play_beep(self, device_idx):
        if not SD_OK:
            return

        status = self._status_vars.get(device_idx)
        if status:
            status.set("▶ bip...")

        def _do():
            try:
                import sounddevice as sd
                sr = 44100
                t = np.linspace(0, 0.6, int(sr * 0.6), endpoint=False)
                # Bip 880 Hz avec fondu
                wave = np.sin(2 * np.pi * 880 * t).astype(np.float32)
                fade = np.ones_like(wave)
                fade_len = sr // 10
                fade[:fade_len] = np.linspace(0, 1, fade_len)
                fade[-fade_len:] = np.linspace(1, 0, fade_len)
                wave *= fade * 0.5

                # Essaie en stéréo, fallback mono
                try:
                    stereo = np.column_stack([wave, wave])
                    sd.play(stereo, samplerate=sr, device=device_idx, blocking=True)
                except Exception:
                    sd.play(wave, samplerate=sr, device=device_idx, blocking=True)

                if status:
                    self.after(0, lambda: status.set("✓"))
                    self.after(2000, lambda: status.set(""))
            except Exception as e:
                if status:
                    self.after(0, lambda: status.set("❌"))
                print(f"[DeviceTester] Bip erreur device {device_idx}: {e}")

        threading.Thread(target=_do, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────

    def _on_close(self):
        self._running = False
        for s in self._input_streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._input_streams.clear()
        self.destroy()


class VoiceTab(tk.Frame):
    def __init__(self, parent, app, **kw):
        super().__init__(parent, bg="#13131f", **kw)
        self.app = app
        self._section_widgets: dict = {}  # name -> CollapsibleSection
        self._param_sliders: dict = {}    # (name, param) -> ParamSlider
        self._build()

    def _build(self):
        # ── Top controls ──────────────────────────────────────────────
        top = tk.Frame(self, bg="#13131f")
        top.pack(fill="x", padx=8, pady=6)

        # Devices
        dev_frame = tk.LabelFrame(top, text=" Périphériques ", bg="#13131f", fg="#8888cc",
                                   font=("Segoe UI", 8), bd=1, relief="solid")
        dev_frame.pack(side="left", padx=4, fill="y")

        def dev_label(row, text, color="#aaaaaa"):
            tk.Label(dev_frame, text=text, bg="#13131f", fg=color,
                     font=("Segoe UI", 8)).grid(row=row, column=0, sticky="w", padx=4)

        def dev_menu(row, var):
            m = tk.OptionMenu(dev_frame, var, "Défaut")
            m.config(bg="#2a2a3a", fg="#ffffff", font=("Segoe UI", 8),
                     activebackground="#3a3a4a", highlightthickness=0)
            m["menu"].config(bg="#2a2a3a", fg="#ffffff")
            m.grid(row=row, column=1, padx=4, pady=1, sticky="w")
            return m

        dev_label(0, "🎙 Micro (entrée):", "#aaffaa")
        self.in_dev_var = tk.StringVar(value="Défaut")
        self.in_dev_menu = dev_menu(0, self.in_dev_var)

        dev_label(1, "🔌 Câble virtuel (sortie):", "#ffaa66")
        self.out_dev_var = tk.StringVar(value="Défaut")
        self.out_dev_menu = dev_menu(1, self.out_dev_var)

        dev_label(2, "🔊 Haut-parleurs (monitor):", "#66aaff")
        self.monitor_dev_var = tk.StringVar(value="Défaut")
        self.monitor_dev_menu = dev_menu(2, self.monitor_dev_var)

        btn_row_dev = tk.Frame(dev_frame, bg="#13131f")
        btn_row_dev.grid(row=3, column=0, columnspan=2, pady=4)

        tk.Button(btn_row_dev, text="⟳ Appliquer", command=self._apply_devices,
                  bg="#2244aa", fg="white", font=("Segoe UI", 8), bd=0, padx=6, pady=2
                  ).pack(side="left", padx=2)

        self._audio_status = tk.Label(btn_row_dev, text="⏹ Arrêté", bg="#13131f",
                                       fg="#ff6666", font=("Segoe UI", 8, "bold"))
        self._audio_status.pack(side="left", padx=4)

        # Buffer size
        buf_frame = tk.LabelFrame(top, text=" Latence ", bg="#13131f", fg="#8888cc",
                                   font=("Segoe UI", 8), bd=1, relief="solid")
        buf_frame.pack(side="left", padx=4, fill="y")
        self.buf_var = tk.StringVar(value="1024")
        for buf in ["256", "512", "1024", "2048", "4096"]:
            tk.Radiobutton(buf_frame, text=buf, variable=self.buf_var, value=buf,
                           bg="#13131f", fg="#aaaaaa", selectcolor="#2a2a3a",
                           activebackground="#13131f", font=("Segoe UI", 8),
                           command=self._apply_buffer
                           ).pack(side="left", padx=2)

        # Volumes
        vol_frame = tk.LabelFrame(top, text=" Volume ", bg="#13131f", fg="#8888cc",
                                   font=("Segoe UI", 8), bd=1, relief="solid")
        vol_frame.pack(side="left", padx=4, fill="y")

        tk.Label(vol_frame, text="Entrée", bg="#13131f", fg="#aaaaaa",
                 font=("Segoe UI", 8)).grid(row=0, column=0)
        self.in_vol_var = tk.DoubleVar(value=1.0)
        tk.Scale(vol_frame, from_=0.0, to=3.0, orient="horizontal", variable=self.in_vol_var,
                 resolution=0.01, bg="#13131f", fg="#aaaaaa", length=100, showvalue=False,
                 command=lambda v: self._set_volume("in", float(v))
                 ).grid(row=1, column=0, padx=4)

        tk.Label(vol_frame, text="Sortie", bg="#13131f", fg="#aaaaaa",
                 font=("Segoe UI", 8)).grid(row=0, column=1)
        self.out_vol_var = tk.DoubleVar(value=1.0)
        tk.Scale(vol_frame, from_=0.0, to=2.0, orient="horizontal", variable=self.out_vol_var,
                 resolution=0.01, bg="#13131f", fg="#aaaaaa", length=100, showvalue=False,
                 command=lambda v: self._set_volume("out", float(v))
                 ).grid(row=1, column=1, padx=4)

        # ── Sensibilité micro (style Discord) ─────────────────────────
        sens_frame = tk.LabelFrame(top, text=" Sensibilité micro ", bg="#13131f", fg="#8888cc",
                                    font=("Segoe UI", 8), bd=1, relief="solid")
        sens_frame.pack(side="left", padx=4, fill="y")

        # Barre de niveau + marqueur de seuil
        self._sens_canvas = tk.Canvas(sens_frame, width=190, height=16, bg="#1a1a2a",
                                       highlightthickness=1, highlightbackground="#333355")
        self._sens_canvas.pack(padx=4, pady=(6, 2))

        self._sens_var = tk.DoubleVar(value=0.0)
        tk.Scale(sens_frame, from_=0, to=100, orient="horizontal", variable=self._sens_var,
                 resolution=1, bg="#13131f", fg="#aaaaaa", showvalue=False, highlightthickness=0,
                 length=190, command=self._on_sensitivity).pack(padx=4, pady=(0, 4))

        tk.Label(sens_frame, text="◄ Sensible    Strict ►", bg="#13131f", fg="#555577",
                 font=("Segoe UI", 7)).pack()

        # Bypass + Monitoring
        ctrl_frame = tk.Frame(top, bg="#13131f")
        ctrl_frame.pack(side="left", padx=8, fill="y")

        self.bypass_var = tk.BooleanVar(value=False)
        bypass_btn = tk.Checkbutton(
            ctrl_frame, text="⊘ BYPASS", variable=self.bypass_var,
            command=self._toggle_bypass,
            bg="#13131f", fg="#ff6666", selectcolor="#2a1a1a",
            activebackground="#13131f", activeforeground="#ff6666",
            font=("Segoe UI", 10, "bold"), pady=4
        )
        bypass_btn.pack(anchor="w")

        self.monitor_var = tk.BooleanVar(value=False)
        monitor_btn = tk.Checkbutton(
            ctrl_frame, text="🎧 S'entendre", variable=self.monitor_var,
            command=self._toggle_monitoring,
            bg="#13131f", fg="#66aaff", selectcolor="#1a1a2a",
            activebackground="#13131f", font=("Segoe UI", 9), pady=4
        )
        monitor_btn.pack(anchor="w")

        tk.Button(ctrl_frame, text="? Guide routing", command=self._show_routing_guide,
                  bg="#2a2240", fg="#aaaaff", font=("Segoe UI", 8),
                  bd=0, padx=6, pady=2, cursor="hand2").pack(anchor="w", pady=(4, 0))

        tk.Button(ctrl_frame, text="🔍 Tester périphériques",
                  command=lambda: DeviceTester(self),
                  bg="#1a2a1a", fg="#88ff88", font=("Segoe UI", 8),
                  bd=0, padx=6, pady=2, cursor="hand2").pack(anchor="w", pady=(2, 0))

        # VU-mètres
        vu_frame = tk.Frame(top, bg="#13131f")
        vu_frame.pack(side="right", padx=8)
        tk.Label(vu_frame, text="IN", bg="#13131f", fg="#888888",
                 font=("Consolas", 7)).grid(row=0, column=0)
        tk.Label(vu_frame, text="OUT", bg="#13131f", fg="#888888",
                 font=("Consolas", 7)).grid(row=0, column=1)
        self.vu_in = VUMeter(vu_frame, width=24, height=80)
        self.vu_in.grid(row=1, column=0, padx=4)
        self.vu_out = VUMeter(vu_frame, width=24, height=80)
        self.vu_out.grid(row=1, column=1, padx=4)

        # ── Prebuilts ─────────────────────────────────────────────────────
        pre_outer = tk.Frame(self, bg="#13131f")
        pre_outer.pack(fill="x", padx=8, pady=(0, 4))

        _ROW1 = [   # effets & neutres
            ("🎤 Normal",    []),
            ("🐭 Chipmunk",  [("Helium",        {"amount": 0.85})]),
            ("📈 Aiguë",     [("Pitch Shifter", {"semitones":  5.0})]),
            ("🤖 Robot",     [("Ring Modulator", {"frequency": 90.0,  "mix": 0.85}),
                              ("Reverb",         {"room_size": 0.3, "damping": 0.4, "wet_dry": 0.2})]),
            ("👽 Alien",     [("Pitch Shifter",  {"semitones": 4.0}),
                              ("Ring Modulator", {"frequency": 150.0, "mix": 0.55}),
                              ("Reverb",         {"room_size": 0.4, "damping": 0.4, "wet_dry": 0.2})]),
            ("📞 Tél.",      [("Telephone Filter", {"low_cut": 300.0, "high_cut": 3400.0, "distortion": 0.3})]),
            ("📻 Radio",     [("Radio Effect",   {"noise_level": 0.04, "bandwidth": 0.5})]),
            ("🌊 Sous-marin",[("Underwater",     {"depth": 0.8, "wobble": 0.4, "wobble_rate": 2.0})]),
            ("📢 Mégaphone", [("Megaphone",      {"drive": 8.0, "mid_boost_db": 10.0})]),
            ("👻 Fantôme",   [("Pitch Shifter",  {"semitones": -3.0}),
                              ("Whisper",         {"intensity": 0.7}),
                              ("Reverb",          {"room_size": 0.9, "damping": 0.3, "wet_dry": 0.5})]),
        ]
        _ROW2 = [   # voix graves
            ("📉 Grave",      [("Pitch Shifter", {"semitones": -4.0})]),
            ("📉📉 Profond",   [("Pitch Shifter", {"semitones": -7.0}),
                               ("Octave Doubler", {"octave": -1, "mix": 0.18})]),
            ("🗿 Titan",      [("Pitch Shifter", {"semitones": -10.0}),
                               ("Octave Doubler", {"octave": -1, "mix": 0.28})]),
            ("😈 Démon",      [("Pitch Shifter", {"semitones": -8.0}),
                               ("Growl",          {"drive": 4.0, "freq": 80.0, "mix": 0.6}),
                               ("Reverb",         {"room_size": 0.6, "damping": 0.5, "wet_dry": 0.25})]),
            ("🐉 Dragon",     [("Pitch Shifter", {"semitones": -6.0}),
                               ("Distortion",     {"drive": 3.0, "tone": 0.3, "mix": 0.4}),
                               ("Reverb",         {"room_size": 0.7, "damping": 0.4, "wet_dry": 0.3})]),
            ("🌑 Abyssal",    [("Pitch Shifter", {"semitones": -12.0}),
                               ("Growl",          {"drive": 6.0, "freq": 60.0, "mix": 0.7}),
                               ("Reverb",         {"room_size": 0.9, "damping": 0.6, "wet_dry": 0.4})]),
        ]

        self._active_preset_btn = None

        def _make_preset_btn(parent, label, cfg, row2=False):
            btn = tk.Button(
                parent, text=label,
                bg="#1a1a2e" if label == "🎤 Normal" else ("#1e1228" if row2 else "#1c1c2e"),
                fg="#ffcc44" if label == "🎤 Normal" else ("#ff8866" if row2 else "#ccccff"),
                activebackground="#2a2a4a", activeforeground="white",
                font=("Segoe UI", 8), bd=0, padx=6, pady=3,
                cursor="hand2", relief="flat",
            )
            def _on_click(c=cfg, b=btn):
                if self._active_preset_btn and self._active_preset_btn.winfo_exists():
                    self._active_preset_btn.config(relief="flat", bd=0)
                b.config(relief="solid", bd=1)
                self._active_preset_btn = b
                self._apply_preset(c)
            btn.config(command=_on_click)
            return btn

        row1_lf = tk.LabelFrame(pre_outer, text=" ⚡ Effets ",
                                bg="#13131f", fg="#aaaaff",
                                font=("Segoe UI", 8, "bold"), bd=1, relief="solid")
        row1_lf.pack(fill="x", pady=(0, 2))
        for label, cfg in _ROW1:
            _make_preset_btn(row1_lf, label, cfg).pack(side="left", padx=2, pady=3)

        row2_lf = tk.LabelFrame(pre_outer, text=" 🔉 Voix graves ",
                                bg="#13131f", fg="#ff8866",
                                font=("Segoe UI", 8, "bold"), bd=1, relief="solid")
        row2_lf.pack(fill="x")
        for label, cfg in _ROW2:
            _make_preset_btn(row2_lf, label, cfg, row2=True).pack(side="left", padx=2, pady=3)

        # ── Scrollable effects area ────────────────────────────────────
        effects_outer = tk.Frame(self, bg="#13131f")
        effects_outer.pack(fill="both", expand=True, padx=8, pady=4)

        canvas = tk.Canvas(effects_outer, bg="#13131f", highlightthickness=0)
        scrollbar = tk.Scrollbar(effects_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._effects_frame = tk.Frame(canvas, bg="#13131f")
        canvas_window = canvas.create_window((0, 0), window=self._effects_frame, anchor="nw")

        def on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_window, width=canvas.winfo_width())
        self._effects_frame.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        self._effects_canvas = canvas

        self._build_effects_sections()

    def _setup_scroll(self):
        """Bind la molette à tous les widgets de la zone effets (récursif)."""
        c = self._effects_canvas
        def _scroll(e):
            c.yview_scroll(int(-1 * (e.delta / 120)), "units")
        def _bind(widget):
            widget.bind("<MouseWheel>", _scroll)
            for child in widget.winfo_children():
                _bind(child)
        _bind(c)

    def _build_effects_sections(self):
        ec = self.app.effects_chain
        for effect in ec.effects:
            section = CollapsibleSection(self._effects_frame, effect.name)
            section.pack(fill="x", pady=2)
            section.enabled_var.set(effect.enabled)
            section.enabled_var.trace_add("write", lambda *a, e=effect, s=section: self._toggle_effect(e, s))
            self._section_widgets[effect.name] = section
            self._build_effect_params(effect, section.content)
        self.after(100, self._setup_scroll)

    def _build_effect_params(self, effect, parent):
        meta = EFFECT_PARAMS_META.get(effect.name)

        if effect.name == "10-Band EQ":
            self._build_eq(effect, parent)
            return

        if not meta:
            tk.Label(parent, text="(pas de paramètres)", bg="#1e1e2e", fg="#666666",
                     font=("Segoe UI", 8)).pack(padx=8, pady=4)
            return

        for entry in meta:
            param_key, label, from_, to_, fmt = entry[:5]
            desc = entry[5] if len(entry) > 5 else ""
            initial = effect.params.get(param_key, (from_ + to_) / 2)

            def on_change(v, eff=effect, key=param_key):
                eff.params[key] = v

            slider = ParamSlider(parent, label, from_, to_, initial, on_change, fmt, desc=desc)
            slider.pack(fill="x", padx=8, pady=1)
            self._param_sliders[(effect.name, param_key)] = slider

    def _build_eq(self, effect, parent):
        eq_frame = tk.Frame(parent, bg="#1e1e2e")
        eq_frame.pack(fill="x", padx=4, pady=4)
        for i, freq in enumerate(EQ_BANDS):
            col = tk.Frame(eq_frame, bg="#1e1e2e")
            col.grid(row=0, column=i, padx=2)
            param = f"band_{freq}"
            var = tk.DoubleVar(value=effect.params.get(param, 0.0))

            def on_change(v, eff=effect, p=param):
                eff.params[p] = float(v)

            lbl = "16k" if freq >= 16000 else (f"{freq//1000}k" if freq >= 1000 else str(freq))
            tk.Label(col, text=lbl, bg="#1e1e2e", fg="#999999",
                     font=("Consolas", 7)).pack()
            tk.Scale(col, from_=12, to=-12, variable=var, orient="vertical",
                     length=100, resolution=0.5, bg="#1e1e2e", fg="#aaaaaa",
                     showvalue=False, command=on_change,
                     troughcolor="#2a2a3a", highlightthickness=0
                     ).pack()
            tk.Label(col, textvariable=var, bg="#1e1e2e", fg="#888888",
                     font=("Consolas", 6)).pack()
            self._param_sliders[(effect.name, param)] = var

    def _toggle_effect(self, effect, section):
        effect.enabled = section.enabled_var.get()

    def _toggle_bypass(self):
        self.app.effects_chain.bypass_all = self.bypass_var.get()

    def _toggle_monitoring(self):
        self.app.audio_engine.monitoring = self.monitor_var.get()
        # Si le stream monitor n'existe pas encore, le créer à la volée
        if self.monitor_var.get() and self.app.audio_engine._monitor_stream is None:
            self.app.audio_engine.restart_monitor()

    def _on_sensitivity(self, val):
        """Contrôle de sensibilité style Discord — pilote le Noise Gate."""
        v = float(val)
        for e in self.app.effects_chain.effects:
            if e.name == "Noise Gate":
                if v < 1.0:
                    e.enabled = False
                else:
                    # 1 → -59 dB (tout passe), 100 → -10 dB (seulement les sons forts)
                    e.params["threshold_db"] = -60.0 + v * 0.5
                    e.enabled = True
                break

    def update_sensitivity(self, rms: float):
        """Redessine la barre de niveau + marqueur de seuil."""
        import math
        c = self._sens_canvas
        c.update_idletasks()
        w = c.winfo_width() or 190
        h = c.winfo_height() or 16
        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill="#1a1a2a", outline="")

        if rms > 1e-9:
            db = 20 * math.log10(rms)
            level = max(0.0, min(1.0, (db + 60) / 60))
        else:
            level = 0.0

        thresh_norm = self._sens_var.get() / 100.0
        thresh_x    = int(w * thresh_norm)
        level_x     = int(w * level)

        if level_x > 0:
            if level > thresh_norm and thresh_norm > 0:
                # La partie sous le seuil = grise, au-dessus = verte
                if thresh_x > 0:
                    c.create_rectangle(0, 2, thresh_x, h - 2, fill="#334455", outline="")
                c.create_rectangle(thresh_x, 2, level_x, h - 2, fill="#44cc44", outline="")
            elif thresh_norm == 0.0:
                # Pas de seuil → toujours vert
                c.create_rectangle(0, 2, level_x, h - 2, fill="#44cc44", outline="")
            else:
                # Sous le seuil → gris
                c.create_rectangle(0, 2, level_x, h - 2, fill="#334455", outline="")

        # Marqueur de seuil (ligne blanche verticale)
        if thresh_x > 0:
            c.create_line(thresh_x, 0, thresh_x, h, fill="white", width=2)

    def _apply_devices(self):
        idx_in = self.app._in_device_map.get(self.in_dev_var.get())
        idx_out = self.app._out_device_map.get(self.out_dev_var.get())
        idx_mon = self.app._out_device_map.get(self.monitor_dev_var.get())
        self.app.audio_engine.input_device = idx_in
        self.app.audio_engine.output_device = idx_out
        self.app.audio_engine.monitor_device = idx_mon
        self.app.audio_engine.restart()
        # Transmettre les périphériques au soundboard
        self.app.soundboard_manager.speakers_device = idx_mon
        self.app.soundboard_manager.virtual_device  = idx_out
        self._update_audio_status()

    def _update_audio_status(self):
        if self.app.audio_engine._running:
            self._audio_status.config(text="▶ Actif", fg="#44ff88")
        else:
            self._audio_status.config(text="⏹ Arrêté", fg="#ff6666")

    def _show_routing_guide(self):
        win = tk.Toplevel(self)
        win.title("Guide : faire entendre les effets aux autres")
        win.configure(bg="#0d0d1a")
        win.geometry("520x400")
        win.resizable(False, False)

        guide = (
            "══════════════════════════════════════════════\n"
            "  GUIDE : Que les autres entendent vos effets\n"
            "══════════════════════════════════════════════\n\n"
            "ÉTAPE 1 — Installer VB-Audio Virtual Cable\n"
            "  → Télécharger sur : vb-audio.com/Cable\n"
            "  → Installer et REDÉMARRER Windows\n\n"
            "ÉTAPE 2 — Configurer Bissap Voice Changer\n"
            "  🎙 Micro (entrée)     : votre vrai micro\n"
            "  🔌 Câble virtuel (sortie) : CABLE Input (VB-Audio)\n"
            "  🔊 Haut-parleurs (monitor): vos écouteurs/HP\n"
            "  → Cliquer ⟳ Appliquer\n\n"
            "ÉTAPE 3 — Configurer Discord / Teams / OBS\n"
            "  → Dans Discord : Paramètres > Voix >\n"
            "    Micro d'entrée = CABLE Output (VB-Audio)\n"
            "  → Dans OBS : Source audio >\n"
            "    Périphérique = CABLE Output (VB-Audio)\n\n"
            "ÉTAPE 4 — Activer 'S'entendre'\n"
            "  → Cochée : vous vous entendez avec les effets\n"
            "  → Décochée : les autres entendent, pas vous\n\n"
            "══════════════════════════════════════════════\n"
            "  Le câble virtuel = tuyau invisible entre\n"
            "  cette app et Discord/Teams/OBS\n"
            "══════════════════════════════════════════════"
        )

        txt = tk.Text(win, bg="#0d0d1a", fg="#ccccee", font=("Consolas", 9),
                      bd=0, padx=16, pady=12, wrap="word", state="normal")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", guide)
        txt.config(state="disabled")

        tk.Button(win, text="Fermer", command=win.destroy,
                  bg="#2244aa", fg="white", bd=0, padx=20, pady=6,
                  font=("Segoe UI", 9)).pack(pady=8)

    def _apply_buffer(self):
        try:
            buf = int(self.buf_var.get())
            self.app.audio_engine.buffer_size = buf
            self.app.audio_engine.restart()
        except ValueError:
            pass

    def _set_volume(self, which: str, val: float):
        if which == "in":
            self.app.audio_engine.input_volume = val
        else:
            self.app.audio_engine.output_volume = val

    def refresh_devices(self, in_devices, out_devices):
        def label(d):
            return f"[{d['index']}] {d['name']}"

        def fill_menu(menu_widget, var, items, add_default=True):
            m = menu_widget["menu"]
            m.delete(0, "end")
            if add_default:
                m.add_command(label="Défaut", command=lambda: var.set("Défaut"))
            for d in items:
                lbl = label(d)
                m.add_command(label=lbl, command=lambda n=lbl, v=var: v.set(n))

        fill_menu(self.in_dev_menu, self.in_dev_var, in_devices)
        fill_menu(self.out_dev_menu, self.out_dev_var, out_devices)
        fill_menu(self.monitor_dev_menu, self.monitor_dev_var, out_devices)

        # Restaurer les périphériques sauvegardés
        saved_in  = self.app.config.get("in_device_name", "")
        saved_out = self.app.config.get("out_device_name", "")
        saved_mon = self.app.config.get("monitor_device_name", "")

        all_in_labels  = [label(d) for d in in_devices]
        all_out_labels = [label(d) for d in out_devices]

        if saved_in and saved_in in all_in_labels:
            self.in_dev_var.set(saved_in)
        if saved_out and saved_out in all_out_labels:
            self.out_dev_var.set(saved_out)
        elif not saved_out:
            # Auto-sélectionner le câble VB-Audio s'il est détecté (premier lancement)
            for d in out_devices:
                if "cable" in d["name"].lower() or "vb-audio" in d["name"].lower():
                    self.out_dev_var.set(label(d))
                    break
        if saved_mon and saved_mon in all_out_labels:
            self.monitor_dev_var.set(saved_mon)

    def _apply_preset(self, effects_config: list):
        """Désactive tout puis active les effets du preset avec leurs paramètres."""
        chain = self.app.effects_chain
        with chain._lock:
            for e in chain.effects:
                e.enabled = False
            for name, params in effects_config:
                for e in chain.effects:
                    if e.name == name:
                        e.enabled = True
                        for k, v in params.items():
                            if k in e.params:
                                e.params[k] = v
                        break
        self.sync_from_chain()

    def sync_from_chain(self):
        """Synchronise les widgets UI depuis la chaîne d'effets (chargement profil)."""
        for effect in self.app.effects_chain.effects:
            sec = self._section_widgets.get(effect.name)
            if sec:
                sec.enabled_var.set(effect.enabled)
            meta = EFFECT_PARAMS_META.get(effect.name)
            if meta and effect.name != "10-Band EQ":
                for param_key, *_ in meta:
                    slider = self._param_sliders.get((effect.name, param_key))
                    if slider and isinstance(slider, ParamSlider):
                        slider.set(effect.params.get(param_key, 0))
            if effect.name == "10-Band EQ":
                for freq in EQ_BANDS:
                    param = f"band_{freq}"
                    var = self._param_sliders.get((effect.name, param))
                    if var and isinstance(var, tk.DoubleVar):
                        var.set(effect.params.get(param, 0.0))


# ──────────────────────────────────────────────────────────────────────────────
# Onglet Profils
# ──────────────────────────────────────────────────────────────────────────────

class ProfilesTab(tk.Frame):
    def __init__(self, parent, app, **kw):
        super().__init__(parent, bg="#13131f", **kw)
        self.app = app
        self._selected = None
        self._hotkeys: dict = {}  # name -> hooked hotkey
        self._build()

    def _build(self):
        # Header buttons
        btn_row = tk.Frame(self, bg="#13131f")
        btn_row.pack(fill="x", padx=8, pady=6)

        def btn(parent, text, cmd, color="#1f5fa6"):
            b = tk.Button(parent, text=text, command=cmd,
                          bg=color, fg="white", font=("Segoe UI", 9),
                          bd=0, padx=10, pady=4, cursor="hand2",
                          activebackground="#2a70b8", activeforeground="white")
            b.pack(side="left", padx=3)
            return b

        btn(btn_row, "💾 Sauvegarder comme profil", self._save_profile, "#1f6a30")
        btn(btn_row, "📂 Charger profil", self._load_selected)
        btn(btn_row, "🗑 Supprimer", self._delete_selected, "#6a1f1f")
        btn(btn_row, "📤 Exporter JSON", self._export_selected, "#4a4a1f")
        btn(btn_row, "📥 Importer JSON", self._import_profile, "#1f4a6a")
        btn(btn_row, "⊘ Désactiver tous", self._deactivate_all, "#333355")

        self._hk_enabled = True
        self._hk_toggle_btn = tk.Button(
            btn_row, text="⌨ Raccourcis ON",
            command=self._toggle_hotkeys,
            bg="#1a3a1a", fg="#88ff88",
            font=("Segoe UI", 9), bd=0, padx=8, pady=4, cursor="hand2",
            activebackground="#2a4a2a"
        )
        self._hk_toggle_btn.pack(side="left", padx=3)

        # Split view
        content = tk.Frame(self, bg="#13131f")
        content.pack(fill="both", expand=True, padx=8)

        # Profile list
        list_frame = tk.LabelFrame(content, text=" Profils ", bg="#13131f", fg="#8888cc",
                                    font=("Segoe UI", 9), bd=1, relief="solid")
        list_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))

        lb_container = tk.Frame(list_frame, bg="#1a1a2e")
        lb_container.pack(fill="both", expand=True, padx=4, pady=4)

        lb_scroll = tk.Scrollbar(lb_container, orient="vertical")
        lb_scroll.pack(side="right", fill="y")

        self._listbox = tk.Listbox(
            lb_container, bg="#1a1a2e", fg="#ddddff", selectbackground="#2244aa",
            font=("Segoe UI", 10), activestyle="none", bd=0, highlightthickness=0,
            yscrollcommand=lb_scroll.set
        )
        self._listbox.pack(side="left", fill="both", expand=True)
        lb_scroll.config(command=self._listbox.yview)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)
        self._listbox.bind("<Double-Button-1>", lambda e: self._load_selected())
        self._listbox.bind("<MouseWheel>", lambda e: self._listbox.yview_scroll(
            int(-1 * (e.delta / 120)), "units"))

        # Detail / shortcut panel
        detail_frame = tk.LabelFrame(content, text=" Détails du profil ", bg="#13131f",
                                      fg="#8888cc", font=("Segoe UI", 9), bd=1, relief="solid",
                                      width=280)
        detail_frame.pack(side="left", fill="y", padx=(4, 0))
        detail_frame.pack_propagate(False)

        tk.Label(detail_frame, text="Raccourci clavier :", bg="#13131f", fg="#aaaaaa",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=(12, 2))

        sc_row = tk.Frame(detail_frame, bg="#13131f")
        sc_row.pack(fill="x", padx=8)
        self.shortcut_var = tk.StringVar()
        self.shortcut_entry = tk.Entry(sc_row, textvariable=self.shortcut_var,
                                        bg="#2a2a3a", fg="#ffffff", insertbackground="white",
                                        font=("Consolas", 10), bd=1, relief="solid")
        self.shortcut_entry.pack(side="left", fill="x", expand=True)
        tk.Button(sc_row, text="✓", command=self._apply_shortcut,
                  bg="#1f5fa6", fg="white", bd=0, padx=6, cursor="hand2"
                  ).pack(side="left", padx=(4, 0))

        tk.Label(detail_frame, text="(ex: f1, ctrl+shift+1)", bg="#13131f",
                 fg="#666688", font=("Segoe UI", 7, "italic")).pack(anchor="w", padx=8)

        self._active_label = tk.Label(detail_frame, text="", bg="#13131f", fg="#88ff88",
                                       font=("Segoe UI", 10, "bold"))
        self._active_label.pack(pady=12)

        self._refresh_list()

    def _refresh_list(self):
        self._listbox.delete(0, "end")
        for p in self.app.profile_manager.list_profiles():
            name = p["name"]
            sc = p.get("shortcut", "")
            active = (name == self.app.profile_manager.active_profile)
            display = f"{'★ ' if active else '  '}{name}"
            if sc:
                display += f"  [{sc}]"
            self._listbox.insert("end", display)
            if active:
                self._listbox.itemconfig("end", fg="#88ff88")

    def _on_select(self, event=None):
        sel = self._listbox.curselection()
        if not sel:
            return
        profiles = self.app.profile_manager.list_profiles()
        if sel[0] < len(profiles):
            self._selected = profiles[sel[0]]["name"]
            sc = profiles[sel[0]].get("shortcut", "")
            self.shortcut_var.set(sc)

    def _save_profile(self):
        name = simpledialog.askstring("Nouveau profil", "Nom du profil :",
                                       parent=self, initialvalue="Mon profil")
        if not name:
            return
        effects_dict = self.app.effects_chain.to_dict()
        sc = self.shortcut_var.get() if self._selected == name else ""
        self.app.profile_manager.save_profile(name, effects_dict, sc)
        self._refresh_list()

    def _load_selected(self):
        if not self._selected:
            return
        profile = self.app.profile_manager.get_profile(self._selected)
        if not profile:
            return
        self.app.effects_chain.from_dict(profile.get("effects", []))
        self.app.effects_chain.reset_all()
        self.app.profile_manager.set_active(self._selected)
        self.app.voice_tab.sync_from_chain()
        self._refresh_list()
        self._active_label.config(text=f"✓ Actif : {self._selected}")

    def _delete_selected(self):
        if not self._selected:
            return
        if messagebox.askyesno("Supprimer", f"Supprimer le profil « {self._selected} » ?",
                                parent=self):
            self._unhook(self._selected)
            self.app.profile_manager.delete_profile(self._selected)
            self._selected = None
            self._refresh_list()
            self._active_label.config(text="")

    def _export_selected(self):
        if not self._selected:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialfile=f"{self._selected}.json", parent=self
        )
        if path:
            self.app.profile_manager.export_profile(self._selected, path)

    def _import_profile(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("Tous", "*.*")], parent=self
        )
        if path:
            name = self.app.profile_manager.import_profile(path)
            if name:
                self._refresh_list()
            else:
                messagebox.showerror("Erreur", "Impossible d'importer le profil.", parent=self)

    def _deactivate_all(self):
        self.app.profile_manager.set_active(None)
        self._active_label.config(text="")
        self._refresh_list()

    def _apply_shortcut(self):
        if not self._selected:
            return
        sc = self.shortcut_var.get().strip()
        self._unhook(self._selected)
        self.app.profile_manager.update_shortcut(self._selected, sc)
        if sc and KB_OK:
            name = self._selected

            def activate():
                self._selected = name
                self._load_selected()

            try:
                self._hotkeys[name] = sc
                kb.add_hotkey(sc, activate)
            except Exception as e:
                print(f"[Profiles] Erreur hotkey '{sc}': {e}")
        self._refresh_list()

    def _unhook(self, name: str):
        if not KB_OK:
            return
        sc = self._hotkeys.pop(name, None)
        if sc:
            try:
                kb.remove_hotkey(sc)
            except Exception:
                pass

    def _toggle_hotkeys(self):
        self._hk_enabled = not self._hk_enabled
        if self._hk_enabled:
            self.setup_all_hotkeys()
            self._hk_toggle_btn.config(text="⌨ Raccourcis ON",  bg="#1a3a1a", fg="#88ff88")
        else:
            for sc in list(self._hotkeys.values()):
                try: kb.remove_hotkey(sc)
                except Exception: pass
            self._hotkeys.clear()
            self._hk_toggle_btn.config(text="⌨ Raccourcis OFF", bg="#3a1a1a", fg="#ff8888")

    def setup_all_hotkeys(self):
        """Enregistre tous les raccourcis au démarrage."""
        if not KB_OK or not self._hk_enabled:
            return
        for p in self.app.profile_manager.list_profiles():
            name = p["name"]
            sc = p.get("shortcut", "").strip()
            if sc:
                try:
                    self._hotkeys[name] = sc
                    kb.add_hotkey(sc, lambda n=name: self._activate_by_name(n))
                except Exception as e:
                    print(f"[Profiles] Hotkey '{sc}': {e}")

    def _activate_by_name(self, name: str):
        self._selected = name
        self._load_selected()


# ──────────────────────────────────────────────────────────────────────────────
# Onglet Soundboard
# ──────────────────────────────────────────────────────────────────────────────

class SoundboardTab(tk.Frame):
    COLS = 6

    def __init__(self, parent, app, **kw):
        super().__init__(parent, bg="#13131f", **kw)
        self.app = app
        self._slot_frames: list = []
        self._hotkeys: dict = {}
        # Polling hotkeys
        self._sb_map: dict = {}
        self._sb_armed: set = set()
        self._polling = False
        self._sb_hk_enabled = True
        self._build()

    def _build(self):
        top = tk.Frame(self, bg="#13131f")
        top.pack(fill="x", padx=8, pady=6)

        def btn(t, cmd, color="#1f5fa6"):
            b = tk.Button(top, text=t, command=cmd, bg=color, fg="white",
                          font=("Segoe UI", 9), bd=0, padx=8, pady=4, cursor="hand2",
                          activebackground="#2a70b8")
            b.pack(side="left", padx=3)
            return b

        btn("➕ Ajouter slot", self._add_slot, "#1f6a30")
        btn("⏹ Stop All", self.app.soundboard_manager.stop_all, "#6a1f1f")

        self.exclusive_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Mode exclusif", variable=self.exclusive_var,
                       command=self._toggle_exclusive,
                       bg="#13131f", fg="#aaaacc", selectcolor="#2a2a3a",
                       activebackground="#13131f", font=("Segoe UI", 9)
                       ).pack(side="left", padx=8)

        self._sb_hk_btn = tk.Button(
            top, text="⌨ Raccourcis ON",
            command=self._toggle_sb_hotkeys,
            bg="#1a3a1a", fg="#88ff88",
            font=("Segoe UI", 9), bd=0, padx=8, pady=4, cursor="hand2",
            activebackground="#2a4a2a"
        )
        self._sb_hk_btn.pack(side="left", padx=3)

        # Grid
        grid_outer = tk.Frame(self, bg="#13131f")
        grid_outer.pack(fill="both", expand=True, padx=8)

        canvas = tk.Canvas(grid_outer, bg="#13131f", highlightthickness=0)
        scrollbar = tk.Scrollbar(grid_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._grid_frame = tk.Frame(canvas, bg="#13131f")
        cw = canvas.create_window((0, 0), window=self._grid_frame, anchor="nw")

        def on_cfg(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(cw, width=canvas.winfo_width())
        self._grid_frame.bind("<Configure>", on_cfg)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        self._build_grid()

    def _build_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._slot_frames.clear()
        sb = self.app.soundboard_manager
        for i, slot in enumerate(sb.slots):
            row, col = divmod(i, self.COLS)
            self._create_slot_widget(slot, row, col)
        # Colonnes égales et extensibles
        for c in range(self.COLS):
            self._grid_frame.columnconfigure(c, weight=1, uniform="col")

    def _create_slot_widget(self, slot, row, col):
        frame = tk.Frame(self._grid_frame, bg=slot.color, bd=2, relief="raised",
                         height=120)
        frame.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
        frame.grid_propagate(False)

        # Name label
        name_lbl = tk.Label(frame, text=slot.name, bg=slot.color, fg="white",
                             font=("Segoe UI", 9, "bold"), wraplength=120)
        name_lbl.pack(pady=(6, 1))

        # File label
        file_name = Path(slot.file_path).name if slot.file_path else "— vide —"
        file_lbl = tk.Label(frame, text=file_name, bg=slot.color, fg="#cccccc",
                             font=("Segoe UI", 7), wraplength=120)
        file_lbl.pack()

        # Shortcut label
        sc_lbl = tk.Label(frame, text=f"[{slot.shortcut}]" if slot.shortcut else "",
                           bg=slot.color, fg="#aaffaa", font=("Consolas", 7))
        sc_lbl.pack()

        # Status/error label
        status_lbl = tk.Label(frame, text="", bg=slot.color, fg="#ff6666",
                               font=("Segoe UI", 7), wraplength=120)
        status_lbl.pack()

        def _on_error(msg):
            status_lbl.config(text=msg, fg="#ff6666")
            frame.after(4000, lambda: status_lbl.config(text=""))

        def _play(s=slot):
            status_lbl.config(text="")
            self.app.soundboard_manager.play(s.index, on_error=_on_error)

        # Buttons row
        btn_row = tk.Frame(frame, bg=slot.color)
        btn_row.pack(fill="x", padx=4, pady=2)

        play_btn = tk.Button(btn_row, text="▶", bg="#2a2a2a", fg="white",
                              font=("Consolas", 9), bd=0, padx=4,
                              command=_play, cursor="hand2")
        play_btn.pack(side="left")

        stop_btn = tk.Button(btn_row, text="⏹", bg="#2a2a2a", fg="white",
                              font=("Consolas", 9), bd=0, padx=4,
                              command=lambda s=slot: self.app.soundboard_manager.stop(s.index),
                              cursor="hand2")
        stop_btn.pack(side="left")

        edit_btn = tk.Button(btn_row, text="✎", bg="#2a2a2a", fg="white",
                              font=("Consolas", 9), bd=0, padx=4,
                              command=lambda s=slot, f=frame: self._edit_slot(s, f),
                              cursor="hand2")
        edit_btn.pack(side="right")

        # Double-clic sur le slot = lecture
        for widget in [frame, name_lbl, file_lbl]:
            widget.bind("<Double-Button-1>", lambda e, fn=_play: fn())

        self._slot_frames.append(frame)

    def _add_slot(self):
        idx = self.app.soundboard_manager.add_slot()
        slot = self.app.soundboard_manager.slots[idx]
        row, col = divmod(idx, self.COLS)
        self._create_slot_widget(slot, row, col)

    def _toggle_exclusive(self):
        self.app.soundboard_manager.exclusive_mode = self.exclusive_var.get()

    def _edit_slot(self, slot, frame):
        win = tk.Toplevel(self)
        win.title(f"Éditer slot : {slot.name}")
        win.configure(bg="#13131f")
        win.geometry("360x360")
        win.grab_set()

        def lbl(text):
            tk.Label(win, text=text, bg="#13131f", fg="#aaaaaa",
                     font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(8, 0))

        def row_entry(var):
            e = tk.Entry(win, textvariable=var, bg="#2a2a3a", fg="white",
                         insertbackground="white", font=("Segoe UI", 10), bd=1, relief="solid")
            e.pack(fill="x", padx=12, pady=2)
            return e

        lbl("Nom :")
        name_var = tk.StringVar(value=slot.name)
        row_entry(name_var)

        lbl("Fichier audio :")
        file_var = tk.StringVar(value=slot.file_path)
        file_row = tk.Frame(win, bg="#13131f")
        file_row.pack(fill="x", padx=12, pady=2)
        tk.Entry(file_row, textvariable=file_var, bg="#2a2a3a", fg="white",
                 insertbackground="white", font=("Segoe UI", 9), bd=1, relief="solid"
                 ).pack(side="left", fill="x", expand=True)
        tk.Button(file_row, text="📁", command=lambda: file_var.set(
            filedialog.askopenfilename(
                filetypes=[("Audio", "*.wav *.mp3 *.ogg *.flac"), ("Tous", "*.*")]
            ) or file_var.get()
        ), bg="#2a2a3a", fg="white", bd=0, padx=4).pack(side="left")

        lbl("Raccourci clavier :")
        sc_var = tk.StringVar(value=slot.shortcut)
        sc_row = tk.Frame(win, bg="#13131f")
        sc_row.pack(fill="x", padx=12, pady=2)
        tk.Entry(sc_row, textvariable=sc_var, bg="#2a2a3a", fg="white",
                 insertbackground="white", font=("Segoe UI", 10), bd=1, relief="solid"
                 ).pack(side="left", fill="x", expand=True)

        def _fmt(keys):
            """Normalise un set de noms de touches → 'ctrl+shift+1'."""
            mods, rest = [], []
            for k in keys:
                k = k.lower().replace('left ', '').replace('right ', '')
                if k in ('ctrl', 'control'):
                    if 'ctrl' not in mods: mods.append('ctrl')
                elif k == 'shift':
                    if 'shift' not in mods: mods.append('shift')
                elif k in ('alt', 'altgr'):
                    if 'alt' not in mods: mods.append('alt')
                else:
                    rest.append(k)
            return '+'.join(mods + rest)

        def _capture():
            if not KB_OK:
                return
            sc_var.set("")
            cap_btn.config(text="Appuie...", state="disabled", fg="#ffaa44")
            keys_held = set()
            best      = ['']
            hooks     = []
            done      = [False]

            def _on_press(e):
                if done[0]:
                    return
                keys_held.add(e.name)
                combo = _fmt(keys_held)
                best[0] = combo
                # thread-safe : màj tkinter depuis le thread principal
                win.after(0, lambda c=combo: sc_var.set(c))

            def _on_release(e):
                if done[0]:
                    return
                done[0] = True
                final = best[0]
                def _finish():
                    if final:
                        sc_var.set(final)
                    for h in hooks:
                        try: kb.unhook(h)
                        except Exception: pass
                    cap_btn.config(text="⌨ Capturer", state="normal", fg="white")
                win.after(0, _finish)   # unhook + màj UI sur le thread tkinter

            hooks.append(kb.on_press(_on_press,   suppress=False))
            hooks.append(kb.on_release(_on_release, suppress=False))

        cap_btn = tk.Button(sc_row, text="⌨ Capturer", command=_capture,
                            bg="#2244aa", fg="white", bd=0, padx=6, font=("Segoe UI", 8))
        cap_btn.pack(side="left", padx=(4, 0))

        lbl(f"Volume : {slot.volume:.2f}")
        vol_var = tk.DoubleVar(value=slot.volume)
        tk.Scale(win, from_=0.0, to=2.0, orient="horizontal", variable=vol_var,
                 resolution=0.01, bg="#13131f", fg="#aaaaaa", length=300
                 ).pack(padx=12)

        # Output options
        opt_frame = tk.Frame(win, bg="#13131f")
        opt_frame.pack(fill="x", padx=12, pady=4)
        sp_var = tk.BooleanVar(value=slot.play_to_speakers)
        mic_var = tk.BooleanVar(value=slot.play_to_mic)
        tk.Checkbutton(opt_frame, text="Haut-parleurs", variable=sp_var,
                       bg="#13131f", fg="#aaaaaa", selectcolor="#2a2a3a",
                       activebackground="#13131f").pack(side="left")
        tk.Checkbutton(opt_frame, text="Micro virtuel", variable=mic_var,
                       bg="#13131f", fg="#aaaaaa", selectcolor="#2a2a3a",
                       activebackground="#13131f").pack(side="left", padx=8)

        def pick_color():
            color = colorchooser.askcolor(color=slot.color, parent=win)[1]
            if color:
                slot.color = color
                frame.configure(bg=color)

        btn_row = tk.Frame(win, bg="#13131f")
        btn_row.pack(fill="x", padx=12, pady=8)

        def save():
            old_sc = slot.shortcut
            slot.name = name_var.get()
            slot.file_path = file_var.get()
            slot.shortcut = sc_var.get().strip()
            slot.volume = vol_var.get()
            slot.play_to_speakers = sp_var.get()
            slot.play_to_mic = mic_var.get()
            # Save to disk
            self.app.config.set("soundboard_slots", self.app.soundboard_manager.to_dict())
            self._build_grid()
            self.register_all_hotkeys()
            win.destroy()

        tk.Button(btn_row, text="Couleur", command=pick_color,
                  bg="#444422", fg="white", bd=0, padx=8, pady=4).pack(side="left")
        tk.Button(btn_row, text="✓ Sauvegarder", command=save,
                  bg="#1f6a30", fg="white", bd=0, padx=12, pady=4).pack(side="right")
        tk.Button(btn_row, text="Annuler", command=win.destroy,
                  bg="#333333", fg="white", bd=0, padx=8, pady=4).pack(side="right", padx=6)

    def load_from_config(self, slots_data: list):
        self.app.soundboard_manager.from_dict(slots_data)
        self._build_grid()
        self.register_all_hotkeys()

    # ── Hotkeys globaux soundboard (polling kb.is_pressed) ─────────────
    # Les hooks on_press sont instables sur Windows pour les combos.
    # kb.is_pressed() utilise GetAsyncKeyState — fiable globalement.

    @staticmethod
    def _is_down(key: str) -> bool:
        """Vérifie si une touche normalisée est enfoncée (gauche ou droite)."""
        try:
            if key == 'ctrl':
                return kb.is_pressed('left ctrl') or kb.is_pressed('right ctrl')
            if key == 'shift':
                return kb.is_pressed('left shift') or kb.is_pressed('right shift')
            if key == 'alt':
                return kb.is_pressed('left alt') or kb.is_pressed('right alt')
            return kb.is_pressed(key)
        except Exception:
            return False

    @staticmethod
    def _sc_to_frozenset(sc: str) -> frozenset:
        out = set()
        for p in sc.lower().split('+'):
            p = p.strip().replace('left ', '').replace('right ', '')
            if p in ('control',): p = 'ctrl'
            if p in ('altgr',):   p = 'alt'
            if p:
                out.add(p)
        return frozenset(out)

    def register_all_hotkeys(self):
        """Reconstruit la table hotkey → slot index."""
        self._sb_map.clear()
        self._sb_armed.clear()
        if not KB_OK:
            return
        for slot in self.app.soundboard_manager.slots:
            raw = slot.shortcut.strip()
            if not raw:
                continue
            fs = self._sc_to_frozenset(raw)
            if fs:
                self._sb_map[fs] = slot.index
                print(f"[Soundboard] Hotkey {set(fs)} → slot {slot.index + 1}")
        if self._sb_map and not self._polling:
            self._polling = True
            self._poll_hotkeys()

    def _toggle_sb_hotkeys(self):
        self._sb_hk_enabled = not self._sb_hk_enabled
        if self._sb_hk_enabled:
            self._sb_hk_btn.config(text="⌨ Raccourcis ON",  bg="#1a3a1a", fg="#88ff88")
        else:
            self._sb_armed.clear()
            self._sb_hk_btn.config(text="⌨ Raccourcis OFF", bg="#3a1a1a", fg="#ff8888")

    def _poll_hotkeys(self):
        """Vérifie toutes les 40 ms si une combinaison est enfoncée."""
        if not KB_OK:
            self._polling = False
            return
        if self._sb_hk_enabled:
            try:
                for combo, idx in list(self._sb_map.items()):
                    all_held = all(self._is_down(k) for k in combo)
                    if all_held and combo not in self._sb_armed:
                        self._sb_armed.add(combo)
                        self._trigger_play(idx)
                    elif not all_held:
                        self._sb_armed.discard(combo)
            except Exception:
                pass
        self.after(40, self._poll_hotkeys)

    def _trigger_play(self, index: int):
        sb = self.app.soundboard_manager
        if sb.speakers_device is None:
            try:
                import sounddevice as _sd
                default_out = _sd.default.device[1]
                sb.speakers_device = default_out if default_out >= 0 else None
            except Exception:
                pass
        sb.play(index)


# ──────────────────────────────────────────────────────────────────────────────
# Application principale
# ──────────────────────────────────────────────────────────────────────────────

class App:
    def __init__(self):
        # Managers
        self.config = ConfigManager()
        self.audio_engine = AudioEngine()
        self.effects_chain = EffectsChain()
        self.profile_manager = ProfileManager()
        self.soundboard_manager = SoundboardManager()

        # Inject effects chain into audio engine
        self.audio_engine.effects_chain = self.effects_chain

        # Device maps (name -> index)
        self._in_device_map: dict = {"Défaut": None}
        self._out_device_map: dict = {"Défaut": None}

        # UI root
        if CTK:
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()

        self._setup_window()
        self._build_ui()
        self._load_config()
        self._start_audio()
        self._start_vu_loop()

    def _setup_window(self):
        self.root.title("Bissap Voice Changer by Groudy")
        geom = self.config.get("window_geometry", "1300x850")
        self.root.geometry(geom)
        self.root.minsize(900, 640)
        self.root.configure(bg="#13131f")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Icône de la fenêtre
        ico = Path(__file__).parent / "bissap.ico"
        if ico.exists():
            try:
                self.root.iconbitmap(str(ico))
            except Exception:
                pass

    def _build_ui(self):
        # Menu bar
        menubar = tk.Menu(self.root, bg="#1e1e2e", fg="#cccccc",
                          activebackground="#2a2a4a", activeforeground="white")
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0, bg="#1e1e2e", fg="#cccccc")
        menubar.add_cascade(label="Fichier", menu=file_menu)
        file_menu.add_command(label="Réinitialiser tous les effets", command=self._reset_effects)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self._on_close)

        # Notebook tabs
        self._notebook = ttk.Notebook(self.root) if not CTK else None

        if CTK:
            tabview = ctk.CTkTabview(self.root)
            tabview.pack(fill="both", expand=True, padx=6, pady=6)
            tabview.add("🎙 Modificateur de voix")
            tabview.add("🎭 Profils")
            tabview.add("🎵 Soundboard")

            voice_container = tabview.tab("🎙 Modificateur de voix")
            profiles_container = tabview.tab("🎭 Profils")
            soundboard_container = tabview.tab("🎵 Soundboard")
        else:
            import tkinter.ttk as ttk
            self._notebook = ttk.Notebook(self.root)
            self._notebook.pack(fill="both", expand=True, padx=6, pady=6)
            voice_container = tk.Frame(self._notebook, bg="#13131f")
            profiles_container = tk.Frame(self._notebook, bg="#13131f")
            soundboard_container = tk.Frame(self._notebook, bg="#13131f")
            self._notebook.add(voice_container, text="🎙 Modificateur de voix")
            self._notebook.add(profiles_container, text="🎭 Profils")
            self._notebook.add(soundboard_container, text="🎵 Soundboard")

        self.voice_tab = VoiceTab(voice_container, self)
        self.voice_tab.pack(fill="both", expand=True)

        self.profiles_tab = ProfilesTab(profiles_container, self)
        self.profiles_tab.pack(fill="both", expand=True)

        self.soundboard_tab = SoundboardTab(soundboard_container, self)
        self.soundboard_tab.pack(fill="both", expand=True)

        # Status bar
        self._status_var = tk.StringVar(value="Prêt")
        tk.Label(self.root, textvariable=self._status_var, bg="#0d0d1a", fg="#666688",
                 font=("Consolas", 8), anchor="w", padx=8, pady=2
                 ).pack(fill="x", side="bottom")

    def _load_config(self):
        # Apply saved config
        buf = self.config.get("buffer_size", 1024)
        self.audio_engine.buffer_size = buf
        self.voice_tab.buf_var.set(str(buf))

        in_vol = self.config.get("input_volume", 1.0)
        self.audio_engine.input_volume = in_vol
        self.voice_tab.in_vol_var.set(in_vol)

        out_vol = self.config.get("output_volume", 1.0)
        self.audio_engine.output_volume = out_vol
        self.voice_tab.out_vol_var.set(out_vol)

        monitoring = self.config.get("monitoring", False)
        self.audio_engine.monitoring = monitoring
        self.voice_tab.monitor_var.set(monitoring)

        sens = self.config.get("sensitivity", 0.0)
        self.voice_tab._sens_var.set(sens)
        if sens > 0:
            self.voice_tab._on_sensitivity(str(sens))

        # Soundboard slots
        slots = self.config.get("soundboard_slots", [])
        if slots:
            self.soundboard_tab.load_from_config(slots)

        # Last profile
        last_p = self.config.get("last_profile")
        if last_p:
            profile = self.profile_manager.get_profile(last_p)
            if profile:
                self.effects_chain.from_dict(profile.get("effects", []))
                self.profile_manager.set_active(last_p)
                self.root.after(500, self.voice_tab.sync_from_chain)

        # Setup profile hotkeys + soundboard hotkeys
        self.root.after(1000, self.profiles_tab.setup_all_hotkeys)
        self.root.after(1200, self.soundboard_tab.register_all_hotkeys)

    def _start_audio(self):
        # On ne démarre PAS le moteur audio automatiquement.
        # L'audio démarre seulement quand l'utilisateur clique ⟳ Appliquer.
        # Cela évite que l'app capture le micro dès l'ouverture.
        self.root.after(200, self._refresh_devices)

    def _refresh_devices(self):
        # Énumération des périphériques sans ouvrir de stream audio
        try:
            import sounddevice as sd
            all_devs = sd.query_devices()
            in_devs = [{"index": i, "name": d["name"]}
                       for i, d in enumerate(all_devs) if d["max_input_channels"] > 0]
            out_devs = [{"index": i, "name": d["name"]}
                        for i, d in enumerate(all_devs) if d["max_output_channels"] > 0]
        except Exception:
            in_devs, out_devs = [], []
        self._in_device_map  = {"Défaut": None, **{f"[{d['index']}] {d['name']}": d["index"] for d in in_devs}}
        self._out_device_map = {"Défaut": None, **{f"[{d['index']}] {d['name']}": d["index"] for d in out_devs}}
        self.voice_tab.refresh_devices(in_devs, out_devs)

    def _start_vu_loop(self):
        def update():
            try:
                lvl = self.audio_engine.in_level
                self.voice_tab.vu_in.update_level(lvl)
                self.voice_tab.vu_out.update_level(self.audio_engine.out_level)
                self.voice_tab.update_sensitivity(lvl)
            except Exception:
                pass
            self.root.after(40, update)  # ~25 fps
        self.root.after(200, update)

    def _reset_effects(self):
        self.effects_chain.reset_all()
        for e in self.effects_chain.effects:
            e.enabled = False
        self.voice_tab.sync_from_chain()
        self._status_var.set("Tous les effets réinitialisés.")

    def _save_config(self):
        self.config.update({
            "window_geometry": self.root.geometry(),
            "buffer_size": self.audio_engine.buffer_size,
            "input_volume": self.audio_engine.input_volume,
            "output_volume": self.audio_engine.output_volume,
            "monitoring": self.audio_engine.monitoring,
            "last_profile": self.profile_manager.active_profile,
            "soundboard_slots": self.soundboard_manager.to_dict(),
            "in_device_name": self.voice_tab.in_dev_var.get(),
            "out_device_name": self.voice_tab.out_dev_var.get(),
            "monitor_device_name": self.voice_tab.monitor_dev_var.get(),
            "sensitivity": self.voice_tab._sens_var.get(),
        })

    def _on_close(self):
        self._save_config()
        self.audio_engine.stop()
        try:
            if KB_OK:
                kb.unhook_all()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ──────────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        import tkinter.ttk  # noqa
    except ImportError:
        print("tkinter non disponible.")
        sys.exit(1)

    app = App()
    app.run()
