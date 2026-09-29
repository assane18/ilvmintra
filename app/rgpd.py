"""Archivage et purge RGPD (lot 8).

Deux fonctions séparées, volontairement :
  plan_purge(now)   -> calcule et RENVOIE le plan (liste d'opérations) sans
                       rien modifier (base ni fichiers) ; c'est le « dry-run ».
  apply_purge(plan) -> exécute exactement ce plan, écrit une entrée d'audit et
                       un journal backups/rgpd_AAAA-MM-JJ.log (références
                       uniquement, jamais de données personnelles).

Règles (durées paramétrables ci-dessous, valeurs par défaut à faire valider) :
  R1  Anonymisation : tickets et soumissions de formulaire TERMINÉS ou REFUSÉS
      depuis plus de ANONYMIZE_AFTER_YEARS -> titre/description/données
      remplacés par « [Anonymisé] », messages supprimés, demandeur détaché,
      champs nominatifs (téléphone, nouvel utilisateur, fournisseur DAF…) vidés.
      Les dates, le service, la catégorie, le statut et la satisfaction sont
      conservés pour les statistiques.
  R2  Pièces jointes sensibles supprimées FILES_AFTER_YEARS après clôture :
      dossiers FCPI (CV, fiche de poste, photo), RIB des bons de commande DAF,
      fichiers des dossiers séjour, pièces des soumissions de formulaires — y
      compris leurs copies dans les dossiers des tickets enfants.
  R3  Notifications LUES de plus de NOTIF_READ_MONTHS mois supprimées.
  R4  Comptes intranet sans aucune activité depuis INACTIVE_USER_YEARS et
      absents des validations (validated_by) supprimés (jamais un ADMIN, ni
      un compte sans aucune trace datée : on ne sait pas s'il est ancien).
"""
import json
import os
from datetime import datetime

from dateutil.relativedelta import relativedelta
from flask import current_app

from app import db
from app.models import (Ticket, TicketStatus, TicketMessage, FormSubmission, FormSubmissionStatus,
                        FormSubmissionFile, Recruitment, RecruitmentStatus, DossierSejour, SejourStatus,
                        Publication, Announcement, FormDefinition, Notification, User, UserRole, AuditLog)

# --- Règles paramétrables -------------------------------------------------
ANONYMIZE_AFTER_YEARS = 3     # R1 : tickets / soumissions terminés ou refusés
FILES_AFTER_YEARS = 1         # R2 : pièces jointes sensibles après clôture
NOTIF_READ_MONTHS = 6         # R3 : notifications lues
INACTIVE_USER_YEARS = 2       # R4 : comptes sans activité
ANONYMIZED = '[Anonymisé]'
LOG_DIR = '/var/www/intranet/backups'   # surchargeable : app.config['RGPD_LOG_DIR']

RULES = [
    {'code': 'anonymize_ticket', 'label': 'Anonymisation des tickets terminés/refusés',
     'delay': f'{ANONYMIZE_AFTER_YEARS} ans après la clôture'},
    {'code': 'anonymize_submission', 'label': 'Anonymisation des formulaires terminés/refusés',
     'delay': f'{ANONYMIZE_AFTER_YEARS} ans après la clôture'},
    {'code': 'files_fcpi', 'label': 'Suppression des pièces FCPI (CV, fiche de poste, photo)',
     'delay': f'{FILES_AFTER_YEARS} an après la clôture'},
    {'code': 'files_daf_rib', 'label': 'Suppression des RIB des bons de commande DAF',
     'delay': f'{FILES_AFTER_YEARS} an après la clôture'},
    {'code': 'files_sejour', 'label': 'Suppression des fichiers des dossiers séjour',
     'delay': f'{FILES_AFTER_YEARS} an après la clôture'},
    {'code': 'files_submission', 'label': 'Suppression des pièces jointes des formulaires',
     'delay': f'{FILES_AFTER_YEARS} an après la clôture'},
    {'code': 'notifications', 'label': 'Purge des notifications lues',
     'delay': f'{NOTIF_READ_MONTHS} mois'},
    {'code': 'inactive_user', 'label': 'Suppression des comptes inactifs',
     'delay': f'{INACTIVE_USER_YEARS} ans sans activité, hors validateurs et administrateurs'},
]

