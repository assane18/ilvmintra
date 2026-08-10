from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os
import shutil
from datetime import datetime

from app import db
from app.decorators import can_validate_step
from app.models import (
    FormDefinition, FormSubmission, FormSubmissionFile, FormFieldType,
    FormSubmissionStatus, ServiceSource, Notification, Ticket, TicketStatus,
)

forms_bp = Blueprint('forms', __name__, url_prefix='/forms')


def _upload_dir(slug, uid):
    path = os.path.join(current_app.root_path, 'static', 'uploads', 'forms', slug, uid)
    os.makedirs(path, exist_ok=True)
    return path


def _step_matches(user, step, submission):
    """Correspondance stricte rôle/service de l'étape, sans le bypass ADMIN
    utilisé pour l'autorisation (can_validate_step) — sert uniquement à cibler
    les notifications."""
    from app.models import UserRole
    role_ok = (user.role == step.validator_role) if step.validator_role \
        else user.role in (UserRole.MANAGER, UserRole.DIRECTEUR)
    if not role_ok:
        return False
    if step.service_source == ServiceSource.EMITTER:
        emitter_services = set(submission.author.get_origin_services()) if submission.author else set()
        return bool(emitter_services & set(user.get_origin_services()))
    if step.validator_service:
        return step.validator_service.value in user.get_allowed_services()
    return True


def _notify_step_validators(submission, step):
    if not step:
        return
    from app.models import User
    candidates = User.query.all()
    for u in candidates:
        if _step_matches(u, step, submission):
            n = Notification(
                user=u,
                message=f"Formulaire « {submission.form.name} » ({submission.uid_public}) à valider — étape « {step.label} ».",
                category='info',
                link=url_for('forms.view_submission', id=submission.id)
            )
            db.session.add(n)


def _render_submission_text(submission):
    lines = []
    data = submission.get_data()
    for field in submission.form.fields:
        if field.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE):
            continue
        lines.append(f"{field.label} : {data.get(field.name) or '-'}")
    return "\n".join(lines)


def _create_ticket_from_submission(submission):
    """Crée un Ticket réel routé vers submission.form.target_service, calqué sur
    sejour.py:_create_sejour_ticket. Idempotent via submission.ticket_id."""
    if submission.ticket_id:
        return submission.ticket
    form_def = submission.form
    if not form_def.target_service:
        return None

    # Ticket.uid_public est limité à 30 caractères (contrairement à
    # FormSubmission.uid_public qui tolère jusqu'à 40) : on ne peut pas se
    # contenter de suffixer l'uid de la soumission pour les slugs longs.
    uid = f"FRM-{submission.id}-TCK"
    existing = Ticket.query.filter_by(uid_public=uid).first()
    if existing:
        submission.ticket_id = existing.id
        return existing

    ticket = Ticket(
        uid_public=uid,
        title=f"[{form_def.name}] {submission.uid_public}",
        description=_render_submission_text(submission),
        author_id=submission.author_id,
        target_service=form_def.target_service,
        status=TicketStatus.PENDING,
        # 'Standard' (et non un libellé personnalisé) pour que le ticket tombe
        # dans pool_standard côté solver_dashboard — les catégories libres n'y
        # sont pas reconnues et resteraient invisibles dans l'Espace Tech. Le
        # nom du formulaire reste visible dans le titre du ticket.
        category_ticket='Standard',
        service_demandeur=submission.author.service if submission.author else None,
        created_at=datetime.utcnow(),
    )

    if submission.files:
        base = os.path.join(current_app.root_path, 'static', 'uploads')
        src_dir = os.path.join(base, 'forms', form_def.slug, submission.uid_public)
        dest_dir = os.path.join(base, 'tickets', uid)
        ticket_files = []
        if os.path.exists(src_dir):
            os.makedirs(dest_dir, exist_ok=True)
            for f in submission.files:
                src = os.path.join(src_dir, f.stored_filename)
                if os.path.exists(src):
                    shutil.copy2(src, dest_dir)
                    ticket_files.append(f.stored_filename)
        if ticket_files:
            import json
            ticket.daf_files_json = json.dumps(ticket_files)

    db.session.add(ticket)
    db.session.flush()
    submission.ticket_id = ticket.id
    return ticket


def _finalize_submission(submission):
    """Marque la soumission comme terminée, notifie l'auteur, et crée un Ticket
    réel si le formulaire a un target_service (sinon rien de plus ne se passe)."""
    submission.status = FormSubmissionStatus.DONE
    db.session.add(Notification(
        user=submission.author,
        message=f"Votre formulaire {submission.uid_public} a été validé et est terminé.",
        category='success',
        link=url_for('forms.view_submission', id=submission.id)
    ))
    if submission.form.target_service:
        _create_ticket_from_submission(submission)


