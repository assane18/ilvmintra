"""Lot 5 — Délais et pilotage : logique pure, testable sans requête HTTP.

Quatre volets :
  1. Paramètres applicatifs (table app_settings, modèle AppSetting) avec
     valeurs par défaut — get_setting / set_setting.
  2. Escalade automatique des validations en souffrance
     (scripts/escalade_validations.py) : niveau « rappel » aux validateurs
     éligibles après N1 jours, niveau « directeur » (mention « escaladé ») aux
     Directeurs des mêmes services + copie des managers après N2 jours.
     Anti-doublon : une trace EscalationTrace par (demande, niveau, jour).
  3. Bandeau d'état du portail : traduction « grand public » de
     app/health.py::get_full_health(), mise en cache 60 s par processus.
  4. Vérification de la sauvegarde (scripts/verif_sauvegarde.py) : fichiers
     locaux récents et non vides, copie sur le partage réseau, espace libre.
"""
import os
import glob
import shutil
from collections import defaultdict
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
#  1. Paramètres applicatifs
# ---------------------------------------------------------------------------

SETTING_DEFAULTS = {
    'escalade_rappel_jours': '3',      # rappel aux validateurs après N1 jours d'attente
    'escalade_directeur_jours': '5',   # escalade aux Directeurs après N2 jours d'attente
    'sauvegarde_espace_min_go': '5',   # espace libre minimal (Go) sur le partage de sauvegarde
    'bandeau_etat_masque': '0',        # '1' = l'admin masque le bandeau d'état du portail
}

SETTING_LABELS = {
    'escalade_rappel_jours': "Rappel aux validateurs après (jours d'attente)",
    'escalade_directeur_jours': "Escalade aux Directeurs après (jours d'attente)",
    'sauvegarde_espace_min_go': "Espace libre minimal sur le partage de sauvegarde (Go)",
    'bandeau_etat_masque': "Masquer le bandeau d'état du portail",
}


def get_setting(key, default=None):
    """Valeur texte du paramètre, ou sa valeur par défaut (SETTING_DEFAULTS puis `default`)."""
    from app.models import AppSetting
    row = AppSetting.query.get(key)
    if row is not None and row.value is not None and row.value != '':
        return row.value
    return SETTING_DEFAULTS.get(key, default)


def get_setting_int(key, default=None):
    """Valeur entière ; retombe sur la valeur par défaut si la saisie est invalide."""
    raw = get_setting(key, default)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return int(SETTING_DEFAULTS.get(key, default or 0))


def get_setting_float(key, default=None):
    raw = get_setting(key, default)
    try:
        return float(str(raw).strip().replace(',', '.'))
    except (TypeError, ValueError):
        return float(SETTING_DEFAULTS.get(key, default or 0))


def set_setting(key, value, commit=True):
    from app import db
    from app.models import AppSetting
    row = AppSetting.query.get(key)
    if row is None:
        row = AppSetting(key=key)
        db.session.add(row)
    row.value = None if value is None else str(value)
    if commit:
        db.session.commit()
    return row


def all_settings():
    """Toutes les clés connues avec leur valeur effective (défaut si non saisie)."""
    return {k: get_setting(k) for k in SETTING_DEFAULTS}


# ---------------------------------------------------------------------------
#  2. Escalade des validations en souffrance
# ---------------------------------------------------------------------------

LEVEL_RAPPEL = 'rappel'
LEVEL_DIRECTEUR = 'directeur'


def escalation_level(created_at, now, rappel_jours, directeur_jours):
    """Niveau d'escalade d'une demande en attente depuis `created_at` :
    None (sous le seuil), 'rappel' (> N1 jours) ou 'directeur' (> N2 jours).
    Un seuil à 0 ou None désactive le niveau correspondant."""
    if not created_at:
        return None
    age_days = (now - created_at).total_seconds() / 86400.0
    if directeur_jours and age_days > directeur_jours:
        return LEVEL_DIRECTEUR
    if rappel_jours and age_days > rappel_jours:
        return LEVEL_RAPPEL
    return None


def plan_escalations(items, now, rappel_jours, directeur_jours, already_sent=()):
    """Logique pure : pour chaque élément (dict avec au moins 'key' et
    'created_at'), décide du niveau à envoyer aujourd'hui.

    `already_sent` : ensemble de (key, level) déjà envoyés le jour même
    (anti-doublon). Renvoie la liste des (item, level) à traiter."""
    already = set(already_sent or ())
    planned = []
    for item in items:
        level = escalation_level(item['created_at'], now, rappel_jours, directeur_jours)
        if level is None or (item['key'], level) in already:
            continue
        planned.append((item, level))
    return planned


