# Strava-Integration – Einrichtung und Deployment

## Übersicht

Die Strava-Integration ermöglicht es, Fahrradaktivitäten aus Strava automatisch als Bikepacking-Etappen zu importieren. Bestehende manuelle Garmin- und Colab-Importe bleiben vollständig erhalten.

---

## 1. Voraussetzungen

- Python 3.10+
- Öffentlich erreichbare URL für den OAuth-Callback und den Webhook-Endpunkt (z. B. via Reverse-Proxy oder ngrok beim lokalen Testen)

---

## 2. Strava API-Anwendung anlegen

1. Besuche <https://www.strava.com/settings/api>
2. Klicke auf **Create & Manage Your App**
3. Fülle das Formular aus:
   - **Application Name**: z. B. `Bikepacking Diary`
   - **Category**: Other
   - **Club**: leer lassen
   - **Website**: deine App-URL
   - **Authorization Callback Domain**: der Hostname deiner App (z. B. `yourapp.example.com`)
4. Notiere **Client ID** und **Client Secret**

---

## 3. Umgebungsvariablen setzen

Kopiere `.env.example` nach `.env` und setze folgende Werte:

```dotenv
# Strava OAuth
STRAVA_CLIENT_ID=<deine Strava Client-ID>
STRAVA_CLIENT_SECRET=<dein Strava Client-Secret>

# Vollständige Callback-URL (muss mit dem Hostname in der Strava-App übereinstimmen)
STRAVA_CALLBACK_URL=https://yourapp.example.com/strava/callback

# Zufälliges Geheimnis für Webhook-Verifikation (selbst gewählt, z. B. uuid4)
STRAVA_WEBHOOK_VERIFY_TOKEN=<zufälliger_geheimer_string>
```

> **Wichtig:** `STRAVA_CLIENT_SECRET` und `STRAVA_WEBHOOK_VERIFY_TOKEN` dürfen niemals in Code, Logs oder API-Antworten erscheinen. Die App liest diese Werte ausschließlich aus Umgebungsvariablen.

---

## 4. Anwendung starten

```bash
pip install -r requirements.txt
python app.py
```

---

## 5. Strava verbinden (OAuth)

1. Öffne `/settings` in der Web-App
2. Im Abschnitt **Strava-Integration** → **Mit Strava verbinden** klicken
3. Du wirst zu Strava weitergeleitet und authorisierst die App
4. Nach erfolgreicher Verbindung erscheint der Abschnitt **Erstmaliger Import**

---

## 6. Erstmaliger Import

1. Nach dem Verbinden Start- und Enddatum für den Importzeitraum eingeben
2. **Strava-Aktivitäten importieren** klicken
3. Die App:
   - Holt alle Fahrradaktivitäten (Ride, GravelRide, MountainBikeRide, EBikeRide) im Zeitraum
   - Speichert den Zeitraum als Tour-Zeitraum
   - Erstellt Pausentage für Tage ohne Aktivität

---

## 7. Automatische Synchronisation via Webhook

Damit neue, geänderte oder gelöschte Strava-Aktivitäten automatisch synchronisiert werden, muss ein Strava-Webhook abonniert werden.

### Webhook-Endpunkt

```
GET/POST https://yourapp.example.com/strava/webhook
```

### Webhook-Abonnement anlegen (einmalig)

```bash
curl -X POST https://www.strava.com/api/v3/push_subscriptions \
  -F client_id=<STRAVA_CLIENT_ID> \
  -F client_secret=<STRAVA_CLIENT_SECRET> \
  -F callback_url=https://yourapp.example.com/strava/webhook \
  -F verify_token=<STRAVA_WEBHOOK_VERIFY_TOKEN>
```

Strava sendet sofort eine GET-Anfrage zur Verifikation. Die App antwortet automatisch mit dem `hub.challenge`.

### Webhook-Ereignisse

| Ereignis | Aktion |
|---|---|
| `activity.create` | Aktivität importieren, Pausentage aktualisieren |
| `activity.update` | Aktivität aktualisieren, Tageszuordnung neu berechnen |
| `activity.delete` | Aktivität entfernen, ggf. Pausentag anlegen |
| `athlete.deauthorize` | Tokens löschen (Reisedaten bleiben erhalten) |

---

## 8. Lokale Entwicklung mit ngrok

```bash
ngrok http 5000
```

Setze `STRAVA_CALLBACK_URL` und die Callback-URL in deiner Strava-App-Konfiguration auf die ngrok-URL.

---

## 9. Tests ausführen

```bash
python -m pytest tests/ -v
```

---

## 10. Datenbankmigrationen

Die Migration wird automatisch beim Start der App (`init_db()`) angewendet. Folgende Änderungen werden an bestehenden Datenbanken vorgenommen:

| Tabelle | Neue Spalte | Typ | Beschreibung |
|---|---|---|---|
| `tours` | `end_date` | TEXT | Enddatum der Tour |
| `stages` | `source` | TEXT | Datenquelle (`manual`, `strava`, `rest`) |
| `stages` | `external_activity_id` | TEXT | Strava-Aktivitäts-ID |
| `stages` | `average_speed` | REAL | Durchschnittsgeschwindigkeit in km/h |
| `stages` | `max_speed` | REAL | Maximalgeschwindigkeit in km/h |
| `stages` | `average_cadence` | REAL | Durchschnittliche Trittfrequenz |
| `stages` | `temperature` | REAL | Durchschnittstemperatur in °C |
| `stages` | `is_rest_day` | INTEGER | 1 = Pausentag, 0 = Aktivitätstag |
| `stages` | `location` | TEXT | Aufenthaltsort (manuell eingebbar) |
| `strava_tokens` | – | neue Tabelle | Speichert OAuth-Tokens |

Eindeutiger Index: `(source, external_activity_id)` verhindert Duplikate bei wiederholtem Import.

---

## 11. Bekannte Einschränkungen und offene Punkte

- **Kein Benutzerlogin**: Die App ist als Single-User-App konzipiert. Strava-Tokens werden global gespeichert.
- **Webhook-Abonnement manuell**: Das Anlegen des Webhook-Abonnements bei Strava muss einmalig manuell (per curl oder Strava-API) durchgeführt werden.
- **VirtualRide nicht importiert**: Virtuelle Fahrten werden standardmäßig übersprungen.
- **Manuelle Duplikatserkennung**: Bei ähnlichen manuellen und Strava-Aktivitäten wird ein Eintrag im Log erstellt; automatisches Zusammenführen wird nicht durchgeführt.
- **Foto-Import**: Strava-Aktivitätsfotos werden nicht automatisch importiert (Strava-API-Beschränkung).
- **Herzfrequenz-Zonen und Segmente**: Werden nicht importiert.
