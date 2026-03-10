#!/usr/bin/env python3
"""
LeadRadar Backend v6
- Stufe 1: OpenStreetMap (alle Unternehmen, auch ohne Website-Tag)
- Stufe 2: Fuer Eintraege ohne Website -> DuckDuckGo Lookup
- Stufe 3: Website-Qualitaet pruefen
- Funktioniert auf Railway (kein Scraping von Google/Gelbe Seiten)
"""

from flask import Flask, jsonify, request, send_from_directory
import requests
from bs4 import BeautifulSoup
import time
import re
import os
from urllib.parse import quote_plus
from datetime import datetime
import urllib3
urllib3.disable_warnings()

app = Flask(__name__, static_folder=".")

HEADERS_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

NOT_A_WEBSITE = [
    "google.", "facebook.", "instagram.", "twitter.", "linkedin.", "xing.",
    "yelp.", "tripadvisor.", "gelbeseiten.", "klicktel.", "11880.", "cylex.",
    "meinestadt.", "stadtbranchenbuch.", "wikipedia.", "youtube.",
    "maps.google", "branchenbuch.", "dastelefonbuch.", "dasoertliche.",
    "hotfrog.", "foursquare.", "trustpilot.", "kununu.", "jameda.",
    "doctolib.", "booking.", "trivago.", "holidaycheck.", "openstreetmap.",
    "wikidata.", "whatsapp.", "tiktok.", "pinterest.",
]

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
    "norma ","action ","tedi ","zeeman","five guys",
]