def _user_services(user):
    """Services d'origine + services gérés d'un utilisateur (valeurs ServiceType),
    avec la normalisation 'GS-DRH' -> 'DRH' déjà utilisée ailleurs."""
    svcs = set(user.get_origin_services() or [])
    for s in (user.get_allowed_services() or []):
        svcs.add('DRH' if s == 'GS-DRH' else s)
    return svcs


def item_services(obj):
    """Services « concernés » par une demande en attente — ceux dont les
    Directeurs doivent être alertés au niveau 2. Ticket en validation
    hiérarchique : service du demandeur ; sinon service destinataire.
    Soumission : service émetteur (EMITTER) ou service validateur (FIXED)."""
    from app.models import Ticket, TicketStatus, ServiceSource
    if isinstance(obj, Ticket):
        if obj.status == TicketStatus.VALIDATION_N1:
            return {obj.service_demandeur} if obj.service_demandeur else set()
        v = obj.target_service.value if hasattr(obj.target_service, 'value') else str(obj.target_service)
        return {v} if v else set()
    step = getattr(obj, 'current_step', None)
    if step is None:
        return set()
    if step.service_source == ServiceSource.EMITTER:
        return set(obj.author.get_origin_services()) if obj.author else set()
    if step.validator_service:
        return {step.validator_service.value}
    return set()


def directors_for(services, all_directors, eligible_validators):
    """Directeurs à alerter au niveau 2 : ceux déjà éligibles à valider la
    demande, plus tout Directeur dont les services recoupent `services`."""
    from app.models import UserRole
    chosen = {u.id: u for u in eligible_validators if u.role == UserRole.DIRECTEUR}
    if services:
        for d in all_directors:
            if _user_services(d) & set(services):
                chosen[d.id] = d
    return list(chosen.values())


def describe_item(obj, base_url=''):
    """Représentation homogène ticket / soumission pour les e-mails et la trace."""
    from app.models import Ticket
    base_url = (base_url or '').rstrip('/')
    if isinstance(obj, Ticket):
        return {
            'key': ('ticket', obj.id),
            'ref': obj.uid_public,
            'title': obj.title,
            'author': obj.author.fullname if obj.author else '',
            'created_at': obj.created_at,
            'url': f"{base_url}/tickets/view/{obj.uid_public}",
            'kind': 'Ticket',
        }
    return {
        'key': ('submission', obj.id),
        'ref': obj.uid_public,
        'title': obj.form.name if obj.form else 'Formulaire',
        'author': obj.author.fullname if obj.author else '',
        'created_at': obj.created_at,
        'url': f"{base_url}/forms/submission/{obj.id}",
        'kind': 'Formulaire',
    }


def collect_pending_items(base_url=''):
    """Toutes les demandes en attente de validation, chacune avec ses
    validateurs éligibles (réutilise digests.pending_validations_for pour
    chaque Manager/Directeur — même éligibilité que le tableau manager) et
    les Directeurs à alerter en cas d'escalade."""
    from app.models import User, UserRole
    from app.digests import pending_validations_for, weekly_digest_recipients

    objects, validators = {}, defaultdict(list)
    for user in weekly_digest_recipients():
        tickets, subs = pending_validations_for(user)
        for obj in list(tickets) + list(subs):
            d = describe_item(obj, base_url)
            objects.setdefault(d['key'], (obj, d))
            validators[d['key']].append(user)

    all_directors = User.query.filter(User.role == UserRole.DIRECTEUR, User.email.isnot(None)).all()
    items = []
    for key, (obj, d) in objects.items():
        d = dict(d)
        d['validators'] = validators[key]
        d['managers'] = [u for u in validators[key] if u.role == UserRole.MANAGER]
        d['directors'] = directors_for(item_services(obj), all_directors, validators[key])
        items.append(d)
    return items


def already_sent_today(day):
    from app.models import EscalationTrace
    return {((t.item_type, t.item_id), t.level)
            for t in EscalationTrace.query.filter(EscalationTrace.sent_on == day).all()}


