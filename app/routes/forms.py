from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os
import shutil
from datetime import datetime
from string import Template

from app import db
from app.decorators import can_validate_step
from app.models import (
    HelpTip,
    FormDefinition, FormSubmission, FormSubmissionFile, FormFieldType,
    FormSubmissionStatus, ServiceSource, Notification, Ticket, TicketStatus,
    TICKET_FIELD_MAPPING_CHOICES,
)
from app.emails import send_form_step_alert, send_form_refused_notification, send_service_alert

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
    matched_emails = []
    for u in candidates:
        if _step_matches(u, step, submission):
            n = Notification(
                user=u,
                message=f"Formulaire « {submission.form.name} » ({submission.uid_public}) à valider — étape « {step.label} ».",
                category='info',
                link=url_for('forms.view_submission', id=submission.id)
            )
            db.session.add(n)
            if u.email:
                matched_emails.append(u.email)
    if matched_emails:
        send_form_step_alert(submission, step, list(set(matched_emails)))


def _first_eligible_step_index(form_def, author, start=0):
    """Première étape (à partir de `start`) qui n'est pas sautée pour ce
    demandeur (skip_for_author_roles). Retourne len(steps) si toutes les
    étapes restantes sont sautées (= finalisation immédiate)."""
    steps = form_def.steps
    for i in range(start, len(steps)):
        if not steps[i].is_skipped_for(author):
            return i
    return len(steps)


def _render_submission_text(submission, included_fields=None):
    """Description générique listant les champs de la soumission. Scopée par
    destinataire via `included_fields` (target.get_included_description_fields()
    — None = tous les champs, comportement par défaut ; liste = seulement ces
    champs) pour éviter qu'une donnée sensible d'une section (ex: DRH) fuite
    dans le texte libre d'un ticket destiné à un autre service."""
    lines = []
    data = submission.get_data()
    for field in submission.form.fields:
        if field.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE):
            continue
        if included_fields is not None and field.name not in included_fields:
            continue
        lines.append(f"{field.label} : {data.get(field.name) or '-'}")
    return "\n".join(lines)


def _render_template_or_default(template_str, data, default):
    """Rend un modèle $nom_du_champ (string.Template) avec les données de la
    soumission ; un placeholder sans correspondance reste tel quel (pas
    d'erreur). Retourne `default` si aucun modèle n'est configuré ou si le
    rendu échoue/est vide."""
    if not template_str:
        return default
    try:
        safe_data = {k: ('' if v is None else v) for k, v in data.items()}
        rendered = Template(template_str).safe_substitute(safe_data).strip()
        return rendered or default
    except Exception:
        return default


