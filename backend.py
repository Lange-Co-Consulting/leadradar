#!/usr/bin/env python3
"""
LeadRadar Backend — Echtes Flask-Backend
Startet mit: python backend.py
Dann im Browser: http://localhost:5000
"""

from flask import Flask, jsonify, request, send_from_directory
import requests
from bs4 import BeautifulSoup
import time
import re
import json
import os
from urllib.parse import quote_plus, urlparse
from datetime import datetime
import urllib3
urllib3.disable_warnings()

app = Flask(__name__, static_folder=".")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# ─────────────────────────────────────────
#  SCRAPING: GELBE SEITEN
# ─────────────────────────────────────────

def scrape_gelbe_seiten(query, location, max_results=20):
    businesses = []
    page = 1

    while len(businesses) < max_results:
        url = (
            f"https://www.gelbeseiten.de/suche/"
            f"{quote_plus(query)}/{quote_plus(location)}"
            f"?von={(page - 1) * 20 + 1}"
        )
        print(f"  [GS] Seite {page}: {url}")

        try:
            resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
            soup = BeautifulSoup(resp.text, "lxml")

            # Einträge finden — Gelbe Seiten nutzt article-Tags
            entries = (
                soup.find_all("article", {"class": re.compile(r"teilnehmer", re.I)})
                or soup.find_all("article")
            )

            if not entries:
                print("  [GS] Keine Einträge auf dieser Seite")
                break

            for entry in entries:
                biz = _parse_gelbe_eintrag(entry)
                if biz and biz["name"]:
                    businesses.append(biz)
                    print(f"  [GS] ✓ {biz['name']} | {biz.get('phone','–')} | {biz.get('website','–')[:40] if biz.get('website') else '–'}")
                if len(businesses) >= max_results:
                    break

            # Nächste Seite?
            next_btn = soup.find("a", {"class": re.compile(r"next|weiter", re.I)}) \
                       or soup.find("li", {"class": re.compile(r"next", re.I)})
            if not next_btn:
                break
            page += 1
            time.sleep(1.2)

        except Exception as e:
            print(f"  [GS] Fehler: {e}")
            break

    return businesses[:max_results]


def _parse_gelbe_eintrag(entry):
    """Parst einen einzelnen Gelbe-Seiten-Eintrag"""
    biz = {"name": "", "website": "", "phone": "", "address": "", "source": "Gelbe Seiten"}

    # NAME ─ h2 oder h3 im Eintrag
    for tag in ["h2", "h3", "h4"]:
        el = entry.find(tag)
        if el:
            biz["name"] = el.get_text(strip=True)
            break

    if not biz["name"]:
        # Fallback: data-Attribute
        biz["name"] = entry.get("data-name", "") or entry.get("aria-label", "")

    # WEBSITE ─ suche Link der nicht zu gelbeseiten.de geht
    for a in entry.find_all("a", href=True):
        href = a["href"]
        if re.match(r"https?://", href) and "gelbeseiten" not in href and "google" not in href:
            biz["website"] = href.split("?")[0].rstrip("/")
            break
    # Manchmal als data-url
    if not biz["website"]:
        for el in entry.find_all(attrs={"data-website": True}):
            biz["website"] = el["data-website"]
            break

    # TELEFON ─ tel: Link oder span mit Nummernmuster
    tel_link = entry.find("a", href=re.compile(r"^tel:"))
    if tel_link:
        biz["phone"] = tel_link["href"].replace("tel:", "").strip()
    else:
        # Text-Suche
        text = entry.get_text(" ", strip=True)
        m = re.search(r'(\+49[\d\s\-/]{7,}|0[\d][\d\s\-/]{8,})', text)
        if m:
            biz["phone"] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # ADRESSE
    addr = entry.find(["address", "span", "div", "p"],
                      {"class": re.compile(r"adress|address|location|ort|street|plz", re.I)})
    if addr:
        biz["address"] = re.sub(r'\s+', ' ', addr.get_text(" ", strip=True))
    else:
        # Fallback: PLZ-Muster im Text suchen
        text = entry.get_text(" ", strip=True)
        m = re.search(r'(\d{5}\s+\w[\w\s]{2,30})', text)
        if m:
            biz["address"] = m.group(1).strip()

    return biz


