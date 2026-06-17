# Voice Modifier Pro

Modificateur de voix en temps réel avec soundboard, pour Windows.

Capture l'audio de votre micro, applique une chaîne d'effets DSP, et route le résultat vers un câble audio virtuel — ce qui permet à Discord, Teams, OBS ou n'importe quelle app de vous entendre avec les effets.

---

## Fonctionnalités

### 29 effets temps réel

**Pitch & Tonalité**
- Pitch Shifter — décalage en demi-tons (-24 à +24)
- Formant Shifter — décalage de formants indépendant du pitch
- Vibrato — modulation de pitch par LFO
- Tremolo — modulation d'amplitude
- Octave Doubler — voix parallèle une octave en dessous ou au-dessus

**Effets temporels**
- Echo — délai, feedback, mix wet/dry
- Reverb — algorithme de Schroeder (filtres en peigne + all-pass)
- Chorus — jusqu'à 8 voix
- Flanger — délai court modulé
- Phaser — chaîne de filtres all-pass
- Multi-Tap Delay — 4 taps configurables indépendamment

**Timbre**
- Distortion / Saturation — tanh soft-clip avec tone control
- Bitcrusher — réduction de résolution et de sample rate
- Ring Modulator — effet robot
- Vocoder — modulation spectrale par bandes
- Whisper — effet chuchotement
- Growl — harmoniques graves / throat effect
- Helium — effet chipmunk (pitch + formants)
- Telephone Filter — simulation voix téléphonique
- Megaphone — distorsion + boost médium
- Radio Effect — bruit + filtre + saturation
- Underwater — filtre passe-bas + modulation lente

**Filtres & Dynamique**
- Low-Pass Filter — fréquence de coupure + résonance (Q)
- High-Pass Filter — fréquence de coupure + résonance (Q)
- Band-Pass Filter — centre + largeur de bande
- Égaliseur 10 bandes — 31 Hz à 16 kHz
- Noise Gate — seuil, attack, release
- Compressor — threshold, ratio, attack, release, makeup gain
- De-Esser — atténuation des sibilantes

### Profils de voix
- Sauvegarde de l'état complet de tous les effets
- Raccourcis clavier globaux par profil (F1, Ctrl+Shift+1, etc.)
- Activation exclusive (un seul profil actif à la fois)
- Export / import en JSON pour partager des configurations

### Soundboard
- 24 slots extensibles
- Lecture par clic ou raccourci clavier (même app en arrière-plan)
- Couleur personnalisable par slot
- Volume individuel par slot
- Mode overlap ou exclusif

### Interface
- Thème sombre (CustomTkinter)
- VU-mètres animés entrée / sortie
- Sections repliables par effet
- Sliders avec saisie numérique directe
- Sélecteurs de périphériques séparés : micro, câble virtuel, haut-parleurs

---

## Installation

### Prérequis
- Python 3.10 ou supérieur
- Windows 10 / 11

### Dépendances Python

```
pip install -r requirements.txt
```

Ou manuellement :

```
pip install numpy scipy customtkinter keyboard soundfile sounddevice
```

> **PyAudio** : non disponible sur Python 3.14+. L'application utilise `sounddevice` comme backend audio, ce qui fonctionne de façon identique.

> **pygame** : nécessaire pour le soundboard. Si la compilation échoue, double-cliquez sur `install.bat` qui tentera l'installation automatique.

### Câble audio virtuel (obligatoire pour que les autres vous entendent)

1. Télécharger **VB-Audio Virtual Cable** : https://vb-audio.com/Cable  
2. Installer et **redémarrer Windows**

---

## Lancement

```
python main.py
```

ou double-clic sur `launch.bat`

---

## Structure des fichiers

```
voice_modifier/
├── main.py                 Interface graphique principale
├── audio_engine.py         Moteur audio temps réel
├── effects.py              Tous les effets DSP
├── profile_manager.py      Gestion des profils
├── soundboard_manager.py   Gestion du soundboard
├── config_manager.py       Configuration persistante
├── requirements.txt        Dépendances Python
├── install.bat             Installation automatique
└── launch.bat              Lancement rapide
```

Les profils et la configuration sont sauvegardés dans `%USERPROFILE%\.voice_modifier\`.

---

## Licence

Libre d'utilisation et de modification.