TICKET_CLOSED = (TicketStatus.DONE, TicketStatus.REFUSED)
SUB_CLOSED = (FormSubmissionStatus.DONE, FormSubmissionStatus.REFUSED)


# --- Helpers --------------------------------------------------------------
def uploads_base():
    return current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, 'static', 'uploads')


def log_dir():
    return current_app.config.get('RGPD_LOG_DIR') or LOG_DIR


def _ticket_end_date(t):
    """Date de « clôture » d'un ticket : closed_at, sinon validated_at (refus),
    sinon created_at (données historiques)."""
    return t.closed_at or t.validated_at or t.created_at


def _op(rule, target_type, target_id, target_ref, detail='', files=None, **extra):
    op = {'rule': rule, 'target_type': target_type, 'target_id': target_id,
          'target_ref': target_ref, 'detail': detail, 'files': files or []}
    op.update(extra)
    return op


def _existing(paths):
    return [p for p in paths if p and os.path.isfile(p)]


def _ticket_file_copies(ticket_ids, filenames):
    """Chemins des copies de `filenames` dans les dossiers des tickets enfants."""
    if not ticket_ids or not filenames:
        return [], []
    tickets = Ticket.query.filter(Ticket.id.in_(ticket_ids)).all()
    paths = []
    for t in tickets:
        for name in filenames:
            paths.append(os.path.join(uploads_base(), 'tickets', t.uid_public or '', name))
    return _existing(paths), tickets


