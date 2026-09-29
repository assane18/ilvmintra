#!/usr/bin/env python3
"""
=============================================================================
 TESTS LOT 7 — « Organisation des demandes »
=============================================================================
   1. Délégation de validation (absences) : app/delegation.py,
      ValidationDelegation, /delegations/*, effet sur _can_validate_ticket,
      can_validate_step, manager_dashboard, batch_validate, digests.
   2. Demande pour quelqu'un d'autre : Ticket/FormSubmission.created_by,
      auteur = personne concernée, N1 sur SON service, manager_only.
   3. Refaire la même demande : pré-remplissage ?from=<id|uid>.

 Fixtures reprises de tests_intranet.py (SQLite mémoire, pas de LDAP, e-mails
 supprimés via mail.init_app après TestConfig). `login()` vide g._login_user :
 la fixture `app` garde un app_context ambiant pour toute la session.

 Usage :
   cd /var/www/intranet && source venv/bin/activate
   python -m pytest tests_lot7.py -v
=============================================================================
"""

import os
import sys
import json
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['FLASK_ENV'] = 'testing'
os.environ['FLASK_DEBUG'] = '0'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app, db, mail
from app.models import (
    User, UserRole, Ticket, TicketStatus, TicketMessage, ServiceType, Notification,
    FormDefinition, FormField, FormFieldType, FormWorkflowStep, ServiceSource,
    FormSubmission, FormSubmissionStatus, ValidationDelegation,
)


class TestConfig:
    TESTING = True
    DEBUG = False
    SECRET_KEY = 'cle-secrete-test-lot7'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    UPLOAD_FOLDER = '/tmp/intranet_test_uploads_lot7'
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
#  FIXTURES (reprises de tests_intranet.py)
# ===========================================================================

@pytest.fixture(scope='session')
def app():
    _app = create_app('development')
    _app.config.from_object(TestConfig)
    assert _app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite:///:memory:', (
        "Refus de lancer les tests : SQLALCHEMY_DATABASE_URI ne pointe pas vers la sqlite en mémoire "
        f"(valeur actuelle : {_app.config['SQLALCHEMY_DATABASE_URI']!r})."
    )
    # Flask-Mail a capturé MAIL_SUPPRESS_SEND avant TestConfig : on le rappelle
    # pour qu'aucun e-mail réel ne parte (délégation -> e-mail au délégué).
    mail.init_app(_app)
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


def make_user(role=UserRole.USER, username='testuser', password='Test1234!',
              fullname='Test User', service=ServiceType.INFO, allowed_services=None):
    u = User(username=username, fullname=fullname, email=f'{username}@test.lan', role=role)
    u.set_origin_services([service.value])
    if allowed_services:
        u.set_allowed_services([s.value for s in allowed_services])
    else:
        u.set_allowed_services([service.value])
    db.session.add(u)
    db.session.commit()
    return u


def login(client, username='testuser', password='Test1234!'):
    with client.application.app_context():
        user = User.query.filter_by(username=username).first()
        if user is None:
            raise ValueError(f"Utilisateur '{username}' introuvable en base de test")
        uid = user.id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True
    from flask import g, has_app_context
    if has_app_context():
        g.pop('_login_user', None)
    return client.get('/portal', follow_redirects=False)


def make_ticket(author, service=ServiceType.INFO, status=TicketStatus.PENDING,
                title='Ticket de test', description='Description de test', uid=None, **extra):
    t = Ticket(
        uid_public=uid or f'{datetime.utcnow().strftime("%Y%m%d")}-{Ticket.query.count()+1:03d}',
        title=title, description=description, author_id=author.id, target_service=service,
        status=status, category_ticket=extra.pop('category_ticket', 'STANDARD'),
        service_demandeur=extra.pop('service_demandeur', author.service),
        tel_demandeur='0100000000', **extra,
    )
    db.session.add(t)
    db.session.commit()
    return t


def make_delegation(delegator, delegate, days_before=1, days_after=1, active=True, reason='Congés'):
    now = datetime.now()
    d = ValidationDelegation(delegator_id=delegator.id, delegate_id=delegate.id,
                             starts_at=now - timedelta(days=days_before) if days_before >= 0 else now + timedelta(days=-days_before),
                             ends_at=now + timedelta(days=days_after),
                             reason=reason, is_active=active)
    db.session.add(d)
    db.session.commit()
    return d