# OSM Tag-Mapping: Suchbegriff -> amenity/shop/craft Tags
OSM_TAGS = {
    # Gastronomie
    "restaurant":    {"amenity": ["restaurant","fast_food","food_court"]},
    "cafe":          {"amenity": ["cafe"]},
    "bar":           {"amenity": ["bar","pub","nightclub"]},
    "kneipe":        {"amenity": ["bar","pub"]},
    "pizza":         {"amenity": ["restaurant","fast_food"]},
    "imbiss":        {"amenity": ["fast_food","food_court"]},
    "biergarten":    {"amenity": ["biergarten","bar"]},
    # Gesundheit
    "arzt":          {"amenity": ["doctors","clinic","dentist"]},
    "zahnarzt":      {"amenity": ["dentist"]},
    "apotheke":      {"amenity": ["pharmacy"]},
    "physiotherapie":{"amenity": ["physiotherapist"]},
    "optiker":       {"shop": ["optician"]},
    # Beauty & Wellness
    "friseur":       {"shop": ["hairdresser"], "amenity": ["hairdresser"]},
    "hairdresser":   {"shop": ["hairdresser"]},
    "kosmetik":      {"shop": ["cosmetics","beauty"]},
    "nagel":         {"shop": ["nail_salon"]},
    "tattoo":        {"shop": ["tattoo"]},
    "massage":       {"amenity": ["massage"]},
    # Handwerk & Dienstleistung
    "handwerker":    {"craft": ["carpenter","electrician","plumber","painter","builder","roofer"]},
    "elektriker":    {"craft": ["electrician"]},
    "klempner":      {"craft": ["plumber"]},
    "maler":         {"craft": ["painter"]},
    "schreiner":     {"craft": ["carpenter","cabinet_maker"]},
    "dachdecker":    {"craft": ["roofer"]},
    "zimmermann":    {"craft": ["carpenter"]},
    "sanitaer":      {"craft": ["plumber","hvac"]},
    # Kfz
    "autowerkstatt": {"amenity": ["car_repair"]},
    "werkstatt":     {"amenity": ["car_repair"]},
    "kfz":           {"amenity": ["car_repair"]},
    "autohaendler":  {"shop": ["car"]},
    "reifenservice": {"shop": ["tyres"]},
    # Unterkuenfte
    "hotel":         {"amenity": ["hotel","motel","guest_house"]},
    "pension":       {"amenity": ["guest_house","hostel"]},
    # Bildung
    "schule":        {"amenity": ["school","kindergarten"]},
    "kindergarten":  {"amenity": ["kindergarten"]},
    "nachhilfe":     {"amenity": ["school","language_school"]},
    "sprachschule":  {"amenity": ["language_school"]},
    # Finanzen & Recht
    "rechtsanwalt":  {"amenity": ["lawyers"]},
    "steuerberater": {"office": ["accountant","tax_advisor"]},
    "versicherung":  {"office": ["insurance"]},
    "immobilien":    {"office": ["estate_agent"]},
    # Lebensmittel & Einzelhandel
    "baeckerei":     {"shop": ["bakery"]},
    "bäckerei":      {"shop": ["bakery"]},
    "metzger":       {"shop": ["butcher"]},
    "fleischer":     {"shop": ["butcher"]},
    "supermarkt":    {"shop": ["supermarket","convenience"]},
    "blumen":        {"shop": ["florist"]},
    "moebel":        {"shop": ["furniture"]},
    "moebelhändler": {"shop": ["furniture"]},
    "buchhandlung":  {"shop": ["books"]},
    "spielzeug":     {"shop": ["toys"]},
    "elektronik":    {"shop": ["electronics"]},
    "computer":      {"shop": ["computer"]},
    "handy":         {"shop": ["mobile_phone"]},
    # Sport & Freizeit
    "fitnessstudio": {"leisure": ["fitness_centre","gym"]},
    "gym":           {"leisure": ["fitness_centre","gym"]},
    "yoga":          {"leisure": ["fitness_centre"]},
    "schwimmbad":    {"leisure": ["swimming_pool","sports_centre"]},
    "sport":         {"leisure": ["sports_centre","pitch"]},
    # Tiere
    "tierarzt":      {"amenity": ["veterinary"]},
    "tierpflege":    {"shop": ["pet_grooming","pet"]},
    # Reinigung
    "reinigung":     {"shop": ["dry_cleaning","laundry"]},
    "waescherei":    {"shop": ["laundry"]},
    # Sonstiges
    "tankstelle":    {"amenity": ["fuel"]},
    "fahrrad":       {"shop": ["bicycle"]},
    "fotograf":      {"shop": ["photo"]},
    "reisebuero":    {"shop": ["travel_agency"]},
    "bank":          {"amenity": ["bank"]},
    "kita":          {"amenity": ["kindergarten"]},
    "druckerei":     {"craft": ["print_shop"]},
    "schluesseldienst": {"craft": ["locksmith"]},
    "umzug":         {"office": ["moving_company"]},
}


def is_chain(name):
    n = name.lower()
    return any(c in n for c in CHAIN_BLACKLIST)


def is_directory_url(url):
    url_l = url.lower()
    return any(d in url_l for d in NOT_A_WEBSITE)


# ─────────────────────────────────────────
#  SCHRITT 1: OSM - Unternehmen holen
# ─────────────────────────────────────────

def get_osm_area_id(city):
    url = f"https://nominatim.openstreetmap.org/search?q={quote_plus(city)},+Germany&format=json&limit=3&addressdetails=1"
    try:
        r = requests.get(url, headers={"User-Agent": "LeadRadar/1.0"}, timeout=10)
        data = r.json()
        for item in data:
            osm_id   = int(item.get("osm_id", 0))
            osm_type = item.get("osm_type", "")
            if osm_type == "relation":
                return osm_id + 3600000000
            elif osm_type == "way":
                return osm_id + 2400000000
            elif osm_type == "node":
                return osm_id
    except Exception as e:
        print(f"  [NOMINATIM] Fehler: {e}")
    return None


def build_overpass_query(tags_dict, area_id, limit=200):
    """Baut eine Overpass-Query die ALLE Unternehmen holt (mit und ohne Website)."""
    parts = []
    for tag_type, values in tags_dict.items():
        for val in values:
            parts.append(f'  node["{tag_type}"="{val}"](area.searchArea);')
            parts.append(f'  way["{tag_type}"="{val}"](area.searchArea);')

    if not parts:
        return None

    return f"""
[out:json][timeout:30];
area({area_id})->.searchArea;
(
{chr(10).join(parts)}
);
out body {limit};
"""


