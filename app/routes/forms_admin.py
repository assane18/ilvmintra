from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
import json
import re

from app import db
from app.decorators import admin_required
from app.models import (
    FormDefinition, FormField, FormWorkflowStep, FormFieldType,
    UserRole, ServiceType, ServiceSource, FormDispatchTarget, TICKET_FIELD_MAPPING_CHOICES,
)

forms_admin_bp = Blueprint('forms_admin', __name__, url_prefix='/admin/forms')


def _slugify(value):
    value = value.strip().lower()
    value = re.sub(r'[^a-z0-9]+', '-', value)
    return re.sub(r'-+', '-', value).strip('-')[:60]


@forms_admin_bp.route('/')
@login_required
@admin_required
def list_forms():
    forms = FormDefinition.query.order_by(FormDefinition.created_at.desc()).all()
    return render_template('forms_admin/list.html', forms=forms)


@forms_admin_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_form():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash("Le nom du formulaire est obligatoire.", "danger")
            return redirect(url_for('forms_admin.new_form'))

        slug = _slugify(request.form.get('slug') or name)
        if not slug or FormDefinition.query.filter_by(slug=slug).first():
            flash("Cet identifiant (slug) est déjà utilisé ou invalide.", "danger")
            return redirect(url_for('forms_admin.new_form'))

        form_def = FormDefinition(
            slug=slug,
            name=name,
            description=request.form.get('description', '').strip(),
            is_active=False,
            created_by=current_user,
        )
        db.session.add(form_def)
        db.session.commit()
        flash(f"Formulaire « {form_def.name} » créé. Ajoutez maintenant ses champs et ses étapes.", "success")
        return redirect(url_for('forms_admin.edit_form', id=form_def.id))

    return render_template('forms_admin/new.html')


@forms_admin_bp.route('/<int:id>/edit')
@login_required
@admin_required
def edit_form(id):
    form_def = FormDefinition.query.get_or_404(id)
    field_types = [t.value for t in FormFieldType]
    roles = [r.value for r in UserRole]
    services = [s.value for s in ServiceType]
    return render_template(
        'forms_admin/edit.html',
        form_def=form_def,
        field_types=field_types,
        roles=roles,
        services=services,
        ticket_field_choices=TICKET_FIELD_MAPPING_CHOICES,
    )


@forms_admin_bp.route('/<int:id>/update', methods=['POST'])
@login_required
@admin_required
def update_form(id):
    form_def = FormDefinition.query.get_or_404(id)
    name = request.form.get('name', '').strip()
    if name:
        form_def.name = name
    form_def.description = request.form.get('description', '').strip()
    form_def.manager_only = bool(request.form.get('manager_only'))

    raw_templates = request.form.get('structured_field_templates', '').strip()
    if not raw_templates:
        form_def.structured_field_templates_json = None
    else:
        try:
            parsed = json.loads(raw_templates)
            if not isinstance(parsed, dict):
                raise ValueError("doit être un objet JSON")
            invalid_keys = [k for k in parsed if k not in TICKET_FIELD_MAPPING_CHOICES]
            if invalid_keys:
                raise ValueError(f"colonne(s) inconnue(s) : {', '.join(invalid_keys)}")
            form_def.structured_field_templates_json = json.dumps(parsed)
        except (ValueError, TypeError) as e:
            flash(f"Colonnes Ticket calculées invalides, non enregistrées : {e}", "danger")
            return redirect(url_for('forms_admin.edit_form', id=form_def.id))

    db.session.commit()
    flash("Informations du formulaire mises à jour.", "success")
    return redirect(url_for('forms_admin.edit_form', id=form_def.id))


@forms_admin_bp.route('/<int:id>/fields/save', methods=['POST'])
@login_required
@admin_required
def save_fields(id):
    form_def = FormDefinition.query.get_or_404(id)

    try:
        payload = json.loads(request.form.get('fields_payload') or '[]')
    except ValueError:
        flash("Données de champs invalides.", "danger")
        return redirect(url_for('forms_admin.edit_form', id=id))

    seen_names = set()
    new_fields = []
    pending_conditions = []  # (field, condition_field_name, condition_value)
    for index, item in enumerate(payload):
        label = (item.get('label') or '').strip()
        field_type_value = item.get('field_type')
        if not label or field_type_value not in [t.value for t in FormFieldType]:
            continue

        name = _slugify(item.get('name') or label).replace('-', '_')
        if not name:
            continue
        base_name = name
        suffix = 1
        while name in seen_names:
            suffix += 1
            name = f"{base_name}_{suffix}"
        seen_names.add(name)

        options_list = [o.strip() for o in (item.get('options') or '').split('\n') if o.strip()]
        maps_to = item.get('maps_to_ticket_field') or None
        if maps_to not in TICKET_FIELD_MAPPING_CHOICES:
            maps_to = None

        field = FormField(
            form_definition_id=form_def.id,
            name=name,
            label=label,
            field_type=FormFieldType(field_type_value),
            is_required=bool(item.get('is_required')),
            options_json=json.dumps(options_list) if options_list else None,
            help_text=(item.get('help_text') or '').strip() or None,
            order_index=index,
            maps_to_ticket_field=maps_to,
        )
        new_fields.append(field)
        condition_field_name = item.get('condition_field_name') or None
        if condition_field_name:
            pending_conditions.append((field, condition_field_name, item.get('condition_value') or None))

    FormField.query.filter_by(form_definition_id=form_def.id).delete()
    for f in new_fields:
        db.session.add(f)
    db.session.flush()

    # Résolution des conditions d'affichage : le champ référencé doit exister
    # dans ce même lot et précéder le champ dépendant (ordre = déclaration).
    names_to_fields = {f.name: f for f in new_fields}
    for field, condition_field_name, condition_value in pending_conditions:
        ref = names_to_fields.get(condition_field_name)
        if ref and ref.order_index < field.order_index:
            field.condition_field_id = ref.id
            field.condition_value = condition_value

    db.session.commit()
    flash("Champs du formulaire enregistrés.", "success")
    return redirect(url_for('forms_admin.edit_form', id=id))


