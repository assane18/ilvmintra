"""Seed des formulaires pilotes du moteur de formulaires génériques.

Crée deux définitions de formulaire (sejour-v2, publication-v2), reproduisant
à l'identique les champs et le workflow des modules codés en dur Séjour et
Publication, mais éditables depuis /admin/forms. Idempotent : ne recrée rien
si le slug existe déjà. Les formulaires sont créés désactivés (is_active=False)
pour ne pas être visibles des utilisateurs tant qu'un admin ne les active pas.

Usage : python seed_pilot_forms.py
"""
from app import create_app, db
from app.models import (
    FormDefinition, FormField, FormWorkflowStep, FormFieldType, UserRole, ServiceType, ServiceSource,
)

app = create_app()


def seed_sejour():
    if FormDefinition.query.filter_by(slug='sejour-v2').first():
        print("sejour-v2 existe déjà, ignoré.")
        return

    form_def = FormDefinition(
        slug='sejour-v2',
        name='Dossier de Séjour (v2)',
        description="Pilote du moteur de formulaires génériques, calqué sur le module Séjour existant.",
        is_active=False,
        # Service destinataire (Espace Tech) : dans l'ancien module, le dossier
        # validé est dispatché vers DRH, DAF et SG (3 services). Le moteur v1 ne
        # supporte qu'un seul target_service ; SG est choisi comme représentant
        # le plus proche — limite documentée, pas un oubli.
        target_service=ServiceType.SG,
    )
    db.session.add(form_def)
    db.session.flush()

    fields = [
        FormField(form_definition_id=form_def.id, name='titre', label='Intitulé du séjour',
                   field_type=FormFieldType.TEXT, is_required=True, order_index=0),
        FormField(form_definition_id=form_def.id, name='date_sejour', label='Date du séjour',
                   field_type=FormFieldType.DATE, is_required=False, order_index=1),
        FormField(form_definition_id=form_def.id, name='service_demandeur', label='Service demandeur',
                   field_type=FormFieldType.TEXT, is_required=False, order_index=2),
        FormField(form_definition_id=form_def.id, name='description', label='Description / Contexte',
                   field_type=FormFieldType.TEXTAREA, is_required=False, order_index=3),
        FormField(form_definition_id=form_def.id, name='file_dossier', label='Dossier de séjour (Word ou PDF)',
                   field_type=FormFieldType.FILE, is_required=True, order_index=4,
                   help_text="Sera transmis aux services après validation."),
        FormField(form_definition_id=form_def.id, name='file_pv_securite', label='PV de Sécurité (PDF)',
                   field_type=FormFieldType.FILE, is_required=False, order_index=5),
        FormField(form_definition_id=form_def.id, name='file_devis', label='Devis (PDF)',
                   field_type=FormFieldType.FILE, is_required=False, order_index=6),
    ]
    for f in fields:
        db.session.add(f)

    steps = [
        # service_source=EMITTER : Manager ou Directeur du service du demandeur
        # lui-même (dynamique), comme la validation N1 hiérarchique de l'ancien
        # système de tickets — pas un rôle fixe choisi une fois pour toutes.
        FormWorkflowStep(form_definition_id=form_def.id, order_index=0, label='Validation Manager/Directeur',
                          validator_role=None, service_source=ServiceSource.EMITTER),
    ]
    for s in steps:
        db.session.add(s)

    db.session.commit()
    print("sejour-v2 créé.")


def seed_publication():
    if FormDefinition.query.filter_by(slug='publication-v2').first():
        print("publication-v2 existe déjà, ignoré.")
        return

    form_def = FormDefinition(
        slug='publication-v2',
        name='Publication (v2)',
        description="Pilote du moteur de formulaires génériques, calqué sur le module Publication existant.",
        is_active=False,
        # target_service=None : ce formulaire ne débouche jamais sur l'Espace
        # Tech/un Ticket — il se termine par "publié", fidèle à l'ancien module.
    )
    db.session.add(form_def)
    db.session.flush()

    fields = [
        FormField(form_definition_id=form_def.id, name='titre', label='Titre',
                   field_type=FormFieldType.TEXT, is_required=True, order_index=0),
        FormField(form_definition_id=form_def.id, name='contenu', label='Contenu',
                   field_type=FormFieldType.TEXTAREA, is_required=True, order_index=1),
        FormField(form_definition_id=form_def.id, name='visuels', label='Visuels',
                   field_type=FormFieldType.MULTI_FILE, is_required=False, order_index=2),
    ]
    for f in fields:
        db.session.add(f)

    # Note : le module Publication existant route sa 2e étape vers un service
    # "COMMUNICATION" qui n'existe pas dans l'enum ServiceType (incohérence
    # préexistante, hors scope). On utilise ADMIN comme validateur de repli
    # pour cette étape pilote.
    steps = [
        FormWorkflowStep(form_definition_id=form_def.id, order_index=0, label='Validation Directeur',
                          validator_role=UserRole.DIRECTEUR),
        FormWorkflowStep(form_definition_id=form_def.id, order_index=1, label='Mise en ligne (Communication)',
                          validator_role=UserRole.ADMIN),
    ]
    for s in steps:
        db.session.add(s)

    db.session.commit()
    print("publication-v2 créé.")


if __name__ == '__main__':
    with app.app_context():
        seed_sejour()
        seed_publication()
        print("Seed des formulaires pilotes terminé.")
