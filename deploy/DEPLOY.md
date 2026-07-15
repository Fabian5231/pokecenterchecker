# Deployment auf dem VPS – pkmn-center.fabian-social.dev

Gleiches Muster wie dein bestehender Dienst `bnr.fabian-social.dev`:
**PCAlerts** läuft lokal auf `127.0.0.1:8080`, **nginx** ist der Reverse-Proxy,
**Certbot** stellt das SSL-Zertifikat aus und leitet HTTP→HTTPS um.

---

## 1. DNS setzen
Beim DNS-Anbieter von `fabian-social.dev` einen Eintrag anlegen:

```
Typ: A     Name: pkmn-center     Wert: <öffentliche IP deines VPS>
```
(Falls du IPv6 nutzt, zusätzlich ein `AAAA`-Record.)

Prüfen: `dig +short pkmn-center.fabian-social.dev` → muss die VPS-IP zeigen.

---

## 2. App installieren & als Dienst starten
```bash
git clone https://github.com/Fabian5231/pokecenterchecker.git /opt/pcalerts
cd /opt/pcalerts
chmod +x setup_vps.sh run.sh
./setup_vps.sh
nano .env
```
In der `.env` sicherstellen (wichtig fürs Proxy-Setup):
```
WEB_HOST=127.0.0.1      # nur lokal, nginx greift davor  (NICHT 0.0.0.0)
WEB_PORT=8080           # muss zum proxy_pass in der nginx-Konfig passen
HEADLESS=false          # headed unter xvfb
BROWSER_OFFSCREEN=false # egal auf headless-Server (kein Bildschirm da)
```
Dann Telegram-Daten eintragen und den Dienst starten:
```bash
sudo cp pcalerts.service /etc/systemd/system/pcalerts.service
# Pfade/User in der Datei prüfen (Standard: /opt/pcalerts)
sudo systemctl daemon-reload
sudo systemctl enable --now pcalerts
systemctl status pcalerts            # sollte "active (running)" zeigen
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080   # -> 200
```

---

## 3. nginx-Reverse-Proxy einrichten
```bash
sudo cp /opt/pcalerts/deploy/pkmn-center.fabian-social.dev.conf \
        /etc/nginx/sites-available/pkmn-center.fabian-social.dev
sudo ln -s /etc/nginx/sites-available/pkmn-center.fabian-social.dev \
           /etc/nginx/sites-enabled/
sudo nginx -t          # Syntax prüfen
sudo systemctl reload nginx
```

---

## 4. SSL mit Certbot (wie bei bnr)
```bash
sudo certbot --nginx -d pkmn-center.fabian-social.dev
```
Certbot holt das Zertifikat und schreibt den 443-Block + die HTTP→HTTPS-
Weiterleitung automatisch in die Konfig – identisch zu deinem anderen Dienst.
Die automatische Verlängerung ist über den bestehenden Certbot-Timer schon aktiv.

**Fertig:** https://pkmn-center.fabian-social.dev

---

## Kurz-Checks bei Problemen
| Symptom | Prüfen |
|---|---|
| 502 Bad Gateway | Läuft der Dienst? `systemctl status pcalerts`, `curl 127.0.0.1:8080` |
| Certbot findet Domain nicht | DNS korrekt? `dig +short pkmn-center.fabian-social.dev` |
| Dashboard zeigt „blocked" | VPS-IP evtl. von DataDome markiert → siehe README (Proxy-Hinweis) |
| App-Logs | `journalctl -u pcalerts -f` |
| nginx-Logs | `sudo tail -f /var/log/nginx/error.log` |
