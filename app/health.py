"""Vérifications de santé du système, partagées entre le endpoint public
/health (liveness, sans authentification), le tableau de bord /admin/health
(détaillé, réservé ADMIN) et le script externe scripts/watchdog.sh (qui ne
passe pas par Flask, mais réutilise les mêmes seuils pour rester cohérent)."""
import os
import glob
import shutil
import socket
import subprocess
from datetime import datetime
from urllib.parse import urlparse

from flask import current_app
from sqlalchemy import text

from app import db

BACKUP_DIR = '/var/www/intranet/backups'
BACKUP_STALE_HOURS = 36  # sauvegarde attendue chaque nuit -> alerte si absente 1,5 jour
BACKUP_SHARE_MOUNT = '/mnt/ilvmfap1_info'  # partage réseau recevant la copie distante (scripts/backup.sh)


def check_db():
    try:
        db.session.execute(text('SELECT 1'))
        return True, None
    except Exception as e:
        return False, str(e)


def check_ldap():
    ldap_url = current_app.config.get('LDAP_SERVER', 'ldap://192.168.1.9')
    parsed = urlparse(ldap_url)
    host = parsed.hostname or ldap_url.replace('ldap://', '').split(':')[0]
    port = parsed.port or 389
    try:
        with socket.create_connection((host, port), timeout=3):
            return True, None
    except Exception as e:
        return False, str(e)


def check_mail():
    """Le serveur de messagerie (MAIL_SERVER:MAIL_PORT) accepte-t-il une
    connexion TCP ? Suffisant pour détecter une messagerie KO sans envoyer."""
    host = current_app.config.get('MAIL_SERVER')
    port = int(current_app.config.get('MAIL_PORT') or 25)
    if not host:
        return True, None  # pas de messagerie configurée : rien à signaler
    try:
        with socket.create_connection((host, port), timeout=3):
            return True, None
    except Exception as e:
        return False, str(e)


def check_backup_share():
    """Le partage réseau de sauvegarde est-il monté ?"""
    return os.path.ismount(BACKUP_SHARE_MOUNT)


def check_disk():
    usage = shutil.disk_usage('/')
    percent_used = round(usage.used / usage.total * 100, 1)
    free_gb = round(usage.free / (1024 ** 3), 1)
    return percent_used, free_gb


def check_last_backup():
    files = glob.glob(os.path.join(BACKUP_DIR, 'intranet_db_*.sql.gz'))
    if not files:
        return None, None
    latest = max(files, key=os.path.getmtime)
    mtime = datetime.fromtimestamp(os.path.getmtime(latest))
    age_hours = round((datetime.now() - mtime).total_seconds() / 3600, 1)
    return mtime, age_hours


def check_service_uptime():
    try:
        # Chemin absolu obligatoire : le service systemd tourne avec
        # Environment="PATH=/var/www/intranet/venv/bin" (voir
        # intranet.service), qui écrase le PATH par défaut — 'systemctl' seul
        # n'est pas trouvable depuis le process gunicorn (silencieux, capturé
        # par l'except ci-dessous, d'où un faux "Problème" côté dashboard).
        out = subprocess.run(
            ['/usr/bin/systemctl', 'show', 'intranet.service', '-p', 'ActiveEnterTimestamp', '-p', 'ActiveState'],
            capture_output=True, text=True, timeout=3
        )
        info = dict(line.split('=', 1) for line in out.stdout.strip().splitlines() if '=' in line)
        return info.get('ActiveState'), info.get('ActiveEnterTimestamp')
    except Exception:
        return None, None


def get_ticket_queue_depth():
    from app.models import Ticket, TicketStatus
    return {
        'pending': Ticket.query.filter_by(status=TicketStatus.PENDING).count(),
        'validation_n1': Ticket.query.filter_by(status=TicketStatus.VALIDATION_N1).count(),
        'validation_n2': Ticket.query.filter_by(status=TicketStatus.VALIDATION_N2).count(),
    }


def get_liveness():
    """Version légère pour /health (public, non authentifié) : pas de détail
    interne (chemins, messages d'erreur bruts), juste des booléens."""
    db_ok, _ = check_db()
    return {
        'status': 'ok' if db_ok else 'degraded',
        'db': db_ok,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    }


def get_full_health():
    """Version complète pour /admin/health (réservé ADMIN)."""
    db_ok, db_err = check_db()
    ldap_ok, ldap_err = check_ldap()
    mail_ok, mail_err = check_mail()
    disk_percent, disk_free_gb = check_disk()
    backup_time, backup_age_hours = check_last_backup()
    service_state, service_since = check_service_uptime()
    queue = get_ticket_queue_depth() if db_ok else {}

    return {
        'db': {'ok': db_ok, 'error': db_err},
        'ldap': {'ok': ldap_ok, 'error': ldap_err},
        'mail': {'ok': mail_ok, 'error': mail_err},
        'backup_share': {'mounted': check_backup_share()},
        'disk': {'percent_used': disk_percent, 'free_gb': disk_free_gb},
        'backup': {
            'last_time': backup_time.isoformat() if backup_time else None,
            'age_hours': backup_age_hours,
            'stale': backup_age_hours is None or backup_age_hours > BACKUP_STALE_HOURS,
        },
        'service': {'state': service_state, 'since': service_since},
        'queue': queue,
        'generated_at': datetime.utcnow().isoformat() + 'Z',
    }
