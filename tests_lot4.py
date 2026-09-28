#!/usr/bin/env python3
"""
=============================================================================
 TESTS — LOT 4 : builder de formulaires pour non-technicien
 (app/routes/forms_admin.py : duplication complète d'un formulaire et aperçu
 en lecture seule ; app/templates/forms_admin/preview.html ;
 app/templates/forms/_submission_fields.html partagé avec la page de dépôt)
=============================================================================
 Base SQLite en mémoire, entièrement isolée de la production (mêmes garde-fous
 que tests_intranet.py / test_forms_engine.py). Aucun email réel envoyé.

 Usage :
   cd /var/www/intranet && source venv/bin/activate
   python -m pytest tests_lot4.py -v
=============================================================================
"""

import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Doit précéder tout import de l'app (config.py lit DATABASE_URL à l'import).
os.environ['FLASK_ENV'] = 'testing'
os.environ['FLASK_DEBUG'] = '0'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app, db
from app.models import (
    User, UserRole, ServiceType, ServiceSource,
    FormDefinition, FormField, FormFieldType, FormWorkflowStep,
    FormDispatchTarget, FormSubmission,
)


class TestConfig:
    TESTING = True
    DEBUG = False
    SECRET_KEY = 'cle-secrete-test-lot4'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    UPLOAD_FOLDER = '/tmp/intranet_test_uploads_lot4'
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    MAIL_SUPPRESS_SEND = True
    MAIL_SERVER = 'localhost'
    MAIL_PORT = 25
    MAIL_USE_TLS = False
    MAIL_USERNAME = None
    MAIL_PASSWORD = None
    MAIL_DEFAULT_SENDER = 'no-reply-intranet@test.lan'
    BASE_URL = 'http://localhost/'
    SERVER_NAME = None
    LDAP_SERVER = 'ldap://localhost'
    LDAP_DOMAIN = 'TEST\\'
    LDAP_BASE_DN = 'dc=test,dc=lan'


# ===========================================================================
#  FIXTURES (même pattern que tests_intranet.py)
# ===========================================================================

@pytest.fixture(scope='session')
def app():
    _app = create_app('development')
    _app.config.from_object(TestConfig)
    # Garde-fou irréversible : refus de continuer si l'URI n'est pas la sqlite
    # mémoire de test (sinon drop_all() toucherait la base réellement connectée).
    assert _app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite:///:memory:', (
        "Refus de lancer les tests : SQLALCHEMY_DATABASE_URI ne pointe pas "
        "vers la sqlite en mémoire de test (valeur actuelle : "
        f"{_app.config['SQLALCHEMY_DATABASE_URI']!r})."
    )
    os.makedirs(_app.config['UPLOAD_FOLDER'], exist_ok=True)
    with _app.app_context():
        db.create_all()
        yield _app
        db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture(scope='function')
def db_session(app):
    """Remet la DB à zéro entre chaque test."""
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield db
        db.session.remove()


def make_user(role=UserRole.USER, username='testuser', password='Test1234!',
              fullname='Test User', service=ServiceType.INFO, allowed_services=None):
    u = User(username=username, fullname=fullname, email=f'{username}@test.lan', role=role)
    u.set_origin_services([service.value])
    u.set_allowed_services([s.value for s in allowed_services] if allowed_services else [service.value])
    db.session.add(u)
    db.session.commit()
    return u


def login(client, username='testuser', password='Test1234!'):
    """Connexion Flask-Login simulée (LDAP indisponible en test)."""
    with client.application.app_context():
        user = User.query.filter_by(username=username).first()
        if user is None:
            raise ValueError(f"Utilisateur '{username}' introuvable en base de test")
        uid = user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True

    # La fixture `app` garde un app_context ambiant : Flask-Login met
    # current_user en cache dans `g`. Sans ce reset, un 2e login() dans un
    # même test garderait l'identité précédente.
    from flask import g, has_app_context
    if has_app_context():
        g.pop('_login_user', None)

    return client.get('/portal', follow_redirects=False)


