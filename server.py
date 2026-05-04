import json
import os
import uuid

from flask import Flask, jsonify, request, send_from_directory

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


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)


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
                car.get("brand", ""),
                car.get("model", ""),
                car.get("year", 0),
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
                car.get("brand", ""),
                car.get("model", ""),
                car.get("year", 0),
            )
            break
    save_listings(listings)
    return jsonify({"message": "ok"})


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


if __name__ == "__main__":
    print("=" * 50)
    print("  CarAnalyser - Análise de Carros Usados")
    print("  http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=5000)
