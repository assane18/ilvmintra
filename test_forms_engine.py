#!/usr/bin/env python3
"""
=============================================================================
 SUITE DE TESTS — MOTEUR DE FORMULAIRES GÉNÉRIQUES (app/routes/forms.py,
 app/routes/forms_admin.py, app/models.py: FormDefinition & co.)
=============================================================================
 Base SQLite en mémoire, entièrement isolée de la production (aucune
 connexion à la vraie base Postgres, aucun email réel envoyé — voir
 TestConfig.MAIL_SUPPRESS_SEND).

 IMPORTANT — piège connu et corrigé ici : ne JAMAIS envelopper plusieurs
 appels client.get()/client.post() dans un même `with app.app_context():`.
 Flask ne pousse pas de nouveau contexte (donc pas de nouveau `g`) si un
 AppContext pour la même app est déjà sur la pile, et `current_user` reste
 alors bloqué sur la première connexion pour tous les appels suivants — même
 après avoir changé l'utilisateur en session. Les fixtures ci-dessous n'ouvrent
 un app_context que pour de courts blocs de setup/teardown ou de requêtes ORM
 ponctuelles entre deux appels client, jamais en `yield` à travers tout un test.

 Usage :
   cd /var/www/intranet
   source venv/bin/activate
   python -m pytest test_forms_engine.py -v
=============================================================================
"""

import os
import io
import json
import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from app import create_app, db, mail
from app.models import (
    User, UserRole, ServiceType, FormDefinition, FormField, FormFieldType,
    FormWorkflowStep, ServiceSource, FormDispatchTarget, FormSubmission,
    FormSubmissionStatus, Ticket, TicketStatus,
)


class TestConfig:
    TESTING = True
    DEBUG = False
    SECRET_KEY = 'test-forms-engine'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    UPLOAD_FOLDER = '/tmp/intranet_test_uploads_forms_engine'
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    MAIL_SUPPRESS_SEND = True
    MAIL_SERVER = 'localhost'
    MAIL_PORT = 25
    MAIL_USE_TLS = False
    MAIL_USERNAME = None
    MAIL_PASSWORD = None
    MAIL_DEFAULT_SENDER = 'no-reply-intranet@test.lan'
    BASE_URL = 'http://localhost'
    SERVER_NAME = None


# ===========================================================================
#  FIXTURES
# ===========================================================================

@pytest.fixture(scope='session')
def app():
    _app = create_app('development')
    _app.config.from_object(TestConfig)
    # Flask-Mail capture MAIL_SUPPRESS_SEND au moment de init_app(), déjà
    # appelé dans create_app() avec la config réelle (pas encore TestConfig) —
    # on le rappelle pour qu'il recapture le flag avec la config de test,
    # sinon les emails tentent une vraie connexion SMTP malgré le suppress.
    mail.init_app(_app)
    os.makedirs(_app.config['UPLOAD_FOLDER'], exist_ok=True)
    with _app.app_context():
        db.create_all()
    yield _app
    with _app.app_context():
        db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture(scope='function', autouse=True)
def db_session(app):
    """Remet la DB à zéro entre chaque test. N'ouvre PAS d'app_context ambiant
    pendant le corps du test (voir avertissement en tête de fichier)."""
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()


# ===========================================================================
#  HELPERS
# ===========================================================================

_user_counter = [0]


def make_user(app, role=UserRole.USER, username=None,
              allowed_services=None, origin_services=None):
    if username is None:
        _user_counter[0] += 1
        username = f'testuser{_user_counter[0]}'
    with app.app_context():
        u = User(username=username, fullname=username, email=f'{username}@test.lan', role=role)
        if allowed_services:
            u.set_allowed_services(allowed_services)
        if origin_services:
            u.set_origin_services(origin_services)
        db.session.add(u)
        db.session.commit()
        return u.id


def login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def get_form(app, form_id):
    with app.app_context():
        return FormDefinition.query.get(form_id)


def get_submission(app, submission_id):
    with app.app_context():
        return FormSubmission.query.get(submission_id)


def latest_submission(app, form_id):
    with app.app_context():
        return FormSubmission.query.filter_by(form_definition_id=form_id) \
            .order_by(FormSubmission.id.desc()).first()


