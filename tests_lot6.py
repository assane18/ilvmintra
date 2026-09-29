#!/usr/bin/env python3
"""Tests — LOT 6 « Espace Tech au quotidien » (app/routes/tech_extras.py).

Notes internes, pièces jointes du chat, tickets liés / doublons, planning
d'interventions. Réutilise les fixtures de tests_intranet.py (SQLite en
mémoire, login par injection de session). Les fichiers de test sont écrits
dans UPLOAD_FOLDER de la TestConfig (/tmp/intranet_test_uploads) et nettoyés.

    /var/www/intranet/venv/bin/python -m pytest tests_lot6.py -q
"""
import io
import os
import shutil
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tests_intranet import app, client, db_session, make_user, login, make_ticket  # noqa: F401
from app import db
from app.models import User, UserRole, Ticket, TicketStatus, TicketMessage, ServiceType, Notification
from app.routes import tech_extras


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _users(app):
    with app.app_context():
        make_user(username='l6_user', role=UserRole.USER, service=ServiceType.DRH, fullname='Ulysse USER')
        make_user(username='l6_user2', role=UserRole.USER, service=ServiceType.FH, fullname='Ursule USER2')
        make_user(username='l6_solver', role=UserRole.SOLVER, service=ServiceType.INFO,
                  allowed_services=[ServiceType.INFO], fullname='Sam SOLVER')
        make_user(username='l6_solver2', role=UserRole.SOLVER, service=ServiceType.INFO,
                  allowed_services=[ServiceType.INFO], fullname='Théo TECH')
        make_user(username='l6_daf', role=UserRole.SOLVER, service=ServiceType.DAF,
                  allowed_services=[ServiceType.DAF], fullname='Dora DAF')


def _u(username):
    return User.query.filter_by(username=username).first()


def _ticket(app, author='l6_user', service=ServiceType.INFO, status=TicketStatus.PENDING,
            solver=None, rdv=None, title='Sujet'):
    with app.app_context():
        t = Ticket(title=title, description='d', author=_u(author),
                   solver=_u(solver) if solver else None, target_service=service, status=status,
                   uid_public=f'L6-{Ticket.query.count()+1:03d}', category_ticket='Standard',
                   service_demandeur='DRH', created_at=datetime.now() - timedelta(hours=1), rdv_date=rdv)
        db.session.add(t)
        db.session.commit()
        return t.id


def _get(model, id_):
    return db.session.get(model, id_)


def _notifs(username):
    return Notification.query.filter_by(user_id=_u(username).id).all()


def _upload_dir(app, uid):
    return os.path.join(app.config['UPLOAD_FOLDER'], 'tickets', uid)


@pytest.fixture
def mail_spy(monkeypatch):
    """Capture les e-mails de message (kind='message') émis par tech_extras."""
    sent = []
    monkeypatch.setattr(tech_extras, 'send_message_notification',
                        lambda ticket, content, recipient: sent.append((ticket.uid_public, content, recipient.username)))
    closed = []
    monkeypatch.setattr(tech_extras, 'send_closure_notification', lambda ticket: closed.append(ticket.uid_public))
    return {'message': sent, 'closure': closed}


# ---------------------------------------------------------------------------
#  1. Notes internes
# ---------------------------------------------------------------------------

