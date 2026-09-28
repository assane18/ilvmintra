"""Écran mural (« wallboard ») de l'Espace Tech.

Vue plein écran, fond sombre, destinée à un écran du service informatique :
compteurs, file « À prendre en charge », tickets « En cours » groupés par
technicien et dernières prises en charge / clôtures. La page ne fait aucun
rendu serveur des données : elle interroge ``/tickets/wallboard/data`` toutes
les 30 s (auto-rafraîchissement sans rechargement).

Blueprint séparé de ``tickets.py`` (chantiers parallèles sur ce fichier) mais
qui en RÉUTILISE les règles d'accès : rôles SOLVER / MANAGER / DIRECTEUR /
ADMIN (``check_permission``) et périmètre limité aux services autorisés de
l'utilisateur (``User.get_allowed_services()``, ADMIN = tous), comme
``solver_dashboard``.
"""
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from app.models import ServiceType, Ticket, TicketStatus
from app.routes.tickets import check_permission, nocache, safe_role_str
from app.status_display import status_label

wallboard_bp = Blueprint('wallboard', __name__)

WALLBOARD_ROLES = ['SOLVER', 'MANAGER', 'DIRECTEUR', 'ADMIN']

# Seuil « en retard » actuel (même règle que Ticket.is_stale : 24 h). Isolé ici
# pour brancher ensuite le calcul sur le SLA (sla_label / sla_remaining_hours,
# pas encore disponibles dans cette branche) sans toucher au reste.
LATE_THRESHOLD_HOURS = 24

_SERVICE_NAME_TO_VALUE = {s.name: s.value for s in ServiceType}
_SERVICE_VALUES = {s.value for s in ServiceType}


def is_late(ticket):
    """Un ticket est « en retard » s'il attend encore un technicien (PENDING /
    IN_PROGRESS) depuis plus de LATE_THRESHOLD_HOURS. Point d'entrée unique à
    remplacer par la règle SLA quand elle existera."""
    return (ticket.status in (TicketStatus.PENDING, TicketStatus.IN_PROGRESS)
            and ticket.age_hours > LATE_THRESHOLD_HOURS)


def _canon_service(token):
    """Normalise un token de service (nom d'enum, valeur, membre, ou l'alias
    historique 'GS-DRH') vers la valeur canonique ServiceType.value ; None si
    inconnu."""
    if token is None:
        return None
    if hasattr(token, 'value'):
        token = token.value
    if token == 'GS-DRH':
        return 'DRH'
    if token in _SERVICE_NAME_TO_VALUE:
        return _SERVICE_NAME_TO_VALUE[token]
    return token if token in _SERVICE_VALUES else None


def allowed_service_values(user):
    """Périmètre de l'utilisateur : None = tous (ADMIN), sinon ensemble trié
    de valeurs ServiceType (les tokens inconnus sont ignorés)."""
    if 'ADMIN' in safe_role_str(user):
        return None
    values = {_canon_service(t) for t in (user.get_allowed_services() or [])}
    values.discard(None)
    return sorted(values)


def _resolve_scope(user, requested):
    """Combine le périmètre autorisé et le filtre ``?service=`` optionnel.

    Retourne (membres ServiceType à interroger, valeur du filtre retenu ou
    None, autorisé : bool). ``autorisé`` est False si le service demandé est
    inconnu ou hors périmètre — la vue répond alors 403 plutôt que d'élargir
    silencieusement le périmètre."""
    allowed = allowed_service_values(user)
    wanted = _canon_service(requested) if requested else None
    if requested and wanted is None:
        return [], None, False
    if wanted and allowed is not None and wanted not in allowed:
        return [], None, False
    if wanted:
        values = [wanted]
    elif allowed is None:
        values = None  # illimité
    else:
        values = allowed
    members = None if values is None else [s for s in ServiceType if s.value in values]
    return members, wanted, True


def _scoped_query(members):
    q = Ticket.query
    if members is not None:
        # Filtrage par membres d'enum (et non par chaînes) : la colonne est un
        # db.Enum(ServiceType), qui stocke les NOMS ; passer des valeurs brutes
        # ferait échouer la conversion.
        q = q.filter(Ticket.target_service.in_(members)) if members else q.filter(False)
    return q


def _age_label(hours):
    if hours < 1:
        return f"{int(round(hours * 60))} min"
    if hours < 48:
        return f"{int(hours)} h"
    return f"{int(hours // 24)} j"


def _person(user):
    if not user:
        return None
    return user.fullname or user.username


