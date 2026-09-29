"""Rendez-vous sur ticket — proposition par l'équipe, réponse du demandeur.

Circuit (décisions utilisateur du 2026-09-29) :
- Toute l'équipe du service cible (SOLVER/MANAGER/DIRECTEUR habilités, ADMIN)
  peut proposer un créneau, même si le ticket n'est pas encore pris en charge,
  ou le « fixer directement » (sans confirmation, le demandeur est informé).
- Le demandeur accepte, refuse, ou transmet jusqu'à 3 disponibilités ; l'équipe
  en retient une d'un clic ou en propose une autre.
- L'équipe peut annuler à tout moment et reproposer.
- Rappel le jour même à 9h aux deux parties (scripts/rappel_rdv.py).
Le RDV accepté est recopié dans Ticket.rdv_date : planning et écran mural
continuent de fonctionner sans changement.
"""
import json
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.emails import send_rdv_email
from app.models import Appointment, Ticket, TicketMessage, TicketStatus
from app.routes.tickets import create_notification, get_paris_time, get_service_emails, nocache
from app.routes.tech_extras import can_manage

rdv_bp = Blueprint('rdv', __name__)


@rdv_bp.app_context_processor
def _rdv_context():
    return {'current_appointment': current_appointment}

_CLOSED = (TicketStatus.DONE, TicketStatus.REFUSED)
_OPEN_APPOINTMENT = ('proposed', 'accepted', 'counter')


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def current_appointment(ticket):
    """Dernier rendez-vous encore « vivant » (proposé, accepté ou en attente
    d'une nouvelle proposition après disponibilités), sinon None."""
    for a in reversed(ticket.appointments or []):
        if a.status in _OPEN_APPOINTMENT:
            return a
    return None


def is_requester(ticket, user):
    return user.id in (ticket.author_id, getattr(ticket, 'created_by_id', None))


def _parse_dt(raw):
    try:
        return datetime.strptime((raw or '').strip(), '%Y-%m-%dT%H:%M')
    except ValueError:
        return None


def _fmt(dt):
    return dt.strftime('%d/%m/%Y à %H:%M')


def _view(ticket):
    return redirect(url_for('tickets.view_ticket', ticket_uid=ticket.uid_public))


def _link(ticket):
    """Lien in-app vers le ticket. Hors requête (script cron de rappel), url_for
    n'est pas disponible : on reconstruit le chemin avec le préfixe applicatif."""
    try:
        return url_for('tickets.view_ticket', ticket_uid=ticket.uid_public)
    except RuntimeError:
        from flask import current_app
        root = (current_app.config.get('APPLICATION_ROOT') or '/intranet').rstrip('/')
        return f"{root}/tickets/view/{ticket.uid_public}"


def _team_recipients(ticket, appointment):
    """Qui prévenir côté équipe d'une réponse du demandeur : la personne qui a
    proposé, le technicien en charge, sinon tout le service."""
    users = []
    for u in (appointment.proposed_by if appointment else None, ticket.solver):
        if u and u not in users:
            users.append(u)
    return users


def _close_pending(ticket, exclude_id=None):
    for a in ticket.appointments or []:
        if a.id != exclude_id and a.status in ('proposed', 'counter'):
            a.status = 'cancelled'


# ---------------------------------------------------------------------------
#  Équipe : proposer / fixer / annuler
# ---------------------------------------------------------------------------

