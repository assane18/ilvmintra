#!/var/www/intranet/venv/bin/python3
"""Vérification quotidienne de la sauvegarde de l'intranet (Lot 5).

Contrôle, après le passage de scripts/backup.sh :
  - que les dernières intranet_db_*.sql.gz et uploads_*.tar.gz locales datent
    de moins de 26 h et ne sont pas vides ;
  - que le partage /mnt/ilvmfap1_info est monté et que les mêmes fichiers y
    sont présents (Backups_Intranet) ;
  - que l'espace libre du partage dépasse le seuil AppSetting
    sauvegarde_espace_min_go (défaut 5 Go, réglable sur /admin/pilotage).
En cas d'anomalie : UN e-mail groupé aux comptes ADMIN de la base
(kind='digest') + une ligne par anomalie dans le journal (stdout, redirigé par
cron). Aucun e-mail si tout va bien. Logique pure : app/pilotage.py::check_backup_state.

Usage cron (tous les jours à 7h) — NON installé, à ajouter manuellement :
  0 7 * * * /var/www/intranet/scripts/verif_sauvegarde.py >> /var/www/intranet/backups/verif_sauvegarde.log 2>&1
"""
import sys
from datetime import datetime

sys.path.insert(0, '/var/www/intranet')

from app import create_app  # noqa: E402
from app.pilotage import (check_backup_state, admin_emails, send_backup_alert,  # noqa: E402
                          get_setting_float, BACKUP_MAX_AGE_HOURS)

LOCAL_BACKUP_DIR = '/var/www/intranet/backups'
MOUNT_POINT = '/mnt/ilvmfap1_info'
REMOTE_BACKUP_DIR = '/mnt/ilvmfap1_info/Backups_Intranet'


def main():
    app = create_app('production')
    with app.app_context():
        now = datetime.now()
        stamp = now.strftime('%F %T')
        min_free_gb = get_setting_float('sauvegarde_espace_min_go')
        anomalies, details = check_backup_state(LOCAL_BACKUP_DIR, REMOTE_BACKUP_DIR, MOUNT_POINT, now=now,
                                                max_age_hours=BACKUP_MAX_AGE_HOURS, min_free_gb=min_free_gb)
        if not anomalies:
            print(f"[{stamp}] OK — sauvegardes à jour, copie distante présente, "
                  f"{details.get('free_gb')} Go libres sur le partage.")
            return
        for a in anomalies:
            print(f"[{stamp}] ANOMALIE : {a}")
        recipients = admin_emails()
        if recipients:
            send_backup_alert(anomalies, details, recipients, now=now)
            print(f"[{stamp}] Alerte envoyée à {', '.join(recipients)}.")
        else:
            print(f"[{stamp}] Aucun ADMIN avec e-mail en base : alerte non envoyée.")
        sys.exit(1)


if __name__ == '__main__':
    main()