class TestNotesInternes:

    def test_note_interne_invisible_pour_le_demandeur_et_sans_notification(self, client, db_session, app, mail_spy):
        _users(app)
        tid = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver')
        with app.app_context():
            uid = _get(Ticket, tid).uid_public
        login(client, 'l6_solver')
        r = client.post(f'/tickets/view/{uid}', data={'message': 'NOTE_SECRETE_EQUIPE', 'is_internal': '1'},
                        follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            msg = TicketMessage.query.filter_by(ticket_id=tid).first()
            assert msg.is_internal is True
            assert _notifs('l6_user') == []          # le demandeur n'est pas prévenu
        assert mail_spy['message'] == []             # aucun e-mail au demandeur

        # Page du solver : note visible avec badge
        assert b'NOTE_SECRETE_EQUIPE' in r.data
        assert b'Note interne' in r.data

        # Page du demandeur : rien
        login(client, 'l6_user')
        r = client.get(f'/tickets/view/{uid}')
        assert r.status_code == 200
        assert b'NOTE_SECRETE_EQUIPE' not in r.data
        assert b'chat-internal' not in r.data        # pas de case « Note interne » pour l'auteur USER

    def test_note_interne_notifie_le_technicien_en_charge(self, client, db_session, app, mail_spy):
        _users(app)
        tid = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver')
        with app.app_context():
            uid = _get(Ticket, tid).uid_public
        login(client, 'l6_solver2')  # collègue du même service, pas en charge
        client.post(f'/tickets/view/{uid}', data={'message': 'Note pour Sam', 'is_internal': '1'})
        with app.app_context():
            assert len(_notifs('l6_solver')) == 1
            assert _notifs('l6_user') == []
        assert [s[2] for s in mail_spy['message']] == ['l6_solver']

    def test_demandeur_ne_peut_pas_creer_de_note_interne(self, client, db_session, app, mail_spy):
        _users(app)
        tid = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver')
        with app.app_context():
            uid = _get(Ticket, tid).uid_public
        login(client, 'l6_user')
        client.post(f'/tickets/view/{uid}', data={'message': 'Je tente', 'is_internal': '1'})
        with app.app_context():
            msg = TicketMessage.query.filter_by(ticket_id=tid).first()
            assert msg.is_internal is False       # case ignorée
            assert len(_notifs('l6_solver')) == 1  # flux normal auteur -> technicien

    def test_message_normal_notifie_le_demandeur(self, client, db_session, app, mail_spy):
        _users(app)
        tid = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver')
        with app.app_context():
            uid = _get(Ticket, tid).uid_public
        login(client, 'l6_solver')
        client.post(f'/tickets/view/{uid}', data={'message': 'Réponse publique'})
        with app.app_context():
            assert len(_notifs('l6_user')) == 1
        assert [s[2] for s in mail_spy['message']] == ['l6_user']


# ---------------------------------------------------------------------------
#  2. Pièces jointes du chat
# ---------------------------------------------------------------------------

class TestPiecesJointesChat:

    def test_piece_jointe_enregistree_et_listee(self, client, db_session, app, mail_spy):
        _users(app)
        tid = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver')
        with app.app_context():
            uid = _get(Ticket, tid).uid_public
        folder = _upload_dir(app, uid)
        try:
            login(client, 'l6_user')  # le demandeur peut joindre
            data = {'message': 'Voici la capture',
                    'attachments': [(io.BytesIO(b'\x89PNG fake'), 'capture ecran.png'),
                                    (io.BytesIO(b'%PDF-1.4 fake'), 'devis.pdf')]}
            r = client.post(f'/tickets/view/{uid}', data=data, content_type='multipart/form-data',
                            follow_redirects=True)
            assert r.status_code == 200
            with app.app_context():
                msg = TicketMessage.query.filter_by(ticket_id=tid).first()
                names = msg.get_attachments()
                assert names == [f'msg_{msg.id}_capture_ecran.png', f'msg_{msg.id}_devis.pdf']
                for n in names:
                    assert os.path.isfile(os.path.join(folder, n))
            assert b'capture_ecran.png' in r.data
            assert b'devis.pdf' in r.data
            assert f'uploads/tickets/{uid}/msg_'.encode() in r.data
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_extension_interdite_refusee(self, client, db_session, app, mail_spy):
        _users(app)
        tid = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver')
        with app.app_context():
            uid = _get(Ticket, tid).uid_public
        folder = _upload_dir(app, uid)
        try:
            login(client, 'l6_solver')
            data = {'message': 'Un script', 'attachments': (io.BytesIO(b'MZ'), 'virus.exe')}
            r = client.post(f'/tickets/view/{uid}', data=data, content_type='multipart/form-data',
                            follow_redirects=True)
            assert r.status_code == 200
            assert 'refusé'.encode() in r.data
            with app.app_context():
                assert TicketMessage.query.filter_by(ticket_id=tid).count() == 0
            assert not os.path.exists(folder)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_piece_jointe_de_note_interne_invisible_du_demandeur(self, client, db_session, app, mail_spy):
        _users(app)
        tid = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver')
        with app.app_context():
            uid = _get(Ticket, tid).uid_public
        folder = _upload_dir(app, uid)
        try:
            login(client, 'l6_solver')
            data = {'message': 'Analyse interne', 'is_internal': '1',
                    'attachments': (io.BytesIO(b'xlsx'), 'analyse_secrete.xlsx')}
            client.post(f'/tickets/view/{uid}', data=data, content_type='multipart/form-data')
            login(client, 'l6_user')
            r = client.get(f'/tickets/view/{uid}')
            assert b'analyse_secrete' not in r.data
        finally:
            shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------------------
#  3. Tickets liés / doublons
# ---------------------------------------------------------------------------

class TestDoublons:

    def _pair(self, app, master_status=TicketStatus.IN_PROGRESS, master_service=ServiceType.INFO):
        master = _ticket(app, author='l6_user', status=master_status, solver='l6_solver',
                         service=master_service, title='Imprimante HS')
        dup = _ticket(app, author='l6_user2', status=TicketStatus.PENDING, title='Imprimante en panne')
        return master, dup

    def test_liaison_ok(self, client, db_session, app, mail_spy):
        _users(app)
        master, dup = self._pair(app)
        with app.app_context():
            m_uid, d_uid = _get(Ticket, master).uid_public, _get(Ticket, dup).uid_public
        login(client, 'l6_solver')
        r = client.post(f'/tickets/link/{dup}', data={'master_uid': f'#{m_uid}'}, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            d, m = _get(Ticket, dup), _get(Ticket, master)
            assert d.parent_id == master and d.is_duplicate
            assert d.status == TicketStatus.IN_PROGRESS
            assert d.solver.username == 'l6_solver'
            assert [x.id for x in m.duplicates] == [dup]
            texts = [x.content for x in d.messages]
            assert any(f'rattaché au ticket maître #{m_uid}' in c for c in texts)
            # Trace côté maître en note interne
            assert any(x.is_internal and d_uid in x.content for x in m.messages)
            notes = _notifs('l6_user2')
            assert len(notes) == 1 and m_uid in notes[0].message
        # La page du maître liste le doublon et son demandeur
        r = client.get(f'/tickets/view/{m_uid}')
        assert d_uid.encode() in r.data and b'Ursule USER2' in r.data
        assert b'chat-broadcast' in r.data

    @pytest.mark.parametrize('case', ['autre_service', 'maitre_termine', 'lui_meme', 'maitre_doublon'])
    def test_refus_de_liaison(self, client, db_session, app, mail_spy, case):
        _users(app)
        if case == 'autre_service':
            master, dup = self._pair(app, master_service=ServiceType.DAF)
        elif case == 'maitre_termine':
            master, dup = self._pair(app, master_status=TicketStatus.DONE)
        else:
            master, dup = self._pair(app)
        with app.app_context():
            m_uid = _get(Ticket, master).uid_public
            if case == 'maitre_doublon':
                # Le « maître » visé est lui-même rattaché à un troisième ticket
                third = _ticket(app, author='l6_user', status=TicketStatus.IN_PROGRESS, solver='l6_solver')
                _get(Ticket, master).parent_id = third
                db.session.commit()
        login(client, 'l6_solver')
        target = f'#{_get(Ticket, dup).uid_public}' if case == 'lui_meme' else m_uid
        r = client.post(f'/tickets/link/{dup}', data={'master_uid': target}, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            d = _get(Ticket, dup)
            assert d.parent_id is None
            assert d.status == TicketStatus.PENDING
            assert d.messages == []
            assert _notifs('l6_user2') == []

    def test_liaison_refusee_au_demandeur(self, client, db_session, app, mail_spy):
        _users(app)
        master, dup = self._pair(app)
        with app.app_context():
            m_uid = _get(Ticket, master).uid_public
        login(client, 'l6_user2')  # auteur du doublon : pas l'équipe
        client.post(f'/tickets/link/{dup}', data={'master_uid': m_uid}, follow_redirects=True)
        with app.app_context():
            assert _get(Ticket, dup).parent_id is None

    def test_cloture_en_cascade(self, client, db_session, app, mail_spy):
        _users(app)
        master, dup = self._pair(app)
        with app.app_context():
            m_uid = _get(Ticket, master).uid_public
        login(client, 'l6_solver')
        client.post(f'/tickets/link/{dup}', data={'master_uid': m_uid})
        with app.app_context():
            Notification.query.delete(); db.session.commit()
        r = client.post(f'/tickets/solver/close/{master}', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            m, d = _get(Ticket, master), _get(Ticket, dup)
            assert m.status == TicketStatus.DONE and d.status == TicketStatus.DONE
            assert d.closed_at == m.closed_at
            assert any('Clôturé automatiquement' in x.content for x in d.messages)
            assert len(_notifs('l6_user2')) == 1 and 'clôturé' in _notifs('l6_user2')[0].message
            assert len(_notifs('l6_user')) == 1
            d_uid = d.uid_public
        assert mail_spy['closure'] == [d_uid]  # e-mail de clôture au demandeur du doublon (le maître passe par tickets.py)

    def test_detachement(self, client, db_session, app, mail_spy):
        _users(app)
        master, dup = self._pair(app)
        with app.app_context():
            m_uid = _get(Ticket, master).uid_public
        login(client, 'l6_solver')
        client.post(f'/tickets/link/{dup}', data={'master_uid': m_uid})
        r = client.post(f'/tickets/unlink/{dup}', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            d = _get(Ticket, dup)
            assert d.parent_id is None
            assert any('détaché' in x.content for x in d.messages)
            assert _get(Ticket, master).duplicates == []

    def test_diffusion_aux_doublons(self, client, db_session, app, mail_spy):
        _users(app)
        master, dup = self._pair(app)
        with app.app_context():
            m_uid = _get(Ticket, master).uid_public
        login(client, 'l6_solver')
        client.post(f'/tickets/link/{dup}', data={'master_uid': m_uid})
        with app.app_context():
            Notification.query.delete(); db.session.commit()
        client.post(f'/tickets/view/{m_uid}', data={'message': 'Pièce commandée, retour jeudi', 'broadcast': '1'})
        with app.app_context():
            d = _get(Ticket, dup)
            assert any('Pièce commandée' in x.content and not x.is_internal for x in d.messages)
            assert len(_notifs('l6_user2')) == 1 and len(_notifs('l6_user')) == 1
        assert sorted(s[2] for s in mail_spy['message']) == ['l6_user', 'l6_user2']

    def test_note_interne_jamais_diffusee(self, client, db_session, app, mail_spy):
        _users(app)
        master, dup = self._pair(app)
        with app.app_context():
            m_uid = _get(Ticket, master).uid_public
        login(client, 'l6_solver')
        client.post(f'/tickets/link/{dup}', data={'master_uid': m_uid})
        client.post(f'/tickets/view/{m_uid}', data={'message': 'INTERNE', 'is_internal': '1', 'broadcast': '1'})
        with app.app_context():
            assert not any('INTERNE' in x.content for x in _get(Ticket, dup).messages)


# ---------------------------------------------------------------------------
#  4. Planning d'interventions
# ---------------------------------------------------------------------------

class TestPlanning:

    def test_acces_refuse_user(self, client, db_session, app):
        _users(app)
        login(client, 'l6_user')
        assert client.get('/tickets/planning').status_code == 403

    def test_tickets_de_la_semaine_et_navigation(self, client, db_session, app):
        _users(app)
        monday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        monday -= timedelta(days=monday.weekday())
        this_week = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver',
                            rdv=monday + timedelta(days=2, hours=10), title='Semaine courante')
        next_week = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver',
                            rdv=monday + timedelta(days=8, hours=14), title='Semaine suivante')
        hors_perimetre = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_daf', service=ServiceType.DAF,
                                 rdv=monday + timedelta(days=2, hours=11), title='Commande DAF')
        with app.app_context():
            uids = {k: _get(Ticket, v).uid_public for k, v in
                    dict(this_week=this_week, next_week=next_week, daf=hors_perimetre).items()}
        login(client, 'l6_solver')
        r = client.get('/tickets/planning')
        assert r.status_code == 200
        assert uids['this_week'].encode() in r.data
        assert uids['next_week'].encode() not in r.data
        assert uids['daf'].encode() not in r.data       # hors périmètre (service DAF)
        assert b'planning-grid' in r.data and r.data.count(b'data-day=') == 7

        r = client.get('/tickets/planning?week=' + (monday + timedelta(days=7)).strftime('%Y-%m-%d'))
        assert uids['next_week'].encode() in r.data
        assert uids['this_week'].encode() not in r.data

        # Le solver DAF voit son ticket, pas ceux de l'informatique
        login(client, 'l6_daf')
        r = client.get('/tickets/planning')
        assert uids['daf'].encode() in r.data and uids['this_week'].encode() not in r.data

    def test_lien_planning_sur_espace_tech(self, client, db_session, app):
        _users(app)
        login(client, 'l6_solver')
        r = client.get('/tickets/solver/dashboard')
        assert r.status_code == 200
        assert b'/tickets/planning' in r.data

    def test_rdv_modifiable_par_le_solver_assigne_seulement(self, client, db_session, app, mail_spy):
        _users(app)
        tid = _ticket(app, status=TicketStatus.IN_PROGRESS, solver='l6_solver')
        with app.app_context():
            uid = _get(Ticket, tid).uid_public

        # Collègue non assigné : refus
        login(client, 'l6_solver2')
        client.post(f'/tickets/rdv/{tid}', data={'rdv_date': '2026-10-05T09:30'})
        with app.app_context():
            assert _get(Ticket, tid).rdv_date is None
            assert _notifs('l6_user') == []

        # Technicien en charge : OK + notification « Intervention planifiée le … »
        login(client, 'l6_solver')
        r = client.get(f'/tickets/view/{uid}')
        assert b'planning-rdv' in r.data
        r = client.post(f'/tickets/rdv/{tid}', data={'rdv_date': '2026-10-05T09:30'}, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            t = _get(Ticket, tid)
            assert t.rdv_date == datetime(2026, 10, 5, 9, 30)
            assert any('Intervention planifiée le 05/10/2026 à 09:30' in x.content for x in t.messages)
            notes = _notifs('l6_user')
            assert len(notes) == 1 and 'Intervention planifiée le 05/10/2026' in notes[0].message
        assert [s[2] for s in mail_spy['message']] == ['l6_user']

        # Modification (replanification) puis déprogrammation
        client.post(f'/tickets/rdv/{tid}', data={'rdv_date': '2026-10-06T14:00'})
        with app.app_context():
            t = _get(Ticket, tid)
            assert t.rdv_date == datetime(2026, 10, 6, 14, 0)
            assert any('replanifiée' in x.content for x in t.messages)
        client.post(f'/tickets/rdv/{tid}', data={'clear': '1'})
        with app.app_context():
            assert _get(Ticket, tid).rdv_date is None

    def test_rdv_sur_ticket_non_assigne_refuse(self, client, db_session, app, mail_spy):
        _users(app)
        tid = _ticket(app, status=TicketStatus.PENDING)
        login(client, 'l6_solver')
        client.post(f'/tickets/rdv/{tid}', data={'rdv_date': '2026-10-05T09:30'})
        with app.app_context():
            assert _get(Ticket, tid).rdv_date is None
