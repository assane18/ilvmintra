#!/usr/bin/env python3
"""Tests du lot 8 « Reporting et conformité » : journal d'audit (app/audit.py,
/admin/audit), rapport mensuel PDF (app/reporting.py, /admin/rapports) et
purge RGPD (app/rgpd.py, /admin/rgpd).

Réutilise les fixtures de tests_intranet.py (SQLite en mémoire, login par
injection de session). Les fichiers sont créés dans des dossiers temporaires :
aucune purge réelle n'est possible ici. Lancer :

    /var/www/intranet/venv/bin/python -m pytest tests_lot8.py -q
"""
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tests_intranet import app, client, db_session, make_user, login, make_ticket, make_notification  # noqa: F401
from app import db
from app.models import (User, UserRole, Ticket, TicketStatus, TicketMessage, ServiceType, Notification,
                        AuditLog, Recruitment, RecruitmentStatus, FormDefinition, FormField, FormFieldType,
                        FormSubmission, FormSubmissionStatus, FormSubmissionFile)
from app.audit import log_action, history_for
from app import reporting, rgpd


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def _users(app):
    with app.app_context():
        make_user(username='l8_user', role=UserRole.USER, service=ServiceType.DRH, fullname='Ulysse USER')
        make_user(username='l8_manager', role=UserRole.MANAGER, service=ServiceType.DRH,
                  allowed_services=[ServiceType.INFO], fullname='Manu MANAGER')
        make_user(username='l8_solver', role=UserRole.SOLVER, service=ServiceType.INFO,
                  allowed_services=[ServiceType.INFO], fullname='Sam SOLVER')
        make_user(username='l8_admin', role=UserRole.ADMIN, service=ServiceType.INFO,
                  allowed_services=[ServiceType.INFO], fullname='Alice ADMIN')
        make_user(username='l8_dir', role=UserRole.DIRECTEUR, service=ServiceType.DG,
                  allowed_services=[ServiceType.DG], fullname='Dan DIRECTEUR')


def _ticket(app, status, author='l8_user', service=ServiceType.INFO, **kw):
    with app.app_context():
        u = User.query.filter_by(username=author).first()
        t = make_ticket(u, service=service, status=status, **kw)
        return t.id


def _entries(action=None):
    q = AuditLog.query
    if action:
        q = q.filter_by(action=action)
    return q.order_by(AuditLog.id).all()


@pytest.fixture
def tmp_dirs(app, tmp_path):
    """Dossiers temporaires pour les uploads, les rapports et les journaux."""
    old = {k: app.config.get(k) for k in ('UPLOAD_FOLDER', 'REPORTS_DIR', 'REPORTS_SHARE_DIR', 'RGPD_LOG_DIR')}
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    app.config['REPORTS_DIR'] = str(tmp_path / 'rapports')
    app.config['REPORTS_SHARE_DIR'] = str(tmp_path / 'absent' / 'Rapports')  # partage non monté
    app.config['RGPD_LOG_DIR'] = str(tmp_path / 'backups')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    yield tmp_path
    for k, v in old.items():
        if v is None:
            app.config.pop(k, None)
        else:
            app.config[k] = v


