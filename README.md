# 📡 LeadRadar v2 — Echtes Backend

Findet **echte Unternehmen** (Gelbe Seiten + klicktel) und prüft ihre Website-Qualität.

---

## 🚀 Setup (3 Schritte)

### 1. Python-Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```

### 2. Backend starten
```bash
python backend.py
```
→ Terminal zeigt: `http://localhost:5000`

### 3. Browser öffnen
```
http://localhost:5000
```
Das ist alles. Die `index.html` wird automatisch vom Backend ausgeliefert.

---

## 💡 Wie es funktioniert

```
Browser (index.html)
  ↓  [Klick "Starten"]
  ↓  GET /api/scrape?query=Handwerker&location=München&max=20
  ↓
Flask Backend (backend.py)
  ↓  scrapt gelbeseiten.de
  ↓  scrapt klicktel.de (Fallback)
  ↓  prüft jede Website (SSL, Ladezeit, Inhalt, Mobile...)
  ↓  berechnet Lead-Score 0–100
  ↓  generiert Cold-Outreach-Text
  ↓
  ↑  JSON mit echten Leads zurück
  ↑
Browser zeigt Ergebnisse sortiert nach Qualität
```

---

## 📊 Lead-Score-System

| Score | Kategorie | Bedeutung |
|-------|-----------|-----------|
| 0–10  | 🎯 **TOP LEAD**  | Keine Website / Website tot |
| 10–35 | ✅ **GUTER LEAD** | Schlechte Website (kein SSL, langsam, veraltet) |
| 35–55 | ⚠ **MÖGLICHER LEAD** | Verbesserungsbedarf |
| 55+   | ❌ **KEIN LEAD** | Website ausreichend |

---

## 🌟 Features v2

- ✅ **Echte Daten** von Gelbe Seiten & klicktel
- ✅ **Light / Dark Mode** (gespeichert im Browser)
- ✅ **Klickbare Website-URLs** (öffnen im neuen Tab)
- ✅ **Klickbare Telefonnummern** (öffnen Telefon-App)
- ✅ **Paginierung** — lädt wirklich die gewünschte Anzahl
- ✅ **CSV-Export** mit allen Daten inkl. Outreach-Texte
- ✅ **Outreach-Text kopieren** per Klick

---

## ⚖ DSGVO-Hinweis

B2B Cold Email ist erlaubt wenn:
- Legitimes Interesse besteht (du bietest eine relevante Dienstleistung an)
- Eine Abmelde-Option enthalten ist
- Nur Geschäftskontakte angeschrieben werden
