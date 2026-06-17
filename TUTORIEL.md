# Tutoriel — Bissap Voice Changer by Groudy

## Sommaire

1. [Installation complète](#1-installation-complète)
2. [Premier lancement](#2-premier-lancement)
3. [Configurer le routing audio](#3-configurer-le-routing-audio)
4. [Utiliser les effets](#4-utiliser-les-effets)
5. [Créer et gérer des profils](#5-créer-et-gérer-des-profils)
6. [Utiliser le soundboard](#6-utiliser-le-soundboard)
7. [Raccourcis clavier](#7-raccourcis-clavier)
8. [Conseils et dépannage](#8-conseils-et-dépannage)

---

## 1. Installation complète

### Étape 1 — Installer Python

Télécharger Python 3.10 ou supérieur sur https://python.org  
Cocher **"Add Python to PATH"** pendant l'installation.

Vérifier l'installation :
```
python --version
```

### Étape 2 — Installer les dépendances

Ouvrir un terminal dans le dossier `voice_modifier` et lancer :

```
pip install -r requirements.txt
```

Ou double-cliquer sur `install.bat`.

### Étape 3 — Installer VB-Audio Virtual Cable

C'est le **câble audio virtuel** qui permet à Discord, Teams, OBS, etc. de capter votre voix modifiée.

1. Aller sur https://vb-audio.com/Cable
2. Télécharger **VB-CABLE_Driver_Pack45.zip** (gratuit, pas de compte requis)
3. Extraire l'archive
4. Cliquer droit sur `VBCABLE_Setup_x64.exe` → **Exécuter en tant qu'administrateur**
5. Cliquer "Install Driver"
6. **Redémarrer Windows** (obligatoire)

Après redémarrage, deux nouveaux périphériques apparaissent dans Windows :
- **CABLE Input (VB-Audio Virtual Cable)** — entrée du câble (ce que Bissap Voice Changer by Groudy envoie)
- **CABLE Output (VB-Audio Virtual Cable)** — sortie du câble (ce que Discord/Teams reçoit)

---

## 2. Premier lancement

Lancer l'application :
```
python main.py
```

L'interface s'ouvre avec trois onglets :
- **Modificateur de voix** — effets et périphériques
- **Profils** — sauvegarder et charger des configurations
- **Soundboard** — jouer des sons en direct

---

## 3. Configurer le routing audio

C'est l'étape la plus importante. Elle permet que vos effets soient entendus par les autres.

### Dans l'onglet "Modificateur de voix"

Dans la section **Périphériques** :

| Champ | Valeur à sélectionner |
|---|---|
| 🎙 Micro (entrée) | Votre vrai micro (ex: "Microphone (Realtek)") |
| 🔌 Câble virtuel (sortie) | **CABLE Input (VB-Audio Virtual Cable)** |
| 🔊 Haut-parleurs (monitor) | Vos écouteurs ou haut-parleurs |

Cliquer **⟳ Appliquer**.

> Si VB-Audio est installé, le câble est détecté et sélectionné automatiquement dans le champ "Sortie".

### Dans Discord

1. Paramètres (roue dentée) → **Voix et vidéo**
2. **Périphérique d'entrée** → `CABLE Output (VB-Audio Virtual Cable)`
3. Désactiver la suppression de bruit de Discord (elle peut altérer les effets)

### Dans OBS

1. Ajouter une source → **Capture audio (entrée)**
2. Périphérique → `CABLE Output (VB-Audio Virtual Cable)`

### Dans Teams

1. Paramètres → **Appareils**
2. Microphone → `CABLE Output (VB-Audio Virtual Cable)`

### Le schéma complet

```
Votre micro
    │
    ▼
Bissap Voice Changer by Groudy  ──(effets DSP)──►  CABLE Input  ──►  CABLE Output  ──►  Discord / Teams / OBS
                                                                         
    │ (optionnel)
    ▼
Vos haut-parleurs / écouteurs   ◄── cocher "S'entendre"
```

### S'entendre soi-même avec les effets

Cocher la case **🎧 S'entendre** dans la barre de contrôle.  
Le son passe par le périphérique "Haut-parleurs (monitor)" sélectionné.

---

## 4. Utiliser les effets

### Activer un effet

Chaque effet est dans une **section repliable**.  
- Cliquer sur le titre de la section pour la déplier
- Cocher la case **ON** à droite du titre pour activer l'effet

### Ajuster les paramètres

Deux façons de modifier une valeur :

1. **Glisser le slider** avec la souris
2. **Cliquer dans la case de saisie** à droite du slider et taper une valeur, puis appuyer sur Entrée

Les valeurs ne sont pas limitées artificiellement — vous pouvez entrer manuellement des valeurs extrêmes.

### Bypass global

Le bouton **⊘ BYPASS** désactive instantanément tous les effets.  
Votre voix passe à travers sans traitement. Utile pour comparer avec/sans effets.

### Exemples de configurations utiles

**Voix de robot :**
- Ring Modulator ON, fréquence = 100 Hz, mix = 0.8
- Bitcrusher ON, bits = 8, rate reduction = 4

**Voix grave / démon :**
- Pitch Shifter ON, demi-tons = -8
- Growl ON, drive = 5, mix = 0.5
- Reverb ON, room size = 0.8

**Voix chipmunk :**
- Helium ON, intensité = 0.8

**Voix téléphonique :**
- Telephone Filter ON (paramètres par défaut suffisent)
- Compressor ON, ratio = 6

**Voix à la radio :**
- Radio Effect ON, noise = 0.03
- Compressor ON, threshold = -20 dB

**Voix sous-marine :**
- Underwater ON, depth = 0.9, wobble = 0.5

**Karaoké / grande salle :**
- Reverb ON, room size = 0.9, wet = 0.4
- Echo ON, delay = 300 ms, feedback = 0.3

### Égaliseur 10 bandes

Les sliders verticaux contrôlent le gain de chaque bande de fréquences en décibels.  
- Vers le haut = boost (jusqu'à +12 dB)
- Vers le bas = coupure (jusqu'à -12 dB)

Valeur affichée sous chaque slider. Valeur 0 = neutre.

---

## 5. Créer et gérer des profils

Un profil sauvegarde l'état complet de tous les effets (quels effets sont actifs, tous leurs paramètres).

### Créer un profil

1. Configurer vos effets comme vous le souhaitez
2. Aller dans l'onglet **Profils**
3. Cliquer **💾 Sauvegarder comme profil**
4. Entrer un nom et valider

### Assigner un raccourci clavier

1. Sélectionner un profil dans la liste
2. Dans le champ "Raccourci clavier", taper la combinaison souhaitée  
   Exemples : `f1`, `f2`, `ctrl+shift+1`, `ctrl+alt+r`
3. Cliquer **✓** pour confirmer

Le raccourci fonctionne **même si l'application n'est pas au premier plan**.

### Charger un profil

- Double-clic sur un profil dans la liste
- Ou sélectionner puis cliquer **📂 Charger profil**
- Ou appuyer sur le raccourci clavier assigné

Le profil actif est indiqué par une étoile ★ et affiché en vert.

### Partager un profil

**Exporter :**  
Sélectionner un profil → **📤 Exporter JSON** → choisir un emplacement

**Importer :**  
**📥 Importer JSON** → sélectionner le fichier `.json`

### Désactiver tous les profils

Cliquer **⊘ Désactiver tous** pour revenir à l'état neutre sans supprimer les profils.

---

## 6. Utiliser le soundboard

### Configurer un slot

1. Aller dans l'onglet **Soundboard**
2. Cliquer sur le bouton **✎** d'un slot
3. Renseigner :
   - **Nom** affiché sur le bouton
   - **Fichier audio** (.wav, .mp3, .ogg, .flac)
   - **Raccourci clavier** (optionnel)
   - **Volume** du slot
   - **Couleur** du bouton
4. Cliquer **✓ Sauvegarder**

### Jouer un son

- **Double-clic** sur le bouton du slot
- Cliquer le bouton **▶**
- Appuyer sur le raccourci assigné (même app en arrière-plan)

### Arrêter les sons

- **⏹** sur un slot = arrêter ce son
- **⏹ Stop All** = arrêter tous les sons simultanément

### Modes de lecture

- **Mode normal (overlap)** : plusieurs sons peuvent jouer simultanément
- **Mode exclusif** : cocher "Mode exclusif" — un nouveau son coupe le précédent

### Ajouter des slots

Cliquer **➕ Ajouter slot** pour créer un nouveau slot vide.

---

## 7. Raccourcis clavier

| Action | Raccourci |
|---|---|
| Activer profil X | Configurable dans l'onglet Profils |
| Jouer son soundboard | Configurable dans l'éditeur de slot |

Les raccourcis sont **globaux** — ils fonctionnent même quand l'application est en arrière-plan ou minimisée.

### Configurer un raccourci de profil

Dans l'onglet Profils, sélectionner un profil, taper dans le champ raccourci :
- `f1` à `f12`
- `ctrl+1`, `ctrl+2`, etc.
- `ctrl+shift+a`, `alt+r`, etc.

---

## 8. Conseils et dépannage

### Latence trop élevée

Réduire la taille du buffer dans la section **Latence** :
- `256` = latence minimale (~6 ms) mais peut causer des craquements
- `512` = bon compromis
- `1024` = valeur par défaut, stable
- `2048` ou `4096` = si des craquements persistent

Après changement, cliquer **⟳ Appliquer**.

### Craquements / discontinuités dans le son

- Augmenter le buffer size
- Désactiver les effets les plus gourmands (Vocoder, Reverb avec grande salle)
- Fermer les applications en arrière-plan

### Discord entend votre voix sans effets

Vérifier que dans Discord le micro sélectionné est bien **CABLE Output (VB-Audio Virtual Cable)** et non votre vrai micro.

### Vous vous entendez en double

Si vous avez activé "S'entendre" dans l'app ET que Windows a activé l'écoute du micro dans les paramètres son, vous aurez deux échos. Aller dans :  
Panneau de configuration → Son → Enregistrement → double-clic sur votre micro → onglet "Écouter" → décocher "Écouter ce périphérique".

### L'app ne détecte pas le câble VB-Audio

- Vérifier que VB-Audio a bien été installé **en administrateur**
- Redémarrer Windows
- Cliquer **⟳ Appliquer** pour forcer la détection des périphériques

### Le son sort trop fort / distordu même sans effets

Baisser le slider **Volume d'entrée** dans la section Volume. Valeur recommandée : 0.7 à 1.0.

### Réinitialiser tous les effets

Menu **Fichier → Réinitialiser tous les effets** : désactive tous les effets et remet les paramètres à zéro.

### Emplacement des fichiers de configuration

```
C:\Users\<votre-nom>\.voice_modifier\
├── config.json          Configuration générale
└── profiles\            Profils sauvegardés
    ├── mon_profil.json
    └── ...
```