def make_full_form(author, slug='demande-test', is_active=True):
    """Formulaire complet : 4 champs (dont 2 conditionnels), 2 étapes,
    2 destinataires (dont 1 conditionné par un champ), templates et JSON."""
    form_def = FormDefinition(
        slug=slug, name='Demande test', description='Description du formulaire de test',
        is_active=is_active, created_by=author, manager_only=True,
        structured_field_templates_json=json.dumps({'new_user_fullname': '$nom $type_demande'}),
    )
    db.session.add(form_def)
    db.session.flush()

    f_type = FormField(form_definition_id=form_def.id, name='type_demande', label='Type de demande',
                       field_type=FormFieldType.SELECT, is_required=True, order_index=0,
                       options_json=json.dumps(['CDI', 'Mutation', 'Autre']))
    f_urgent = FormField(form_definition_id=form_def.id, name='urgent', label='Urgent',
                         field_type=FormFieldType.CHECKBOX, order_index=1)
    f_nom = FormField(form_definition_id=form_def.id, name='nom', label='Nom',
                      field_type=FormFieldType.TEXT, is_required=True, order_index=2,
                      help_text='Nom de famille', maps_to_ticket_field='new_user_fullname')
    f_pj = FormField(form_definition_id=form_def.id, name='piece_jointe', label='Pièce jointe',
                     field_type=FormFieldType.FILE, order_index=3)
    db.session.add_all([f_type, f_urgent, f_nom, f_pj])
    db.session.flush()

    # Conditions : « Nom » visible si type ∈ {CDI, Mutation} ; « PJ » visible si « Urgent » coché.
    f_nom.condition_field_id = f_type.id
    f_nom.condition_values_json = json.dumps(['CDI', 'Mutation'])
    f_pj.condition_field_id = f_urgent.id

    db.session.add_all([
        FormWorkflowStep(form_definition_id=form_def.id, order_index=0, label='Validation Manager',
                         service_source=ServiceSource.EMITTER,
                         skip_for_author_roles_json=json.dumps(['MANAGER', 'DIRECTEUR'])),
        FormWorkflowStep(form_definition_id=form_def.id, order_index=1, label='Validation DAF',
                         validator_role=UserRole.DIRECTEUR, validator_service=ServiceType.DAF,
                         service_source=ServiceSource.FIXED, skip_for_author_roles_json='[]'),
    ])
    db.session.add_all([
        FormDispatchTarget(form_definition_id=form_def.id, label='DRH', target_service=ServiceType.DRH,
                           condition_field_id=f_type.id, condition_values_json=json.dumps(['CDI']),
                           included_file_fields_json=json.dumps(['piece_jointe']),
                           included_mapped_fields_json=json.dumps(['nom']),
                           included_description_fields_json=json.dumps(['type_demande', 'nom']),
                           ticket_category_template='$type_demande', ticket_title_template='[DRH] $nom',
                           ticket_description_template='Demande $type_demande', uid_suffix='DRH'),
        FormDispatchTarget(form_definition_id=form_def.id, label='Informatique', target_service=ServiceType.INFO),
    ])
    db.session.commit()
    return form_def


# ===========================================================================
#  DUPLICATION
# ===========================================================================

