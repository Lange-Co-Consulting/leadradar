#!/usr/bin/env python3
"""
LeadRadar Backend v4
- Findet Website per Google-Suche fuer jedes Unternehmen
- Filtert Ketten/Franchises + geschlossene Betriebe
- Nur Leads MIT Website aber schlechter Qualitaet
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

HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# Domains die KEINE echte Unternehmenswebsite sind
NOT_A_WEBSITE = [
    "google.", "facebook.", "instagram.", "twitter.", "linkedin.",
    "xing.", "yelp.", "tripadvisor.", "gelbeseiten.", "klicktel.",
    "11880.", "cylex.", "meinestadt.", "stadtbranchenbuch.",
    "wikipedia.", "youtube.", "maps.google", "waze.",
    "branchenbuch.", "dastelefonbuch.", "dasoertliche.",
    "hotfrog.", "foursquare.", "trustpilot.", "kununu.",
    "jameda.", "doctolib.", "booking.", "trivago.", "holidaycheck.",
]

CHAIN_BLACKLIST = [
    "subway","mcdonald","burger king","kfc","pizza hut","domino","vapiano",
    "nordsee","wienerwald","hans im gluck","hans im glück","peter pane",
    "enchilada","l'osteria","dean david","dean & david","ditsch","backwerk",
    "le crobag","jim block","five guys","dunkin","starbucks","costa coffee",
    "tchibo","balzac","yorma","cinnabon","aldi","lidl","rewe","edeka",
    "penny","netto","kaufland","dm drogerie","rossmann","saturn","mediamarkt",
    "ikea","obi ","bauhaus","hornbach","toom","hagebau","deichmann","snipes",
    "foot locker","h&m","zara","primark","c&a","esprit","douglas","thalia",
    "hugendubel","fielmann","apollo optik","mcfit","fitx","clever fit",
    "fitness first","sixt","hertz","europcar","telekom shop","o2 shop",
    "vodafone shop","motel one","ibis ","novotel","mercure","holiday inn",
    "hilton","marriott","radisson","a&o hostel","meininger","takko",
    "kik ","nkd ","woolworth","norma ","action ",
]

CLOSED_KEYWORDS = [
    "dauerhaft geschlossen","permanently closed","betrieb eingestellt",
    "insolvenz","insolvent","aufgeloest","domain expired",
    "account suspended","parked domain",
]


def is_chain(name):
    n = name.lower()
    return any(c in n for c in CHAIN_BLACKLIST)


def is_closed(text, name=""):
    combined = (text + " " + name).lower()
    return any(kw in combined for kw in CLOSED_KEYWORDS)


def is_directory_url(url):
    """Prueft ob eine URL ein Branchenverzeichnis ist, keine echte Website."""
    return any(d in url.lower() for d in NOT_A_WEBSITE)


# ─────────────────────────────────────────
#  WEBSITE-LOOKUP via Google/DuckDuckGo
# ─────────────────────────────────────────

def find_website(company_name, address=""):
    """
    Sucht die offizielle Website eines Unternehmens via Google.
    Gibt URL zurueck oder leeren String wenn nichts gefunden.
    """
    # Suchbegriff: Firmenname + Stadt (aus Adresse extrahiert)
    city = ""
    if address:
        m = re.search(r'\d{5}\s+(\w[\w\s]{2,20})', address)
        if m:
            city = m.group(1).strip().split()[0]

    query = f"{company_name} {city} offizielle website".strip()
    search_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=de&num=5"

    try:
        resp = requests.get(search_url, headers=HEADERS_BROWSER, timeout=12, verify=False)
        soup = BeautifulSoup(resp.text, "lxml")

        # Google zeigt URLs in verschiedenen Elementen
        candidates = []

        # Methode 1: cite-Tags (zeigen die URL an)
        for cite in soup.find_all("cite"):
            url = cite.get_text(strip=True)
            if url.startswith("http") or ("." in url and "/" in url):
                if not url.startswith("http"):
                    url = "https://" + url
                candidates.append(url.split(" ")[0])

        # Methode 2: a-Tags mit href zu externen Seiten
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Google verschleiert Links mit /url?q=
            m = re.search(r'/url\?q=(https?://[^&]+)', href)
            if m:
                candidates.append(m.group(1))
            elif re.match(r'https?://', href):
                candidates.append(href)

        # Bestes Ergebnis: erste nicht-Verzeichnis URL
        for url in candidates:
            url = url.split("?")[0].rstrip("/")
            if not is_directory_url(url) and len(url) > 10:
                # Sanity check: enthaelt die Domain den Firmennamen oder eine Stadt?
                domain = re.sub(r'https?://(www\.)?', '', url).split('/')[0].lower()
                print(f"    [GOOGLE] Gefunden: {url}")
                return url

    except Exception as e:
        print(f"    [GOOGLE] Fehler bei '{company_name}': {e}")

    # Fallback: DuckDuckGo
    try:
        ddg_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        resp = requests.get(ddg_url, headers=HEADERS_BROWSER, timeout=10, verify=False)
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", {"class": re.compile(r"result__url|result__a")}):
            href = a.get("href", "")
            if not href:
                href = a.get_text(strip=True)
            if "." in href and not is_directory_url(href):
                if not href.startswith("http"):
                    href = "https://" + href
                print(f"    [DDG] Gefunden: {href}")
                return href.split("?")[0].rstrip("/")
    except Exception as e:
        print(f"    [DDG] Fehler: {e}")

    return ""


# ─────────────────────────────────────────
#  SCRAPING: GELBE SEITEN
# ─────────────────────────────────────────

def scrape_gelbe_seiten(query, location, max_results=20):
    businesses = []
    page = 1
    target = max_results * 3

    while len(businesses) < target and page <= 10:
        url = (
            f"https://www.gelbeseiten.de/suche/"
            f"{quote_plus(query)}/{quote_plus(location)}"
            f"?von={(page - 1) * 20 + 1}"
        )
        print(f"  [GS] Seite {page}: {url}")

        try:
            resp = requests.get(url, headers=HEADERS_BROWSER, timeout=20, verify=False)
            soup = BeautifulSoup(resp.text, "lxml")
            entries = (
                soup.find_all("article", {"class": re.compile(r"teilnehmer", re.I)})
                or soup.find_all("article")
            )
            if not entries:
                print("  [GS] Keine Eintraege mehr")
                break

            for entry in entries:
                biz = _parse_gelbe_eintrag(entry)
                if not biz or not biz["name"]:
                    continue
                entry_text = entry.get_text(" ", strip=True)
                if is_chain(biz["name"]):
                    print(f"  [SKIP-KETTE]  {biz['name']}")
                    continue
                if is_closed(entry_text, biz["name"]):
                    print(f"  [SKIP-CLOSED] {biz['name']}")
                    continue
                businesses.append(biz)
                print(f"  [GS] + {biz['name']} | {biz.get('phone','--')}")

            next_btn = soup.find("a", {"class": re.compile(r"next|weiter", re.I)})
            if not next_btn:
                break
            page += 1
            time.sleep(1.5)

        except Exception as e:
            print(f"  [GS] Fehler: {e}")
            break

    return businesses


def _parse_gelbe_eintrag(entry):
    biz = {"name": "", "website": "", "phone": "", "address": "", "source": "Gelbe Seiten"}

    for tag in ["h2", "h3", "h4"]:
        el = entry.find(tag)
        if el:
            biz["name"] = el.get_text(strip=True)
            break
    if not biz["name"]:
        biz["name"] = entry.get("data-name", "") or entry.get("aria-label", "")

    # Website aus Gelbe Seiten (oft nicht vorhanden — wird spaeter per Google ergaenzt)
    for a in entry.find_all("a", href=True):
        href = a["href"]
        if re.match(r"https?://", href) and not is_directory_url(href):
            biz["website"] = href.split("?")[0].rstrip("/")
            break
    if not biz["website"]:
        for el in entry.find_all(attrs={"data-website": True}):
            w = el["data-website"]
            if not is_directory_url(w):
                biz["website"] = w
                break

    # Telefon
    tel_link = entry.find("a", href=re.compile(r"^tel:"))
    if tel_link:
        biz["phone"] = tel_link["href"].replace("tel:", "").strip()
    else:
        text = entry.get_text(" ", strip=True)
        m = re.search(r'(\+49[\d\s\-/]{7,}|0[\d][\d\s\-/]{8,})', text)
        if m:
            biz["phone"] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # Adresse
    addr = entry.find(["address","span","div","p"],
                      {"class": re.compile(r"adress|address|location|ort|street|plz", re.I)})
    if addr:
        biz["address"] = re.sub(r'\s+', ' ', addr.get_text(" ", strip=True))
    else:
        text = entry.get_text(" ", strip=True)
        m = re.search(r'(\d{5}\s+\w[\w\s]{2,30})', text)
        if m:
            biz["address"] = m.group(1).strip()

    return biz


# ─────────────────────────────────────────
#  WEBSITE-QUALITAET PRUEFEN
# ─────────────────────────────────────────

def check_website(url):
    result = {
        "has_website": bool(url),
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

    if not url:
        # Kein Lead — wir wollen nur Firmen MIT Website
        result["recommendation"] = "KEIN LEAD - Keine Website gefunden"
        result["rec_class"] = "none"
        result["score"] = 100
        return result

    if not url.startswith("http"):
        url = "https://" + url

    result["has_ssl"] = url.startswith("https://")
    if not result["has_ssl"]:
        result["issues"].append("Kein HTTPS/SSL")
        result["score"] -= 20

    start = time.time()
    try:
        resp = requests.get(url, headers=HEADERS_BROWSER, timeout=10,
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
        for kw in ["domain expired","account suspended","parked domain",
                   "under construction","coming soon","diese domain"]:
            if kw in page_lower:
                result["issues"].append(f"Inaktive Domain ({kw})")
                result["score"] -= 40
                break

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text(strip=True)
        result["page_size_kb"] = round(len(resp.text) / 1024, 1)

        if len(text) < 200:
            result["issues"].append("Kaum Inhalt (Under Construction?)")
            result["score"] -= 30
        else:
            result["has_content"] = True
            result["score"] += 20

        if soup.find("meta", {"name": "viewport"}):
            result["is_mobile_friendly"] = True
            result["score"] += 10
        else:
            result["issues"].append("Nicht mobile-optimiert")
            result["score"] -= 15

        # Veraltetes Copyright-Jahr
        for yr_match in re.findall(r'copyright\D{0,5}(\d{4})|&copy;\D{0,5}(\d{4})', page_lower):
            yr_str = yr_match[0] or yr_match[1]
            if yr_str:
                yr = int(yr_str)
                if yr < datetime.now().year - 3:
                    result["issues"].append(f"Website seit {yr} nicht aktualisiert")
                    result["score"] -= 20
                    break

        if re.search(r'cellpadding|cellspacing|bgcolor=', resp.text, re.I):
            result["issues"].append("Veraltetes HTML-Table-Layout")
            result["score"] -= 10

        if any(x in page_lower for x in ["react","vue","angular","next","gatsby",
               "wordpress","shopify","typo3","joomla","wix","squarespace","jimdo"]):
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

    if not wc.get("is_reachable") and wc.get("has_website"):
        subj = f"Ihre Website ist nicht erreichbar - {name}"
        body = (f"Guten Tag,\n\nIhre Website ist aktuell nicht erreichbar. Kunden, die online nach "
                f"{name} suchen, landen auf einer toten Seite und wechseln zur Konkurrenz.\n\n"
                f"Ich kann helfen, das schnell zu beheben.\n\nMit freundlichen Gruessen")
    elif issues:
        main = issues[0]
        if "langsam" in main.lower() or "timeout" in main.lower():
            prob = f"Ihre Website laedt sehr langsam ({main}). Studien zeigen: 53% der Nutzer verlassen eine Seite, die laenger als 3 Sekunden braucht."
        elif "ssl" in main.lower() or "https" in main.lower():
            prob = "Ihre Website hat kein HTTPS. Besucher sehen eine Sicherheitswarnung im Browser - das kostet massiv Vertrauen und Kunden."
        elif "mobile" in main.lower():
            prob = "Ihre Website ist nicht fuer Smartphones optimiert. Ueber 60% der lokalen Suchen passieren heute auf dem Handy."
        elif "aktualisiert" in main.lower():
            prob = f"Ihre Website wurde seit Jahren nicht aktualisiert ({main}). Das wirkt unprofessionell und schadet Ihrem Google-Ranking."
        elif "inhalt" in main.lower():
            prob = "Ihre Website hat kaum Inhalte. Google zeigt Seiten mit wenig Inhalt kaum in den Suchergebnissen an."
        else:
            prob = f"Ihre Website hat ein technisches Problem: {main}."
        subj = f"Kurze Frage zu Ihrer Website - {name}"
        body = (f"Guten Tag,\n\nIch habe Ihre Website besucht und dabei festgestellt:\n\n"
                f"{prob}\n\nIch helfe lokalen Unternehmen wie {name} dabei, genau solche Probleme "
                f"schnell und kostenguenstig zu loesen.\n\n"
                f"Haetten Sie 15 Minuten Zeit fuer ein kurzes Gespraech?\n\nMit freundlichen Gruessen")
    else:
        subj = f"Ihre Website - {name}"
        body = (f"Guten Tag,\n\nIch wuerde Ihnen gerne zeigen, wie Sie mit gezielten Verbesserungen "
                f"noch mehr Kunden ueber Ihre Website gewinnen koennen.\n\nMit freundlichen Gruessen")

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

    # 1. Unternehmen scrapen
    businesses = scrape_gelbe_seiten(query, location, max_r)

    # Duplikate entfernen
    seen, unique = set(), []
    for b in businesses:
        key = b["name"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(b)
    businesses = unique[:max_r]

    if not businesses:
        return jsonify({"leads": [], "stats": {}, "message": "Keine Unternehmen gefunden."}), 200

    print(f"\n{len(businesses)} Unternehmen gefunden. Suche Websites...")

    # 2. Fuer jedes Unternehmen Website suchen (falls Gelbe Seiten keine liefert)
    for biz in businesses:
        if not biz.get("website"):
            print(f"  [LOOKUP] {biz['name'][:45]}...")
            biz["website"] = find_website(biz["name"], biz.get("address", ""))
            time.sleep(1.5)  # Google-Freundlichkeit
        else:
            print(f"  [OK-URL] {biz['name'][:45]} -> {biz['website'][:40]}")

    # 3. Nur Unternehmen MIT Website behalten
    with_website = [b for b in businesses if b.get("website")]
    without_website = [b for b in businesses if not b.get("website")]
    print(f"\n  Mit Website: {len(with_website)} | Ohne Website: {len(without_website)}")
    print(f"  Analysiere nur Unternehmen MIT Website...")

    # 4. Website-Qualitaet pruefen
    leads = []
    for i, biz in enumerate(with_website):
        name = biz["name"]
        url  = biz["website"]
        print(f"  [{i+1}/{len(with_website)}] {name[:40]} | {url[:45]}")
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
        time.sleep(0.8)

    # Sortieren: schlechteste Website zuerst
    leads.sort(key=lambda x: x["website_score"])

    # Kein-Lead-Eintraege ans Ende
    leads_qualified = [l for l in leads if l["rec_class"] != "none"]
    leads_none      = [l for l in leads if l["rec_class"] == "none"]
    leads = leads_qualified + leads_none

    stats = {
        "total":    len(leads),
        "top":      sum(1 for l in leads if l["rec_class"] == "top"),
        "good":     sum(1 for l in leads if l["rec_class"] == "good"),
        "possible": sum(1 for l in leads if l["rec_class"] == "possible"),
        "none":     sum(1 for l in leads if l["rec_class"] == "none"),
        "no_website": len(without_website),
    }
    print(f"\nFertig: {stats}")
    return jsonify({"leads": leads, "stats": stats})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None
    print(f"""
+------------------------------------------+
|  LeadRadar Backend v4                    |
|  http://localhost:{port}                   |
|  Website-Lookup: Google + DuckDuckGo     |
|  Ketten-Filter:  aktiv                   |
|  Nur Leads MIT (schlechter) Website      |
+------------------------------------------+
""")
    app.run(debug=debug, port=port, host="0.0.0.0")
