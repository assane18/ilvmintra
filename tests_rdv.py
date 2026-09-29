"""Rendez-vous sur ticket : proposition par l'équipe, réponse du demandeur
(accepter / refuser / disponibilités), annulation, planning, rappel à 9h.
E-mails capturés par monkeypatch (aucune tentative SMTP)."""
import os
import sys
import json
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['FLASK_ENV'] = 'testing'
os.environ['FLASK_DEBUG'] = '0'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from tests_intranet import app, client, db_session, make_user, login, TestConfig  # noqa: E402,F401
from app import db  # noqa: E402
from app.models import User, UserRole, Ticket, TicketStatus, TicketMessage, ServiceType, Notification, Appointment  # noqa: E402
import app.routes.rdv as rdv  # noqa: E402


@pytest.fixture
def mail_spy(monkeypatch):
    sent = []
    monkeypatch.setattr(rdv, 'send_rdv_email',
                        lambda recipient, subject, intro, ticket, buttons=None, kind='important', recipients_emails=None:
                        sent.append({'to': recipient.username if recipient else recipients_emails, 'subject': subject,
                                     'buttons': buttons, 'kind': kind}))
    return sent


def _users(app):
    with app.app_context():
        make_user(username='rdv_user', role=UserRole.USER, service=ServiceType.FJ, fullname='Ulysse USER')
        make_user(username='rdv_drh', role=UserRole.SOLVER, service=ServiceType.DRH, allowed_services=[ServiceType.DRH], fullname='Rachel RH')
        make_user(username='rdv_drh2', role=UserRole.MANAGER, service=ServiceType.DRH, allowed_services=[ServiceType.DRH], fullname='Marc RH')
        make_user(username='rdv_info', role=UserRole.SOLVER, service=ServiceType.INFO, allowed_services=[ServiceType.INFO])
        make_user(username='rdv_autre', role=UserRole.USER, service=ServiceType.SG)


def _ticket(app, service=ServiceType.DRH, solver=None, status=TicketStatus.PENDING):
    with app.app_context():
        a = User.query.filter_by(username='rdv_user').first()
        s = User.query.filter_by(username=solver).first() if solver else None
        t = Ticket(title='Entretien RH', description='d', author=a, solver=s, target_service=service, status=status,
                   uid_public=f'RDV-{Ticket.query.count()+1:03d}', category_ticket='Paie', created_at=datetime.now(),
                   service_demandeur='FJ')
        db.session.add(t); db.session.commit(); return t.id


def _notifs(username):
    u = User.query.filter_by(username=username).first()
    return [n.message for n in Notification.query.filter_by(user_id=u.id).all()]


def _future(days=2, hour=10):
    d = datetime.now() + timedelta(days=days)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0)


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M')


class TestProposition:

    def test_equipe_du_service_propose_meme_sans_prise_en_charge(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        when = _future()
        login(client, 'rdv_drh')
        r = client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(when), 'message': 'Bureau 12'})
        assert r.status_code == 302
        with app.app_context():
            a = Appointment.query.filter_by(ticket_id=tid).one()
            assert a.status == 'proposed' and a.starts_at == when and a.message == 'Bureau 12' and a.proposed_by.username == 'rdv_drh'
            assert Ticket.query.get(tid).rdv_date is None                       # pas encore confirmé
            assert any('Rendez-vous proposé' in m for m in _notifs('rdv_user'))
            assert 'proposé' in TicketMessage.query.filter_by(ticket_id=tid).first().content
        assert mail_spy[-1]['to'] == 'rdv_user' and len(mail_spy[-1]['buttons']) == 3

    def test_autre_service_ou_demandeur_ne_peut_pas_proposer(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        for who in ('rdv_info', 'rdv_user', 'rdv_autre'):
            login(client, who)
            client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(_future())})
        with app.app_context():
            assert Appointment.query.count() == 0

    def test_fixer_directement(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        when = _future()
        login(client, 'rdv_drh')
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(when), 'direct': '1'})
        with app.app_context():
            a = Appointment.query.filter_by(ticket_id=tid).one()
            assert a.status == 'accepted' and a.direct and Ticket.query.get(tid).rdv_date == when
            assert any('Rendez-vous fixé' in m for m in _notifs('rdv_user'))
        assert mail_spy[-1]['buttons'] is None

    def test_date_passee_ou_ticket_clos_refuses(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app); closed = _ticket(app, status=TicketStatus.DONE)
        login(client, 'rdv_drh')
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(datetime.now() - timedelta(days=1))})
        client.post(f'/tickets/rdv/{closed}/propose', data={'starts_at': _iso(_future())})
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': 'n/a'})
        with app.app_context():
            assert Appointment.query.count() == 0

    def test_nouvelle_proposition_remplace_la_precedente(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        login(client, 'rdv_drh')
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(_future(2))})
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(_future(3))})
        with app.app_context():
            statuses = [a.status for a in Appointment.query.filter_by(ticket_id=tid).order_by(Appointment.id).all()]
            assert statuses == ['cancelled', 'proposed']
            assert rdv.current_appointment(Ticket.query.get(tid)).starts_at == _future(3)


