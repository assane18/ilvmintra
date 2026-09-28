#!/var/www/intranet/venv/bin/python3
"""Résumé quotidien par e-mail pour les utilisateurs qui ont choisi le mode
« un résumé par jour » dans leur profil (User.email_mode == 'daily') : leurs
e-mails immédiats sont retenus par app/emails.py::send_email, ce script leur
envoie à la place la liste des notifications in-app des dernières 24 h.

Usage cron (une fois par jour, ex. 8h05) :
  5 8 * * * /var/www/intranet/scripts/resume_quotidien.py >> /var/www/intranet/backups/resume_quotidien.log 2>&1
"""
import sys

sys.path.insert(0, '/var/www/intranet')

from app import create_app  # noqa: E402
from app.digests import daily_digest_recipients, daily_digest_for  # noqa: E402
from app.emails import send_daily_digest  # noqa: E402


def main():
    app = create_app('production')
    with app.app_context():
        sent = 0
        for user in daily_digest_recipients():
            notifs = daily_digest_for(user)
            if not notifs:
                continue
            send_daily_digest(user, notifs)
            sent += 1
            print(f"Résumé envoyé à {user.username} ({len(notifs)} événement(s)).")
        print(f"Terminé : {sent} résumé(s) envoyé(s).")


if __name__ == '__main__':
    main()
