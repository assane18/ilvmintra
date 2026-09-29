"""Lot 7 — « Organisation des demandes » : logique pure, sans dépendance à la
requête Flask (testable en isolation), partagée par les routes.

1. Délégation de validation (absences) : `ValidationDelegation` — pendant la
   période, le délégué voit et peut valider tout ce que le délégant pourrait
   valider, en plus de ses propres droits. Point d'entrée unique :
   `effective_validators(user)` / `validation_identities(user, author_id)`,
   utilisé par tickets._can_validate_ticket, decorators.can_validate_step,
   tickets.manager_dashboard et (par transitivité) digests.pending_validations_for.
   La trace « validé par X pour le compte de Y » est produite par des écouteurs
   SQLAlchemy `before_flush` / `before_commit` (section 2) : le contrôle d'accès
   mémorise sur l'objet contrôlé l'identité empruntée, et les écouteurs ajoutent
   message + notifications au moment où la validation est réellement
   enregistrée (validated_by_id / validated_at), sans toucher au moteur de
   validation (_validate_ticket, advance_submission).

2. Demande pour quelqu'un d'autre : `author` = la personne concernée,
   `created_by` = la personne qui a saisi (Ticket / FormSubmission). Le
   créateur réel est prévenu à la clôture (même écouteur before_flush).

3. Refaire la même demande : pré-remplissage d'un formulaire du moteur ou
   d'un ticket legacy à partir d'une demande existante de l'utilisateur.
"""
import re
from datetime import datetime, time, timedelta

from sqlalchemy import event, func, inspect, or_

from app import db
from app.models import (FormSubmission, FormSubmissionStatus, FormFieldType, Notification,
                        ServiceType, Ticket, TicketMessage, TicketStatus, User, UserRole,
                        ValidationDelegation)

# Rôles pouvant recevoir une délégation (le délégué) — jamais USER/SOLVER.
DELEGATE_ROLES = tuple(UserRole)  # tout utilisateur peut recevoir une délégation (il agit alors avec les droits du délégant)
# Rôles pouvant déclarer une délégation (le délégant).
DELEGATOR_ROLES = (UserRole.MANAGER, UserRole.DIRECTEUR, UserRole.ADMIN)

# Attribut transitoire posé sur un Ticket / une FormSubmission par le contrôle
# d'accès quand le droit de valider vient d'une délégation (= le délégant).
ON_BEHALF_ATTR = '_lot7_on_behalf_of'


def _unwrap(user):
    """current_user est un LocalProxy : on travaille sur l'objet réel."""
    if user is not None and hasattr(user, '_get_current_object'):
        user = user._get_current_object()
    return user


def _display(user):
    return (user.fullname or user.username) if user else '?'


def _safe_url(endpoint, fallback, **kwargs):
    try:
        from flask import url_for
        return url_for(endpoint, **kwargs)
    except Exception:
        return fallback


def _notify(user, message, category='info', link=None):
    if user:
        db.session.add(Notification(user=user, message=message[:255], category=category, link=link))


# ---------------------------------------------------------------------------
#  1. Délégations — identités effectives d'un validateur
# ---------------------------------------------------------------------------

def active_delegations_for(user, now=None):
    """Délégations en vigueur dont `user` est le délégué."""
    user = _unwrap(user)
    if not getattr(user, 'id', None):
        return []
    now = now or datetime.now()
    return ValidationDelegation.query.filter(
        ValidationDelegation.delegate_id == user.id,
        ValidationDelegation.is_active.is_(True),
        ValidationDelegation.starts_at <= now,
        ValidationDelegation.ends_at >= now,
    ).order_by(ValidationDelegation.starts_at).all()


def effective_validators(user, now=None):
    """L'utilisateur lui-même + les délégants dont il tient une délégation
    active, sans doublon. Toute règle d'éligibilité à la validation s'évalue
    en bouclant sur cette liste."""
    user = _unwrap(user)
    identities = [user]
    seen = {getattr(user, 'id', None)}
    for d in active_delegations_for(user, now):
        if d.delegator and d.delegator.id not in seen:
            identities.append(d.delegator)
            seen.add(d.delegator.id)
    return identities


def validation_identities(user, author_id=None, now=None):
    """Comme effective_validators, mais un délégué ne peut jamais utiliser une
    délégation pour valider SA PROPRE demande (author_id) : dans ce cas, seuls
    ses droits personnels comptent."""
    user = _unwrap(user)
    if author_id is not None and getattr(user, 'id', None) == author_id:
        return [user]
    return effective_validators(user, now)


