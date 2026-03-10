#!/usr/bin/env python3
"""
LeadRadar Backend v5
- Datenquelle: OpenStreetMap Overpass API (kostenlos, kein API-Key, Railway-kompatibel)
- Liefert echte Unternehmen MIT Website
- Filtert Ketten/Franchises und geschlossene Betriebe
- Bewertet Website-Qualitaet
"""

from flask import Flask, jsonify, request, send_from_directory
import requests
from bs4 import BeautifulSoup
import time
import re
import os
from urllib.parse import quote_plus
from datetime import datetime
import json
import urllib3
urllib3.disable_warnings()

app = Flask(__name__, static_folder=".")

HEADERS = {
    "User-Agent": "LeadRadar/1.0 (lead-research-tool)",
    "Accept": "application/json",
}

HEADERS_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# OSM amenity-Tags die zu Branchen-Keywords passen
AMENITY_MAP = {
    "restaurant": ["restaurant", "fast_food", "cafe", "bar", "pub", "food_court", "biergarten"],
    "cafe": ["cafe", "coffee_shop"],
    "bar": ["bar", "pub", "nightclub"],
    "hotel": ["hotel", "motel", "hostel", "guest_house"],
    "friseur": ["hairdresser"],
    "hairdresser": ["hairdresser"],
    "arzt": ["doctors", "dentist", "clinic", "pharmacy"],
    "zahnarzt": ["dentist"],
    "apotheke": ["pharmacy"],
    "fitnessstudio": ["gym", "fitness_centre"],
    "gym": ["gym", "fitness_centre"],
    "autowerkstatt": ["car_repair"],
    "werkstatt": ["car_repair", "workshop"],
    "supermarkt": ["supermarket", "convenience"],
    "baeckerei": ["bakery"],
    "bäckerei": ["bakery"],
    "metzger": ["butcher"],
    "blumen": ["florist"],
    "optiker": ["optician"],
    "rechtsanwalt": ["lawyers"],
    "steuerberater": ["accountant"],
    "reinigung": ["dry_cleaning", "laundry"],
    "tankstelle": ["fuel"],
    "kiosk": ["kiosk", "newsagent"],
}

SHOP_MAP = {
    "baeckerei": ["bakery"],
    "bäckerei": ["bakery"],
    "metzger": ["butcher"],
    "blumen": ["florist"],
    "optiker": ["optician"],
    "handwerker": ["hardware", "doityourself"],
    "elektriker": ["electronics"],
    "moebel": ["furniture"],
    "möbel": ["furniture"],
    "kleidung": ["clothes", "fashion"],
    "schuhe": ["shoes"],
    "spielzeug": ["toys"],
    "buchhandlung": ["books"],
    "supermarkt": ["supermarket", "convenience"],
    "friseur": ["hairdresser"],
    "hairdresser": ["hairdresser"],
}

CRAFT_MAP = {
    "handwerker": ["carpenter", "electrician", "plumber", "painter", "builder", "roofer", "glazier"],
    "zimmermann": ["carpenter"],
    "elektriker": ["electrician"],
    "klempner": ["plumber"],
    "maler": ["painter"],
    "dachdecker": ["roofer"],
    "schreiner": ["carpenter", "cabinet_maker"],
    "sanitaer": ["plumber", "hvac"],
}

CHAIN_BLACKLIST = [
    "subway","mcdonald","burger king","kfc","pizza hut","domino","vapiano",
    "nordsee","wienerwald","hans im gluck","peter pane","enchilada","l'osteria",
    "dean david","dean & david","ditsch","backwerk","le crobag","jim block",
    "five guys","dunkin","starbucks","costa coffee","tchibo","balzac",
    "aldi","lidl","rewe","edeka","penny","netto","kaufland",
    "dm drogerie","rossmann","saturn","mediamarkt","ikea","obi ","bauhaus",
    "hornbach","toom","hagebau","deichmann","snipes","foot locker",
    "h&m","zara","primark","c&a","esprit","douglas","thalia","hugendubel",
    "fielmann","apollo optik","mcfit","fitx","clever fit","fitness first",
    "sixt","hertz","europcar","telekom shop","o2 shop","vodafone shop",
    "motel one","ibis ","novotel","mercure","holiday inn","hilton","marriott",
    "radisson","a&o hostel","meininger","takko","kik ","nkd ","woolworth",
    "norma ","action ","tedi ","zeeman",
]


