#!/var/www/intranet/venv/bin/python3
"""Récap hebdomadaire e-mail pour chaque Manager / Directeur : demandes en
attente de SA validation (tickets + formulaires, avec ancienneté), tickets en
retard sur ses services, volume reçu dans la semaine. Envoyé uniquement s'il
y a quelque chose à traiter (voir app/digests.py::weekly_manager_summary).

Usage cron (lundi 8h) :
  0 8 * * 1 /var/www/intranet/scripts/recap_hebdo_managers.py >> /var/www/intranet/backups/recap_hebdo.log 2>&1
"""
import sys

sys.path.insert(0, '/var/www/intranet')

from app import create_app  # noqa: E402
from app.digests import weekly_digest_recipients, weekly_manager_summary  # noqa: E402
from app.emails import send_weekly_manager_digest  # noqa: E402


def main():
    app = create_app('production')
    with app.app_context():
        sent = 0
        for user in weekly_digest_recipients():
            data = weekly_manager_summary(user)
            if not data:
                continue
            send_weekly_manager_digest(user, data)
            sent += 1
            print(f"Récap envoyé à {user.username} : {len(data['pending_tickets']) + len(data['pending_submissions'])} à valider, "
                  f"{len(data['stale'])} en retard, {len(data['received_week'])} reçu(s) cette semaine.")
        print(f"Terminé : {sent} récap(s) envoyé(s).")


if __name__ == '__main__':
    main()
