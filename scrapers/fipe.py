"""
FIPE price lookup via parallelum.com.br public API.

Caches results in data/fipe_cache.json to minimise repeated requests.
Brand/model matching uses a simple normalisation + contains strategy.
"""

import json
import os
import re
import time
import unicodedata

import requests

FIPE_API = "https://parallelum.com.br/fipe/api/v2"
CACHE_FILE = "data/fipe_cache.json"

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 CarAnalyser/1.0",
        "Accept": "application/json",
    }
)


def _normalise(text: str) -> str:
    """Lowercase, strip accents, keep only alphanumeric + spaces."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _get(url: str, retries: int = 3) -> dict | list | None:
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=10)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"[FIPE] GET {url} erro: {e}")
            time.sleep(1)
    return None


class FipeLookup:
    def __init__(self):
        self._cache = self._load_cache()

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #

    def lookup(self, brand: str, model: str, year: int) -> float | None:
        if not brand or not model or not year:
            return None

        cache_key = f"{_normalise(brand)}|{_normalise(model)}|{year}"
        if cache_key in self._cache.get("prices", {}):
            return self._cache["prices"][cache_key]

        price = self._fetch_price(brand, model, year)

        self._cache.setdefault("prices", {})[cache_key] = price
        self._save_cache()
        return price

    def get_brands(self) -> list:
        """Return list of {code, name} from FIPE (cached)."""
        if "brands" in self._cache:
            return self._cache["brands"]
        data = _get(f"{FIPE_API}/cars/brands")
        if data:
            self._cache["brands"] = data
            self._save_cache()
            return data
        return []

    # ------------------------------------------------------------------ #
    # Internal lookup                                                      #
    # ------------------------------------------------------------------ #

    def _fetch_price(self, brand: str, model: str, year: int) -> float | None:
        brand_id = self._find_brand_id(brand)
        if not brand_id:
            return None

        model_id = self._find_model_id(brand_id, model)
        if not model_id:
            return None

        year_id = self._find_year_id(brand_id, model_id, year)
        if not year_id:
            return None

        data = _get(f"{FIPE_API}/cars/brands/{brand_id}/models/{model_id}/years/{year_id}")
        if data and "price" in data:
            raw = str(data["price"])
            raw = re.sub(r"[R$\s\.]", "", raw).replace(",", ".")
            try:
                return float(raw)
            except Exception:
                pass
        return None

    def _find_brand_id(self, brand: str) -> str | None:
        brands = self.get_brands()
        norm = _normalise(brand)

        # Exact match first
        for b in brands:
            if _normalise(b.get("name", "")) == norm:
                return b["code"]

        # Contains match
        for b in brands:
            if norm in _normalise(b.get("name", "")) or _normalise(b.get("name", "")) in norm:
                return b["code"]

        return None

    def _find_model_id(self, brand_id: str, model: str) -> str | None:
        cache_key = f"models_{brand_id}"
        if cache_key not in self._cache:
            data = _get(f"{FIPE_API}/cars/brands/{brand_id}/models")
            if not data:
                return None
            models = data if isinstance(data, list) else data.get("models", data.get("modelos", []))
            self._cache[cache_key] = models
            self._save_cache()

        models = self._cache.get(cache_key, [])
        norm = _normalise(model)

        for m in models:
            if _normalise(m.get("name", "")) == norm:
                return m["code"]

        for m in models:
            m_norm = _normalise(m.get("name", ""))
            if norm in m_norm or m_norm in norm:
                return m["code"]

        # Try first word match (e.g. "Civic" matches "Civic EXL 2.0")
        first_word = norm.split()[0] if norm else ""
        if first_word and len(first_word) > 2:
            for m in models:
                if _normalise(m.get("name", "")).startswith(first_word):
                    return m["code"]

        return None

    def _find_year_id(self, brand_id: str, model_id: str, year: int) -> str | None:
        data = _get(f"{FIPE_API}/cars/brands/{brand_id}/models/{model_id}/years")
        if not data:
            return None

        year_str = str(year)

        # Exact year
        for y in data:
            if str(y.get("code", "")).startswith(year_str) or year_str in str(y.get("name", "")):
                return y["code"]

        # Flex (year-1)
        fallback = str(year - 1)
        for y in data:
            if str(y.get("code", "")).startswith(fallback) or fallback in str(y.get("name", "")):
                return y["code"]

        # Return most recent available
        if data:
            return data[0]["code"]

        return None

    # ------------------------------------------------------------------ #
    # Cache helpers                                                        #
    # ------------------------------------------------------------------ #

    def _load_cache(self) -> dict:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_cache(self):
        os.makedirs("data", exist_ok=True)
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