def is_chain(name):
    n = name.lower()
    return any(c in n for c in CHAIN_BLACKLIST)


def get_osm_area_id(city):
    """Holt die OSM Area-ID fuer eine Stadt via Nominatim."""
    url = f"https://nominatim.openstreetmap.org/search?q={quote_plus(city)}&format=json&limit=1&addressdetails=1"
    try:
        r = requests.get(url, headers={"User-Agent": "LeadRadar/1.0"}, timeout=10)
        data = r.json()
        if data:
            osm_id = int(data[0].get("osm_id", 0))
            osm_type = data[0].get("osm_type", "")
            # Fuer Relations: area_id = osm_id + 3600000000
            if osm_type == "relation":
                return osm_id + 3600000000
            elif osm_type == "way":
                return osm_id + 2400000000
            else:
                return osm_id
    except Exception as e:
        print(f"  [NOMINATIM] Fehler: {e}")
    return None


def query_overpass(amenity_types, shop_types, craft_types, area_id, max_results):
    """
    Fragt OpenStreetMap Overpass API ab.
    Gibt nur Eintraege MIT website-Tag zurueck.
    """
    results = []

    # Overpass QL Query aufbauen
    # Wir suchen nach Nodes und Ways mit website-Tag in der Zielstadt
    queries = []

    for at in amenity_types:
        queries.append(f'node["amenity"="{at}"]["website"](area:{area_id});')
        queries.append(f'way["amenity"="{at}"]["website"](area:{area_id});')

    for st in shop_types:
        queries.append(f'node["shop"="{st}"]["website"](area:{area_id});')
        queries.append(f'way["shop"="{st}"]["website"](area:{area_id});')

    for ct in craft_types:
        queries.append(f'node["craft"="{ct}"]["website"](area:{area_id});')
        queries.append(f'way["craft"="{ct}"]["website"](area:{area_id});')

    # Falls keine spezifischen Tags: allgemeine Suche nach allem mit Website
    if not queries:
        queries = [
            f'node["name"]["website"](area:{area_id});',
            f'way["name"]["website"](area:{area_id});',
        ]

    union_body = "\n  ".join(queries)
    overpass_query = f"""
[out:json][timeout:30];
area({area_id})->.searchArea;
(
  {union_body}
);
out body {max_results * 4};
"""

    print(f"  [OSM] Query fuer area_id={area_id}")
    print(f"  [OSM] Suche nach: amenity={amenity_types}, shop={shop_types}, craft={craft_types}")

    try:
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": overpass_query},
            headers={"User-Agent": "LeadRadar/1.0"},
            timeout=35
        )
        data = r.json()
        elements = data.get("elements", [])
        print(f"  [OSM] {len(elements)} Rohergebnisse mit Website")

        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name", "").strip()
            website = tags.get("website", "").strip()
            phone = tags.get("phone", tags.get("contact:phone", "")).strip()
            email = tags.get("email", tags.get("contact:email", "")).strip()

            # Adresse zusammensetzen
            street  = tags.get("addr:street", "")
            housenr = tags.get("addr:housenumber", "")
            postcode = tags.get("addr:postcode", "")
            city_tag = tags.get("addr:city", "")
            address = f"{street} {housenr}, {postcode} {city_tag}".strip().strip(",").strip()

            if not name or not website:
                continue
            if is_chain(name):
                print(f"  [SKIP] Kette: {name}")
                continue

            # Website normalisieren
            if not website.startswith("http"):
                website = "https://" + website
            website = website.rstrip("/")

            results.append({
                "name": name,
                "website": website,
                "phone": phone,
                "email": email,
                "address": address,
                "source": "OpenStreetMap",
            })

            if len(results) >= max_results * 2:
                break

    except Exception as e:
        print(f"  [OSM] Fehler: {e}")

    return results


