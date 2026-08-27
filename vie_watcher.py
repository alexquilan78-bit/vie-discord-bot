"""
VIE Watcher — surveille les nouvelles offres VIE sur mon-vie-via.businessfrance.fr
et envoie une notification Discord (via webhook) quand une offre correspond
aux critères définis dans criteria.json.

Le site étant une application JavaScript (Angular), on utilise Playwright
(navigateur headless) plutôt que de simples requêtes HTTP.

Usage:
    python vie_watcher.py                # scan normal, notifie les nouveautés qui matchent
    python vie_watcher.py --seed-only    # marque les offres actuelles comme "vues" sans notifier
    python vie_watcher.py --debug        # sauvegarde debug.html / debug.png pour inspection
"""

import json
import os
import re
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SEARCH_URL = "https://mon-vie-via.businessfrance.fr/en/offres/recherche?sort=0"
SEEN_FILE = Path("seen_offers.json")
CRITERIA_FILE = Path("criteria.json")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"Attention: {path} n'est pas un JSON valide, utilisation de la valeur par défaut.")
            return default
    return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def matches_criteria(text: str, criteria: dict) -> bool:
    """Retourne True si le texte de l'offre correspond aux critères.

    - keywords: au moins UN mot-clé doit apparaître (titre, poste, description...)
    - countries: au moins UN pays doit apparaître
    - exclude_keywords: si un seul de ces mots apparaît, l'offre est rejetée
    Une catégorie vide dans criteria.json n'est pas prise en compte (pas de filtre).
    """
    text_low = text.lower()

    keywords = [k.lower() for k in criteria.get("keywords", [])]
    countries = [c.lower() for c in criteria.get("countries", [])]
    exclude = [e.lower() for e in criteria.get("exclude_keywords", [])]

    if exclude and any(e in text_low for e in exclude):
        return False
    if keywords and not any(k in text_low for k in keywords):
        return False
    if countries and not any(c in text_low for c in countries):
        return False
    return True


FIELD_LABELS = {
    "entreprise": ["Entreprise", "Société"],
    "localisation": ["Localisation", "Lieu de la mission", "Ville"],
    "duree": ["Durée", "Duree", "Durée de la mission"],
    "indemnite": ["Indemnité", "Indemnite", "Indemnité mensuelle"],
    "debut": ["Début", "Debut", "Date de début"],
    "reference": ["Référence", "Reference", "Réf."],
}


def extract_field(lines: list, labels: list) -> str | None:
    """Cherche un label parmi une liste de lignes de texte brut.

    Gère deux mises en page courantes:
      - "Label : valeur" sur la même ligne
      - "Label" seul, suivi de la valeur sur une des lignes suivantes
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        for label in labels:
            same_line = re.match(rf"^{re.escape(label)}\s*[:\-]\s*(.+)$", stripped, re.IGNORECASE)
            if same_line and same_line.group(1).strip():
                return same_line.group(1).strip()
            if stripped.lower() == label.lower():
                for j in range(i + 1, min(i + 3, len(lines))):
                    candidate = lines[j].strip()
                    if candidate and candidate.lower() not in (l.lower() for l in labels):
                        return candidate
    return None


def scrape_offers(max_offers: int = 80, debug: bool = False) -> dict:
    """Charge la page de recherche et repère les offres visibles (id + URL).

    Approche volontairement générique: on repère tous les liens qui pointent
    vers /offres/<id> plutôt que de dépendre de noms de classes CSS précis,
    qui peuvent changer sans préavis.
    """
    offers = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="fr-FR")
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)  # laisse le temps à Angular de finir de rendre

        # Certaines listes se chargent au scroll (lazy loading) : on force un peu.
        for _ in range(5):
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(800)

        links = page.locator("a[href*='/offres/']")
        count = links.count()

        for i in range(count):
            href = links.nth(i).get_attribute("href") or ""
            m = re.search(r"/offres/(\d+)", href)
            if not m:
                continue
            offer_id = m.group(1)
            if offer_id in offers:
                continue

            full_url = f"https://mon-vie-via.businessfrance.fr/fr/offres/{offer_id}"
            offers[offer_id] = {"id": offer_id, "url": full_url}
            if len(offers) >= max_offers:
                break

        if debug:
            page.screenshot(path="debug_listing.png", full_page=True)
            Path("debug_listing.html").write_text(page.content(), encoding="utf-8")
            print("Mode debug: debug_listing.html et debug_listing.png générés.")

        browser.close()
    return offers


def scrape_offer_detail(browser, url: str, debug: bool = False) -> dict:
    """Ouvre la page de détail d'une offre et en extrait les champs structurés."""
    page = browser.new_page(locale="fr-FR")
    page.goto(url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2500)

    title = ""
    try:
        h1 = page.locator("h1").first
        if h1.count() > 0:
            title = h1.inner_text().strip()
    except Exception:  # noqa: BLE001
        pass

    body_text = page.inner_text("body")
    lines = [l for l in body_text.splitlines() if l.strip()]

    if not title:
        title = lines[0] if lines else "Nouvelle offre VIE"

    fields = {key: extract_field(lines, labels) for key, labels in FIELD_LABELS.items()}

    if not fields.get("reference"):
        ref_match = re.search(r"\bVIE\d{4,8}\b", body_text)
        if ref_match:
            fields["reference"] = ref_match.group(0)

    if debug:
        offer_id = re.search(r"/offres/(\d+)", url).group(1)
        page.screenshot(path=f"debug_offer_{offer_id}.png", full_page=True)
        Path(f"debug_offer_{offer_id}.html").write_text(page.content(), encoding="utf-8")

    page.close()
    return {"title": title, **fields}