# ─────────────────────────────────────────
#  SCRAPING: KLICKTEL (Fallback)
# ─────────────────────────────────────────

def scrape_klicktel(query, location, max_results=20):
    businesses = []
    url = f"https://www.klicktel.de/branchenbuch/{quote_plus(query)}/{quote_plus(location)}/"
    print(f"  [KT] {url}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        soup = BeautifulSoup(resp.text, "lxml")

        entries = soup.find_all("div", {"class": re.compile(r"result-item|entry-item|branche", re.I)}) \
                  or soup.find_all("article")

        for entry in entries[:max_results]:
            biz = {"name": "", "website": "", "phone": "", "address": "", "source": "klicktel"}

            name_el = entry.find(["h2", "h3", "h4", "strong"])
            if name_el:
                biz["name"] = name_el.get_text(strip=True)

            tel_el = entry.find("a", href=re.compile(r"^tel:"))
            if tel_el:
                biz["phone"] = tel_el["href"].replace("tel:", "").strip()

            for a in entry.find_all("a", href=True):
                href = a["href"]
                if re.match(r"https?://", href) and "klicktel" not in href:
                    biz["website"] = href.split("?")[0].rstrip("/")
                    break

            if biz["name"]:
                businesses.append(biz)
                print(f"  [KT] ✓ {biz['name']}")

    except Exception as e:
        print(f"  [KT] Fehler: {e}")

    return businesses


# ─────────────────────────────────────────
#  WEBSITE-QUALITÄT PRÜFEN
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
        result["issues"].append("Keine Website vorhanden")
        result["recommendation"] = "TOP LEAD – Keine Website"
        result["rec_class"] = "top"
        result["score"] = 0
        return result

    if not url.startswith("http"):
        url = "https://" + url

    result["has_ssl"] = url.startswith("https://")
    if not result["has_ssl"]:
        result["issues"].append("Kein HTTPS/SSL")
        result["score"] -= 20

    start = time.time()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10,
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
            result["recommendation"] = "TOP LEAD – Website nicht erreichbar"
            result["rec_class"] = "top"
            result["score"] = 5
            return result

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

        # Veraltetes Copyright
        for yr_match in re.findall(r'©\s*(\d{4})|copyright\s+(\d{4})', resp.text.lower()):
            yr = int(yr_match[0] or yr_match[1])
            if yr < datetime.now().year - 3:
                result["issues"].append(f"Website seit {yr} nicht aktualisiert")
                result["score"] -= 20
                break

        if any(x in resp.text.lower() for x in ["react","vue","angular","next","gatsby","wordpress","shopify","typo3","joomla"]):
            result["score"] += 10

        result["score"] = max(0, min(100, 50 + result["score"]))

    except requests.exceptions.SSLError:
        result["issues"].append("SSL-Zertifikat ungültig")
        result["recommendation"] = "GUTER LEAD – SSL-Probleme"
        result["rec_class"] = "good"
        result["score"] = 10
        return result
    except requests.exceptions.ConnectionError:
        result["issues"].append("Domain nicht erreichbar")
        result["recommendation"] = "TOP LEAD – Website tot"
        result["rec_class"] = "top"
        result["score"] = 0
        return result
    except requests.exceptions.Timeout:
        result["issues"].append("Timeout >10s")
        result["recommendation"] = "GUTER LEAD – Website extrem langsam"
        result["rec_class"] = "good"
        result["score"] = 5
        return result
    except Exception as e:
        result["issues"].append(f"Fehler: {str(e)[:60]}")
        result["score"] = 0

    # Endklassifizierung
    s = result["score"]
    if s < 20:
        result["recommendation"] = "TOP LEAD – Sehr schlechte Website"
        result["rec_class"] = "top"
    elif s < 35:
        result["recommendation"] = "GUTER LEAD – Schlechte Website"
        result["rec_class"] = "good"
    elif s < 55:
        result["recommendation"] = "MÖGLICHER LEAD – Verbesserungswürdig"
        result["rec_class"] = "possible"
    else:
        result["recommendation"] = "KEIN LEAD – Website OK"
        result["rec_class"] = "none"

    return result


def make_outreach(biz, wc):
    name = biz.get("name", "Ihr Unternehmen")
    issues = wc.get("issues", [])
    if not wc.get("has_website"):
        subj = f"Online-Präsenz für {name}"
        body = (
            f"Guten Tag,\n\n"
            f"ich bin auf {name} aufmerksam geworden und habe festgestellt, "
            f"dass Sie aktuell keine eigene Website haben.\n\n"
            f"Über 80 % der Kunden recherchieren heute online, bevor sie einen Betrieb kontaktieren. "
            f"Eine professionelle Website kann Ihnen helfen, genau diese Kunden zu gewinnen – "
            f"ohne technischen Aufwand für Sie.\n\n"
            f"Darf ich Ihnen kurz zeigen, was ich für {name} tun könnte?\n\n"
            f"Mit freundlichen Grüßen"
        )
    elif issues:
        main = issues[0]
        subj = f"Kurze Frage zu Ihrer Website – {name}"
        body = (
            f"Guten Tag,\n\n"
            f"ich habe Ihre Website besucht und dabei festgestellt: {main}.\n\n"
            f"Das kostet täglich Kunden, die auf mobilen Geräten suchen oder bei langen Ladezeiten abspringen.\n\n"
            f"Ich helfe lokalen Unternehmen genau dabei – schnell und unkompliziert.\n\n"
            f"Hätten Sie 15 Minuten Zeit für ein kurzes Gespräch?\n\n"
            f"Mit freundlichen Grüßen"
        )
    else:
        subj = f"Digitale Präsenz – {name}"
        body = f"Guten Tag,\n\nich würde Ihnen gerne zeigen, wie Sie noch mehr Kunden online gewinnen können.\n\nMit freundlichen Grüßen"
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

    print(f"\n{'='*60}")
    print(f"Suche: '{query}' in '{location}' | max={max_r}")
    print(f"{'='*60}")

    # Primär: Gelbe Seiten
    businesses = scrape_gelbe_seiten(query, location, max_r)

    # Fallback: klicktel
    if len(businesses) < max_r // 2:
        print("  → Zu wenig Ergebnisse, versuche klicktel...")
        extra = scrape_klicktel(query, location, max_r - len(businesses))
        businesses.extend(extra)

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

    print(f"\n--- Website-Check für {len(businesses)} Unternehmen ---")

    leads = []
    for i, biz in enumerate(businesses):
        name = biz.get("name", "?")
        url  = biz.get("website", "")
        print(f"  [{i+1}/{len(businesses)}] {name[:40]} | {url[:40] if url else '(keine Website)'}")

        wc = check_website(url)
        outreach = make_outreach(biz, wc)

        leads.append({
            **biz,
            "website_score":   wc["score"],
            "has_ssl":         wc["has_ssl"],
            "is_reachable":    wc["is_reachable"],
            "load_time":       wc["load_time"],
            "status_code":     wc["status_code"],
            "is_mobile":       wc["is_mobile_friendly"],
            "has_content":     wc["has_content"],
            "page_size_kb":    wc["page_size_kb"],
            "issues":          wc["issues"],
            "recommendation":  wc["recommendation"],
            "rec_class":       wc["rec_class"],
            "outreach_subject": outreach["subject"],
            "outreach_body":    outreach["body"],
            "scraped_at":       datetime.now().strftime("%d.%m.%Y %H:%M"),
        })
        time.sleep(0.8)  # Höfliche Pause

    # Sortieren: schlechteste Website zuerst
    leads.sort(key=lambda x: x["website_score"])

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
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None  # debug nur lokal
    print(f"""
╔══════════════════════════════════════╗
║  LeadRadar Backend gestartet         ║
║  → http://localhost:{port}             ║
╚══════════════════════════════════════╝
""")
    app.run(debug=debug, port=port, host="0.0.0.0")
