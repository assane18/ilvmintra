#!/var/www/intranet/venv/bin/python3
"""Escalade automatique des validations en souffrance (Lot 5).

Pour chaque ticket / soumission de formulaire en attente de validation :
  - depuis plus de N1 jours (AppSetting escalade_rappel_jours, défaut 3) :
    e-mail de rappel aux validateurs éligibles (même éligibilité que le
    tableau manager, via app/digests.py::pending_validations_for) ;
  - depuis plus de N2 jours (AppSetting escalade_directeur_jours, défaut 5) :
    e-mail « escaladé » aux DIRECTEUR des services concernés, managers
    éligibles en copie.
Un e-mail par destinataire (regroupant ses demandes), kind='digest' (jamais
filtré par les préférences e-mail). Anti-doublon : table escalation_traces,
un même niveau n'est pas renvoyé le même jour pour la même demande.
Seuils modifiables sur /admin/pilotage. Logique : app/pilotage.py.

Usage cron (tous les jours à 8h10) — NON installé, à ajouter manuellement :
  10 8 * * * /var/www/intranet/scripts/escalade_validations.py >> /var/www/intranet/backups/escalade_validations.log 2>&1

Options : --dry-run (affiche ce qui serait envoyé, sans e-mail ni trace).
"""
import sys
from datetime import datetime

sys.path.insert(0, '/var/www/intranet')

from app import create_app  # noqa: E402
from app.pilotage import run_escalations  # noqa: E402


def main():
    dry_run = '--dry-run' in sys.argv
    app = create_app('production')
    with app.app_context():
        now = datetime.now()
        summary = run_escalations(now=now, dry_run=dry_run)
        stamp = now.strftime('%F %T')
        for ref, level, emails in summary['details']:
            print(f"[{stamp}] {ref} -> {level} -> {', '.join(emails) if emails else 'AUCUN DESTINATAIRE'}")
        print(f"[{stamp}] Terminé{' (simulation)' if dry_run else ''} : {summary['rappel']} rappel(s), "
              f"{summary['directeur']} escaladée(s), {summary['emails']} e-mail(s), "
              f"{summary['sans_destinataire']} sans destinataire.")


if __name__ == '__main__':
    main()