def check_as_identities(user, subject, predicate, author_id=None):
    """Vrai si `predicate(identity)` passe pour l'utilisateur lui-même ou pour
    l'un de ses délégants actifs. Mémorise sur `subject` (Ticket ou
    FormSubmission) le délégant emprunté — ou None si les droits propres
    suffisent — pour la trace « pour le compte de » (voir before_flush)."""
    user = _unwrap(user)
    for identity in validation_identities(user, author_id):
        if predicate(identity):
            borrowed = None if identity.id == user.id else identity
            try:
                setattr(subject, ON_BEHALF_ATTR, borrowed)
            except Exception:
                pass
            return True
    try:
        setattr(subject, ON_BEHALF_ATTR, None)
    except Exception:
        pass
    return False


def on_behalf_of(subject):
    """Délégant emprunté lors du dernier contrôle d'accès sur cet objet (ou None)."""
    return getattr(subject, ON_BEHALF_ATTR, None)


def acting_label(validator, delegator):
    """« Prénom Nom pour le compte de Prénom Nom » (ou juste le validateur)."""
    label = _display(validator)
    if delegator and getattr(delegator, 'id', None) != getattr(validator, 'id', None):
        label += f" pour le compte de {_display(delegator)}"
    return label


# ---------------------------------------------------------------------------
#  2. Trace « pour le compte de » + notification du créateur réel
# ---------------------------------------------------------------------------
# Deux temps, car un autoflush peut survenir AVANT que le statut final soit
# posé (ex: manager_action/refuse renseigne validated_by_id, accède à t.author
# -> autoflush, puis seulement status = REFUSED) :
#   - before_flush : détecte les changements (historique d'attributs encore
#     disponible) et les mémorise dans session.info ;
#   - before_commit : tout est posé -> ajoute message + notifications, que le
#     flush final du commit persiste. Un rollback vide la file.

_PENDING_KEY = 'lot7_pending'


def _changed(obj, attr):
    try:
        return inspect(obj).attrs[attr].history.has_changes()
    except Exception:
        return False


def _mark(session, obj, kind, delegator=None):
    pending = session.info.setdefault(_PENDING_KEY, {})
    entry = pending.setdefault(id(obj), {'obj': obj, 'kinds': set(), 'delegator': None})
    entry['kinds'].add(kind)
    if delegator is not None:
        entry['delegator'] = delegator


_CLOSED_ATTR = '_lot7_closed_marked'   # garde anti-doublon (le statut reste « changé » jusqu'au flush final)


def _collect(session):
    for obj in list(session.dirty):
        if isinstance(obj, Ticket):
            delegator = on_behalf_of(obj)
            if delegator is not None and (_changed(obj, 'validated_by_id') or _changed(obj, 'validated_at')):
                _mark(session, obj, 'validated', delegator)
                setattr(obj, ON_BEHALF_ATTR, None)
            if obj.created_by_id and obj.created_by_id != obj.author_id and _changed(obj, 'status') \
                    and obj.status in (TicketStatus.DONE, TicketStatus.REFUSED) and not getattr(obj, _CLOSED_ATTR, False):
                _mark(session, obj, 'closed')
                setattr(obj, _CLOSED_ATTR, True)
        elif isinstance(obj, FormSubmission):
            delegator = on_behalf_of(obj)
            if delegator is not None:
                if _changed(obj, 'validated_by_id') or _changed(obj, 'last_validated_at'):
                    _mark(session, obj, 'validated', delegator)
                    setattr(obj, ON_BEHALF_ATTR, None)
                elif _changed(obj, 'status') and obj.status == FormSubmissionStatus.REFUSED:
                    _mark(session, obj, 'refused', delegator)
                    setattr(obj, ON_BEHALF_ATTR, None)
            if obj.created_by_id and obj.created_by_id != obj.author_id and _changed(obj, 'status') \
                    and obj.status in (FormSubmissionStatus.DONE, FormSubmissionStatus.REFUSED) and not getattr(obj, _CLOSED_ATTR, False):
                _mark(session, obj, 'closed')
                setattr(obj, _CLOSED_ATTR, True)


@event.listens_for(db.session, 'before_flush')
def _lot7_before_flush(session, flush_context, instances):
    _collect(session)


@event.listens_for(db.session, 'after_soft_rollback')
def _lot7_forget(session, previous_transaction):
    session.info.pop(_PENDING_KEY, None)


@event.listens_for(db.session, 'before_commit')
def _lot7_emit(session):
    _collect(session)  # changements pas encore flushés (commit direct, sans autoflush intermédiaire)
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending:
        return
    with session.no_autoflush:
        for entry in pending.values():
            obj = entry['obj']
            if isinstance(obj, Ticket):
                _trace_ticket(session, obj, entry['kinds'], entry['delegator'])
            elif isinstance(obj, FormSubmission):
                _trace_submission(session, obj, entry['kinds'], entry['delegator'])