# ===========================================================================
#  1. Journal d'audit
# ===========================================================================
class TestAuditLog:

    def test_validation_cree_une_entree(self, client, db_session, app):
        _users(app)
        tid = _ticket(app, TicketStatus.VALIDATION_N1)
        login(client, 'l8_manager')
        client.get(f'/tickets/manager/action/{tid}/validate')
        with app.app_context():
            t = Ticket.query.get(tid)
            assert t.status == TicketStatus.VALIDATION_N2
            e = _entries('ticket.validate')
            assert len(e) == 1
            assert e[0].username == 'l8_manager' and e[0].target_type == 'Ticket'
            assert e[0].target_id == tid and e[0].target_ref == t.uid_public
            assert e[0].user_id == User.query.filter_by(username='l8_manager').first().id
            assert e[0].timestamp is not None

    def test_refus_trace_le_motif(self, client, db_session, app):
        _users(app)
        tid = _ticket(app, TicketStatus.VALIDATION_N1)
        login(client, 'l8_manager')
        client.post(f'/tickets/manager/action/{tid}/refuse', data={'refusal_reason': 'Hors périmètre'})
        with app.app_context():
            e = _entries('ticket.refuse')
            assert len(e) == 1 and 'Hors périmètre' in e[0].details

    def test_validation_en_lot_trace_chaque_ticket(self, client, db_session, app):
        _users(app)
        a = _ticket(app, TicketStatus.VALIDATION_N1, title='A')
        b = _ticket(app, TicketStatus.VALIDATION_N1, title='B')
        login(client, 'l8_manager')
        client.post('/tickets/manager/batch_validate', data={'ticket_ids': [str(a), str(b)]})
        with app.app_context():
            assert sorted(e.target_id for e in _entries('ticket.validate')) == sorted([a, b])

    def test_cloture_cree_une_entree(self, client, db_session, app):
        _users(app)
        tid = _ticket(app, TicketStatus.IN_PROGRESS)
        with app.app_context():
            t = Ticket.query.get(tid)
            t.solver_id = User.query.filter_by(username='l8_solver').first().id
            db.session.commit()
        login(client, 'l8_solver')
        client.post(f'/tickets/solver/close/{tid}')
        with app.app_context():
            assert Ticket.query.get(tid).status == TicketStatus.DONE
            e = _entries('ticket.close')
            assert len(e) == 1 and e[0].username == 'l8_solver' and e[0].target_id == tid

    def test_prise_en_charge_et_transfert(self, client, db_session, app):
        _users(app)
        tid = _ticket(app, TicketStatus.PENDING)
        login(client, 'l8_solver')
        client.get(f'/tickets/solver/take/{tid}')
        client.post(f'/tickets/solver/transfer/{tid}', data={'target_service': 'DAF'})
        with app.app_context():
            assert len(_entries('ticket.assign')) == 1
            tr = _entries('ticket.transfer')
            assert len(tr) == 1 and 'INFORMATIQUE -> DAF' in tr[0].details

    def test_connexion_echouee_cree_une_entree_commitee(self, client, db_session, app):
        """LDAP injoignable en test => échec de connexion ; l'entrée est
        validée seule (commit=True) et sans user_id."""
        r = client.post('/auth/login', data={'username': 'inconnu', 'password': 'x'}, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            db.session.remove()
            e = _entries('auth.login_failed')
            assert len(e) == 1
            assert e[0].user_id is None and e[0].username is None
            assert 'inconnu' in e[0].details

    def test_log_action_n_echoue_jamais(self, app, db_session):
        with app.app_context():
            class Bizarre:
                @property
                def id(self):
                    raise RuntimeError("boum")
            assert log_action('test.bizarre', Bizarre()) is None
            # cible tuple, chaîne et None acceptées
            assert log_action('test.tuple', ('Chose', 42, 'REF-42')).target_ref == 'REF-42'
            assert log_action('test.str', 'juste-une-ref').target_ref == 'juste-une-ref'
            assert log_action('test.none', None).target_type is None
            # details trop long => tronqué, pas d'erreur
            e = log_action('test.long', None, details='x' * 2000)
            assert len(e.details) == 500
            db.session.rollback()

    def test_log_action_hors_session_ne_casse_pas_l_action(self, app, db_session, monkeypatch):
        with app.app_context():
            import app.audit as audit_mod

            def boom(*a, **k):
                raise RuntimeError("base indisponible")
            monkeypatch.setattr(audit_mod.db.session, 'add', boom)
            assert log_action('ticket.close', None) is None

    def test_page_admin_reservee(self, client, db_session, app):
        _users(app)
        login(client, 'l8_user')
        r = client.get('/admin/audit', follow_redirects=False)
        assert r.status_code == 302
        login(client, 'l8_manager')
        assert client.get('/admin/audit').status_code == 302
        login(client, 'l8_admin')
        assert client.get('/admin/audit').status_code == 200

    def test_filtres_et_pagination(self, client, db_session, app):
        _users(app)
        with app.app_context():
            m = User.query.filter_by(username='l8_manager').first()
            s = User.query.filter_by(username='l8_solver').first()
            for i in range(60):
                log_action('ticket.validate', ('Ticket', i, f'T-{i:03d}'), user=m)
            log_action('ticket.close', ('Ticket', 999, 'T-CLOSE'), user=s, details='fini')
            old = log_action('auth.login', None, user=s)
            old.timestamp = datetime(2020, 1, 15, 10, 0)
            db.session.commit()
        login(client, 'l8_admin')
        html = client.get('/admin/audit').data.decode()
        assert '62 entrées' in html and 'page 1 / 2' in html
        assert 'T-011' in html and 'T-010' not in html   # 50 par page : T-CLOSE + T-059..T-011
        html2 = client.get('/admin/audit?page=2').data.decode()
        assert 'page 2 / 2' in html2
        # filtre utilisateur
        html = client.get('/admin/audit?user=l8_solver').data.decode()
        assert '2 entrées' in html and 'T-CLOSE' in html
        # filtre action exacte et par domaine
        assert '1 entrée ' in client.get('/admin/audit?action=ticket.close').data.decode()
        assert '61 entrées' in client.get('/admin/audit?action=ticket.').data.decode()
        # filtre cible
        assert '1 entrée ' in client.get('/admin/audit?target=T-CLOSE').data.decode()
        # période
        html = client.get('/admin/audit?start=2020-01-01&end=2020-01-31').data.decode()
        assert '1 entrée ' in html and 'Connexion' in html

    def test_export_csv(self, client, db_session, app):
        _users(app)
        with app.app_context():
            m = User.query.filter_by(username='l8_manager').first()
            log_action('ticket.validate', ('Ticket', 1, 'T-CSV'), user=m, details='ok')
            log_action('ticket.close', ('Ticket', 2, 'T-AUTRE'), user=m)
            db.session.commit()
        login(client, 'l8_admin')
        r = client.get('/admin/audit/export.csv?action=ticket.validate')
        assert r.status_code == 200 and 'text/csv' in r.headers['Content-Type']
        body = r.data.decode('utf-8-sig')
        lines = [l for l in body.splitlines() if l]
        assert lines[0].startswith('Horodatage;Utilisateur;Action')
        assert len(lines) == 2 and 'T-CSV' in lines[1] and 'l8_manager' in lines[1]
        assert 'T-AUTRE' not in body

    def test_historique_sur_le_detail_du_ticket_equipe_seulement(self, client, db_session, app):
        _users(app)
        tid = _ticket(app, TicketStatus.VALIDATION_N1)
        login(client, 'l8_manager')
        client.get(f'/tickets/manager/action/{tid}/validate')
        with app.app_context():
            uid = Ticket.query.get(tid).uid_public
            assert len(history_for('Ticket', tid)) == 1
        login(client, 'l8_admin')
        html = client.get(f'/tickets/view/{uid}').data.decode()
        assert 'Historique' in html and 'Ticket validé' in html and 'l8_manager' in html
        login(client, 'l8_user')   # le demandeur ne voit pas le journal
        html = client.get(f'/tickets/view/{uid}').data.decode()
        assert 'Ticket validé' not in html

    def test_tuiles_du_hub_admin(self, client, db_session, app):
        _users(app)
        login(client, 'l8_admin')
        html = client.get('/admin/dashboard').data.decode()
        assert '/admin/audit' in html and '/admin/rapports' in html and '/admin/rgpd' in html


# ===========================================================================
#  2. Rapport mensuel
# ===========================================================================
def _seed_month(app, year=2026, month=8):
    """Jeu de données daté : 3 tickets INFO (2 clôturés, 1 refusé) et 1 DAF."""
    _users(app)
    with app.app_context():
        u = User.query.filter_by(username='l8_user').first()
        s = User.query.filter_by(username='l8_solver').first()
        base = datetime(year, month, 10, 9, 0)
        rows = [
            dict(service=ServiceType.INFO, status=TicketStatus.DONE, title='Imprimante', cat='Impression', assigned=2, closed=10, sat=3),
            dict(service=ServiceType.INFO, status=TicketStatus.DONE, title='Écran', cat='Matériel', assigned=4, closed=30, sat=1),
            dict(service=ServiceType.INFO, status=TicketStatus.REFUSED, title='Refusé', cat='Matériel', assigned=None, closed=None, sat=None),
            dict(service=ServiceType.DAF, status=TicketStatus.DONE, title='Bon', cat='Bon de Commande', assigned=1, closed=5, sat=None),
        ]
        for i, r in enumerate(rows):
            t = make_ticket(u, service=r['service'], status=r['status'], title=r['title'])
            t.category_ticket = r['cat']
            t.created_at = base + timedelta(days=i)
            if r['assigned'] is not None:
                t.assigned_at = t.created_at + timedelta(hours=r['assigned'])
                t.solver_id = s.id
            if r['closed'] is not None:
                t.closed_at = t.created_at + timedelta(hours=r['closed'])
            t.satisfaction = r['sat']
        # Un ticket du mois précédent (hors période, mais dans la série 12 mois)
        old = make_ticket(u, service=ServiceType.INFO, status=TicketStatus.DONE, title='Ancien')
        old.created_at = datetime(year, month - 1, 3); old.closed_at = datetime(year, month - 1, 4)
        db.session.commit()


class TestRapportMensuel:

    def test_donnees_et_html(self, app, db_session):
        _seed_month(app)
        with app.app_context():
            data = reporting.monthly_report_data(2026, 8)
            info = data['stats']['INFORMATIQUE']
            assert info['received'] == 3 and info['closed'] == 2
            assert info['assign_avg_h'] == 3.0 and info['close_avg_h'] == 20.0
            assert info['refusal_rate'] == 33.3
            assert info['satisfaction_count'] == 2 and info['satisfaction_pct'] == 50
            assert data['stats']['DAF']['received'] == 1
            assert data['totals'] == {'received': 4, 'closed': 3, 'refused': 1, 'rated': 2, 'satisfaction_pct': 50}
            assert len(data['series']) == 12 and data['series'][-1]['key'] == '2026-08'
            assert data['series'][-2] == {'key': '2026-07', 'label': 'juil. 26', 'received': 1, 'closed': 1}

            html = reporting.build_monthly_report(2026, 8)
            assert 'août 2026' in html and 'INFORMATIQUE' in html and 'DAF' in html
            assert 'Impression (1)' in html and 'Matériel (2)' in html
            assert '<svg' in html and 'data:image/png;base64' in html
            assert '33.3 %' in html

    def test_pdf_commence_par_pdf(self, app, db_session, tmp_dirs):
        _seed_month(app)
        with app.app_context():
            pdf = reporting.render_monthly_pdf(2026, 8)
            assert pdf[:5] == b'%PDF-' and len(pdf) > 1000
            path, pdf2, shared = reporting.generate_and_store(2026, 8)
            assert os.path.isfile(path) and path.endswith('rapport_2026-08.pdf')
            assert shared is None   # partage non monté => pas de copie, pas de dossier créé
            assert not os.path.exists(app.config['REPORTS_SHARE_DIR'])
            reports = reporting.list_reports()
            assert len(reports) == 1 and reports[0]['label'] == 'Août 2026'

    def test_mois_precedent_et_destinataires(self, app, db_session):
        _users(app)
        with app.app_context():
            assert reporting.previous_month(datetime(2026, 1, 15)) == (2025, 12)
            assert reporting.previous_month(datetime(2026, 9, 29)) == (2026, 8)
            assert sorted(reporting.report_recipients()) == ['l8_admin@test.lan', 'l8_dir@test.lan']

    def test_envoi_email_avec_piece_jointe(self, app, db_session, monkeypatch):
        _users(app)
        sent = {}
        with app.app_context():
            import app.reporting as rep
            from app import emails

            def fake_send(subject, recipients, text, html, kind='important', attachments=None):
                sent.update(subject=subject, recipients=recipients, kind=kind, attachments=attachments)
            monkeypatch.setattr(emails, 'send_email', fake_send)
            rep.send_monthly_report(2026, 8, b'%PDF-fake')
            assert sent['kind'] == 'digest' and 'août 2026' in sent['subject']
            assert sorted(sent['recipients']) == ['l8_admin@test.lan', 'l8_dir@test.lan']
            assert sent['attachments'] == [('rapport_2026-08.pdf', 'application/pdf', b'%PDF-fake')]

    def test_send_email_accepte_attachments(self, app, db_session):
        """Paramètre rétrocompatible : le Message flask_mail porte la pièce jointe."""
        from app import emails
        captured = {}
        with app.app_context():
            from threading import Thread
            orig_start = Thread.start
            Thread.start = lambda self: None   # pas d'envoi asynchrone réel
            try:
                real_message = emails.Message

                class SpyMessage(real_message):
                    def __init__(self, *a, **k):
                        super().__init__(*a, **k); captured['msg'] = self
                emails.Message = SpyMessage
                emails.send_email('S', ['x@test.lan'], 'txt', '<p>h</p>', kind='digest',
                                  attachments=[('r.pdf', 'application/pdf', b'%PDF-1')])
                emails.send_email('S2', ['x@test.lan'], 'txt', '<p>h</p>', kind='digest')  # sans le paramètre
            finally:
                emails.Message = real_message
                Thread.start = orig_start
        names = [a.filename for a in captured['msg'].attachments]
        assert 'logo.png' in names or 'r.pdf' in names

    def test_page_admin_rapports(self, client, db_session, app, tmp_dirs):
        _seed_month(app)
        login(client, 'l8_user')
        assert client.get('/admin/rapports').status_code == 302
        login(client, 'l8_admin')
        html = client.get('/admin/rapports').data.decode()
        assert 'Aucun rapport' in html and 'Générer' in html
        r = client.post('/admin/rapports', data={'month': '2026-08'}, follow_redirects=True)
        assert r.status_code == 200 and 'généré' in r.data.decode()
        html = client.get('/admin/rapports').data.decode()
        assert 'Août 2026' in html
        r = client.get('/admin/rapports/2026-8.pdf')
        assert r.status_code == 200 and r.data[:5] == b'%PDF-'
        assert client.get('/admin/rapports/2026-7.pdf').status_code == 404
        r = client.get('/admin/rapports/apercu/2026-8')
        assert r.status_code == 200 and b'INFORMATIQUE' in r.data
        with app.app_context():
            assert len(_entries('report.generate')) == 1
        r = client.post('/admin/rapports', data={'month': 'n-importe-quoi'}, follow_redirects=True)
        assert 'invalide' in r.data.decode()


# ===========================================================================
#  3. RGPD
# ===========================================================================
def _touch(path, content=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fp:
        fp.write(content)
    return path


def _seed_rgpd(app, now):
    """Jeu de données daté autour de `now` :
    - ticket ancien clos (4 ans) avec messages et pièces -> anonymisable
    - ticket récent clos (1 mois) -> intact
    - ticket ouvert très ancien -> intact (pas clos)
    - ticket DAF clos il y a 2 ans avec RIB -> RIB supprimé
    - ticket DAF clos il y a 2 mois avec RIB -> intact
    - FCPI terminé il y a 18 mois avec CV/photo (+ copie dans le ticket enfant)
    - soumission de formulaire terminée il y a 14 mois avec une pièce
    - 2 notifications lues (8 mois / 1 mois) + 1 non lue ancienne
    - compte 'dormant' (dernière activité 3 ans), compte 'valideur' inactif
      mais présent en validated_by, compte 'recent' actif, compte 'vierge'
    """
    _users(app)
    base = app.config['UPLOAD_FOLDER']
    ids = {}
    with app.app_context():
        u = User.query.filter_by(username='l8_user').first()
        solver = User.query.filter_by(username='l8_solver').first()
        dormant = make_user(username='dormant', role=UserRole.USER, service=ServiceType.MAS)
        valideur = make_user(username='valideur', role=UserRole.MANAGER, service=ServiceType.MAS)
        make_user(username='vierge', role=UserRole.USER, service=ServiceType.MAS)
        recent = make_user(username='recent', role=UserRole.USER, service=ServiceType.MAS)

        old = make_ticket(dormant, status=TicketStatus.DONE, title='Vieux ticket', description='Mon poste 0612345678')
        old.created_at = now - timedelta(days=4 * 365 + 10); old.closed_at = now - timedelta(days=4 * 365)
        old.tel_demandeur = '0612345678'; old.solver_id = solver.id; old.validated_by_id = valideur.id
        db.session.add(TicketMessage(content='msg perso', ticket=old, author=dormant, timestamp=old.closed_at))
        db.session.add(TicketMessage(content='réponse', ticket=old, author=solver, timestamp=old.closed_at))
        old.daf_files_json = json.dumps(['capture.png'])
        _touch(os.path.join(base, 'tickets', old.uid_public, 'capture.png'))

        recent_t = make_ticket(recent, status=TicketStatus.DONE, title='Récent')
        recent_t.created_at = now - timedelta(days=40); recent_t.closed_at = now - timedelta(days=30)

        open_old = make_ticket(u, status=TicketStatus.IN_PROGRESS, title='Ouvert ancien')
        open_old.created_at = now - timedelta(days=5 * 365)

        daf_old = make_ticket(u, service=ServiceType.DAF, status=TicketStatus.DONE, title='Bon ancien')
        daf_old.created_at = now - timedelta(days=740); daf_old.closed_at = now - timedelta(days=730)
        daf_old.daf_rib_file = 'RIB_old.pdf'
        _touch(os.path.join(base, 'tickets', daf_old.uid_public, 'RIB_old.pdf'))

        daf_new = make_ticket(u, service=ServiceType.DAF, status=TicketStatus.DONE, title='Bon récent')
        daf_new.created_at = now - timedelta(days=70); daf_new.closed_at = now - timedelta(days=60)
        daf_new.daf_rib_file = 'RIB_new.pdf'
        _touch(os.path.join(base, 'tickets', daf_new.uid_public, 'RIB_new.pdf'))

        child = make_ticket(u, service=ServiceType.DRH, status=TicketStatus.DONE, title='FCPI enfant')
        child.created_at = now - timedelta(days=540); child.closed_at = now - timedelta(days=530)
        child.daf_files_json = json.dumps(['cv.pdf', 'autre.pdf'])
        _touch(os.path.join(base, 'tickets', child.uid_public, 'cv.pdf'))
        _touch(os.path.join(base, 'tickets', child.uid_public, 'autre.pdf'))
        rec = Recruitment(uid_public='FCPI-OLD-001', author_id=u.id, status=RecruitmentStatus.DONE,
                          nom_agent='Durand', prenom_agent='Paul', file_cv='cv.pdf', file_photo='photo.jpg',
                          child_tickets_ids=json.dumps([child.id]))
        rec.created_at = now - timedelta(days=540)
        db.session.add(rec)
        _touch(os.path.join(base, 'fcpi', 'FCPI-OLD-001', 'cv.pdf'))
        _touch(os.path.join(base, 'fcpi', 'FCPI-OLD-001', 'photo.jpg'))

        fd = FormDefinition(slug='l8-form', name='Lot8', is_active=True)
        db.session.add(fd); db.session.flush()
        db.session.add(FormField(form_definition_id=fd.id, name='piece', label='Pièce', field_type=FormFieldType.FILE, order_index=1))
        sub = FormSubmission(uid_public='FRM-l8-1', form_definition_id=fd.id, author_id=u.id,
                             status=FormSubmissionStatus.DONE, data_json='{"nom": "Durand"}')
        db.session.add(sub); db.session.flush()
        db.session.add(FormSubmissionFile(submission_id=sub.id, field_name='piece', stored_filename='justif.pdf'))
        _touch(os.path.join(base, 'forms', 'l8-form', 'FRM-l8-1', 'justif.pdf'))
        db.session.flush()
        sub.created_at = now - timedelta(days=430)
        sub.updated_at = now - timedelta(days=425)

        n_old = make_notification(u, message='ancienne lue'); n_old.is_read = True; n_old.timestamp = now - timedelta(days=240)
        n_new = make_notification(u, message='récente lue'); n_new.is_read = True; n_new.timestamp = now - timedelta(days=30)
        n_unread = make_notification(u, message='ancienne non lue'); n_unread.timestamp = now - timedelta(days=400)
        make_notification(solver, message='activité récente').timestamp = now   # l8_solver reste actif

        # activité datée des comptes
        t_val = make_ticket(recent, status=TicketStatus.DONE, title='Validé par valideur')
        t_val.created_at = now - timedelta(days=3 * 365); t_val.closed_at = now - timedelta(days=3 * 365)
        t_val.validated_by_id = valideur.id
        db.session.add(TicketMessage(content='x', ticket=t_val, author=valideur, timestamp=now - timedelta(days=3 * 365)))
        db.session.commit()
        # updated_at : onupdate l'a peut-être écrasé au commit -> on force en SQL brut
        db.session.execute(db.text("UPDATE form_submissions SET updated_at=:d WHERE id=:i"),
                           {'d': now - timedelta(days=425), 'i': sub.id})
        db.session.commit()
        ids.update(old=old.id, recent=recent_t.id, open_old=open_old.id, daf_old=daf_old.id, daf_new=daf_new.id,
                   child=child.id, rec=rec.id, sub=sub.id, n_old=n_old.id, n_new=n_new.id, n_unread=n_unread.id,
                   dormant=dormant.id, valideur=valideur.id, old_uid=old.uid_public, child_uid=child.uid_public,
                   daf_old_uid=daf_old.uid_public, daf_new_uid=daf_new.uid_public)
    return ids


class TestRGPD:

    def test_plan_correct_sans_rien_modifier(self, app, db_session, tmp_dirs):
        now = datetime(2026, 9, 29, 12, 0)
        ids = _seed_rgpd(app, now)
        base = app.config['UPLOAD_FOLDER']
        with app.app_context():
            before_tickets = {t.id: (t.title, t.author_id) for t in Ticket.query.all()}
            n_msgs = TicketMessage.query.count()
            plan = rgpd.plan_purge(now)
            by_rule = {}
            for op in plan['operations']:
                by_rule.setdefault(op['rule'], []).append(op)

            assert [o['target_id'] for o in by_rule['anonymize_ticket']] == [ids['old']]
            assert by_rule['anonymize_ticket'][0]['target_ref'] == ids['old_uid']
            assert [o['target_id'] for o in by_rule['files_daf_rib']] == [ids['daf_old']]
            assert by_rule['files_daf_rib'][0]['files'] == [os.path.join(base, 'tickets', ids['daf_old_uid'], 'RIB_old.pdf')]
            fcpi = by_rule['files_fcpi'][0]
            assert fcpi['target_ref'] == 'FCPI-OLD-001' and len(fcpi['files']) == 3   # cv, photo + copie cv du ticket enfant
            subop = by_rule['files_submission'][0]
            assert subop['target_id'] == ids['sub'] and len(subop['files']) == 1
            assert 'anonymize_submission' not in by_rule          # 14 mois < 3 ans
            assert by_rule['notifications'][0]['count'] == 1      # seule l'ancienne lue
            assert [o['target_ref'] for o in by_rule['inactive_user']] == ['dormant']
            assert plan['counts']['anonymize_ticket'] == 1 and plan['counts']['inactive_user'] == 1
            assert 'files_sejour' not in by_rule

            # dry-run : rien n'a bougé
            assert {t.id: (t.title, t.author_id) for t in Ticket.query.all()} == before_tickets
            assert TicketMessage.query.count() == n_msgs
            assert Notification.query.count() == 4
            assert User.query.filter_by(username='dormant').first() is not None
            assert os.path.isfile(os.path.join(base, 'tickets', ids['daf_old_uid'], 'RIB_old.pdf'))
            assert os.path.isfile(os.path.join(base, 'fcpi', 'FCPI-OLD-001', 'cv.pdf'))
            assert AuditLog.query.filter_by(action='rgpd.purge').count() == 0
            assert not os.path.exists(app.config['RGPD_LOG_DIR'])

    def test_apply_applique_exactement_le_plan_et_journalise(self, app, db_session, tmp_dirs):
        now = datetime(2026, 9, 29, 12, 0)
        ids = _seed_rgpd(app, now)
        base = app.config['UPLOAD_FOLDER']
        with app.app_context():
            admin = User.query.filter_by(username='l8_admin').first()
            plan = rgpd.plan_purge(now)
            n_ops = len(plan['operations'])
            result = rgpd.apply_purge(plan, actor=admin)
            assert result['applied'] == n_ops
            # 1 capture du vieux ticket + RIB + cv/photo + copie cv (ticket enfant) + justif = 6
            assert result['files_removed'] == 6

            old = Ticket.query.get(ids['old'])
            assert old.title == '[Anonymisé]' and old.description == '[Anonymisé]'
            assert old.author_id is None and old.tel_demandeur is None and old.daf_files_json is None
            assert old.status == TicketStatus.DONE and old.closed_at is not None and old.target_service == ServiceType.INFO
            assert TicketMessage.query.filter_by(ticket_id=old.id).count() == 0
            assert not os.path.exists(os.path.join(base, 'tickets', ids['old_uid']))

            rec_t = Ticket.query.get(ids['recent'])
            assert rec_t.title == 'Récent' and rec_t.author_id is not None
            assert Ticket.query.get(ids['open_old']).title == 'Ouvert ancien'

            assert Ticket.query.get(ids['daf_old']).daf_rib_file is None
            assert not os.path.exists(os.path.join(base, 'tickets', ids['daf_old_uid'], 'RIB_old.pdf'))
            assert Ticket.query.get(ids['daf_new']).daf_rib_file == 'RIB_new.pdf'
            assert os.path.isfile(os.path.join(base, 'tickets', ids['daf_new_uid'], 'RIB_new.pdf'))

            rec = Recruitment.query.get(ids['rec'])
            assert rec.file_cv is None and rec.file_photo is None and rec.nom_agent == 'Durand'
            assert not os.path.exists(os.path.join(base, 'fcpi', 'FCPI-OLD-001', 'cv.pdf'))
            child = Ticket.query.get(ids['child'])
            assert child.get_daf_files() == ['autre.pdf']
            assert not os.path.exists(os.path.join(base, 'tickets', ids['child_uid'], 'cv.pdf'))
            assert os.path.isfile(os.path.join(base, 'tickets', ids['child_uid'], 'autre.pdf'))

            sub = FormSubmission.query.get(ids['sub'])
            assert sub.files == [] and sub.get_data() == {'nom': 'Durand'}   # pièces supprimées, données gardées (< 3 ans)
            assert not os.path.exists(os.path.join(base, 'forms', 'l8-form', 'FRM-l8-1', 'justif.pdf'))

            assert Notification.query.get(ids['n_old']) is None
            assert Notification.query.get(ids['n_new']) is not None and Notification.query.get(ids['n_unread']) is not None

            assert User.query.filter_by(username='dormant').first() is None
            for name in ('valideur', 'vierge', 'recent', 'l8_user', 'l8_admin'):
                assert User.query.filter_by(username=name).first() is not None, name

            audit = AuditLog.query.filter_by(action='rgpd.purge').all()
            assert len(audit) == 1 and audit[0].username == 'l8_admin' and f"{n_ops} opération(s)" in audit[0].details
            assert result['log_path'] and os.path.basename(result['log_path']) == 'rgpd_2026-09-29.log'
            log = open(result['log_path'], encoding='utf-8').read()
            assert ids['old_uid'] in log and 'FCPI-OLD-001' in log and 'dormant' in log
            assert '0612345678' not in log and 'Durand' not in log   # aucune donnée personnelle

            # Idempotent : un second plan est vide
            assert rgpd.plan_purge(now)['operations'] == []

    def test_page_admin_rgpd_et_confirmation(self, client, db_session, app, tmp_dirs):
        now = datetime.now()
        ids = _seed_rgpd(app, now)
        login(client, 'l8_user')
        assert client.get('/admin/rgpd').status_code == 302
        login(client, 'l8_admin')
        html = client.get('/admin/rgpd').data.decode()
        assert 'Anonymisation des tickets' in html and ids['old_uid'] in html and 'dormant' in html
        assert 'PURGER' in html
        # mauvaise confirmation : rien ne bouge
        r = client.post('/admin/rgpd', data={'confirm1': 'PURGER', 'confirm2': 'purger'}, follow_redirects=True)
        assert 'Confirmation incorrecte' in r.data.decode()
        with app.app_context():
            assert Ticket.query.get(ids['old']).title == 'Vieux ticket'
        # double saisie correcte : purge exécutée
        r = client.post('/admin/rgpd', data={'confirm1': 'PURGER', 'confirm2': 'PURGER'}, follow_redirects=True)
        assert 'Purge exécutée' in r.data.decode()
        with app.app_context():
            assert Ticket.query.get(ids['old']).title == '[Anonymisé]'
            assert AuditLog.query.filter_by(action='rgpd.purge').count() == 1
        html = client.get('/admin/rgpd').data.decode()
        assert 'Rien à purger' in html and 'Dernières purges' in html

    def test_scripts_dry_run_par_defaut(self):
        """Le script CLI est en simulation sans option et documente son cron."""
        src = open(os.path.join(os.path.dirname(__file__), 'scripts', 'purge_rgpd.py'), encoding='utf-8').read()
        assert '--apply' in src and 'if not args.apply' in src and '0 3 2 * *' in src
        src2 = open(os.path.join(os.path.dirname(__file__), 'scripts', 'rapport_mensuel.py'), encoding='utf-8').read()
        assert '0 6 1 * *' in src2 and 'previous_month' in src2
