# PCAlerts – Pokémon Center Monitor

Überwacht eine Kategorie-Seite von **Pokémon Center Deutschland** und meldet,
sobald **neue Sammelkarten-Artikel gelistet** oder **wieder verfügbar** werden –
über eine **Weboberfläche** und per **Telegram-Nachricht**.

![Kurz gesagt](https://img.shields.io/badge/status-fertig-brightgreen)

---

## Was es kann

- Prüft die Seite automatisch alle 1–2 Minuten (einstellbar).
- Weboberfläche zeigt: letzte Prüfung, aktuelle Artikel + Verfügbarkeit,
  erkannte Ereignisse und die komplette Prüf-Historie.
- Telegram-Bot benachrichtigt dich sofort bei neuen / wieder verfügbaren Artikeln.
- Kommt am Bot-Schutz der Seite (DataDome + Imperva Incapsula) vorbei, indem ein
  echter, getarnter Browser verwendet wird.

## Wie es funktioniert (kurz)

Die Pokémon-Center-Seite ist eine JavaScript-App mit **starkem Bot-Schutz**.
Einfache HTTP-Abrufe werden mit `403` / Captcha blockiert. Deshalb nutzt PCAlerts
[`patchright`](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) – einen
getarnten Chromium-Browser – der die Seite wie ein echter Nutzer lädt, das
JavaScript ausführt und die Produktdaten aus dem eingebetteten `JSON-LD` ausliest.

> **Wichtig:** Der Browser muss **sichtbar** laufen (`HEADLESS=false`), sonst
> greift der Bot-Schutz. Auf einem Windows-PC mit angemeldeter Sitzung passt das
> direkt. Auf einem Linux-Server ohne Bildschirm sorgt das mitgelieferte
> `run.sh` automatisch für einen virtuellen Bildschirm (`xvfb`).

---

## Installation

### Voraussetzungen
- Python 3.11+ (getestet mit 3.13)

### Windows
```powershell
cd C:\Users\admin\Desktop\PCAlerts
.\run.ps1        # legt venv an, installiert alles, kopiert .env
# .env bearbeiten (siehe unten), dann erneut:
.\run.ps1
```

### Linux / macOS
```bash
cd PCAlerts
./run.sh         # legt venv an, installiert alles, kopiert .env
# Auf Servern ohne Bildschirm einmalig:  sudo apt install xvfb
# .env bearbeiten, dann erneut:
./run.sh
```

Danach im Browser öffnen: **http://127.0.0.1:8080**

---

## Auf einem headless-VPS betreiben (Linux, ohne Grafikoberfläche)

Ein Browser braucht **keinen Bildschirm** – `xvfb` stellt einen virtuellen,
unsichtbaren Bildschirm bereit. Chromium läuft darauf komplett im Hintergrund,
es wird **kein Desktop / keine GUI** benötigt.

**1. Einrichtung (einmalig):**
```bash
# Projekt z. B. nach /opt/pcalerts kopieren, dann:
cd /opt/pcalerts
chmod +x setup_vps.sh run.sh
./setup_vps.sh          # installiert python-venv, xvfb, Chromium + alles
nano .env               # Telegram-Daten eintragen, HEADLESS=false lassen!
```

**2. Zum Testen im Vordergrund:**
```bash
./run.sh                # erkennt fehlendes Display und nutzt automatisch xvfb
```

**3. Dauerbetrieb als Dienst (empfohlen):**
```bash
sudo cp pcalerts.service /etc/systemd/system/pcalerts.service
# Pfade/User in der Datei prüfen (Standard: /opt/pcalerts, User "pcalerts")
sudo systemctl daemon-reload
sudo systemctl enable --now pcalerts
systemctl status pcalerts          # Status
journalctl -u pcalerts -f          # Live-Logs
```

**4. Dashboard vom eigenen PC aus erreichen** (der VPS hat keinen Browser):
- **Per Domain + HTTPS (empfohlen, wie die anderen Dienste):** nginx-Reverse-Proxy
  + Certbot. Komplette Schritt-für-Schritt-Anleitung inkl. fertiger nginx-Konfig:
  **[`deploy/DEPLOY.md`](deploy/DEPLOY.md)** → Ergebnis: `https://pkmn-center.fabian-social.dev`
- **Schnell zum Testen:** SSH-Tunnel vom eigenen Rechner:
  ```bash
  ssh -L 8080:127.0.0.1:8080 benutzer@dein-vps
  ```
  Dann lokal `http://127.0.0.1:8080` öffnen.
- Bei Proxy-Betrieb `WEB_HOST=127.0.0.1` lassen (nur nginx greift davor).

> ⚠️ **Wichtig zu VPS-IP-Adressen:** DataDome stuft **Rechenzentrums-IPs**
> (typische VPS-Adressen) strenger ein als normale Privat-Anschlüsse. Es kann
> sein, dass dein VPS häufiger „blockiert" wird als dein Heim-PC. Falls das
> passiert: Prüfintervall erhöhen (z. B. `CHECK_INTERVAL_SECONDS=120`), und
> wenn es dauerhaft blockiert, hilft nur ein **Wohn-/Mobil-Proxy** (residential
> proxy). Ein kleiner, günstiger VPS bei einem weniger „verbrannten" Anbieter
> ist oft weniger betroffen.

---

## Telegram-Bot einrichten (3 Minuten)

1. **Bot erstellen:** In Telegram [@BotFather](https://t.me/BotFather) öffnen,
   `/newbot` senden, Namen + Benutzernamen vergeben. Du bekommst einen **Token**
   wie `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
2. Token in die Datei **`.env`** eintragen:
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
3. **Deinem Bot in Telegram eine beliebige Nachricht schreiben** (z. B. „hallo").
4. Chat-ID ermitteln:
   ```
   .venv\Scripts\python.exe get_chat_id.py      # Windows
   ./.venv/bin/python get_chat_id.py            # Linux/macOS
   ```
   Die angezeigte Zahl in die `.env` eintragen:
   ```
   TELEGRAM_CHAT_ID=987654321
   ```
5. Test senden:
   ```
   .venv\Scripts\python.exe notifier.py
   ```
   Kommt die Testnachricht an, ist alles fertig. PCAlerts neu starten.

---

## Konfiguration (`.env`)

| Einstellung | Bedeutung | Standard |
|---|---|---|
| `PC_URL` | Zu überwachende Kategorie-URL | Elite-Trainer-Box / Tins |
| `CHECK_INTERVAL_SECONDS` | Prüfintervall in Sekunden | `90` |
| `HEADLESS` | Browser unsichtbar? (siehe Warnung oben) | `false` |
| `TELEGRAM_BOT_TOKEN` | Bot-Token von BotFather | – |
| `TELEGRAM_CHAT_ID` | Deine Chat-ID | – |
| `NOTIFY_ON` | `new` (neu gelistet), `restock` (wieder verfügbar) | `new,restock` |
| `WEB_HOST` / `WEB_PORT` | Adresse der Weboberfläche | `127.0.0.1` / `8080` |

**Andere Kategorie überwachen:** Einfach die gewünschte Kategorie-Seite auf
pokemoncenter.com öffnen, die URL aus der Adresszeile kopieren und als `PC_URL`
eintragen. Das Auslesen funktioniert für jede Produktkategorie identisch.

**Von anderen Geräten erreichbar machen:** `WEB_HOST=0.0.0.0` setzen (dann ist
das Dashboard im lokalen Netz erreichbar).

---

## Als Dauerbetrieb einrichten

- **Windows:** Aufgabenplanung → neue Aufgabe → „Bei Anmeldung" → Programm
  `…\PCAlerts\run.ps1` (über `powershell.exe -File run.ps1`). So läuft es in der
  angemeldeten Sitzung (nötig für den sichtbaren Browser).
- **Linux:** `run.sh` per `systemd`-Service oder in `tmux`/`screen` starten
  (mit installiertem `xvfb`).

---

## Wichtige Hinweise

- **Erste erfolgreiche Prüfung = Basis.** Beim allerersten OK-Lauf werden alle
  aktuell sichtbaren Artikel als „bekannt" gespeichert (keine Benachrichtigung).
  Ab dann meldet PCAlerts nur noch echte Neuzugänge / Wieder-Verfügbarkeiten.
- **Gelegentliche „blockiert"-Einträge sind normal.** Der Bot-Schutz greift
  manchmal; PCAlerts wärmt die Sitzung dann neu auf und versucht es beim nächsten
  Intervall erneut. Wenn es dauerhaft blockiert: Intervall erhöhen (z. B. 120 s)
  und sicherstellen, dass `HEADLESS=false` ist.
- **Dauerhaft blockiert nach vielen schnellen Zugriffen?** Dann hat DataDome
  deine **IP vorübergehend markiert** (das passiert bei sehr häufigem Testen).
  Auch die Startseite ist dann im Browser leer/geblockt. Lösung: einige Stunden
  warten (die Sperre löst sich von selbst), moderates Intervall verwenden
  (≥ 90 s) und nicht manuell im Sekundentakt „Jetzt prüfen" drücken. Ein
  Neustart deines Routers (neue IP) hilft oft sofort.
- Nutze das Tool verantwortungsvoll (moderates Intervall). Es ist für den
  persönlichen Gebrauch gedacht.

## Dateien

| Datei | Zweck |
|---|---|
| `web.py` | Startpunkt: Weboberfläche + Hintergrund-Monitor |
| `monitor.py` | Prüf-Schleife + Erkennung neuer/verfügbarer Artikel |
| `scraper.py` | Getarnter Browser + Datenextraktion |
| `notifier.py` | Telegram-Nachrichten |
| `get_chat_id.py` | Helfer zum Ermitteln der Telegram-Chat-ID |
| `db.py` | SQLite-Speicher (Snapshot, Ereignisse, Historie) |
| `config.py` | Konfiguration aus `.env` |
