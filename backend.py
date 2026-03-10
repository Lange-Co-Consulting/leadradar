#!/usr/bin/env python3
"""
LeadRadar Backend v3
- Filtert Ketten/Franchises heraus
- Filtert geschlossene Betriebe heraus
- Priorisiert schlechte Websites über keine Website
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# Bekannte Ketten und Franchises
CHAIN_BLACKLIST = [
    "subway","mcdonald","burger king","kfc","pizza hut","domino","vapiano",
    "nordsee","wienerwald","hans im gluck","hans im glück","peter pane",
    "enchilada","l'osteria","dean david","dean & david","ditsch","backwerk",
    "le crobag","jim block","five guys","dunkin","starbucks","costa coffee",
    "tchibo","balzac","yorma","cinnabon",
    "aldi","lidl","rewe","edeka","penny","netto","kaufland",
    "dm drogerie","rossmann","saturn","mediamarkt","ikea","obi ","bauhaus",
    "hornbach","toom","hagebau","deichmann","snipes","foot locker",
    "h&m","zara","primark","c&a","esprit","douglas","thalia","hugendubel",
    "fielmann","apollo optik","mcfit","fitx","clever fit","fitness first",
    "sixt","hertz","europcar","telekom shop","o2 shop","vodafone shop",
    "motel one","ibis ","novotel","mercure","holiday inn","hilton","marriott",
    "radisson","a&o hostel","meininger","takko","kik ","nkd ","woolworth",
    "mc paper","backofenfrisch","norma ","action ",
]

# Keywords fuer geschlossene Betriebe
CLOSED_KEYWORDS = [
    "dauerhaft geschlossen","permanently closed","geschaeft geschlossen",
    "betrieb eingestellt","aufgeloest","insolvenz","insolvent",
    "voruebergehend geschlossen","wir haben geschlossen",
    "diese domain ist nicht","domain expired","account suspended",
    "parked domain","under construction","coming soon",
]


def is_chain(name):
    n = name.lower()
    for c in CHAIN_BLACKLIST:
        if c in n:
            return True
    return False


def is_closed(text, name):
    combined = (text + " " + name).lower()
    for kw in CLOSED_KEYWORDS:
        if kw in combined:
            return True
    return False


def scrape_gelbe_seiten(query, location, max_results=20):
    businesses = []
    page = 1
    target = max_results * 3  # Mehr scrapen wegen Filter

    while len(businesses) < target and page <= 8:
        url = (
            f"https://www.gelbeseiten.de/suche/"
            f"{quote_plus(query)}/{quote_plus(location)}"
            f"?von={(page - 1) * 20 + 1}"
        )
        print(f"  [GS] Seite {page}: {url}")

        try:
            resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
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
                print(f"  [OK] {biz['name']} | {biz.get('phone','--')} | {(biz.get('website') or '--')[:40]}")

            next_btn = soup.find("a", {"class": re.compile(r"next|weiter", re.I)})
            if not next_btn:
                break
            page += 1
            time.sleep(1.2)

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

    for a in entry.find_all("a", href=True):
        href = a["href"]
        if re.match(r"https?://", href) and "gelbeseiten" not in href and "google" not in href:
            biz["website"] = href.split("?")[0].rstrip("/")
            break
    if not biz["website"]:
        for el in entry.find_all(attrs={"data-website": True}):
            biz["website"] = el["data-website"]
            break

    tel_link = entry.find("a", href=re.compile(r"^tel:"))
    if tel_link:
        biz["phone"] = tel_link["href"].replace("tel:", "").strip()
    else:
        text = entry.get_text(" ", strip=True)
        m = re.search(r'(\+49[\d\s\-/]{7,}|0[\d][\d\s\-/]{8,})', text)
        if m:
            biz["phone"] = re.sub(r'\s+', ' ', m.group(1)).strip()

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


def scrape_klicktel(query, location, max_results=20):
    businesses = []
    url = f"https://www.klicktel.de/branchenbuch/{quote_plus(query)}/{quote_plus(location)}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        soup = BeautifulSoup(resp.text, "lxml")
        entries = (soup.find_all("div", {"class": re.compile(r"result-item|entry-item|branche", re.I)})
                   or soup.find_all("article"))
        for entry in entries:
            biz = {"name": "", "website": "", "phone": "", "address": "", "source": "klicktel"}
            name_el = entry.find(["h2","h3","h4","strong"])
            if name_el:
                biz["name"] = name_el.get_text(strip=True)
            if not biz["name"]:
                continue
            if is_chain(biz["name"]) or is_closed(entry.get_text(" ", strip=True), biz["name"]):
                continue
            tel_el = entry.find("a", href=re.compile(r"^tel:"))
            if tel_el:
                biz["phone"] = tel_el["href"].replace("tel:", "").strip()
            for a in entry.find_all("a", href=True):
                href = a["href"]
                if re.match(r"https?://", href) and "klicktel" not in href:
                    biz["website"] = href.split("?")[0].rstrip("/")
                    break
            businesses.append(biz)
            if len(businesses) >= max_results:
                break
    except Exception as e:
        print(f"  [KT] Fehler: {e}")
    return businesses


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

    # Keine Website: guter, aber NICHT top Lead
    # Schlechte Website ist wertvoller (Firma ist bereits online-affin)
    if not url:
        result["issues"].append("Keine Website vorhanden")
        result["recommendation"] = "GUTER LEAD - Keine Website"
        result["rec_class"] = "good"
        result["score"] = 28
        return result

    if not url.startswith("http"):
        url = "https://" + url

    result["has_ssl"] = url.startswith("https://")
    if not result["has_ssl"]:
        result["issues"].append("Kein HTTPS/SSL")
        result["score"] -= 20

    start = time.time()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=False, allow_redirects=True)
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
        for kw in ["domain expired","account suspended","parked domain","under construction",
                   "coming soon","diese domain","domain ist abgelaufen"]:
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

        for yr_match in re.findall(r'copyright\s+(\d{4})|(\d{4})\s+all rights|&copy;\s*(\d{4})', page_lower):
            yr_str = yr_match[0] or yr_match[1] or yr_match[2]
            if yr_str:
                yr = int(yr_str)
                if yr < datetime.now().year - 3:
                    result["issues"].append(f"Website seit {yr} nicht aktualisiert")
                    result["score"] -= 20
                    break

        if re.search(r'cellpadding|cellspacing|bgcolor=', resp.text, re.I):
            result["issues"].append("Veraltetes HTML-Layout")
            result["score"] -= 10

        if any(x in page_lower for x in ["react","vue","angular","next","gatsby",
               "wordpress","shopify","typo3","joomla","wix","squarespace"]):
            result["score"] += 10

        result["score"] = max(0, min(100, 50 + result["score"]))

    except requests.exceptions.SSLError:
        result["issues"].append("SSL-Zertifikat ungueltig")
        result["recommendation"] = "TOP LEAD - SSL-Probleme"
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
        result["recommendation"] = "TOP LEAD - Website extrem langsam"
        result["rec_class"] = "top"
        result["score"] = 8
        return result
    except Exception as e:
        result["issues"].append(f"Fehler: {str(e)[:60]}")
        result["score"] = 0

    s = result["score"]
    if s < 15:
        result["recommendation"] = "TOP LEAD - Sehr schlechte Website"
        result["rec_class"] = "top"
    elif s < 30:
        result["recommendation"] = "TOP LEAD - Schlechte Website"
        result["rec_class"] = "top"
    elif s < 45:
        result["recommendation"] = "GUTER LEAD - Verbesserungsbedarf"
        result["rec_class"] = "good"
    elif s < 60:
        result["recommendation"] = "MOEGLICHER LEAD - Ausbaufaehig"
        result["rec_class"] = "possible"
    else:
        result["recommendation"] = "KEIN LEAD - Website OK"
        result["rec_class"] = "none"

    return result


def make_outreach(biz, wc):
    name = biz.get("name", "Ihr Unternehmen")
    issues = wc.get("issues", [])

    if not wc.get("has_website"):
        subj = f"Online-Praesenz fuer {name}"
        body = (f"Guten Tag,\n\nich bin auf {name} aufmerksam geworden und habe festgestellt, "
                f"dass Sie aktuell keine eigene Website haben.\n\nUeber 80 % der Kunden recherchieren "
                f"heute online. Eine professionelle Website kann Ihnen helfen, genau diese Kunden zu gewinnen.\n\n"
                f"Darf ich Ihnen kurz zeigen, was ich fuer {name} tun koennte?\n\nMit freundlichen Gruessen")
    elif not wc.get("is_reachable"):
        subj = f"Ihre Website ist nicht erreichbar - {name}"
        body = (f"Guten Tag,\n\nIhre Website ist aktuell nicht erreichbar. Potenzielle Kunden, "
                f"die online nach {name} suchen, landen auf einer toten Seite.\n\n"
                f"Ich kann helfen, das schnell zu beheben.\n\nMit freundlichen Gruessen")
    elif issues:
        main = issues[0]
        if "langsam" in main.lower():
            prob = f"Ihre Website laedt sehr langsam ({main}). Viele Besucher springen ab, bevor sie Ihre Inhalte sehen."
        elif "ssl" in main.lower() or "https" in main.lower():
            prob = "Ihre Website hat kein HTTPS. Browser zeigen Besuchern eine Sicherheitswarnung - das kostet Vertrauen."
        elif "mobile" in main.lower():
            prob = "Ihre Website ist nicht fuer Smartphones optimiert. Ueber 60 % der Suchanfragen kommen vom Handy."
        elif "aktualisiert" in main.lower():
            prob = f"Ihre Website wurde lange nicht aktualisiert ({main}). Das schadet dem Google-Ranking."
        else:
            prob = f"Ihre Website hat ein technisches Problem: {main}."
        subj = f"Kurze Frage zu Ihrer Website - {name}"
        body = (f"Guten Tag,\n\n{prob}\n\nIch helfe lokalen Unternehmen wie {name} dabei, "
                f"solche Probleme schnell zu loesen.\n\nHaetten Sie 15 Minuten fuer ein kurzes Gespraech?\n\nMit freundlichen Gruessen")
    else:
        subj = f"Digitale Praesenz - {name}"
        body = f"Guten Tag,\n\nIch wuerde Ihnen gerne zeigen, wie Sie noch mehr Kunden online gewinnen koennen.\n\nMit freundlichen Gruessen"

    return {"subject": subj, "body": body}


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

    businesses = scrape_gelbe_seiten(query, location, max_r)

    if len(businesses) < max_r // 2:
        print("  Zu wenig Ergebnisse, versuche klicktel...")
        extra = scrape_klicktel(query, location, max_r * 2)
        businesses.extend(extra)

    seen, unique = set(), []
    for b in businesses:
        key = b["name"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(b)
    businesses = unique[:max_r]

    print(f"\n{len(businesses)} Unternehmen nach Filterung. Website-Check startet...")

    if not businesses:
        return jsonify({"leads": [], "stats": {}, "message": "Keine Unternehmen gefunden."}), 200

    leads = []
    for i, biz in enumerate(businesses):
        name = biz.get("name", "?")
        url  = biz.get("website", "")
        print(f"  [{i+1}/{len(businesses)}] {name[:45]} | {url[:40] if url else '(keine Website)'}")
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
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None
    print(f"""
+--------------------------------------+
|  LeadRadar Backend v3 gestartet      |
|  http://localhost:{port}               |
|  Ketten-Filter:       aktiv          |
|  Geschlossen-Filter:  aktiv          |
|  Score: schlechte Website = Top Lead |
+--------------------------------------+
""")
    app.run(debug=debug, port=port, host="0.0.0.0")