def make_simple_form(app, slug='test-form', manager_only=False, fields=None,
                      steps=None, dispatch_targets=None, active=True,
                      structured_field_templates=None):
    """Construit une FormDefinition complète en une fois. `fields` est une
    liste de dicts (name, label, field_type, is_required, options, help_text,
    condition_on, condition_value, maps_to_ticket_field). `steps` une liste de
    dicts (label, validator_role, service_source, validator_service,
    skip_for_author_roles). `dispatch_targets` une liste de dicts (label,
    target_service, condition_on, included_file_fields, uid_suffix,
    ticket_category_template, ticket_title_template,
    ticket_description_template). `structured_field_templates` un dict
    {colonne_ticket: "modèle $champ"} appliqué à FormDefinition."""
    with app.app_context():
        form_def = FormDefinition(
            slug=slug, name=slug, is_active=active, manager_only=manager_only,
            structured_field_templates_json=json.dumps(structured_field_templates) if structured_field_templates else None,
        )
        db.session.add(form_def)
        db.session.flush()

        field_objs = {}
        for i, fdef in enumerate(fields or []):
            f = FormField(
                form_definition_id=form_def.id, name=fdef['name'], label=fdef.get('label', fdef['name']),
                field_type=fdef['field_type'], is_required=fdef.get('is_required', False),
                options_json=json.dumps(fdef['options']) if fdef.get('options') else None,
                help_text=fdef.get('help_text'), order_index=i,
                maps_to_ticket_field=fdef.get('maps_to_ticket_field'),
            )
            db.session.add(f)
            db.session.flush()
            field_objs[f.name] = f

        for fdef in (fields or []):
            if fdef.get('condition_on'):
                field_objs[fdef['name']].condition_field_id = field_objs[fdef['condition_on']].id
                values = fdef.get('condition_values')
                if values is None and fdef.get('condition_value') is not None:
                    values = [fdef['condition_value']]
                field_objs[fdef['name']].condition_values_json = json.dumps(values) if values else None

        for i, sdef in enumerate(steps or []):
            db.session.add(FormWorkflowStep(
                form_definition_id=form_def.id, order_index=i, label=sdef.get('label', f'Étape {i}'),
                validator_role=sdef.get('validator_role'),
                service_source=sdef.get('service_source', ServiceSource.FIXED),
                validator_service=sdef.get('validator_service'),
                skip_for_author_roles_json=json.dumps(sdef.get('skip_for_author_roles', [])),
            ))

        for tdef in (dispatch_targets or []):
            included = tdef.get('included_file_fields')
            included_mapped = tdef.get('included_mapped_fields')
            included_description = tdef.get('included_description_fields')
            db.session.add(FormDispatchTarget(
                form_definition_id=form_def.id, label=tdef.get('label', tdef['target_service'].value),
                target_service=tdef['target_service'],
                condition_field_id=field_objs[tdef['condition_on']].id if tdef.get('condition_on') else None,
                included_file_fields_json=json.dumps(included) if included is not None else None,
                included_mapped_fields_json=json.dumps(included_mapped) if included_mapped is not None else None,
                included_description_fields_json=json.dumps(included_description) if included_description is not None else None,
                uid_suffix=tdef.get('uid_suffix'),
                ticket_category_template=tdef.get('ticket_category_template'),
                ticket_title_template=tdef.get('ticket_title_template'),
                ticket_description_template=tdef.get('ticket_description_template'),
            ))

        db.session.commit()
        return form_def.id


# ===========================================================================
#  TESTS — TYPES DE CHAMPS ET VISIBILITÉ CONDITIONNELLE
# ===========================================================================