def _serialize(ticket):
    return {
        'id': ticket.id,
        'uid': ticket.uid_public,
        'title': ticket.title,
        'service': ticket.get_safe_target_service(),
        'category': ticket.category_ticket,
        'requester': _person(ticket.author) or ticket.author_name,
        'requester_service': ticket.service_demandeur,
        'solver': _person(ticket.solver),
        'status': ticket.get_safe_status(),
        'status_label': status_label(ticket.status, short=True),
        'age_hours': round(ticket.age_hours, 1),
        'age_label': _age_label(ticket.age_hours),
        'late': is_late(ticket),
        'created_at': ticket.created_at.isoformat() if ticket.created_at else None,
    }


def build_wallboard_data(user, requested_service=None, now=None):
    """Calcule le contenu JSON de l'écran mural pour ``user``.

    Lève ``PermissionError`` si le service demandé est hors périmètre."""
    now = now or datetime.now()
    members, service, ok = _resolve_scope(user, requested_service)
    if not ok:
        raise PermissionError(requested_service)

    base = _scoped_query(members)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    pending = (base.filter(Ticket.status == TicketStatus.PENDING)
                   .order_by(Ticket.created_at.asc()).all())
    in_progress = (base.filter(Ticket.status == TicketStatus.IN_PROGRESS)
                       .order_by(Ticket.created_at.asc()).all())
    closed_today = base.filter(Ticket.status == TicketStatus.DONE,
                               Ticket.closed_at.isnot(None),
                               Ticket.closed_at >= today_start).count()

    late_count = sum(1 for t in pending + in_progress if is_late(t))

    # Regroupement « En cours » par technicien (non affectés en dernier).
    groups = {}
    for t in in_progress:
        key = t.solver_id or 0
        g = groups.setdefault(key, {'solver': _person(t.solver) or 'Non affecté',
                                    'count': 0, 'late': 0, 'tickets': []})
        g['count'] += 1
        if is_late(t):
            g['late'] += 1
        g['tickets'].append(_serialize(t))
    by_solver = sorted(groups.values(), key=lambda g: (g['solver'] == 'Non affecté', -g['count'], g['solver']))

    # 5 dernières prises en charge / clôtures : on prend 5 candidats de chaque
    # type puis on fusionne par date décroissante.
    taken = (base.filter(Ticket.assigned_at.isnot(None))
                 .order_by(Ticket.assigned_at.desc()).limit(5).all())
    closed = (base.filter(Ticket.status == TicketStatus.DONE, Ticket.closed_at.isnot(None))
                  .order_by(Ticket.closed_at.desc()).limit(5).all())
    events = [{'kind': 'taken', 'label': 'Prise en charge', 'at': t.assigned_at, 'ticket': _serialize(t)} for t in taken]
    events += [{'kind': 'closed', 'label': 'Clôturé', 'at': t.closed_at, 'ticket': _serialize(t)} for t in closed]
    events.sort(key=lambda e: e['at'], reverse=True)
    recent = [{**e, 'at': e['at'].isoformat()} for e in events[:5]]

    return {
        'generated_at': now.isoformat(),
        'service': service,
        'late_threshold_hours': LATE_THRESHOLD_HOURS,
        'counters': {
            'pending': len(pending),
            'in_progress': len(in_progress),
            'late': late_count,
            'closed_today': closed_today,
        },
        'pending': [_serialize(t) for t in pending],
        'in_progress_by_solver': by_solver,
        'recent': recent,
    }


def _service_options(user):
    """Options du sélecteur de service : périmètre de l'utilisateur, ou
    l'ensemble des services pour un ADMIN."""
    allowed = allowed_service_values(user)
    values = [s.value for s in ServiceType] if allowed is None else allowed
    return [{'value': v, 'label': v} for v in values]


@wallboard_bp.route('/wallboard')
@login_required
@nocache
def wallboard():
    if not check_permission(WALLBOARD_ROLES):
        return render_template('errors/catdance.html'), 403
    requested = request.args.get('service') or None
    _members, service, ok = _resolve_scope(current_user, requested)
    if not ok:
        return render_template('errors/catdance.html'), 403
    return render_template('tickets/wallboard.html',
                           service=service,
                           service_options=_service_options(current_user),
                           refresh_seconds=30,
                           late_threshold_hours=LATE_THRESHOLD_HOURS)


@wallboard_bp.route('/wallboard/data')
@login_required
@nocache
def wallboard_data():
    if not check_permission(WALLBOARD_ROLES):
        return jsonify({'error': 'forbidden'}), 403
    requested = request.args.get('service') or None
    try:
        data = build_wallboard_data(current_user, requested)
    except PermissionError:
        return jsonify({'error': 'forbidden', 'service': requested}), 403
    return jsonify(data)
