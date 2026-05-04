"""
Scraper for iCarros listings.

Strategies (in order):
  1. Internal JSON search API  (/ola/busca/buscar-carros) — paginates all pages
  2. __NEXT_DATA__ embedded JSON
  3. Structured JSON-LD + card HTML fallback
"""

import json
import re
import time
import uuid

import requests
from bs4 import BeautifulSoup

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

SEARCH_URL = "https://www.icarros.com.br/comprar/"
API_URL = "https://www.icarros.com.br/ola/busca/buscar-carros"
ITEMS_PER_PAGE = 24
DEFAULT_MAX_PAGES = 15  # 360 cars max


class ICarrosScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(BASE_HEADERS)

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #

    def search(self, filters: dict, progress_cb=None) -> list:
        """Fetch all pages matching filters. progress_cb(source, page, total) optional."""
        max_pages = int(filters.get("max_pages", DEFAULT_MAX_PAGES))

        # Warm up session
        self._warm_session()

        all_results = []
        for page in range(1, max_pages + 1):
            batch = self._try_api(filters, page)
            if batch is None:
                # API unavailable — fall back to HTML for page 1 only
                if page == 1:
                    batch = self._try_html(filters, page=1) or []
                else:
                    break

            if not batch:
                print(f"[iCarros] Página {page}: vazia, encerrando.")
                break

            all_results.extend(batch)
            print(f"[iCarros] Página {page}: {len(batch)} anúncios (total: {len(all_results)})")

            if progress_cb:
                progress_cb("icarros", page, len(all_results))

            if len(batch) < ITEMS_PER_PAGE:
                break

            time.sleep(0.5)

        # Deduplicate by id
        seen = set()
        unique = []
        for car in all_results:
            if car["id"] not in seen:
                seen.add(car["id"])
                unique.append(car)

        print(f"[iCarros] Total: {len(unique)} anúncios únicos em {page} página(s)")
        return unique

    # ------------------------------------------------------------------ #
    # Strategy 1: Internal JSON API                                        #
    # ------------------------------------------------------------------ #

    def _try_api(self, filters: dict, page: int):
        payload = self._build_payload(filters, page)
        headers = {
            **BASE_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://www.icarros.com.br/comprar/",
            "Origin": "https://www.icarros.com.br",
        }
        try:
            r = self.session.post(API_URL, json=payload, headers=headers, timeout=20)
            if r.status_code == 200:
                data = r.json()
                items = data.get("anuncios", data.get("results", data.get("data", [])))
                if isinstance(items, list):
                    cars = [self._normalise_api(i) for i in items]
                    return cars
            elif r.status_code in (403, 429):
                print(f"[iCarros] API bloqueada ({r.status_code}) — use a aplicação localmente")
                return None
        except Exception as e:
            print(f"[iCarros] API erro p{page}: {e}")
        return None

    # ------------------------------------------------------------------ #
    # Strategy 2/3: HTML page parsing                                     #
    # ------------------------------------------------------------------ #

    def _warm_session(self):
        try:
            headers = {
                **BASE_HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            self.session.get("https://www.icarros.com.br/", headers=headers, timeout=10)
        except Exception:
            pass

    def _try_html(self, filters: dict, page: int = 1):
        params = self._build_params(filters, page)
        headers = {
            **BASE_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }
        try:
            r = self.session.get(SEARCH_URL, params=params, headers=headers, timeout=20)
            if r.status_code != 200:
                print(f"[iCarros] HTML retornou {r.status_code}")
                return None
            return self._parse_html(r.text)
        except Exception as e:
            print(f"[iCarros] HTML falhou: {e}")
        return None

    def _parse_html(self, html: str):
        soup = BeautifulSoup(html, "lxml")

        tag = soup.find("script", id="__NEXT_DATA__")
        if tag and tag.string:
            try:
                data = json.loads(tag.string)
                items = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("anuncios", [])
                )
                if not items:
                    items = (
                        data.get("props", {})
                        .get("pageProps", {})
                        .get("listings", [])
                    )
                if items:
                    cars = [self._normalise_api(i) for i in items]
                    print(f"[iCarros] __NEXT_DATA__: {len(cars)} anúncios")
                    return cars
            except Exception as e:
                print(f"[iCarros] __NEXT_DATA__ parse error: {e}")

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    cars = [self._normalise_jsonld(i) for i in data if i.get("@type") == "Car"]
                    if cars:
                        print(f"[iCarros] JSON-LD: {len(cars)} anúncios")
                        return cars
            except Exception:
                pass

        cards = soup.select("[class*='card'], [class*='anuncio'], [class*='listing']")
        if cards:
            cars = [self._parse_card(c) for c in cards[:50]]
            cars = [c for c in cars if c]
            if cars:
                print(f"[iCarros] HTML cards: {len(cars)} anúncios")
                return cars

        return None

    # ------------------------------------------------------------------ #
    # Normalisation                                                        #
    # ------------------------------------------------------------------ #

    def _normalise_api(self, item: dict) -> dict:
        listing_id = str(item.get("id", item.get("anuncioId", uuid.uuid4())))
        brand = item.get("marca", item.get("brand", item.get("makeName", "")))
        model = item.get("modelo", item.get("model", item.get("modelName", "")))
        version = item.get("versao", item.get("version", item.get("versionName", "")))
        year = int(item.get("anoFabricacao", item.get("year", item.get("yearFabrication", 0))) or 0)
        year_model = int(item.get("anoModelo", item.get("yearModel", year)) or year)
        km = int(item.get("km", item.get("odometer", item.get("quilometragem", 0))) or 0)
        color = item.get("cor", item.get("color", ""))
        price = float(item.get("preco", item.get("price", item.get("valor", 0))) or 0)
        photo = ""
        photos = item.get("fotos", item.get("photos", item.get("images", [])))
        if photos and isinstance(photos, list):
            first = photos[0]
            photo = first if isinstance(first, str) else first.get("url", first.get("path", ""))

        city = item.get("cidade", item.get("city", ""))
        state = item.get("estado", item.get("state", ""))
        transmission = item.get("cambio", item.get("transmission", ""))
        fuel = item.get("combustivel", item.get("fuel", ""))

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
            "transmission": transmission,
            "fuel": fuel,
            "price": price,
            "photo": photo,
            "city": city,
            "state": state,
            "seller_type": item.get("tipoAnunciante", "PF"),
            "seller_name": item.get("anunciante", ""),
            "fipe_price": None,
            "owners": item.get("qtdDonos", 1) or 1,
            "risk_flags": {
                "auction": bool(item.get("origemLeilao", False)),
                "recall": bool(item.get("temRecall", False)),
            },
            "liquidity": "media",
        }

    def _normalise_jsonld(self, item: dict) -> dict:
        listing_id = str(uuid.uuid4())
        offer = item.get("offers", {})
        return {
            "id": listing_id,
            "source": "icarros",
            "source_label": "iCarros",
            "source_url": item.get("url", SEARCH_URL),
            "brand": item.get("brand", {}).get("name", ""),
            "model": item.get("name", ""),
            "version": item.get("model", ""),
            "year": int(item.get("vehicleModelDate", 0) or 0),
            "year_model": int(item.get("vehicleModelDate", 0) or 0),
            "km": int(item.get("mileageFromOdometer", {}).get("value", 0) or 0),
            "color": item.get("color", ""),
            "transmission": item.get("vehicleTransmission", ""),
            "fuel": item.get("fuelType", ""),
            "price": float(offer.get("price", 0) or 0),
            "photo": (item.get("image", [None]) or [None])[0] or "",
            "city": "",
            "state": "",
            "seller_type": "PF",
            "seller_name": "",
            "fipe_price": None,
            "owners": 1,
            "risk_flags": {"auction": False, "recall": False},
            "liquidity": "media",
        }

    def _parse_card(self, card) -> dict | None:
        try:
            price_el = card.select_one("[class*='price'], [class*='preco'], [class*='valor']")
            price = 0.0
            if price_el:
                raw = re.sub(r"[^\d,]", "", price_el.get_text())
                try:
                    price = float(raw.replace(",", "."))
                except Exception:
                    pass

            title_el = card.select_one("[class*='title'], [class*='titulo'], h2, h3")
            title = title_el.get_text(strip=True) if title_el else ""

            link_el = card.select_one("a[href*='/anuncio'], a[href*='/detalhe']")
            url = ""
            listing_id = str(uuid.uuid4())
            if link_el:
                href = link_el.get("href", "")
                url = "https://www.icarros.com.br" + href if href.startswith("/") else href
                m = re.search(r"/(\d+)", url)
                if m:
                    listing_id = m.group(1)

            img_el = card.select_one("img")
            photo = img_el.get("src", img_el.get("data-src", "")) if img_el else ""

            if not title and not price:
                return None

            return {
                "id": listing_id,
                "source": "icarros",
                "source_label": "iCarros",
                "source_url": url or SEARCH_URL,
                "brand": "",
                "model": title,
                "version": "",
                "year": 0,
                "year_model": 0,
                "km": 0,
                "color": "",
                "transmission": "",
                "fuel": "",
                "price": price,
                "photo": photo,
                "city": "",
                "state": "",
                "seller_type": "PF",
                "seller_name": "",
                "fipe_price": None,
                "owners": 1,
                "risk_flags": {"auction": False, "recall": False},
                "liquidity": "media",
            }
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _build_params(self, f: dict, page: int = 1) -> dict:
        p = {"pagina": page}
        if f.get("brand"):
            p["marca"] = f["brand"]
        if f.get("model"):
            p["modelo"] = f["model"]
        if f.get("price_min"):
            p["valorMinimo"] = f["price_min"]
        if f.get("price_max"):
            p["valorMaximo"] = f["price_max"]
        if f.get("year_min"):
            p["anoInicial"] = f["year_min"]
        if f.get("year_max"):
            p["anoFinal"] = f["year_max"]
        if f.get("km_max"):
            p["kmMaximo"] = f["km_max"]
        if f.get("state"):
            p["estado"] = f["state"]
        return p

    def _build_payload(self, f: dict, page: int = 1) -> dict:
        payload: dict = {"pagina": page, "quantidadePorPagina": ITEMS_PER_PAGE}
        if f.get("brand"):
            payload["marcas"] = [{"nome": f["brand"]}]
        if f.get("model"):
            payload["modelos"] = [{"nome": f["model"]}]
        if f.get("price_min"):
            payload["valorMinimo"] = f["price_min"]
        if f.get("price_max"):
            payload["valorMaximo"] = f["price_max"]
        if f.get("year_min"):
            payload["anoInicial"] = f["year_min"]
        if f.get("year_max"):
            payload["anoFinal"] = f["year_max"]
        if f.get("km_max"):
            payload["kmMaximo"] = f["km_max"]
        if f.get("state"):
            payload["estado"] = f["state"]
        return payload
