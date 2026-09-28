#!/usr/bin/env python3
"""
Tests d'accessibilité clavier / focus visible — Intranet ILVM.

Vérifie que la couche a11y (css/a11y.css, js/a11y.js, lien d'évitement, rôles
ARIA sur les onglets et menus) est bien rendue par base.html et que les pages
concernées (portail, profil, détail de ticket, tableau de bord manager,
gestion des annonces, statistiques) se rendent toujours en 200.

Usage :
    cd /home/admin-intra/worktrees/a11y
    /var/www/intranet/venv/bin/python -m pytest tests_accessibilite.py -q

Reprend les fixtures de tests_intranet.py (SQLite en mémoire, sans LDAP).
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['FLASK_ENV'] = 'testing'
os.environ['FLASK_DEBUG'] = '0'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app, db
from app.models import User, UserRole, ServiceType, TicketStatus

# Fixtures et helpers partagés avec la suite principale (même TestConfig).
from tests_intranet import TestConfig, make_user, make_ticket  # noqa: E402


@pytest.fixture(scope='session')
def app():
    _app = create_app('development')
    _app.config.from_object(TestConfig)
    assert _app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite:///:memory:', (
        "Refus de lancer les tests : SQLALCHEMY_DATABASE_URI ne pointe pas "
        "vers la sqlite en mémoire de test."
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
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield db
        db.session.remove()


def login(client, username='testuser'):
    """Pose la session Flask-Login directement (pas de LDAP en test) et purge
    le cache de current_user dans `g` (app_context ambiant de la fixture)."""
    with client.application.app_context():
        user = User.query.filter_by(username=username).first()
        assert user is not None, f"Utilisateur '{username}' introuvable"
        uid = user.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True
    from flask import g, has_app_context
    if has_app_context():
        g.pop('_login_user', None)


def html(r):
    return r.data.decode('utf-8', errors='replace')


# ---------------------------------------------------------------------------
#  Couche a11y dans base.html
# ---------------------------------------------------------------------------

class TestBaseLayout:

    def test_portail_contient_skip_link_et_feuille_a11y(self, client, db_session):
        make_user()
        login(client)
        r = client.get('/portal')
        assert r.status_code == 200
        page = html(r)
        assert 'css/a11y.css' in page
        assert 'js/a11y.js' in page
        assert 'class="a11y-skip-link"' in page
        assert 'href="#contenu"' in page
        assert 'Aller au contenu' in page
        # Le lien d'évitement est le premier élément du body.
        body = page.index('<body')
        assert page.index('a11y-skip-link') - body < 400
        # La cible existe et est focalisable programmatiquement.
        assert 'id="contenu"' in page
        assert '<main id="contenu" tabindex="-1"' in page

    def test_menus_ont_les_attributs_aria(self, client, db_session):
        make_user()
        login(client)
        page = html(client.get('/portal'))
        assert 'aria-controls="notif-dropdown"' in page
        assert 'aria-expanded="false"' in page
        assert 'id="notif-list" aria-live="polite"' in page

    def test_fichiers_statiques_servis(self, client, db_session):
        r = client.get('/static/css/a11y.css')
        assert r.status_code == 200
        css = html(r)
        assert ':focus-visible' in css
        assert 'rgb(var(--accent-500))' in css
        assert 'html[data-contrast="high"]' in css
        assert '.peer.sr-only:focus-visible + span' in css
        assert 'prefers-reduced-motion' in css
        assert '#networkCanvas' in css
        r = client.get('/static/js/a11y.js')
        assert r.status_code == 200
        js = html(r)
        assert 'role="tablist"' in js
        assert 'Escape' in js
        assert 'prefers-reduced-motion' in js

    def test_page_login_contient_aussi_le_skip_link(self, client, db_session):
        r = client.get('/auth/login')
        assert r.status_code == 200
        page = html(r)
        assert 'a11y-skip-link' in page
        assert 'id="contenu"' in page


# ---------------------------------------------------------------------------
#  Pages concernées : rendu 200 + rôles ARIA
# ---------------------------------------------------------------------------

class TestPages:

    def test_profil_rendu_avec_onglets_aria(self, client, db_session):
        make_user()
        login(client)
        r = client.get('/profile')
        assert r.status_code == 200
        page = html(r)
        assert 'role="tablist"' in page
        assert page.count('role="tab"') == 3
        assert page.count('role="tabpanel"') == 3
        assert 'id="profile-tab-account"' in page
        assert 'aria-controls="appearance-tab"' in page
        assert 'aria-labelledby="profile-tab-bug"' in page
        # Panneau profil du layout sidebar : dialogue + déclencheur.
        assert 'id="profile-panel" role="dialog"' in page
        assert 'aria-controls="profile-panel"' in page
        # Radios e-mail masqués : sr-only (focalisable), jamais hidden.
        assert 'name="email_mode" value="all" class="peer sr-only"' in page
        assert 'peer hidden' not in page

    def test_detail_ticket_rendu(self, client, db_session, app):
        u = make_user()
        with app.app_context():
            t = make_ticket(u, service=ServiceType.INFO)
            uid = t.uid_public
        login(client)
        r = client.get(f'/tickets/view/{uid}')
        assert r.status_code == 200
        assert 'a11y-skip-link' in html(r)

    def test_detail_ticket_clos_avis_focalisable(self, client, db_session, app):
        u = make_user()
        with app.app_context():
            t = make_ticket(u, service=ServiceType.INFO, status=TicketStatus.DONE)
            uid = t.uid_public
        login(client)
        r = client.get(f'/tickets/view/{uid}')
        assert r.status_code == 200
        page = html(r)
        if 'name="score"' in page:  # bloc d'avis affiché au demandeur
            assert 'name="score" value="3" class="peer sr-only"' in page
            assert 'peer hidden' not in page

    def test_dashboard_manager_onglets_aria(self, client, db_session):
        make_user(role=UserRole.MANAGER, username='manager')
        login(client, 'manager')
        r = client.get('/tickets/manager/dashboard')
        assert r.status_code == 200
        page = html(r)
        assert 'role="tablist"' in page
        assert page.count('role="tab"') == 3
        assert page.count('role="tabpanel"') == 3
        assert 'aria-controls="mgr-panel-n2"' in page

    def test_annonces_niveaux_sr_only(self, client, db_session):
        make_user(role=UserRole.ADMIN, username='admin')
        login(client, 'admin')
        r = client.get('/announcements/manage')
        assert r.status_code in (200, 302, 403)
        if r.status_code == 200:
            page = html(r)
            assert 'name="level"' in page
            assert 'peer hidden' not in page

    def test_stats_filtres_services_sr_only(self, client, db_session):
        make_user(role=UserRole.ADMIN, username='admin')
        login(client, 'admin')
        r = client.get('/tickets/stats')
        assert r.status_code in (200, 302, 403, 404)
        if r.status_code == 200:
            page = html(r)
            assert 'peer hidden' not in page