def _create_one_ticket(submission, target):
    """Crée un Ticket pour un FormDispatchTarget donné. Idempotent via l'uid
    dérivé. Copie les fichiers de la soumission sélectionnés pour ce
    destinataire (target.get_included_file_fields() — None = tous,
    comportement par défaut ; liste = seulement ces champs, comme l'ancien
    FCPI qui routait des fichiers différents par service). Catégorie/titre/
    description personnalisables par modèle ($nom_du_champ) pour reproduire
    fidèlement les anciens modules ; valeurs génériques sinon."""
    form_def = submission.form
    data = submission.get_data()
    # Les champs MULTI_SELECT sont stockés en liste Python — pour les modèles
    # ($nom_du_champ) et le mapping de colonnes, on les aplatit en texte
    # séparé par virgules, comme l'ancien FCPI (",".join(request.form.getlist(...)))
    # produisait déjà pour Recruitment.materiels_demandes.
    flat_data = {k: (','.join(v) if isinstance(v, list) else v) for k, v in data.items()}

    # Ticket.uid_public est limité à 30 caractères (contrairement à
    # FormSubmission.uid_public qui tolère jusqu'à 40) — uid_suffix donne un
    # identifiant lisible (F<id soumission>-<suffixe>, ex: F42-DRH) comme les
    # anciens modules ; sinon repli sur un uid opaque garanti unique.
    uid = f"F{submission.id}-{target.uid_suffix}" if target.uid_suffix else f"FRM-{submission.id}-{target.id}"
    existing = Ticket.query.filter_by(uid_public=uid).first()
    if existing:
        return existing

    default_title = f"[{form_def.name}] {submission.uid_public} — {target.label}"
    default_description = _render_submission_text(submission, target.get_included_description_fields())
    # 'Standard' par défaut (et non un libellé personnalisé) pour que le
    # ticket tombe dans pool_standard côté solver_dashboard si aucune
    # catégorie n'est configurée — les catégories libres non reconnues y
    # resteraient invisibles dans l'Espace Tech.
    category = _render_template_or_default(target.ticket_category_template, flat_data, 'Standard')
    title = _render_template_or_default(target.ticket_title_template, flat_data, default_title)
    description = _render_template_or_default(target.ticket_description_template, flat_data, default_description)

    ticket = Ticket(
        uid_public=uid,
        title=title,
        description=description,
        author_id=submission.author_id,
        target_service=target.target_service,
        status=TicketStatus.PENDING,
        category_ticket=category,
        service_demandeur=submission.author.service if submission.author else None,
        created_at=datetime.utcnow(),
    )

    # Champs mappés vers des colonnes structurées du Ticket (ex: FCPI ->
    # materiel_list, new_user_acces...), en plus de la description générique.
    # Scopés par destinataire via target.get_included_mapped_fields() (None =
    # tous, comportement par défaut ; liste = seulement ces champs) — sinon un
    # champ mappé s'appliquerait à TOUS les tickets de la soumission, y compris
    # des destinataires qui ne doivent pas le recevoir (ex: FCPI).
    included_mapped = target.get_included_mapped_fields()
    for field in form_def.fields:
        if field.maps_to_ticket_field:
            if included_mapped is not None and field.name not in included_mapped:
                continue
            value = flat_data.get(field.name) or None
            # new_user_date est un DateTime côté Ticket (comme
            # Recruitment.date_entree dans l'ancien FCPI) — un champ DATE du
            # moteur stocke une chaîne "AAAA-MM-JJ" brute, à convertir.
            if value and field.field_type == FormFieldType.DATE and field.maps_to_ticket_field == 'new_user_date':
                try:
                    value = datetime.strptime(value, '%Y-%m-%d')
                except ValueError:
                    value = None
            setattr(ticket, field.maps_to_ticket_field, value)

    # Colonnes structurées calculées à partir de PLUSIEURS champs combinés
    # (ex: new_user_fullname = "$nom_agent $prenom_agent"), non exprimables
    # par le mapping 1:1 ci-dessus. Appliqué à tous les tickets de la
    # soumission, comme l'ancien fcpi.py qui les fixait identiquement pour
    # chacun des 4 tickets créés.
    for column, tmpl in form_def.get_structured_templates().items():
        if column in TICKET_FIELD_MAPPING_CHOICES and hasattr(ticket, column):
            rendered = _render_template_or_default(tmpl, flat_data, None)
            if rendered:
                setattr(ticket, column, rendered)

    included_fields = target.get_included_file_fields()
    files_to_copy = submission.files if included_fields is None \
        else [f for f in submission.files if f.field_name in included_fields]

    if files_to_copy:
        base = os.path.join(current_app.root_path, 'static', 'uploads')
        src_dir = os.path.join(base, 'forms', form_def.slug, submission.uid_public)
        dest_dir = os.path.join(base, 'tickets', uid)
        ticket_files = []
        if os.path.exists(src_dir):
            os.makedirs(dest_dir, exist_ok=True)
            for f in files_to_copy:
                src = os.path.join(src_dir, f.stored_filename)
                if os.path.exists(src):
                    shutil.copy2(src, dest_dir)
                    ticket_files.append(f.stored_filename)
        if ticket_files:
            import json
            ticket.daf_files_json = json.dumps(ticket_files)

    db.session.add(ticket)
    db.session.flush()
    return ticket