def get_tags_for_query(query_raw):
    """Wandelt einen Suchbegriff in OSM-Tags um."""
    q = query_raw.lower().strip()

    amenity = set()
    shop = set()
    craft = set()

    for kw, tags in AMENITY_MAP.items():
        if kw in q or q in kw:
            amenity.update(tags)

    for kw, tags in SHOP_MAP.items():
        if kw in q or q in kw:
            shop.update(tags)

    for kw, tags in CRAFT_MAP.items():
        if kw in q or q in kw:
            craft.update(tags)

    # Fallback: direkt als amenity/shop versuchen
    if not amenity and not shop and not craft:
        amenity = {q}
        shop = {q}
        craft = {q}

    return list(amenity), list(shop), list(craft)


# ─────────────────────────────────────────
#  WEBSITE-QUALITAET
# ─────────────────────────────────────────

def check_website(url):
    result = {
        "has_website": True,
        "is_reachable": False,
        "score": 0,
        "issues": [],
        "status_code": None,
        "load_time": None,
        "has_ssl": False,
        "is_mobile_friendly": False,
        "has_content": False,
        "page_size_kb": 0,
        "recommendation": "KEIN LEAD",
        "rec_class": "none",
    }

    if not url.startswith("http"):
        url = "https://" + url

    result["has_ssl"] = url.startswith("https://")
    if not result["has_ssl"]:
        result["issues"].append("Kein HTTPS/SSL")
        result["score"] -= 20

    start = time.time()
    try:
        resp = requests.get(url, headers=HEADERS_WEB, timeout=10,
                            verify=False, allow_redirects=True)
        load_time = round(time.time() - start, 2)
        result["load_time"] = load_time
        result["status_code"] = resp.status_code
        result["is_reachable"] = resp.status_code < 400

        if load_time > 5:
            result["issues"].append(f"Extrem langsam ({load_time}s)")
            result["score"] -= 20
        elif load_time > 3:
            result["issues"].append(f"Langsam ({load_time}s)")
            result["score"] -= 10

        if resp.status_code >= 400:
            result["issues"].append(f"HTTP {resp.status_code} Fehler")
            result["recommendation"] = "TOP LEAD - Website nicht erreichbar"
            result["rec_class"] = "top"
            result["score"] = 5
            return result

        page_lower = resp.text.lower()

        # Inaktive / geparkte Domain
        for kw in ["domain expired", "account suspended", "parked domain",
                   "under construction", "coming soon", "diese domain"]:
            if kw in page_lower:
                result["issues"].append(f"Inaktive Domain")
                result["score"] -= 40
                break

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text(strip=True)
        result["page_size_kb"] = round(len(resp.text) / 1024, 1)

        # Inhalt
        if len(text) < 300:
            result["issues"].append("Kaum Inhalt (Under Construction?)")
            result["score"] -= 30
        elif len(text) < 800:
            result["issues"].append("Wenig Inhalt")
            result["score"] -= 10
        else:
            result["has_content"] = True
            result["score"] += 20

        # Mobile
        if soup.find("meta", {"name": "viewport"}):
            result["is_mobile_friendly"] = True
            result["score"] += 10
        else:
            result["issues"].append("Nicht mobile-optimiert")
            result["score"] -= 15

        # Veraltetes Copyright
        for yr_match in re.findall(r'copyright\D{0,5}(\d{4})|&copy;\D{0,5}(\d{4})', page_lower):
            yr_str = yr_match[0] or yr_match[1]
            if yr_str:
                yr = int(yr_str)
                if yr < datetime.now().year - 3:
                    result["issues"].append(f"Seit {yr} nicht aktualisiert")
                    result["score"] -= 20
                    break

        # Veraltetes HTML
        if re.search(r'cellpadding|cellspacing|bgcolor=', resp.text, re.I):
            result["issues"].append("Veraltetes HTML-Layout")
            result["score"] -= 10

        # Kein Meta-Description
        if not soup.find("meta", {"name": "description"}):
            result["issues"].append("Kein Meta-Description (SEO)")
            result["score"] -= 5

        # Modernes CMS/Framework
        if any(x in page_lower for x in ["wordpress", "shopify", "typo3", "joomla",
               "wix", "squarespace", "jimdo", "react", "vue", "angular", "next"]):
            result["score"] += 10

        result["score"] = max(0, min(100, 50 + result["score"]))

    except requests.exceptions.SSLError:
        result["issues"].append("SSL-Zertifikat ungueltig")
        result["recommendation"] = "TOP LEAD - SSL-Fehler"
        result["rec_class"] = "top"
        result["score"] = 8
        return result
    except requests.exceptions.ConnectionError:
        result["issues"].append("Domain nicht erreichbar")
        result["recommendation"] = "TOP LEAD - Website tot"
        result["rec_class"] = "top"
        result["score"] = 5
        return result
    except requests.exceptions.Timeout:
        result["issues"].append("Timeout (>10s)")
        result["recommendation"] = "TOP LEAD - Extrem langsam"
        result["rec_class"] = "top"
        result["score"] = 8
        return result
    except Exception as e:
        result["issues"].append(f"Fehler: {str(e)[:60]}")
        result["score"] = 15

    s = result["score"]
    if s < 15:
        result["recommendation"] = "TOP LEAD - Sehr schlechte Website"
        result["rec_class"] = "top"
    elif s < 32:
        result["recommendation"] = "TOP LEAD - Schlechte Website"
        result["rec_class"] = "top"
    elif s < 48:
        result["recommendation"] = "GUTER LEAD - Verbesserungsbedarf"
        result["rec_class"] = "good"
    elif s < 62:
        result["recommendation"] = "MOEGLICHER LEAD - Ausbaufaehig"
        result["rec_class"] = "possible"
    else:
        result["recommendation"] = "KEIN LEAD - Website OK"
        result["rec_class"] = "none"

    return result