def query_osm(query_raw, area_id, limit=200):
    """Holt Unternehmen aus OSM - sowohl MIT als auch OHNE Website."""
    q = query_raw.lower().strip()

    # Passende Tags finden
    tags_dict = {}
    for kw, tags in OSM_TAGS.items():
        if kw in q or q in kw or q == kw:
            for tag_type, values in tags.items():
                if tag_type not in tags_dict:
                    tags_dict[tag_type] = []
                tags_dict[tag_type].extend(v for v in values if v not in tags_dict[tag_type])

    # Fallback: direkt als Tag-Wert probieren
    if not tags_dict:
        tags_dict = {
            "amenity": [q],
            "shop": [q],
            "craft": [q],
            "office": [q],
        }

    print(f"  [OSM] Tags: {tags_dict}")
    overpass_q = build_overpass_query(tags_dict, area_id, limit)
    if not overpass_q:
        return []

    results = []
    try:
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": overpass_q},
            headers={"User-Agent": "LeadRadar/1.0"},
            timeout=35,
        )
        data = r.json()
        elements = data.get("elements", [])
        print(f"  [OSM] {len(elements)} Eintraege gefunden")

        for el in elements:
            tags = el.get("tags", {})
            name    = tags.get("name", "").strip()
            website = tags.get("website", tags.get("contact:website", "")).strip()
            phone   = tags.get("phone", tags.get("contact:phone", "")).strip()
            email   = tags.get("email", tags.get("contact:email", "")).strip()

            street   = tags.get("addr:street", "")
            housenr  = tags.get("addr:housenumber", "")
            postcode = tags.get("addr:postcode", "")
            city_tag = tags.get("addr:city", "")
            address  = f"{street} {housenr}, {postcode} {city_tag}".strip(" ,")

            if not name:
                continue
            if is_chain(name):
                continue

            # Website bereinigen
            if website and not website.startswith("http"):
                website = "https://" + website
            if website:
                website = website.rstrip("/")
            if website and is_directory_url(website):
                website = ""

            results.append({
                "name":    name,
                "website": website,
                "phone":   phone,
                "email":   email,
                "address": address,
                "source":  "OpenStreetMap",
            })

    except Exception as e:
        print(f"  [OSM] Fehler: {e}")

    return results


# ─────────────────────────────────────────
#  SCHRITT 2: Website per DuckDuckGo finden
# ─────────────────────────────────────────

def find_website_ddg(name, city=""):
    """Sucht offizielle Website via DuckDuckGo HTML."""
    query = f"{name} {city} website".strip()
    url   = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&kl=de-de"

    try:
        resp = requests.get(url, headers=HEADERS_WEB, timeout=12, verify=False)
        soup = BeautifulSoup(resp.text, "lxml")

        for a in soup.find_all("a", {"class": re.compile(r"result__url|result__a")}):
            href = a.get("href", "") or a.get_text(strip=True)
            if not href:
                continue
            # DDG redirect links
            m = re.search(r'uddg=(https?%3A[^&]+)', href)
            if m:
                from urllib.parse import unquote
                href = unquote(m.group(1))
            if not href.startswith("http"):
                href = "https://" + href
            href = href.split("?")[0].rstrip("/")
            if not is_directory_url(href) and len(href) > 10:
                print(f"    [DDG] {name} -> {href}")
                return href

        # Fallback: alle Links durchsuchen
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if re.match(r"https?://", href) and not is_directory_url(href):
                href = href.split("?")[0].rstrip("/")
                if len(href) > 15:
                    print(f"    [DDG-fallback] {name} -> {href}")
                    return href

    except Exception as e:
        print(f"    [DDG] Fehler fuer '{name}': {e}")

    return ""


