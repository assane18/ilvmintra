"""Détection des demandes en double (2026-11-16).

Principe retenu avec la DSI : on ne lie jamais automatiquement. Quand un
demandeur s'apprête à soumettre une demande très proche d'une de ses demandes
encore ouvertes, on l'avertit AVANT la validation (il peut aller voir sa
demande en cours, ou créer quand même). Si la demande est créée malgré tout,
l'équipe en charge est prévenue (note interne + notification « doublon
probable ») et dispose d'un bouton « Lier » pré-rempli dans le détail du
ticket — la décision de rattacher (tech_extras.link_duplicate) reste humaine.

Hors périmètre : les bons de commande DAF (deux bons semblables sont souvent
légitimes).

Mesure de similarité : rapport difflib sur les textes normalisés (minuscules,
sans accents ni ponctuation). Seuil 0.82, fenêtre 30 jours.
"""
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from app import db
from app.models import (FormSubmission, FormSubmissionStatus, FormFieldType, Notification,
                        ServiceType, Ticket, TicketMessage, TicketStatus, User, UserRole)

WINDOW_DAYS = 30
THRESHOLD = 0.82
_CLOSED = (TicketStatus.DONE, TicketStatus.REFUSED)


def normalize(text):
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode()
    text = re.sub(r'[^a-z0-9]+', ' ', text.lower())
    return text.strip()


def similarity(a, b):
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _score(title, description, other_title, other_description):
    s = similarity(title, other_title)
    if description and other_description and len(normalize(description)) >= 20:
        s = max(s, similarity(description, other_description))
    return s


def _service_value(svc):
    return getattr(svc, 'value', str(svc)) if svc is not None else None


def similar_open_tickets(author_id, title, description='', target_service=None,
                         exclude_uid=None, before=None, threshold=THRESHOLD):
    """[(ticket, score)] des tickets ouverts du même demandeur ressemblant à la
    demande décrite, hors DAF, créés dans les WINDOW_DAYS derniers jours."""
    if not author_id or not (title or description):
        return []
    if _service_value(target_service) == ServiceType.DAF.value:
        return []
    since = (before or datetime.utcnow()) - timedelta(days=WINDOW_DAYS)
    q = Ticket.query.filter(Ticket.author_id == author_id,
                            Ticket.status.notin_(_CLOSED),
                            Ticket.target_service != ServiceType.DAF,
                            Ticket.created_at >= since)
    if target_service is not None:
        q = q.filter(Ticket.target_service == target_service)
    if before is not None:
        q = q.filter(Ticket.created_at < before)
    out = []
    for t in q.all():
        if exclude_uid and t.uid_public == exclude_uid:
            continue
        s = _score(title, description, t.title, t.description)
        if s >= threshold:
            out.append((t, s))
    out.sort(key=lambda x: (-x[1], -(x[0].id or 0)))
    return out


def submission_text(form_def, data):
    """Texte comparable d'une soumission : valeurs des champs (hors fichiers),
    dans l'ordre du formulaire."""
    parts = []
    for field in form_def.fields:
        if field.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE):
            continue
        v = data.get(field.name)
        if isinstance(v, (list, tuple)):
            v = ', '.join(str(x) for x in v)
        if v not in (None, '', False):
            parts.append(str(v))
    return '\n'.join(parts)


def _submission_is_open(sub):
    if sub.status == FormSubmissionStatus.IN_PROGRESS:
        return True
    if sub.status == FormSubmissionStatus.REFUSED:
        return False
    ids = sub.get_ticket_ids() if hasattr(sub, 'get_ticket_ids') else []
    if not ids:
        return False
    return Ticket.query.filter(Ticket.id.in_(ids), Ticket.status.notin_(_CLOSED)).count() > 0


def similar_open_submissions(author_id, form_def, data, threshold=THRESHOLD):
    """[(submission, score)] des soumissions encore ouvertes du même demandeur,
    sur le même formulaire, dont les réponses ressemblent à `data`."""
    text = submission_text(form_def, data)
    if not author_id or len(normalize(text)) < 10:
        return []
    since = datetime.utcnow() - timedelta(days=WINDOW_DAYS)
    subs = FormSubmission.query.filter(FormSubmission.author_id == author_id,
                                       FormSubmission.form_definition_id == form_def.id,
                                       FormSubmission.status != FormSubmissionStatus.REFUSED,
                                       FormSubmission.created_at >= since).all()
    out = []
    for sub in subs:
        if not _submission_is_open(sub):
            continue
        s = similarity(text, submission_text(form_def, sub.get_data()))
        if s >= threshold:
            out.append((sub, s))
    out.sort(key=lambda x: (-x[1], -(x[0].id or 0)))
    return out


def form_data_to_dict(form_def, form):
    """request.form -> dict comparable (même forme que FormSubmission.get_data())."""
    data = {}
    for field in form_def.fields:
        if field.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE):
            continue
        if field.field_type == FormFieldType.MULTI_SELECT:
            data[field.name] = form.getlist(field.name)
        elif field.field_type == FormFieldType.CHECKBOX:
            data[field.name] = bool(form.get(field.name))
        else:
            data[field.name] = (form.get(field.name) or '').strip()
    return data


def suspected_for(ticket):
    """Doublons probables d'un ticket (pour le détail) : tickets ouverts plus
    anciens du même demandeur vers le même service, non encore liés."""
    if ticket is None or ticket.parent_id is not None or ticket.status in _CLOSED:
        return []
    return [t for t, _ in similar_open_tickets(ticket.author_id, ticket.title, ticket.description,
                                               target_service=ticket.target_service,
                                               exclude_uid=ticket.uid_public, before=ticket.created_at)
            if t.parent_id is None]


def _team_for(target_service):
    val = _service_value(target_service)
    names = {val}
    try:
        names.add(ServiceType(val).name)
    except Exception:
        pass
    team = []
    for u in User.query.filter(User.role.in_([UserRole.SOLVER, UserRole.MANAGER, UserRole.DIRECTEUR, UserRole.ADMIN])).all():
        if u.role == UserRole.ADMIN or names & set(u.get_allowed_services() or []):
            team.append(u)
    return team


def signal_possible_duplicates(ticket, link_url=None):
    """À la création : si le ticket ressemble à une demande ouverte du même
    demandeur, note interne sur le ticket + notification à l'équipe. Ne lie
    rien. Retourne la liste des tickets suspects."""
    suspects = suspected_for(ticket)
    if not suspects:
        return []
    refs = ', '.join(f"#{t.uid_public}" for t in suspects[:3])
    db.session.add(TicketMessage(
        content=f"Doublon probable : ce ticket ressemble à {refs} (même demandeur, demande similaire). "
                "Vérifiez et liez-le au ticket maître si c'est la même demande (carte « Tickets liés »).",
        ticket=ticket, author=None, is_internal=True))
    for u in _team_for(ticket.target_service):
        db.session.add(Notification(user=u, category='warning',
                                    message=f"Doublon probable : {ticket.uid_public} ressemble à {refs}.",
                                    link=link_url))
    return suspects