def make_outreach(biz, wc):
    name = biz.get("name", "Ihr Unternehmen")
    issues = wc.get("issues", [])

    if not wc.get("is_reachable"):
        subj = f"Ihre Website ist nicht erreichbar - {name}"
        body = (f"Guten Tag,\n\nIhre Website ist aktuell nicht erreichbar. "
                f"Kunden, die online nach {name} suchen, landen auf einer toten Seite "
                f"und wechseln zur Konkurrenz.\n\n"
                f"Ich kann helfen, das schnell zu beheben.\n\nMit freundlichen Gruessen")
    elif issues:
        main = issues[0]
        if "langsam" in main.lower() or "timeout" in main.lower():
            prob = f"Ihre Website laedt sehr langsam ({main}). 53% der Nutzer verlassen eine Seite, die laenger als 3 Sekunden braucht."
        elif "ssl" in main.lower() or "https" in main.lower():
            prob = "Ihre Website hat kein HTTPS. Besucher sehen eine Sicherheitswarnung im Browser - das kostet massiv Vertrauen."
        elif "mobile" in main.lower():
            prob = "Ihre Website ist nicht fuer Smartphones optimiert. Ueber 60% der lokalen Suchen passieren heute auf dem Handy."
        elif "aktualisiert" in main.lower() or "seit" in main.lower():
            prob = f"Ihre Website wurde seit Jahren nicht aktualisiert ({main}). Das schadet Ihrem Google-Ranking."
        elif "inhalt" in main.lower():
            prob = "Ihre Website hat kaum Inhalte. Google zeigt solche Seiten kaum in den Suchergebnissen an."
        elif "seo" in main.lower():
            prob = "Ihrer Website fehlen wichtige SEO-Grundlagen, weshalb sie in Google kaum gefunden wird."
        else:
            prob = f"Ihre Website hat ein technisches Problem: {main}."
        subj = f"Kurze Frage zu Ihrer Website - {name}"
        body = (f"Guten Tag,\n\nIch habe Ihre Website besucht und folgendes festgestellt:\n\n"
                f"{prob}\n\nIch helfe lokalen Unternehmen wie {name} dabei, genau solche Probleme "
                f"schnell und guenstig zu loesen - mit messbaren Ergebnissen.\n\n"
                f"Haetten Sie kurz Zeit fuer ein Gespraech?\n\nMit freundlichen Gruessen")
    else:
        subj = f"Ihre Website - {name}"
        body = (f"Guten Tag,\n\nIch wuerde Ihnen gerne zeigen, wie Sie mit gezielten Verbesserungen "
                f"noch mehr Kunden ueber Ihre Website gewinnen koennen.\n\nMit freundlichen Gruessen")

    return {"subject": subj, "body": body}