def _trace_ticket(session, t, kinds, delegator):
    link = _safe_url('tickets.view_ticket', f"/tickets/view/{t.uid_public}", ticket_uid=t.uid_public)
    if 'validated' in kinds and delegator is not None:
        validator = session.get(User, t.validated_by_id) if t.validated_by_id else None
        refused = t.status == TicketStatus.REFUSED
        verb = 'refusé' if refused else 'validé'
        who = acting_label(validator, delegator)
        session.add(TicketMessage(content=f"Ticket {verb.upper()} par {who} (délégation de validation).",
                                  ticket=t, author=validator))
        _notify(delegator, f"{_display(validator)} a {verb} le ticket {t.uid_public} pour votre compte (délégation).", 'info', link)
        if not refused:
            _notify(t.author, f"Votre ticket {t.uid_public} a été validé par {who}.", 'success', link)
    if 'closed' in kinds and t.created_by_id and t.status in (TicketStatus.DONE, TicketStatus.REFUSED):
        creator = session.get(User, t.created_by_id)
        done = t.status == TicketStatus.DONE
        _notify(creator, f"Le ticket {t.uid_public} que vous avez créé pour {_display(t.author)} "
                         f"{'a été traité et clôturé' if done else 'a été refusé'}.",
                'success' if done else 'danger', link)


def _trace_submission(session, s, kinds, delegator):
    link = _safe_url('forms.view_submission', f"/forms/submission/{s.id}", id=s.id)
    if delegator is not None and ('validated' in kinds or 'refused' in kinds):
        if s.status == FormSubmissionStatus.REFUSED:
            if s.refusal_reason and 'pour le compte de' not in s.refusal_reason:
                s.refusal_reason = f"{s.refusal_reason} (pour le compte de {_display(delegator)})"
            _notify(delegator, f"Le formulaire {s.uid_public} a été refusé pour votre compte (délégation).", 'info', link)
        else:
            validator = session.get(User, s.validated_by_id) if s.validated_by_id else None
            who = acting_label(validator, delegator)
            _notify(delegator, f"{_display(validator)} a validé le formulaire {s.uid_public} pour votre compte (délégation).", 'info', link)
            _notify(s.author, f"Votre formulaire {s.uid_public} a été validé par {who}.", 'success', link)
    if 'closed' in kinds and s.created_by_id and s.status in (FormSubmissionStatus.DONE, FormSubmissionStatus.REFUSED):
        creator = session.get(User, s.created_by_id)
        done = s.status == FormSubmissionStatus.DONE
        _notify(creator, f"Le formulaire {s.uid_public} que vous avez déposé pour {_display(s.author)} "
                         f"{'a été validé et est terminé' if done else 'a été refusé'}.",
                'success' if done else 'danger', link)


# ---------------------------------------------------------------------------
#  1 bis. Gestion des délégations (création / annulation)
# ---------------------------------------------------------------------------

def can_manage_delegations(user):
    return getattr(user, 'role', None) in DELEGATOR_ROLES


def delegation_error(delegator, delegate, starts_at, ends_at):
    """Message d'erreur (français) ou None si la délégation est valide."""
    if not delegator or not can_manage_delegations(delegator):
        return "Seuls les managers, directeurs et administrateurs peuvent déléguer leur validation."
    if not delegate:
        return "Choisissez la personne qui validera à votre place."
    if delegate.id == delegator.id:
        return "Vous ne pouvez pas vous déléguer la validation à vous-même."
    if delegate.role not in DELEGATE_ROLES:
        return "Ce compte ne peut pas recevoir de délégation."
    if not starts_at or not ends_at:
        return "Indiquez les dates de début et de fin."
    if ends_at < starts_at:
        return "La date de fin doit être postérieure à la date de début."
    if ends_at < datetime.now():
        return "La période est déjà terminée."
    return None


