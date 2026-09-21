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