def make_form(slug='demande-test', steps=None, fields=None, manager_only=False, active=True):
    """Formulaire du moteur : par défaut un champ texte + une étape EMITTER
    (validation par le manager du service du DEMANDEUR — l'équivalent N1)."""
    f = FormDefinition(slug=slug, name=f'Formulaire {slug}', is_active=active, manager_only=manager_only)
    db.session.add(f)
    db.session.flush()
    fields = fields if fields is not None else [dict(name='sujet', label='Sujet', field_type=FormFieldType.TEXT, is_required=True)]
    for i, fd in enumerate(fields):
        db.session.add(FormField(form_definition_id=f.id, order_index=i,
                                 options_json=json.dumps(fd.pop('options')) if fd.get('options') else None, **fd))
    steps = steps if steps is not None else [dict(label='Validation équipe', service_source=ServiceSource.EMITTER)]
    for i, sd in enumerate(steps):
        db.session.add(FormWorkflowStep(form_definition_id=f.id, order_index=i, **sd))
    db.session.commit()
    return f


def make_submission(form, author, data, created_by=None):
    s = FormSubmission(uid_public=f'FRM-{form.slug}-{FormSubmission.query.count()+1:03d}', form_definition_id=form.id,
                       author_id=author.id, created_by_id=created_by.id if created_by else None,
                       current_step_index=0, status=FormSubmissionStatus.IN_PROGRESS)
    s.set_data(data)
    db.session.add(s)
    db.session.commit()
    return s


def notifications_of(user, contains=None):
    q = Notification.query.filter_by(user_id=user.id)
    if contains:
        q = q.filter(Notification.message.contains(contains))
    return q.all()


def _team():
    """Jeu de données commun : un agent du FJ, son manager (FJ), un manager
    d'un autre service (MAS, qui n'a AUCUN droit sur le FJ), un admin."""
    agent = make_user(username='agent_fj', fullname='Alice Agent', service=ServiceType.FJ)
    mgr_fj = make_user(UserRole.MANAGER, username='mgr_fj', fullname='Marc Manager', service=ServiceType.FJ,
                       allowed_services=[ServiceType.TECH])
    mgr_mas = make_user(UserRole.MANAGER, username='mgr_mas', fullname='Diane Deleguee', service=ServiceType.MAS)
    admin = make_user(UserRole.ADMIN, username='admin', fullname='Super Admin', service=ServiceType.INFO)
    return agent, mgr_fj, mgr_mas, admin


# ===========================================================================
#  1. DÉLÉGATION DE VALIDATION
# ===========================================================================

class TestDelegationLogique:
    """app/delegation.py — identités effectives, sans passer par HTTP."""

    def test_effective_validators_suit_la_periode(self, app, db_session):
        from app.delegation import effective_validators, validation_identities
        agent, mgr_fj, mgr_mas, admin = _team()
        assert [u.id for u in effective_validators(mgr_mas)] == [mgr_mas.id]

        d = make_delegation(mgr_fj, mgr_mas)  # active (hier -> demain)
        assert [u.id for u in effective_validators(mgr_mas)] == [mgr_mas.id, mgr_fj.id]
        # Le délégant, lui, ne gagne rien
        assert [u.id for u in effective_validators(mgr_fj)] == [mgr_fj.id]

        # Avant / après la période, ou annulée : aucun effet
        d.starts_at = datetime.now() + timedelta(days=2); d.ends_at = datetime.now() + timedelta(days=5); db.session.commit()
        assert [u.id for u in effective_validators(mgr_mas)] == [mgr_mas.id]
        d.starts_at = datetime.now() - timedelta(days=5); d.ends_at = datetime.now() - timedelta(days=2); db.session.commit()
        assert [u.id for u in effective_validators(mgr_mas)] == [mgr_mas.id]
        d.starts_at = datetime.now() - timedelta(days=1); d.ends_at = datetime.now() + timedelta(days=1); d.is_active = False; db.session.commit()
        assert [u.id for u in effective_validators(mgr_mas)] == [mgr_mas.id]

        # Jamais de délégation pour SA PROPRE demande
        d.is_active = True; db.session.commit()
        assert [u.id for u in validation_identities(mgr_mas, author_id=mgr_mas.id)] == [mgr_mas.id]
        assert [u.id for u in validation_identities(mgr_mas, author_id=agent.id)] == [mgr_mas.id, mgr_fj.id]

    def test_regles_de_creation(self, app, db_session):
        from app.delegation import create_delegation, parse_period
        agent, mgr_fj, mgr_mas, admin = _team()
        solver = make_user(UserRole.SOLVER, username='solver', fullname='Sam Solver', service=ServiceType.INFO)
        s, e = parse_period('2030-01-01', '2030-01-10')
        assert s == datetime(2030, 1, 1) and e == datetime(2030, 1, 10, 23, 59, 59)

        assert create_delegation(mgr_fj, mgr_fj, s, e)[1]          # à soi-même
        assert create_delegation(mgr_fj, agent, s, e)[1]           # vers un USER
        assert create_delegation(mgr_fj, solver, s, e)[1]          # vers un SOLVER
        assert create_delegation(agent, mgr_fj, s, e)[1]           # un USER ne délègue pas
        assert create_delegation(mgr_fj, mgr_mas, e, s)[1]         # fin avant début
        assert create_delegation(mgr_fj, mgr_mas, *parse_period('2020-01-01', '2020-01-02'))[1]  # déjà terminée
        assert parse_period('n/a', '2030-01-01') == (None, None)
        assert create_delegation(mgr_fj, mgr_mas, None, None)[1]
        assert ValidationDelegation.query.count() == 0

        d, err = create_delegation(mgr_fj, mgr_mas, s, e, reason='Congés')
        db.session.commit()
        assert err is None and d.id and d.reason == 'Congés'
        assert notifications_of(mgr_mas, 'vous délègue ses validations')

    def test_can_validate_ticket_par_delegation_et_trace(self, app, db_session):
        from app.routes.tickets import _can_validate_ticket
        from app.delegation import on_behalf_of
        agent, mgr_fj, mgr_mas, admin = _team()
        t = make_ticket(agent, service=ServiceType.TECH, status=TicketStatus.VALIDATION_N1)
        assert _can_validate_ticket(mgr_fj, t) is True and on_behalf_of(t) is None
        assert _can_validate_ticket(mgr_mas, t) is False

        make_delegation(mgr_fj, mgr_mas)
        assert _can_validate_ticket(mgr_mas, t) is True
        assert on_behalf_of(t).id == mgr_fj.id  # droit emprunté -> trace « pour le compte de »
        # Le délégué n'utilise pas la délégation pour son propre ticket
        own = make_ticket(mgr_mas, service=ServiceType.TECH, status=TicketStatus.VALIDATION_N1, service_demandeur='FJ')
        assert _can_validate_ticket(mgr_mas, own) is False