def recipients_for(item, level):
    """E-mails destinataires selon le niveau : rappel -> validateurs éligibles ;
    directeur -> Directeurs concernés + copie des managers éligibles."""
    if level == LEVEL_DIRECTEUR:
        users = list(item.get('directors') or []) + list(item.get('managers') or [])
    else:
        users = list(item.get('validators') or [])
    seen, emails = set(), []
    for u in users:
        e = (u.email or '').strip()
        if e and e.lower() not in seen:
            seen.add(e.lower()); emails.append(e)
    return emails


def _age_label(created_at, now):
    d = (now - created_at).days
    return f"{d} j" if d else "aujourd'hui"


def _rows_html(items, now):
    return "".join(f"""
        <tr>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;"><a href="{i['url']}">{i['ref']}</a></td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;">{i['kind']} — {i['title']}</td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0;">{i['author']}</td>
            <td style="padding:6px; border-bottom:1px solid #e2e8f0; text-align:center; white-space:nowrap;">{_age_label(i['created_at'], now)}</td>
        </tr>""" for i in items)


def send_escalation_email(email, rappel_items, directeur_items, now, rappel_jours, directeur_jours, base_url=''):
    """UN e-mail par destinataire regroupant ses demandes en rappel et/ou escaladées."""
    from app.emails import send_email, get_outlook_friendly_html
    base_url = (base_url or '').rstrip('/')
    head = """<tr style="background-color:#f7fafc;"><th style="padding:6px; text-align:left;">Réf.</th><th style="padding:6px; text-align:left;">Objet</th><th style="padding:6px; text-align:left;">Demandeur</th><th style="padding:6px; text-align:center;">Attente</th></tr>"""
    sections = ""
    if directeur_items:
        sections += f"""
        <h3 style="margin:18px 0 6px; color:#b91c1c;">🔴 Escaladé — en attente depuis plus de {directeur_jours} jours ({len(directeur_items)})</h3>
        <p style="font-size:12px; color:#718096; margin:0 0 6px;">Ces demandes n'ont toujours pas été validées malgré le rappel : elles sont escaladées à la direction du service, le manager étant en copie.</p>
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;">{head}{_rows_html(directeur_items, now)}</table>"""
    if rappel_items:
        sections += f"""
        <h3 style="margin:18px 0 6px; color:#b45309;">⏳ Rappel — en attente de votre validation depuis plus de {rappel_jours} jours ({len(rappel_items)})</h3>
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;">{head}{_rows_html(rappel_items, now)}</table>"""
    html_content = f"""
    <p>Bonjour,</p>
    <p>Des demandes attendent une validation depuis trop longtemps :</p>
    {sections}
    <p style="font-size:12px; color:#718096; margin-top:18px;">Message automatique quotidien (seuils réglables par l'administrateur dans Pilotage). Il ne sera pas renvoyé aujourd'hui pour ces demandes.</p>
    """
    full_html = get_outlook_friendly_html("Validations en attente", html_content, f"{base_url}/tickets/manager", "Ouvrir mes validations")
    if directeur_items:
        subject = f"[Intranet] Escaladé : {len(directeur_items)} demande(s) en attente de validation depuis plus de {directeur_jours} jours"
    else:
        subject = f"[Intranet] Rappel : {len(rappel_items)} demande(s) attendent votre validation"
    text = f"{len(directeur_items)} escaladée(s), {len(rappel_items)} rappel(s)."
    send_email(subject, [email], text, full_html, kind='digest')


def run_escalations(now=None, dry_run=False, base_url=None):
    """Point d'entrée du script quotidien. Renvoie un bilan
    {'rappel': n, 'directeur': n, 'emails': n, 'sans_destinataire': n, 'details': [...]}."""
    from flask import current_app
    from app import db
    from app.models import EscalationTrace

    now = now or datetime.now()
    base_url = base_url if base_url is not None else current_app.config.get('BASE_URL', '')
    rappel_jours = get_setting_int('escalade_rappel_jours')
    directeur_jours = get_setting_int('escalade_directeur_jours')

    items = collect_pending_items(base_url)
    planned = plan_escalations(items, now, rappel_jours, directeur_jours, already_sent_today(now.date()))

    per_recipient = defaultdict(lambda: {LEVEL_RAPPEL: [], LEVEL_DIRECTEUR: []})
    summary = {LEVEL_RAPPEL: 0, LEVEL_DIRECTEUR: 0, 'emails': 0, 'sans_destinataire': 0, 'details': []}
    traces = []
    for item, level in planned:
        emails = recipients_for(item, level)
        if not emails:
            summary['sans_destinataire'] += 1
            summary['details'].append((item['ref'], level, []))
            continue
        for e in emails:
            per_recipient[e][level].append(item)
        summary[level] += 1
        summary['details'].append((item['ref'], level, emails))
        traces.append(EscalationTrace(item_type=item['key'][0], item_id=item['key'][1], level=level,
                                      sent_on=now.date(), recipients=', '.join(emails)))

    if not dry_run:
        for email, groups in per_recipient.items():
            send_escalation_email(email, groups[LEVEL_RAPPEL], groups[LEVEL_DIRECTEUR], now,
                                  rappel_jours, directeur_jours, base_url)
        for t in traces:
            db.session.add(t)
        db.session.commit()
    summary['emails'] = len(per_recipient)
    return summary


