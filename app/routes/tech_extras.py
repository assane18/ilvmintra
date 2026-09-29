"""Lot 6 — « Espace Tech au quotidien ».

Blueprint séparé de ``tickets.py`` (chantiers parallèles sur ce fichier),
enregistré sous le préfixe ``/tickets`` et qui en RÉUTILISE les helpers
(``check_permission``, ``create_notification``, ``safe_role_str``,
``get_paris_time``) ainsi que les e-mails de ``app/emails.py``.

Quatre livrables :

1. Notes internes du chat (``TicketMessage.is_internal``) : visibles et
   rédigeables uniquement par l'équipe qui gère le ticket (jamais par le
   demandeur, ni dans la page, ni dans les e-mails/notifications).
2. Pièces jointes du chat (``TicketMessage.attachments_json``) : fichiers
   ``uploads/tickets/<uid>/msg_<id>_<nom>`` — demandeur ET équipe.
3. Tickets liés / fusion de doublons (``Ticket.parent_id``) : rattachement,
   détachement, clôture en cascade, diffusion d'un message aux doublons.
4. Planning hebdomadaire des interventions (``rdv_date``), généralisation du
   formulaire de RDV (jusqu'ici réservé à Imago) à tout ticket assigné.

``tickets.py::view_ticket`` (bloc MESSAGERIE) délègue ici à
``post_chat_message`` et ``tickets.py::close_ticket`` à
``close_duplicates_of`` — imports paresseux côté tickets.py pour éviter le
cycle (ce module importe tickets.py au chargement).
"""
import json
import os
import shutil
from datetime import datetime, timedelta

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db
from app.emails import send_closure_notification, send_message_notification
from app.models import ServiceType, Ticket, TicketMessage, TicketStatus
from app.routes.tickets import (check_permission, create_notification,
                                get_paris_time, nocache, safe_role_str)
from app.routes.wallboard import allowed_service_values

tech_extras_bp = Blueprint('tech_extras', __name__)

TEAM_ROLES = ['SOLVER', 'MANAGER', 'DIRECTEUR', 'ADMIN']

# Pièces jointes du chat : extensions acceptées et poids total maximal (20 Mo,
# aligné sur MAX_CONTENT_LENGTH de config.py).
CHAT_ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'webp', 'pdf', 'docx', 'xlsx'}
CHAT_MAX_TOTAL_BYTES = 20 * 1024 * 1024

_CLOSED_STATUSES = (TicketStatus.DONE, TicketStatus.REFUSED)


# ---------------------------------------------------------------------------
#  Helpers droits
# ---------------------------------------------------------------------------

def _service_tags(value):
    """Toutes les écritures possibles d'un service (nom d'enum, valeur, brut)
    — même logique « robuste » que tickets.py::view_ticket."""
    tags = set()
    if value is None:
        return tags
    if hasattr(value, 'value'):
        tags.add(str(value.value))
    if hasattr(value, 'name'):
        tags.add(str(value.name))
    tags.add(str(value))
    # La valeur brute peut être une valeur d'enum : on ajoute alors son nom.
    for s in ServiceType:
        if s.value == str(value):
            tags.add(s.name)
    return tags


def can_manage(ticket, user):
    """Réplique de ``can_manage_ticket`` de tickets.py::view_ticket : ADMIN,
    ou SOLVER/MANAGER/DIRECTEUR compétent sur le service cible — jamais
    l'auteur (sauf ADMIN)."""
    role = safe_role_str(user)
    if 'ADMIN' in role:
        return True
    if ticket.author_id == user.id:
        return False
    if not any(r in role for r in ['SOLVER', 'MANAGER', 'DIRECTEUR']):
        return False
    mine = set()
    for s in (user.get_allowed_services() or []):
        mine |= _service_tags(s)
    return not _service_tags(ticket.target_service).isdisjoint(mine)


def can_plan(ticket, user):
    """Qui peut fixer la date d'intervention : le technicien assigné ou un ADMIN."""
    return ticket.solver_id == user.id or 'ADMIN' in safe_role_str(user)