class TestConditionalFields:
    def test_field_hidden_by_default_is_not_required(self, app, client):
        form_id = make_simple_form(app, slug='cond-form', fields=[
            {'name': 'active', 'label': 'Actif', 'field_type': FormFieldType.CHECKBOX},
            {'name': 'precision', 'label': 'Précision', 'field_type': FormFieldType.TEXT,
             'is_required': True, 'condition_on': 'active'},
        ])
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)

        # 'active' non coché -> 'precision' masqué -> pas d'erreur malgré is_required
        r = client.post('/forms/cond-form/new', data={}, follow_redirects=True)
        assert r.status_code == 200
        sub = latest_submission(app, form_id)
        assert sub is not None
        assert sub.get_data()['precision'] == ''
        assert sub.get_data()['active'] is False

    def test_field_visible_when_condition_met_stores_value(self, app, client):
        form_id = make_simple_form(app, slug='cond-form2', fields=[
            {'name': 'active', 'label': 'Actif', 'field_type': FormFieldType.CHECKBOX},
            {'name': 'precision', 'label': 'Précision', 'field_type': FormFieldType.TEXT,
             'is_required': True, 'condition_on': 'active'},
        ])
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)

        r = client.post('/forms/cond-form2/new', data={'active': 'on', 'precision': 'Détail important'},
                         follow_redirects=True)
        assert r.status_code == 200
        sub = latest_submission(app, form_id)
        assert sub.get_data()['active'] is True
        assert sub.get_data()['precision'] == 'Détail important'

    def test_select_based_condition(self, app, client):
        form_id = make_simple_form(app, slug='cond-form3', fields=[
            {'name': 'type_demande', 'label': 'Type', 'field_type': FormFieldType.SELECT,
             'options': ['A', 'Autre']},
            {'name': 'precision', 'label': 'Précision', 'field_type': FormFieldType.TEXT,
             'condition_on': 'type_demande', 'condition_value': 'Autre'},
        ])
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)

        r = client.post('/forms/cond-form3/new', data={'type_demande': 'A', 'precision': 'ignoré'},
                         follow_redirects=True)
        assert get_submission(app, latest_submission(app, form_id).id).get_data()['precision'] == ''

        r = client.post('/forms/cond-form3/new', data={'type_demande': 'Autre', 'precision': 'gardé'},
                         follow_redirects=True)
        sub = latest_submission(app, form_id)
        assert sub.get_data()['precision'] == 'gardé'

    def test_select_condition_with_multiple_trigger_values(self, app, client):
        """condition_values_json permet plusieurs valeurs déclenchantes (ex:
        CDI/Mutation/Détachement déclenchent tous "date de prise de poste"),
        contrairement à l'ancien condition_value qui n'en acceptait qu'une."""
        form_id = make_simple_form(app, slug='cond-form4', fields=[
            {'name': 'statut', 'label': 'Statut', 'field_type': FormFieldType.SELECT,
             'options': ['CDI', 'CDD', 'Mutation', 'Détachement']},
            {'name': 'date_prise_poste', 'label': 'Date de prise de poste', 'field_type': FormFieldType.TEXT,
             'condition_on': 'statut', 'condition_values': ['CDI', 'Mutation', 'Détachement']},
        ])
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)

        client.post('/forms/cond-form4/new', data={'statut': 'CDD', 'date_prise_poste': 'ignoré'},
                     follow_redirects=True)
        assert get_submission(app, latest_submission(app, form_id).id).get_data()['date_prise_poste'] == ''

        for statut in ['CDI', 'Mutation', 'Détachement']:
            client.post('/forms/cond-form4/new', data={'statut': statut, 'date_prise_poste': '01/01/2026'},
                         follow_redirects=True)
            sub = latest_submission(app, form_id)
            assert sub.get_data()['date_prise_poste'] == '01/01/2026', f"échoue pour statut={statut}"

    def test_multi_select_field_stores_list(self, app, client):
        form_id = make_simple_form(app, slug='multisel-form', fields=[
            {'name': 'materiel', 'label': 'Matériel', 'field_type': FormFieldType.MULTI_SELECT,
             'options': ['Fixe', 'Portable', 'UC']},
        ])
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        r = client.post('/forms/multisel-form/new', data={'materiel': ['Fixe', 'UC']}, follow_redirects=True)
        assert r.status_code == 200
        sub = latest_submission(app, form_id)
        assert set(sub.get_data()['materiel']) == {'Fixe', 'UC'}


# ===========================================================================
#  TESTS — RÉSOLUTION DU VALIDATEUR (FIXED / EMITTER) ET SAUT DE RÔLE
# ===========================================================================

class TestWorkflowValidation:
    def test_fixed_step_requires_matching_allowed_service(self, app, client):
        form_id = make_simple_form(app, slug='fixed-form',
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT, 'is_required': True}],
            steps=[{'label': 'Validation', 'service_source': ServiceSource.FIXED, 'validator_service': ServiceType.DRH}],
        )
        author_id = make_user(app, role=UserRole.USER, username='auteur1')
        wrong_validator_id = make_user(app, role=UserRole.MANAGER, username='mgr_info', allowed_services=['INFORMATIQUE'])
        right_validator_id = make_user(app, role=UserRole.MANAGER, username='mgr_drh', allowed_services=['DRH'])

        login(client, author_id)
        client.post('/forms/fixed-form/new', data={'titre': 'Test'}, follow_redirects=True)
        sub_id = latest_submission(app, form_id).id

        login(client, wrong_validator_id)
        r = client.post(f'/forms/submission/{sub_id}/validate/validate', follow_redirects=True)
        assert get_submission(app, sub_id).status == FormSubmissionStatus.IN_PROGRESS, \
            "un manager d'un autre service ne devrait pas pouvoir valider"

        login(client, right_validator_id)
        client.post(f'/forms/submission/{sub_id}/validate/validate', follow_redirects=True)
        assert get_submission(app, sub_id).status == FormSubmissionStatus.DONE

    def test_emitter_step_requires_shared_origin_service(self, app, client):
        form_id = make_simple_form(app, slug='emitter-form',
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}],
            steps=[{'label': 'Validation équipe', 'service_source': ServiceSource.EMITTER}],
        )
        author_id = make_user(app, role=UserRole.USER, username='auteur2', origin_services=['TECHNIQUE'])
        wrong_id = make_user(app, role=UserRole.MANAGER, username='mgr_gen', origin_services=['GENERAUX'])
        right_id = make_user(app, role=UserRole.MANAGER, username='mgr_tech', origin_services=['TECHNIQUE'])

        login(client, author_id)
        client.post('/forms/emitter-form/new', data={'titre': 'Test'}, follow_redirects=True)
        sub_id = latest_submission(app, form_id).id

        login(client, wrong_id)
        client.post(f'/forms/submission/{sub_id}/validate/validate', follow_redirects=True)
        assert get_submission(app, sub_id).status == FormSubmissionStatus.IN_PROGRESS

        login(client, right_id)
        client.post(f'/forms/submission/{sub_id}/validate/validate', follow_redirects=True)
        assert get_submission(app, sub_id).status == FormSubmissionStatus.DONE

    def test_step_without_explicit_role_accepts_manager_or_directeur(self, app, client):
        form_id = make_simple_form(app, slug='anyrole-form',
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}],
            steps=[{'label': 'Validation', 'service_source': ServiceSource.FIXED, 'validator_service': ServiceType.GEN}],
        )
        author_id = make_user(app, role=UserRole.USER, username='auteur3')
        directeur_id = make_user(app, role=UserRole.DIRECTEUR, username='dir_gen', allowed_services=['GENERAUX'])

        login(client, author_id)
        client.post('/forms/anyrole-form/new', data={'titre': 'Test'}, follow_redirects=True)
        sub_id = latest_submission(app, form_id).id

        login(client, directeur_id)
        client.post(f'/forms/submission/{sub_id}/validate/validate', follow_redirects=True)
        assert get_submission(app, sub_id).status == FormSubmissionStatus.DONE