def parse_period(start_str, end_str):
    """'AAAA-MM-JJ' x2 -> (début 00:00:00, fin 23:59:59) ; (None, None) si invalide."""
    try:
        d1 = datetime.strptime((start_str or '').strip(), '%Y-%m-%d').date()
        d2 = datetime.strptime((end_str or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        return None, None
    return datetime.combine(d1, time.min), datetime.combine(d2, time(23, 59, 59))


def create_delegation(delegator, delegate, starts_at, ends_at, reason=None):
    """Crée la délégation (après contrôle) et prévient le délégué (in-app +
    e-mail). Retourne (delegation, erreur)."""
    delegator, delegate = _unwrap(delegator), _unwrap(delegate)
    error = delegation_error(delegator, delegate, starts_at, ends_at)
    if error:
        return None, error
    d = ValidationDelegation(delegator=delegator, delegate=delegate, starts_at=starts_at, ends_at=ends_at,
                             reason=(reason or '').strip()[:255] or None, is_active=True)
    db.session.add(d)
    period = f"du {starts_at.strftime('%d/%m/%Y')} au {ends_at.strftime('%d/%m/%Y')}"
    _notify(delegate, f"{_display(delegator)} vous délègue ses validations {period}.", 'warning',
            _safe_url('tickets.manager_dashboard', '/tickets/manager/dashboard'))
    _email_delegate(d, period)
    return d, None


def _email_delegate(d, period):
    if not d.delegate or not d.delegate.email:
        return
    try:
        from flask import current_app
        from app.emails import send_email, get_outlook_friendly_html
        base_url = current_app.config.get('BASE_URL', '') or ''
        link = f"{base_url.rstrip('/')}/tickets/manager/dashboard"
        title = "Délégation de validation"
        content = (f"<p>Bonjour {_display(d.delegate)},</p>"
                   f"<p><strong>{_display(d.delegator)}</strong> vous délègue ses validations <strong>{period}</strong>."
                   + (f"<br>Motif : {d.reason}" if d.reason else "") +
                   "</p><p>Pendant cette période, ses demandes à valider (tickets, formulaires) apparaissent dans votre "
                   "tableau de bord manager, en plus des vôtres.</p>")
        text = (f"{_display(d.delegator)} vous délègue ses validations {period}."
                + (f" Motif : {d.reason}." if d.reason else ""))
        send_email(f"[Intranet] {title} — {_display(d.delegator)}", [d.delegate.email], text,
                   get_outlook_friendly_html(title, content, link, "Ouvrir le tableau de bord"), kind='important')
    except Exception as e:  # l'e-mail ne doit jamais bloquer la déclaration
        print(f"⚠️ E-mail délégation non envoyé : {e}")


def can_cancel_delegation(user, d):
    user = _unwrap(user)
    return bool(user) and (d.delegator_id == user.id or user.role == UserRole.ADMIN)


def cancel_delegation(d, by_user):
    d.is_active = False
    by_user = _unwrap(by_user)
    if d.delegate_id != by_user.id:
        _notify(d.delegate, f"La délégation de {_display(d.delegator)} "
                            f"({d.starts_at.strftime('%d/%m')} → {d.ends_at.strftime('%d/%m/%Y')}) a été annulée.", 'info')
    if d.delegator_id != by_user.id:
        _notify(d.delegator, f"Votre délégation à {_display(d.delegate)} a été annulée par {_display(by_user)}.", 'info')


def delegations_of(user):
    """(données, reçues) — toutes, la plus récente en tête (le template trie par état)."""
    user = _unwrap(user)
    given = ValidationDelegation.query.filter_by(delegator_id=user.id).order_by(ValidationDelegation.starts_at.desc()).all()
    received = ValidationDelegation.query.filter_by(delegate_id=user.id).order_by(ValidationDelegation.starts_at.desc()).all()
    return given, received


# ---------------------------------------------------------------------------
#  3. Recherche d'utilisateurs (autocomplétion)
# ---------------------------------------------------------------------------

def search_users(q, limit=10, roles=None, exclude_id=None):
    """Recherche insensible à la casse sur nom complet / identifiant."""
    q = (q or '').strip().lower()
    if len(q) < 2:
        return []
    query = User.query.filter(or_(func.lower(User.fullname).like(f'%{q}%'),
                                  func.lower(User.username).like(f'%{q}%')))
    if roles:
        query = query.filter(User.role.in_(list(roles)))
    if exclude_id:
        query = query.filter(User.id != exclude_id)
    return query.order_by(User.fullname, User.username).limit(limit).all()


def user_to_json(u):
    return {'id': u.id, 'username': u.username, 'fullname': u.fullname or u.username,
            'service': u.service, 'role': u.role.value if u.role else '',
            'label': f"{u.fullname or u.username} — {u.service}"}


# ---------------------------------------------------------------------------
#  4. Demande pour quelqu'un d'autre
# ---------------------------------------------------------------------------

def resolve_on_behalf(current, form):
    """Lit `on_behalf_of_id` du formulaire soumis ; retourne l'utilisateur
    concerné (bénéficiaire) ou None si absent / invalide / soi-même."""
    raw = (form.get('on_behalf_of_id') or '').strip()
    if not raw.isdigit():
        return None
    current = _unwrap(current)
    beneficiary = User.query.get(int(raw))
    if not beneficiary or beneficiary.id == getattr(current, 'id', None):
        return None
    return beneficiary


def is_manager_like(user):
    return getattr(user, 'role', None) in (UserRole.MANAGER, UserRole.DIRECTEUR, UserRole.ADMIN)


def notify_on_behalf_created(beneficiary, creator, ref, link):
    _notify(beneficiary, f"{_display(creator)} a créé la demande {ref} pour votre compte.", 'info', link)


def created_for_label(obj):
    """« Demande créée par Z pour le compte de A » ou None."""
    if getattr(obj, 'created_by_id', None) and obj.created_by_id != obj.author_id and obj.created_by:
        return f"Demande créée par {_display(obj.created_by)} pour le compte de {_display(obj.author)}"
    return None


# ---------------------------------------------------------------------------
#  5. Refaire la même demande
# ---------------------------------------------------------------------------

_LEGACY_UID = re.compile(r'^\d{8}-\d{3}$')
_FORM_TICKET_UID = re.compile(r'^(?:F|FRM-)(\d+)-')


def _owns(obj, user):
    uid = getattr(user, 'id', None)
    return uid is not None and (obj.author_id == uid or getattr(obj, 'created_by_id', None) == uid)


def redo_url_for_submission(sub):
    if not sub or not sub.form or not sub.form.is_active:
        return None
    return _safe_url('forms.new_submission', f"/forms/{sub.form.slug}/new?from={sub.id}",
                     slug=sub.form.slug, **{'from': sub.id})


def redo_url_for_ticket(t):
    """Ticket legacy (uid AAAAMMJJ-NNN) -> /tickets/new/<service>?from=uid ;
    ticket issu du moteur (F<id>-…, FRM-<id>-…) -> formulaire d'origine."""
    if not t or not t.uid_public:
        return None
    m = _FORM_TICKET_UID.match(t.uid_public)
    if m:
        return redo_url_for_submission(FormSubmission.query.get(int(m.group(1))))
    if not _LEGACY_UID.match(t.uid_public) or t.target_service is None:
        return None
    kwargs = {'from': t.uid_public}
    if (t.category_ticket or '') == 'Demande Matériel':
        service_name = 'MATERIEL'
    else:
        service_name = t.target_service.name
        if (t.category_ticket or '') == 'Bon de Commande (Délégation)':
            kwargs['type'] = 'delegation'
    return _safe_url('tickets.new_ticket', f"/tickets/new/{service_name}?from={t.uid_public}",
                     service_name=service_name, **kwargs)


_DRH_CHOICES = ('Changement de RIB', 'Contrat', "Modification d'information")


def ticket_prefill(uid, user):
    """Champs simples d'un ticket legacy de l'utilisateur, prêts pour
    new_ticket.html (dict vide si inconnu ou pas à lui)."""
    if not uid:
        return {}
    t = Ticket.query.filter_by(uid_public=uid).first()
    if not t or not _owns(t, user):
        return {}
    data = {
        'title': t.title or '',
        'description': t.description or '',
        'hostname': t.hostname or '',
        'tel_demandeur': t.tel_demandeur or '',
        'category_ticket': t.category_ticket or '',
        'lieu_installation': t.lieu_installation or '',
        'selected_origin': t.service_demandeur or '',
    }
    if (t.title or '').startswith('[DRH] '):
        subject = t.title[6:]
        if subject in _DRH_CHOICES:
            data['titre_drh_select'] = subject
        else:
            data['titre_drh_select'], data['titre_drh_autre'] = 'Autre', subject
    return data


def submission_prefill(sub_id, user, form_def):
    """Valeurs (hors fichiers) d'une soumission de l'utilisateur, pour le même
    formulaire, sous forme de MultiDict compatible avec _submission_fields.html
    (get/getlist). None si inconnue, d'un autre formulaire ou pas à lui."""
    from werkzeug.datastructures import MultiDict
    if not sub_id or not str(sub_id).isdigit():
        return None
    sub = FormSubmission.query.get(int(sub_id))
    if not sub or not _owns(sub, user) or sub.form_definition_id != form_def.id:
        return None
    data = sub.get_data()
    md = MultiDict()
    for field in form_def.fields:
        if field.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE):
            continue
        value = data.get(field.name)
        if value is None or value == '' or value is False:
            continue
        if isinstance(value, list):
            for v in value:
                md.add(field.name, v)
        elif value is True:
            md.add(field.name, 'on')
        else:
            md.add(field.name, str(value))
    return md
