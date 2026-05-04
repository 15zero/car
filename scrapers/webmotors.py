"""
Scraper for Webmotors listings.

Strategies (in order):
  1. Internal JSON API  (/api/search/car) — paginates through all pages
  2. __NEXT_DATA__ embedded JSON in page HTML
  3. __PRELOADED_STATE__ script variable
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
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
}

SEARCH_URL = "https://www.webmotors.com.br/carros/estoque"
API_URL = "https://www.webmotors.com.br/api/search/car"
ITEMS_PER_PAGE = 24
DEFAULT_MAX_PAGES = 15  # 360 cars max


class WebmotorsScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(BASE_HEADERS)

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #

    def search(self, filters: dict, progress_cb=None) -> list:
        """Fetch all pages matching filters. progress_cb(page, total) optional."""
        params = self._build_params(filters)
        max_pages = int(filters.get("max_pages", DEFAULT_MAX_PAGES))

        # Warm up session with a browser-like GET to avoid 403
        self._warm_session()

        all_results = []
        for page in range(1, max_pages + 1):
            batch = self._try_api(params, page)
            if batch is None:
                # API unavailable — fall back to HTML for page 1 only
                if page == 1:
                    batch = self._try_html(params) or []
                else:
                    break

            if not batch:
                print(f"[Webmotors] Página {page}: vazia, encerrando.")
                break

            all_results.extend(batch)
            print(f"[Webmotors] Página {page}: {len(batch)} anúncios (total: {len(all_results)})")

            if progress_cb:
                progress_cb("webmotors", page, len(all_results))

            if len(batch) < ITEMS_PER_PAGE:
                # Last page (partial)
                break

            # Polite delay to avoid rate limiting
            time.sleep(0.5)

        # Deduplicate by id
        seen = set()
        unique = []
        for car in all_results:
            if car["id"] not in seen:
                seen.add(car["id"])
                unique.append(car)

        print(f"[Webmotors] Total: {len(unique)} anúncios únicos em {page} página(s)")
        return unique

    # ------------------------------------------------------------------ #
    # Strategy 1: Internal JSON API                                        #
    # ------------------------------------------------------------------ #

    def _try_api(self, params: dict, page: int):
        page_url = SEARCH_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        api_params = {
            "url": page_url,
            "actualPage": page,
            "itemsPerPage": ITEMS_PER_PAGE,
            "showMenu": "true",
            "hasVehicleLeadForm": "false",
        }
        headers = {
            **BASE_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.webmotors.com.br/",
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            r = self.session.get(API_URL, params=api_params, headers=headers, timeout=20)
            if r.status_code == 200:
                data = r.json()
                items = data.get("SearchResults", [])
                return self._parse_api_results(items)
            elif r.status_code in (403, 429):
                print(f"[Webmotors] API bloqueada ({r.status_code}) — use a aplicação localmente")
                return None
        except Exception as e:
            print(f"[Webmotors] API erro p{page}: {e}")
        return None

    # ------------------------------------------------------------------ #
    # Strategy 2/3: HTML page parsing                                     #
    # ------------------------------------------------------------------ #

    def _warm_session(self):
        """Visit the homepage to get cookies before scraping."""
        try:
            headers = {
                **BASE_HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            self.session.get("https://www.webmotors.com.br/", headers=headers, timeout=10)
        except Exception:
            pass

    def _try_html(self, params: dict):
        headers = {
            **BASE_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }
        try:
            r = self.session.get(SEARCH_URL, params=params, headers=headers, timeout=20)
            if r.status_code != 200:
                print(f"[Webmotors] HTML retornou {r.status_code}")
                return None
            return self._parse_html(r.text)
        except Exception as e:
            print(f"[Webmotors] HTML falhou: {e}")
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
                    .get("searchResult", {})
                    .get("SearchResults", [])
                )
                if items:
                    cars = self._parse_api_results(items)
                    print(f"[Webmotors] __NEXT_DATA__: {len(cars)} anúncios")
                    return cars
            except Exception as e:
                print(f"[Webmotors] __NEXT_DATA__ parse error: {e}")

        for script in soup.find_all("script"):
            text = script.string or ""
            if "__PRELOADED_STATE__" in text:
                m = re.search(r"__PRELOADED_STATE__\s*=\s*(\{.+?\});", text, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        items = data.get("searchResult", {}).get("SearchResults", [])
                        if items:
                            cars = self._parse_api_results(items)
                            print(f"[Webmotors] PRELOADED_STATE: {len(cars)} anúncios")
                            return cars
                    except Exception as e:
                        print(f"[Webmotors] PRELOADED_STATE parse error: {e}")

        return None

    # ------------------------------------------------------------------ #
    # Normalisation                                                        #
    # ------------------------------------------------------------------ #

    def _parse_api_results(self, items: list) -> list:
        cars = []
        for item in items:
            try:
                cars.append(self._normalise(item))
            except Exception as e:
                print(f"[Webmotors] Normalise error: {e}")
        return cars

    def _normalise(self, item: dict) -> dict:
        spec = item.get("Specification", {})
        media = item.get("Media", {})
        prices = item.get("Prices", {})
        seller = item.get("Seller", {})

        photos = media.get("Photos", [])
        photo = photos[0].get("Path", "") if photos else ""

        listing_id = str(item.get("UniqueId", uuid.uuid4()))

        return {
            "id": listing_id,
            "source": "webmotors",
            "source_label": "Webmotors",
            "source_url": f"https://www.webmotors.com.br/carros/anuncio/{listing_id}",
            "brand": spec.get("Make", {}).get("Value", ""),
            "model": spec.get("Model", {}).get("Value", ""),
            "version": spec.get("Version", {}).get("Value", ""),
            "year": spec.get("YearFabrication", 0),
            "year_model": spec.get("YearModel", 0),
            "km": spec.get("Odometer", 0),
            "color": spec.get("Color", {}).get("Primary", {}).get("Value", ""),
            "transmission": spec.get("Transmission", {}).get("Value", ""),
            "fuel": spec.get("Fuel", {}).get("Value", ""),
            "price": prices.get("Price", 0),
            "photo": photo,
            "city": seller.get("City", ""),
            "state": seller.get("State", ""),
            "seller_type": seller.get("Type", "PF"),
            "seller_name": seller.get("Name", ""),
            "fipe_price": None,
            "owners": item.get("OwnersCount", 1) or 1,
            "risk_flags": {
                "auction": bool(item.get("AuctionOrigin", False)),
                "recall": bool(item.get("HasOpenRecall", False)),
            },
            "liquidity": "media",
        }

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _build_params(self, f: dict) -> dict:
        p = {"TipoPessoa": "F", "Pesquisa": "True"}
        if f.get("brand"):
            p["marca"] = f["brand"]
        if f.get("model"):
            p["modelo"] = f["model"]
        if f.get("price_min"):
            p["preco_de"] = f["price_min"]
        if f.get("price_max"):
            p["preco_ate"] = f["price_max"]
        if f.get("year_min"):
            p["ano_de"] = f["year_min"]
        if f.get("year_max"):
            p["ano_ate"] = f["year_max"]
        if f.get("km_max"):
            p["km_ate"] = f["km_max"]
        if f.get("state"):
            p["estado"] = f["state"]
        if f.get("city"):
            p["cidade"] = f["city"]
        return p
