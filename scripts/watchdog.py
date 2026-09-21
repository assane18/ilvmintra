#!/var/www/intranet/venv/bin/python3
"""Surveillance de disponibilité de l'intranet ILVM, indépendante de Flask.

Vérifie toutes les 5 minutes (via cron) :
  1. Que le service systemd tourne (`systemctl is-active intranet.service`).
  2. Que l'application répond réellement (GET /intranet/health via nginx,
     pas juste que le process gunicorn existe — un service "active" peut
     très bien être bloqué/planté côté applicatif).

N'envoie un email QUE lors d'un changement d'état (panne détectée, ou retour
à la normale après une panne) — pas à chaque exécution, pour éviter le spam.
L'état précédent est gardé dans STATE_FILE.

Usage cron (toutes les 5 min) :
  */5 * * * * /var/www/intranet/scripts/watchdog.py >> /var/www/intranet/backups/watchdog.log 2>&1
"""
import smtplib
import subprocess
import sys
from datetime import datetime
from email.mime.text import MIMEText

sys.path.insert(0, '/var/www/intranet')
from config import Config  # noqa: E402

STATE_FILE = '/var/www/intranet/backups/.watchdog_state'
HEALTH_URL = 'https://localhost/intranet/health'
RECIPIENTS = ['ATraore2@ilvm.fr', 'Arichard@ilvm.fr', 'DSI@ilvm.fr']
TIMEOUT = 5


def check_service():
    try:
        out = subprocess.run(
            ['/usr/bin/systemctl', 'is-active', 'intranet.service'],
            capture_output=True, text=True, timeout=TIMEOUT
        )
        return out.stdout.strip() == 'active'
    except Exception:
        return False


def check_http():
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        # nginx route sur server_name (ilvmintra1 / 192.168.1.25) : sans le
        # bon en-tête Host, la requête tombe hors du bloc server /intranet et
        # renvoie un faux 404, quel que soit l'état réel de l'application.
        r = requests.get(HEALTH_URL, timeout=TIMEOUT, verify=False, headers={'Host': 'ilvmintra1'})
        return r.status_code == 200 and r.json().get('status') == 'ok'
    except Exception:
        return False


def read_last_state():
    try:
        with open(STATE_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return 'up'  # au premier lancement, on suppose que tout va bien


def write_state(state):
    with open(STATE_FILE, 'w') as f:
        f.write(state)


def send_alert(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = Config.MAIL_DEFAULT_SENDER
    msg['To'] = ', '.join(RECIPIENTS)
    with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT, timeout=10) as s:
        s.sendmail(Config.MAIL_DEFAULT_SENDER, RECIPIENTS, msg.as_string())


def main():
    now = datetime.now().strftime('%F %T')
    service_ok = check_service()
    http_ok = check_http()
    current_state = 'up' if (service_ok and http_ok) else 'down'
    last_state = read_last_state()

    print(f"[{now}] service={'OK' if service_ok else 'KO'} http={'OK' if http_ok else 'KO'} -> {current_state}")

    if current_state == last_state:
        return  # pas de changement, pas d'email

    if current_state == 'down':
        detail = []
        if not service_ok:
            detail.append("- Le service systemd intranet.service n'est PAS actif.")
        if not http_ok:
            detail.append(f"- L'endpoint {HEALTH_URL} ne répond pas correctement.")
        send_alert(
            "🔴 ALERTE : Intranet ILVM indisponible",
            "L'intranet ILVM semble indisponible depuis la dernière vérification "
            f"({now}).\n\n" + "\n".join(detail) +
            "\n\nVérifier : systemctl status intranet.service, journalctl -u intranet.service -n 50"
        )
        print(f"[{now}] Alerte de panne envoyée.")
    else:
        send_alert(
            "🟢 Intranet ILVM de nouveau disponible",
            f"L'intranet ILVM répond de nouveau normalement depuis {now}."
        )
        print(f"[{now}] Alerte de rétablissement envoyée.")

    write_state(current_state)


if __name__ == '__main__':
    main()
