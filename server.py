import json
import os
import queue
import threading
import uuid

# Load .env file if present (sets GECKO_TOKEN etc.)
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from flask import Flask, Response, jsonify, request, send_from_directory

from scrapers.fipe import FipeLookup
from scrapers.icarros import ICarrosScraper
from scrapers.webmotors import WebmotorsScraper

app = Flask(__name__, static_folder="static")
DATA_FILE = "data/listings.json"


def load_listings():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_listings(listings):
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ #
# Static                                                               #
# ------------------------------------------------------------------ #

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)


# ------------------------------------------------------------------ #
# Search — with Server-Sent Events progress stream                    #
# ------------------------------------------------------------------ #

@app.route("/api/search/stream", methods=["POST"])
def search_stream():
    """
    SSE endpoint: streams progress events while scraping, then sends the
    final result as a 'done' event.

    Client-side usage:
        const es = new EventSource('/api/search/stream');  // won't work with POST body
    Instead we store filters in a session key and GET it, or accept query params.

    Since SSE requires GET, the frontend POSTS filters to /api/search/prepare
    which stores them under a token, then GETs /api/search/stream?token=X.
    """
    return jsonify({"error": "Use GET with token from /api/search/prepare"}), 405


_pending_searches: dict = {}


@app.route("/api/search/prepare", methods=["POST"])
def search_prepare():
    """Store search filters, return a short-lived token for the SSE stream."""
    filters = request.json or {}
    token = str(uuid.uuid4())
    _pending_searches[token] = filters
    return jsonify({"token": token})


@app.route("/api/search/stream")
def search_stream_get():
    """SSE stream: scrape both sites and push progress + final results."""
    token = request.args.get("token", "")
    filters = _pending_searches.pop(token, None)
    if filters is None:
        return jsonify({"error": "Token inválido ou expirado"}), 400

    q: queue.Queue = queue.Queue()

    def progress_cb(source: str, page: int, total: int):
        q.put({"type": "progress", "source": source, "page": page, "total": total})

    def run():
        results = []
        errors = []
        sources = filters.get("sources", ["webmotors", "icarros"])

        if "webmotors" in sources:
            try:
                q.put({"type": "status", "msg": "Buscando no Webmotors…"})
                scraper = WebmotorsScraper()
                wm = scraper.search(filters, progress_cb=progress_cb)
                results.extend(wm)
                q.put({"type": "status", "msg": f"Webmotors: {len(wm)} anúncios encontrados"})
            except Exception as e:
                errors.append(f"Webmotors: {e}")
                q.put({"type": "status", "msg": f"Webmotors erro: {e}"})

        if "icarros" in sources:
            try:
                q.put({"type": "status", "msg": "Buscando no iCarros…"})
                scraper = ICarrosScraper()
                ic = scraper.search(filters, progress_cb=progress_cb)
                results.extend(ic)
                q.put({"type": "status", "msg": f"iCarros: {len(ic)} anúncios encontrados"})
            except Exception as e:
                errors.append(f"iCarros: {e}")
                q.put({"type": "status", "msg": f"iCarros erro: {e}"})

        # Enrich with FIPE
        q.put({"type": "status", "msg": f"Consultando FIPE para {len(results)} anúncios…"})
        fipe = FipeLookup()
        for i, car in enumerate(results):
            if not car.get("fipe_price"):
                car["fipe_price"] = fipe.lookup(
                    car.get("brand", ""), car.get("model", ""), car.get("year", 0)
                )
            if i % 10 == 0:
                q.put({"type": "fipe_progress", "done": i, "total": len(results)})

        # Merge with existing saved listings
        existing = load_listings()
        existing_keys = {f"{c['source']}_{c['id']}" for c in existing}
        added = 0
        for car in results:
            key = f"{car['source']}_{car['id']}"
            if key not in existing_keys:
                existing.insert(0, car)
                existing_keys.add(key)
                added += 1
        save_listings(existing)

        q.put({"type": "done", "results": results, "total": len(results), "added": added, "errors": errors})

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    def generate():
        while True:
            try:
                event = q.get(timeout=120)
            except queue.Empty:
                yield "event: error\ndata: {\"msg\": \"timeout\"}\n\n"
                break

            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

            if event["type"] == "done":
                break

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ #
# Simple (non-streaming) search — kept for backwards compat           #
# ------------------------------------------------------------------ #

