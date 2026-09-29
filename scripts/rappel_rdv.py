#!/var/www/intranet/venv/bin/python3
"""Rappel des rendez-vous du jour (tickets) aux deux parties — demandeur et
équipe (personne ayant proposé + technicien en charge) — par e-mail et
notification in-app. Un seul rappel par rendez-vous (Appointment.reminder_sent_at).

Usage cron (chaque jour à 9h) :
  0 9 * * * /var/www/intranet/scripts/rappel_rdv.py >> /var/www/intranet/backups/rappel_rdv.log 2>&1
"""
import sys
from datetime import datetime

sys.path.insert(0, '/var/www/intranet')

from app import create_app  # noqa: E402
from app.routes.rdv import send_reminders  # noqa: E402


def main():
    app = create_app('production')
    with app.app_context():
        n = send_reminders(datetime.now())
        print(f"[{datetime.now():%F %T}] {n} rappel(s) de rendez-vous envoyé(s).")


if __name__ == '__main__':
    main()
