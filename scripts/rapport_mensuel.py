#!/var/www/intranet/venv/bin/python3
"""Rapport mensuel d'activité PDF (lot 8) : génère le rapport du MOIS PRÉCÉDENT
dans /var/www/intranet/backups/rapports/rapport_AAAA-MM.pdf, l'envoie par
e-mail (pièce jointe, kind='digest') aux comptes DIRECTEUR et ADMIN, et le
copie sur le partage /mnt/ilvmfap1_info/Backups_Intranet/Rapports/ s'il est
monté. Même calcul que la page Statistiques (tickets._compute_stats).

Usage cron (le 1er du mois à 6h) — À INSTALLER MANUELLEMENT, non installé :
  0 6 1 * * /var/www/intranet/scripts/rapport_mensuel.py >> /var/www/intranet/backups/rapport_mensuel.log 2>&1

Options :
  --month AAAA-MM   mois à traiter (défaut : mois précédent)
  --no-mail         ne pas envoyer l'e-mail
  --no-share        ne pas copier sur le partage réseau
"""
import argparse
import sys
from datetime import datetime

sys.path.insert(0, '/var/www/intranet')

from app import create_app  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Rapport mensuel d'activité (PDF)")
    parser.add_argument('--month', help='AAAA-MM (défaut : mois précédent)')
    parser.add_argument('--no-mail', action='store_true')
    parser.add_argument('--no-share', action='store_true')
    args = parser.parse_args()

    app = create_app('production')
    with app.app_context():
        from app import reporting
        from app.audit import log_action
        if args.month:
            year, month = (int(x) for x in args.month.split('-'))
        else:
            year, month = reporting.previous_month()
        label = f"{reporting.MONTHS_FR[month]} {year}"
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Génération du rapport {label}…")
        path, pdf, shared = reporting.generate_and_store(year, month, copy_to_share=not args.no_share)
        print(f"  PDF : {path} ({len(pdf)} octets)")
        print(f"  Partage : {shared or 'non copié (partage absent ou --no-share)'}")
        recipients = []
        if not args.no_mail:
            recipients = reporting.send_monthly_report(year, month, pdf)
            print(f"  E-mail : {len(recipients)} destinataire(s) DIRECTEUR/ADMIN")
        log_action('report.generate', ('Rapport', None, f"{year:04d}-{month:02d}"),
                   details=f"cron ; {len(pdf)} octets ; {len(recipients)} destinataire(s)"
                           + (' ; copié sur le partage' if shared else ''), commit=True)
        print("Terminé.")


if __name__ == '__main__':
    main()