class TestDuplicationFormulaire:

    def test_duplication_complete_et_remappage_des_conditions(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        original = make_full_form(admin)
        original_id = original.id
        old_ids = {f.name: f.id for f in original.fields}
        login(client, 'admin')

        r = client.post(f'/admin/forms/{original_id}/duplicate', follow_redirects=False)
        assert r.status_code == 302

        with client.application.app_context():
            copy = FormDefinition.query.filter_by(slug='demande-test-copie').first()
            assert copy is not None
            assert r.headers['Location'].endswith(f'/admin/forms/{copy.id}/edit')

            # Métadonnées
            assert copy.name == 'Demande test (copie)'
            assert copy.is_active is False
            assert copy.description == 'Description du formulaire de test'
            assert copy.manager_only is True
            assert json.loads(copy.structured_field_templates_json) == {'new_user_fullname': '$nom $type_demande'}

            # Comptes
            assert len(copy.fields) == 4
            assert len(copy.steps) == 2
            assert len(copy.dispatch_targets) == 2

            # Champs : attributs et conditions remappées vers les NOUVEAUX ids
            new_by_name = {f.name: f for f in copy.fields}
            assert [f.name for f in copy.fields] == ['type_demande', 'urgent', 'nom', 'piece_jointe']
            assert new_by_name['type_demande'].get_options() == ['CDI', 'Mutation', 'Autre']
            assert new_by_name['nom'].help_text == 'Nom de famille'
            assert new_by_name['nom'].maps_to_ticket_field == 'new_user_fullname'
            assert new_by_name['nom'].is_required is True

            assert new_by_name['nom'].condition_field_id == new_by_name['type_demande'].id
            assert new_by_name['nom'].condition_field_id != old_ids['type_demande']
            assert new_by_name['nom'].get_condition_values() == ['CDI', 'Mutation']
            assert new_by_name['piece_jointe'].condition_field_id == new_by_name['urgent'].id
            assert new_by_name['piece_jointe'].condition_field_id != old_ids['urgent']
            assert new_by_name['type_demande'].condition_field_id is None
            # Tous les champs de la copie appartiennent bien à la copie
            assert all(f.form_definition_id == copy.id for f in copy.fields)

            # Étapes
            s1, s2 = copy.steps
            assert (s1.label, s1.service_source, s1.get_skip_roles()) == ('Validation Manager', ServiceSource.EMITTER, ['MANAGER', 'DIRECTEUR'])
            assert (s2.label, s2.validator_role, s2.validator_service) == ('Validation DAF', UserRole.DIRECTEUR, ServiceType.DAF)

            # Destinataires : condition remappée + tous les attributs JSON/templates
            drh = next(t for t in copy.dispatch_targets if t.label == 'DRH')
            info = next(t for t in copy.dispatch_targets if t.label == 'Informatique')
            assert drh.target_service == ServiceType.DRH
            assert drh.condition_field_id == new_by_name['type_demande'].id
            assert drh.get_condition_values() == ['CDI']
            assert drh.get_included_file_fields() == ['piece_jointe']
            assert drh.get_included_mapped_fields() == ['nom']
            assert drh.get_included_description_fields() == ['type_demande', 'nom']
            assert (drh.ticket_category_template, drh.ticket_title_template, drh.ticket_description_template, drh.uid_suffix) \
                == ('$type_demande', '[DRH] $nom', 'Demande $type_demande', 'DRH')
            assert info.condition_field_id is None
            assert info.get_included_file_fields() is None

            # L'original est intact
            orig = FormDefinition.query.get(original_id)
            assert orig.is_active is True
            assert len(orig.fields) == 4
            assert {f.name: f.id for f in orig.fields} == old_ids

    def test_slug_unique_apres_deux_duplications(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        original = make_full_form(admin)
        original_id = original.id
        login(client, 'admin')

        client.post(f'/admin/forms/{original_id}/duplicate')
        client.post(f'/admin/forms/{original_id}/duplicate')

        with client.application.app_context():
            slugs = sorted(f.slug for f in FormDefinition.query.all())
            assert slugs == ['demande-test', 'demande-test-copie', 'demande-test-copie-2']
            for copy in FormDefinition.query.filter(FormDefinition.slug != 'demande-test'):
                assert copy.is_active is False
                assert copy.name == 'Demande test (copie)'
                assert len(copy.fields) == 4

    def test_duplication_d_une_copie_repart_du_slug_de_la_copie(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        original = make_full_form(admin)
        original_id = original.id
        login(client, 'admin')

        client.post(f'/admin/forms/{original_id}/duplicate')
        with client.application.app_context():
            copy_id = FormDefinition.query.filter_by(slug='demande-test-copie').first().id
        client.post(f'/admin/forms/{copy_id}/duplicate')

        with client.application.app_context():
            assert FormDefinition.query.filter_by(slug='demande-test-copie-copie').first() is not None

    def test_duplication_reservee_a_l_admin(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        make_user(role=UserRole.MANAGER, username='manager')
        original = make_full_form(admin)
        original_id = original.id

        login(client, 'manager')
        r = client.post(f'/admin/forms/{original_id}/duplicate', follow_redirects=False)
        assert r.status_code == 302
        assert '/admin/forms' not in r.headers['Location']
        with client.application.app_context():
            assert FormDefinition.query.count() == 1

    def test_duplication_sans_connexion_redirige_vers_login(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        original = make_full_form(admin)
        r = client.post(f'/admin/forms/{original.id}/duplicate', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_boutons_dupliquer_presents_sur_liste_et_edition(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        original = make_full_form(admin)
        original_id = original.id
        login(client, 'admin')

        r = client.get('/admin/forms/')
        assert r.status_code == 200
        assert f'/admin/forms/{original_id}/duplicate' in r.get_data(as_text=True)

        r = client.get(f'/admin/forms/{original_id}/edit')
        assert r.status_code == 200
        assert f'/admin/forms/{original_id}/duplicate' in r.get_data(as_text=True)


# ===========================================================================
#  APERÇU EN DIRECT
# ===========================================================================

class TestApercuFormulaire:

    def test_apercu_accessible_a_l_admin_meme_pour_un_brouillon(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        form_def = make_full_form(admin, is_active=False)
        form_id = form_def.id
        login(client, 'admin')

        r = client.get(f'/admin/forms/{form_id}/preview')
        assert r.status_code == 200
        html = r.get_data(as_text=True)

        # Rendu identique à la page de dépôt : titre, description, champs, options
        assert 'Demande test' in html
        assert 'Description du formulaire de test' in html
        assert 'name="type_demande"' in html
        assert 'name="urgent"' in html
        assert 'name="nom"' in html
        assert 'name="piece_jointe"' in html
        assert '<option value="Mutation"' in html
        assert 'Nom de famille' in html  # help_text
        # Champs conditionnels : attributs data-condition-* + script partagé
        assert 'data-condition-on="type_demande"' in html
        assert 'data-condition-type="SELECT"' in html
        assert 'data-condition-on="urgent"' in html
        assert 'data-condition-type="CHECKBOX"' in html
        assert 'js/form_conditions.js' in html
        # Parcours de validation rappelé
        assert 'Validation Manager' in html and 'Validation DAF' in html
        assert 'DRH' in html and 'Informatique' in html

    def test_apercu_est_en_lecture_seule(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        form_def = make_full_form(admin)
        form_id = form_def.id
        login(client, 'admin')

        html = client.get(f'/admin/forms/{form_id}/preview').get_data(as_text=True)
        # Formulaire neutralisé : pas de POST, submit bloqué, bouton désactivé
        assert 'method="POST"' not in html
        assert 'onsubmit="return false;"' in html
        assert '<button type="button" disabled' in html
        assert '<button type="submit"' not in html
        # Pas de bloc conseils ni de brouillon/récap (opt-in via data-recap-confirm)
        assert 'Avant d\'envoyer' not in html
        assert 'data-recap-confirm' not in html
        # Page autonome (pas de base.html : pas de barre latérale)
        assert 'sidebar-mobile-toggle' not in html
        assert 'Déconnexion' not in html

    def test_apercu_n_accepte_aucune_soumission(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        form_def = make_full_form(admin)
        form_id = form_def.id
        login(client, 'admin')

        r = client.post(f'/admin/forms/{form_id}/preview',
                        data={'type_demande': 'CDI', 'nom': 'Dupont'}, follow_redirects=False)
        assert r.status_code == 405
        with client.application.app_context():
            assert FormSubmission.query.count() == 0

    def test_apercu_refuse_aux_non_admins(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        make_user(role=UserRole.USER, username='user')
        make_user(role=UserRole.DIRECTEUR, username='directeur')
        form_def = make_full_form(admin)
        form_id = form_def.id

        for username in ('user', 'directeur'):
            login(client, username)
            r = client.get(f'/admin/forms/{form_id}/preview', follow_redirects=False)
            assert r.status_code == 302, username
            assert '/admin/forms' not in r.headers['Location']

        r = client.get(f'/admin/forms/{form_id}/preview', follow_redirects=True)
        assert 'name="type_demande"' not in r.get_data(as_text=True)

    def test_apercu_sans_connexion_redirige_vers_login(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        form_def = make_full_form(admin)
        r = client.get(f'/admin/forms/{form_def.id}/preview', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers['Location']

    def test_apercu_formulaire_inexistant_404(self, client, db_session):
        make_user(role=UserRole.ADMIN, username='admin')
        login(client, 'admin')
        assert client.get('/admin/forms/9999/preview').status_code == 404

    def test_apercu_formulaire_sans_champ(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        form_def = FormDefinition(slug='vide', name='Formulaire vide', created_by=admin)
        db.session.add(form_def)
        db.session.commit()
        form_id = form_def.id
        login(client, 'admin')

        r = client.get(f'/admin/forms/{form_id}/preview')
        assert r.status_code == 200
        assert "n'a pas encore de champ configuré" in r.get_data(as_text=True)

    def test_page_edition_integre_l_iframe_d_apercu(self, client, db_session):
        admin = make_user(role=UserRole.ADMIN, username='admin')
        form_def = make_full_form(admin)
        form_id = form_def.id
        login(client, 'admin')

        html = client.get(f'/admin/forms/{form_id}/edit').get_data(as_text=True)
        assert 'id="formPreviewFrame"' in html
        assert f'src="/admin/forms/{form_id}/preview"' in html
        assert 'Aperçu utilisateur' in html

    def test_page_de_depot_reelle_toujours_fonctionnelle_apres_factorisation(self, client, db_session):
        """La factorisation en include ne doit rien changer à /forms/<slug>/new."""
        admin = make_user(role=UserRole.ADMIN, username='admin')
        form_def = make_full_form(admin)
        slug = form_def.slug
        login(client, 'admin')

        r = client.get(f'/forms/{slug}/new')
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'method="POST"' in html
        assert 'data-recap-confirm' in html
        assert '<button type="submit"' in html
        assert 'data-condition-on="type_demande"' in html
        assert 'js/form_conditions.js' in html
        assert 'name="nom"' in html

        # Soumission réelle : « Nom » requis car type=CDI le rend visible.
        r = client.post(f'/forms/{slug}/new', data={'type_demande': 'CDI', 'nom': 'Dupont'}, follow_redirects=False)
        assert r.status_code == 302
        with client.application.app_context():
            assert FormSubmission.query.count() == 1
            assert FormSubmission.query.first().get_data()['nom'] == 'Dupont'
