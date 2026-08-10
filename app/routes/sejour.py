from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app.models import DossierSejour, SejourStatus, ServiceType, Ticket, TicketStatus, User, UserRole, Notification
from app import db
from werkzeug.utils import secure_filename
import os, json, shutil
from datetime import datetime

sejour_bp = Blueprint('sejour', __name__)


def _save_file(request_files_key, upload_path, prefix=''):
    f = request_files_key
    if f and f.filename:
        fname = prefix + secure_filename(f.filename)
        f.save(os.path.join(upload_path, fname))
        return fname
    return None


def _create_sejour_ticket(sejour, target_service, description, files_to_copy):
    """Crée un ticket enfant pour un service donné après validation du dossier de séjour."""
    suffix_map = {
        ServiceType.DRH: 'DRH',
        ServiceType.DAF: 'DAF',
        ServiceType.SG:  'SG',
    }
    suffix = suffix_map.get(target_service, target_service.value[:3])
    uid = f"{sejour.uid_public}-{suffix}"

    existing = Ticket.query.filter_by(uid_public=uid).first()
    if existing:
        return existing.id

    t = Ticket(
        uid_public=uid,
        title=f"[SEJOUR] {sejour.titre}",
        description=description,
        author_id=sejour.author_id,
        target_service=target_service,
        status=TicketStatus.PENDING,
        category_ticket="Dossier de Séjour",
        service_demandeur=sejour.service_demandeur,
        created_at=datetime.utcnow(),
    )

    # Copier les fichiers concernés dans le dossier du ticket
    ticket_files = []
    if files_to_copy:
        base = os.path.join(current_app.root_path, 'static', 'uploads')
        src_dir = os.path.join(base, 'sejour', sejour.uid_public)
        dest_dir = os.path.join(base, 'tickets', uid)
        if os.path.exists(src_dir):
            os.makedirs(dest_dir, exist_ok=True)
            for fname in files_to_copy:
                if fname:
                    src = os.path.join(src_dir, fname)
                    if os.path.exists(src):
                        shutil.copy2(src, dest_dir)
                        ticket_files.append(fname)

    if ticket_files:
        t.daf_files_json = json.dumps(ticket_files)

    db.session.add(t)
    db.session.flush()
    return t.id


# ─────────────────────────────────────────────
# CRÉATION
# ─────────────────────────────────────────────

@sejour_bp.route('/sejour/new', methods=['GET', 'POST'])
@login_required
def new_sejour():
    if request.method == 'POST':
        today_str = datetime.now().strftime('%Y%m%d')
        count = DossierSejour.query.filter(
            DossierSejour.uid_public.like(f"SEJ-{today_str}%")
        ).count() + 1
        uid = f"SEJ-{today_str}-{str(count).zfill(3)}"

        upload_path = os.path.join(
            current_app.root_path, 'static', 'uploads', 'sejour', uid
        )
        os.makedirs(upload_path, exist_ok=True)

        date_sejour = None
        if request.form.get('date_sejour'):
            try:
                date_sejour = datetime.strptime(request.form.get('date_sejour'), '%Y-%m-%d')
            except:
                pass

        sejour = DossierSejour(
            uid_public=uid,
            author=current_user,
            status=SejourStatus.VALIDATION_MANAGER,
            titre=request.form.get('titre'),
            description=request.form.get('description'),
            date_sejour=date_sejour,
            service_demandeur=request.form.get('service_demandeur') or current_user.service,
            file_dossier=_save_file(request.files.get('file_dossier'), upload_path, 'dossier_'),
            file_pv_securite=_save_file(request.files.get('file_pv_securite'), upload_path, 'pv_'),
            file_devis=_save_file(request.files.get('file_devis'), upload_path, 'devis_'),
        )
        db.session.add(sejour)
        db.session.commit()

        # Notifier les managers du service de l'utilisateur
        managers = User.query.filter(
            (User.role == UserRole.MANAGER) | (User.role == UserRole.DIRECTEUR) | (User.role == UserRole.ADMIN)
        ).all()
        for m in managers:
            n = Notification(
                user=m,
                message=f"Nouveau dossier de séjour à valider : {uid}",
                category='info',
                link=url_for('sejour.view_sejour', id=sejour.id)
            )
            db.session.add(n)
        db.session.commit()

        flash("Dossier de séjour déposé. En attente de validation.", "success")
        return redirect(url_for('main.user_portal'))

    return render_template('sejour/new_sejour.html')


# ─────────────────────────────────────────────
# VISUALISATION
# ─────────────────────────────────────────────