@rdv_bp.route('/rdv/<int:ticket_id>/propose', methods=['POST'])
@login_required
@nocache
def propose(ticket_id):
    t = Ticket.query.get_or_404(ticket_id)
    if not can_manage(t, current_user):
        flash("Seule l'équipe du service concerné peut proposer un rendez-vous.", 'danger')
        return _view(t)
    if t.status in _CLOSED:
        flash("Ticket terminé : plus de rendez-vous possible.", 'warning')
        return _view(t)
    when = _parse_dt(request.form.get('starts_at'))
    if not when:
        flash("Date et heure du rendez-vous invalides.", 'danger')
        return _view(t)
    if when < datetime.now() - timedelta(minutes=5):
        flash("Le rendez-vous doit être dans le futur.", 'danger')
        return _view(t)

    direct = bool(request.form.get('direct'))
    message = (request.form.get('message') or '').strip()[:2000] or None
    # Une nouvelle proposition remplace la précédente encore en attente.
    previous = current_appointment(t)
    _close_pending(t)
    if previous and previous.status == 'accepted' and not direct:
        # Reproposition alors qu'un RDV était confirmé : on l'annule explicitement.
        previous.status = 'cancelled'
        t.rdv_date = None

    a = Appointment(ticket=t, proposed_by=current_user, starts_at=when, message=message,
                    status='accepted' if direct else 'proposed', direct=direct,
                    responded_at=get_paris_time() if direct else None)
    db.session.add(a)

    label = _fmt(when)
    if direct:
        t.rdv_date = when
        content = f"📅 Rendez-vous fixé le {label} par {current_user.fullname}." + (f"\n{message}" if message else "")
        notif = f"Rendez-vous fixé le {label} ({t.uid_public})"
        subject = f"[Rendez-vous] {t.title} — le {label}"
        intro = (f"<p>Un rendez-vous a été fixé pour votre demande <strong>#{t.uid_public}</strong> "
                 f"le <strong>{label}</strong>.</p>" + (f"<p>{message}</p>" if message else ""))
        buttons = None
    else:
        content = f"📅 Rendez-vous proposé le {label} par {current_user.fullname} — en attente de votre réponse." + (f"\n{message}" if message else "")
        notif = f"Rendez-vous proposé le {label} : merci de répondre ({t.uid_public})"
        subject = f"[Rendez-vous à confirmer] {t.title} — le {label}"
        intro = (f"<p>Le service vous propose un rendez-vous pour votre demande <strong>#{t.uid_public}</strong> "
                 f"le <strong>{label}</strong>.</p>" + (f"<p>{message}</p>" if message else "") +
                 "<p>Merci de répondre en un clic :</p>")
        buttons = [
            ('✅ J\'accepte', url_for('rdv.quick_respond', ticket_id=t.id, action='accept', _external=True), '#059669'),
            ('📆 Proposer mes disponibilités', url_for('tickets.view_ticket', ticket_uid=t.uid_public, _external=True, _anchor='rdv'), '#2563eb'),
            ('❌ Je refuse', url_for('rdv.quick_respond', ticket_id=t.id, action='refuse', _external=True), '#dc2626'),
        ]
    db.session.add(TicketMessage(content=content, ticket=t, author=current_user))
    if t.author:
        create_notification(t.author, notif, 'info', _link(t))
        send_rdv_email(t.author, subject, intro, t, buttons=buttons)
    db.session.commit()
    flash("Rendez-vous fixé." if direct else "Rendez-vous proposé, le demandeur est prévenu.", 'success')
    return _view(t)


@rdv_bp.route('/rdv/<int:ticket_id>/cancel', methods=['POST'])
@login_required
@nocache
def cancel(ticket_id):
    t = Ticket.query.get_or_404(ticket_id)
    if not can_manage(t, current_user):
        flash("Seule l'équipe du service concerné peut annuler un rendez-vous.", 'danger')
        return _view(t)
    a = current_appointment(t)
    if not a:
        flash("Aucun rendez-vous à annuler.", 'warning')
        return _view(t)
    reason = (request.form.get('reason') or '').strip()[:2000]
    a.status = 'cancelled'
    a.response_comment = (a.response_comment or '')
    t.rdv_date = None
    label = _fmt(a.starts_at)
    content = f"📅 Rendez-vous du {label} annulé par {current_user.fullname}." + (f"\nMotif : {reason}" if reason else "")
    db.session.add(TicketMessage(content=content, ticket=t, author=current_user))
    if t.author:
        create_notification(t.author, f"Rendez-vous du {label} annulé ({t.uid_public})", 'warning', _link(t))
        send_rdv_email(t.author, f"[Rendez-vous annulé] {t.title}",
                       f"<p>Le rendez-vous du <strong>{label}</strong> pour votre demande <strong>#{t.uid_public}</strong> est annulé."
                       + (f" Motif : {reason}" if reason else "") + " Une nouvelle date vous sera proposée.</p>", t)
    db.session.commit()
    flash("Rendez-vous annulé. Vous pouvez en proposer un autre.", 'success')
    return _view(t)


# ---------------------------------------------------------------------------
#  Demandeur : accepter / refuser / disponibilités
# ---------------------------------------------------------------------------