# --- Plan -----------------------------------------------------------------
def plan_purge(now=None):
    """Calcule le plan sans rien modifier. Retourne un dict :
    {'now', 'rules', 'operations': [...], 'counts': {rule: n}}."""
    now = now or datetime.now()
    anonymize_before = now - relativedelta(years=ANONYMIZE_AFTER_YEARS)
    files_before = now - relativedelta(years=FILES_AFTER_YEARS)
    notif_before = now - relativedelta(months=NOTIF_READ_MONTHS)
    inactive_before = now - relativedelta(years=INACTIVE_USER_YEARS)
    ops = []
    base = uploads_base()

    # R1a — tickets
    for t in Ticket.query.filter(Ticket.status.in_(TICKET_CLOSED)).all():
        end = _ticket_end_date(t)
        if not end or end > anonymize_before or t.title == ANONYMIZED:
            continue
        n_msg = TicketMessage.query.filter_by(ticket_id=t.id).count()
        ops.append(_op('anonymize_ticket', 'Ticket', t.id, t.uid_public,
                       f"clôturé le {end.strftime('%d/%m/%Y')}, {n_msg} message(s)"))

    # R1b — soumissions de formulaires
    for s in FormSubmission.query.filter(FormSubmission.status.in_(SUB_CLOSED)).all():
        end = s.updated_at or s.last_validated_at or s.created_at
        if not end or end > anonymize_before or s.data_json == json.dumps({'_': ANONYMIZED}):
            continue
        ops.append(_op('anonymize_submission', 'FormSubmission', s.id, s.uid_public,
                       f"clôturée le {end.strftime('%d/%m/%Y')}, {len(s.files)} fichier(s)"))

    # R2a — FCPI (pas de date de clôture : la date de création sert de repère)
    for r in Recruitment.query.filter(Recruitment.status.in_((RecruitmentStatus.DONE, RecruitmentStatus.REFUSED))).all():
        if not r.created_at or r.created_at > files_before:
            continue
        names = [n for n in (r.file_cv, r.file_fiche_poste, r.file_photo) if n]
        if not names:
            continue
        own = _existing([os.path.join(base, 'fcpi', r.uid_public or '', n) for n in names])
        copies, _ = _ticket_file_copies(r.get_child_tickets(), names)
        ops.append(_op('files_fcpi', 'Recruitment', r.id, r.uid_public,
                       f"{len(names)} champ(s) fichier, {len(own) + len(copies)} fichier(s) sur disque",
                       files=own + copies, filenames=names, child_ticket_ids=r.get_child_tickets()))

    # R2b — RIB DAF
    for t in Ticket.query.filter(Ticket.daf_rib_file.isnot(None), Ticket.status.in_(TICKET_CLOSED)).all():
        end = _ticket_end_date(t)
        if not end or end > files_before:
            continue
        path = os.path.join(base, 'tickets', t.uid_public or '', t.daf_rib_file)
        ops.append(_op('files_daf_rib', 'Ticket', t.id, t.uid_public, 'RIB fournisseur',
                       files=_existing([path])))

    # R2c — dossiers séjour
    for d in DossierSejour.query.filter(DossierSejour.status.in_((SejourStatus.DONE, SejourStatus.REFUSED))).all():
        if not d.created_at or d.created_at > files_before:
            continue
        names = [n for n in (d.file_dossier, d.file_dossier_signe, d.file_pv_securite, d.file_devis) if n]
        if not names:
            continue
        own = _existing([os.path.join(base, 'sejour', d.uid_public or '', n) for n in names])
        copies, _ = _ticket_file_copies(d.get_child_tickets(), names)
        ops.append(_op('files_sejour', 'DossierSejour', d.id, d.uid_public,
                       f"{len(names)} fichier(s) déclaré(s), {len(own) + len(copies)} sur disque",
                       files=own + copies, filenames=names, child_ticket_ids=d.get_child_tickets()))

    # R2d — pièces des soumissions
    for s in FormSubmission.query.filter(FormSubmission.status.in_(SUB_CLOSED)).all():
        end = s.updated_at or s.last_validated_at or s.created_at
        if not end or end > files_before or not s.files:
            continue
        slug = s.form.slug if s.form else ''
        names = [f.stored_filename for f in s.files]
        own = _existing([os.path.join(base, 'forms', slug, s.uid_public or '', n) for n in names])
        copies, _ = _ticket_file_copies(s.get_ticket_ids(), names)
        ops.append(_op('files_submission', 'FormSubmission', s.id, s.uid_public,
                       f"{len(names)} pièce(s), {len(own) + len(copies)} fichier(s) sur disque",
                       files=own + copies, filenames=names, child_ticket_ids=s.get_ticket_ids()))

    # R3 — notifications lues
    n_notif = Notification.query.filter(Notification.is_read.is_(True), Notification.timestamp < notif_before).count()
    if n_notif:
        ops.append(_op('notifications', 'Notification', None, f"{n_notif} notification(s)",
                       f"lues avant le {notif_before.strftime('%d/%m/%Y')}", count=n_notif, before=notif_before))

    # R4 — comptes inactifs
    for u in _inactive_users(inactive_before):
        ops.append(_op('inactive_user', 'User', u['user'].id, u['user'].username,
                       f"dernière activité : {u['last'].strftime('%d/%m/%Y') if u['last'] else 'inconnue'}"))

    counts = {r['code']: 0 for r in RULES}
    for op in ops:
        counts[op['rule']] = counts.get(op['rule'], 0) + 1
    return {'now': now, 'rules': RULES, 'operations': ops, 'counts': counts}


def _last_activity(user):
    """Date de la dernière trace datée d'un utilisateur (None si aucune)."""
    dates = []
    q = lambda col, model, *filters: db.session.query(db.func.max(col)).filter(*filters).scalar()
    dates.append(q(Ticket.created_at, Ticket, Ticket.author_id == user.id))
    dates.append(q(Ticket.closed_at, Ticket, Ticket.solver_id == user.id))
    dates.append(q(Ticket.assigned_at, Ticket, Ticket.solver_id == user.id))
    dates.append(q(TicketMessage.timestamp, TicketMessage, TicketMessage.author_id == user.id))
    dates.append(q(FormSubmission.created_at, FormSubmission, FormSubmission.author_id == user.id))
    dates.append(q(Notification.timestamp, Notification, Notification.user_id == user.id))
    dates.append(q(Recruitment.created_at, Recruitment, Recruitment.author_id == user.id))
    dates.append(q(DossierSejour.created_at, DossierSejour, DossierSejour.author_id == user.id))
    dates.append(q(Publication.created_at, Publication, Publication.author_id == user.id))
    dates.append(q(AuditLog.timestamp, AuditLog, AuditLog.user_id == user.id))
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def _is_validator(user):
    if Ticket.query.filter(Ticket.validated_by_id == user.id).count():
        return True
    if FormSubmission.query.filter(FormSubmission.validated_by_id == user.id).count():
        return True
    return False


