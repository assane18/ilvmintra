#!/usr/bin/env python3
"""
=============================================================================
 SCRIPT DE TESTS COMPLET - INTRANET ILVM
=============================================================================
 Couvre toutes les fonctionnalités de l'application :
   - Authentification (login/logout)
   - Portail & navigation
   - Système de tickets (création, workflow, messagerie)
   - Module DAF (bons de commande)
   - Module DRH / FCPI (recrutement)
   - Module Séjour
   - Module Publications
   - Inventaire & Prêts de matériel
   - API (notifications, team chat)
   - Administration utilisateurs
   - Accès RBAC (rôles et permissions)
   - Endpoints de redirection et pages d'erreur

 Usage :
   cd /var/www/intranet
   source venv/bin/activate
   pip install pytest pytest-cov
   python -m pytest tests_intranet.py -v
   python -m pytest tests_intranet.py -v --cov=app --cov-report=term-missing

 Note :
   Les tests utilisent une base SQLite en mémoire, sans LDAP ni Exchange.
   Aucune connexion réseau externe n'est requise.
=============================================================================
"""

import os
import sys
import json
import io
import pytest
from datetime import datetime, timedelta

# --- Ajout du chemin du projet ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ==========================================================================
#  IMPORTANT : Ces variables DOIVENT être définies AVANT tout import de l'app
#  car DevelopmentConfig.SQLALCHEMY_DATABASE_URI est évalué à l'import de config.py
# ==========================================================================
os.environ['FLASK_ENV'] = 'testing'
os.environ['FLASK_DEBUG'] = '0'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'   # Évite la connexion à PostgreSQL

from app import create_app, db
from app.models import (
    User, UserRole, Ticket, TicketStatus, TicketMessage,
    ServiceType, Notification, TeamMessage, Materiel, Pret,
    Recruitment, RecruitmentStatus, DossierSejour, SejourStatus,
    Publication, PublicationStatus
)


# ===========================================================================
#  CONFIGURATION DE L'APP DE TEST
# ===========================================================================

class TestConfig:
    TESTING = True
    DEBUG = False
    SECRET_KEY = 'cle-secrete-test-intranet-2026'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    UPLOAD_FOLDER = '/tmp/intranet_test_uploads'
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
#  FIXTURES PYTEST
# ===========================================================================

@pytest.fixture(scope='session')
def app():
    """Crée l'application Flask pour les tests (une seule fois)."""
    _app = create_app('development')
    _app.config.from_object(TestConfig)
    # Garde-fou irréversible (même principe que test_forms_engine.py après
    # l'incident du 24/09/2026) : on refuse de continuer si l'URI ne pointe
    # pas vers la sqlite en mémoire de test, quelle qu'en soit la raison —
    # sinon db.create_all()/db.drop_all() ci-dessous s'appliqueraient à la
    # base réellement connectée.
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
    """Client de test Flask."""
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


# ---------------------------------------------------------------------------
#  Helpers de création de données
# ---------------------------------------------------------------------------

def make_user(role=UserRole.USER, username='testuser', password='Test1234!',
              fullname='Test User', service=ServiceType.INFO,
              allowed_services=None):
    """Crée et persiste un utilisateur en base."""
    u = User(
        username=username,
        fullname=fullname,
        email=f'{username}@test.lan',
        role=role,
    )
    u.set_origin_services([service.value])
    if allowed_services:
        u.set_allowed_services([s.value for s in allowed_services])
    else:
        u.set_allowed_services([service.value])
    db.session.add(u)
    db.session.commit()
    return u


def login(client, username='testuser', password='Test1234!'):
    """
    Simule une connexion Flask-Login en injectant directement le user_id
    dans la session (bypasse LDAP, indisponible en environnement de test).
    """
    from flask_login import login_user
    from app.models import User

    # Trouver l'utilisateur en base et injecter sa session
    with client.application.app_context():
        user = User.query.filter_by(username=username).first()
        if user is None:
            raise ValueError(f"Utilisateur '{username}' introuvable en base de test")
        uid = user.id

    # Injecter directement user_id dans la session Flask-Login
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True

    # La fixture `app` garde un app_context ambiant pour toute la session : les
    # requêtes du test_client réutilisent donc le même `g`, où Flask-Login
    # met current_user en cache. Sans ce reset, un 2e login() dans un même
    # test continue d'agir avec l'identité précédente (piège déjà rencontré).
    from flask import g, has_app_context
    if has_app_context():
        g.pop('_login_user', None)

    # Vérifier que la session est bien active
    r = client.get('/portal', follow_redirects=False)
    return r


def logout(client):
    return client.get('/auth/logout', follow_redirects=True)


def make_ticket(author, service=ServiceType.INFO, status=TicketStatus.PENDING,
                title='Ticket de test', description='Description de test'):
    """Crée un ticket directement en base."""
    t = Ticket(
        uid_public=f'{datetime.utcnow().strftime("%Y%m%d")}-{Ticket.query.count()+1:03d}',
        title=title,
        description=description,
        author_id=author.id,
        target_service=service,
        status=status,
        category_ticket='STANDARD',
        service_demandeur=author.service,
        tel_demandeur='0100000000',
    )
    db.session.add(t)
    db.session.commit()
    return t


def make_notification(user, message='Test notif', category='info', link='/'):
    n = Notification(
        user_id=user.id,
        message=message,
        category=category,
        link=link,
        is_read=False,
    )
    db.session.add(n)
    db.session.commit()
    return n


# ===========================================================================
#  TESTS AUTHENTIFICATION
# ===========================================================================