def _view(ticket):
    return redirect(url_for('tickets.view_ticket', ticket_uid=ticket.uid_public))


# ---------------------------------------------------------------------------
#  Pièces jointes du chat
# ---------------------------------------------------------------------------

def _ticket_upload_dir(ticket):
    return os.path.join(current_app.config['UPLOAD_FOLDER'], 'tickets', ticket.uid_public)


def _ext(filename):
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''


def _human_size(n):
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n // 1024} Ko"
    return f"{n / (1024 * 1024):.1f} Mo"


def _incoming_files():
    """Fichiers réellement fournis dans le champ ``attachments`` (multiple)."""
    return [f for f in request.files.getlist('attachments') if f and f.filename]


def validate_chat_files(files):
    """Retourne un message d'erreur (str) ou None si tout est acceptable."""
    total = 0
    for f in files:
        if _ext(f.filename) not in CHAT_ALLOWED_EXT:
            return (f"Fichier « {f.filename} » refusé : formats acceptés "
                    "PNG, JPG, WEBP, PDF, DOCX, XLSX.")
        f.stream.seek(0, os.SEEK_END)
        total += f.stream.tell()
        f.stream.seek(0)
    if total > CHAT_MAX_TOTAL_BYTES:
        return f"Pièces jointes trop volumineuses ({_human_size(total)}) : 20 Mo maximum au total."
    return None


def save_chat_files(msg, files):
    """Enregistre les fichiers sous uploads/tickets/<uid>/msg_<id>_<nom> et
    renseigne ``msg.attachments_json``. ``msg`` doit déjà avoir un id (flush)."""
    if not files:
        return []
    folder = _ticket_upload_dir(msg.ticket)
    os.makedirs(folder, exist_ok=True)
    names = []
    for f in files:
        safe = secure_filename(f.filename) or 'fichier'
        name = f"msg_{msg.id}_{safe}"
        f.save(os.path.join(folder, name))
        names.append(name)
    msg.attachments_json = json.dumps(names)
    return names


def _copy_attachments(src_msg, dst_msg):
    """Diffusion aux doublons : copie physique des fichiers du message maître
    dans le dossier du doublon (préfixe = id du nouveau message)."""
    names = src_msg.get_attachments()
    if not names:
        return
    src_dir = _ticket_upload_dir(src_msg.ticket)
    dst_dir = _ticket_upload_dir(dst_msg.ticket)
    os.makedirs(dst_dir, exist_ok=True)
    out = []
    prefix = f"msg_{src_msg.id}_"
    for n in names:
        base = n[len(prefix):] if n.startswith(prefix) else n
        new_name = f"msg_{dst_msg.id}_{base}"
        try:
            shutil.copyfile(os.path.join(src_dir, n), os.path.join(dst_dir, new_name))
            out.append(new_name)
        except OSError:
            continue
    dst_msg.attachments_json = json.dumps(out)