def _apply_response(t, a, action, comment='', slots=None):
    """Applique la réponse du demandeur et prévient l'équipe. Retourne le message flash."""
    a.responded_at = get_paris_time()
    a.response_comment = comment or None
    label = _fmt(a.starts_at)
    if action == 'accept':
        a.status = 'accepted'
        t.rdv_date = a.starts_at
        content = f"✅ Rendez-vous du {label} accepté par {current_user.fullname}."
        notif, subject = f"Rendez-vous du {label} accepté ({t.uid_public})", f"[Rendez-vous confirmé] {t.title} — le {label}"
        intro = f"<p><strong>{current_user.fullname}</strong> a accepté le rendez-vous du <strong>{label}</strong> pour le ticket <strong>#{t.uid_public}</strong>.</p>"
        msg = "Rendez-vous confirmé."
    elif action == 'refuse':
        a.status = 'refused'
        t.rdv_date = None
        content = f"❌ Rendez-vous du {label} refusé par {current_user.fullname}." + (f"\n{comment}" if comment else "")
        notif, subject = f"Rendez-vous du {label} refusé ({t.uid_public})", f"[Rendez-vous refusé] {t.title}"
        intro = (f"<p><strong>{current_user.fullname}</strong> a refusé le rendez-vous du <strong>{label}</strong> "
                 f"(ticket <strong>#{t.uid_public}</strong>).</p>" + (f"<p>{comment}</p>" if comment else "") +
                 "<p>Vous pouvez proposer une autre date depuis le ticket.</p>")
        msg = "Rendez-vous refusé, le service est prévenu."
    else:  # counter : disponibilités
        a.status = 'counter'
        a.slots_json = json.dumps([s.isoformat(timespec='minutes') for s in (slots or [])])
        t.rdv_date = None
        lines = "\n".join(f"- {_fmt(s)}" for s in (slots or []))
        content = f"📆 {current_user.fullname} ne peut pas le {label} et propose ses disponibilités :\n{lines}" + (f"\n{comment}" if comment else "")
        notif, subject = f"Disponibilités transmises pour un rendez-vous ({t.uid_public})", f"[Rendez-vous — disponibilités] {t.title}"
        intro = (f"<p><strong>{current_user.fullname}</strong> ne peut pas le <strong>{label}</strong> "
                 f"(ticket <strong>#{t.uid_public}</strong>) et propose :</p><ul>"
                 + "".join(f"<li>{_fmt(s)}</li>" for s in (slots or [])) + "</ul>"
                 + (f"<p>{comment}</p>" if comment else "") +
                 "<p>Retenez un créneau ou proposez une autre date depuis le ticket.</p>")
        msg = "Vos disponibilités ont été transmises au service."
    db.session.add(TicketMessage(content=content, ticket=t, author=current_user))
    recipients = _team_recipients(t, a)
    for u in recipients:
        create_notification(u, notif, 'success' if action == 'accept' else 'warning', _link(t))
        send_rdv_email(u, subject, intro, t)
    if not recipients:
        emails = get_service_emails(t.target_service)
        if emails:
            send_rdv_email(None, subject, intro, t, recipients_emails=emails)
    return msg


@rdv_bp.route('/rdv/<int:ticket_id>/respond', methods=['POST'])
@login_required
@nocache
def respond(ticket_id):
    t = Ticket.query.get_or_404(ticket_id)
    if not is_requester(t, current_user):
        flash("Seul le demandeur peut répondre à ce rendez-vous.", 'danger')
        return _view(t)
    a = current_appointment(t)
    if not a or a.status != 'proposed':
        flash("Aucun rendez-vous en attente de votre réponse.", 'warning')
        return _view(t)
    action = request.form.get('action')
    comment = (request.form.get('comment') or '').strip()[:2000]
    if action == 'counter':
        slots = [d for d in (_parse_dt(request.form.get(f'slot{i}')) for i in (1, 2, 3)) if d]
        if not slots:
            flash("Indiquez au moins une disponibilité.", 'warning')
            return _view(t)
        msg = _apply_response(t, a, 'counter', comment, slots)
    elif action in ('accept', 'refuse'):
        msg = _apply_response(t, a, action, comment)
    else:
        flash("Réponse inconnue.", 'danger')
        return _view(t)
    db.session.commit()
    flash(msg, 'success')
    return _view(t)