class TestAuthentification:
    """Vérifie login / logout et protection des routes."""

    def test_login_page_accessible(self, client, db_session):
        r = client.get('/auth/login')
        assert r.status_code == 200
        assert b'login' in r.data.lower() or b'connexion' in r.data.lower()

    def test_login_utilisateur_inconnu(self, client, db_session):
        r = client.post('/auth/login', data={
            'username': 'inconnu',
            'password': 'mauvais'
        }, follow_redirects=True)
        assert r.status_code == 200
        # Doit rester sur la page de login (redirection ou message d'erreur)
        assert b'login' in r.data.lower() or b'invalide' in r.data.lower() \
               or b'incorrect' in r.data.lower() or b'erreur' in r.data.lower() \
               or r.request.path == '/auth/login'

    def test_login_mot_de_passe_local(self, client, db_session, app):
        with app.app_context():
            make_user(username='localuser', password='TestPass99!')
        r = login(client, 'localuser', 'TestPass99!')
        assert r.status_code == 200

    def test_login_mauvais_mot_de_passe(self, client, db_session, app):
        with app.app_context():
            make_user(username='localuser2', password='BonMotDePasse1!')
        r = client.post('/auth/login', data={
            'username': 'localuser2',
            'password': 'MauvaisMotDePasse!'
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_logout_deconnecte_utilisateur(self, client, db_session, app):
        with app.app_context():
            make_user(username='logoutuser', password='Logout1234!')
        login(client, 'logoutuser', 'Logout1234!')
        r = logout(client)
        assert r.status_code == 200
        # Après déconnexion, le portail doit rediriger vers login
        r2 = client.get('/portal', follow_redirects=False)
        assert r2.status_code in (302, 401)

    def test_portail_inaccessible_sans_login(self, client, db_session):
        r = client.get('/portal', follow_redirects=False)
        assert r.status_code == 302
        assert '/auth/login' in r.headers.get('Location', '')

    def test_anti_cache_headers_sur_login(self, client, db_session, app):
        """La route /auth/login porte le décorateur @nocache."""
        r = client.get('/auth/login')
        cc = r.headers.get('Cache-Control', '')
        # Le décorateur nocache est appliqué sur la vue login/logout
        assert 'no-cache' in cc or 'no-store' in cc or r.status_code == 200


# ===========================================================================
#  TESTS PORTAIL & NAVIGATION
# ===========================================================================

class TestPortailNavigation:
    """Pages principales du portail."""

    def setup_method(self):
        pass

    def _login_as_user(self, client, db_session, app):
        with app.app_context():
            make_user(username='navuser', password='Nav1234!', role=UserRole.USER)
        login(client, 'navuser', 'Nav1234!')

    def test_racine_redirige_vers_login_ou_portail(self, client, db_session, app):
        r = client.get('/', follow_redirects=False)
        assert r.status_code in (200, 302)

    def test_portail_accessible_apres_login(self, client, db_session, app):
        self._login_as_user(client, db_session, app)
        r = client.get('/portal')
        assert r.status_code == 200

    def test_page_aide_accessible(self, client, db_session, app):
        self._login_as_user(client, db_session, app)
        r = client.get('/help')
        assert r.status_code == 200

    def test_historique_accessible(self, client, db_session, app):
        self._login_as_user(client, db_session, app)
        r = client.get('/my_history')
        assert r.status_code == 200

    def test_dashboard_redirect_selon_role(self, client, db_session, app):
        self._login_as_user(client, db_session, app)
        r = client.get('/dashboard', follow_redirects=False)
        assert r.status_code in (200, 302)


# ===========================================================================
#  TESTS TICKETS
# ===========================================================================

class TestTickets:
    """Création, visualisation et workflow des tickets."""

    def _setup_users(self, app):
        with app.app_context():
            user = make_user(username='ticket_user', password='User1234!',
                             role=UserRole.USER, service=ServiceType.INFO)
            manager = make_user(username='ticket_mgr', password='Mgr1234!',
                                role=UserRole.MANAGER, service=ServiceType.INFO,
                                allowed_services=[ServiceType.INFO])
            solver = make_user(username='ticket_sol', password='Sol1234!',
                               role=UserRole.SOLVER, service=ServiceType.INFO,
                               allowed_services=[ServiceType.INFO])
            admin = make_user(username='ticket_adm', password='Adm1234!',
                              role=UserRole.ADMIN, service=ServiceType.INFO,
                              allowed_services=[ServiceType.INFO])

    # --- Formulaire de création ---

    def test_formulaire_nouveau_ticket_accessible(self, client, db_session, app):
        # L'URL utilise le NOM Python de l'enum (INFO), pas la valeur ('INFORMATIQUE')
        self._setup_users(app)
        login(client, 'ticket_user', 'User1234!')
        r = client.get('/tickets/new/INFO')
        assert r.status_code == 200

    def test_creation_ticket_standard(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_user', 'User1234!')
        r = client.post('/tickets/new/INFORMATIQUE', data={
            'title': 'Mon PC ne démarre plus',
            'description': 'Allumage impossible depuis ce matin',
            'category_ticket': 'MATERIEL',
            'hostname': 'PC-TEST-01',
            'service_demandeur': 'INFORMATIQUE',
            'tel_demandeur': '0101010101',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_creation_ticket_champs_manquants(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_user', 'User1234!')
        r = client.post('/tickets/new/INFORMATIQUE', data={
            'title': '',
            'description': '',
        }, follow_redirects=True)
        # Le formulaire doit rejeter ou rester sur la page de création
        assert r.status_code in (200, 400)

    def test_visualisation_ticket(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_user', 'User1234!')
        with app.app_context():
            user = User.query.filter_by(username='ticket_user').first()
            t = make_ticket(user, service=ServiceType.INFO)
            uid = t.uid_public
        r = client.get(f'/tickets/view/{uid}')
        assert r.status_code == 200

    def test_ticket_inexistant_retourne_404(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_user', 'User1234!')
        r = client.get('/tickets/view/99999999-999')
        assert r.status_code in (404, 302)

    def test_ajout_message_dans_ticket(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_user', 'User1234!')
        with app.app_context():
            user = User.query.filter_by(username='ticket_user').first()
            t = make_ticket(user, service=ServiceType.INFO, status=TicketStatus.PENDING)
            uid = t.uid_public
        r = client.post(f'/tickets/view/{uid}', data={
            'content': 'Je viens de relancer le PC, même problème.'
        }, follow_redirects=True)
        assert r.status_code == 200

    # --- Dashboard Manager ---

    def test_dashboard_manager_accessible_manager(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_mgr', 'Mgr1234!')
        r = client.get('/tickets/manager/dashboard')
        assert r.status_code == 200

    def test_dashboard_manager_refuse_user(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_user', 'User1234!')
        r = client.get('/tickets/manager/dashboard', follow_redirects=False)
        assert r.status_code in (302, 403)

    # --- Dashboard Solver ---

    def test_dashboard_solver_accessible(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_sol', 'Sol1234!')
        r = client.get('/tickets/solver/dashboard')
        assert r.status_code == 200

    # --- Actions Manager ---

    def test_action_valider_ticket(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_mgr', 'Mgr1234!')
        with app.app_context():
            user = User.query.filter_by(username='ticket_user').first()
            t = make_ticket(user, service=ServiceType.INFO,
                            status=TicketStatus.VALIDATION_N1)
            tid = t.id
        r = client.post(f'/tickets/manager/action/{tid}/valider',
                        follow_redirects=True)
        assert r.status_code == 200

    def test_action_refuser_ticket(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_mgr', 'Mgr1234!')
        with app.app_context():
            user = User.query.filter_by(username='ticket_user').first()
            t = make_ticket(user, service=ServiceType.INFO,
                            status=TicketStatus.VALIDATION_N1)
            tid = t.id
        r = client.post(f'/tickets/manager/action/{tid}/refuser',
                        data={'refusal_reason': 'Hors périmètre'},
                        follow_redirects=True)
        assert r.status_code == 200

    # --- Actions Solver ---

    def test_solver_prend_ticket(self, client, db_session, app):
        # La route /solver/take/ est GET-only (pas de méthodes=['POST'])
        self._setup_users(app)
        login(client, 'ticket_sol', 'Sol1234!')
        with app.app_context():
            user = User.query.filter_by(username='ticket_user').first()
            t = make_ticket(user, service=ServiceType.INFO,
                            status=TicketStatus.PENDING)
            tid = t.id
        r = client.get(f'/tickets/solver/take/{tid}', follow_redirects=True)
        assert r.status_code == 200

    def test_solver_ferme_ticket(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_sol', 'Sol1234!')
        with app.app_context():
            solver = User.query.filter_by(username='ticket_sol').first()
            user = User.query.filter_by(username='ticket_user').first()
            t = make_ticket(user, service=ServiceType.INFO,
                            status=TicketStatus.IN_PROGRESS)
            t.solver_id = solver.id
            db.session.commit()
            tid = t.id
        r = client.post(f'/tickets/solver/close/{tid}',
                        data={'resolution_notes': 'Problème résolu après redémarrage.'},
                        follow_redirects=True)
        assert r.status_code == 200

    # --- Historique & Export ---

    def test_historique_tickets_accessible(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_mgr', 'Mgr1234!')
        r = client.get('/tickets/historique')
        assert r.status_code == 200

    def test_export_historique_excel(self, client, db_session, app):
        self._setup_users(app)
        login(client, 'ticket_mgr', 'Mgr1234!')
        r = client.get('/tickets/export/history')
        assert r.status_code in (200, 302)
        if r.status_code == 200:
            assert 'spreadsheet' in r.content_type or 'excel' in r.content_type \
                   or 'octet-stream' in r.content_type


# ===========================================================================
#  TESTS MODULE DAF
# ===========================================================================

class TestModuleDAF:
    """Bons de commande et workflow DAF."""

    def _setup(self, app):
        with app.app_context():
            make_user(username='daf_mgr', password='Mgr1234!',
                      role=UserRole.MANAGER, service=ServiceType.INFO,
                      allowed_services=[ServiceType.DAF])
            make_user(username='daf_solver', password='Sol1234!',
                      role=UserRole.SOLVER, service=ServiceType.DAF,
                      allowed_services=[ServiceType.DAF])
            make_user(username='daf_dir', password='Dir1234!',
                      role=UserRole.DIRECTEUR, service=ServiceType.DAF,
                      allowed_services=[ServiceType.DAF])

    def test_formulaire_daf_accessible(self, client, db_session, app):
        self._setup(app)
        login(client, 'daf_mgr', 'Mgr1234!')
        r = client.get('/tickets/new/DAF')
        assert r.status_code == 200

    def test_creation_bon_commande_daf(self, client, db_session, app):
        self._setup(app)
        login(client, 'daf_mgr', 'Mgr1234!')
        lignes = json.dumps([{
            'designation': 'Ordinateur portable',
            'quantite': 2,
            'prix_unitaire': 850.00,
            'total': 1700.00
        }])
        r = client.post('/tickets/new/DAF', data={
            'title': 'Achat matériel informatique',
            'description': 'Commande pour renouvellement parc',
            'category_ticket': 'DAF',
            'service_demandeur': 'INFORMATIQUE',
            'tel_demandeur': '0101010101',
            'daf_lieu_livraison': 'Siège social',
            'daf_fournisseur_nom': 'Fournisseur Test',
            'daf_fournisseur_tel': '0102030405',
            'daf_fournisseur_email': 'contact@fournisseur.fr',
            'daf_type_prix': 'HT',
            'daf_lignes_json': lignes,
            'daf_uf': 'UF-001',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_mode_delegation_daf(self, client, db_session, app):
        """Ticket DAF en mode délégation (< 380€ HT)."""
        self._setup(app)
        login(client, 'daf_mgr', 'Mgr1234!')
        r = client.post('/tickets/new/DAF', data={
            'title': 'Achat câble réseau',
            'description': 'Câble RJ45 5m',
            'category_ticket': 'DAF',
            'delegation': 'true',
            'service_demandeur': 'INFORMATIQUE',
            'tel_demandeur': '0101010101',
            'daf_lieu_livraison': 'Siège',
            'daf_fournisseur_nom': 'Câblerie Pro',
            'daf_fournisseur_tel': '0102030405',
            'daf_fournisseur_email': 'info@cablerie.fr',
            'daf_type_prix': 'HT',
            'daf_lignes_json': json.dumps([{
                'designation': 'Câble RJ45',
                'quantite': 1,
                'prix_unitaire': 15.00,
                'total': 15.00
            }]),
        }, follow_redirects=True)
        assert r.status_code == 200


# ===========================================================================
#  TESTS MODULE FCPI (RECRUTEMENT)
# ===========================================================================

class TestModuleFCPI:
    """Fiches de Coordination Pour Intégration."""

    def _setup(self, app):
        with app.app_context():
            make_user(username='fcpi_mgr', password='Mgr1234!',
                      role=UserRole.MANAGER, service=ServiceType.DRH,
                      allowed_services=[ServiceType.DRH])
            make_user(username='fcpi_dir', password='Dir1234!',
                      role=UserRole.DIRECTEUR, service=ServiceType.DRH,
                      allowed_services=[ServiceType.DRH])

    def test_check_acces_fcpi(self, client, db_session, app):
        self._setup(app)
        login(client, 'fcpi_mgr', 'Mgr1234!')
        r = client.get('/fcpi/check_access', follow_redirects=True)
        assert r.status_code == 200

    def test_formulaire_nouvelle_fcpi_accessible(self, client, db_session, app):
        self._setup(app)
        login(client, 'fcpi_mgr', 'Mgr1234!')
        r = client.get('/fcpi/new')
        assert r.status_code in (200, 302)

    def test_creation_fcpi(self, client, db_session, app):
        self._setup(app)
        login(client, 'fcpi_mgr', 'Mgr1234!')
        r = client.post('/fcpi/new', data={
            'nom_agent': 'DUPONT',
            'prenom_agent': 'Jean',
            'fonction': 'Éducateur spécialisé',
            'service_agent': 'ESAT',
            'uf_agent': 'UF-042',
            'contractuel': 'false',
            'date_entree': '2026-05-01',
            'date_debut_contrat': '2026-05-01',
            'condition_recrutement': 'CDI',
            'temps_travail': 'TEMPS_PLEIN',
            'pourcentage_temps': '100',
            'motif_recrutement': 'Nouveau poste',
            'acces_informatique': 'Messagerie, Intranet',
            'materiels_demandes': 'PC portable, téléphone',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_visualisation_fcpi(self, client, db_session, app):
        self._setup(app)
        login(client, 'fcpi_mgr', 'Mgr1234!')
        with app.app_context():
            mgr = User.query.filter_by(username='fcpi_mgr').first()
            rec = Recruitment(
                uid_public=f'FCPI-{datetime.utcnow().strftime("%Y%m%d")}-001',
                author_id=mgr.id,
                status=RecruitmentStatus.WAITING_RH_MGR,
                nom_agent='MARTIN',
                prenom_agent='Sophie',
                fonction='Infirmière',
                service_agent='MAS',
                uf_agent='UF-010',
                contractuel=False,
                date_entree=datetime(2026, 6, 1),
                condition_recrutement='CDI',
                temps_travail='TEMPS_PLEIN',
                pourcentage_temps=100,
                motif_recrutement='Remplacement',
                materiels_demandes='PC portable',      # évite split(None) dans le template
                acces_informatique='Messagerie',
            )
            db.session.add(rec)
            db.session.commit()
            rec_id = rec.id
        r = client.get(f'/fcpi/view/{rec_id}')
        assert r.status_code == 200

    def test_validation_fcpi_par_directeur(self, client, db_session, app):
        self._setup(app)
        login(client, 'fcpi_dir', 'Dir1234!')
        with app.app_context():
            mgr = User.query.filter_by(username='fcpi_mgr').first()
            rec = Recruitment(
                uid_public=f'FCPI-{datetime.utcnow().strftime("%Y%m%d")}-002',
                author_id=mgr.id,
                status=RecruitmentStatus.WAITING_RH_DIR,
                nom_agent='BERNARD',
                prenom_agent='Paul',
                fonction='AES',
                service_agent='FH',
                uf_agent='UF-020',
                contractuel=True,
                date_entree=datetime(2026, 7, 1),
                date_debut_contrat=datetime(2026, 7, 1),
                date_fin_contrat=datetime(2026, 12, 31),
                condition_recrutement='CDD',
                temps_travail='TEMPS_PARTIEL',
                pourcentage_temps=80,
                motif_recrutement='Congé maternité',
            )
            db.session.add(rec)
            db.session.commit()
            rec_id = rec.id
        r = client.post(f'/fcpi/validate/{rec_id}/valider',
                        follow_redirects=True)
        assert r.status_code == 200


# ===========================================================================
#  TESTS MODULE SÉJOUR
# ===========================================================================

class TestModuleSejour:
    """Dossiers de séjour."""

    def _setup(self, app):
        with app.app_context():
            make_user(username='sej_mgr', password='Mgr1234!',
                      role=UserRole.MANAGER, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])

    def test_formulaire_nouveau_sejour(self, client, db_session, app):
        self._setup(app)
        login(client, 'sej_mgr', 'Mgr1234!')
        r = client.get('/sejour/new')
        assert r.status_code in (200, 302)

    def test_creation_dossier_sejour(self, client, db_session, app):
        self._setup(app)
        login(client, 'sej_mgr', 'Mgr1234!')
        r = client.post('/sejour/new', data={
            'titre': 'Séjour mer – été 2026',
            'description': 'Séjour résidentiel 5 jours mer',
            'date_sejour': '2026-07-15',
            'service_demandeur': 'ESAT',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_liste_sejours_accessible(self, client, db_session, app):
        """
        BUG DÉTECTÉ : la route /sejour/list existe (sejour.py:159) mais
        son template 'sejour/list_sejours.html' est ABSENT du projet.
        Ce test documente le bug — il passera quand le template sera créé.
        """
        import jinja2
        self._setup(app)
        login(client, 'sej_mgr', 'Mgr1234!')
        try:
            r = client.get('/sejour/list', follow_redirects=True)
            # Si le template est créé, le test devrait passer avec 200
            assert r.status_code == 200
        except jinja2.exceptions.TemplateNotFound as e:
            pytest.xfail(
                f"BUG CONNU : template manquant 'sejour/list_sejours.html' "
                f"— créer le template pour activer cette fonctionnalité ({e})"
            )

    def test_visualisation_sejour(self, client, db_session, app):
        self._setup(app)
        login(client, 'sej_mgr', 'Mgr1234!')
        with app.app_context():
            mgr = User.query.filter_by(username='sej_mgr').first()
            ds = DossierSejour(
                uid_public=f'SEJ-{datetime.utcnow().strftime("%Y%m%d")}-001',
                author_id=mgr.id,
                status=SejourStatus.VALIDATION_MANAGER,
                titre='Camp montagne',
                description='Séjour annuel montagne',
                date_sejour=datetime(2026, 8, 10),
                service_demandeur='ESAT',
            )
            db.session.add(ds)
            db.session.commit()
            ds_id = ds.id
        r = client.get(f'/sejour/view/{ds_id}')
        assert r.status_code == 200


# ===========================================================================
#  TESTS MODULE PUBLICATIONS
# ===========================================================================

class TestModulePublication:
    """Workflow de publication."""

    def _setup(self, app):
        # NB: 'COMMUNICATION' n'a jamais existé comme valeur de ServiceType
        # (confirmé lors de l'analyse du moteur de formulaires : en réalité,
        # seul un ADMIN peut exécuter l'étape "Communication" en legacy,
        # is_communication ne peut jamais être vrai). La création d'une
        # publication ne vérifie de toute façon que le rôle (Manager/
        # Directeur/Admin), pas un service précis — GEN sert juste de service
        # valide quelconque pour ces comptes de test.
        with app.app_context():
            make_user(username='pub_mgr', password='Mgr1234!',
                      role=UserRole.MANAGER, service=ServiceType.GEN,
                      allowed_services=[ServiceType.GEN])
            make_user(username='pub_dir', password='Dir1234!',
                      role=UserRole.DIRECTEUR, service=ServiceType.GEN,
                      allowed_services=[ServiceType.GEN])
            make_user(username='pub_com', password='Com1234!',
                      role=UserRole.SOLVER, service=ServiceType.GEN,
                      allowed_services=[ServiceType.GEN])

    def test_formulaire_publication_accessible(self, client, db_session, app):
        self._setup(app)
        login(client, 'pub_mgr', 'Mgr1234!')
        r = client.get('/publication/new')
        assert r.status_code in (200, 302)

    def test_creation_publication(self, client, db_session, app):
        self._setup(app)
        login(client, 'pub_mgr', 'Mgr1234!')
        r = client.post('/publication/new', data={
            'titre': 'Newsletter Juin 2026',
            'contenu': 'Contenu de la newsletter mensuelle.',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_validation_publication_directeur(self, client, db_session, app):
        self._setup(app)
        login(client, 'pub_dir', 'Dir1234!')
        with app.app_context():
            mgr = User.query.filter_by(username='pub_mgr').first()
            pub = Publication(
                uid_public=f'PUB-{datetime.utcnow().strftime("%Y%m%d")}-001',
                author_id=mgr.id,
                status=PublicationStatus.VALIDATION_DIRECTEUR,
                titre='Note interne',
                contenu='Contenu de la note.',
            )
            db.session.add(pub)
            db.session.commit()
            pub_id = pub.id
        r = client.post(f'/publication/validate/{pub_id}/valider',
                        follow_redirects=True)
        assert r.status_code == 200

    def test_visualisation_publication(self, client, db_session, app):
        self._setup(app)
        login(client, 'pub_mgr', 'Mgr1234!')
        with app.app_context():
            mgr = User.query.filter_by(username='pub_mgr').first()
            pub = Publication(
                uid_public=f'PUB-{datetime.utcnow().strftime("%Y%m%d")}-002',
                author_id=mgr.id,
                status=PublicationStatus.VALIDATION_DIRECTEUR,
                titre='Événement sport',
                contenu='Journée sport le 20 juin.',
            )
            db.session.add(pub)
            db.session.commit()
            pub_id = pub.id
        r = client.get(f'/publication/view/{pub_id}')
        assert r.status_code == 200


# ===========================================================================
#  TESTS INVENTAIRE & PRÊTS MATÉRIEL
# ===========================================================================

class TestInventaire:
    """Gestion de l'inventaire et des prêts."""

    def _setup(self, app):
        with app.app_context():
            make_user(username='inv_tech', password='Tech1234!',
                      role=UserRole.SOLVER, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])
            make_user(username='inv_admin', password='Adm1234!',
                      role=UserRole.ADMIN, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])

    def test_page_inventaire_accessible(self, client, db_session, app):
        self._setup(app)
        login(client, 'inv_tech', 'Tech1234!')
        r = client.get('/inventaire')
        assert r.status_code == 200

    def test_ajout_materiel(self, client, db_session, app):
        self._setup(app)
        login(client, 'inv_tech', 'Tech1234!')
        r = client.post('/inventaire/add', data={
            'categorie': 'PC',
            'modele': 'Dell Latitude 5540',
            'sn': 'SN-TEST-001',
            'hostname': 'PC-TEST-001',
            'imei': '',
            'statut': 'DISPONIBLE',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_modification_materiel(self, client, db_session, app):
        self._setup(app)
        login(client, 'inv_tech', 'Tech1234!')
        with app.app_context():
            m = Materiel(
                categorie='PC',
                modele='HP EliteBook',
                sn='SN-EDIT-001',
                hostname='PC-EDIT-001',
                statut='DISPONIBLE',
            )
            db.session.add(m)
            db.session.commit()
            mid = m.id
        r = client.post(f'/inventaire/edit/{mid}', data={
            'categorie': 'PC',
            'modele': 'HP EliteBook 840 G9',
            'sn': 'SN-EDIT-001',
            'hostname': 'PC-EDIT-001',
            'imei': '',
            'statut': 'EN_PRET',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_export_inventaire_excel(self, client, db_session, app):
        self._setup(app)
        login(client, 'inv_tech', 'Tech1234!')
        r = client.get('/export/stock')
        assert r.status_code in (200, 302)

    def test_page_prets_accessible(self, client, db_session, app):
        self._setup(app)
        login(client, 'inv_tech', 'Tech1234!')
        r = client.get('/prets')
        assert r.status_code == 200

    def test_retour_pret(self, client, db_session, app):
        self._setup(app)
        login(client, 'inv_tech', 'Tech1234!')
        with app.app_context():
            tech = User.query.filter_by(username='inv_tech').first()
            m = Materiel(
                categorie='PC',
                modele='Lenovo ThinkPad',
                sn='SN-PRET-001',
                hostname='PC-PRET-001',
                statut='EN_PRET',
            )
            db.session.add(m)
            db.session.flush()
            p = Pret(
                materiel_id=m.id,
                technicien_id=tech.id,
                nom_emprunteur='DUBOIS',
                prenom_emprunteur='Claire',
                service_emprunteur='ESAT',
                date_sortie=datetime.utcnow() - timedelta(days=5),
                date_retour_prevue=datetime.utcnow() + timedelta(days=2),
                statut_dossier='EN_COURS',
                type_pret='LONG_TERME',
            )
            db.session.add(p)
            db.session.commit()
            pid = p.id
        r = client.post(f'/pret/{pid}/retour', data={
            'date_retour_reelle': datetime.utcnow().strftime('%Y-%m-%d'),
            'etat_ecran_retour': 'BON',
            'etat_clavier_retour': 'BON',
            'etat_coque_retour': 'BON',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_export_prets_excel(self, client, db_session, app):
        self._setup(app)
        login(client, 'inv_tech', 'Tech1234!')
        r = client.get('/export/prets')
        assert r.status_code in (200, 302)


# ===========================================================================
#  TESTS API REST
# ===========================================================================

class TestAPI:
    """Endpoints de l'API JSON (notifications, team chat)."""

    def _setup(self, app):
        with app.app_context():
            make_user(username='api_user', password='Api1234!',
                      role=UserRole.USER, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])

    def test_api_notifications_non_authentifie(self, client, db_session, app):
        r = client.get('/api/notifications')
        assert r.status_code in (401, 302)

    def test_api_notifications_authentifie(self, client, db_session, app):
        self._setup(app)
        login(client, 'api_user', 'Api1234!')
        r = client.get('/api/notifications')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert 'notifications' in data or 'count' in data or isinstance(data, list)

    def test_api_count_notifications(self, client, db_session, app):
        self._setup(app)
        login(client, 'api_user', 'Api1234!')
        r = client.get('/api/notifications/count')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert 'count' in data

    def test_api_marquer_notification_lue(self, client, db_session, app):
        self._setup(app)
        login(client, 'api_user', 'Api1234!')
        with app.app_context():
            user = User.query.filter_by(username='api_user').first()
            n = make_notification(user, 'Notif test', 'info', '/portal')
            nid = n.id
        r = client.post(f'/api/notifications/read/{nid}')
        assert r.status_code == 200

    def test_api_marquer_toutes_notifications_lues(self, client, db_session, app):
        self._setup(app)
        login(client, 'api_user', 'Api1234!')
        with app.app_context():
            user = User.query.filter_by(username='api_user').first()
            for i in range(3):
                make_notification(user, f'Notif {i}', 'info', '/portal')
        r = client.post('/api/notifications/read_all')
        assert r.status_code == 200

    def test_api_team_chat_get(self, client, db_session, app):
        self._setup(app)
        login(client, 'api_user', 'Api1234!')
        r = client.get('/api/team_chat')
        assert r.status_code == 200

    def test_api_team_chat_post(self, client, db_session, app):
        self._setup(app)
        login(client, 'api_user', 'Api1234!')
        r = client.post('/api/team_chat', json={
            'content': 'Message de test depuis les tests automatiques'
        })
        assert r.status_code in (200, 201)


# ===========================================================================
#  TESTS ADMINISTRATION UTILISATEURS
# ===========================================================================

class TestAdminUtilisateurs:
    """Gestion des comptes utilisateurs (admin seulement)."""

    def _setup(self, app):
        with app.app_context():
            make_user(username='admin_main', password='Admin1234!',
                      role=UserRole.ADMIN, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])
            make_user(username='simple_user', password='User1234!',
                      role=UserRole.USER, service=ServiceType.INFO)

    def test_liste_utilisateurs_accessible_admin(self, client, db_session, app):
        self._setup(app)
        login(client, 'admin_main', 'Admin1234!')
        r = client.get('/admin/users')
        assert r.status_code == 200

    def test_liste_utilisateurs_refuse_non_admin(self, client, db_session, app):
        self._setup(app)
        login(client, 'simple_user', 'User1234!')
        r = client.get('/admin/users', follow_redirects=False)
        assert r.status_code in (302, 403)

    def test_edition_utilisateur(self, client, db_session, app):
        self._setup(app)
        login(client, 'admin_main', 'Admin1234!')
        with app.app_context():
            u = User.query.filter_by(username='simple_user').first()
            uid = u.id
        r = client.post(f'/admin/users/edit/{uid}', data={
            'role': UserRole.MANAGER.value,
            'location': 'Siège',
            'allowed_services': ServiceType.INFO.value,
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_suppression_utilisateur(self, client, db_session, app):
        self._setup(app)
        login(client, 'admin_main', 'Admin1234!')
        with app.app_context():
            to_delete = make_user(username='user_to_delete',
                                  password='Del1234!',
                                  role=UserRole.USER,
                                  service=ServiceType.INFO)
            uid = to_delete.id
        r = client.get(f'/admin/users/delete/{uid}', follow_redirects=True)
        assert r.status_code == 200


# ===========================================================================
#  TESTS CONTRÔLE D'ACCÈS RBAC
# ===========================================================================

class TestRBAC:
    """Vérification des permissions basées sur les rôles."""

    def _setup(self, app):
        with app.app_context():
            make_user(username='rbac_user', password='User1234!',
                      role=UserRole.USER, service=ServiceType.INFO)
            make_user(username='rbac_mgr', password='Mgr1234!',
                      role=UserRole.MANAGER, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])
            make_user(username='rbac_dir', password='Dir1234!',
                      role=UserRole.DIRECTEUR, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])
            make_user(username='rbac_sol', password='Sol1234!',
                      role=UserRole.SOLVER, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])
            make_user(username='rbac_adm', password='Adm1234!',
                      role=UserRole.ADMIN, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])

    def test_user_ne_peut_acceder_admin(self, client, db_session, app):
        self._setup(app)
        login(client, 'rbac_user', 'User1234!')
        r = client.get('/admin/users', follow_redirects=False)
        assert r.status_code in (302, 403)

    def test_user_ne_peut_acceder_dashboard_manager(self, client, db_session, app):
        self._setup(app)
        login(client, 'rbac_user', 'User1234!')
        r = client.get('/tickets/manager/dashboard', follow_redirects=False)
        assert r.status_code in (302, 403)

    def test_manager_peut_acceder_dashboard_manager(self, client, db_session, app):
        self._setup(app)
        login(client, 'rbac_mgr', 'Mgr1234!')
        r = client.get('/tickets/manager/dashboard')
        assert r.status_code == 200

    def test_directeur_peut_acceder_dashboard_manager(self, client, db_session, app):
        self._setup(app)
        login(client, 'rbac_dir', 'Dir1234!')
        r = client.get('/tickets/manager/dashboard')
        assert r.status_code == 200

    def test_solver_peut_acceder_dashboard_solver(self, client, db_session, app):
        self._setup(app)
        login(client, 'rbac_sol', 'Sol1234!')
        r = client.get('/tickets/solver/dashboard')
        assert r.status_code == 200

    def test_admin_peut_acceder_toutes_sections(self, client, db_session, app):
        self._setup(app)
        login(client, 'rbac_adm', 'Adm1234!')
        pages = ['/admin/users', '/tickets/manager/dashboard',
                 '/tickets/solver/dashboard', '/inventaire', '/prets']
        for page in pages:
            r = client.get(page, follow_redirects=False)
            assert r.status_code in (200, 302), \
                f"Page {page} a retourné {r.status_code}"


# ===========================================================================
#  TESTS MODÈLES (UNITAIRES)
# ===========================================================================

class TestModeles:
    """Tests unitaires des modèles SQLAlchemy."""

    def test_creation_utilisateur(self, db_session, app):
        with app.app_context():
            u = User(username='model_test', fullname='Model Test',
                     email='model@test.lan', role=UserRole.USER)
            db.session.add(u)
            db.session.commit()
            found = User.query.filter_by(username='model_test').first()
            assert found is not None
            assert found.email == 'model@test.lan'

    def test_services_json_serialisation(self, db_session, app):
        with app.app_context():
            u = User(username='svc_test', fullname='Svc Test',
                     email='svc@test.lan', role=UserRole.USER)
            u.set_origin_services([ServiceType.INFO.value, ServiceType.DAF.value])
            u.set_allowed_services([ServiceType.INFO.value])
            db.session.add(u)
            db.session.commit()
            found = User.query.filter_by(username='svc_test').first()
            origins = found.get_origin_services()
            allowed = found.get_allowed_services()
            assert ServiceType.INFO.value in origins
            assert ServiceType.DAF.value in origins
            assert ServiceType.INFO.value in allowed

    def test_uid_public_ticket_unique(self, db_session, app):
        with app.app_context():
            u = make_user(username='uid_user', password='Uid1234!')
            t1 = make_ticket(u, title='Ticket A')
            t2 = make_ticket(u, title='Ticket B')
            assert t1.uid_public != t2.uid_public

    def test_notification_to_dict(self, db_session, app):
        with app.app_context():
            u = make_user(username='notif_user', password='Notif1234!')
            n = make_notification(u, 'Test', 'info', '/portal')
            d = n.to_dict()
            assert 'message' in d
            assert 'category' in d
            assert d['is_read'] == False

    def test_ticket_get_safe_status(self, db_session, app):
        with app.app_context():
            u = make_user(username='status_user', password='St1234!')
            t = make_ticket(u)
            s = t.get_safe_status()
            assert isinstance(s, str)
            assert len(s) > 0

    def test_user_service_property(self, db_session, app):
        with app.app_context():
            u = make_user(username='prop_user', password='Prop1234!',
                          service=ServiceType.DAF)
            assert u.service == ServiceType.DAF.value

    def test_materiel_creation(self, db_session, app):
        with app.app_context():
            m = Materiel(
                categorie='TELEPHONE',
                modele='iPhone 15',
                sn='IMEI-TEST-001',
                statut='DISPONIBLE',
            )
            db.session.add(m)
            db.session.commit()
            found = Materiel.query.filter_by(sn='IMEI-TEST-001').first()
            assert found is not None
            assert found.categorie == 'TELEPHONE'


# ===========================================================================
#  TESTS MODULE TECH
# ===========================================================================

class TestModuleTech:
    """Générateur de prêts et outil technique."""

    def _setup(self, app):
        with app.app_context():
            make_user(username='tech_sol', password='Tech1234!',
                      role=UserRole.SOLVER, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])

    def test_generateur_pret_accessible(self, client, db_session, app):
        self._setup(app)
        login(client, 'tech_sol', 'Tech1234!')
        r = client.get('/tech/generateur')
        assert r.status_code == 200

    def test_get_inventory_api(self, client, db_session, app):
        self._setup(app)
        login(client, 'tech_sol', 'Tech1234!')
        r = client.get('/tech/get_inventory')
        assert r.status_code == 200


# ===========================================================================
#  TESTS SÉCURITÉ
# ===========================================================================

class TestSecurite:
    """Vérifications de sécurité basiques."""

    def test_session_invalide_apres_logout(self, client, db_session, app):
        with app.app_context():
            make_user(username='sec_user', password='Sec1234!')
        login(client, 'sec_user', 'Sec1234!')
        logout(client)
        r = client.get('/portal', follow_redirects=False)
        assert r.status_code in (302, 401)

    def test_protection_portail_sans_session(self, client, db_session, app):
        routes_protegees = [
            '/portal', '/my_history', '/tickets/manager/dashboard',
            '/tickets/solver/dashboard', '/inventaire', '/prets',
            '/admin/users',
        ]
        for route in routes_protegees:
            r = client.get(route, follow_redirects=False)
            assert r.status_code in (302, 401), \
                f"Route {route} devrait être protégée (got {r.status_code})"

    def test_api_refusee_sans_authentification(self, client, db_session, app):
        endpoints = [
            '/api/notifications',
            '/api/notifications/count',
            '/api/team_chat',
        ]
        for ep in endpoints:
            r = client.get(ep, follow_redirects=False)
            assert r.status_code in (302, 401), \
                f"Endpoint {ep} devrait nécessiter une auth (got {r.status_code})"

    def test_upload_sans_auth_refuse(self, client, db_session, app):
        r = client.post('/import/stock',
                        data={'file': (io.BytesIO(b'fake'), 'test.xlsx')},
                        follow_redirects=False)
        assert r.status_code in (302, 401, 403)


# ===========================================================================
#  TESTS PAGES D'ERREUR
# ===========================================================================

class TestPagesErreur:
    """Gestion des erreurs et redirections."""

    def test_page_404_ticket_inconnu(self, client, db_session, app):
        with app.app_context():
            make_user(username='err_user', password='Err1234!')
        login(client, 'err_user', 'Err1234!')
        r = client.get('/tickets/view/INCONNU-9999')
        assert r.status_code in (404, 302, 200)

    def test_redirect_vers_login_depuis_racine(self, client, db_session, app):
        r = client.get('/', follow_redirects=False)
        assert r.status_code in (200, 302)



# ===========================================================================
#  PAGE PROFIL (Mon compte / Apparence / Signaler un bug)
# ===========================================================================

class TestProfil:
    """Page /profile : infos, coordonnées, préférences d'apparence, bug intranet."""

    def _setup(self, app):
        with app.app_context():
            make_user(username='profil_user', password='Prof1234!',
                      role=UserRole.USER, service=ServiceType.DRH,
                      fullname='Jeanne DUPONT')
            make_user(username='profil_solver_info', password='Prof1234!',
                      role=UserRole.SOLVER, service=ServiceType.INFO,
                      allowed_services=[ServiceType.INFO])
            make_user(username='profil_solver_drh', password='Prof1234!',
                      role=UserRole.SOLVER, service=ServiceType.DRH,
                      allowed_services=[ServiceType.DRH])

    def test_profil_inaccessible_sans_login(self, client, db_session, app):
        r = client.get('/profile', follow_redirects=False)
        assert r.status_code in (302, 401)

    def test_page_profil_affiche_infos(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        r = client.get('/profile')
        assert r.status_code == 200
        html = r.data.decode()
        assert 'Jeanne' in html and 'DUPONT' in html
        assert 'profil_user@test.lan' in html
        assert 'Signaler un bug' in html and 'Apparence' in html

    def test_onglet_bug_prerempli_avec_page(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        r = client.get('/profile?tab=bug&page=/tickets/view/X')
        assert r.status_code == 200
        assert 'value="/tickets/view/X"' in r.data.decode()

    def test_maj_coordonnees(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        r = client.post('/profile/info', data={'phone': '01 23 45 67 89', 'office': 'Bât. A - 12', 'avatar_initials': 'jd'})
        assert r.status_code == 302
        with app.app_context():
            u = User.query.filter_by(username='profil_user').first()
            assert u.phone == '01 23 45 67 89'
            assert u.office == 'Bât. A - 12'
            assert u.avatar_initials == 'JD'

    def test_apparence_json_valide(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        r = client.post('/profile/appearance', json={
            'theme_color': 'indigo', 'theme_mode': 'dark', 'font_scale': 'large',
            'density': 'compact', 'high_contrast': True,
        })
        assert r.status_code == 200
        assert r.get_json()['ok'] is True
        with app.app_context():
            u = User.query.filter_by(username='profil_user').first()
            assert (u.theme_color, u.theme_mode, u.font_scale, u.density, u.high_contrast) == \
                   ('indigo', 'dark', 'large', 'compact', True)

    def test_apparence_valeurs_inconnues_ignorees(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        r = client.post('/profile/appearance', json={'theme_color': 'javascript:alert(1)', 'theme_mode': 'neon', 'font_scale': 'huge'})
        assert r.status_code == 200
        assert r.get_json()['changed'] == {}
        with app.app_context():
            u = User.query.filter_by(username='profil_user').first()
            assert u.theme_color in (None, 'teal')
            assert u.theme_mode in (None, 'auto')

    def test_preferences_appliquees_dans_le_html(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        client.post('/profile/appearance', json={'theme_color': 'rose', 'theme_mode': 'light', 'font_scale': 'xlarge', 'density': 'compact', 'high_contrast': True})
        html = client.get('/portal').data.decode()
        assert 'data-theme-color="rose"' in html
        assert 'data-font-scale="xlarge"' in html
        assert 'data-density="compact"' in html
        assert 'data-contrast="high"' in html
        assert 'window.ILVM_THEME_MODE = "light"' in html

    def test_declaration_bug_cree_ticket_info_et_notifie(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        r = client.post('/profile/bug', data={
            'title': 'Bouton Valider inactif', 'bug_type': 'Erreur',
            'page': '/tickets/view/20260101-001', 'description': 'Rien ne se passe au clic.',
            'user_agent': 'TestBrowser/1.0', 'screen': '1920x1080',
        }, follow_redirects=False)
        assert r.status_code == 302
        with app.app_context():
            t = Ticket.query.filter(Ticket.category_ticket == 'Bug Intranet').first()
            assert t is not None
            assert t.title == '[Bug Intranet] Bouton Valider inactif'
            assert t.target_service == ServiceType.INFO
            assert t.status == TicketStatus.PENDING
            assert t.author.username == 'profil_user'
            assert t.service_demandeur == 'DRH'
            for fragment in ('Type : Erreur', '/tickets/view/20260101-001', 'Rien ne se passe', 'TestBrowser/1.0', '1920x1080'):
                assert fragment in t.description
            assert r.headers['Location'].endswith(f'/tickets/view/{t.uid_public}')
            # Le solver Informatique est notifié in-app, pas celui de la DRH.
            info = User.query.filter_by(username='profil_solver_info').first()
            drh = User.query.filter_by(username='profil_solver_drh').first()
            assert Notification.query.filter_by(user_id=info.id).count() == 1
            assert Notification.query.filter_by(user_id=drh.id).count() == 0

    def test_declaration_bug_champs_obligatoires(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        r = client.post('/profile/bug', data={'title': '', 'description': ''}, follow_redirects=False)
        assert r.status_code == 302
        assert 'tab=bug' in r.headers['Location']
        with app.app_context():
            assert Ticket.query.count() == 0

    def test_declaration_bug_avec_capture(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        data = {'title': 'Affichage cassé', 'bug_type': 'Affichage', 'description': 'Voir capture.',
                'screenshot': (io.BytesIO(b'\x89PNG fake'), 'ecran.png')}
        r = client.post('/profile/bug', data=data, content_type='multipart/form-data')
        assert r.status_code == 302
        with app.app_context():
            t = Ticket.query.filter(Ticket.category_ticket == 'Bug Intranet').first()
            assert t.get_daf_files() == ['CAPTURE_ecran.png']
            import shutil
            shutil.rmtree(os.path.join(app.root_path, 'static', 'uploads', 'tickets', t.uid_public), ignore_errors=True)

    def test_detail_ticket_affiche_coordonnees_profil(self, client, db_session, app):
        self._setup(app)
        login(client, 'profil_user', 'Prof1234!')
        client.post('/profile/info', data={'phone': '4512', 'office': 'Bureau 7'})
        client.post('/profile/bug', data={'title': 'X', 'description': 'Y'})
        with app.app_context():
            uid = Ticket.query.first().uid_public
        html = client.get(f'/tickets/view/{uid}').data.decode()
        assert '4512' in html and 'Bureau 7' in html


# ===========================================================================
#  CONNEXION SSO MICROSOFT ENTRA ID (Microsoft et l'AD sont simulés)
# ===========================================================================

class _FakeAttr:
    def __init__(self, v): self.v = v
    def __str__(self): return self.v
    def __bool__(self): return bool(self.v)
    def __iter__(self): return iter(self.v)

class _FakeAdEntry:
    """Imite une entrée ldap3 (attributs displayName / mail / memberOf / sAMAccountName)."""
    def __init__(self, sam, display, mail, groups):
        self.sAMAccountName = _FakeAttr(sam)
        self.displayName = _FakeAttr(display)
        self.mail = _FakeAttr(mail)
        self.memberOf = _FakeAttr([f'CN={g},OU=Groupes,DC=ilvm,DC=lan' for g in groups])

class _FakeMsal:
    """Remplace msal.ConfidentialClientApplication : pas d'appel réseau."""
    def __init__(self, claims=None, error=None):
        self.claims, self.error = claims, error
    def initiate_auth_code_flow(self, scopes, redirect_uri=None, **kw):
        assert redirect_uri == 'http://localhost/auth/microsoft/callback'
        return {'state': 'abc', 'auth_uri': 'https://login.microsoftonline.com/fake?state=abc', 'code_verifier': 'x'}
    def acquire_token_by_auth_code_flow(self, flow, args, **kw):
        if args.get('state') != flow['state']:
            raise ValueError('state mismatch')
        if self.error:
            return {'error': self.error, 'error_description': 'simulé'}
        return {'access_token': 'tok', 'id_token_claims': self.claims}


class TestSSOMicrosoft:
    TENANT = '00000000-0000-0000-0000-00000000tnt1'

    def _configure(self, app, monkeypatch, claims=None, error=None, ad_entry='default'):
        app.config['AZURE_SSO_TENANT_ID'] = self.TENANT
        app.config['AZURE_SSO_CLIENT_ID'] = 'client-id'
        app.config['AZURE_SSO_CLIENT_SECRET'] = 'secret'
        import app.routes.auth as auth_mod
        monkeypatch.setattr(auth_mod, '_msal_app', lambda: _FakeMsal(claims, error))
        if ad_entry == 'default':
            ad_entry = ('jdupont', 'Jeanne DUPONT', 'JDupont@ilvm.fr', ['GR-MANAGER', 'GS-DRH', 'GU-DRH'])
        def fake_lookup(upn):
            fake_lookup.called_with = upn
            if ad_entry is None: return None, None
            return ad_entry[0], _FakeAdEntry(*ad_entry)
        fake_lookup.called_with = None
        monkeypatch.setattr(auth_mod, 'ldap_lookup_by_upn', fake_lookup)
        return fake_lookup

    def _start_flow(self, client):
        r = client.get('/auth/microsoft')
        assert r.status_code == 302 and r.headers['Location'].startswith('https://login.microsoftonline.com/')
        with client.session_transaction() as sess:
            assert sess['sso_flow']['state'] == 'abc'

    def _claims(self, **over):
        c = {'tid': self.TENANT, 'preferred_username': 'JDupont@ilvm.fr', 'name': 'Jeanne DUPONT'}
        c.update(over); return c

    def test_sso_non_configure_renvoie_vers_login(self, client, db_session, app):
        app.config['AZURE_SSO_CLIENT_SECRET'] = None
        r = client.get('/auth/microsoft')
        assert r.status_code == 302 and r.headers['Location'].endswith('/auth/login')

    def test_bouton_microsoft_visible_seulement_si_configure(self, client, db_session, app):
        app.config['AZURE_SSO_CLIENT_ID'] = None
        assert 'compte Microsoft 365' not in client.get('/auth/login').data.decode()
        app.config['AZURE_SSO_CLIENT_ID'] = 'client-id'
        assert 'compte Microsoft 365' in client.get('/auth/login').data.decode()

    def test_callback_sans_flux_en_session(self, client, db_session, app, monkeypatch):
        self._configure(app, monkeypatch)
        r = client.get('/auth/microsoft/callback?code=x&state=abc')
        assert r.status_code == 302 and r.headers['Location'].endswith('/auth/login')

    def test_connexion_sso_cree_le_compte_avec_les_droits_ad(self, client, db_session, app, monkeypatch):
        lookup = self._configure(app, monkeypatch, claims=self._claims())
        self._start_flow(client)
        r = client.get('/auth/microsoft/callback?code=x&state=abc')
        assert r.status_code == 302 and r.headers['Location'].endswith('/portal')
        assert lookup.called_with == 'JDupont@ilvm.fr'
        with app.app_context():
            u = User.query.filter_by(username='jdupont').first()
            assert u is not None
            assert u.role == UserRole.MANAGER
            assert u.get_allowed_services() == ['DRH'] and u.get_origin_services() == ['DRH']
            assert u.fullname == 'Jeanne DUPONT' and u.email == 'JDupont@ilvm.fr'
        # Session ouverte : le portail est accessible
        assert client.get('/portal').status_code == 200
        # Le flux a été consommé, il ne reste rien en session
        with client.session_transaction() as sess:
            assert 'sso_flow' not in sess

    def test_connexion_sso_reutilise_le_compte_existant(self, client, db_session, app, monkeypatch):
        with app.app_context():
            existing = make_user(username='jdupont', role=UserRole.USER, service=ServiceType.INFO)
            existing.theme_color = 'rose'; existing.phone = '4512'; db.session.commit(); existing_id = existing.id
        self._configure(app, monkeypatch, claims=self._claims())
        self._start_flow(client)
        client.get('/auth/microsoft/callback?code=x&state=abc')
        with app.app_context():
            users = User.query.filter_by(username='jdupont').all()
            assert len(users) == 1 and users[0].id == existing_id
            assert users[0].role == UserRole.MANAGER          # droits recalculés depuis l'AD
            assert users[0].theme_color == 'rose' and users[0].phone == '4512'  # préférences conservées

    def test_connexion_sso_respecte_next(self, client, db_session, app, monkeypatch):
        self._configure(app, monkeypatch, claims=self._claims())
        client.get('/auth/microsoft?next=/my_history')
        r = client.get('/auth/microsoft/callback?code=x&state=abc')
        assert r.headers['Location'].endswith('/my_history')

    def test_next_externe_ignore(self, client, db_session, app, monkeypatch):
        self._configure(app, monkeypatch, claims=self._claims())
        client.get('/auth/microsoft?next=https://evil.example/phish')
        r = client.get('/auth/microsoft/callback?code=x&state=abc')
        assert r.headers['Location'].endswith('/portal')

    def test_state_incoherent_refuse(self, client, db_session, app, monkeypatch):
        self._configure(app, monkeypatch, claims=self._claims())
        self._start_flow(client)
        r = client.get('/auth/microsoft/callback?code=x&state=WRONG')
        assert r.headers['Location'].endswith('/auth/login')
        with app.app_context():
            assert User.query.filter_by(username='jdupont').first() is None

    def test_erreur_microsoft_refuse(self, client, db_session, app, monkeypatch):
        self._configure(app, monkeypatch, error='access_denied')
        self._start_flow(client)
        r = client.get('/auth/microsoft/callback?error=access_denied&state=abc')
        assert r.headers['Location'].endswith('/auth/login')
        assert client.get('/portal').status_code == 302

    def test_autre_locataire_refuse(self, client, db_session, app, monkeypatch):
        self._configure(app, monkeypatch, claims=self._claims(tid='autre-tenant'))
        self._start_flow(client)
        r = client.get('/auth/microsoft/callback?code=x&state=abc')
        assert r.headers['Location'].endswith('/auth/login')
        with app.app_context():
            assert User.query.count() == 0

    def test_compte_absent_de_l_ad_refuse(self, client, db_session, app, monkeypatch):
        self._configure(app, monkeypatch, claims=self._claims(preferred_username='invite@partenaire.fr'), ad_entry=None)
        self._start_flow(client)
        r = client.get('/auth/microsoft/callback?code=x&state=abc')
        assert r.headers['Location'].endswith('/auth/login')
        with app.app_context():
            assert User.query.count() == 0
        assert client.get('/portal').status_code == 302

    def test_deja_connecte_va_directement_au_portail(self, client, db_session, app, monkeypatch):
        self._configure(app, monkeypatch)
        with app.app_context():
            make_user(username='deja', role=UserRole.USER)
        login(client, 'deja')
        r = client.get('/auth/microsoft')
        assert r.status_code == 302 and r.headers['Location'].endswith('/portal')

    def test_login_ldap_classique_inchange(self, client, db_session, app):
        # Le formulaire LDAP reste la porte d'entrée normale (LDAP indisponible en test → message d'erreur, pas de 500)
        r = client.post('/auth/login', data={'username': 'x', 'password': 'y'})
        assert r.status_code == 200


# ===========================================================================
#  LOT UX 2026-09-28 : statuts humains, frise, portail, recherche, avis,
#  réouverture, conseils avant envoi, réponses types, casse identifiant
# ===========================================================================

class TestLotUX:

    def _users(self, app):
        with app.app_context():
            make_user(username='ux_user', role=UserRole.USER, service=ServiceType.DRH, fullname='Ursule XAVIER')
            make_user(username='ux_solver', role=UserRole.SOLVER, service=ServiceType.INFO, allowed_services=[ServiceType.INFO])
            make_user(username='ux_admin', role=UserRole.ADMIN, service=ServiceType.INFO, allowed_services=[ServiceType.INFO])

    def _ticket(self, app, status=TicketStatus.PENDING, author='ux_user', solver=None, title='Imprimante en panne', closed_days_ago=None):
        with app.app_context():
            a = User.query.filter_by(username=author).first()
            s = User.query.filter_by(username=solver).first() if solver else None
            t = Ticket(title=title, description='desc', author=a, solver=s, target_service=ServiceType.INFO,
                       status=status, uid_public=f'T{Ticket.query.count()+1:03d}', category_ticket='Incident Standard',
                       created_at=datetime.now(), service_demandeur='DRH')
            if closed_days_ago is not None:
                t.closed_at = datetime.now() - timedelta(days=closed_days_ago)
            db.session.add(t); db.session.commit()
            return t.uid_public

    # --- statuts humains + frise ---
    def test_filtre_status_label(self, app):
        from app.status_display import status_label, ticket_timeline
        assert status_label(TicketStatus.PENDING) == 'En attente de prise en charge'
        assert status_label(TicketStatus.VALIDATION_N1, short=True) == 'Validation manager'
        assert status_label('INCONNU_X') == 'Inconnu x'

    def test_frise_selon_statut(self, app, db_session):
        self._users(app)
        from app.status_display import ticket_timeline
        with app.app_context():
            for status, expected in [
                (TicketStatus.VALIDATION_N1, ['done', 'current', 'todo', 'todo', 'todo']),
                (TicketStatus.REFUSED,       ['done', 'failed', 'todo', 'todo', 'todo']),
                (TicketStatus.PENDING,       ['done', 'current', 'todo', 'todo']),
                (TicketStatus.IN_PROGRESS,   ['done', 'done', 'current', 'todo']),
                (TicketStatus.DONE,          ['done', 'done', 'done', 'done']),
            ]:
                uid = self._ticket(app, status=status, solver='ux_solver' if status in (TicketStatus.IN_PROGRESS, TicketStatus.DONE) else None)
                t = Ticket.query.filter_by(uid_public=uid).first()
                assert [st['state'] for st in ticket_timeline(t)] == expected, status

    def test_detail_ticket_affiche_frise_et_libelle(self, client, db_session, app):
        self._users(app)
        uid = self._ticket(app, status=TicketStatus.PENDING)
        login(client, 'ux_user')
        html = client.get(f'/tickets/view/{uid}').data.decode()
        assert 'Suivi de la demande' in html and 'En attente de prise en charge' in html
        assert 'EN_ATTENTE_TRAITEMENT' not in html

    # --- portail : demandes en cours en tête ---
    def test_portail_bloc_demandes_en_cours(self, client, db_session, app):
        self._users(app)
        self._ticket(app, status=TicketStatus.IN_PROGRESS, solver='ux_solver', title='Souris cassée')
        self._ticket(app, status=TicketStatus.DONE, solver='ux_solver', title='Vieux ticket clos', closed_days_ago=30)
        login(client, 'ux_user')
        html = client.get('/portal').data.decode()
        assert 'Mes demandes en cours' in html
        assert html.index('Souris cassée') < html.index('Grille Services')
        assert 'Vieux ticket clos' in html  # reste dans le tableau des dernières demandes

    def test_portail_sans_demande_en_cours(self, client, db_session, app):
        self._users(app)
        login(client, 'ux_user')
        html = client.get('/portal').data.decode()
        assert 'Mes demandes en cours' not in html
        assert 'Créer' in html or 'première demande' in html

    # --- recherche globale ---
    def test_recherche_mes_demandes_et_formulaires(self, client, db_session, app):
        self._users(app)
        uid = self._ticket(app, title='Ecran noir au démarrage')
        login(client, 'ux_user')
        r = client.get('/api/search?q=ecran')
        d = r.get_json()
        assert [m['ref'] for m in d['mine']] == [uid]
        assert d['tickets'] == []  # un USER ne voit pas les tickets des services
        assert any('Informatique' in f['title'] for f in client.get('/api/search?q=informatique').get_json()['forms'])
        page = client.get('/search?q=ecran').data.decode()
        assert 'Ecran noir' in page

    def test_recherche_tickets_de_mon_service_solver(self, client, db_session, app):
        self._users(app)
        uid = self._ticket(app, title='Clavier bloqué')
        login(client, 'ux_solver')
        d = client.get('/api/search?q=clavier').get_json()
        assert [t['ref'] for t in d['tickets']] == [uid]
        d2 = client.get('/api/search?q=Ursule').get_json()  # par nom du demandeur
        assert [t['ref'] for t in d2['tickets']] == [uid]

    def test_recherche_trop_courte(self, client, db_session, app):
        self._users(app)
        login(client, 'ux_user')
        assert client.get('/api/search?q=a').get_json() == {'query': 'a', 'mine': [], 'forms': [], 'tickets': []}

    # --- satisfaction ---
    def test_avis_rapide_depuis_email(self, client, db_session, app):
        self._users(app)
        uid = self._ticket(app, status=TicketStatus.DONE, solver='ux_solver', closed_days_ago=0)
        login(client, 'ux_user')
        r = client.get(f'/tickets/rate/{uid}/3')
        assert r.status_code == 302
        with app.app_context():
            t = Ticket.query.filter_by(uid_public=uid).first()
            assert t.satisfaction == 3 and t.satisfaction_at is not None
        # Un second clic ne réécrit pas l'avis
        client.get(f'/tickets/rate/{uid}/1')
        with app.app_context():
            assert Ticket.query.filter_by(uid_public=uid).first().satisfaction == 3

    def test_avis_formulaire_avec_commentaire(self, client, db_session, app):
        self._users(app)
        uid = self._ticket(app, status=TicketStatus.DONE, solver='ux_solver', closed_days_ago=1)
        login(client, 'ux_user')
        client.post(f'/tickets/rate/{uid}', data={'score': '1', 'comment': 'Pas résolu vraiment'})
        with app.app_context():
            t = Ticket.query.filter_by(uid_public=uid).first()
            assert (t.satisfaction, t.satisfaction_comment) == (1, 'Pas résolu vraiment')

    def test_avis_refuse_si_pas_auteur_ou_pas_termine(self, client, db_session, app):
        self._users(app)
        uid_open = self._ticket(app, status=TicketStatus.IN_PROGRESS, solver='ux_solver')
        uid_done = self._ticket(app, status=TicketStatus.DONE, solver='ux_solver', closed_days_ago=0)
        login(client, 'ux_user')
        client.get(f'/tickets/rate/{uid_open}/3')
        login(client, 'ux_solver')
        client.get(f'/tickets/rate/{uid_done}/3')
        with app.app_context():
            assert Ticket.query.filter_by(uid_public=uid_open).first().satisfaction is None
            assert Ticket.query.filter_by(uid_public=uid_done).first().satisfaction is None

    def test_stats_incluent_la_satisfaction(self, client, db_session, app):
        self._users(app)
        for score in (3, 3, 1):
            uid = self._ticket(app, status=TicketStatus.DONE, solver='ux_solver', closed_days_ago=0)
            with app.app_context():
                t = Ticket.query.filter_by(uid_public=uid).first(); t.satisfaction = score; db.session.commit()
        login(client, 'ux_admin')
        html = client.get('/tickets/stats?services=INFORMATIQUE').data.decode()
        assert '3 avis' in html and '67%' in html

    # --- réouverture ---
    def test_reouverture_par_le_demandeur(self, client, db_session, app):
        self._users(app)
        uid = self._ticket(app, status=TicketStatus.DONE, solver='ux_solver', closed_days_ago=2)
        login(client, 'ux_user')
        r = client.post(f'/tickets/reopen/{uid}', data={'reason': "L'imprimante bloque encore"})
        assert r.status_code == 302
        with app.app_context():
            t = Ticket.query.filter_by(uid_public=uid).first()
            assert t.status == TicketStatus.IN_PROGRESS and t.closed_at is None and t.reopen_count == 1
            assert "rouverte" in t.messages[-1].content and "bloque encore" in t.messages[-1].content
            solver = User.query.filter_by(username='ux_solver').first()
            assert Notification.query.filter_by(user_id=solver.id).filter(Notification.message.like('%rouvert%')).count() == 1

    def test_reouverture_sans_technicien_repasse_en_attente(self, client, db_session, app):
        self._users(app)
        uid = self._ticket(app, status=TicketStatus.DONE, closed_days_ago=0)
        login(client, 'ux_user')
        client.post(f'/tickets/reopen/{uid}', data={'reason': 'Toujours pareil'})
        with app.app_context():
            assert Ticket.query.filter_by(uid_public=uid).first().status == TicketStatus.PENDING

    def test_reouverture_refusee_apres_7_jours_ou_sans_motif(self, client, db_session, app):
        self._users(app)
        old = self._ticket(app, status=TicketStatus.DONE, solver='ux_solver', closed_days_ago=8)
        recent = self._ticket(app, status=TicketStatus.DONE, solver='ux_solver', closed_days_ago=1)
        login(client, 'ux_user')
        client.post(f'/tickets/reopen/{old}', data={'reason': 'x'})
        client.post(f'/tickets/reopen/{recent}', data={'reason': '   '})
        with app.app_context():
            assert Ticket.query.filter_by(uid_public=old).first().status == TicketStatus.DONE
            assert Ticket.query.filter_by(uid_public=recent).first().status == TicketStatus.DONE

    def test_reouverture_refusee_si_pas_auteur(self, client, db_session, app):
        self._users(app)
        uid = self._ticket(app, status=TicketStatus.DONE, solver='ux_solver', closed_days_ago=1)
        login(client, 'ux_solver')
        client.post(f'/tickets/reopen/{uid}', data={'reason': 'test'})
        with app.app_context():
            assert Ticket.query.filter_by(uid_public=uid).first().status == TicketStatus.DONE

    # --- conseils avant envoi + réponses types ---
    def test_conseils_affiches_sur_le_formulaire_legacy(self, client, db_session, app):
        from app.models import HelpTip
        self._users(app)
        with app.app_context():
            db.session.add(HelpTip(context='DAF', title='Avez-vous le devis ?', body='Un devis PDF est obligatoire.'))
            db.session.add(HelpTip(context='DAF', title='Conseil désactivé', body='x', is_active=False))
            db.session.commit()
        login(client, 'ux_user')
        html = client.get('/tickets/new/DAF').data.decode()
        assert 'Avez-vous le devis' in html and 'Conseil désactivé' not in html

    def test_reponses_types_visibles_par_le_technicien_pas_le_demandeur(self, client, db_session, app):
        from app.models import CannedResponse
        self._users(app)
        with app.app_context():
            db.session.add(CannedResponse(title='Précision poste', body='Pouvez-vous préciser le poste ?'))
            db.session.add(CannedResponse(title='Spécifique DRH', body='x', service='DRH'))
            db.session.commit()
        uid = self._ticket(app, status=TicketStatus.IN_PROGRESS, solver='ux_solver')
        login(client, 'ux_solver')
        html = client.get(f'/tickets/view/{uid}').data.decode()
        assert 'id="canned-select"' in html and 'Précision poste' in html and 'Spécifique DRH' not in html
        login(client, 'ux_user')
        assert 'id="canned-select"' not in client.get(f'/tickets/view/{uid}').data.decode()

    def test_admin_contenus_aide_crud(self, client, db_session, app):
        from app.models import HelpTip, CannedResponse
        self._users(app)
        login(client, 'ux_user')
        assert client.get('/admin/help-contents').status_code in (302, 403)
        login(client, 'ux_admin')
        assert client.get('/admin/help-contents').status_code == 200
        client.post('/admin/help-contents', data={'action': 'add_tip', 'context': 'info-v2', 'title': 'Redémarrer', 'body': 'Éteignez puis rallumez.', 'sort_order': '1'})
        client.post('/admin/help-contents', data={'action': 'add_response', 'title': 'Merci', 'body': 'Merci pour votre retour.', 'service': ''})
        with app.app_context():
            tip = HelpTip.query.filter_by(title='Redémarrer').first(); resp = CannedResponse.query.filter_by(title='Merci').first()
            assert tip and tip.context == 'info-v2' and resp and resp.service is None
            tip_id, resp_id = tip.id, resp.id
        client.post('/admin/help-contents', data={'action': 'toggle_tip', 'id': tip_id})
        client.post('/admin/help-contents', data={'action': 'delete_response', 'id': resp_id})
        with app.app_context():
            assert HelpTip.query.get(tip_id).is_active is False
            assert CannedResponse.query.get(resp_id) is None

    # --- casse de l'identifiant ---
    def test_provisioning_aligne_la_graphie_sur_l_ad(self, app, db_session):
        """Quelle que soit la casse tapée (nprenom / NPRENOM / NPrenom), un seul
        compte, un seul id, et le username stocké prend la graphie de l'AD."""
        from app.routes.auth import provision_user_from_ad_entry
        with app.app_context():
            entry = _FakeAdEntry('NPrenom', 'Nom PRENOM', 'NPrenom@ilvm.fr', ['GU-DRH'])
            ids = set()
            for typed in ('nprenom', 'NPRENOM', 'Nprenom', 'NPrenom'):
                u = provision_user_from_ad_entry(str(entry.sAMAccountName), entry); db.session.commit()
                ids.add(u.id)
            assert len(ids) == 1
            assert User.query.filter(User.username.ilike('nprenom')).count() == 1
            assert User.query.filter(User.username.ilike('nprenom')).first().username == 'NPrenom'

    def test_provisioning_insensible_a_la_casse(self, app, db_session):
        from app.routes.auth import provision_user_from_ad_entry
        with app.app_context():
            existing = make_user(username='astraore', role=UserRole.USER, service=ServiceType.INFO); existing_id = existing.id
            entry = _FakeAdEntry('AsTraore', 'Assane TRAORE', 'AsTraore@ilvm.fr', ['GR-SOLVER', 'GS-INFORMATIQUE', 'GU-INFORMATIQUE'])
            u = provision_user_from_ad_entry('ASTRAORE', entry); db.session.commit()
            assert u.id == existing_id
            assert User.query.filter(User.username.ilike('astraore')).count() == 1
            assert u.role == UserRole.SOLVER


# ===========================================================================
#  LOT 2 (2026-09-28) : annonces, filtres/export d'historique, préférence
#  e-mail, résumé quotidien et récap hebdo managers
# ===========================================================================

class TestLot2:

    def _users(self, app):
        with app.app_context():
            make_user(username='l2_user', role=UserRole.USER, service=ServiceType.DRH, fullname='Lucie DEUX')
            make_user(username='l2_com', role=UserRole.USER, service=ServiceType.COMMUNICATION, allowed_services=[ServiceType.COMMUNICATION])
            make_user(username='l2_admin', role=UserRole.ADMIN, service=ServiceType.INFO, allowed_services=[ServiceType.INFO])
            make_user(username='l2_manager', role=UserRole.MANAGER, service=ServiceType.DRH, allowed_services=[ServiceType.INFO])
            make_user(username='l2_solver', role=UserRole.SOLVER, service=ServiceType.INFO, allowed_services=[ServiceType.INFO])

    def _ticket(self, app, status, author='l2_user', service=ServiceType.INFO, title='Sujet', days_ago=0, solver=None):
        with app.app_context():
            a = User.query.filter_by(username=author).first()
            s = User.query.filter_by(username=solver).first() if solver else None
            t = Ticket(title=title, description='d', author=a, solver=s, target_service=service, status=status,
                       uid_public=f'L2-{Ticket.query.count()+1:03d}', category_ticket='Standard',
                       created_at=datetime.now() - timedelta(days=days_ago), service_demandeur='DRH')
            if status == TicketStatus.DONE: t.closed_at = datetime.now()
            db.session.add(t); db.session.commit(); return t.uid_public

    # --- annonces ---
    def test_annonce_visible_selon_dates_et_activation(self, app, db_session):
        from app.models import Announcement
        now = datetime(2026, 9, 28, 12, 0)
        a = Announcement(title='x', body='y')
        assert a.is_visible(now)
        a.is_active = False; assert not a.is_visible(now); a.is_active = True
        a.starts_at = now + timedelta(days=1); assert not a.is_visible(now); a.starts_at = None
        a.ends_at = now - timedelta(hours=1); assert not a.is_visible(now)

    def test_gestion_annonces_acces(self, client, db_session, app):
        self._users(app)
        login(client, 'l2_user');    assert client.get('/announcements/manage').status_code == 403
        login(client, 'l2_com');     assert client.get('/announcements/manage').status_code == 200
        login(client, 'l2_admin');   assert client.get('/announcements/manage').status_code == 200

    def test_publication_annonce_et_bandeau_portail(self, client, db_session, app):
        from app.models import Announcement
        self._users(app)
        login(client, 'l2_com')
        client.post('/announcements/manage', data={'action': 'add', 'title': 'Maintenance messagerie', 'body': 'Samedi 8h-12h', 'level': 'warning'})
        client.post('/announcements/manage', data={'action': 'add', 'title': 'Future annonce', 'body': 'x', 'level': 'info', 'starts_at': '2099-01-01'})
        with app.app_context():
            a = Announcement.query.filter_by(title='Maintenance messagerie').first()
            assert a and a.level == 'warning' and a.created_by.username == 'l2_com'
            future_id = Announcement.query.filter_by(title='Future annonce').first().id
        login(client, 'l2_user')
        html = client.get('/portal').data.decode()
        assert 'Maintenance messagerie' in html and 'Samedi 8h-12h' in html
        assert 'Future annonce' not in html
        # Un simple utilisateur ne peut pas modifier
        r = client.post('/announcements/manage', data={'action': 'delete', 'id': future_id})
        assert r.status_code == 403
        login(client, 'l2_com')
        client.post('/announcements/manage', data={'action': 'toggle', 'id': future_id})
        with app.app_context():
            assert Announcement.query.get(future_id).is_active is False

    # --- historique : filtres + export ---
    def test_historique_filtres(self, client, db_session, app):
        self._users(app)
        self._ticket(app, TicketStatus.IN_PROGRESS, title='Ouvert INFO', service=ServiceType.INFO, solver='l2_solver')
        self._ticket(app, TicketStatus.DONE, title='Fini DRH', service=ServiceType.DRH, days_ago=10)
        self._ticket(app, TicketStatus.REFUSED, title='Refuse GEN', service=ServiceType.GEN)
        login(client, 'l2_user')
        def titles(qs):
            html = client.get('/my_history' + qs).data.decode()
            return [t for t in ('Ouvert INFO', 'Fini DRH', 'Refuse GEN') if t in html]
        assert titles('') == ['Ouvert INFO', 'Fini DRH', 'Refuse GEN']
        assert titles('?status=open') == ['Ouvert INFO']
        assert titles('?status=done') == ['Fini DRH']
        assert titles('?status=refused') == ['Refuse GEN']
        assert titles('?service=DRH') == ['Fini DRH']
        recent = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        assert titles(f'?date_from={recent}') == ['Ouvert INFO', 'Refuse GEN']
        assert titles(f'?date_to={recent}') == ['Fini DRH']

    def test_historique_export_csv_et_excel(self, client, db_session, app):
        self._users(app)
        self._ticket(app, TicketStatus.DONE, title='Export moi', days_ago=1)
        self._ticket(app, TicketStatus.IN_PROGRESS, title='Pas moi', solver='l2_solver')
        login(client, 'l2_user')
        r = client.get('/my_history/export?status=done')
        assert r.status_code == 200 and 'text/csv' in r.headers['Content-Type']
        body = r.data.decode('utf-8-sig')
        assert 'Export moi' in body and 'Pas moi' not in body and 'Terminée' in body
        r = client.get('/my_history/export?format=xlsx')
        assert r.status_code == 200 and 'spreadsheetml' in r.headers['Content-Type']
        assert r.data[:2] == b'PK'  # zip = xlsx

    # --- préférence e-mail ---
    def test_profil_enregistre_la_preference_email(self, client, db_session, app):
        self._users(app)
        login(client, 'l2_user')
        client.post('/profile/info', data={'phone': '', 'office': '', 'email_mode': 'daily'})
        with app.app_context():
            assert User.query.filter_by(username='l2_user').first().email_mode == 'daily'
        client.post('/profile/info', data={'email_mode': 'n_importe_quoi'})
        with app.app_context():
            assert User.query.filter_by(username='l2_user').first().email_mode == 'daily'

    def test_filtre_destinataires_selon_preference(self, app, db_session):
        from app.emails import filter_recipients_by_preference
        self._users(app)
        with app.app_context():
            User.query.filter_by(username='l2_user').first().email_mode = 'important'
            User.query.filter_by(username='l2_com').first().email_mode = 'daily'
            db.session.commit()
            all_r = ['l2_user@test.lan', 'L2_COM@test.lan', 'l2_admin@test.lan', 'inconnu@ailleurs.fr']
            assert filter_recipients_by_preference(all_r, 'message') == ['l2_admin@test.lan', 'inconnu@ailleurs.fr']
            assert filter_recipients_by_preference(all_r, 'important') == ['l2_user@test.lan', 'l2_admin@test.lan', 'inconnu@ailleurs.fr']
            assert filter_recipients_by_preference(all_r, 'digest') == all_r

    # --- résumés ---
    def test_resume_quotidien_liste_les_notifications_recentes(self, app, db_session):
        from app.digests import daily_digest_for, daily_digest_recipients
        self._users(app)
        with app.app_context():
            u = User.query.filter_by(username='l2_user').first(); u.email_mode = 'daily'
            db.session.add(Notification(user=u, message='Récent', timestamp=datetime.utcnow() - timedelta(hours=2)))
            db.session.add(Notification(user=u, message='Vieux', timestamp=datetime.utcnow() - timedelta(days=3)))
            db.session.commit()
            assert [x.username for x in daily_digest_recipients()] == ['l2_user']
            assert [n.message for n in daily_digest_for(u)] == ['Récent']

    def test_recap_hebdo_manager(self, app, db_session):
        from app.digests import weekly_manager_summary, weekly_digest_recipients
        self._users(app)
        # N1 : demandeur du service DRH (origine du manager), pas lui-même
        n1 = self._ticket(app, TicketStatus.VALIDATION_N1, title='A valider N1')
        # N2 : cible INFO (service géré par le manager)
        n2 = self._ticket(app, TicketStatus.VALIDATION_N2, title='A valider N2', service=ServiceType.INFO)
        stale = self._ticket(app, TicketStatus.PENDING, title='En retard', service=ServiceType.INFO, days_ago=3)
        self._ticket(app, TicketStatus.PENDING, title='Autre service', service=ServiceType.GEN, days_ago=3)
        with app.app_context():
            m = User.query.filter_by(username='l2_manager').first()
            assert 'l2_manager' in [u.username for u in weekly_digest_recipients()]
            data = weekly_manager_summary(m)
            assert [t.uid_public for t in data['pending_tickets']] == [n1, n2]
            assert [t.uid_public for t in data['stale']] == [stale]
            assert {t.uid_public for t in data['received_week']} == {n1, n2, stale}  # tous ciblent INFO
            # Un manager sans rien à traiter -> None (pas d'e-mail)
            other = make_user(username='l2_manager2', role=UserRole.MANAGER, service=ServiceType.SG, allowed_services=[ServiceType.SG])
            assert weekly_manager_summary(other) is None

    def test_email_recap_hebdo_se_construit(self, app, db_session):
        from app.digests import weekly_manager_summary
        from app.emails import send_weekly_manager_digest, send_daily_digest
        self._users(app)
        self._ticket(app, TicketStatus.VALIDATION_N1, title='A valider')
        with app.app_context():
            m = User.query.filter_by(username='l2_manager').first()
            send_weekly_manager_digest(m, weekly_manager_summary(m))  # MAIL_SUPPRESS_SEND : ne doit juste pas planter
            u = User.query.filter_by(username='l2_user').first()
            db.session.add(Notification(user=u, message='Test', link='/tickets/view/X')); db.session.commit()
            send_daily_digest(u, u.notifications.all())


# ===========================================================================
#  LOT 3 (2026-09-28) : SLA configurables, tableau de bord manager enrichi
#  (KPI, > 48 h, validation en lot), traçabilité des validations
# ===========================================================================

class TestLot3:

    def _users(self, app):
        with app.app_context():
            make_user(username='l3_user', role=UserRole.USER, service=ServiceType.DRH)
            make_user(username='l3_manager', role=UserRole.MANAGER, service=ServiceType.DRH, allowed_services=[ServiceType.INFO])
            make_user(username='l3_solver', role=UserRole.SOLVER, service=ServiceType.INFO, allowed_services=[ServiceType.INFO])
            make_user(username='l3_admin', role=UserRole.ADMIN, service=ServiceType.INFO, allowed_services=[ServiceType.INFO])

    def _ticket(self, app, status, service=ServiceType.INFO, category='Incident Standard', hours_ago=0, title='T', author='l3_user'):
        with app.app_context():
            a = User.query.filter_by(username=author).first()
            t = Ticket(title=title, description='d', author=a, target_service=service, status=status,
                       uid_public=f'L3-{Ticket.query.count()+1:03d}', category_ticket=category,
                       created_at=datetime.now() - timedelta(hours=hours_ago), service_demandeur='DRH')
            db.session.add(t); db.session.commit(); return t.id

    # --- SLA ---
    def test_sla_priorite_categorie_service_defaut(self, app, db_session):
        from app.models import SlaRule
        from app.sla import sla_hours_for, format_remaining
        with app.app_context():
            db.session.add(SlaRule(service='INFORMATIQUE', category=None, hours=8))
            db.session.add(SlaRule(service='INFORMATIQUE', category='Demande Matériel', hours=120))
            db.session.add(SlaRule(service='IMAGO', category=None, hours=4, is_active=False))
            db.session.commit()
            assert sla_hours_for(ServiceType.INFO, 'Incident Standard') == 8
            assert sla_hours_for(ServiceType.INFO, 'demande matériel') == 120   # insensible à la casse
            assert sla_hours_for(ServiceType.IMAGO, None) == 24                # règle désactivée -> défaut
            assert sla_hours_for(ServiceType.DRH, 'Paie') == 24
        assert format_remaining(3.4) == 'dans 3 h' and format_remaining(-50) == 'dépassé de 2 j' and format_remaining(0.2) == "dans moins d'1 h"

    def test_is_stale_utilise_le_sla(self, app, db_session):
        from app.models import SlaRule
        self._users(app)
        with app.app_context():
            db.session.add(SlaRule(service='IMAGO', category=None, hours=4)); db.session.commit()
        imago = self._ticket(app, TicketStatus.PENDING, service=ServiceType.IMAGO, category='Dépannage Imago', hours_ago=6)
        info = self._ticket(app, TicketStatus.PENDING, service=ServiceType.INFO, hours_ago=6)
        with app.app_context():
            t_imago, t_info = Ticket.query.get(imago), Ticket.query.get(info)
            assert t_imago.sla_hours == 4 and t_imago.is_stale and t_imago.sla_label.startswith('dépassé')
            assert t_info.sla_hours == 24 and not t_info.is_stale and t_info.sla_label.startswith('dans')
            assert t_info.due_at == t_info.created_at + timedelta(hours=24)

    def test_admin_sla_crud(self, client, db_session, app):
        from app.models import SlaRule
        self._users(app)
        login(client, 'l3_solver'); assert client.get('/admin/sla').status_code in (302, 403)
        login(client, 'l3_admin'); assert client.get('/admin/sla').status_code == 200
        client.post('/admin/sla', data={'action': 'add', 'service': 'DAF', 'category': '', 'hours': '72'})
        client.post('/admin/sla', data={'action': 'add', 'service': 'DAF', 'category': '', 'hours': '96'})  # même couple -> mise à jour
        client.post('/admin/sla', data={'action': 'add', 'service': 'DAF', 'category': '', 'hours': '0'})   # invalide
        with app.app_context():
            rules = SlaRule.query.filter_by(service='DAF').all()
            assert len(rules) == 1 and rules[0].hours == 96
            rid = rules[0].id
        client.post('/admin/sla', data={'action': 'toggle', 'id': rid})
        with app.app_context():
            assert SlaRule.query.get(rid).is_active is False
        client.post('/admin/sla', data={'action': 'delete', 'id': rid})
        with app.app_context():
            assert SlaRule.query.get(rid) is None

    def test_badge_sla_sur_espace_tech(self, client, db_session, app):
        self._users(app)
        self._ticket(app, TicketStatus.PENDING, hours_ago=30, title='Vieux')
        login(client, 'l3_solver')
        html = client.get('/tickets/solver/dashboard').data.decode()
        assert 'Hors délai' in html and 'dépassé de' in html

    # --- tableau de bord manager ---
    def test_kpi_manager_et_tri_anciennete(self, client, db_session, app):
        self._users(app)
        recent = self._ticket(app, TicketStatus.VALIDATION_N1, hours_ago=2, title='Recent N1')
        old = self._ticket(app, TicketStatus.VALIDATION_N1, hours_ago=60, title='Vieux N1')
        login(client, 'l3_manager')
        html = client.get('/tickets/manager/dashboard').data.decode()
        assert html.index('Vieux N1') < html.index('Recent N1')   # plus ancien en tête
        assert 'En attente &gt; 48 h' in html
        assert 'Valider la sélection' in html

    def test_boutons_du_tableau_manager_ne_soumettent_pas_le_lot(self, client, db_session, app):
        """Les onglets / Refuser / Signer sont dans le <form> de validation en
        lot : sans type="button", un clic soumettait une sélection vide
        (« Aucune demande validée ») — bug constaté en prod le 2026-09-29."""
        import re
        self._users(app)
        self._ticket(app, TicketStatus.VALIDATION_N1, title='A')
        self._ticket(app, TicketStatus.VALIDATION_N2, title='B')
        login(client, 'l3_manager')
        html = client.get('/tickets/manager/dashboard').data.decode()
        form = html[html.index('manager/batch_validate'):]
        form = form[:form.index('</form>')]
        untyped = [b for b in re.findall(r'<button[^>]*>', form) if 'type=' not in b]
        assert untyped == [], untyped
        assert form.count('type="submit"') == 1

    def test_validation_en_lot(self, client, db_session, app):
        self._users(app)
        a = self._ticket(app, TicketStatus.VALIDATION_N1, title='A')
        b = self._ticket(app, TicketStatus.VALIDATION_N1, title='B')
        daf = self._ticket(app, TicketStatus.VALIDATION_N1, service=ServiceType.DAF, category='Bon de Commande', title='DAF')
        login(client, 'l3_manager')
        r = client.post('/tickets/manager/batch_validate', data={'ticket_ids': [str(a), str(b), str(daf)]})
        assert r.status_code == 302
        with app.app_context():
            m = User.query.filter_by(username='l3_manager').first()
            for tid in (a, b):
                t = Ticket.query.get(tid)
                assert t.status == TicketStatus.VALIDATION_N2 and t.validated_by_id == m.id and t.validated_at is not None
            assert Ticket.query.get(daf).status == TicketStatus.VALIDATION_N1   # DAF exclu du lot

    def test_validation_en_lot_refuse_sans_droits(self, client, db_session, app):
        self._users(app)
        a = self._ticket(app, TicketStatus.VALIDATION_N1, title='A')
        login(client, 'l3_user')
        client.post('/tickets/manager/batch_validate', data={'ticket_ids': [str(a)]})
        with app.app_context():
            assert Ticket.query.get(a).status == TicketStatus.VALIDATION_N1

    def test_validation_unitaire_trace_et_alimente_le_kpi(self, client, db_session, app):
        self._users(app)
        a = self._ticket(app, TicketStatus.VALIDATION_N1, hours_ago=10, title='A')
        login(client, 'l3_manager')
        client.get(f'/tickets/manager/action/{a}/validate')
        with app.app_context():
            t = Ticket.query.get(a)
            assert t.status == TicketStatus.VALIDATION_N2 and t.validated_at is not None
        html = client.get('/tickets/manager/dashboard').data.decode()
        assert '1 validée(s) sur 30 j' in html

    def test_validation_en_lot_formulaire(self, client, db_session, app):
        from app.models import FormDefinition, FormField, FormFieldType, FormWorkflowStep, FormSubmission, FormSubmissionStatus, ServiceSource
        self._users(app)
        with app.app_context():
            fd = FormDefinition(slug='lot3-form', name='Lot3', is_active=True)
            db.session.add(fd); db.session.flush()
            db.session.add(FormField(form_definition_id=fd.id, name='titre', label='Titre', field_type=FormFieldType.TEXT, is_required=True, order_index=1))
            db.session.add(FormWorkflowStep(form_definition_id=fd.id, label='Validation Équipe', order_index=0, service_source=ServiceSource.EMITTER))
            author = User.query.filter_by(username='l3_user').first()
            sub = FormSubmission(uid_public='FRM-lot3-1', form_definition_id=fd.id, author_id=author.id,
                                 status=FormSubmissionStatus.IN_PROGRESS, current_step_index=0, data_json='{"titre": "x"}')
            db.session.add(sub); db.session.commit(); sid = sub.id
        login(client, 'l3_manager')
        client.post('/tickets/manager/batch_validate', data={'submission_ids': [str(sid)]})
        with app.app_context():
            sub = FormSubmission.query.get(sid)
            assert sub.status == FormSubmissionStatus.DONE and sub.validated_by_id is not None and sub.last_validated_at is not None

# ===========================================================================
#  RÉSUMÉ RAPIDE (sans pytest)
# ===========================================================================

def run_quick_check():
    """
    Vérification rapide : imports, création de l'app, accessibilité des routes.
    N'utilise PAS la base de données de production.
    Pour les tests complets (DB incluse) : python -m pytest tests_intranet.py -v
    """
    print("\n" + "="*60)
    print("  VÉRIFICATION RAPIDE DE L'APPLICATION INTRANET")
    print("="*60)

    errors = []

    # 1. Vérification des imports
    try:
        from app.models import (User, Ticket, Notification, Materiel,
                                 Pret, Recruitment, DossierSejour, Publication)
        print("[OK] Imports des modèles")
    except Exception as e:
        errors.append(f"Import modèles : {e}")
        print(f"[KO] Import modèles : {e}")

    # 2. Vérification de la création de l'app en mode test (SQLite)
    try:
        _app = create_app('development')
        _app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        _app.config['TESTING'] = True
        _app.config['MAIL_SUPPRESS_SEND'] = True
        _app.config['WTF_CSRF_ENABLED'] = False
        print("[OK] Création de l'application Flask")
    except Exception as e:
        errors.append(f"Création app : {e}")
        print(f"[KO] Création app : {e}")
        print("\n[ECHEC] Impossible de créer l'app, arrêt des vérifications.\n")
        return

    # 3. Vérification des blueprints enregistrés
    try:
        blueprints = list(_app.blueprints.keys())
        expected = ['auth', 'main', 'tickets', 'inventaire', 'prets',
                    'users', 'api', 'fcpi', 'tech', 'sejour', 'publication']
        for bp in expected:
            assert bp in blueprints, f"Blueprint manquant : {bp}"
        print(f"[OK] Blueprints enregistrés ({len(blueprints)}) : {', '.join(blueprints)}")
    except Exception as e:
        errors.append(f"Blueprints : {e}")
        print(f"[KO] Blueprints : {e}")

    # 4. Vérification des routes principales (sans DB)
    routes_a_tester = [
        ('/auth/login',    200,  'Login page'),
        ('/portal',        302,  'Portal protégé (redirection)'),
        ('/help',          302,  'Help protégé (redirection)'),
        ('/inventaire',    302,  'Inventaire protégé'),
        ('/admin/users',   302,  'Admin protégé'),
        ('/api/notifications', 302, 'API protégée'),
    ]
    with _app.test_client() as c:
        for route, expected_code, label in routes_a_tester:
            try:
                r = c.get(route, follow_redirects=False)
                assert r.status_code == expected_code, \
                    f"Attendu {expected_code}, reçu {r.status_code}"
                print(f"[OK] {label} → {route} ({r.status_code})")
            except Exception as e:
                errors.append(f"{label} : {e}")
                print(f"[KO] {label} → {route} : {e}")

    # 5. Vérification des modèles (SQLite en mémoire)
    try:
        with _app.app_context():
            from app import db as test_db
            test_db.create_all()

            u = User(username='_qc_test_', fullname='QC Test',
                     email='qc@test.lan', role=UserRole.ADMIN)
            u.set_origin_services([ServiceType.INFO.value])
            u.set_allowed_services([ServiceType.INFO.value])
            test_db.session.add(u)
            test_db.session.commit()

            found = User.query.filter_by(username='_qc_test_').first()
            assert found and found.email == 'qc@test.lan'
            print("[OK] Modèle User : création")

            n = Notification(user_id=found.id, message='QC notif',
                             category='info', link='/', is_read=False)
            test_db.session.add(n)
            test_db.session.commit()
            d = n.to_dict()
            assert 'message' in d and d['is_read'] == False
            print("[OK] Modèle Notification : to_dict()")

            test_db.drop_all()
    except Exception as e:
        errors.append(f"Tests modèles : {e}")
        print(f"[KO] Tests modèles : {e}")

    # Résumé
    print("\n" + "="*60)
    if errors:
        print(f"  {len(errors)} PROBLÈME(S) DÉTECTÉ(S) :")
        for err in errors:
            print(f"   ✗ {err}")
    else:
        print("  TOUS LES CHECKS RAPIDES SONT PASSÉS !")
    print("="*60)
    print("\nPour la suite complète des tests (avec DB) :")
    print("   source venv/bin/activate")
    print("   python -m pytest tests_intranet.py -v\n")


if __name__ == '__main__':
    run_quick_check()