# ─────────────────────────────────────────
#  SCHRITT 3: Website-Qualitaet pruefen
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
        result["load_time"]  = load_time
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

        for kw in ["domain expired","account suspended","parked domain",
                   "under construction","coming soon","diese domain"]:
            if kw in page_lower:
                result["issues"].append("Inaktive/geparkte Domain")
                result["score"] -= 40
                break

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text(strip=True)
        result["page_size_kb"] = round(len(resp.text) / 1024, 1)

        if len(text) < 300:
            result["issues"].append("Kaum Inhalt (Under Construction?)")
            result["score"] -= 30
        elif len(text) < 800:
            result["issues"].append("Wenig Inhalt")
            result["score"] -= 10
        else:
            result["has_content"] = True
            result["score"] += 20

        if soup.find("meta", {"name": "viewport"}):
            result["is_mobile_friendly"] = True
            result["score"] += 10
        else:
            result["issues"].append("Nicht mobile-optimiert")
            result["score"] -= 15

        for yr_match in re.findall(r'copyright\D{0,5}(\d{4})|&copy;\D{0,5}(\d{4})', page_lower):
            yr_str = yr_match[0] or yr_match[1]
            if yr_str:
                yr = int(yr_str)
                if yr < datetime.now().year - 3:
                    result["issues"].append(f"Seit {yr} nicht aktualisiert")
                    result["score"] -= 20
                    break

        if re.search(r'cellpadding|cellspacing|bgcolor=', resp.text, re.I):
            result["issues"].append("Veraltetes HTML-Layout")
            result["score"] -= 10

        if not soup.find("meta", {"name": "description"}):
            result["issues"].append("Kein Meta-Description (SEO)")
            result["score"] -= 5

        if any(x in page_lower for x in ["wordpress","shopify","typo3","joomla",
               "wix","squarespace","jimdo","react","vue","angular","next"]):
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
    name   = biz.get("name", "Ihr Unternehmen")
    issues = wc.get("issues", [])

    if not wc.get("is_reachable"):
        subj = f"Ihre Website ist nicht erreichbar - {name}"
        body = (f"Guten Tag,\n\nIhre Website ist aktuell nicht erreichbar. "
                f"Kunden die online nach {name} suchen, landen auf einer toten Seite "
                f"und wechseln zur Konkurrenz.\n\n"
                f"Ich kann helfen, das schnell zu beheben.\n\nMit freundlichen Gruessen")
    elif issues:
        main = issues[0]
        if "langsam" in main.lower() or "timeout" in main.lower():
            prob = f"Ihre Website laedt sehr langsam ({main}). 53% der Nutzer verlassen Seiten die laenger als 3 Sekunden brauchen."
        elif "ssl" in main.lower() or "https" in main.lower():
            prob = "Ihre Website hat kein HTTPS. Browser zeigen Besuchern eine Sicherheitswarnung - das kostet Vertrauen und Kunden."
        elif "mobile" in main.lower():
            prob = "Ihre Website ist nicht fuer Smartphones optimiert. Ueber 60% der lokalen Suchen finden auf dem Handy statt."
        elif "aktualisiert" in main.lower() or "seit" in main.lower():
            prob = f"Ihre Website wurde seit Jahren nicht aktualisiert ({main}). Das schadet aktiv Ihrem Google-Ranking."
        elif "inhalt" in main.lower():
            prob = "Ihre Website hat kaum Inhalte. Google zeigt solche Seiten in der Suche kaum an."
        elif "seo" in main.lower():
            prob = "Ihrer Website fehlen grundlegende SEO-Einstellungen, wodurch sie in Google kaum gefunden wird."
        else:
            prob = f"Ihre Website hat folgendes Problem: {main}."
        subj = f"Kurze Frage zu Ihrer Website - {name}"
        body = (f"Guten Tag,\n\nIch habe Ihre Website besucht und dabei festgestellt:\n\n"
                f"{prob}\n\nIch helfe lokalen Unternehmen wie {name} genau dabei - "
                f"schnell, guenstig und mit messbaren Ergebnissen.\n\n"
                f"Haetten Sie 15 Minuten fuer ein kurzes Gespraech?\n\nMit freundlichen Gruessen")
    else:
        subj = f"Ihre Website - {name}"
        body = (f"Guten Tag,\n\nIch wuerde Ihnen gerne zeigen, wie Sie mit gezielten "
                f"Verbesserungen noch mehr Kunden ueber Ihre Website gewinnen koennen."
                f"\n\nMit freundlichen Gruessen")

    return {"subject": subj, "body": body}