@forms_admin_bp.route('/<int:id>/steps/save', methods=['POST'])
@login_required
@admin_required
def save_steps(id):
    form_def = FormDefinition.query.get_or_404(id)

    try:
        payload = json.loads(request.form.get('steps_payload') or '[]')
    except ValueError:
        flash("Données d'étapes invalides.", "danger")
        return redirect(url_for('forms_admin.edit_form', id=id))

    role_values = [r.value for r in UserRole]
    service_values = [s.value for s in ServiceType]
    skippable_roles = {UserRole.MANAGER.value, UserRole.DIRECTEUR.value, UserRole.ADMIN.value}

    new_steps = []
    for index, item in enumerate(payload):
        label = (item.get('label') or '').strip()
        role_value = item.get('validator_role') or None
        service_source_value = item.get('service_source') or ServiceSource.FIXED.value
        service_value = item.get('validator_service') or None
        skip_roles = [r for r in (item.get('skip_for_author_roles') or []) if r in skippable_roles]

        if not label:
            continue
        if role_value and role_value not in role_values:
            continue
        if service_source_value not in (ServiceSource.FIXED.value, ServiceSource.EMITTER.value):
            continue

        if service_source_value == ServiceSource.EMITTER.value:
            # Service résolu dynamiquement (celui du demandeur) : pas de service fixe.
            service_value = None
        elif service_value and service_value not in service_values:
            # Service fixe invalide fourni : on l'ignore plutôt que de rejeter
            # toute l'étape (une étape FIXED sans service = pas de contrainte,
            # seul le rôle compte).
            service_value = None

        new_steps.append(FormWorkflowStep(
            form_definition_id=form_def.id,
            order_index=index,
            label=label,
            validator_role=UserRole(role_value) if role_value else None,
            validator_service=ServiceType(service_value) if service_value else None,
            service_source=ServiceSource(service_source_value),
            skip_for_author_roles_json=json.dumps(skip_roles),
        ))

    FormWorkflowStep.query.filter_by(form_definition_id=form_def.id).delete()
    for s in new_steps:
        db.session.add(s)
    db.session.commit()
    flash("Étapes de validation enregistrées.", "success")
    return redirect(url_for('forms_admin.edit_form', id=id))


@forms_admin_bp.route('/<int:id>/dispatch_targets/save', methods=['POST'])
@login_required
@admin_required
def save_dispatch_targets(id):
    form_def = FormDefinition.query.get_or_404(id)

    try:
        payload = json.loads(request.form.get('dispatch_targets_payload') or '[]')
    except ValueError:
        flash("Données de destinataires invalides.", "danger")
        return redirect(url_for('forms_admin.edit_form', id=id))

    service_values = [s.value for s in ServiceType]
    checkbox_fields_by_name = {f.name: f for f in form_def.fields if f.field_type == FormFieldType.CHECKBOX}
    file_field_names = {f.name for f in form_def.fields if f.field_type in (FormFieldType.FILE, FormFieldType.MULTI_FILE)}
    mapped_field_names = {f.name for f in form_def.fields if f.maps_to_ticket_field}

    new_targets = []
    for item in payload:
        label = (item.get('label') or '').strip()
        service_value = item.get('target_service') or None
        condition_field_name = item.get('condition_field_name') or None

        if not label or not service_value or service_value not in service_values:
            continue

        condition_field = checkbox_fields_by_name.get(condition_field_name) if condition_field_name else None

        # included_file_fields absent du payload (clé non envoyée) = "tous les
        # fichiers" (comportement par défaut, None) ; présent (même vide) =
        # sélection explicite.
        included_files_json = None
        if 'included_file_fields' in item:
            selected = [n for n in (item.get('included_file_fields') or []) if n in file_field_names]
            included_files_json = json.dumps(selected)

        # Même principe que included_file_fields : absent du payload = "tous
        # les champs mappés" (None, comportement par défaut) ; présent (même
        # vide) = scoping explicite par destinataire.
        included_mapped_json = None
        if 'included_mapped_fields' in item:
            selected = [n for n in (item.get('included_mapped_fields') or []) if n in mapped_field_names]
            included_mapped_json = json.dumps(selected)

        new_targets.append(FormDispatchTarget(
            form_definition_id=form_def.id,
            label=label,
            target_service=ServiceType(service_value),
            condition_field_id=condition_field.id if condition_field else None,
            included_file_fields_json=included_files_json,
            included_mapped_fields_json=included_mapped_json,
            ticket_category_template=(item.get('ticket_category_template') or '').strip() or None,
            ticket_title_template=(item.get('ticket_title_template') or '').strip() or None,
            ticket_description_template=(item.get('ticket_description_template') or '').strip() or None,
            uid_suffix=(item.get('uid_suffix') or '').strip()[:20] or None,
        ))

    FormDispatchTarget.query.filter_by(form_definition_id=form_def.id).delete()
    for t in new_targets:
        db.session.add(t)
    db.session.commit()
    flash("Destinataires enregistrés.", "success")
    return redirect(url_for('forms_admin.edit_form', id=id))


