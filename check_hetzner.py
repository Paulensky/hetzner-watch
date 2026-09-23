#!/usr/bin/env python3
"""Prueft ueber die Hetzner Cloud API, ob bestimmte Servertypen an bestimmten
Standorten bestellbar sind, und schickt bei einem Wechsel auf "verfuegbar"
eine Push-Nachricht ueber ntfy.sh.

Nutzt GET /v1/server_types -> server_types[].locations[].available
(der alte Weg ueber /v1/datacenters wird nach dem 01.10.2026 abgeschaltet).
Nur Standardbibliothek, keine Abhaengigkeiten.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.hetzner.cloud/v1"
TOKEN = os.environ.get("HCLOUD_TOKEN", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
SERVER_TYPES = [s.strip() for s in os.environ.get("SERVER_TYPES", "cx33,cax21").split(",") if s.strip()]
LOCATIONS = [s.strip() for s in os.environ.get("LOCATIONS", "fsn1,nbg1").split(",") if s.strip()]
STATE_FILE = os.environ.get("STATE_FILE", "state/last.json")
FORCE_TEST = os.environ.get("FORCE_TEST", "").lower() == "true"
CONSOLE_URL = "https://console.hetzner.com/"


def api_get(path, params):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def location_name(loc):
    # robust gegen beide moeglichen Formen: flach oder verschachtelt
    return loc.get("name") or (loc.get("location") or {}).get("name")


def fetch_availability():
    result = {}
    for st in SERVER_TYPES:
        data = api_get("/server_types", {"name": st})
        types = data.get("server_types") or []
        if not types:
            sys.exit(f"FEHLER: Servertyp '{st}' nicht gefunden (Name falsch oder eingestellt?)")
        locs = types[0].get("locations")
        if locs is None:
            sys.exit("FEHLER: Feld 'locations' fehlt - hat Hetzner die API-Struktur geaendert?\n"
                     + json.dumps(types[0], indent=2)[:2000])
        for loc in locs:
            name = location_name(loc)
            if name in LOCATIONS:
                result[f"{st}@{name}"] = bool(loc.get("available"))
        missing = [l for l in LOCATIONS if f"{st}@{l}" not in result]
        for l in missing:
            # Standort wird fuer diesen Typ gar nicht angeboten
            result[f"{st}@{l}"] = False
    return result


def notify(title, message, priority="high", tags="rocket"):
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        method="POST",
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": CONSOLE_URL},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def main():
    if not TOKEN or not NTFY_TOPIC:
        sys.exit("FEHLER: Secrets HCLOUD_TOKEN und/oder NTFY_TOPIC fehlen.")

    if FORCE_TEST:
        notify("Hetzner-Watch: Test", "Test erfolgreich - Push kommt an.", priority="default", tags="white_check_mark")
        print("Test-Push gesendet.")

    current = fetch_availability()
    previous = load_state()

    for key in sorted(current):
        print(f"{key:<16} {'VERFUEGBAR' if current[key] else 'ausverkauft'}")

    newly = [k for k, v in current.items() if v and not previous.get(k)]
    if newly:
        pretty = ", ".join(k.replace("@", " in ").upper() for k in sorted(newly))
        notify("Hetzner: Server frei", f"Jetzt bestellbar: {pretty}. Schnell sein - oft nach Minuten wieder weg.")
        print(f"Push gesendet fuer: {pretty}")

    save_state(current)


if __name__ == "__main__":
    main()