def build_search_text(title: str, details: dict) -> str:
    """Texte concaténé utilisé pour le filtrage par mots-clés / pays."""
    parts = [title] + [v for v in details.values() if v]
    return " ".join(parts)


def send_discord_notification(offer_url: str, title: str, details: dict) -> None:
    def val(key: str) -> str:
        return details.get(key) or "Non précisé"

    payload = {
        "embeds": [
            {
                "title": f"🚀 {title}"[:256],
                "url": offer_url,
                "color": 3066993,
                "fields": [
                    {"name": "🏢 Entreprise", "value": val("entreprise"), "inline": True},
                    {"name": "📍 Localisation", "value": val("localisation"), "inline": True},
                    {"name": "🗓️ Durée", "value": val("duree"), "inline": True},
                    {"name": "💰 Indemnité", "value": val("indemnite"), "inline": True},
                    {"name": "📅 Début", "value": val("debut"), "inline": True},
                    {"name": "📇 Référence", "value": val("reference"), "inline": True},
                    {
                        "name": "🔗 Lien",
                        "value": f"[Voir l'offre sur Business France]({offer_url})",
                        "inline": False,
                    },
                ],
                "footer": {"text": "Alerte VIE • Business France"},
                "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            }
        ]
    }
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()


def main() -> None:
    debug = "--debug" in sys.argv
    seed_only = "--seed-only" in sys.argv

    if not seed_only and not DISCORD_WEBHOOK_URL:
        print("ERREUR: la variable d'environnement DISCORD_WEBHOOK_URL n'est pas définie.", file=sys.stderr)
        sys.exit(1)

    criteria = load_json(CRITERIA_FILE, {})
    seen = load_json(SEEN_FILE, {})

    offers = scrape_offers(debug=debug)
    print(f"{len(offers)} offre(s) récupérée(s) sur la page de recherche.")

    new_offer_ids = [oid for oid in offers if oid not in seen]

    new_matches = 0
    if new_offer_ids:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for offer_id in new_offer_ids:
                offer = offers[offer_id]
                seen[offer_id] = True  # marquée comme vue dès qu'on l'a traitée, matche ou non

                if seed_only:
                    continue

                try:
                    details = scrape_offer_detail(browser, offer["url"], debug=debug)
                except Exception as exc:  # noqa: BLE001
                    print(f"Erreur lors de la lecture de l'offre {offer['url']}: {exc}", file=sys.stderr)
                    continue

                title = details.pop("title")
                search_text = build_search_text(title, details)

                if matches_criteria(search_text, criteria):
                    print(f"-> Nouvelle offre correspondante: {offer['url']}")
                    try:
                        send_discord_notification(offer["url"], title, details)
                        new_matches += 1
                    except Exception as exc:  # noqa: BLE001
                        print(f"Erreur lors de l'envoi à Discord: {exc}", file=sys.stderr)
            browser.close()

    save_json(SEEN_FILE, seen)

    if seed_only:
        print(f"Seed effectué: {len(seen)} offre(s) au total marquée(s) comme déjà vues, aucune notification envoyée.")
    else:
        print(f"{new_matches} nouvelle(s) offre(s) correspondante(s) envoyée(s) sur Discord.")


if __name__ == "__main__":
    main()