# ─────────────────────────────────────────
#  API ROUTES
# ─────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/scrape")
def api_scrape():
    query    = request.args.get("query", "").strip()
    location = request.args.get("location", "").strip()
    max_r    = min(int(request.args.get("max", 20)), 50)

    if not query or not location:
        return jsonify({"error": "query und location fehlen"}), 400

    print(f"\n{'='*60}\nSuche: '{query}' in '{location}' | max={max_r}\n{'='*60}")

    # 1. Stadt -> OSM Area ID
    print(f"  Suche OSM Area ID fuer '{location}'...")
    area_id = get_osm_area_id(location)
    if not area_id:
        return jsonify({"error": f"Stadt '{location}' nicht gefunden."}), 400
    print(f"  Area ID: {area_id}")

    # 2. Query -> OSM Tags
    amenity_tags, shop_tags, craft_tags = get_tags_for_query(query)
    print(f"  Tags: amenity={amenity_tags}, shop={shop_tags}, craft={craft_tags}")

    # 3. OSM abfragen — gibt nur Eintraege MIT Website
    businesses = query_overpass(amenity_tags, shop_tags, craft_tags, area_id, max_r)

    # Duplikate entfernen
    seen, unique = set(), []
    for b in businesses:
        key = b["name"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(b)
    businesses = unique[:max_r]

    print(f"\n{len(businesses)} Unternehmen MIT Website gefunden. Starte Qualitaetscheck...")

    if not businesses:
        return jsonify({
            "leads": [],
            "stats": {"total": 0, "top": 0, "good": 0, "possible": 0, "none": 0},
            "message": f"Keine Unternehmen mit Website fuer '{query}' in '{location}' gefunden. Versuche andere Begriffe wie 'restaurant', 'friseur', 'handwerker'."
        }), 200

    # 4. Website-Qualitaet pruefen
    leads = []
    for i, biz in enumerate(businesses):
        url = biz["website"]
        print(f"  [{i+1}/{len(businesses)}] {biz['name'][:40]} | {url[:45]}")
        wc = check_website(url)
        outreach = make_outreach(biz, wc)
        leads.append({
            **biz,
            "website_score":    wc["score"],
            "has_ssl":          wc["has_ssl"],
            "is_reachable":     wc["is_reachable"],
            "load_time":        wc["load_time"],
            "status_code":      wc["status_code"],
            "is_mobile":        wc["is_mobile_friendly"],
            "has_content":      wc["has_content"],
            "page_size_kb":     wc["page_size_kb"],
            "issues":           wc["issues"],
            "recommendation":   wc["recommendation"],
            "rec_class":        wc["rec_class"],
            "outreach_subject": outreach["subject"],
            "outreach_body":    outreach["body"],
            "scraped_at":       datetime.now().strftime("%d.%m.%Y %H:%M"),
        })
        time.sleep(0.5)

    # Sortieren: schlechteste zuerst, dann gute Leads, OK-Leads ans Ende
    leads.sort(key=lambda x: x["website_score"])
    leads_q    = [l for l in leads if l["rec_class"] != "none"]
    leads_none = [l for l in leads if l["rec_class"] == "none"]
    leads = leads_q + leads_none

    stats = {
        "total":    len(leads),
        "top":      sum(1 for l in leads if l["rec_class"] == "top"),
        "good":     sum(1 for l in leads if l["rec_class"] == "good"),
        "possible": sum(1 for l in leads if l["rec_class"] == "possible"),
        "none":     sum(1 for l in leads if l["rec_class"] == "none"),
    }
    print(f"\nFertig: {stats}")
    return jsonify({"leads": leads, "stats": stats})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None
    print(f"""
+------------------------------------------+
|  LeadRadar Backend v5                    |
|  http://localhost:{port}                   |
|  Datenquelle: OpenStreetMap (kostenlos)  |
|  Nur Leads MIT Website                   |
|  Ketten-Filter: aktiv                    |
+------------------------------------------+
""")
    app.run(debug=debug, port=port, host="0.0.0.0")
