from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'ADMIN' not in str(current_user.role.value).upper():
            flash("Accès réservé aux administrateurs.", "danger")
            return redirect(url_for('main.user_portal'))
        return f(*args, **kwargs)
    return wrapped


def can_validate_step(user, step, submission):
    """Un utilisateur peut valider une étape s'il est ADMIN, ou s'il correspond
    au rôle et au service attendus par l'étape.

    Rôle : si `step.validator_role` est renseigné, il faut ce rôle précis.
    Sinon, MANAGER ou DIRECTEUR conviennent (comme le système de tickets
    existant, qui ne distingue pas les deux pour valider une étape N1/N2).

    Service : deux modes (`step.service_source`) —
    - FIXED : si `step.validator_service` est renseigné, il doit être dans les
      services gérés (`get_allowed_services()`) du validateur (cas
      "destinataire" ciblé). S'il n'est pas renseigné, aucune contrainte de
      service (seul le rôle compte — ex: "n'importe quel Directeur").
    - EMITTER : le service à matcher est celui du demandeur lui-même
      (`submission.author`), comparé aux services d'origine
      (`get_origin_services()`) du validateur (cas "émetteur" — mirroir de la
      validation N1 hiérarchique du système de tickets).
    """
    from app.models import UserRole, ServiceSource

    if 'ADMIN' in str(user.role.value).upper():
        return True

    if step.validator_role:
        role_ok = user.role == step.validator_role
    else:
        role_ok = user.role in (UserRole.MANAGER, UserRole.DIRECTEUR)
    if not role_ok:
        return False

    if step.service_source == ServiceSource.EMITTER:
        emitter_services = set(submission.author.get_origin_services()) if submission.author else set()
        return bool(emitter_services & set(user.get_origin_services()))
    elif step.validator_service:
        return step.validator_service.value in user.get_allowed_services()
    else:
        return True