@forms_admin_bp.route('/<int:id>/toggle_active', methods=['POST'])
@login_required
@admin_required
def toggle_active(id):
    form_def = FormDefinition.query.get_or_404(id)
    if not form_def.is_active:
        if not form_def.fields:
            flash("Impossible d'activer un formulaire sans champ.", "danger")
            return redirect(url_for('forms_admin.edit_form', id=id))
    form_def.is_active = not form_def.is_active
    db.session.commit()
    flash(f"Formulaire {'activé' if form_def.is_active else 'désactivé'}.", "success")
    return redirect(url_for('forms_admin.list_forms'))


@forms_admin_bp.route('/<int:id>/duplicate', methods=['POST'])
@login_required
@admin_required
def duplicate_form(id):
    original = FormDefinition.query.get_or_404(id)

    base_slug = f"{original.slug}-copie"
    slug = base_slug
    suffix = 1
    while FormDefinition.query.filter_by(slug=slug).first():
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    copy = FormDefinition(
        slug=slug,
        name=f"{original.name} (copie)",
        description=original.description,
        is_active=False,
        created_by=current_user,
        manager_only=original.manager_only,
        structured_field_templates_json=original.structured_field_templates_json,
    )
    db.session.add(copy)
    db.session.flush()

    field_id_map = {}
    for f in original.fields:
        new_field = FormField(
            form_definition_id=copy.id, name=f.name, label=f.label, field_type=f.field_type,
            is_required=f.is_required, options_json=f.options_json, help_text=f.help_text,
            order_index=f.order_index, maps_to_ticket_field=f.maps_to_ticket_field,
        )
        db.session.add(new_field)
        db.session.flush()
        field_id_map[f.id] = new_field.id

    # 2e passe : les conditions d'affichage référencent d'autres champs du même
    # formulaire, donc seulement une fois que tous les champs ont un nouvel id.
    for f in original.fields:
        if f.condition_field_id:
            new_field = FormField.query.filter_by(form_definition_id=copy.id, name=f.name).first()
            new_field.condition_field_id = field_id_map.get(f.condition_field_id)
            new_field.condition_value = f.condition_value

    for s in original.steps:
        db.session.add(FormWorkflowStep(
            form_definition_id=copy.id, order_index=s.order_index, label=s.label,
            validator_role=s.validator_role, validator_service=s.validator_service,
            service_source=s.service_source, skip_for_author_roles_json=s.skip_for_author_roles_json,
        ))
    for t in original.dispatch_targets:
        db.session.add(FormDispatchTarget(
            form_definition_id=copy.id, label=t.label, target_service=t.target_service,
            condition_field_id=field_id_map.get(t.condition_field_id),
            included_file_fields_json=t.included_file_fields_json,
            included_mapped_fields_json=t.included_mapped_fields_json,
            ticket_category_template=t.ticket_category_template,
            ticket_title_template=t.ticket_title_template,
            ticket_description_template=t.ticket_description_template,
            uid_suffix=t.uid_suffix,
        ))

    db.session.commit()
    flash(f"Formulaire dupliqué sous « {copy.name} ».", "success")
    return redirect(url_for('forms_admin.edit_form', id=copy.id))


@forms_admin_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_form(id):
    form_def = FormDefinition.query.get_or_404(id)
    if form_def.submissions_count > 0:
        flash("Impossible de supprimer un formulaire ayant déjà des soumissions. Désactivez-le plutôt.", "danger")
        return redirect(url_for('forms_admin.list_forms'))
    db.session.delete(form_def)
    db.session.commit()
    flash("Formulaire supprimé.", "success")
    return redirect(url_for('forms_admin.list_forms'))