@rdv_bp.route('/rdv/<int:ticket_id>/respond/<action>')
@login_required
@nocache
def quick_respond(ticket_id, action):
    """Boutons de l'e-mail : accepter en un clic ; refuser renvoie sur le ticket
    pour donner un motif / des disponibilités."""
    t = Ticket.query.get_or_404(ticket_id)
    if not is_requester(t, current_user):
        flash("Seul le demandeur peut répondre à ce rendez-vous.", 'danger')
        return _view(t)
    a = current_appointment(t)
    if not a or a.status != 'proposed':
        flash("Ce rendez-vous n'est plus en attente de réponse.", 'warning')
        return _view(t)
    if action == 'accept':
        flash(_apply_response(t, a, 'accept'), 'success')
        db.session.commit()
    else:
        flash("Indiquez ci-dessous vos disponibilités ou le motif de votre refus.", 'warning')
    return redirect(url_for('tickets.view_ticket', ticket_uid=t.uid_public, _anchor='rdv'))


@rdv_bp.route('/rdv/<int:ticket_id>/pick/<int:appointment_id>/<int:index>', methods=['POST'])
@login_required
@nocache
def pick_slot(ticket_id, appointment_id, index):
    """L'équipe retient d'un clic une des disponibilités du demandeur : cela
    équivaut à fixer directement le rendez-vous à ce créneau."""
    t = Ticket.query.get_or_404(ticket_id)
    if not can_manage(t, current_user):
        flash("Seule l'équipe du service concerné peut retenir un créneau.", 'danger')
        return _view(t)
    a = Appointment.query.get_or_404(appointment_id)
    slots = a.get_slots()
    if a.ticket_id != t.id or a.status != 'counter' or not (0 <= index < len(slots)):
        flash("Créneau introuvable.", 'warning')
        return _view(t)
    when = slots[index]
    a.status = 'cancelled'
    new = Appointment(ticket=t, proposed_by=current_user, starts_at=when, status='accepted', direct=True,
                      responded_at=get_paris_time(), message="Créneau retenu parmi vos disponibilités.")
    db.session.add(new)
    t.rdv_date = when
    label = _fmt(when)
    db.session.add(TicketMessage(content=f"📅 Rendez-vous fixé le {label} (créneau proposé par le demandeur, retenu par {current_user.fullname}).", ticket=t, author=current_user))
    if t.author:
        create_notification(t.author, f"Rendez-vous fixé le {label} ({t.uid_public})", 'success', _link(t))
        send_rdv_email(t.author, f"[Rendez-vous confirmé] {t.title} — le {label}",
                       f"<p>Le service a retenu votre disponibilité : rendez-vous le <strong>{label}</strong> pour la demande <strong>#{t.uid_public}</strong>.</p>", t)
    db.session.commit()
    flash(f"Rendez-vous fixé le {label}.", 'success')
    return _view(t)


# ---------------------------------------------------------------------------
#  Rappel du jour (scripts/rappel_rdv.py, cron 9h)
# ---------------------------------------------------------------------------

def due_reminders(now=None):
    """Rendez-vous acceptés prévus aujourd'hui et pas encore rappelés."""
    now = now or datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return Appointment.query.filter(Appointment.status == 'accepted', Appointment.reminder_sent_at.is_(None),
                                    Appointment.starts_at >= start, Appointment.starts_at < end)\
        .order_by(Appointment.starts_at).all()


def send_reminders(now=None):
    """Envoie le rappel du jour aux deux parties (demandeur + équipe). Retourne
    le nombre de rendez-vous rappelés."""
    now = now or datetime.now()
    count = 0
    for a in due_reminders(now):
        t = a.ticket
        if not t or t.status in _CLOSED:
            a.reminder_sent_at = now
            continue
        label = a.starts_at.strftime('%H:%M')
        parties = [u for u in (t.author, a.proposed_by, t.solver) if u]
        seen = set()
        for u in parties:
            if u.id in seen:
                continue
            seen.add(u.id)
            create_notification(u, f"Rappel : rendez-vous aujourd'hui à {label} ({t.uid_public})", 'info', _link(t))
            send_rdv_email(u, f"[Rappel] Rendez-vous aujourd'hui à {label} — {t.title}",
                           f"<p>Rappel : rendez-vous <strong>aujourd'hui à {label}</strong> pour la demande "
                           f"<strong>#{t.uid_public}</strong> ({t.title}).</p>"
                           + (f"<p>Avec : {', '.join(x.fullname for x in parties if x.id != u.id)}</p>" if len(parties) > 1 else ""),
                           t, kind='digest')
        a.reminder_sent_at = now
        count += 1
    db.session.commit()
    return count