class TestSkipForAuthorRole:
    def _make_two_step_form(self, app, slug):
        return make_simple_form(app, slug=slug,
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}],
            steps=[
                {'label': 'Équipe', 'service_source': ServiceSource.EMITTER,
                 'skip_for_author_roles': ['DIRECTEUR', 'ADMIN']},
                {'label': 'Service', 'service_source': ServiceSource.FIXED, 'validator_service': ServiceType.TECH,
                 'skip_for_author_roles': ['ADMIN']},
            ],
            dispatch_targets=[{'target_service': ServiceType.TECH}],
        )

    def test_user_starts_at_first_step(self, app, client):
        form_id = self._make_two_step_form(app, 'skip-user')
        uid = make_user(app, role=UserRole.USER, username='u_skip1')
        login(client, uid)
        client.post('/forms/skip-user/new', data={'titre': 'x'}, follow_redirects=True)
        sub = latest_submission(app, form_id)
        assert sub.current_step_index == 0
        assert sub.status == FormSubmissionStatus.IN_PROGRESS

    def test_directeur_skips_first_step(self, app, client):
        form_id = self._make_two_step_form(app, 'skip-dir')
        uid = make_user(app, role=UserRole.DIRECTEUR, username='d_skip1')
        login(client, uid)
        client.post('/forms/skip-dir/new', data={'titre': 'x'}, follow_redirects=True)
        sub = latest_submission(app, form_id)
        assert sub.current_step_index == 1
        assert sub.status == FormSubmissionStatus.IN_PROGRESS

    def test_admin_skips_everything_ticket_created_immediately(self, app, client):
        form_id = self._make_two_step_form(app, 'skip-admin')
        uid = make_user(app, role=UserRole.ADMIN, username='a_skip1')
        login(client, uid)
        client.post('/forms/skip-admin/new', data={'titre': 'x'}, follow_redirects=True)
        sub = latest_submission(app, form_id)
        assert sub.status == FormSubmissionStatus.DONE
        with app.app_context():
            tickets = FormSubmission.query.get(sub.id).get_tickets()
            assert len(tickets) == 1
            assert tickets[0].status == TicketStatus.PENDING
            assert tickets[0].target_service == ServiceType.TECH


# ===========================================================================
#  TESTS — DISPATCH MULTIPLE CONDITIONNEL + ROUTAGE SÉLECTIF DES FICHIERS
# ===========================================================================

