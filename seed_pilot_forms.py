"""Seed des formulaires pilotes du moteur de formulaires génériques.

Crée les définitions de formulaire pilotes (sejour-v2, publication-v2, fcpi-v2,
info-v2, drh-v2, imago-v2, materiel-v2, tech-v2, generaux-v2), reproduisant à
l'identique (catégorie/titre/description/colonnes structurées de Ticket) les
modules codés en dur correspondants, mais éditables depuis /admin/forms.
Idempotent : ne recrée rien si le slug existe déjà — pour mettre à jour un
pilote déjà présent en base, utiliser update_pilot_forms.py. Les formulaires
sont créés désactivés (is_active=False) pour ne pas être visibles des
utilisateurs tant qu'un admin ne les active pas.

Usage : python seed_pilot_forms.py
"""
import json
from app import create_app, db
from app.models import (
    FormDefinition, FormField, FormWorkflowStep, FormFieldType, UserRole, ServiceType, ServiceSource,
    FormDispatchTarget,
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
    db.session.flush()

    # Destinataires : reproduit exactement l'ancien module — le dossier
    # validé est TOUJOURS dispatché vers les 3 mêmes services (DRH, DAF, SG),
    # chacun avec un jeu de fichiers différent (sejour.py:216-234). Le fichier
    # "signé" (ou l'original à défaut) va partout ; devis en plus pour
    # DAF/SG ; PV de sécurité en plus pour SG seulement.
    category = "Dossier de Séjour"
    title_tmpl = "[SEJOUR] $titre"
    desc_prefix = "Séjour : $titre\nService : $service_demandeur\n\n$description"
    dispatch_targets = [
        FormDispatchTarget(
            form_definition_id=form_def.id, label='DRH', target_service=ServiceType.DRH,
            uid_suffix='DRH', ticket_category_template=category, ticket_title_template=title_tmpl,
            ticket_description_template=f"Dossier de séjour à traiter (DRH).\n{desc_prefix}",
            included_file_fields_json=json.dumps(['file_dossier']),
        ),
        FormDispatchTarget(
            form_definition_id=form_def.id, label='DAF', target_service=ServiceType.DAF,
            uid_suffix='DAF', ticket_category_template=category, ticket_title_template=title_tmpl,
            ticket_description_template=f"Dossier de séjour à traiter (DAF).\n{desc_prefix}",
            included_file_fields_json=json.dumps(['file_dossier', 'file_devis']),
        ),
        FormDispatchTarget(
            form_definition_id=form_def.id, label='Secrétariat Général', target_service=ServiceType.SG,
            uid_suffix='SG', ticket_category_template=category, ticket_title_template=title_tmpl,
            ticket_description_template=f"Dossier de séjour à traiter (Secrétariat Général).\n{desc_prefix}",
            included_file_fields_json=json.dumps(['file_dossier', 'file_devis', 'file_pv_securite']),
        ),
    ]
    for t in dispatch_targets:
        db.session.add(t)

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
        # Aucun FormDispatchTarget : ce formulaire ne débouche jamais sur
        # l'Espace Tech/un Ticket — il se termine par "publié", fidèle à
        # l'ancien module.
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


def seed_fcpi():
    if FormDefinition.query.filter_by(slug='fcpi-v2').first():
        print("fcpi-v2 existe déjà, ignoré.")
        return

    form_def = FormDefinition(
        slug='fcpi-v2',
        name='Agent Recruté (FCPI) (v2)',
        description="Pilote du moteur de formulaires génériques, calqué sur le module FCPI existant.",
        is_active=False,
        # Réservé Manager/Directeur/Admin pour la création, comme l'ancien fcpi.py.
        manager_only=True,
        # new_user_service/service_demandeur = service_agent et
        # new_user_fullname/destinataire_materiel = "nom prénom" pour LES 4
        # tickets, identique à create_sub_ticket() qui les fixe sans
        # condition de service (fcpi.py:34-45).
        structured_field_templates_json=json.dumps({
            'new_user_fullname': '$nom_agent $prenom_agent',
            'destinataire_materiel': '$nom_agent $prenom_agent',
            'new_user_service': '$service_agent',
            'service_demandeur': '$service_agent',
        }),
    )
    db.session.add(form_def)
    db.session.flush()

    fields = [
        FormField(form_definition_id=form_def.id, name='nom_agent', label='Nom',
                  field_type=FormFieldType.TEXT, is_required=True, order_index=0),
        FormField(form_definition_id=form_def.id, name='prenom_agent', label='Prénom',
                  field_type=FormFieldType.TEXT, is_required=True, order_index=1),
        FormField(form_definition_id=form_def.id, name='fonction', label='Fonction',
                  field_type=FormFieldType.TEXT, is_required=False, order_index=2),
        FormField(form_definition_id=form_def.id, name='service_agent', label='Service',
                  field_type=FormFieldType.TEXT, is_required=False, order_index=3),
        FormField(form_definition_id=form_def.id, name='uf_agent', label='UF',
                  field_type=FormFieldType.TEXT, is_required=False, order_index=4),
        FormField(form_definition_id=form_def.id, name='date_entree', label="Date d'entrée",
                  field_type=FormFieldType.DATE, is_required=True, order_index=5,
                  maps_to_ticket_field='new_user_date'),
        FormField(form_definition_id=form_def.id, name='contractuel', label='Statut',
                  field_type=FormFieldType.SELECT, is_required=False, order_index=6,
                  options_json='["Titulaire", "Contractuel"]'),
        FormField(form_definition_id=form_def.id, name='date_debut_contrat', label='Date début contrat',
                  field_type=FormFieldType.DATE, is_required=False, order_index=7),
        FormField(form_definition_id=form_def.id, name='date_fin_contrat', label='Date fin contrat',
                  field_type=FormFieldType.DATE, is_required=False, order_index=8),
        FormField(form_definition_id=form_def.id, name='condition_recrutement', label='Condition de recrutement',
                  field_type=FormFieldType.TEXT, is_required=False, order_index=9),
        FormField(form_definition_id=form_def.id, name='temps_travail', label='Temps de travail',
                  field_type=FormFieldType.SELECT, is_required=False, order_index=10,
                  options_json='["Plein", "Partiel", "Non Complet"]'),
        FormField(form_definition_id=form_def.id, name='pourcentage_temps', label='Pourcentage temps de travail',
                  field_type=FormFieldType.NUMBER, is_required=False, order_index=11,
                  help_text="À remplir seulement si temps de travail partiel."),
        FormField(form_definition_id=form_def.id, name='motif_recrutement', label='Motif du recrutement',
                  field_type=FormFieldType.TEXTAREA, is_required=False, order_index=12),
        FormField(form_definition_id=form_def.id, name='simulation_salaire', label='Simulation salaire souhaitée',
                  field_type=FormFieldType.SELECT, is_required=False, order_index=13,
                  options_json='["Non", "Oui"]'),
        FormField(form_definition_id=form_def.id, name='localisation_poste', label='Localisation du poste',
                  field_type=FormFieldType.TEXT, is_required=False, order_index=14,
                  maps_to_ticket_field='lieu_installation'),
        FormField(form_definition_id=form_def.id, name='commentaire_securite', label='Commentaire sécurité',
                  field_type=FormFieldType.TEXTAREA, is_required=False, order_index=15),
        FormField(form_definition_id=form_def.id, name='imago_active', label='Accès IMAGO',
                  field_type=FormFieldType.CHECKBOX, is_required=False, order_index=16),
        FormField(form_definition_id=form_def.id, name='imago_mobilite', label='Mobilité IMAGO',
                  field_type=FormFieldType.TEXT, is_required=False, order_index=17,
                  help_text="À remplir seulement si accès IMAGO coché."),
        FormField(form_definition_id=form_def.id, name='materiels_demandes', label='Matériel demandé',
                  field_type=FormFieldType.MULTI_SELECT, is_required=False, order_index=18,
                  options_json='["Fixe", "Portable", "UC", "Laptop"]',
                  maps_to_ticket_field='materiel_list'),
        FormField(form_definition_id=form_def.id, name='acces_informatique', label='Accès informatique',
                  field_type=FormFieldType.TEXT, is_required=False, order_index=19,
                  maps_to_ticket_field='new_user_acces'),
        FormField(form_definition_id=form_def.id, name='file_cv', label='CV',
                  field_type=FormFieldType.FILE, is_required=False, order_index=20),
        FormField(form_definition_id=form_def.id, name='file_fiche_poste', label='Fiche de poste',
                  field_type=FormFieldType.FILE, is_required=False, order_index=21),
        FormField(form_definition_id=form_def.id, name='file_photo', label='Photo',
                  field_type=FormFieldType.FILE, is_required=False, order_index=22),
    ]
    for f in fields:
        db.session.add(f)
    db.session.flush()

    # Champs conditionnels — désormais reproduits fidèlement (le moteur
    # supporte l'affichage conditionnel) : dates de contrat visibles seulement
    # si "Contractuel" choisi, pourcentage seulement si temps partiel, mobilité
    # IMAGO seulement si accès IMAGO coché.
    # Limite assumée : le pourcentage reste masqué pour "Non Complet" (l'ancien
    # formulaire l'affiche aussi dans ce cas) car le moteur ne supporte qu'une
    # seule valeur de déclenchement par champ conditionnel, pas une liste.
    by_name = {f.name: f for f in fields}
    by_name['date_debut_contrat'].condition_field_id = by_name['contractuel'].id
    by_name['date_debut_contrat'].condition_value = 'Contractuel'
    by_name['date_fin_contrat'].condition_field_id = by_name['contractuel'].id
    by_name['date_fin_contrat'].condition_value = 'Contractuel'
    by_name['pourcentage_temps'].condition_field_id = by_name['temps_travail'].id
    by_name['pourcentage_temps'].condition_value = 'Partiel'
    by_name['imago_mobilite'].condition_field_id = by_name['imago_active'].id

    # Étapes séquentielles, mirroir exact de RecruitmentStatus (WAITING_RH_MGR -> WAITING_RH_DIR).
    steps = [
        FormWorkflowStep(form_definition_id=form_def.id, order_index=0, label='Validation Manager RH',
                          validator_role=UserRole.MANAGER, service_source=ServiceSource.FIXED,
                          validator_service=ServiceType.DRH),
        FormWorkflowStep(form_definition_id=form_def.id, order_index=1, label='Validation Directeur RH',
                          validator_role=UserRole.DIRECTEUR, service_source=ServiceSource.FIXED,
                          validator_service=ServiceType.DRH),
    ]
    for s in steps:
        db.session.add(s)

    # Destinataires : DRH/INFO/SECU systématiques, IMAGO conditionnel —
    # catégorie/titre/description/uid reproduisent exactement create_sub_ticket()
    # et les 4 appels de validate_fcpi() (fcpi.py:229-297). Routage sélectif des
    # fichiers déjà fidèle : CV + fiche de poste -> DRH, photo -> SECU, aucun -> INFO/IMAGO.
    imago_field = by_name['imago_active']
    category_tmpl = 'Nouvel Utilisateur'
    dispatch_targets = [
        FormDispatchTarget(
            form_definition_id=form_def.id, label='DRH', target_service=ServiceType.DRH,
            uid_suffix='DRH', ticket_category_template=category_tmpl,
            ticket_title_template='[FCPI] Dossier Administratif - $nom_agent $prenom_agent',
            ticket_description_template=(
                "Nouvelle arrivée validée.\n"
                "Contrat: $contractuel\n"
                "Temps: $temps_travail ($pourcentage_temps)\n"
                "Salaire simu: $simulation_salaire\n"
                "Condition: $condition_recrutement"
            ),
            included_file_fields_json=json.dumps(['file_cv', 'file_fiche_poste']),
        ),
        FormDispatchTarget(
            form_definition_id=form_def.id, label='Informatique', target_service=ServiceType.INFO,
            uid_suffix='INF', ticket_category_template=category_tmpl,
            ticket_title_template='[FCPI] Matériel & Accès - $nom_agent $prenom_agent',
            ticket_description_template=(
                "Préparation poste informatique.\n"
                "Service: $service_agent\n"
                "Localisation: $localisation_poste\n"
                "Matériel demandé: $materiels_demandes"
            ),
            included_file_fields_json=json.dumps([]),
        ),
        FormDispatchTarget(
            form_definition_id=form_def.id, label='Sécurité', target_service=ServiceType.SECU,
            uid_suffix='SEC', ticket_category_template=category_tmpl,
            ticket_title_template='[FCPI] Badge & Accès - $nom_agent $prenom_agent',
            ticket_description_template=(
                "Création de badge et accès physiques.\n"
                "Localisation: $localisation_poste\n"
                "Commentaire: $commentaire_securite"
            ),
            included_file_fields_json=json.dumps(['file_photo']),
        ),
        FormDispatchTarget(
            form_definition_id=form_def.id, label='IMAGO', target_service=ServiceType.IMAGO,
            condition_field_id=imago_field.id,
            uid_suffix='IMA', ticket_category_template=category_tmpl,
            ticket_title_template='[FCPI] Compte Imago - $nom_agent $prenom_agent',
            ticket_description_template='Création compte IMAGO. Mobilité: $imago_mobilite',
            included_file_fields_json=json.dumps([]),
        ),
    ]
    for t in dispatch_targets:
        db.session.add(t)

    db.session.commit()
    print("fcpi-v2 créé.")


def _common_ticket_fields(form_def_id, include_titre=True):
    """Champs communs aux catégories de tickets standard (Informatique, Technique,
    Généraux, IMAGO, Matériel) : titre/description/service-bureau/téléphone/capture
    d'écran — reproduit new_ticket.html, identique pour toutes ces catégories.
    'hostname' est le nom de champ réel utilisé par l'ancien formulaire pour le
    champ affiché "Service/Bureau" (tickets/new_ticket.html:117) — pas un vrai
    nom de machine malgré son nom de colonne."""
    fields = []
    idx = 0
    if include_titre:
        fields.append(FormField(form_definition_id=form_def_id, name='titre', label='Titre de la demande',
                                 field_type=FormFieldType.TEXT, is_required=True, order_index=idx))
        idx += 1
    fields.append(FormField(form_definition_id=form_def_id, name='description', label='Description détaillée',
                             field_type=FormFieldType.TEXTAREA, is_required=False, order_index=idx))
    idx += 1
    fields.append(FormField(form_definition_id=form_def_id, name='hostname', label='Service/Bureau',
                             field_type=FormFieldType.TEXT, is_required=False, order_index=idx,
                             maps_to_ticket_field='hostname'))
    idx += 1
    fields.append(FormField(form_definition_id=form_def_id, name='tel_demandeur', label='Téléphone de contact',
                             field_type=FormFieldType.TEXT, is_required=False, order_index=idx,
                             maps_to_ticket_field='tel_demandeur'))
    idx += 1
    fields.append(FormField(form_definition_id=form_def_id, name='screenshot', label="Capture d'écran / Photo",
                             field_type=FormFieldType.FILE, is_required=False, order_index=idx))
    return fields


def _seed_simple_ticket_form(slug, name, target_service, category_tmpl, title_tmpl, manager_only=False,
                              include_titre=True):
    """Catégorie de ticket standard sans aucune étape de validation (dispatch
    immédiat à la soumission) : Informatique, DRH, IMAGO."""
    if FormDefinition.query.filter_by(slug=slug).first():
        print(f"{slug} existe déjà, ignoré.")
        return

    form_def = FormDefinition(
        slug=slug, name=name,
        description=f"Pilote du moteur de formulaires génériques, calqué sur la catégorie de ticket « {name} ».",
        is_active=False, manager_only=manager_only,
    )
    db.session.add(form_def)
    db.session.flush()

    for f in _common_ticket_fields(form_def.id, include_titre=include_titre):
        db.session.add(f)

    db.session.add(FormDispatchTarget(
        form_definition_id=form_def.id, label=name, target_service=target_service,
        ticket_category_template=category_tmpl, ticket_title_template=title_tmpl,
        ticket_description_template='$description',
    ))

    db.session.commit()
    print(f"{slug} créé.")


def seed_info():
    # category_ticket réel toujours "Incident Standard" : le menu déroulant de
    # l'ancien formulaire n'offre que cette seule option pour INFO
    # (new_ticket.html:59-65 — l'option "Standard" est explicitement exclue
    # pour ce service).
    _seed_simple_ticket_form('info-v2', 'Informatique (v2)', ServiceType.INFO,
                              category_tmpl='Incident Standard', title_tmpl='$titre')


def seed_imago():
    _seed_simple_ticket_form('imago-v2', 'IMAGO (v2)', ServiceType.IMAGO,
                              category_tmpl='Dépannage Imago', title_tmpl='$titre')


def seed_drh():
    if FormDefinition.query.filter_by(slug='drh-v2').first():
        print("drh-v2 existe déjà, ignoré.")
        return

    form_def = FormDefinition(
        slug='drh-v2', name='DRH (v2)',
        description="Pilote du moteur de formulaires génériques, calqué sur la catégorie de ticket « DRH ».",
        is_active=False,
    )
    db.session.add(form_def)
    db.session.flush()

    # Reproduit le menu titre_drh_select de l'ancien new_ticket.html : le type
    # de demande pilote le titre ET la catégorie du ticket ("Contrat" est la
    # VALEUR réelle soumise par le menu, même si son libellé affiché est
    # "Contrat / Avenant" — tickets.py:124-131). precision_autre n'apparaît
    # que si "Autre" est sélectionné (champ conditionnel) ; son contenu est
    # ajouté à la description (au lieu de remplacer le titre comme l'ancien
    # module) car le moteur ne supporte pas de titre conditionnel — limite
    # assumée pour ne perdre aucune donnée saisie.
    fields = [
        FormField(form_definition_id=form_def.id, name='type_demande', label='Type de demande',
                  field_type=FormFieldType.SELECT, is_required=True, order_index=0,
                  options_json='["Changement de RIB", "Contrat", "Modification d\'information", "Autre"]'),
        FormField(form_definition_id=form_def.id, name='precision_autre', label='Précision (si "Autre")',
                  field_type=FormFieldType.TEXT, is_required=False, order_index=1),
    ]
    for f in fields:
        db.session.add(f)
    db.session.flush()
    fields[1].condition_field_id = fields[0].id
    fields[1].condition_value = 'Autre'

    for f in _common_ticket_fields(form_def.id, include_titre=False):
        f.order_index += 2
        db.session.add(f)

    db.session.add(FormDispatchTarget(
        form_definition_id=form_def.id, label='DRH', target_service=ServiceType.DRH,
        ticket_category_template='$type_demande', ticket_title_template='[DRH] $type_demande',
        ticket_description_template='$description\n$precision_autre',
    ))

    db.session.commit()
    print("drh-v2 créé.")


def seed_materiel():
    """Demande Matériel : réservée Manager/Directeur/Admin, 1 étape de
    validation (jamais sautée, quel que soit le rôle — comme l'ancien système),
    dispatché vers INFO (le matériel est géré par l'Informatique, tickets.py:107-108).
    Titre fixe "Demande de Matériel" : l'ancien champ titre était pré-rempli en
    lecture seule avec ce texte (new_ticket.html:104-106), jamais modifiable par
    l'utilisateur — pas de champ titre dans le pilote non plus."""
    if FormDefinition.query.filter_by(slug='materiel-v2').first():
        print("materiel-v2 existe déjà, ignoré.")
        return

    form_def = FormDefinition(
        slug='materiel-v2', name='Demande Matériel (v2)',
        description="Pilote du moteur de formulaires génériques, calqué sur la catégorie de ticket « Demande Matériel ».",
        is_active=False, manager_only=True,
    )
    db.session.add(form_def)
    db.session.flush()

    for f in _common_ticket_fields(form_def.id, include_titre=False):
        db.session.add(f)

    db.session.add(FormWorkflowStep(
        form_definition_id=form_def.id, order_index=0, label='Validation Informatique',
        service_source=ServiceSource.FIXED, validator_service=ServiceType.INFO,
    ))
    db.session.add(FormDispatchTarget(
        form_definition_id=form_def.id, label='Informatique', target_service=ServiceType.INFO,
        ticket_category_template='Demande Matériel', ticket_title_template='Demande de Matériel',
        ticket_description_template='$description',
    ))

    db.session.commit()
    print("materiel-v2 créé.")


def _seed_two_step_ticket_form(slug, name, target_service):
    """Technique / Généraux : 2 étapes dont le nombre effectif dépend du rôle
    du demandeur (skip_for_author_roles), reproduisant exactement tickets.py:210-216 —
    USER/MANAGER: étape 1 puis 2 ; DIRECTEUR: étape 2 seule ; ADMIN: aucune."""
    if FormDefinition.query.filter_by(slug=slug).first():
        print(f"{slug} existe déjà, ignoré.")
        return

    form_def = FormDefinition(
        slug=slug, name=name,
        description=f"Pilote du moteur de formulaires génériques, calqué sur la catégorie de ticket « {name} ».",
        is_active=False,
    )
    db.session.add(form_def)
    db.session.flush()

    for f in _common_ticket_fields(form_def.id):
        db.session.add(f)

    db.session.add(FormWorkflowStep(
        form_definition_id=form_def.id, order_index=0, label='Validation Équipe',
        service_source=ServiceSource.EMITTER,
        skip_for_author_roles_json='["DIRECTEUR", "ADMIN"]',
    ))
    db.session.add(FormWorkflowStep(
        form_definition_id=form_def.id, order_index=1, label='Validation Service',
        service_source=ServiceSource.FIXED, validator_service=target_service,
        skip_for_author_roles_json='["ADMIN"]',
    ))
    db.session.add(FormDispatchTarget(
        form_definition_id=form_def.id, label=name, target_service=target_service,
        ticket_category_template='Standard', ticket_title_template='$titre',
        ticket_description_template='$description',
    ))

    db.session.commit()
    print(f"{slug} créé.")


def seed_tech():
    _seed_two_step_ticket_form('tech-v2', 'Technique (v2)', ServiceType.TECH)


def seed_generaux():
    _seed_two_step_ticket_form('generaux-v2', 'Généraux (v2)', ServiceType.GEN)


if __name__ == '__main__':
    with app.app_context():
        seed_sejour()
        seed_publication()
        seed_fcpi()
        seed_info()
        seed_drh()
        seed_imago()
        seed_materiel()
        seed_tech()
        seed_generaux()
        print("Seed des formulaires pilotes terminé.")