@app.route("/api/search", methods=["POST"])
def search():
    filters = request.json or {}
    sources = filters.get("sources", ["webmotors", "icarros"])
    results = []
    errors = []

    if "webmotors" in sources:
        try:
            scraper = WebmotorsScraper()
            wm_results = scraper.search(filters)
            results.extend(wm_results)
        except Exception as e:
            errors.append(f"Webmotors: {str(e)}")

    if "icarros" in sources:
        try:
            scraper = ICarrosScraper()
            ic_results = scraper.search(filters)
            results.extend(ic_results)
        except Exception as e:
            errors.append(f"iCarros: {str(e)}")

    fipe = FipeLookup()
    for car in results:
        if not car.get("fipe_price"):
            car["fipe_price"] = fipe.lookup(
                car.get("brand", ""), car.get("model", ""), car.get("year", 0)
            )

    existing = load_listings()
    existing_keys = {f"{c['source']}_{c['id']}" for c in existing}
    added = 0
    for car in results:
        key = f"{car['source']}_{car['id']}"
        if key not in existing_keys:
            existing.insert(0, car)
            existing_keys.add(key)
            added += 1
    save_listings(existing)

    return jsonify({"results": results, "total": len(results), "added": added, "errors": errors})


# ------------------------------------------------------------------ #
# Listings CRUD                                                        #
# ------------------------------------------------------------------ #

@app.route("/api/listings", methods=["GET"])
def get_listings():
    return jsonify({"listings": load_listings()})


@app.route("/api/listings", methods=["DELETE"])
def clear_listings():
    save_listings([])
    return jsonify({"message": "ok"})


@app.route("/api/listing/<listing_id>", methods=["DELETE"])
def delete_listing(listing_id):
    listings = [l for l in load_listings() if l.get("id") != listing_id]
    save_listings(listings)
    return jsonify({"message": "ok"})


@app.route("/api/listing/add", methods=["POST"])
def add_listing():
    listing = request.json or {}
    listing["id"] = str(uuid.uuid4())
    listing.setdefault("source", "manual")
    listing.setdefault("risk_flags", {"auction": False, "recall": False})
    listing.setdefault("owners", 1)

    if not listing.get("fipe_price") and listing.get("brand") and listing.get("model"):
        fipe = FipeLookup()
        listing["fipe_price"] = fipe.lookup(
            listing["brand"], listing["model"], listing.get("year", 0)
        )

    listings = load_listings()
    listings.insert(0, listing)
    save_listings(listings)
    return jsonify({"listing": listing})


@app.route("/api/listing/<listing_id>/fipe", methods=["POST"])
def refresh_fipe(listing_id):
    listings = load_listings()
    fipe = FipeLookup()
    for car in listings:
        if car.get("id") == listing_id:
            car["fipe_price"] = fipe.lookup(
                car.get("brand", ""), car.get("model", ""), car.get("year", 0)
            )
            break
    save_listings(listings)
    return jsonify({"message": "ok"})


# ------------------------------------------------------------------ #
# FIPE helpers                                                         #
# ------------------------------------------------------------------ #

@app.route("/api/fipe/brands")
def fipe_brands():
    fipe = FipeLookup()
    return jsonify(fipe.get_brands())


@app.route("/api/fipe/lookup")
def fipe_price():
    brand = request.args.get("brand", "")
    model = request.args.get("model", "")
    year = int(request.args.get("year", 0))
    fipe = FipeLookup()
    price = fipe.lookup(brand, model, year)
    return jsonify({"price": price})


# ------------------------------------------------------------------ #
# Start                                                                #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    print()
    print("=" * 55)
    print("  CarAnalyser — Análise de Carros Usados")
    print("=" * 55)
    print("  Abra no navegador:  http://localhost:5000")
    print("=" * 55)
    print()
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