class TestMultiDispatch:
    def test_conditional_dispatch_target_count(self, app, client):
        form_id = make_simple_form(app, slug='dispatch-form',
            fields=[
                {'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT},
                {'name': 'imago', 'label': 'IMAGO', 'field_type': FormFieldType.CHECKBOX},
            ],
            dispatch_targets=[
                {'label': 'DRH', 'target_service': ServiceType.DRH},
                {'label': 'INFO', 'target_service': ServiceType.INFO},
                {'label': 'IMAGO', 'target_service': ServiceType.IMAGO, 'condition_on': 'imago'},
            ],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)

        client.post('/forms/dispatch-form/new', data={'titre': 'sans imago'}, follow_redirects=True)
        sub1 = latest_submission(app, form_id)
        assert len(sub1.get_tickets()) == 2

        client.post('/forms/dispatch-form/new', data={'titre': 'avec imago', 'imago': 'on'}, follow_redirects=True)
        sub2 = latest_submission(app, form_id)
        tickets2 = sub2.get_tickets()
        assert len(tickets2) == 3
        assert {t.target_service for t in tickets2} == {ServiceType.DRH, ServiceType.INFO, ServiceType.IMAGO}

    def test_selective_file_routing(self, app, client):
        form_id = make_simple_form(app, slug='fileroute-form',
            fields=[
                {'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT},
                {'name': 'file_a', 'label': 'Fichier A', 'field_type': FormFieldType.FILE},
                {'name': 'file_b', 'label': 'Fichier B', 'field_type': FormFieldType.FILE},
            ],
            dispatch_targets=[
                {'label': 'ServiceA', 'target_service': ServiceType.DRH, 'included_file_fields': ['file_a']},
                {'label': 'ServiceB', 'target_service': ServiceType.SECU, 'included_file_fields': ['file_b']},
                {'label': 'ServiceC', 'target_service': ServiceType.INFO},  # None = tous les fichiers
            ],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)

        data = {
            'titre': 'Test routage',
            'file_a': (io.BytesIO(b'contenu A'), 'a.pdf'),
            'file_b': (io.BytesIO(b'contenu B'), 'b.pdf'),
        }
        r = client.post('/forms/fileroute-form/new', data=data, content_type='multipart/form-data', follow_redirects=True)
        assert r.status_code == 200

        sub = latest_submission(app, form_id)
        tickets = {t.target_service: t for t in sub.get_tickets()}

        with app.app_context():
            drh_ticket = Ticket.query.get(tickets[ServiceType.DRH].id)
            secu_ticket = Ticket.query.get(tickets[ServiceType.SECU].id)
            info_ticket = Ticket.query.get(tickets[ServiceType.INFO].id)
            assert drh_ticket.get_daf_files() == ['a.pdf']
            assert secu_ticket.get_daf_files() == ['b.pdf']
            assert set(info_ticket.get_daf_files()) == {'a.pdf', 'b.pdf'}

    def test_selective_description_scoping(self, app, client):
        """Une donnée sensible (ex: DRH) ne doit pas fuiter dans la
        description générique d'un ticket destiné à un autre service."""
        form_id = make_simple_form(app, slug='descscope-form',
            fields=[
                {'name': 'nom_agent', 'label': 'Nom', 'field_type': FormFieldType.TEXT},
                {'name': 'salaire', 'label': 'Simulation salaire', 'field_type': FormFieldType.TEXT},
            ],
            dispatch_targets=[
                {'label': 'SECU', 'target_service': ServiceType.SECU, 'included_description_fields': ['nom_agent']},
                {'label': 'DRH', 'target_service': ServiceType.DRH},  # None = description complète
            ],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/descscope-form/new', data={'nom_agent': 'Traoré', 'salaire': '2500€ confidentiel'},
                     follow_redirects=True)
        sub = latest_submission(app, form_id)
        tickets = {t.target_service: t for t in sub.get_tickets()}

        with app.app_context():
            secu_ticket = Ticket.query.get(tickets[ServiceType.SECU].id)
            drh_ticket = Ticket.query.get(tickets[ServiceType.DRH].id)
            assert 'Traoré' in secu_ticket.description
            assert 'confidentiel' not in secu_ticket.description
            assert 'confidentiel' in drh_ticket.description


# ===========================================================================
#  TESTS — RESTRICTION manager_only, REFUS, ZÉRO ÉTAPE
# ===========================================================================

class TestAccessAndLifecycle:
    def test_manager_only_blocks_user(self, app, client):
        make_simple_form(app, slug='restricted-form', manager_only=True,
                          fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}])
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        r = client.get('/forms/restricted-form/new')
        assert r.status_code == 403

    def test_manager_only_allows_manager(self, app, client):
        make_simple_form(app, slug='restricted-form2', manager_only=True,
                          fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}])
        uid = make_user(app, role=UserRole.MANAGER)
        login(client, uid)
        r = client.get('/forms/restricted-form2/new')
        assert r.status_code == 200

    def test_zero_step_form_finalizes_immediately(self, app, client):
        form_id = make_simple_form(app, slug='zerostep-form',
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}],
            dispatch_targets=[{'target_service': ServiceType.INFO}],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/zerostep-form/new', data={'titre': 'x'}, follow_redirects=True)
        sub = latest_submission(app, form_id)
        assert sub.status == FormSubmissionStatus.DONE
        assert len(sub.get_tickets()) == 1

    def test_refuse_sets_status_and_reason(self, app, client):
        form_id = make_simple_form(app, slug='refuse-form',
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}],
            steps=[{'label': 'Validation', 'service_source': ServiceSource.FIXED, 'validator_service': ServiceType.DRH}],
        )
        author_id = make_user(app, role=UserRole.USER)
        validator_username = 'refuse_validator'
        validator_id = make_user(app, role=UserRole.MANAGER, username=validator_username, allowed_services=['DRH'])

        login(client, author_id)
        client.post('/forms/refuse-form/new', data={'titre': 'x'}, follow_redirects=True)
        sub_id = latest_submission(app, form_id).id

        login(client, validator_id)
        client.post(f'/forms/submission/{sub_id}/validate/refuse',
                    data={'refusal_reason': 'Pas assez détaillé'}, follow_redirects=True)
        sub = get_submission(app, sub_id)
        assert sub.status == FormSubmissionStatus.REFUSED
        # Préfixé "Refusé par <validateur> : <motif>", identique au format de
        # l'ancien fcpi.py (validate_fcpi) — voir _create_one_ticket/validate_submission.
        assert sub.refusal_reason == f'Refusé par {validator_username} : Pas assez détaillé'