@forms_bp.route('/<slug>/new', methods=['GET', 'POST'])
@login_required
def new_submission(slug):
    form_def = FormDefinition.query.filter_by(slug=slug).first_or_404()
    if not form_def.is_active:
        abort(404)

    if request.method == 'POST':
        today_str = datetime.now().strftime('%Y%m%d')
        count = FormSubmission.query.filter(
            FormSubmission.uid_public.like(f"FRM-{slug}-{today_str}%")
        ).count() + 1
        uid = f"FRM-{slug}-{today_str}-{str(count).zfill(3)}"

        data = {}
        errors = []
        for field in form_def.fields:
            if field.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE):
                continue
            value = request.form.get(field.name, '').strip()
            if field.is_required and not value:
                errors.append(f"Le champ « {field.label} » est obligatoire.")
            if field.field_type == FormFieldType.CHECKBOX:
                value = bool(request.form.get(field.name))
            data[field.name] = value

        file_fields = [f for f in form_def.fields if f.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE)]
        for field in file_fields:
            files = request.files.getlist(field.name)
            files = [f for f in files if f and f.filename]
            if field.is_required and not files:
                errors.append(f"Le champ « {field.label} » est obligatoire.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template('forms/new_submission.html', form_def=form_def, form_data=request.form)

        submission = FormSubmission(
            uid_public=uid,
            form_definition_id=form_def.id,
            author=current_user,
            current_step_index=0,
            status=FormSubmissionStatus.IN_PROGRESS,
        )
        submission.set_data(data)
        db.session.add(submission)
        db.session.flush()

        if file_fields:
            upload_path = _upload_dir(slug, uid)
            for field in file_fields:
                for f in request.files.getlist(field.name):
                    if f and f.filename:
                        stored_name = secure_filename(f.filename)
                        f.save(os.path.join(upload_path, stored_name))
                        db.session.add(FormSubmissionFile(
                            submission_id=submission.id,
                            field_name=field.name,
                            original_filename=f.filename,
                            stored_filename=stored_name,
                        ))

        if form_def.steps:
            _notify_step_validators(submission, submission.current_step)
            flash(f"Formulaire soumis ({uid}). En attente de validation.", "success")
        else:
            _finalize_submission(submission)
            flash(f"Formulaire soumis ({uid}). Aucune validation requise, transmis directement.", "success")

        db.session.commit()
        return redirect(url_for('forms.view_submission', id=submission.id))

    return render_template('forms/new_submission.html', form_def=form_def, form_data={})


@forms_bp.route('/submission/<int:id>')
@login_required
def view_submission(id):
    submission = FormSubmission.query.get_or_404(id)
    is_author = submission.author_id == current_user.id
    is_validator = (
        submission.status == FormSubmissionStatus.IN_PROGRESS
        and submission.current_step is not None
        and can_validate_step(current_user, submission.current_step, submission)
    )
    is_admin = 'ADMIN' in str(current_user.role.value).upper()

    if not (is_author or is_validator or is_admin):
        flash("Accès non autorisé.", "danger")
        return redirect(url_for('main.user_portal'))

    return render_template(
        'forms/view_submission.html',
        submission=submission,
        data=submission.get_data(),
        can_validate=is_validator,
    )


@forms_bp.route('/submission/<int:id>/validate/<action>', methods=['POST'])
@login_required
def validate_submission(id, action):
    submission = FormSubmission.query.get_or_404(id)

    if submission.status != FormSubmissionStatus.IN_PROGRESS:
        flash("Cette soumission n'est plus en attente de validation.", "warning")
        return redirect(url_for('forms.view_submission', id=id))

    step = submission.current_step
    if not step or not can_validate_step(current_user, step, submission):
        flash("Droits insuffisants pour valider cette étape.", "danger")
        return redirect(url_for('forms.view_submission', id=id))

    if action == 'refuse':
        submission.status = FormSubmissionStatus.REFUSED
        submission.refusal_reason = request.form.get('refusal_reason', 'Refusé.')
        db.session.add(Notification(
            user=submission.author,
            message=f"Votre formulaire {submission.uid_public} a été refusé.",
            category='danger',
            link=url_for('forms.view_submission', id=submission.id)
        ))
        flash("Soumission refusée.", "warning")

    elif action == 'validate':
        next_index = submission.current_step_index + 1
        if next_index < len(submission.form.steps):
            submission.current_step_index = next_index
            _notify_step_validators(submission, submission.current_step)
            flash("Étape validée, transmise à l'étape suivante.", "success")
        else:
            _finalize_submission(submission)
            flash("Soumission validée et terminée.", "success")
    else:
        abort(400)

    db.session.commit()
    return redirect(url_for('forms.view_submission', id=id))


@forms_bp.route('/mine')
@login_required
def list_mine():
    submissions = FormSubmission.query.filter_by(author_id=current_user.id) \
        .order_by(FormSubmission.created_at.desc()).all()
    return render_template('forms/list_mine.html', submissions=submissions)


@forms_bp.route('/to-validate')
@login_required
def list_to_validate():
    pending = FormSubmission.query.filter_by(status=FormSubmissionStatus.IN_PROGRESS).all()
    submissions = [s for s in pending if s.current_step and can_validate_step(current_user, s.current_step, s)]
    submissions.sort(key=lambda s: s.created_at, reverse=True)
    return render_template('forms/list_to_validate.html', submissions=submissions)