@sejour_bp.route('/sejour/view/<int:id>')
@login_required
def view_sejour(id):
    sejour = DossierSejour.query.get_or_404(id)
    role = str(current_user.role.value).upper()
    is_manager = 'MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role

    if sejour.author_id != current_user.id and not is_manager:
        flash("Accès non autorisé.", "danger")
        return redirect(url_for('main.user_portal'))

    child_tickets = []
    if sejour.get_child_tickets():
        child_tickets = Ticket.query.filter(
            Ticket.id.in_(sejour.get_child_tickets())
        ).all()

    return render_template('sejour/view_sejour.html', sejour=sejour, child_tickets=child_tickets, is_manager=is_manager)


# ─────────────────────────────────────────────
# LISTE (managers/admins)
# ─────────────────────────────────────────────

@sejour_bp.route('/sejour/list')
@login_required
def list_sejours():
    role = str(current_user.role.value).upper()
    if not ('MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role):
        flash("Accès réservé aux managers.", "danger")
        return redirect(url_for('main.user_portal'))
    sejours = DossierSejour.query.order_by(DossierSejour.created_at.desc()).all()
    return render_template('sejour/list_sejours.html', sejours=sejours)


# ─────────────────────────────────────────────
# VALIDATION / REFUS (Manager/Directeur Adjoint)
# ─────────────────────────────────────────────

@sejour_bp.route('/sejour/validate/<int:id>/<action>', methods=['POST'])
@login_required
def validate_sejour(id, action):
    sejour = DossierSejour.query.get_or_404(id)
    role = str(current_user.role.value).upper()

    if not ('MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role):
        flash("Droits insuffisants.", "danger")
        return redirect(url_for('main.user_portal'))

    if action == 'refuse':
        sejour.status = SejourStatus.REFUSED
        sejour.refusal_reason = request.form.get('refusal_reason', 'Refusé.')
        n = Notification(
            user=sejour.author,
            message=f"Votre dossier de séjour {sejour.uid_public} a été refusé.",
            category='danger',
            link=url_for('sejour.view_sejour', id=sejour.id)
        )
        db.session.add(n)
        db.session.commit()
        flash("Dossier refusé.", "warning")
        return redirect(url_for('tickets.manager_dashboard'))

    if action == 'validate' and sejour.status == SejourStatus.VALIDATION_MANAGER:

        # Sauvegarde du dossier signé uploadé par le Directeur Adjoint
        upload_path = os.path.join(
            current_app.root_path, 'static', 'uploads', 'sejour', sejour.uid_public
        )
        os.makedirs(upload_path, exist_ok=True)
        file_signe = _save_file(request.files.get('file_dossier_signe'), upload_path, 'signe_')
        if file_signe:
            sejour.file_dossier_signe = file_signe

        # Le fichier transmis aux services : version signée si fournie, sinon originale
        dossier_a_transmettre = sejour.file_dossier_signe or sejour.file_dossier

        child_ids = []
        desc_base = f"Séjour : {sejour.titre}\nService : {sejour.service_demandeur}\nDate : {sejour.date_sejour.strftime('%d/%m/%Y') if sejour.date_sejour else 'Non précisée'}\n\n{sejour.description or ''}"

        # 1. DRH — reçoit le dossier signé
        child_ids.append(_create_sejour_ticket(
            sejour, ServiceType.DRH,
            f"Dossier de séjour à traiter (DRH).\n{desc_base}",
            files_to_copy=[dossier_a_transmettre]
        ))

        # 2. DAF — reçoit le dossier signé + devis
        child_ids.append(_create_sejour_ticket(
            sejour, ServiceType.DAF,
            f"Dossier de séjour à traiter (DAF).\n{desc_base}",
            files_to_copy=[dossier_a_transmettre, sejour.file_devis]
        ))

        # 3. SG (Secrétariat Général) — reçoit dossier signé + devis + PV sécurité
        child_ids.append(_create_sejour_ticket(
            sejour, ServiceType.SG,
            f"Dossier de séjour à traiter (Secrétariat Général).\n{desc_base}",
            files_to_copy=[dossier_a_transmettre, sejour.file_devis, sejour.file_pv_securite]
        ))

        sejour.status = SejourStatus.DISPATCHED
        sejour.child_tickets_ids = json.dumps(child_ids)

        n = Notification(
            user=sejour.author,
            message=f"Votre dossier de séjour {sejour.uid_public} a été validé et transmis aux services.",
            category='success',
            link=url_for('sejour.view_sejour', id=sejour.id)
        )
        db.session.add(n)
        db.session.commit()
        flash("Dossier validé. 3 tickets générés (DRH, DAF, SG).", "success")

    return redirect(url_for('tickets.manager_dashboard'))