# ===========================================================================
#  TESTS — EMAILS (interceptés via mail.record_messages(), aucun envoi réel)
# ===========================================================================

class TestEmails:
    def test_email_sent_on_step_pending_and_on_ticket_creation(self, app, client):
        form_id = make_simple_form(app, slug='email-form',
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}],
            steps=[{'label': 'Validation', 'service_source': ServiceSource.FIXED, 'validator_service': ServiceType.DRH}],
            dispatch_targets=[{'target_service': ServiceType.DRH}],
        )
        author_id = make_user(app, role=UserRole.USER)
        validator_id = make_user(app, role=UserRole.MANAGER, allowed_services=['DRH'])

        with mail.record_messages() as outbox:
            login(client, author_id)
            client.post('/forms/email-form/new', data={'titre': 'x'}, follow_redirects=True)
            assert len(outbox) == 1, "un email d'alerte devrait partir au validateur de l'étape"
            assert '[À valider]' in outbox[0].subject

            sub_id = latest_submission(app, form_id).id
            login(client, validator_id)
            client.post(f'/forms/submission/{sub_id}/validate/validate', follow_redirects=True)
            assert len(outbox) == 2, "un email devrait partir au service destinataire à la création du ticket"
            assert '[Nouveau]' in outbox[1].subject

    def test_email_sent_on_refusal(self, app, client):
        form_id = make_simple_form(app, slug='email-refuse-form',
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}],
            steps=[{'label': 'Validation', 'service_source': ServiceSource.FIXED, 'validator_service': ServiceType.DRH}],
        )
        author_id = make_user(app, role=UserRole.USER)
        validator_id = make_user(app, role=UserRole.MANAGER, allowed_services=['DRH'])

        login(client, author_id)
        client.post('/forms/email-refuse-form/new', data={'titre': 'x'}, follow_redirects=True)
        sub_id = latest_submission(app, form_id).id

        with mail.record_messages() as outbox:
            login(client, validator_id)
            client.post(f'/forms/submission/{sub_id}/validate/refuse',
                        data={'refusal_reason': 'motif'}, follow_redirects=True)
            assert len(outbox) == 1
            assert '[Refusé]' in outbox[0].subject


# ===========================================================================
#  TESTS — PARITÉ DE TICKET (catégorie/titre/description/uid/colonnes
#  structurées), fonctionnalité ajoutée pour reproduire fidèlement les
#  anciens modules (FCPI, tickets standard) dans le moteur générique.
# ===========================================================================