class TestDelegationTickets:

    def test_delegue_voit_et_valide_ticket_n1_du_delegant(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        t = make_ticket(agent, service=ServiceType.TECH, status=TicketStatus.VALIDATION_N1, title='Fuite radiateur bureau 12')
        tid, uid = t.id, t.uid_public
        make_delegation(mgr_fj, mgr_mas)

        login(client, 'mgr_mas')
        r = client.get('/tickets/manager/dashboard')
        assert r.status_code == 200 and b'Fuite radiateur bureau 12' in r.data

        r = client.post(f'/tickets/manager/action/{tid}/validate', follow_redirects=True)
        assert r.status_code == 200
        db.session.expire_all()
        t = Ticket.query.get(tid)
        assert t.status == TicketStatus.VALIDATION_N2
        assert t.validated_by_id == mgr_mas.id            # la trace enregistre le DÉLÉGUÉ
        msgs = [m.content for m in TicketMessage.query.filter_by(ticket_id=tid).all()]
        assert sum('Diane Deleguee pour le compte de Marc Manager' in m for m in msgs) == 1   # une seule trace, pas de doublon
        assert len(notifications_of(mgr_fj, 'pour votre compte')) == 1   # le délégant est informé
        assert notifications_of(agent, 'pour le compte de Marc Manager')  # le demandeur aussi

    def test_pas_de_droit_hors_periode_ou_annulee(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        t = make_ticket(agent, service=ServiceType.TECH, status=TicketStatus.VALIDATION_N1, title='Porte bloquée')
        tid = t.id
        future = make_delegation(mgr_fj, mgr_mas, days_before=-2, days_after=5)   # à venir
        login(client, 'mgr_mas')
        r = client.get('/tickets/manager/dashboard')
        assert b'Porte bloqu' not in r.data
        client.post(f'/tickets/manager/action/{tid}/validate', follow_redirects=True)
        db.session.expire_all()
        assert Ticket.query.get(tid).status == TicketStatus.VALIDATION_N1

        # expirée
        future.starts_at = datetime.now() - timedelta(days=10); future.ends_at = datetime.now() - timedelta(days=3); db.session.commit()
        client.post(f'/tickets/manager/action/{tid}/validate', follow_redirects=True)
        db.session.expire_all()
        assert Ticket.query.get(tid).status == TicketStatus.VALIDATION_N1

        # active mais annulée
        future.starts_at = datetime.now() - timedelta(days=1); future.ends_at = datetime.now() + timedelta(days=1)
        future.is_active = False; db.session.commit()
        client.post(f'/tickets/manager/action/{tid}/validate', follow_redirects=True)
        db.session.expire_all()
        assert Ticket.query.get(tid).status == TicketStatus.VALIDATION_N1
        assert TicketMessage.query.filter_by(ticket_id=tid).count() == 0

    def test_delegue_valide_ticket_n2_du_delegant(self, client, db_session, app):
        """N2 : le service cible (TECH) est géré par le délégant, pas par le délégué."""
        agent, mgr_fj, mgr_mas, admin = _team()
        t = make_ticket(agent, service=ServiceType.TECH, status=TicketStatus.VALIDATION_N2, title='Achat perceuse')
        tid = t.id
        make_delegation(mgr_fj, mgr_mas)
        login(client, 'mgr_mas')
        r = client.get('/tickets/manager/dashboard')
        assert b'Achat perceuse' in r.data
        client.post(f'/tickets/manager/action/{tid}/validate', follow_redirects=True)
        db.session.expire_all()
        assert Ticket.query.get(tid).status == TicketStatus.PENDING

    def test_validation_en_lot_par_delegation(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        t1 = make_ticket(agent, service=ServiceType.TECH, status=TicketStatus.VALIDATION_N1)
        t2 = make_ticket(agent, service=ServiceType.GEN, status=TicketStatus.VALIDATION_N1)
        ids = [t1.id, t2.id]
        login(client, 'mgr_mas')
        client.post('/tickets/manager/batch_validate', data={'ticket_ids': [str(i) for i in ids]}, follow_redirects=True)
        db.session.expire_all()
        assert all(Ticket.query.get(i).status == TicketStatus.VALIDATION_N1 for i in ids)  # sans délégation : rien

        make_delegation(mgr_fj, mgr_mas)
        client.post('/tickets/manager/batch_validate', data={'ticket_ids': [str(i) for i in ids]}, follow_redirects=True)
        db.session.expire_all()
        assert all(Ticket.query.get(i).status == TicketStatus.VALIDATION_N2 for i in ids)
        assert all(Ticket.query.get(i).validated_by_id == mgr_mas.id for i in ids)
        assert len(notifications_of(mgr_fj, 'pour votre compte')) == 2

    def test_refus_par_delegation_trace(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        t = make_ticket(agent, service=ServiceType.TECH, status=TicketStatus.VALIDATION_N1)
        tid = t.id
        make_delegation(mgr_fj, mgr_mas)
        login(client, 'mgr_mas')
        client.post(f'/tickets/manager/action/{tid}/refuse', data={'refusal_reason': 'Hors budget'}, follow_redirects=True)
        db.session.expire_all()
        assert Ticket.query.get(tid).status == TicketStatus.REFUSED
        msgs = [m.content for m in TicketMessage.query.filter_by(ticket_id=tid).all()]
        assert any('REFUS' in m and 'pour le compte de Marc Manager' in m for m in msgs)

    def test_recap_hebdo_inclut_les_delegations(self, app, db_session):
        from app.digests import pending_validations_for
        agent, mgr_fj, mgr_mas, admin = _team()
        t = make_ticket(agent, service=ServiceType.TECH, status=TicketStatus.VALIDATION_N1)
        form = make_form()
        s = make_submission(form, agent, {'sujet': 'Badge perdu'})
        assert pending_validations_for(mgr_mas) == ([], [])
        make_delegation(mgr_fj, mgr_mas)
        tickets, subs = pending_validations_for(mgr_mas)
        assert [x.id for x in tickets] == [t.id] and [x.id for x in subs] == [s.id]


class TestDelegationFormulaires:

    def test_delegue_voit_et_valide_soumission_du_delegant(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        form = make_form()
        s = make_submission(form, agent, {'sujet': 'Badge perdu'})
        sid = s.id
        login(client, 'mgr_mas')
        r = client.get('/forms/to-validate')
        assert b'FRM-demande-test' not in r.data
        r = client.post(f'/forms/submission/{sid}/validate/validate', follow_redirects=True)
        db.session.expire_all()
        assert FormSubmission.query.get(sid).status == FormSubmissionStatus.IN_PROGRESS  # refusé sans délégation

        make_delegation(mgr_fj, mgr_mas)
        r = client.get('/forms/to-validate')
        assert b'FRM-demande-test' in r.data
        r = client.get('/tickets/manager/dashboard')
        assert b'FRM-demande-test' in r.data                      # onglet N1 du tableau manager
        r = client.post(f'/forms/submission/{sid}/validate/validate', follow_redirects=True)
        assert r.status_code == 200
        db.session.expire_all()
        s = FormSubmission.query.get(sid)
        assert s.status == FormSubmissionStatus.DONE               # une seule étape, pas de destinataire
        assert s.validated_by_id == mgr_mas.id
        assert notifications_of(mgr_fj, 'pour votre compte')
        assert notifications_of(agent, 'Diane Deleguee pour le compte de Marc Manager')

    def test_refus_soumission_par_delegation(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        form = make_form()
        s = make_submission(form, agent, {'sujet': 'Badge perdu'})
        sid = s.id
        make_delegation(mgr_fj, mgr_mas)
        login(client, 'mgr_mas')
        client.post(f'/forms/submission/{sid}/validate/refuse', data={'refusal_reason': 'Doublon'}, follow_redirects=True)
        db.session.expire_all()
        s = FormSubmission.query.get(sid)
        assert s.status == FormSubmissionStatus.REFUSED
        assert 'pour le compte de Marc Manager' in s.refusal_reason

    def test_validation_en_lot_soumission_par_delegation(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        form = make_form()
        s = make_submission(form, agent, {'sujet': 'Badge perdu'})
        sid = s.id
        make_delegation(mgr_fj, mgr_mas)
        login(client, 'mgr_mas')
        client.post('/tickets/manager/batch_validate', data={'submission_ids': [str(sid)]}, follow_redirects=True)
        db.session.expire_all()
        assert FormSubmission.query.get(sid).status == FormSubmissionStatus.DONE


class TestDelegationRoutes:

    def test_declaration_depuis_le_profil(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        login(client, 'mgr_fj')
        r = client.get('/profile')
        assert r.status_code == 200 and 'Mes délégations de validation'.encode() in r.data

        today = datetime.now().strftime('%Y-%m-%d')
        later = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        # Interdictions : soi-même, un USER, dates inversées
        for data in ({'delegate_id': mgr_fj.id}, {'delegate_id': agent.id},
                     {'delegate_id': mgr_mas.id, 'starts_at': later, 'ends_at': today}):
            payload = {'starts_at': today, 'ends_at': later}; payload.update(data)
            client.post('/delegations/new', data=payload, follow_redirects=True)
        assert ValidationDelegation.query.count() == 0

        r = client.post('/delegations/new', data={'delegate_id': mgr_mas.id, 'starts_at': today, 'ends_at': later,
                                                  'reason': 'Congés'}, follow_redirects=True)
        assert r.status_code == 200 and 'Délégation enregistrée'.encode() in r.data
        d = ValidationDelegation.query.one()
        assert d.delegator_id == mgr_fj.id and d.delegate_id == mgr_mas.id and d.is_current()
        assert notifications_of(mgr_mas, 'vous délègue ses validations')
        assert b'Diane Deleguee' in client.get('/profile').data

        # Un USER n'a ni le bloc, ni le droit de déléguer
        login(client, 'agent_fj')
        assert 'Mes délégations de validation'.encode() not in client.get('/profile').data
        client.post('/delegations/new', data={'delegate_id': mgr_mas.id, 'starts_at': today, 'ends_at': later}, follow_redirects=True)
        assert ValidationDelegation.query.count() == 1

    def test_annulation_par_le_delegant_puis_admin(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        d1 = make_delegation(mgr_fj, mgr_mas)
        d2 = make_delegation(mgr_fj, mgr_mas, days_before=-3, days_after=10)
        id1, id2 = d1.id, d2.id

        login(client, 'mgr_mas')   # le délégué ne peut pas annuler
        client.post(f'/delegations/{id1}/cancel', follow_redirects=True)
        db.session.expire_all()
        assert ValidationDelegation.query.get(id1).is_active is True

        login(client, 'mgr_fj')
        client.post(f'/delegations/{id1}/cancel', follow_redirects=True)
        db.session.expire_all()
        assert ValidationDelegation.query.get(id1).is_active is False
        assert notifications_of(mgr_mas, 'a été annulée')

        login(client, 'admin')
        r = client.get('/delegations/admin')
        assert r.status_code == 200 and b'Marc Manager' in r.data and b'Diane Deleguee' in r.data
        r = client.get('/delegations/admin?show=all')
        assert 'Annulée'.encode() in r.data
        r = client.post(f'/delegations/{id2}/cancel', data={'next': 'admin'}, follow_redirects=True)
        assert r.status_code == 200
        db.session.expire_all()
        assert ValidationDelegation.query.get(id2).is_active is False
        assert notifications_of(mgr_fj, 'annulée par Super Admin')

        login(client, 'mgr_fj')     # vue admin réservée à l'ADMIN
        r = client.get('/delegations/admin')
        assert r.status_code == 302

    def test_recherche_utilisateurs_json(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        for i in range(12):
            make_user(username=f'dup{i}', fullname=f'Dupont Numero{i}', service=ServiceType.FV)

        r = client.get('/delegations/users/search?q=dup')
        assert r.status_code == 302                                  # login_required

        login(client, 'mgr_fj')
        r = client.get('/delegations/users/search?q=DUPONT')          # insensible à la casse
        assert r.status_code == 200
        rows = r.get_json()
        assert len(rows) == 10 and all('Dupont' in x['fullname'] for x in rows)
        assert set(rows[0]) >= {'id', 'username', 'fullname', 'service', 'role', 'label'}
        assert rows[0]['service'] == 'FV'

        rows = client.get('/delegations/users/search?q=ma').get_json()
        names = [x['username'] for x in rows]
        assert 'mgr_mas' in names and 'mgr_fj' not in names           # soi-même exclu ('Marc Manager')
        rows = client.get('/delegations/users/search?q=a&scope=validators').get_json()
        assert rows == []                                             # 2 caractères minimum
        rows = client.get('/delegations/users/search?q=age&scope=validators').get_json()
        assert all(x['username'] != 'agent_fj' for x in rows)         # USER exclu du périmètre validateurs
        rows = client.get('/delegations/users/search?q=age').get_json()
        assert any(x['username'] == 'agent_fj' for x in rows)


# ===========================================================================
#  2. DEMANDE POUR QUELQU'UN D'AUTRE
# ===========================================================================

class TestDemandePourAutrui:

    def test_ticket_pour_autrui(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        creator = make_user(username='secretaire', fullname='Sophie Secretaire', service=ServiceType.INFO)
        login(client, 'secretaire')
        r = client.get('/tickets/new/TECH')
        assert r.status_code == 200 and "au nom de quelqu'un d'autre".encode() in r.data

        r = client.post('/tickets/new/TECH', data={
            'title': 'Store cassé', 'description': 'Le store du bureau 3 ne remonte plus',
            'category_ticket': 'Standard', 'on_behalf_of_id': str(agent.id),
        }, follow_redirects=True)
        assert r.status_code == 200
        t = Ticket.query.filter_by(title='Store cassé').one()
        assert t.author_id == agent.id                 # l'auteur = la personne concernée
        assert t.created_by_id == creator.id           # le créateur réel est conservé
        assert t.service_demandeur == 'FJ'             # N1 sur SON service, pas celui du créateur (INFO)
        assert t.status == TicketStatus.VALIDATION_N1
        assert notifications_of(agent, 'pour votre compte')
        assert notifications_of(mgr_fj, 'Validation requise')   # manager du FJ prévenu

        # La personne concernée voit la demande dans son historique / portail
        login(client, 'agent_fj')
        assert b'Store cass' in client.get('/my_history').data
        assert b'Store cass' in client.get('/portal').data

        # N1 : c'est le manager du FJ (service de la personne concernée) qui la voit, pas celui de l'INFO
        login(client, 'mgr_fj')
        assert b'Store cass' in client.get('/tickets/manager/dashboard').data
        r = client.get(f'/tickets/view/{t.uid_public}')
        assert 'Demande créée par Sophie Secretaire pour le compte de Alice Agent'.encode() in r.data
        login(client, 'mgr_mas')
        assert b'Store cass' not in client.get('/tickets/manager/dashboard').data

    def test_pour_soi_meme_ou_inconnu_ignore(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        login(client, 'agent_fj')
        client.post('/tickets/new/TECH', data={'title': 'Pour moi', 'description': 'x', 'category_ticket': 'Standard',
                                               'on_behalf_of_id': str(agent.id)}, follow_redirects=True)
        client.post('/tickets/new/TECH', data={'title': 'Inconnu', 'description': 'x', 'category_ticket': 'Standard',
                                               'on_behalf_of_id': '99999'}, follow_redirects=True)
        for title in ('Pour moi', 'Inconnu'):
            t = Ticket.query.filter_by(title=title).one()
            assert t.author_id == agent.id and t.created_by_id is None

    def test_cloture_notifie_le_createur(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        creator = make_user(username='secretaire', fullname='Sophie Secretaire', service=ServiceType.INFO)
        solver = make_user(UserRole.SOLVER, username='tech', fullname='Tom Tech', service=ServiceType.TECH)
        t = make_ticket(agent, service=ServiceType.TECH, status=TicketStatus.IN_PROGRESS, created_by_id=creator.id)
        t.solver_id = solver.id; db.session.commit()
        tid, uid = t.id, t.uid_public
        login(client, 'tech')
        r = client.post(f'/tickets/solver/close/{tid}', follow_redirects=True)
        assert r.status_code == 200
        db.session.expire_all()
        assert Ticket.query.get(tid).status == TicketStatus.DONE
        assert notifications_of(agent, 'clôturé')                       # la personne concernée (existant)
        assert len(notifications_of(creator, f'{uid} que vous avez créé pour Alice Agent')) == 1  # le créateur réel, une fois

    def test_materiel_pour_un_non_habilite_refuse(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        login(client, 'mgr_fj')
        r = client.post('/tickets/new/MATERIEL', data={'title': 'Demande de Matériel', 'description': 'Un écran',
                                                       'on_behalf_of_id': str(agent.id)}, follow_redirects=True)
        assert r.status_code == 200 and b'pas habilit' in r.data   # (apostrophe échappée par Jinja)
        assert Ticket.query.count() == 0
        r = client.post('/tickets/new/MATERIEL', data={'title': 'Demande de Matériel', 'description': 'Un écran',
                                                       'on_behalf_of_id': str(mgr_mas.id)}, follow_redirects=True)
        t = Ticket.query.one()
        assert t.author_id == mgr_mas.id and t.created_by_id == mgr_fj.id and t.service_demandeur == 'MAS'

    def test_soumission_pour_autrui(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        creator = make_user(username='secretaire', fullname='Sophie Secretaire', service=ServiceType.INFO)
        form = make_form()
        login(client, 'secretaire')
        r = client.get(f'/forms/{form.slug}/new')
        assert r.status_code == 200 and "au nom de quelqu'un d'autre".encode() in r.data
        r = client.post(f'/forms/{form.slug}/new', data={'sujet': 'Badge perdu', 'on_behalf_of_id': str(agent.id)},
                        follow_redirects=True)
        assert r.status_code == 200
        s = FormSubmission.query.one()
        assert s.author_id == agent.id and s.created_by_id == creator.id
        assert s.status == FormSubmissionStatus.IN_PROGRESS
        assert notifications_of(agent, 'pour votre compte')
        assert notifications_of(mgr_fj, 'à valider')            # étape EMITTER -> manager du service de l'agent

        login(client, 'agent_fj')
        assert b'FRM-demande-test' in client.get('/my_history').data

        # Validation par le manager du FJ (service de la personne concernée), pas par celui de la secrétaire
        from app.decorators import can_validate_step
        assert can_validate_step(mgr_fj, s.current_step, s) is True
        assert can_validate_step(mgr_mas, s.current_step, s) is False
        login(client, 'mgr_fj')
        r = client.get(f'/forms/submission/{s.id}')
        assert 'Demande créée par Sophie Secretaire pour le compte de Alice Agent'.encode() in r.data
        client.post(f'/forms/submission/{s.id}/validate/validate', follow_redirects=True)
        db.session.expire_all()
        assert FormSubmission.query.get(s.id).status == FormSubmissionStatus.DONE
        assert notifications_of(creator, 'que vous avez déposé pour Alice Agent')   # créateur réel prévenu

    def test_formulaire_manager_only_pour_autrui(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        form = make_form(slug='materiel-test', manager_only=True)
        login(client, 'mgr_fj')
        r = client.post(f'/forms/{form.slug}/new', data={'sujet': 'Un PC', 'on_behalf_of_id': str(agent.id)})
        assert r.status_code == 403
        assert FormSubmission.query.count() == 0
        r = client.post(f'/forms/{form.slug}/new', data={'sujet': 'Un PC', 'on_behalf_of_id': str(mgr_mas.id)},
                        follow_redirects=True)
        assert r.status_code == 200
        s = FormSubmission.query.one()
        assert s.author_id == mgr_mas.id and s.created_by_id == mgr_fj.id


# ===========================================================================
#  3. REFAIRE LA MÊME DEMANDE
# ===========================================================================

class TestRefaireDemande:

    def _form_riche(self):
        return make_form(slug='riche', fields=[
            dict(name='sujet', label='Sujet', field_type=FormFieldType.TEXT, is_required=True),
            dict(name='type', label='Type', field_type=FormFieldType.SELECT, options=['Incident', 'Demande']),
            dict(name='options', label='Options', field_type=FormFieldType.MULTI_SELECT, options=['A', 'B', 'C']),
            dict(name='urgent', label='Urgent', field_type=FormFieldType.CHECKBOX),
            dict(name='piece', label='Pièce jointe', field_type=FormFieldType.FILE),
        ])

    def test_soumission_prerempli(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        form = self._form_riche()
        s = make_submission(form, agent, {'sujet': 'Écran cassé', 'type': 'Incident', 'options': ['A', 'C'], 'urgent': True})
        login(client, 'agent_fj')
        r = client.get(f'/forms/riche/new?from={s.id}')
        assert r.status_code == 200
        html = r.data.decode()
        assert 'value="Écran cassé"' in html
        assert '<option value="Incident" selected>' in html
        assert 'value="A" class="w-4 h-4"\n                    checked' in html or ('value="A"' in html and html.count('checked') >= 3)
        assert 'name="urgent" class="w-4 h-4" checked' in html
        assert 'pré-rempli' in html

        # Le détail de la soumission propose « Refaire cette demande »
        r = client.get(f'/forms/submission/{s.id}')
        assert f'/forms/riche/new?from={s.id}'.encode() in r.data and b'Refaire cette demande' in r.data

    def test_soumission_pas_a_moi_refusee(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        form = self._form_riche()
        s = make_submission(form, mgr_mas, {'sujet': 'Secret du MAS', 'type': 'Demande'})
        login(client, 'agent_fj')
        r = client.get(f'/forms/riche/new?from={s.id}')
        assert r.status_code == 200
        assert b'Secret du MAS' not in r.data
        assert 'Impossible de pré-remplir'.encode() in r.data
        # … ni pour un autre formulaire que celui d'origine
        other = make_form(slug='autre')
        mine = make_submission(form, agent, {'sujet': 'Mon sujet'})
        r = client.get(f'/forms/autre/new?from={mine.id}')
        assert b'Mon sujet' not in r.data

    def test_createur_reel_peut_refaire(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        creator = make_user(username='secretaire', fullname='Sophie Secretaire', service=ServiceType.INFO)
        form = self._form_riche()
        s = make_submission(form, agent, {'sujet': 'Pour Alice', 'type': 'Demande'}, created_by=creator)
        login(client, 'secretaire')
        assert b'value="Pour Alice"' in client.get(f'/forms/riche/new?from={s.id}').data

    def test_ticket_legacy_prerempli(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        t = make_ticket(agent, service=ServiceType.TECH, title='Néon grillé', description='Couloir du 2e étage',
                        uid='20260901-001', category_ticket='Standard', hostname='Bureau 12')
        other = make_ticket(mgr_mas, service=ServiceType.TECH, title='Ticket du MAS', uid='20260901-002')
        login(client, 'agent_fj')
        r = client.get('/tickets/new/TECH?from=20260901-001')
        html = r.data.decode()
        assert r.status_code == 200
        assert 'value="Néon grillé"' in html and 'Couloir du 2e étage</textarea>' in html
        assert 'value="Bureau 12"' in html and '<option value="Standard" selected>' in html
        assert 'pré-rempli' in html

        r = client.get('/tickets/new/TECH?from=20260901-002')     # pas à moi
        assert b'Ticket du MAS' not in r.data and 'Impossible de pré-remplir'.encode() in r.data

        # DRH : le type de démarche est retrouvé depuis le titre « [DRH] … »
        make_ticket(agent, service=ServiceType.DRH, title='[DRH] Attestation employeur', uid='20260901-003')
        html = client.get('/tickets/new/DRH?from=20260901-003').data.decode()
        assert '<option value="Autre" selected>' in html and 'value="Attestation employeur"' in html

    def test_historique_propose_refaire(self, client, db_session, app):
        agent, mgr_fj, mgr_mas, admin = _team()
        make_ticket(agent, service=ServiceType.TECH, title='Néon grillé', uid='20260901-001')
        make_ticket(agent, service=ServiceType.INFO, title='Matériel', uid='20260901-002', category_ticket='Demande Matériel')
        make_ticket(agent, service=ServiceType.INFO, title='Hors legacy', uid='SEJ-0001')
        form = make_form()
        s = make_submission(form, agent, {'sujet': 'Badge'})
        login(client, 'agent_fj')
        html = client.get('/my_history').data.decode()
        assert '/tickets/new/TECH?from=20260901-001' in html
        assert '/tickets/new/MATERIEL?from=20260901-002' in html
        assert f'/forms/{form.slug}/new?from={s.id}' in html
        assert 'from=SEJ-0001' not in html
        assert html.count('Refaire') == 3

    def test_redo_url_helpers(self, app, db_session):
        from app.delegation import redo_url_for_ticket, redo_url_for_submission
        agent, mgr_fj, mgr_mas, admin = _team()
        form = make_form()
        s = make_submission(form, agent, {'sujet': 'x'})
        t = make_ticket(agent, service=ServiceType.TECH, uid=f'F{s.id}-TEC')  # ticket issu du moteur -> formulaire d'origine
        with app.test_request_context():
            assert redo_url_for_ticket(t) == f'/forms/{form.slug}/new?from={s.id}'
            daf = make_ticket(agent, service=ServiceType.DAF, uid='20260901-009', category_ticket='Bon de Commande (Délégation)')
            assert redo_url_for_ticket(daf) == '/tickets/new/DAF?from=20260901-009&type=delegation'
            form.is_active = False; db.session.commit()
            assert redo_url_for_submission(s) is None