class TestReponseDemandeur:

    def _propose(self, client, app, tid, when=None):
        login(client, 'rdv_drh')
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(when or _future())})

    def test_accepter(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app, solver='rdv_drh2'); when = _future()
        self._propose(client, app, tid, when)
        login(client, 'rdv_user')
        r = client.post(f'/tickets/rdv/{tid}/respond', data={'action': 'accept'})
        assert r.status_code == 302
        with app.app_context():
            a = Appointment.query.filter_by(ticket_id=tid).one()
            assert a.status == 'accepted' and a.responded_at is not None
            assert Ticket.query.get(tid).rdv_date == when
            # l'équipe (proposeur + technicien en charge) est prévenue
            assert any('accepté' in m for m in _notifs('rdv_drh')) and any('accepté' in m for m in _notifs('rdv_drh2'))
        assert {m['to'] for m in mail_spy if 'confirmé' in m['subject']} == {'rdv_drh', 'rdv_drh2'}

    def test_refuser_avec_motif(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        self._propose(client, app, tid)
        login(client, 'rdv_user')
        client.post(f'/tickets/rdv/{tid}/respond', data={'action': 'refuse', 'comment': 'En congés'})
        with app.app_context():
            a = Appointment.query.filter_by(ticket_id=tid).one()
            assert a.status == 'refused' and a.response_comment == 'En congés' and Ticket.query.get(tid).rdv_date is None
            assert rdv.current_appointment(Ticket.query.get(tid)) is None       # l'équipe peut reproposer
            assert any('refusé' in m for m in _notifs('rdv_drh'))

    def test_proposer_disponibilites_puis_retenue_par_l_equipe(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        self._propose(client, app, tid)
        s1, s2 = _future(4, 9), _future(5, 14)
        login(client, 'rdv_user')
        client.post(f'/tickets/rdv/{tid}/respond', data={'action': 'counter', 'slot1': _iso(s1), 'slot2': _iso(s2), 'comment': 'Plutôt le matin'})
        with app.app_context():
            a = Appointment.query.filter_by(ticket_id=tid).one()
            assert a.status == 'counter' and a.get_slots() == [s1, s2] and a.response_comment == 'Plutôt le matin'
            assert any('Disponibilités' in m for m in _notifs('rdv_drh'))
            aid = a.id
        # L'équipe retient le 2e créneau d'un clic
        login(client, 'rdv_drh2')
        client.post(f'/tickets/rdv/{tid}/pick/{aid}/1')
        with app.app_context():
            t = Ticket.query.get(tid)
            assert t.rdv_date == s2
            assert [x.status for x in Appointment.query.filter_by(ticket_id=tid).order_by(Appointment.id).all()] == ['cancelled', 'accepted']
            assert any('Rendez-vous fixé' in m for m in _notifs('rdv_user'))

    def test_disponibilites_sans_creneau_refusees(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        self._propose(client, app, tid)
        login(client, 'rdv_user')
        client.post(f'/tickets/rdv/{tid}/respond', data={'action': 'counter', 'comment': 'x'})
        with app.app_context():
            assert Appointment.query.filter_by(ticket_id=tid).one().status == 'proposed'

    def test_seul_le_demandeur_repond(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        self._propose(client, app, tid)
        login(client, 'rdv_autre')
        client.post(f'/tickets/rdv/{tid}/respond', data={'action': 'accept'})
        login(client, 'rdv_drh')
        client.post(f'/tickets/rdv/{tid}/respond', data={'action': 'accept'})
        with app.app_context():
            assert Appointment.query.filter_by(ticket_id=tid).one().status == 'proposed'

    def test_lien_email_accepter_en_un_clic(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app); when = _future()
        self._propose(client, app, tid, when)
        login(client, 'rdv_user')
        r = client.get(f'/tickets/rdv/{tid}/respond/accept')
        assert r.status_code == 302 and r.headers['Location'].endswith('#rdv')
        with app.app_context():
            assert Ticket.query.get(tid).rdv_date == when
        # un second clic n'a plus d'effet
        r = client.get(f'/tickets/rdv/{tid}/respond/accept')
        assert r.status_code == 302


class TestAnnulationEtAffichage:

    def test_equipe_annule_et_repropose(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app); when = _future()
        login(client, 'rdv_drh')
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(when), 'direct': '1'})
        client.post(f'/tickets/rdv/{tid}/cancel', data={'reason': 'Imprévu'})
        with app.app_context():
            t = Ticket.query.get(tid)
            assert t.rdv_date is None and Appointment.query.filter_by(ticket_id=tid).one().status == 'cancelled'
            assert any('annulé' in m for m in _notifs('rdv_user'))
            assert 'Imprévu' in TicketMessage.query.filter_by(ticket_id=tid).order_by(TicketMessage.id.desc()).first().content
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(_future(6))})
        with app.app_context():
            assert rdv.current_appointment(Ticket.query.get(tid)).status == 'proposed'

    def test_blocs_dans_le_detail(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        with app.app_context():
            uid = Ticket.query.get(tid).uid_public
        login(client, 'rdv_drh')
        html = client.get(f'/tickets/view/{uid}').data.decode()
        assert 'Proposer un rendez-vous' in html and 'Fixer directement' in html
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(_future())})
        login(client, 'rdv_user')
        html = client.get(f'/tickets/view/{uid}').data.decode()
        assert 'Le service vous propose un rendez-vous' in html and "J'accepte" in html and 'Proposer mes disponibilités' in html
        assert 'Proposer un rendez-vous' not in html      # le demandeur n'a pas le bloc équipe
        login(client, 'rdv_info')                          # autre service : ni l'un ni l'autre
        html = client.get(f'/tickets/view/{uid}').data.decode()
        assert 'Proposer un rendez-vous' not in html

    def test_planning_montre_proposes_en_attente(self, client, db_session, app, mail_spy):
        _users(app); tid = _ticket(app)
        login(client, 'rdv_drh')
        client.post(f'/tickets/rdv/{tid}/propose', data={'starts_at': _iso(_future(1, 11))})
        html = client.get('/tickets/planning?week=' + _future(1).strftime('%Y-%m-%d')).data.decode()
        assert 'À confirmer' in html and 'Entretien RH' in html


