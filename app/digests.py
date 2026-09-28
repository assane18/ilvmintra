"""Données des e-mails récapitulatifs (résumé quotidien, récap hebdomadaire
des managers). Logique pure (pas de Flask request), utilisée par les scripts
cron de scripts/ et testable en isolation.
"""
from datetime import datetime, timedelta

from app.models import (Ticket, TicketStatus, FormSubmission, FormSubmissionStatus,
                        Notification, User, UserRole, ServiceType)
from app.decorators import can_validate_step


def pending_validations_for(user):
    """Tickets et soumissions en attente de la validation de `user` — même
    éligibilité que le tableau de bord manager (tickets._can_validate_ticket)
    et que la liste des formulaires à valider (forms.list_to_validate)."""
    from app.routes.tickets import _can_validate_ticket  # import tardif : module lourd
    tickets = [t for t in Ticket.query.filter(Ticket.status.in_([
        TicketStatus.VALIDATION_N1, TicketStatus.VALIDATION_N2,
        TicketStatus.VALIDATION_DAF_MANAGER, TicketStatus.DAF_SIGNATURE])).all()
        if _can_validate_ticket(user, t)]
    submissions = [s for s in FormSubmission.query.filter_by(status=FormSubmissionStatus.IN_PROGRESS).all()
                   if s.current_step and can_validate_step(user, s.current_step, s)]
    return tickets, submissions


def managed_service_enums(user):
    allowed = user.get_allowed_services() or []
    if 'GS-DRH' in allowed:
        allowed = list(allowed) + ['DRH']
    return [s for s in ServiceType if s.value in allowed or s.name in allowed]


def weekly_manager_summary(user, now=None):
    """Contenu du récap hebdo d'un manager/directeur : validations en attente
    (avec ancienneté), demandes reçues sur ses services dans les 7 derniers
    jours, tickets en retard sur ses services. None si rien à dire."""
    now = now or datetime.now()
    week_ago = now - timedelta(days=7)
    tickets, submissions = pending_validations_for(user)
    services = managed_service_enums(user)
    received, stale = [], []
    if services:
        received = Ticket.query.filter(Ticket.target_service.in_(services),
                                       Ticket.created_at >= week_ago).order_by(Ticket.created_at.desc()).all()
        stale = [t for t in Ticket.query.filter(Ticket.target_service.in_(services),
                                                Ticket.status.in_([TicketStatus.PENDING, TicketStatus.IN_PROGRESS])).all()
                 if t.is_stale]
        stale.sort(key=lambda t: t.created_at)
    if not (tickets or submissions or stale):
        return None
    return {
        'pending_tickets': sorted(tickets, key=lambda t: t.created_at),
        'pending_submissions': sorted(submissions, key=lambda s: s.created_at),
        'received_week': received,
        'stale': stale,
        'services': [s.value for s in services],
        'now': now,
    }


def weekly_digest_recipients():
    return User.query.filter(User.role.in_([UserRole.MANAGER, UserRole.DIRECTEUR]),
                             User.email.isnot(None)).all()


def daily_digest_for(user, now=None):
    """Notifications in-app des dernières 24 h d'un utilisateur en mode
    « résumé quotidien » (ses e-mails immédiats sont retenus par send_email)."""
    now = now or datetime.utcnow()
    return Notification.query.filter(Notification.user_id == user.id,
                                     Notification.timestamp >= now - timedelta(hours=24))\
        .order_by(Notification.timestamp.desc()).all()


def daily_digest_recipients():
    return User.query.filter(User.email_mode == 'daily', User.email.isnot(None)).all()