def _create_tickets_from_submission(submission):
    """Crée un Ticket par FormDispatchTarget dont la condition est satisfaite.
    Idempotent (safe à rappeler)."""
    data = submission.get_data()
    already = set(submission.get_ticket_ids())
    for target in submission.form.dispatch_targets:
        if not target.is_satisfied(data):
            continue
        ticket = _create_one_ticket(submission, target)
        if ticket.id not in already:
            submission.add_ticket_id(ticket.id)
            already.add(ticket.id)
            from app.routes.tickets import get_service_emails, notify_solvers_new_ticket
            send_service_alert(ticket, get_service_emails(target.target_service))
            notify_solvers_new_ticket(ticket)


def _finalize_submission(submission):
    """Marque la soumission comme terminée, notifie l'auteur, et crée les
    Ticket(s) réels pour chaque destinataire dont la condition est satisfaite
    (aucun destinataire configuré = pas de Ticket, juste DONE + notification)."""
    submission.status = FormSubmissionStatus.DONE
    db.session.add(Notification(
        user=submission.author,
        message=f"Votre formulaire {submission.uid_public} a été validé et est terminé.",
        category='success',
        link=url_for('forms.view_submission', id=submission.id)
    ))
    if submission.form.dispatch_targets:
        _create_tickets_from_submission(submission)