class TestRappel:

    def test_rappel_du_jour_aux_deux_parties_une_seule_fois(self, app, db_session, mail_spy):
        _users(app); tid = _ticket(app, solver='rdv_drh2')
        with app.app_context():
            t = Ticket.query.get(tid)
            today = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            drh = User.query.filter_by(username='rdv_drh').first()
            db.session.add(Appointment(ticket=t, proposed_by=drh, starts_at=today, status='accepted'))
            t2 = Ticket.query.get(_ticket(app))
            db.session.add(Appointment(ticket=t2, proposed_by=drh, starts_at=tomorrow, status='accepted'))
            t3 = Ticket.query.get(_ticket(app))
            db.session.add(Appointment(ticket=t3, proposed_by=drh, starts_at=today, status='proposed'))
            db.session.commit()
            # Comme le script cron : simple contexte d'application, sans requête HTTP
            assert rdv.send_reminders(datetime.now()) == 1
            assert rdv.send_reminders(datetime.now()) == 0          # déjà rappelé
            assert {m['to'] for m in mail_spy} == {'rdv_user', 'rdv_drh', 'rdv_drh2'}
            assert all(m['kind'] == 'digest' for m in mail_spy)
            assert any('Rappel' in m for m in _notifs('rdv_user')) and any('Rappel' in m for m in _notifs('rdv_drh2'))
