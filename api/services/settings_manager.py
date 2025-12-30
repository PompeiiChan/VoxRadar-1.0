# -*- coding: utf-8 -*-
import os
import json
import threading
from typing import Optional, Dict, Any

_lock = threading.RLock()

class _SettingsManager:
    def __init__(self) -> None:
        self._data: Dict[str, Any] = {
            "lm": {
                "api_key": "",
                "api_base": "https://api.deepseek.com",
                "model": "deepseek-chat",
                "temperature": 0.1,
                "max_tokens": 4000,
            },
            "account": {
                "username": "",
                "email": "",
                "avatar_url": ""
            },
            "prompt": ""
        }
        self._path = os.path.join("data", "system")
        self._file = os.path.join(self._path, "settings.json")
        self._loaded = False
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        with _lock:
            if self._loaded:
                return
            try:
                if os.path.exists(self._file):
                    with open(self._file, "r", encoding="utf-8") as f:
                        obj = json.load(f)
                        if isinstance(obj, dict):
                            self._data.update(obj)
                self._loaded = True
            except Exception:
                self._loaded = True

    def _save(self) -> None:
        with _lock:
            try:
                os.makedirs(self._path, exist_ok=True)
                with open(self._file, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def get_lm(self) -> Dict[str, Any]:
        self._ensure_loaded()
        with _lock:
            return dict(self._data.get("lm", {}))

    def get_api_key(self) -> str:
        return self.get_lm().get("api_key") or ""

    def set_lm(self, **kwargs: Any) -> None:
        self._ensure_loaded()
        with _lock:
            lm = self._data.setdefault("lm", {})
            for k, v in kwargs.items():
                if v is not None:
                    lm[k] = v
            self._save()

    def get_account(self) -> Dict[str, Any]:
        self._ensure_loaded()
        with _lock:
            return dict(self._data.get("account", {}))

    def set_account(self, **kwargs: Any) -> None:
        self._ensure_loaded()
        with _lock:
            acc = self._data.setdefault("account", {})
            for k, v in kwargs.items():
                if v is not None:
                    acc[k] = v
            self._save()

    def mask_key(self, k: str) -> str:
        if not k:
            return ""
        if len(k) <= 8:
            return "****"
        return f"{k[:4]}****{k[-4:]}"

    def get_account(self) -> Dict[str, Any]:
        self._ensure_loaded()
        with _lock:
            return dict(self._data.get("account", {}))

    def set_account(self, **kwargs: Any) -> None:
        self._ensure_loaded()
        with _lock:
            acc = self._data.setdefault("account", {})
            for k, v in kwargs.items():
                if v is not None:
                    acc[k] = v
            self._save()

    def get_prompt(self) -> str:
        self._ensure_loaded()
        with _lock:
            return str(self._data.get("prompt") or "")

    def set_prompt(self, text: str | None) -> None:
        self._ensure_loaded()
        with _lock:
            if text is not None:
                self._data["prompt"] = text
                self._save()

settings_manager = _SettingsManager()