@forms_bp.route('/<slug>/new', methods=['GET', 'POST'])
@login_required
def new_submission(slug):
    form_def = FormDefinition.query.filter_by(slug=slug).first_or_404()
    if not form_def.is_active:
        abort(404)
    # Conseils "avant d'envoyer" gérés dans /admin/help-contents (contexte = slug)
    help_tips = HelpTip.query.filter_by(context=slug, is_active=True).order_by(HelpTip.sort_order, HelpTip.id).all()

    if form_def.manager_only:
        role = str(current_user.role.value).upper()
        if not ('MANAGER' in role or 'DIRECTEUR' in role or 'ADMIN' in role):
            return render_template('errors/catdance.html'), 403

    # Lot 7 : demande faite au nom de quelqu'un d'autre / refaire une demande
    from app.delegation import (resolve_on_behalf, is_manager_like, notify_on_behalf_created,
                                submission_prefill)

    if request.method == 'POST':
        # L'auteur devient la personne concernée (elle voit la demande dans son
        # portail, reçoit les notifications, et les étapes EMITTER visent SON
        # service) ; le créateur réel est gardé dans created_by. Un formulaire
        # réservé aux managers ne peut pas être déposé au nom d'un non-habilité.
        beneficiary = resolve_on_behalf(current_user, request.form)
        if beneficiary and form_def.manager_only and not is_manager_like(beneficiary):
            flash(f"{beneficiary.fullname or beneficiary.username} n'est pas habilité(e) à ce formulaire : impossible de le déposer en son nom.", "danger")
            return render_template('forms/new_submission.html', form_def=form_def, form_data=request.form,
                                   help_tips=help_tips, on_behalf=beneficiary), 403
        author = beneficiary or current_user

        today_str = datetime.now().strftime('%Y%m%d')
        count = FormSubmission.query.filter(
            FormSubmission.uid_public.like(f"FRM-{slug}-{today_str}%")
        ).count() + 1
        uid = f"FRM-{slug}-{today_str}-{str(count).zfill(3)}"

        # Les champs sont traités dans l'ordre (order_index) et `data` est
        # construit au fur et à mesure : un champ conditionnel doit référencer
        # un champ qui le précède dans l'ordre (convention naturelle de
        # l'éditeur — on ajoute le champ déclencheur avant le champ dépendant).
        # Un champ non visible n'est ni exigé, ni lu depuis le formulaire soumis.
        data = {}
        errors = []
        for field in form_def.fields:
            if field.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE):
                continue
            visible = field.is_visible(data)
            if field.field_type == FormFieldType.MULTI_SELECT:
                values = request.form.getlist(field.name) if visible else []
                if visible and field.is_required and not values:
                    errors.append(f"Le champ « {field.label} » est obligatoire.")
                data[field.name] = values
                continue
            if field.field_type == FormFieldType.CHECKBOX:
                data[field.name] = bool(request.form.get(field.name)) if visible else False
                continue
            value = request.form.get(field.name, '').strip() if visible else ''
            if visible and field.is_required and not value:
                errors.append(f"Le champ « {field.label} » est obligatoire.")
            data[field.name] = value

        file_fields = [f for f in form_def.fields if f.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE)]
        visible_file_fields = [f for f in file_fields if f.is_visible(data)]
        for field in visible_file_fields:
            files = request.files.getlist(field.name)
            files = [f for f in files if f and f.filename]
            if field.is_required and not files:
                errors.append(f"Le champ « {field.label} » est obligatoire.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template('forms/new_submission.html', form_def=form_def, form_data=request.form, help_tips=help_tips, on_behalf=beneficiary)

        initial_index = _first_eligible_step_index(form_def, author, 0)
        submission = FormSubmission(
            uid_public=uid,
            form_definition_id=form_def.id,
            author=author,
            created_by_id=current_user.id if beneficiary else None,
            current_step_index=initial_index,
            status=FormSubmissionStatus.IN_PROGRESS,
        )
        submission.set_data(data)
        db.session.add(submission)
        db.session.flush()

        if visible_file_fields:
            upload_path = _upload_dir(slug, uid)
            for field in visible_file_fields:
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

        if initial_index < len(form_def.steps):
            _notify_step_validators(submission, submission.current_step)
            flash(f"Formulaire soumis ({uid}). En attente de validation.", "success")
        else:
            _finalize_submission(submission)
            flash(f"Formulaire soumis ({uid}). Aucune validation requise, transmis directement.", "success")

        if beneficiary:
            notify_on_behalf_created(beneficiary, current_user, uid, url_for('forms.view_submission', id=submission.id))

        db.session.commit()
        return redirect(url_for('forms.view_submission', id=submission.id))

    # « Refaire cette demande » : ?from=<id> pré-remplit avec une de mes soumissions (hors fichiers)
    form_data = submission_prefill(request.args.get('from'), current_user, form_def)
    if request.args.get('from') and form_data is None:
        flash("Impossible de pré-remplir : demande introuvable ou qui ne vous appartient pas.", "warning")
    return render_template('forms/new_submission.html', form_def=form_def, form_data=form_data or {}, help_tips=help_tips)


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


def advance_submission(submission, user):
    """Valide l'étape courante au nom de `user` : passe à l'étape éligible
    suivante (et notifie ses validateurs) ou finalise. Retourne True si la
    soumission est terminée. Partagé par validate_submission et la validation
    en lot du tableau de bord manager (tickets.manager_batch_validate)."""
    submission.last_validated_at = datetime.now()
    submission.validated_by_id = user.id
    next_index = _first_eligible_step_index(submission.form, submission.author, submission.current_step_index + 1)
    if next_index < len(submission.form.steps):
        submission.current_step_index = next_index
        _notify_step_validators(submission, submission.current_step)
        return False
    _finalize_submission(submission)
    return True


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
        reason = request.form.get('refusal_reason', 'Refusé.')
        submission.refusal_reason = f"Refusé par {current_user.fullname} : {reason}"
        db.session.add(Notification(
            user=submission.author,
            message=f"Votre formulaire {submission.uid_public} a été refusé.",
            category='danger',
            link=url_for('forms.view_submission', id=submission.id)
        ))
        if submission.author and submission.author.email:
            send_form_refused_notification(submission, submission.author.email)
        flash("Soumission refusée.", "warning")

    elif action == 'validate':
        finished = advance_submission(submission, current_user)
        flash("Soumission validée et terminée." if finished else "Étape validée, transmise à l'étape suivante.", "success")
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