def _inactive_users(before):
    out = []
    for u in User.query.all():
        if u.role == UserRole.ADMIN:
            continue
        last = _last_activity(u)
        if last is None or last > before:
            continue  # aucune trace datée = âge inconnu -> on garde
        if _is_validator(u):
            continue
        out.append({'user': u, 'last': last})
    return out


# --- Exécution ------------------------------------------------------------
def _remove_files(paths):
    removed = []
    for p in paths:
        try:
            if os.path.isfile(p):
                os.remove(p)
                removed.append(p)
        except OSError as e:
            current_app.logger.warning(f"RGPD : suppression impossible {p} ({e})")
    return removed


def _strip_ticket_copies(child_ticket_ids, filenames):
    """Retire de daf_files_json des tickets enfants les noms supprimés."""
    if not child_ticket_ids or not filenames:
        return
    for t in Ticket.query.filter(Ticket.id.in_(child_ticket_ids)).all():
        files = t.get_daf_files()
        kept = [f for f in files if f not in filenames]
        if kept != files:
            t.daf_files_json = json.dumps(kept)


def _anonymize_ticket(t):
    t.title = ANONYMIZED
    t.description = ANONYMIZED
    t.author_id = None
    t.tel_demandeur = None
    t.hostname = None
    t.lieu_installation = None
    t.satisfaction_comment = None
    for col in ('new_user_fullname', 'new_user_service', 'new_user_acces', 'materiel_list',
                'destinataire_materiel', 'service_destinataire', 'daf_fournisseur_nom',
                'daf_fournisseur_tel', 'daf_fournisseur_fax', 'daf_fournisseur_email',
                'daf_fournisseur_tel_comment', 'daf_siret', 'daf_lignes_json', 'daf_files_json',
                'daf_rib_file', 'daf_solver_file', 'daf_signed_file'):
        setattr(t, col, None)
    TicketMessage.query.filter_by(ticket_id=t.id).delete(synchronize_session=False)
    # Le dossier de pièces jointes du ticket est supprimé avec lui
    folder = os.path.join(uploads_base(), 'tickets', t.uid_public or '')
    removed = []
    if t.uid_public and os.path.isdir(folder):
        for name in os.listdir(folder):
            removed += _remove_files([os.path.join(folder, name)])
        try:
            os.rmdir(folder)
        except OSError:
            pass
    return removed


def _anonymize_submission(s):
    s.set_data({'_': ANONYMIZED})
    s.refusal_reason = None
    s.author_id = None
    slug = s.form.slug if s.form else ''
    names = [f.stored_filename for f in s.files]
    removed = _remove_files([os.path.join(uploads_base(), 'forms', slug, s.uid_public or '', n) for n in names])
    for f in list(s.files):
        db.session.delete(f)
    return removed


def _detach_user(u):
    """Détache toutes les références avant suppression (contraintes FK)."""
    Ticket.query.filter(Ticket.author_id == u.id).update({'author_id': None}, synchronize_session=False)
    Ticket.query.filter(Ticket.solver_id == u.id).update({'solver_id': None}, synchronize_session=False)
    TicketMessage.query.filter(TicketMessage.author_id == u.id).update({'author_id': None}, synchronize_session=False)
    FormSubmission.query.filter(FormSubmission.author_id == u.id).update({'author_id': None}, synchronize_session=False)
    Recruitment.query.filter(Recruitment.author_id == u.id).update({'author_id': None}, synchronize_session=False)
    DossierSejour.query.filter(DossierSejour.author_id == u.id).update({'author_id': None}, synchronize_session=False)
    Publication.query.filter(Publication.author_id == u.id).update({'author_id': None}, synchronize_session=False)
    Announcement.query.filter(Announcement.created_by_id == u.id).update({'created_by_id': None}, synchronize_session=False)
    FormDefinition.query.filter(FormDefinition.created_by_id == u.id).update({'created_by_id': None}, synchronize_session=False)
    AuditLog.query.filter(AuditLog.user_id == u.id).update({'user_id': None}, synchronize_session=False)
    Notification.query.filter(Notification.user_id == u.id).delete(synchronize_session=False)


