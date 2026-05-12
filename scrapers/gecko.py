"""
GeckoAPI scraper for Webmotors and iCarros.

Uses geckoapi.com.br as a proxy to bypass WAF/IP restrictions.
Free tier: 1,000 requests/month — sign up at https://geckoapi.com.br

Set the token via environment variable:
    export GECKO_TOKEN=seu_token_aqui
or create a .env file with:
    GECKO_TOKEN=seu_token_aqui
"""

import json
import os
import re
import time
import uuid

import requests

GECKO_API = "https://api.geckoapi.com.br/v1/extract"
ITEMS_PER_PAGE = 24
DEFAULT_MAX_PAGES = 15


def get_token() -> str | None:
    token = os.environ.get("GECKO_TOKEN", "").strip()
    if token:
        return token
    # Try .env file
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("GECKO_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


class GeckoScraper:
    """Wraps geckoapi.com.br to scrape Webmotors and iCarros listing pages."""

    def __init__(self, token: str | None = None):
        self.token = token or get_token()
        self.session = requests.Session()

    def is_configured(self) -> bool:
        return bool(self.token)

    # ------------------------------------------------------------------ #
    # Webmotors                                                            #
    # ------------------------------------------------------------------ #

    def search_webmotors(self, filters: dict, progress_cb=None) -> list:
        max_pages = int(filters.get("max_pages", DEFAULT_MAX_PAGES))
        base_url = self._wm_build_url(filters)

        all_results = []
        for page in range(1, max_pages + 1):
            url = base_url + (f"&pagina={page}" if page > 1 else "&pagina=1")
            data = self._extract(target="webmotors.com.br", page_type="plp", url=url)
            if data is None:
                if page == 1:
                    print("[GeckoAPI/Webmotors] Falha na primeira página — verifique o token")
                break

            items = self._wm_parse_plp(data)
            if not items:
                print(f"[GeckoAPI/Webmotors] Página {page}: vazia, encerrando.")
                break

            all_results.extend(items)
            print(f"[GeckoAPI/Webmotors] Página {page}: {len(items)} anúncios (total: {len(all_results)})")

            if progress_cb:
                progress_cb("webmotors", page, len(all_results))

            if len(items) < ITEMS_PER_PAGE:
                break

            time.sleep(0.3)

        seen = set()
        unique = [c for c in all_results if not (c["id"] in seen or seen.add(c["id"]))]
        print(f"[GeckoAPI/Webmotors] Total: {len(unique)} anúncios únicos")
        return unique

    def search_icarros(self, filters: dict, progress_cb=None) -> list:
        max_pages = int(filters.get("max_pages", DEFAULT_MAX_PAGES))
        base_url = self._ic_build_url(filters)

        all_results = []
        for page in range(1, max_pages + 1):
            url = base_url + (f"&pagina={page}" if "?" in base_url else f"?pagina={page}")
            data = self._extract(target="icarros.com.br", page_type="plp", url=url)
            if data is None:
                if page == 1:
                    print("[GeckoAPI/iCarros] Falha na primeira página — verifique o token")
                break

            items = self._ic_parse_plp(data)
            if not items:
                print(f"[GeckoAPI/iCarros] Página {page}: vazia, encerrando.")
                break

            all_results.extend(items)
            print(f"[GeckoAPI/iCarros] Página {page}: {len(items)} anúncios (total: {len(all_results)})")

            if progress_cb:
                progress_cb("icarros", page, len(all_results))

            if len(items) < ITEMS_PER_PAGE:
                break

            time.sleep(0.3)

        seen = set()
        unique = [c for c in all_results if not (c["id"] in seen or seen.add(c["id"]))]
        print(f"[GeckoAPI/iCarros] Total: {len(unique)} anúncios únicos")
        return unique

    # ------------------------------------------------------------------ #
    # Core HTTP call                                                       #
    # ------------------------------------------------------------------ #

    def _extract(self, target: str, page_type: str, url: str) -> dict | list | None:
        if not self.token:
            print("[GeckoAPI] Token não configurado — defina GECKO_TOKEN no .env")
            return None
        try:
            r = self.session.post(
                GECKO_API,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                json={"target": target, "type": page_type, "url": url},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 401:
                print("[GeckoAPI] Token inválido ou expirado")
            elif r.status_code == 402:
                print("[GeckoAPI] Cota esgotada — verifique sua conta em geckoapi.com.br")
            elif r.status_code == 429:
                print("[GeckoAPI] Rate limit atingido, aguardando…")
                time.sleep(5)
            else:
                print(f"[GeckoAPI] HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[GeckoAPI] Erro: {e}")
        return None

    # ------------------------------------------------------------------ #
    # Webmotors parsing                                                    #
    # ------------------------------------------------------------------ #

    def _wm_parse_plp(self, data) -> list:
        """
        GeckoAPI returns structured JSON for the listing page.
        We handle both the structured format and raw SearchResults format.
        """
        cars = []

        # GeckoAPI structured response: {"data": {"listings": [...]}} or similar
        if isinstance(data, dict):
            items = (
                data.get("data", {}).get("listings")
                or data.get("data", {}).get("SearchResults")
                or data.get("SearchResults")
                or data.get("results")
                or data.get("items")
                or []
            )
            # Sometimes GeckoAPI wraps in a different structure
            if not items and "data" in data:
                d = data["data"]
                if isinstance(d, list):
                    items = d
                elif isinstance(d, dict):
                    # Try common keys
                    for key in ("listings", "SearchResults", "results", "anuncios", "vehicles"):
                        if key in d and isinstance(d[key], list):
                            items = d[key]
                            break
        elif isinstance(data, list):
            items = data
        else:
            return []

        for item in items:
            try:
                cars.append(self._wm_normalise(item))
            except Exception as e:
                print(f"[GeckoAPI/Webmotors] Normalise error: {e}")

        return cars

    def _wm_normalise(self, item: dict) -> dict:
        # GeckoAPI may return flat or nested (Webmotors Specification/Media/Prices/Seller)
        spec   = item.get("Specification", item)
        media  = item.get("Media", item)
        prices = item.get("Prices", item)
        seller = item.get("Seller", item)

        # Flat keys (GeckoAPI structured)
        def pick(*keys):
            for k in keys:
                if k in item and item[k] not in (None, ""):
                    return item[k]
            return ""

        # ID
        listing_id = str(
            item.get("UniqueId")
            or item.get("id")
            or item.get("uniqueId")
            or uuid.uuid4()
        )

        # Brand/Model
        brand = (spec.get("Make", {}).get("Value") if isinstance(spec.get("Make"), dict) else None) \
            or pick("brand", "make", "Brand", "marca")
        model = (spec.get("Model", {}).get("Value") if isinstance(spec.get("Model"), dict) else None) \
            or pick("model", "Model", "modelo")
        version = (spec.get("Version", {}).get("Value") if isinstance(spec.get("Version"), dict) else None) \
            or pick("version", "Version", "versao")

        year = int(
            spec.get("YearFabrication")
            or item.get("year") or item.get("anoFabricacao") or 0
        )
        year_model = int(
            spec.get("YearModel")
            or item.get("year_model") or item.get("anoModelo") or year
        )
        km = int(
            spec.get("Odometer")
            or item.get("km") or item.get("odometer") or 0
        )

        color = ""
        if isinstance(spec.get("Color"), dict):
            color = spec["Color"].get("Primary", {}).get("Value", "")
        color = color or pick("color", "cor", "Color")

        transmission = ""
        if isinstance(spec.get("Transmission"), dict):
            transmission = spec["Transmission"].get("Value", "")
        transmission = transmission or pick("transmission", "cambio")

        fuel = ""
        if isinstance(spec.get("Fuel"), dict):
            fuel = spec["Fuel"].get("Value", "")
        fuel = fuel or pick("fuel", "combustivel")

        price = float(
            (prices.get("Price") if isinstance(prices, dict) else None)
            or item.get("price") or item.get("preco") or 0
        )

        photos = media.get("Photos", []) if isinstance(media, dict) else []
        if not photos:
            photos = item.get("photos", item.get("fotos", []))
        photo = ""
        if photos:
            first = photos[0]
            photo = first.get("Path", first.get("url", "")) if isinstance(first, dict) else str(first)

        city  = (seller.get("City") if isinstance(seller, dict) else None) or pick("city", "cidade")
        state = (seller.get("State") if isinstance(seller, dict) else None) or pick("state", "estado")
        seller_type = (seller.get("Type") if isinstance(seller, dict) else None) or pick("seller_type", "tipoAnunciante", "PF")
        seller_name = (seller.get("Name") if isinstance(seller, dict) else None) or pick("seller_name", "anunciante")

        return {
            "id": listing_id,
            "source": "webmotors",
            "source_label": "Webmotors",
            "source_url": f"https://www.webmotors.com.br/carros/anuncio/{listing_id}",
            "brand": brand,
            "model": model,
            "version": version,
            "year": year,
            "year_model": year_model,
            "km": km,
            "color": color,
            "transmission": transmission,
            "fuel": fuel,
            "price": price,
            "photo": photo,
            "city": city,
            "state": state,
            "seller_type": seller_type,
            "seller_name": seller_name,
            "fipe_price": None,
            "owners": int(item.get("OwnersCount") or item.get("owners") or 1),
            "risk_flags": {
                "auction": bool(item.get("AuctionOrigin") or item.get("auction", False)),
                "recall": bool(item.get("HasOpenRecall") or item.get("recall", False)),
            },
            "liquidity": "media",
        }

    # ------------------------------------------------------------------ #
    # iCarros parsing                                                      #
    # ------------------------------------------------------------------ #

    def _ic_parse_plp(self, data) -> list:
        if isinstance(data, dict):
            items = (
                data.get("data", {}).get("anuncios")
                or data.get("data", {}).get("listings")
                or data.get("anuncios")
                or data.get("results")
                or []
            )
            if not items and "data" in data:
                d = data["data"]
                if isinstance(d, list):
                    items = d
        elif isinstance(data, list):
            items = data
        else:
            return []

        cars = []
        for item in items:
            try:
                cars.append(self._ic_normalise(item))
            except Exception as e:
                print(f"[GeckoAPI/iCarros] Normalise error: {e}")
        return cars

    def _ic_normalise(self, item: dict) -> dict:
        listing_id = str(item.get("id") or item.get("anuncioId") or uuid.uuid4())
        brand = item.get("marca") or item.get("brand") or item.get("makeName") or ""
        model = item.get("modelo") or item.get("model") or ""
        version = item.get("versao") or item.get("version") or ""
        year = int(item.get("anoFabricacao") or item.get("year") or 0)
        year_model = int(item.get("anoModelo") or item.get("yearModel") or year)
        km = int(item.get("km") or item.get("odometer") or 0)
        price = float(item.get("preco") or item.get("price") or 0)
        color = item.get("cor") or item.get("color") or ""
        photo = ""
        photos = item.get("fotos") or item.get("photos") or []
        if photos:
            first = photos[0]
            photo = first if isinstance(first, str) else first.get("url", first.get("path", ""))

        return {
            "id": listing_id,
            "source": "icarros",
            "source_label": "iCarros",
            "source_url": f"https://www.icarros.com.br/anuncio/detalhe/{listing_id}",
            "brand": brand,
            "model": model,
            "version": version,
            "year": year,
            "year_model": year_model,
            "km": km,
            "color": color,
            "transmission": item.get("cambio") or item.get("transmission") or "",
            "fuel": item.get("combustivel") or item.get("fuel") or "",
            "price": price,
            "photo": photo,
            "city": item.get("cidade") or item.get("city") or "",
            "state": item.get("estado") or item.get("state") or "",
            "seller_type": item.get("tipoAnunciante") or "PF",
            "seller_name": item.get("anunciante") or "",
            "fipe_price": None,
            "owners": int(item.get("qtdDonos") or 1),
            "risk_flags": {
                "auction": bool(item.get("origemLeilao", False)),
                "recall": bool(item.get("temRecall", False)),
            },
            "liquidity": "media",
        }

    # ------------------------------------------------------------------ #
    # URL builders                                                         #
    # ------------------------------------------------------------------ #

    def _wm_build_url(self, f: dict) -> str:
        base = "https://www.webmotors.com.br/carros/estoque?TipoPessoa=F&Pesquisa=True"
        if f.get("brand"): base += f"&marca={f['brand']}"
        if f.get("model"): base += f"&modelo={f['model']}"
        if f.get("price_min"): base += f"&preco_de={f['price_min']}"
        if f.get("price_max"): base += f"&preco_ate={f['price_max']}"
        if f.get("year_min"): base += f"&ano_de={f['year_min']}"
        if f.get("year_max"): base += f"&ano_ate={f['year_max']}"
        if f.get("km_max"): base += f"&km_ate={f['km_max']}"
        if f.get("state"): base += f"&estado={f['state']}"
        return base

    def _ic_build_url(self, f: dict) -> str:
        base = "https://www.icarros.com.br/comprar/"
        params = []
        if f.get("brand"): params.append(f"marca={f['brand']}")
        if f.get("model"): params.append(f"modelo={f['model']}")
        if f.get("price_min"): params.append(f"valorMinimo={f['price_min']}")
        if f.get("price_max"): params.append(f"valorMaximo={f['price_max']}")
        if f.get("year_min"): params.append(f"anoInicial={f['year_min']}")
        if f.get("year_max"): params.append(f"anoFinal={f['year_max']}")
        if f.get("km_max"): params.append(f"kmMaximo={f['km_max']}")
        return base + ("?" + "&".join(params) if params else "")