# ---------------------------------------------------------------------------
#  3. Bandeau d'état du portail
# ---------------------------------------------------------------------------

HEALTH_CACHE_TTL = 60  # secondes
_HEALTH_CACHE = {'at': None, 'notices': []}

DISK_FULL_PERCENT = 90


def health_notices_from(health):
    """Traduit le dict de get_full_health() en messages compréhensibles par un
    non-technicien (sans aucun détail technique). Liste vide = tout va bien."""
    if not health:
        return []
    notices = []
    if not (health.get('db') or {}).get('ok', True):
        notices.append("La base de données de l'intranet répond mal : certaines pages peuvent être lentes ou indisponibles.")
    if not (health.get('ldap') or {}).get('ok', True):
        notices.append("L'annuaire des comptes est momentanément injoignable : la connexion à l'intranet peut échouer pour les personnes qui ne sont pas encore connectées.")
    if not (health.get('mail') or {}).get('ok', True):
        notices.append("La messagerie est perturbée, les notifications par e-mail peuvent être retardées.")
    backup = health.get('backup') or {}
    share = health.get('backup_share') or {}
    if backup.get('stale') or share.get('mounted') is False:
        notices.append("La sauvegarde automatique de l'intranet rencontre un problème ; le service informatique en est informé.")
    disk = health.get('disk') or {}
    if (disk.get('percent_used') or 0) >= DISK_FULL_PERCENT:
        notices.append("L'espace de stockage de l'intranet est presque plein : l'ajout de pièces jointes peut échouer.")
    return notices


def reset_health_cache():
    _HEALTH_CACHE['at'] = None
    _HEALTH_CACHE['notices'] = []


def cached_health_notices(now=None, health_fn=None, ttl=HEALTH_CACHE_TTL):
    """Messages d'état, recalculés au plus une fois par `ttl` secondes et par
    processus (les vérifications réseau de health.py ne doivent pas être
    refaites à chaque affichage du portail)."""
    now = now or datetime.now()
    at = _HEALTH_CACHE['at']
    if at is not None and (now - at).total_seconds() < ttl:
        return list(_HEALTH_CACHE['notices'])
    if health_fn is None:
        from app.health import get_full_health
        health_fn = get_full_health
    try:
        notices = health_notices_from(health_fn())
    except Exception:
        notices = []
    _HEALTH_CACHE['at'] = now
    _HEALTH_CACHE['notices'] = list(notices)
    return notices


def portal_health_notice(now=None, health_fn=None, ttl=HEALTH_CACHE_TTL):
    """Ce que le portail affiche : None si tout va bien ou si l'admin a masqué
    le bandeau ; sinon {'messages': [...], 'checked_at': datetime}.
    Ne lève jamais : le portail ne doit pas tomber à cause du bandeau."""
    try:
        if get_setting('bandeau_etat_masque') == '1':
            return None
        messages = cached_health_notices(now, health_fn, ttl)
    except Exception:
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass
        return None
    if not messages:
        return None
    return {'messages': messages, 'checked_at': _HEALTH_CACHE['at']}


# ---------------------------------------------------------------------------
#  4. Vérification de la sauvegarde
# ---------------------------------------------------------------------------

BACKUP_PATTERNS = {
    'base de données': 'intranet_db_*.sql.gz',
    'fichiers joints': 'uploads_*.tar.gz',
}
BACKUP_MAX_AGE_HOURS = 26


def _latest(directory, pattern):
    files = glob.glob(os.path.join(directory, pattern)) if directory else []
    return max(files, key=os.path.getmtime) if files else None


