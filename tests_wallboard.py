#!/usr/bin/env python3
"""Tests de l'écran mural de l'Espace Tech (app/routes/wallboard.py).

Réutilise les fixtures et helpers de tests_intranet.py (SQLite en mémoire,
login par injection de session, garde-fou sur l'URI). Lancer :

    /var/www/intranet/venv/bin/python -m pytest tests_wallboard.py -q
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fixtures `app`, `client`, `db_session` importées pour être vues par pytest.
from tests_intranet import app, client, db_session, make_user, login, make_ticket  # noqa: F401
from app import db
from app.models import User, UserRole, Ticket, TicketStatus, ServiceType


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _users(app):
    with app.app_context():
        make_user(username='wb_user', role=UserRole.USER, service=ServiceType.DRH, fullname='Ulysse USER')
        make_user(username='wb_solver', role=UserRole.SOLVER, service=ServiceType.INFO,
                  allowed_services=[ServiceType.INFO], fullname='Sam SOLVER')
        make_user(username='wb_solver2', role=UserRole.SOLVER, service=ServiceType.INFO,
                  allowed_services=[ServiceType.INFO], fullname='Théo TECH')
        make_user(username='wb_daf', role=UserRole.SOLVER, service=ServiceType.DAF,
                  allowed_services=[ServiceType.DAF], fullname='Dora DAF')
        make_user(username='wb_manager', role=UserRole.MANAGER, service=ServiceType.DRH,
                  allowed_services=[ServiceType.INFO], fullname='Manu MANAGER')
        make_user(username='wb_admin', role=UserRole.ADMIN, service=ServiceType.INFO,
                  allowed_services=[ServiceType.INFO], fullname='Alice ADMIN')


def _ticket(app, status, service=ServiceType.INFO, author='wb_user', solver=None,
            title='Sujet', hours_ago=1, closed_at=None, assigned_at=None):
    with app.app_context():
        a = User.query.filter_by(username=author).first()
        s = User.query.filter_by(username=solver).first() if solver else None
        t = Ticket(title=title, description='d', author=a, solver=s, target_service=service,
                   status=status, uid_public=f'WB-{Ticket.query.count()+1:03d}',
                   category_ticket='Standard', service_demandeur='DRH',
                   created_at=datetime.now() - timedelta(hours=hours_ago),
                   closed_at=closed_at, assigned_at=assigned_at)
        db.session.add(t)
        db.session.commit()
        return t.uid_public


# ---------------------------------------------------------------------------
#  Accès
# ---------------------------------------------------------------------------

class TestWallboardAcces:

    def test_anonyme_redirige_vers_login(self, client, db_session):
        r = client.get('/tickets/wallboard')
        assert r.status_code in (302, 401)

    def test_user_simple_refuse(self, client, db_session, app):
        _users(app)
        login(client, 'wb_user')
        assert client.get('/tickets/wallboard').status_code == 403
        r = client.get('/tickets/wallboard/data')
        assert r.status_code == 403
        assert r.get_json()['error'] == 'forbidden'

    @pytest.mark.parametrize('username', ['wb_solver', 'wb_manager', 'wb_admin'])
    def test_roles_tech_acceptes(self, client, db_session, app, username):
        _users(app)
        login(client, username)
        r = client.get('/tickets/wallboard')
        assert r.status_code == 200
        html = r.data.decode()
        assert 'Écran mural' in html
        assert '/tickets/wallboard/data' in html          # URL interrogée par la page
        assert 'requestFullscreen' in html                # bouton plein écran (API Fullscreen)
        assert 'extends' not in html and '<html' in html  # page autonome, pas base.html
        assert client.get('/tickets/wallboard/data').status_code == 200

    def test_service_hors_perimetre_refuse(self, client, db_session, app):
        _users(app)
        login(client, 'wb_solver')  # périmètre INFO uniquement
        assert client.get('/tickets/wallboard?service=DAF').status_code == 403
        assert client.get('/tickets/wallboard/data?service=DAF').status_code == 403
        assert client.get('/tickets/wallboard/data?service=INEXISTANT').status_code == 403
        # Dans son périmètre, par valeur comme par nom d'enum
        assert client.get('/tickets/wallboard?service=INFORMATIQUE').status_code == 200
        assert client.get('/tickets/wallboard/data?service=INFO').get_json()['service'] == 'INFORMATIQUE'

    def test_bouton_ecran_mural_dans_dashboard_tech(self, client, db_session, app):
        _users(app)
        login(client, 'wb_solver')
        html = client.get('/tickets/solver/dashboard').data.decode()
        assert '/tickets/wallboard' in html and 'Écran mural' in html

    def test_reponse_non_cachee(self, client, db_session, app):
        _users(app)
        login(client, 'wb_solver')
        r = client.get('/tickets/wallboard/data')
        assert 'no-store' in r.headers.get('Cache-Control', '')


# ---------------------------------------------------------------------------
#  Contenu JSON
# ---------------------------------------------------------------------------

class TestWallboardData:

    def test_compteurs_et_colonnes(self, client, db_session, app):
        _users(app)
        now = datetime.now()
        # 2 en attente (dont 1 en retard, la plus ancienne), 2 en cours (1 par
        # technicien, dont 1 en retard), 1 clôturé aujourd'hui, 1 clôturé hier,
        # 1 en validation manager (ignoré partout).
        _ticket(app, TicketStatus.PENDING, title='Récent', hours_ago=2)
        old_uid = _ticket(app, TicketStatus.PENDING, title='Vieux', hours_ago=30)
        _ticket(app, TicketStatus.IN_PROGRESS, solver='wb_solver', title='Sam bosse', hours_ago=3,
                assigned_at=now - timedelta(hours=2))
        _ticket(app, TicketStatus.IN_PROGRESS, solver='wb_solver2', title='Théo traîne', hours_ago=50,
                assigned_at=now - timedelta(hours=49))
        _ticket(app, TicketStatus.DONE, solver='wb_solver', title='Fini ce matin', hours_ago=5,
                closed_at=now - timedelta(minutes=10), assigned_at=now - timedelta(hours=4))
        _ticket(app, TicketStatus.DONE, solver='wb_solver', title='Fini hier', hours_ago=40,
                closed_at=now - timedelta(days=1, hours=2))
        _ticket(app, TicketStatus.VALIDATION_N1, title='En validation', hours_ago=100)

        login(client, 'wb_solver')
        d = client.get('/tickets/wallboard/data').get_json()

        assert d['counters'] == {'pending': 2, 'in_progress': 2, 'late': 2, 'closed_today': 1}
        assert d['service'] is None
        assert d['generated_at']

        # Colonne « À prendre en charge » : plus ancien en premier, badge retard
        assert [t['title'] for t in d['pending']] == ['Vieux', 'Récent']
        vieux = d['pending'][0]
        assert vieux['uid'] == old_uid and vieux['late'] is True
        assert vieux['service'] == 'INFORMATIQUE'
        assert vieux['requester'] == 'Ulysse USER'
        assert vieux['status_label'] == 'À prendre en charge'
        assert vieux['age_label'] == '30 h'  # < 48 h : affiché en heures
        assert d['pending'][1]['late'] is False and d['pending'][1]['age_label'] == '2 h'

        # Colonne « En cours » groupée par technicien
        groups = {g['solver']: g for g in d['in_progress_by_solver']}
        assert set(groups) == {'Sam SOLVER', 'Théo TECH'}
        assert groups['Sam SOLVER']['count'] == 1 and groups['Sam SOLVER']['late'] == 0
        assert groups['Théo TECH']['count'] == 1 and groups['Théo TECH']['late'] == 1
        assert groups['Théo TECH']['tickets'][0]['title'] == 'Théo traîne'

        # Dernières activités : la clôture de ce matin puis la prise en charge la plus récente
        assert len(d['recent']) == 5
        assert d['recent'][0]['kind'] == 'closed' and d['recent'][0]['ticket']['title'] == 'Fini ce matin'
        assert d['recent'][1]['kind'] == 'taken' and d['recent'][1]['ticket']['title'] == 'Sam bosse'
        assert [e['at'] for e in d['recent']] == sorted((e['at'] for e in d['recent']), reverse=True)

    def test_recent_limite_a_cinq(self, client, db_session, app):
        _users(app)
        now = datetime.now()
        for i in range(8):
            _ticket(app, TicketStatus.DONE, solver='wb_solver', title=f'Clos {i}',
                    closed_at=now - timedelta(minutes=i), assigned_at=now - timedelta(hours=1, minutes=i))
        login(client, 'wb_solver')
        d = client.get('/tickets/wallboard/data').get_json()
        assert len(d['recent']) == 5
        assert d['recent'][0]['ticket']['title'] == 'Clos 0'

    def test_isolation_par_service_autorise(self, client, db_session, app):
        _users(app)
        _ticket(app, TicketStatus.PENDING, service=ServiceType.INFO, title='Info 1')
        _ticket(app, TicketStatus.PENDING, service=ServiceType.INFO, title='Info 2', hours_ago=30)
        _ticket(app, TicketStatus.PENDING, service=ServiceType.DAF, title='Daf 1')
        _ticket(app, TicketStatus.IN_PROGRESS, service=ServiceType.DAF, solver='wb_daf', title='Daf 2')

        # Solver INFO : ne voit que l'informatique
        login(client, 'wb_solver')
        d = client.get('/tickets/wallboard/data').get_json()
        assert d['counters'] == {'pending': 2, 'in_progress': 0, 'late': 1, 'closed_today': 0}
        assert {t['service'] for t in d['pending']} == {'INFORMATIQUE'}

        # Solver DAF : ne voit que la DAF
        login(client, 'wb_daf')
        d = client.get('/tickets/wallboard/data').get_json()
        assert d['counters'] == {'pending': 1, 'in_progress': 1, 'late': 0, 'closed_today': 0}
        assert d['in_progress_by_solver'][0]['solver'] == 'Dora DAF'

        # ADMIN : tout, et peut restreindre avec ?service=
        login(client, 'wb_admin')
        d = client.get('/tickets/wallboard/data').get_json()
        assert d['counters']['pending'] == 3 and d['counters']['in_progress'] == 1
        d = client.get('/tickets/wallboard/data?service=DAF').get_json()
        assert d['service'] == 'DAF'
        assert d['counters'] == {'pending': 1, 'in_progress': 1, 'late': 0, 'closed_today': 0}

    def test_perimetre_vide_ne_montre_rien(self, client, db_session, app):
        with app.app_context():
            u = make_user(username='wb_vide', role=UserRole.SOLVER, service=ServiceType.INFO)
            u.set_allowed_services([])
            db.session.commit()
            make_user(username='wb_auteur', role=UserRole.USER, service=ServiceType.DRH)
        _ticket(app, TicketStatus.PENDING, author='wb_auteur')
        login(client, 'wb_vide')
        d = client.get('/tickets/wallboard/data').get_json()
        assert d['counters'] == {'pending': 0, 'in_progress': 0, 'late': 0, 'closed_today': 0}
        assert d['pending'] == [] and d['in_progress_by_solver'] == [] and d['recent'] == []

    def test_en_cours_non_affecte(self, client, db_session, app):
        _users(app)
        _ticket(app, TicketStatus.IN_PROGRESS, title='Orphelin')  # EN_COURS sans technicien
        login(client, 'wb_solver')
        d = client.get('/tickets/wallboard/data').get_json()
        assert d['counters']['in_progress'] == 1
        assert d['in_progress_by_solver'][0]['solver'] == 'Non affecté'


# ---------------------------------------------------------------------------
#  Règle « en retard » isolée (à brancher sur le SLA plus tard)
# ---------------------------------------------------------------------------

class TestRegleRetard:

    def test_is_late_suit_le_statut_et_le_seuil(self, app, db_session):
        from app.routes.wallboard import is_late, LATE_THRESHOLD_HOURS
        with app.app_context():
            a = make_user(username='wb_r', role=UserRole.USER)
            old = datetime.now() - timedelta(hours=LATE_THRESHOLD_HOURS + 1)
            recent = datetime.now() - timedelta(hours=1)
            assert is_late(Ticket(title='x', description='d', author=a, target_service=ServiceType.INFO,
                                  status=TicketStatus.PENDING, created_at=old))
            assert is_late(Ticket(title='x', description='d', author=a, target_service=ServiceType.INFO,
                                  status=TicketStatus.IN_PROGRESS, created_at=old))
            assert not is_late(Ticket(title='x', description='d', author=a, target_service=ServiceType.INFO,
                                      status=TicketStatus.PENDING, created_at=recent))
            # En validation manager ou clôturé : jamais « en retard » côté technicien
            assert not is_late(Ticket(title='x', description='d', author=a, target_service=ServiceType.INFO,
                                      status=TicketStatus.VALIDATION_N1, created_at=old))
            assert not is_late(Ticket(title='x', description='d', author=a, target_service=ServiceType.INFO,
                                      status=TicketStatus.DONE, created_at=old))
