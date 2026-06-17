# profile_manager.py - Gestion des profils de voix

import json
from pathlib import Path


class ProfileManager:
    """Sauvegarde, chargement et gestion des profils de voix."""

    def __init__(self, profiles_dir: str = None):
        if profiles_dir is None:
            base = Path.home() / ".voice_modifier"
            base.mkdir(exist_ok=True)
            profiles_dir = base / "profiles"
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._profiles: dict = {}  # name -> {effects, shortcut}
        self._active_profile: str | None = None
        self.load_all()

    # ──────────────────────────────────────────────────────────────────

    def load_all(self):
        self._profiles = {}
        for f in self.profiles_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                name = data.get("name", f.stem)
                self._profiles[name] = data
            except Exception as e:
                print(f"[Profiles] Erreur lecture {f}: {e}")

    def save_profile(self, name: str, effects_chain_dict: list, shortcut: str = "") -> bool:
        data = {
            "name": name,
            "shortcut": shortcut,
            "effects": effects_chain_dict,
        }
        self._profiles[name] = data
        path = self.profiles_dir / f"{self._safe_name(name)}.json"
        try:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[Profiles] Erreur sauvegarde : {e}")
            return False

    def delete_profile(self, name: str) -> bool:
        if name not in self._profiles:
            return False
        path = self.profiles_dir / f"{self._safe_name(name)}.json"
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        del self._profiles[name]
        if self._active_profile == name:
            self._active_profile = None
        return True

    def get_profile(self, name: str) -> dict | None:
        return self._profiles.get(name)

    def list_profiles(self) -> list[dict]:
        return list(self._profiles.values())

    def rename_profile(self, old_name: str, new_name: str) -> bool:
        if old_name not in self._profiles or new_name in self._profiles:
            return False
        data = self._profiles.pop(old_name)
        data["name"] = new_name
        self._profiles[new_name] = data
        old_path = self.profiles_dir / f"{self._safe_name(old_name)}.json"
        old_path.unlink(missing_ok=True)
        new_path = self.profiles_dir / f"{self._safe_name(new_name)}.json"
        try:
            with open(new_path, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, ensure_ascii=False)
            if self._active_profile == old_name:
                self._active_profile = new_name
            return True
        except Exception as e:
            print(f"[Profiles] Erreur renommage : {e}")
            return False

    # ──────────────────────────────────────────────────────────────────
    # Import / Export JSON
    # ──────────────────────────────────────────────────────────────────

    def export_profile(self, name: str, path: str) -> bool:
        data = self._profiles.get(name)
        if not data:
            return False
        try:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[Profiles] Erreur export : {e}")
            return False

    def import_profile(self, path: str) -> str | None:
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            name = data.get("name", Path(path).stem)
            # Éviter les doublons
            base_name = name
            i = 1
            while name in self._profiles:
                name = f"{base_name} ({i})"
                i += 1
            data["name"] = name
            self._profiles[name] = data
            dest = self.profiles_dir / f"{self._safe_name(name)}.json"
            with open(dest, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, ensure_ascii=False)
            return name
        except Exception as e:
            print(f"[Profiles] Erreur import : {e}")
            return None

    # ──────────────────────────────────────────────────────────────────

    @property
    def active_profile(self) -> str | None:
        return self._active_profile

    def set_active(self, name: str | None):
        self._active_profile = name

    def update_shortcut(self, name: str, shortcut: str):
        if name in self._profiles:
            self._profiles[name]["shortcut"] = shortcut
            path = self.profiles_dir / f"{self._safe_name(name)}.json"
            try:
                with open(path, "w", encoding="utf-8") as fp:
                    json.dump(self._profiles[name], fp, indent=2, ensure_ascii=False)
            except Exception:
                pass

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()