def apply_purge(plan, actor=None, write_log=True):
    """Exécute le plan (tel que renvoyé par plan_purge) : base + fichiers,
    une seule transaction, entrée d'audit `rgpd.purge`, journal texte.
    Retourne {'applied': n, 'files_removed': n, 'log_path': str|None, 'lines': [...]}."""
    from app.audit import log_action
    now = plan.get('now') or datetime.now()
    lines, applied, files_removed = [], 0, 0
    try:
        for op in plan['operations']:
            rule = op['rule']
            removed = []
            if rule == 'anonymize_ticket':
                t = Ticket.query.get(op['target_id'])
                if t:
                    removed = _anonymize_ticket(t)
            elif rule == 'anonymize_submission':
                s = FormSubmission.query.get(op['target_id'])
                if s:
                    removed = _anonymize_submission(s)
            elif rule == 'files_fcpi':
                r = Recruitment.query.get(op['target_id'])
                if r:
                    removed = _remove_files(op['files'])
                    _strip_ticket_copies(op.get('child_ticket_ids'), op.get('filenames'))
                    r.file_cv = r.file_fiche_poste = r.file_photo = None
            elif rule == 'files_daf_rib':
                t = Ticket.query.get(op['target_id'])
                if t:
                    removed = _remove_files(op['files'])
                    t.daf_rib_file = None
            elif rule == 'files_sejour':
                d = DossierSejour.query.get(op['target_id'])
                if d:
                    removed = _remove_files(op['files'])
                    _strip_ticket_copies(op.get('child_ticket_ids'), op.get('filenames'))
                    d.file_dossier = d.file_dossier_signe = d.file_pv_securite = d.file_devis = None
            elif rule == 'files_submission':
                s = FormSubmission.query.get(op['target_id'])
                if s:
                    removed = _remove_files(op['files'])
                    _strip_ticket_copies(op.get('child_ticket_ids'), op.get('filenames'))
                    for f in list(s.files):
                        db.session.delete(f)
            elif rule == 'notifications':
                n = Notification.query.filter(Notification.is_read.is_(True),
                                              Notification.timestamp < op['before']).delete(synchronize_session=False)
                op = dict(op, detail=f"{n} supprimée(s)")
            elif rule == 'inactive_user':
                u = User.query.get(op['target_id'])
                if u:
                    _detach_user(u)
                    db.session.delete(u)
            else:
                continue
            applied += 1
            files_removed += len(removed)
            lines.append(f"{rule:22s} {op['target_type'] or '':16s} {op['target_ref'] or '':30s} {op['detail']}"
                         + (f" ; {len(removed)} fichier(s) supprimé(s)" if removed else ''))

        summary = f"{applied} opération(s), {files_removed} fichier(s) supprimé(s)"
        log_action('rgpd.purge', ('Purge', None, now.strftime('%Y-%m-%d')), user=actor, details=summary)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    log_path = None
    if write_log:
        log_path = _write_log(now, plan, lines, summary, actor)
    return {'applied': applied, 'files_removed': files_removed, 'log_path': log_path,
            'lines': lines, 'summary': summary}


def _write_log(now, plan, lines, summary, actor):
    try:
        directory = log_dir()
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"rgpd_{now.strftime('%Y-%m-%d')}.log")
        with open(path, 'a', encoding='utf-8') as fp:
            fp.write(f"=== Purge RGPD du {now.strftime('%d/%m/%Y %H:%M')} — {summary}"
                     f" — par {getattr(actor, 'username', None) or 'cron'} ===\n")
            for code, n in plan['counts'].items():
                if n:
                    fp.write(f"  {code}: {n}\n")
            for line in lines:
                fp.write(f"  {line}\n")
            fp.write("\n")
        return path
    except OSError as e:
        current_app.logger.warning(f"RGPD : journal non écrit ({e})")
        return None