# ─────────────────────────────────────────
#  API
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
    area_id = get_osm_area_id(location)
    if not area_id:
        return jsonify({"error": f"Stadt '{location}' nicht gefunden."}), 400
    print(f"  Area ID: {area_id}")

    # 2. OSM: Alle Unternehmen holen (mit + ohne Website)
    all_biz = query_osm(query, area_id, limit=300)

    # Duplikate entfernen
    seen, unique = set(), []
    for b in all_biz:
        key = b["name"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(b)

    # Mischen: Zuerst Eintraege MIT Website, dann ohne
    with_web    = [b for b in unique if b.get("website")]
    without_web = [b for b in unique if not b.get("website")]
    print(f"  OSM: {len(with_web)} mit Website, {len(without_web)} ohne Website")

    # 3. Fuer Eintraege ohne Website: DuckDuckGo-Lookup
    # Wir nehmen aus "ohne Website" so viele wie noetig um max_r zu erreichen
    needed_lookups = max(0, max_r - len(with_web))
    lookup_candidates = without_web[:needed_lookups + 10]  # Etwas Puffer

    print(f"  Starte DDG-Lookup fuer {len(lookup_candidates)} Eintraege ohne Website...")
    city_hint = location.split(",")[0].strip()

    for biz in lookup_candidates:
        found = find_website_ddg(biz["name"], city_hint)
        if found:
            biz["website"] = found
        time.sleep(1.2)

    # Alle mit Website zusammenfuehren (OSM direkt + DDG-gefunden)
    all_with_web = [b for b in (with_web + lookup_candidates) if b.get("website")]

    # Deduplizieren nach Website-Domain
    seen_domains, final_biz = set(), []
    for b in all_with_web:
        domain = re.sub(r'https?://(www\.)?', '', b["website"]).split('/')[0].lower()
        if domain not in seen_domains:
            seen_domains.add(domain)
            final_biz.append(b)

    final_biz = final_biz[:max_r]
    print(f"\n{len(final_biz)} Unternehmen MIT Website. Starte Qualitaetscheck...")

    if not final_biz:
        return jsonify({
            "leads": [],
            "stats": {"total":0,"top":0,"good":0,"possible":0,"none":0},
            "message": f"Keine Unternehmen mit Website fuer '{query}' in '{location}' gefunden."
        }), 200

    # 4. Website-Qualitaet pruefen
    leads = []
    for i, biz in enumerate(final_biz):
        url = biz["website"]
        print(f"  [{i+1}/{len(final_biz)}] {biz['name'][:38]} | {url[:42]}")
        wc       = check_website(url)
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

    # Qualifizierte Leads zuerst, OK-Leads ans Ende
    leads.sort(key=lambda x: x["website_score"])
    leads = [l for l in leads if l["rec_class"] != "none"] + \
            [l for l in leads if l["rec_class"] == "none"]

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
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None
    print(f"""
+------------------------------------------+
|  LeadRadar Backend v6                    |
|  http://localhost:{port}                   |
|  Stufe 1: OpenStreetMap (alle Betriebe)  |
|  Stufe 2: DuckDuckGo Website-Lookup      |
|  Stufe 3: Website-Qualitaetscheck        |
+------------------------------------------+
""")
    app.run(debug=debug, port=port, host="0.0.0.0")
