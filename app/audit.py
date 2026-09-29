"""Journal d'audit (lot 8) : `log_action()` trace une action sensible dans la
table audit_logs, dans la transaction courante de l'appelant (db.session.add,
pas de commit), et NE FAIT JAMAIS ÉCHOUER l'action tracée : toute erreur est
avalée et loguée en warning.

Actions utilisées dans le code (chaîne courte, préfixe = domaine) :
  ticket.validate / ticket.refuse / ticket.close / ticket.reopen /
  ticket.assign / ticket.transfer / ticket.rate
  submission.validate / submission.refuse
  user.create / user.update / user.delete
  form.activate / form.deactivate / form.delete
  auth.login / auth.sso_login / auth.login_failed
  rgpd.purge / report.generate

Le paramètre `commit=True` n'est utilisé que hors transaction métier (échec
de connexion, connexion réussie après le commit du provisioning) : dans ce cas
l'entrée est validée seule, et un échec de ce commit est lui aussi avalé.
"""
from flask import current_app, has_request_context, has_app_context, request

from app import db
from app.models import AuditLog

ACTION_LABELS = {
    'ticket.validate': 'Ticket validé',
    'ticket.refuse': 'Ticket refusé',
    'ticket.close': 'Ticket clôturé',
    'ticket.reopen': 'Ticket rouvert',
    'ticket.assign': 'Ticket affecté',
    'ticket.transfer': 'Ticket transféré',
    'ticket.rate': 'Avis du demandeur',
    'submission.validate': 'Formulaire : étape validée',
    'submission.refuse': 'Formulaire refusé',
    'user.create': 'Compte créé',
    'user.update': 'Compte modifié',
    'user.delete': 'Compte supprimé',
    'form.activate': 'Formulaire activé',
    'form.deactivate': 'Formulaire désactivé',
    'form.delete': 'Formulaire supprimé',
    'auth.login': 'Connexion',
    'auth.sso_login': 'Connexion SSO',
    'auth.login_failed': 'Échec de connexion',
    'rgpd.purge': 'Purge RGPD',
    'report.generate': 'Rapport mensuel généré',
}


def _describe_target(target):
    """(type, id, référence lisible) pour un objet modèle, un tuple
    (type, id, ref), une chaîne (référence seule) ou None."""
    if target is None:
        return None, None, None
    if isinstance(target, tuple):
        parts = list(target) + [None, None, None]
        return parts[0], parts[1], parts[2]
    if isinstance(target, str):
        return None, None, target[:100]
    ttype = type(target).__name__
    tid = getattr(target, 'id', None)
    ref = None
    for attr in ('uid_public', 'username', 'slug', 'title', 'name'):
        val = getattr(target, attr, None)
        if val:
            ref = str(val)
            break
    return ttype, tid, (ref[:100] if ref else None)


def _resolve_user(user):
    if user is not None:
        return user
    if has_request_context():
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                return current_user._get_current_object()
        except Exception:
            return None
    return None


def log_action(action, target, user=None, details=None, commit=False):
    """Ajoute une entrée d'audit à la session courante. Ne lève jamais.

    action  : chaîne courte 'domaine.verbe' (voir ACTION_LABELS).
    target  : objet modèle (Ticket, FormSubmission, User, FormDefinition…),
              tuple (type, id, ref), chaîne (référence) ou None.
    user    : acteur ; par défaut current_user s'il est connecté.
    details : texte court (motif, ancien/nouveau service, note…), tronqué.
    commit  : True pour valider l'entrée seule (hors transaction métier).
    Retourne l'entrée créée, ou None en cas d'échec.
    """
    try:
        if not has_app_context():
            return None
        actor = _resolve_user(user)
        ttype, tid, tref = _describe_target(target)
        if tid is None and target is not None and not isinstance(target, (tuple, str)) \
                and target in db.session:
            # Objet tout juste ajouté (ex: compte créé) : on tente un flush
            # pour obtenir son id, sans bloquer si ce n'est pas possible.
            try:
                db.session.flush()
                tid = getattr(target, 'id', None)
            except Exception:
                tid = None
        ip = None
        if has_request_context():
            ip = (request.headers.get('X-Forwarded-For', '') or request.remote_addr or '').split(',')[0].strip()[:45] or None
        entry = AuditLog(
            user_id=getattr(actor, 'id', None),
            username=(getattr(actor, 'username', None) or None),
            action=str(action)[:40],
            target_type=ttype[:40] if ttype else None,
            target_id=tid,
            target_ref=tref,
            details=(str(details)[:500] if details is not None else None),
            ip=ip,
        )
        db.session.add(entry)
        if commit:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.warning(f"Audit : commit impossible pour {action} ({e})")
                return None
        return entry
    except Exception as e:
        try:
            current_app.logger.warning(f"Audit : entrée {action} non enregistrée ({e})")
        except Exception:
            pass
        return None


def history_for(target_type, target_id, limit=50):
    """Entrées d'audit d'une cible, de la plus ancienne à la plus récente
    (« Historique » du détail d'un ticket). Ne lève jamais."""
    try:
        return (AuditLog.query.filter_by(target_type=target_type, target_id=target_id)
                .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc()).limit(limit).all())
    except Exception:
        return []


def action_label(action):
    return ACTION_LABELS.get(action, action)