_ICONS = {'pdf': 'file-text', 'docx': 'file-text', 'xlsx': 'file-spreadsheet',
          'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'webp': 'image'}


@tech_extras_bp.app_template_global()
def chat_attachment_info(ticket, name):
    """Pour les templates : {name, label, url, size, icon, is_image} d'une
    pièce jointe de message (le nom stocké garde le préfixe msg_<id>_, le
    libellé affiché l'enlève)."""
    label = name.split('_', 2)[2] if name.startswith('msg_') and name.count('_') >= 2 else name
    path = os.path.join(_ticket_upload_dir(ticket), name)
    try:
        size = _human_size(os.path.getsize(path))
    except OSError:
        size = ''
    ext = _ext(name)
    return {
        'name': name, 'label': label, 'size': size,
        'url': url_for('static', filename=f'uploads/tickets/{ticket.uid_public}/{name}'),
        'icon': _ICONS.get(ext, 'paperclip'),
        'is_image': ext in ('png', 'jpg', 'jpeg', 'webp'),
    }


# ---------------------------------------------------------------------------
#  Chat : publication d'un message (appelé par tickets.py::view_ticket)
# ---------------------------------------------------------------------------

def _notify_message(recipient, ticket, content, category, label):
    if not recipient:
        return
    create_notification(recipient, f"{label} {ticket.uid_public}", category,
                        url_for('tickets.view_ticket', ticket_uid=ticket.uid_public))
    send_message_notification(ticket, content, recipient)


def post_chat_message(ticket, can_manage_ticket):
    """Traite le POST du formulaire de message de la page détail.

    - ``message`` : texte (facultatif si des fichiers sont joints) ;
    - ``attachments`` : fichiers (PNG/JPG/WEBP/PDF/DOCX/XLSX, 20 Mo au total) ;
    - ``is_internal`` : note interne — ignorée si l'utilisateur ne gère pas le
      ticket (donc jamais pour le demandeur) ;
    - ``broadcast`` : diffusion aux doublons ouverts (équipe, message non interne).

    Retourne toujours une redirection vers la page du ticket.
    """
    content = (request.form.get('message') or '').strip()
    files = _incoming_files()
    if not content and not files:
        return _view(ticket)

    err = validate_chat_files(files)
    if err:
        flash(err, 'danger')
        return _view(ticket)

    is_internal = bool(request.form.get('is_internal')) and can_manage_ticket
    broadcast = bool(request.form.get('broadcast')) and can_manage_ticket and not is_internal
    is_author = (ticket.author_id == current_user.id)

    msg = TicketMessage(content=content or "(pièce jointe)", ticket=ticket,
                        author=current_user, is_internal=is_internal)
    db.session.add(msg)
    db.session.flush()  # id nécessaire pour nommer les fichiers
    save_chat_files(msg, files)

    link = url_for('tickets.view_ticket', ticket_uid=ticket.uid_public)
    if is_internal:
        # Note interne : on ne prévient QUE l'équipe (technicien en charge),
        # jamais le demandeur.
        if ticket.solver and ticket.solver_id != current_user.id:
            _notify_message(ticket.solver, ticket, f"[Note interne] {msg.content}", 'info', "Note interne sur")
    elif is_author:
        # Cas 1 : le demandeur écrit -> on prévient le technicien (s'il y en a un)
        if ticket.solver:
            _notify_message(ticket.solver, ticket, msg.content, 'warning', "Message sur")
    else:
        # Cas 2 : l'équipe écrit -> on prévient le demandeur
        _notify_message(ticket.author, ticket, msg.content, 'success', "Réponse sur")

    if broadcast:
        for dup in ticket.open_duplicates():
            copy = TicketMessage(
                content=f"[Diffusé depuis le ticket maître #{ticket.uid_public}]\n{msg.content}",
                ticket=dup, author=current_user, is_internal=False)
            db.session.add(copy)
            db.session.flush()
            _copy_attachments(msg, copy)
            if dup.author_id != current_user.id:
                _notify_message(dup.author, dup, copy.content, 'success', "Réponse sur")

    db.session.commit()
    return redirect(link)


# ---------------------------------------------------------------------------
#  Tickets liés / doublons
# ---------------------------------------------------------------------------

def _find_master(uid):
    """Accepte « 20260929-003 », « #20260929-003 » ou un id numérique."""
    uid = (uid or '').strip().lstrip('#')
    if not uid:
        return None
    t = Ticket.query.filter_by(uid_public=uid).first()
    if t is None and uid.isdigit():
        t = Ticket.query.get(int(uid))
    return t


def link_refusal_reason(ticket, master):
    """Règles de rattachement — retourne le motif de refus ou None."""
    if master is None:
        return "Ticket maître introuvable."
    if master.id == ticket.id:
        return "Un ticket ne peut pas être son propre doublon."
    if master.get_safe_target_service() != ticket.get_safe_target_service():
        return "Le ticket maître doit viser le même service cible."
    if master.status in _CLOSED_STATUSES:
        return "Le ticket maître est déjà terminé ou refusé."
    if master.parent_id is not None:
        return f"Le ticket #{master.uid_public} est lui-même un doublon (maître : #{master.parent.uid_public})."
    if ticket.status in _CLOSED_STATUSES:
        return "Ce ticket est déjà terminé : rien à rattacher."
    if ticket.duplicates:
        return "Ce ticket est lui-même maître d'autres doublons : détachez-les d'abord."
    return None


@tech_extras_bp.route('/link/<int:ticket_id>', methods=['POST'])
@login_required
def link_duplicate(ticket_id):
    t = Ticket.query.get_or_404(ticket_id)
    if not can_manage(t, current_user):
        flash("Action réservée à l'équipe en charge du ticket.", 'danger')
        return _view(t)
    master = _find_master(request.form.get('master_uid'))
    reason = link_refusal_reason(t, master)
    if reason:
        flash(reason, 'danger')
        return _view(t)

    t.parent = master
    t.status = TicketStatus.IN_PROGRESS
    if master.solver_id:
        # Le doublon suit le technicien du maître (traitement unique).
        t.solver_id = master.solver_id
    if t.solver_id and t.assigned_at is None:
        t.assigned_at = get_paris_time()

    link_master = url_for('tickets.view_ticket', ticket_uid=master.uid_public)
    db.session.add(TicketMessage(
        content=f"Ce ticket est rattaché au ticket maître #{master.uid_public} : "
                "il sera traité et clôturé avec lui.",
        ticket=t, author=current_user))
    # Trace côté maître, en note interne (le demandeur du maître n'a pas à
    # connaître les autres demandeurs).
    db.session.add(TicketMessage(
        content=f"Le ticket #{t.uid_public} ({t.author_name}) a été rattaché comme doublon.",
        ticket=master, author=current_user, is_internal=True))
    create_notification(t.author,
                        f"Votre ticket {t.uid_public} est traité avec le ticket {master.uid_public}.",
                        'info', url_for('tickets.view_ticket', ticket_uid=t.uid_public))
    db.session.commit()
    flash(f"Ticket rattaché comme doublon de #{master.uid_public}.", 'success')
    return _view(t)


@tech_extras_bp.route('/unlink/<int:ticket_id>', methods=['POST'])
@login_required
def unlink_duplicate(ticket_id):
    t = Ticket.query.get_or_404(ticket_id)
    if not can_manage(t, current_user):
        flash("Action réservée à l'équipe en charge du ticket.", 'danger')
        return _view(t)
    if t.parent_id is None:
        flash("Ce ticket n'est rattaché à aucun ticket maître.", 'warning')
        return _view(t)
    master = t.parent
    t.parent = None
    db.session.add(TicketMessage(
        content=f"Ce ticket a été détaché du ticket maître #{master.uid_public} : "
                "il reprend un traitement indépendant.",
        ticket=t, author=current_user))
    db.session.add(TicketMessage(
        content=f"Le ticket #{t.uid_public} a été détaché (n'est plus un doublon).",
        ticket=master, author=current_user, is_internal=True))
    db.session.commit()
    flash("Ticket détaché.", 'success')
    return _view(t)


def close_duplicates_of(master, actor):
    """Clôture en cascade (appelée par tickets.py::close_ticket AVANT le
    commit) : chaque doublon encore ouvert reçoit le même ``closed_at``, un
    message système, une notification et l'e-mail de clôture."""
    closed = []
    for dup in master.open_duplicates():
        dup.status = TicketStatus.DONE
        dup.closed_at = master.closed_at
        db.session.add(TicketMessage(
            content=f"Clôturé automatiquement avec le ticket maître #{master.uid_public}.",
            ticket=dup, author=actor))
        create_notification(dup.author,
                            f"Votre ticket {dup.uid_public} a été traité et clôturé (avec le ticket {master.uid_public}).",
                            'success', url_for('tickets.view_ticket', ticket_uid=dup.uid_public))
        try:
            send_closure_notification(dup)
        except Exception:
            pass
        closed.append(dup)
    return closed


# ---------------------------------------------------------------------------
#  Planning d'interventions
# ---------------------------------------------------------------------------

@tech_extras_bp.route('/rdv/<int:ticket_id>', methods=['POST'])
@login_required
def set_intervention(ticket_id):
    """Fixe / modifie / efface la date d'intervention (``rdv_date``) d'un
    ticket assigné — technicien en charge ou ADMIN. Généralise l'ancien
    formulaire Imago (tickets.set_rdv, conservé) à tous les services."""
    t = Ticket.query.get_or_404(ticket_id)
    if not can_plan(t, current_user):
        flash("Seul le technicien en charge du ticket peut planifier l'intervention.", 'danger')
        return _view(t)
    if t.status in _CLOSED_STATUSES:
        flash("Ticket terminé : planification impossible.", 'warning')
        return _view(t)

    link = url_for('tickets.view_ticket', ticket_uid=t.uid_public)
    if request.form.get('clear'):
        t.rdv_date = None
        db.session.add(TicketMessage(content="Intervention déprogrammée.", ticket=t, author=current_user))
        create_notification(t.author, f"Intervention déprogrammée sur {t.uid_public}", 'warning', link)
        db.session.commit()
        flash("Intervention déprogrammée.", 'success')
        return _view(t)

    raw = (request.form.get('rdv_date') or '').strip()
    try:
        when = datetime.strptime(raw, '%Y-%m-%dT%H:%M')
    except ValueError:
        flash("Date d'intervention invalide.", 'danger')
        return _view(t)

    verb = "replanifiée" if t.rdv_date else "planifiée"
    t.rdv_date = when
    label = when.strftime('%d/%m/%Y à %H:%M')
    content = f"Intervention {verb} le {label}"
    db.session.add(TicketMessage(content=content, ticket=t, author=current_user))
    create_notification(t.author, f"Intervention planifiée le {label} ({t.uid_public})", 'info', link)
    if t.author_id != current_user.id:
        send_message_notification(t, content, t.author)
    db.session.commit()
    flash(f"Intervention {verb} le {label}.", 'success')
    return _view(t)


def _week_start(ref):
    """Lundi 00:00 de la semaine contenant ``ref`` (date ou datetime)."""
    d = ref.date() if isinstance(ref, datetime) else ref
    monday = d - timedelta(days=d.weekday())
    return datetime(monday.year, monday.month, monday.day)


def planning_week(user, ref=None, solver_id=None):
    """Tickets à ``rdv_date`` dans la semaine de ``ref`` (défaut : aujourd'hui),
    dans le périmètre de services de ``user`` (ADMIN = tous), répartis par jour
    lundi → dimanche."""
    start = _week_start(ref or datetime.now())
    end = start + timedelta(days=7)
    q = Ticket.query.filter(Ticket.rdv_date >= start, Ticket.rdv_date < end)
    allowed = allowed_service_values(user)
    if allowed is not None:
        members = [s for s in ServiceType if s.value in allowed]
        q = q.filter(Ticket.target_service.in_(members)) if members else q.filter(False)
    if solver_id:
        q = q.filter(Ticket.solver_id == solver_id)
    tickets = q.order_by(Ticket.rdv_date.asc()).all()

    days = []
    for i in range(7):
        day = start + timedelta(days=i)
        days.append({
            'date': day,
            'is_today': day.date() == datetime.now().date(),
            'tickets': [t for t in tickets if t.rdv_date.date() == day.date()],
        })
    solvers = {}
    for t in tickets:
        if t.solver:
            solvers[t.solver_id] = t.solver
    return {
        'start': start, 'end': end - timedelta(days=1),
        'prev': (start - timedelta(days=7)).strftime('%Y-%m-%d'),
        'next': (start + timedelta(days=7)).strftime('%Y-%m-%d'),
        'iso_week': start.isocalendar()[1],
        'days': days, 'tickets': tickets,
        'solvers': sorted(solvers.values(), key=lambda u: (u.fullname or u.username)),
    }


@tech_extras_bp.route('/planning')
@login_required
@nocache
def planning():
    if not check_permission(TEAM_ROLES):
        return render_template('errors/catdance.html'), 403
    ref = None
    raw = request.args.get('week')
    if raw:
        try:
            ref = datetime.strptime(raw, '%Y-%m-%d')
        except ValueError:
            ref = None
    solver_id = request.args.get('solver', type=int)
    data = planning_week(current_user, ref, solver_id)
    return render_template('tickets/planning.html', solver_filter=solver_id, **data)