class TestTicketParity:
    def test_category_title_description_templates_rendered(self, app, client):
        form_id = make_simple_form(app, slug='parity-form',
            fields=[
                {'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT},
                {'name': 'description', 'label': 'Description', 'field_type': FormFieldType.TEXTAREA},
            ],
            dispatch_targets=[{
                'target_service': ServiceType.INFO, 'uid_suffix': 'INF',
                'ticket_category_template': 'Incident Standard',
                'ticket_title_template': '$titre',
                'ticket_description_template': '$description',
            }],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/parity-form/new',
                     data={'titre': 'Mon titre libre', 'description': 'Le détail complet'},
                     follow_redirects=True)
        sub = latest_submission(app, form_id)
        ticket = sub.get_tickets()[0]
        with app.app_context():
            t = Ticket.query.get(ticket.id)
            assert t.category_ticket == 'Incident Standard'
            assert t.title == 'Mon titre libre'
            assert t.description == 'Le détail complet'
            assert t.uid_public == f'F{sub.id}-INF'

    def test_default_category_when_no_template_falls_back_to_standard(self, app, client):
        form_id = make_simple_form(app, slug='parity-default-form',
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}],
            dispatch_targets=[{'target_service': ServiceType.INFO}],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/parity-default-form/new', data={'titre': 'x'}, follow_redirects=True)
        sub = latest_submission(app, form_id)
        with app.app_context():
            t = Ticket.query.get(sub.get_tickets()[0].id)
            assert t.category_ticket == 'Standard'

    def test_field_maps_to_structured_ticket_column(self, app, client):
        form_id = make_simple_form(app, slug='mapping-form',
            fields=[
                {'name': 'localisation', 'label': 'Lieu', 'field_type': FormFieldType.TEXT,
                 'maps_to_ticket_field': 'lieu_installation'},
                {'name': 'materiel', 'label': 'Matériel', 'field_type': FormFieldType.MULTI_SELECT,
                 'options': ['Fixe', 'Portable'], 'maps_to_ticket_field': 'materiel_list'},
            ],
            dispatch_targets=[{'target_service': ServiceType.INFO}],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/mapping-form/new',
                     data={'localisation': 'Bureau 12', 'materiel': ['Fixe', 'Portable']},
                     follow_redirects=True)
        sub = latest_submission(app, form_id)
        with app.app_context():
            t = Ticket.query.get(sub.get_tickets()[0].id)
            assert t.lieu_installation == 'Bureau 12'
            # MULTI_SELECT (liste Python) doit être aplati en texte séparé par
            # virgules dans une colonne Ticket texte, comme l'ancien FCPI
            # (",".join(request.form.getlist(...))) — pas une repr() de liste.
            assert t.materiel_list == 'Fixe,Portable'

    def test_structured_field_template_combines_multiple_fields(self, app, client):
        form_id = make_simple_form(app, slug='combined-form',
            fields=[
                {'name': 'nom', 'label': 'Nom', 'field_type': FormFieldType.TEXT},
                {'name': 'prenom', 'label': 'Prénom', 'field_type': FormFieldType.TEXT},
            ],
            dispatch_targets=[{'target_service': ServiceType.DRH}],
            structured_field_templates={'new_user_fullname': '$nom $prenom'},
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/combined-form/new', data={'nom': 'Traoré', 'prenom': 'Assane'}, follow_redirects=True)
        sub = latest_submission(app, form_id)
        with app.app_context():
            t = Ticket.query.get(sub.get_tickets()[0].id)
            assert t.new_user_fullname == 'Traoré Assane'

    def test_structured_field_template_applies_to_every_dispatch_target(self, app, client):
        """Comme l'ancien fcpi.py qui fixe new_user_fullname identiquement sur
        les 4 tickets créés, sans condition de service."""
        form_id = make_simple_form(app, slug='combined-multi-form',
            fields=[
                {'name': 'nom', 'label': 'Nom', 'field_type': FormFieldType.TEXT},
                {'name': 'prenom', 'label': 'Prénom', 'field_type': FormFieldType.TEXT},
            ],
            dispatch_targets=[
                {'label': 'DRH', 'target_service': ServiceType.DRH, 'uid_suffix': 'DRH'},
                {'label': 'INFO', 'target_service': ServiceType.INFO, 'uid_suffix': 'INF'},
            ],
            structured_field_templates={'new_user_fullname': '$nom $prenom'},
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/combined-multi-form/new', data={'nom': 'Traoré', 'prenom': 'Assane'},
                     follow_redirects=True)
        sub = latest_submission(app, form_id)
        with app.app_context():
            for ticket_ref in sub.get_tickets():
                t = Ticket.query.get(ticket_ref.id)
                assert t.new_user_fullname == 'Traoré Assane'

    def test_mapped_field_applies_to_all_targets_when_not_scoped(self, app, client):
        """Comportement par défaut inchangé : sans included_mapped_fields,
        un champ mappé s'applique à tous les tickets de la soumission."""
        form_id = make_simple_form(app, slug='mapping-unscoped-form',
            fields=[
                {'name': 'lieu', 'label': 'Lieu', 'field_type': FormFieldType.TEXT,
                 'maps_to_ticket_field': 'lieu_installation'},
            ],
            dispatch_targets=[
                {'label': 'DRH', 'target_service': ServiceType.DRH, 'uid_suffix': 'DRH'},
                {'label': 'INFO', 'target_service': ServiceType.INFO, 'uid_suffix': 'INF'},
            ],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/mapping-unscoped-form/new', data={'lieu': 'Bureau 12'}, follow_redirects=True)
        sub = latest_submission(app, form_id)
        with app.app_context():
            for ticket_ref in sub.get_tickets():
                t = Ticket.query.get(ticket_ref.id)
                assert t.lieu_installation == 'Bureau 12'

    def test_mapped_field_scoped_to_one_dispatch_target(self, app, client):
        """Reproduit le bug FCPI trouvé le 2026-09-16 : materiel_list/
        lieu_installation ne doivent apparaître QUE sur le ticket INFO (+lieu
        sur SECU), jamais sur DRH/IMAGO. Vérifie que included_mapped_fields
        scope bien maps_to_ticket_field par destinataire."""
        form_id = make_simple_form(app, slug='fcpi-scoping-form',
            fields=[
                {'name': 'materiel', 'label': 'Matériel', 'field_type': FormFieldType.MULTI_SELECT,
                 'options': ['Fixe', 'Portable'], 'maps_to_ticket_field': 'materiel_list'},
                {'name': 'lieu', 'label': 'Lieu', 'field_type': FormFieldType.TEXT,
                 'maps_to_ticket_field': 'lieu_installation'},
            ],
            dispatch_targets=[
                {'label': 'DRH', 'target_service': ServiceType.DRH, 'uid_suffix': 'DRH',
                 'included_mapped_fields': []},
                {'label': 'INFO', 'target_service': ServiceType.INFO, 'uid_suffix': 'INF',
                 'included_mapped_fields': ['materiel', 'lieu']},
                {'label': 'SECU', 'target_service': ServiceType.SECU, 'uid_suffix': 'SEC',
                 'included_mapped_fields': ['lieu']},
            ],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/fcpi-scoping-form/new',
                     data={'materiel': ['Fixe', 'Portable'], 'lieu': 'Bureau 12'},
                     follow_redirects=True)
        sub = latest_submission(app, form_id)
        tickets = {t.target_service: t for t in sub.get_tickets()}

        with app.app_context():
            drh_ticket = Ticket.query.get(tickets[ServiceType.DRH].id)
            info_ticket = Ticket.query.get(tickets[ServiceType.INFO].id)
            secu_ticket = Ticket.query.get(tickets[ServiceType.SECU].id)

            assert drh_ticket.materiel_list is None
            assert drh_ticket.lieu_installation is None

            assert info_ticket.materiel_list == 'Fixe,Portable'
            assert info_ticket.lieu_installation == 'Bureau 12'

            assert secu_ticket.materiel_list is None
            assert secu_ticket.lieu_installation == 'Bureau 12'

    def test_single_step_then_ticket_dispatch_to_new_service(self, app, client):
        """Reproduit la config réelle de publication-v2 après correction du
        2026-09-21 : une seule étape (Validation Directeur, n'importe quel
        DIRECTEUR), puis un ticket dispatché vers le service COMMUNICATION —
        remplace l'ancienne 2e étape validator_role=ADMIN qui ne correspondait
        à aucun service COMMUNICATION réel (celui-ci n'existait pas encore)."""
        form_id = make_simple_form(app, slug='publication-like-form',
            fields=[{'name': 'titre', 'label': 'Titre', 'field_type': FormFieldType.TEXT}],
            steps=[{'label': 'Validation Directeur', 'validator_role': UserRole.DIRECTEUR}],
            dispatch_targets=[
                {'label': 'Communication', 'target_service': ServiceType.COMMUNICATION,
                 'uid_suffix': 'COM', 'ticket_title_template': '[Publication] $titre'},
            ],
        )
        author_id = make_user(app, role=UserRole.MANAGER, username='auteur_pub')
        director_id = make_user(app, role=UserRole.DIRECTEUR, username='directeur_pub')

        login(client, author_id)
        client.post('/forms/publication-like-form/new', data={'titre': 'Nouvelle offre de stage'},
                     follow_redirects=True)
        sub_id = latest_submission(app, form_id).id
        assert get_submission(app, sub_id).status == FormSubmissionStatus.IN_PROGRESS

        login(client, director_id)
        client.post(f'/forms/submission/{sub_id}/validate/validate', follow_redirects=True)

        with app.app_context():
            sub = FormSubmission.query.get(sub_id)
            assert sub.status == FormSubmissionStatus.DONE
            tickets = sub.get_tickets()
            assert len(tickets) == 1
            t = Ticket.query.get(tickets[0].id)
            assert t.target_service == ServiceType.COMMUNICATION
            assert t.title == '[Publication] Nouvelle offre de stage'
            assert t.status == TicketStatus.PENDING
            assert t.solver_id is None
            # category_ticket non configuré -> repli 'Standard' (pool_standard
            # côté solver_dashboard, donc visible pour un solver COMMUNICATION).
            assert t.category_ticket == 'Standard'

    def test_date_field_mapped_to_datetime_column_is_converted(self, app, client):
        form_id = make_simple_form(app, slug='date-mapping-form',
            fields=[{'name': 'date_entree', 'label': "Date d'entrée", 'field_type': FormFieldType.DATE,
                     'maps_to_ticket_field': 'new_user_date'}],
            dispatch_targets=[{'target_service': ServiceType.DRH}],
        )
        uid = make_user(app, role=UserRole.USER)
        login(client, uid)
        client.post('/forms/date-mapping-form/new', data={'date_entree': '2026-09-01'}, follow_redirects=True)
        sub = latest_submission(app, form_id)
        with app.app_context():
            t = Ticket.query.get(sub.get_tickets()[0].id)
            assert t.new_user_date is not None
            assert t.new_user_date.strftime('%Y-%m-%d') == '2026-09-01'


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
