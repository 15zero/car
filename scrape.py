"""
scrape.py — executa o scrape completo do Webmotors e sobe o servidor.

Uso:
    python scrape.py                         # busca todos os anúncios
    python scrape.py --marca Honda           # filtra por marca
    python scrape.py --marca Toyota --modelo Corolla
    python scrape.py --paginas 5             # limita a 5 páginas (120 anúncios)
    python scrape.py --sem-servidor          # só salva o JSON, não sobe Flask
"""

import argparse
import json
import os
import sys

# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Scrape Webmotors e iCarros")
    p.add_argument("--marca",       default="", help="Filtrar por marca (ex: Honda)")
    p.add_argument("--modelo",      default="", help="Filtrar por modelo (ex: Civic)")
    p.add_argument("--ano-min",     type=int, default=0)
    p.add_argument("--ano-max",     type=int, default=0)
    p.add_argument("--km-max",      type=int, default=0)
    p.add_argument("--preco-min",   type=int, default=0)
    p.add_argument("--preco-max",   type=int, default=0)
    p.add_argument("--paginas",     type=int, default=15, help="Máx. de páginas por site (default: 15 = ~360 anúncios)")
    p.add_argument("--fonte",       choices=["webmotors", "icarros", "ambos"], default="webmotors")
    p.add_argument("--token",        default="", help="GeckoAPI token (ou defina GECKO_TOKEN no .env)")
    p.add_argument("--sem-servidor", action="store_true", help="Não sobe o servidor Flask após o scrape")
    p.add_argument("--porta",       type=int, default=5000)
    return p.parse_args()


def progress(source, page, total):
    bar_len = 20
    filled = min(bar_len, page)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] pág. {page:>2} — {total:>4} anúncios ({source})", end="", flush=True)


def run_scrape(filters: dict) -> list:
    from scrapers.webmotors import WebmotorsScraper
    from scrapers.icarros import ICarrosScraper
    from scrapers.fipe import FipeLookup

    results = []
    fonte = filters.get("fonte", "webmotors")

    if fonte in ("webmotors", "ambos"):
        print("\n🔍 Buscando no Webmotors…")
        try:
            scraper = WebmotorsScraper()
            wm = scraper.search(filters, progress_cb=progress)
            print(f"\n  ✓ Webmotors: {len(wm)} anúncios")
            results.extend(wm)
        except Exception as e:
            print(f"\n  ✗ Webmotors erro: {e}")

    if fonte in ("icarros", "ambos"):
        print("\n🔍 Buscando no iCarros…")
        try:
            scraper = ICarrosScraper()
            ic = scraper.search(filters, progress_cb=progress)
            print(f"\n  ✓ iCarros: {len(ic)} anúncios")
            results.extend(ic)
        except Exception as e:
            print(f"\n  ✗ iCarros erro: {e}")

    if not results:
        return []

    # Enrich with FIPE
    print(f"\n📊 Consultando FIPE para {len(results)} anúncios…")
    fipe = FipeLookup()
    for i, car in enumerate(results):
        if not car.get("fipe_price"):
            car["fipe_price"] = fipe.lookup(
                car.get("brand", ""), car.get("model", ""), car.get("year", 0)
            )
        pct = int((i + 1) / len(results) * 20)
        print(f"\r  [{'█'*pct}{'░'*(20-pct)}] {i+1}/{len(results)}", end="", flush=True)
    print(f"\n  ✓ FIPE consultada")

    return results


def save(results: list):
    DATA_FILE = "data/listings.json"
    os.makedirs("data", exist_ok=True)

    existing = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except Exception:
                existing = []

    existing_keys = {f"{c['source']}_{c['id']}" for c in existing}
    added = 0
    for car in results:
        key = f"{car['source']}_{car['id']}"
        if key not in existing_keys:
            existing.insert(0, car)
            existing_keys.add(key)
            added += 1

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    return added, len(existing)


def start_server(port: int):
    import server as srv
    print(f"\n🌐 Servidor iniciado em http://localhost:{port}")
    print("   Pressione Ctrl+C para encerrar.\n")
    srv.app.run(debug=False, host="0.0.0.0", port=port, threaded=True)


# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # GeckoAPI token
    if args.token:
        os.environ["GECKO_TOKEN"] = args.token

    filters = {
        "fonte":     args.fonte,
        "max_pages": args.paginas,
    }
    if args.marca:     filters["brand"]     = args.marca
    if args.modelo:    filters["model"]     = args.modelo
    if args.ano_min:   filters["year_min"]  = args.ano_min
    if args.ano_max:   filters["year_max"]  = args.ano_max
    if args.km_max:    filters["km_max"]    = args.km_max
    if args.preco_min: filters["price_min"] = args.preco_min
    if args.preco_max: filters["price_max"] = args.preco_max

    print()
    print("═" * 52)
    print("  CarAnalyser — Scrape do Webmotors")
    print("═" * 52)
    if filters.get("brand"):  print(f"  Marca:   {filters['brand']}")
    if filters.get("model"):  print(f"  Modelo:  {filters['model']}")
    print(f"  Páginas: até {args.paginas} por site (~{args.paginas*24} anúncios)")
    print(f"  Fonte:   {args.fonte}")
    print("═" * 52)

    results = run_scrape(filters)

    if results:
        added, total_saved = save(results)
        print(f"\n💾 {added} anúncio(s) novo(s) salvos  ({total_saved} total em data/listings.json)")
    else:
        print("\n⚠️  Nenhum anúncio coletado.")
        print("   Certifique-se de que está rodando na sua máquina local (não em servidor).")
        if args.sem_servidor:
            sys.exit(1)

    if not args.sem_servidor:
        start_server(args.porta)


if __name__ == "__main__":
    main()