def check_backup_state(local_dir, remote_dir, mount_point, now=None,
                       max_age_hours=BACKUP_MAX_AGE_HOURS, min_free_gb=5.0,
                       is_mounted=None, free_gb=None):
    """Logique pure : renvoie (anomalies, details).

    - `is_mounted` / `free_gb` : valeurs injectables pour les tests ; sinon
      os.path.ismount(mount_point) et shutil.disk_usage(remote_dir).
    - anomalies : liste de phrases en français, vide si tout va bien."""
    now = now or datetime.now()
    anomalies, details = [], {'local': {}, 'remote': {}, 'mounted': None, 'free_gb': None}

    latest_names = {}
    for label, pattern in BACKUP_PATTERNS.items():
        path = _latest(local_dir, pattern)
        if not path:
            anomalies.append(f"Aucune sauvegarde locale de la {label} ({pattern}) dans {local_dir}.")
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        age_h = (now - mtime).total_seconds() / 3600.0
        size = os.path.getsize(path)
        details['local'][label] = {'path': path, 'age_hours': round(age_h, 1), 'size': size}
        if age_h > max_age_hours:
            anomalies.append(f"La dernière sauvegarde locale de la {label} date de {age_h:.0f} h ({os.path.basename(path)}), seuil {max_age_hours} h.")
        if size <= 0:
            anomalies.append(f"La dernière sauvegarde locale de la {label} est vide ({os.path.basename(path)}).")
        latest_names[label] = os.path.basename(path)

    mounted = is_mounted if is_mounted is not None else os.path.ismount(mount_point)
    details['mounted'] = mounted
    if not mounted:
        anomalies.append(f"Le partage de sauvegarde {mount_point} n'est pas monté : aucune copie hors de la VM.")
    else:
        for label, name in latest_names.items():
            remote_path = os.path.join(remote_dir, name)
            if not os.path.exists(remote_path):
                anomalies.append(f"La copie distante de la {label} ({name}) est absente de {remote_dir}.")
            elif os.path.getsize(remote_path) <= 0:
                anomalies.append(f"La copie distante de la {label} ({name}) est vide.")
            else:
                details['remote'][label] = remote_path
        if free_gb is None:
            try:
                free_gb = shutil.disk_usage(remote_dir if os.path.isdir(remote_dir) else mount_point).free / (1024 ** 3)
            except OSError:
                free_gb = None
        details['free_gb'] = None if free_gb is None else round(free_gb, 1)
        if free_gb is None:
            anomalies.append(f"Impossible de mesurer l'espace libre du partage {mount_point}.")
        elif free_gb < min_free_gb:
            anomalies.append(f"Espace libre sur le partage de sauvegarde : {free_gb:.1f} Go, sous le seuil de {min_free_gb:g} Go.")
    return anomalies, details


def admin_emails():
    from app.models import User, UserRole
    return sorted({(u.email or '').strip() for u in User.query.filter(User.role == UserRole.ADMIN).all()
                   if u.email and u.email.strip()})


def send_backup_alert(anomalies, details, recipients, now=None):
    """UN e-mail groupé aux administrateurs (kind='digest' : jamais filtré par
    les préférences e-mail)."""
    from app.emails import send_email, get_outlook_friendly_html
    now = now or datetime.now()
    rows = "".join(f'<li style="margin:4px 0;">{a}</li>' for a in anomalies)
    html_content = f"""
    <p>Bonjour,</p>
    <p>La vérification quotidienne de la sauvegarde de l'intranet ({now.strftime('%d/%m/%Y %H:%M')}) a relevé
    <strong>{len(anomalies)} anomalie(s)</strong> :</p>
    <ul style="background-color:#fff5f5; border-left:4px solid #e53e3e; padding:10px 10px 10px 28px; margin:12px 0;">{rows}</ul>
    <p style="font-size:12px; color:#718096;">Partage monté : {'oui' if details.get('mounted') else 'non'} ·
    espace libre : {details.get('free_gb') if details.get('free_gb') is not None else '?'} Go ·
    à vérifier : scripts/backup.sh, backups/backup.log, montage /mnt/ilvmfap1_info.</p>
    """
    full_html = get_outlook_friendly_html("Alerte sauvegarde", html_content)
    send_email(f"[Intranet] Sauvegarde : {len(anomalies)} anomalie(s) détectée(s)", recipients,
               "\n".join(anomalies), full_html, kind='digest')
