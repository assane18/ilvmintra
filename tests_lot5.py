#!/usr/bin/env python3
"""
=============================================================================
 TESTS — LOT 5 : délais et pilotage
   1. Statistiques de respect des délais (SLA) : tickets.py::_compute_stats,
      tuile « Respect des délais » et export Excel.
   2. Escalade automatique des validations en souffrance : app/pilotage.py
      (seuils, destinataires, anti-doublon, rien sous le seuil), page
      /admin/pilotage (AppSetting).
   3. Bandeau d'état du portail (santé simulée, masquage admin, cache).
   4. Vérification de la sauvegarde : app/pilotage.py::check_backup_state.
=============================================================================
 Base SQLite en mémoire (fixtures reprises de tests_intranet.py). Les envois
 d'e-mail sont interceptés par monkeypatch : aucun e-mail réel.

 Usage :
   cd /var/www/intranet && source venv/bin/activate
   python -m pytest tests_lot5.py -v
=============================================================================
"""
import io
import os
import sys
import json
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['FLASK_ENV'] = 'testing'
os.environ['FLASK_DEBUG'] = '0'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from tests_intranet import app, client, db_session, make_user, login, make_ticket  # noqa: E402,F401
from app import db  # noqa: E402
from app.models import (User, UserRole, Ticket, TicketStatus, ServiceType, ServiceSource,  # noqa: E402
                        SlaRule, AppSetting, EscalationTrace, FormDefinition, FormWorkflowStep,
                        FormSubmission, FormSubmissionStatus)
from app import pilotage  # noqa: E402
from app.routes.tickets import _compute_stats, _empty_stats_entry  # noqa: E402


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _closed_ticket(author, service, category, created_at, hours_to_close, uid):
    """Ticket clôturé : created_at donné, closed_at = created_at + hours_to_close."""
    t = Ticket(uid_public=uid, title=f'T {uid}', description='d', author_id=author.id,
               target_service=service, status=TicketStatus.DONE, category_ticket=category,
               created_at=created_at, closed_at=created_at + timedelta(hours=hours_to_close),
               service_demandeur=author.service)
    db.session.add(t)
    return t


def _pending_ticket(author, days_old, uid, status=TicketStatus.VALIDATION_N1, service=ServiceType.INFO):
    t = Ticket(uid_public=uid, title=f'Attente {uid}', description='d', author_id=author.id,
               target_service=service, status=status, category_ticket='STANDARD',
               created_at=datetime.now() - timedelta(days=days_old), service_demandeur=author.service)
    db.session.add(t)
    return t


@pytest.fixture
def sent_mails(monkeypatch):
    """Intercepte app.emails.send_email (importé tardivement par app/pilotage.py)."""
    calls = []

    def fake_send_email(subject, recipients, text_body, html_body, kind='important'):
        calls.append({'subject': subject, 'recipients': list(recipients), 'text': text_body,
                      'html': html_body, 'kind': kind})
    monkeypatch.setattr('app.emails.send_email', fake_send_email)
    return calls


@pytest.fixture(autouse=True)
def _reset_health_cache():
    pilotage.reset_health_cache()
    yield
    pilotage.reset_health_cache()


# ===========================================================================
#  1. Statistiques de respect des délais (SLA)
# ===========================================================================

class TestStatsSla:

    def _seed(self):
        author = make_user(username='auteur_sla', service=ServiceType.INFO)
        # Règles : INFORMATIQUE 8 h par défaut, « Demande Matériel » 120 h
        db.session.add(SlaRule(service='INFORMATIQUE', category=None, hours=8))
        db.session.add(SlaRule(service='INFORMATIQUE', category='Demande Matériel', hours=120))
        db.session.commit()
        base = datetime.now().replace(day=15, hour=10, minute=0, second=0, microsecond=0)
        _closed_ticket(author, ServiceType.INFO, 'Incident', base, 4, 'S-001')            # dans le délai (4 <= 8)
        _closed_ticket(author, ServiceType.INFO, 'Incident', base, 12, 'S-002')           # hors délai
        _closed_ticket(author, ServiceType.INFO, 'Incident', base, 30, 'S-003')           # hors délai
        _closed_ticket(author, ServiceType.INFO, 'Demande Matériel', base, 100, 'S-004')  # dans le délai (100 <= 120)
        _closed_ticket(author, ServiceType.INFO, 'Logiciel', base, 9, 'S-005')            # hors délai (9 > 8)
        # Mois précédent : 1 dans le délai, 0 hors délai
        prev = (base.replace(day=1) - timedelta(days=1)).replace(day=10)
        _closed_ticket(author, ServiceType.INFO, 'Incident', prev, 2, 'S-006')
        db.session.commit()
        return base, prev

    def test_taux_et_top_categories_hors_delai(self, db_session):
        base, prev = self._seed()
        start = base.replace(day=1, hour=0)
        end = base + timedelta(days=10)  # les clôtures à +30 h et +100 h restent dans le mois
        stats = _compute_stats(['INFORMATIQUE'], start, end, start - timedelta(days=365), end)
        s = stats['INFORMATIQUE']
        assert s['closed'] == 5
        assert s['sla_on_time'] == 2
        assert s['sla_late'] == 3
        assert s['sla_rate'] == 40.0
        assert s['sla_top_late_categories'][0] == ('Incident', 2)
        assert ('Logiciel', 1) in s['sla_top_late_categories']
        # Les clés historiques restent présentes
        for k in _empty_stats_entry():
            assert k in s

    def test_evolution_mensuelle(self, db_session):
        base, prev = self._seed()
        start = base.replace(day=1, hour=0)
        end = base + timedelta(days=10)  # les clôtures à +30 h et +100 h restent dans le mois
        stats = _compute_stats(['INFORMATIQUE'], start, end, prev.replace(day=1, hour=0), end)
        monthly = stats['INFORMATIQUE']['monthly']
        cur, old = base.strftime('%Y-%m'), prev.strftime('%Y-%m')
        assert monthly[old]['closed'] == 1 and monthly[old]['sla_rate'] == 100.0 and monthly[old]['sla_late'] == 0
        assert monthly[cur]['closed'] == 5 and monthly[cur]['sla_rate'] == 40.0 and monthly[cur]['sla_late'] == 3
        # Le mois précédent est hors période KPI : le taux global ne le compte pas
        assert stats['INFORMATIQUE']['sla_rate'] == 40.0

    def test_sans_cloture_taux_none(self, db_session):
        author = make_user(username='auteur_vide')
        make_ticket(author, status=TicketStatus.PENDING)
        now = datetime.now()
        stats = _compute_stats(None, now - timedelta(days=30), now, now - timedelta(days=365), now)
        s = stats['INFORMATIQUE']
        assert s['received'] == 1 and s['sla_rate'] is None and s['sla_late'] == 0
        assert _empty_stats_entry()['sla_rate'] is None

    def test_tuile_dashboard_et_export(self, client, db_session):
        self._seed()
        make_user(role=UserRole.ADMIN, username='admin_sla')
        login(client, 'admin_sla')
        r = client.get('/tickets/stats?period=this_month')
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'Respect des délais' in html
        assert 'data-testid="sla-rate">40.0%' in html
        assert 'text-red-600' in html  # 40 % < 70 % → rouge
        assert 'Catégories hors délai' in html
        assert 'slaChart_1' in html

        r = client.get('/tickets/stats/export?period=this_month')
        assert r.status_code == 200
        import pandas as pd
        xls = pd.ExcelFile(io.BytesIO(r.data))
        df = pd.read_excel(xls, 'Résumé')
        for col in ('Taux_Respect_Delais_%', 'Tickets_Dans_Delai', 'Tickets_Hors_Delai', 'Top_Hors_Delai_1'):
            assert col in df.columns
        row = df[df['Service'] == 'INFORMATIQUE'].iloc[0]
        assert row['Tickets_Hors_Delai'] == 3 and row['Top_Hors_Delai_1'] == 'Incident'
        dm = pd.read_excel(xls, 'Evolution_Mensuelle')
        assert 'Taux_Respect_Delais_%' in dm.columns
        detail = pd.read_excel(xls, 'Détail_INFORMATIQUE')
        assert 'Delai_Cible_h' in detail.columns and 'Dans_Delai' in detail.columns
        assert set(detail['Dans_Delai']) == {'Oui', 'Non'}


# ===========================================================================
#  2. Escalade des validations en souffrance
# ===========================================================================

class TestEscaladeLogiquePure:

    def test_niveaux(self):
        now = datetime(2026, 9, 29, 8, 10)
        lvl = pilotage.escalation_level
        assert lvl(now - timedelta(days=1), now, 3, 5) is None
        assert lvl(now - timedelta(days=3), now, 3, 5) is None          # exactement 3 j : pas « plus de »
        assert lvl(now - timedelta(days=3, hours=1), now, 3, 5) == 'rappel'
        assert lvl(now - timedelta(days=5, minutes=1), now, 3, 5) == 'directeur'
        assert lvl(now - timedelta(days=10), now, 0, 5) == 'directeur'  # rappel désactivé
        assert lvl(now - timedelta(days=10), now, 3, 0) == 'rappel'     # escalade désactivée
        assert lvl(None, now, 3, 5) is None

    def test_plan_anti_doublon(self):
        now = datetime(2026, 9, 29, 8, 10)
        items = [
            {'key': ('ticket', 1), 'created_at': now - timedelta(days=4)},
            {'key': ('ticket', 2), 'created_at': now - timedelta(days=6)},
            {'key': ('ticket', 3), 'created_at': now - timedelta(days=1)},
        ]
        planned = pilotage.plan_escalations(items, now, 3, 5)
        assert [(i['key'], l) for i, l in planned] == [(('ticket', 1), 'rappel'), (('ticket', 2), 'directeur')]
        planned = pilotage.plan_escalations(items, now, 3, 5, already_sent={(('ticket', 1), 'rappel')})
        assert [(i['key'], l) for i, l in planned] == [(('ticket', 2), 'directeur')]


class TestEscaladeIntegration:

    def _people(self):
        author = make_user(username='demandeur', service=ServiceType.INFO)
        mgr = make_user(role=UserRole.MANAGER, username='mgr_info', service=ServiceType.INFO)
        director = make_user(role=UserRole.DIRECTEUR, username='dir_info', service=ServiceType.INFO)
        make_user(role=UserRole.DIRECTEUR, username='dir_daf', service=ServiceType.DAF)  # autre service : jamais alerté
        return author, mgr, director

    def test_rien_sous_le_seuil(self, db_session, sent_mails):
        author, mgr, director = self._people()
        _pending_ticket(author, 2, 'E-001')
        db.session.commit()
        summary = pilotage.run_escalations(now=datetime.now(), base_url='http://intra')
        assert summary['rappel'] == 0 and summary['directeur'] == 0 and summary['emails'] == 0
        assert sent_mails == []
        assert EscalationTrace.query.count() == 0

    def test_rappel_aux_validateurs(self, db_session, sent_mails):
        author, mgr, director = self._people()
        _pending_ticket(author, 4, 'E-002')
        db.session.commit()
        summary = pilotage.run_escalations(now=datetime.now(), base_url='http://intra')
        assert summary['rappel'] == 1 and summary['directeur'] == 0
        # Manager ET Directeur du service INFO sont éligibles à la validation N1 → un e-mail chacun
        rcpts = sorted(r for m in sent_mails for r in m['recipients'])
        assert rcpts == sorted([mgr.email, director.email])
        assert all(m['kind'] == 'digest' for m in sent_mails)
        assert all('Rappel' in m['subject'] and 'escalad' not in m['subject'].lower() for m in sent_mails)
        assert 'E-002' in sent_mails[0]['html'] and 'http://intra/tickets/view/E-002' in sent_mails[0]['html']
        trace = EscalationTrace.query.one()
        assert trace.level == 'rappel' and trace.item_type == 'ticket' and trace.sent_on == datetime.now().date()

    def test_escalade_directeur_avec_copie_manager(self, db_session, sent_mails):
        author, mgr, director = self._people()
        _pending_ticket(author, 6, 'E-003')
        db.session.commit()
        summary = pilotage.run_escalations(now=datetime.now(), base_url='http://intra')
        assert summary['directeur'] == 1 and summary['rappel'] == 0
        rcpts = sorted(r for m in sent_mails for r in m['recipients'])
        assert rcpts == sorted([mgr.email, director.email])
        assert 'dir_daf@test.lan' not in rcpts
        assert all('Escaladé' in m['subject'] for m in sent_mails)
        assert all('escaladé' in m['html'].lower() for m in sent_mails)
        assert EscalationTrace.query.filter_by(level='directeur').count() == 1

    def test_anti_doublon_meme_jour_puis_lendemain(self, db_session, sent_mails):
        author, mgr, director = self._people()
        _pending_ticket(author, 3.5, 'E-004')  # 3,5 j : rappel aujourd'hui, encore rappel demain (4,5 j < 5)
        db.session.commit()
        now = datetime.now()
        s1 = pilotage.run_escalations(now=now, base_url='http://intra')
        assert s1['rappel'] == 1 and len(sent_mails) == 2
        s2 = pilotage.run_escalations(now=now + timedelta(hours=2), base_url='http://intra')
        assert s2['rappel'] == 0 and s2['emails'] == 0 and len(sent_mails) == 2
        # Le lendemain : nouveau rappel autorisé
        s3 = pilotage.run_escalations(now=now + timedelta(days=1), base_url='http://intra')
        assert s3['rappel'] == 1 and len(sent_mails) == 4
        assert EscalationTrace.query.count() == 2

    def test_seuils_depuis_app_setting(self, db_session, sent_mails):
        author, mgr, director = self._people()
        _pending_ticket(author, 4, 'E-005')
        db.session.commit()
        pilotage.set_setting('escalade_rappel_jours', 10)
        pilotage.set_setting('escalade_directeur_jours', 20)
        assert pilotage.run_escalations(now=datetime.now(), base_url='http://intra')['emails'] == 0
        pilotage.set_setting('escalade_directeur_jours', 2)
        s = pilotage.run_escalations(now=datetime.now(), base_url='http://intra')
        assert s['directeur'] == 1

    def test_un_email_par_destinataire_regroupe(self, db_session, sent_mails):
        author, mgr, director = self._people()
        _pending_ticket(author, 4, 'E-006')
        _pending_ticket(author, 7, 'E-007')
        db.session.commit()
        pilotage.run_escalations(now=datetime.now(), base_url='http://intra')
        assert len(sent_mails) == 2  # un par personne, pas un par demande
        for m in sent_mails:
            assert 'E-006' in m['html'] and 'E-007' in m['html']
            assert 'Escaladé' in m['subject']

    def test_dry_run_ne_trace_rien(self, db_session, sent_mails):
        author, mgr, director = self._people()
        _pending_ticket(author, 4, 'E-008')
        db.session.commit()
        s = pilotage.run_escalations(now=datetime.now(), dry_run=True, base_url='http://intra')
        assert s['rappel'] == 1 and sent_mails == [] and EscalationTrace.query.count() == 0

    def test_soumission_formulaire_en_attente(self, db_session, sent_mails):
        author, mgr, director = self._people()
        form = FormDefinition(slug='demande-lot5', name='Demande Lot 5', is_active=True, created_by=mgr)
        db.session.add(form); db.session.flush()
        db.session.add(FormWorkflowStep(form_definition_id=form.id, order_index=0, label='Validation Manager',
                                        service_source=ServiceSource.EMITTER))
        sub = FormSubmission(uid_public='FRM-lot5-001', form_definition_id=form.id, author_id=author.id,
                             status=FormSubmissionStatus.IN_PROGRESS, current_step_index=0,
                             created_at=datetime.now() - timedelta(days=4))
        db.session.add(sub); db.session.commit()
        s = pilotage.run_escalations(now=datetime.now(), base_url='http://intra')
        assert s['rappel'] == 1
        assert 'FRM-lot5-001' in sent_mails[0]['html'] and f'/forms/submission/{sub.id}' in sent_mails[0]['html']
        assert EscalationTrace.query.filter_by(item_type='submission', item_id=sub.id).count() == 1


class TestPageAdminPilotage:

    def test_defauts_et_acces(self, client, db_session):
        assert pilotage.get_setting_int('escalade_rappel_jours') == 3
        assert pilotage.get_setting_int('escalade_directeur_jours') == 5
        assert pilotage.get_setting_float('sauvegarde_espace_min_go') == 5.0
        assert pilotage.get_setting('bandeau_etat_masque') == '0'
        make_user(username='simple')
        login(client, 'simple')
        r = client.get('/admin/pilotage')
        assert r.status_code == 302  # non admin : redirigé
        make_user(role=UserRole.ADMIN, username='admin_pil')
        login(client, 'admin_pil')
        r = client.get('/admin/pilotage')
        assert r.status_code == 200
        assert 'Pilotage' in r.get_data(as_text=True)

    def test_modification_parametres(self, client, db_session):
        make_user(role=UserRole.ADMIN, username='admin_pil2')
        login(client, 'admin_pil2')
        r = client.post('/admin/pilotage', data={'escalade_rappel_jours': '2', 'escalade_directeur_jours': '4',
                                                 'sauvegarde_espace_min_go': '10', 'bandeau_etat_masque': '1'},
                        follow_redirects=True)
        assert r.status_code == 200
        assert pilotage.get_setting_int('escalade_rappel_jours') == 2
        assert pilotage.get_setting_int('escalade_directeur_jours') == 4
        assert pilotage.get_setting_float('sauvegarde_espace_min_go') == 10.0
        assert pilotage.get_setting('bandeau_etat_masque') == '1'
        # Valeur invalide : rien n'est modifié
        r = client.post('/admin/pilotage', data={'escalade_rappel_jours': 'abc', 'escalade_directeur_jours': '4',
                                                 'sauvegarde_espace_min_go': '10'}, follow_redirects=True)
        assert pilotage.get_setting_int('escalade_rappel_jours') == 2
        assert pilotage.get_setting('bandeau_etat_masque') == '1'
        # Décocher masque le bandeau → '0'
        client.post('/admin/pilotage', data={'escalade_rappel_jours': '2', 'escalade_directeur_jours': '4',
                                             'sauvegarde_espace_min_go': '10'}, follow_redirects=True)
        assert pilotage.get_setting('bandeau_etat_masque') == '0'
        # Le hub admin propose la carte
        r = client.get('/admin/dashboard')
        assert '/admin/pilotage' in r.get_data(as_text=True)


# ===========================================================================
#  3. Bandeau d'état du portail
# ===========================================================================

HEALTH_OK = {'db': {'ok': True}, 'ldap': {'ok': True}, 'mail': {'ok': True},
             'backup': {'stale': False}, 'backup_share': {'mounted': True}, 'disk': {'percent_used': 40}}


class TestBandeauEtat:

    def test_traduction_non_technique(self):
        assert pilotage.health_notices_from(HEALTH_OK) == []
        h = dict(HEALTH_OK, mail={'ok': False, 'error': 'Connection refused 10.0.0.1:25'})
        msgs = pilotage.health_notices_from(h)
        assert msgs == ["La messagerie est perturbée, les notifications par e-mail peuvent être retardées."]
        assert '10.0.0.1' not in ' '.join(msgs)
        h = dict(HEALTH_OK, ldap={'ok': False}, backup_share={'mounted': False}, disk={'percent_used': 95})
        msgs = pilotage.health_notices_from(h)
        assert len(msgs) == 3
        assert any('annuaire' in m.lower() for m in msgs)
        assert any('sauvegarde' in m.lower() for m in msgs)
        assert any('stockage' in m.lower() for m in msgs)
        # Sauvegarde trop ancienne signalée même si le partage est monté
        assert len(pilotage.health_notices_from(dict(HEALTH_OK, backup={'stale': True}))) == 1

    def test_cache_60s(self, db_session):
        calls = []

        def fake_health():
            calls.append(1)
            return dict(HEALTH_OK, mail={'ok': False})
        t0 = datetime(2026, 9, 29, 9, 0, 0)
        n1 = pilotage.portal_health_notice(now=t0, health_fn=fake_health)
        n2 = pilotage.portal_health_notice(now=t0 + timedelta(seconds=30), health_fn=fake_health)
        assert n1 and n2 and len(calls) == 1
        pilotage.portal_health_notice(now=t0 + timedelta(seconds=61), health_fn=fake_health)
        assert len(calls) == 2

    def test_masque_par_admin(self, db_session):
        fake = lambda: dict(HEALTH_OK, mail={'ok': False})  # noqa: E731
        assert pilotage.portal_health_notice(health_fn=fake) is not None
        pilotage.set_setting('bandeau_etat_masque', '1')
        assert pilotage.portal_health_notice(health_fn=fake) is None
        pilotage.set_setting('bandeau_etat_masque', '0')
        assert pilotage.portal_health_notice(health_fn=fake) is not None

    def test_health_en_erreur_ne_casse_pas(self, db_session):
        def boom():
            raise RuntimeError('ldap explose')
        assert pilotage.portal_health_notice(health_fn=boom) is None

    def test_portail_affiche_puis_masque(self, client, db_session, monkeypatch):
        make_user(username='agent')
        login(client, 'agent')
        monkeypatch.setattr('app.health.get_full_health', lambda: dict(HEALTH_OK, mail={'ok': False}))
        r = client.get('/portal')
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert 'id="health-notice"' in html
        assert 'La messagerie est perturbée' in html
        assert 'Masquer ce bandeau' not in html  # lien réservé à l'admin

        pilotage.set_setting('bandeau_etat_masque', '1')
        r = client.get('/portal')
        assert 'id="health-notice"' not in r.get_data(as_text=True)

        pilotage.set_setting('bandeau_etat_masque', '0')
        pilotage.reset_health_cache()
        monkeypatch.setattr('app.health.get_full_health', lambda: dict(HEALTH_OK))
        r = client.get('/portal')
        assert 'id="health-notice"' not in r.get_data(as_text=True)

    def test_lien_masquer_pour_admin(self, client, db_session, monkeypatch):
        make_user(role=UserRole.ADMIN, username='admin_band')
        login(client, 'admin_band')
        monkeypatch.setattr('app.health.get_full_health', lambda: dict(HEALTH_OK, ldap={'ok': False}))
        html = client.get('/portal').get_data(as_text=True)
        assert 'id="health-notice"' in html and 'Masquer ce bandeau' in html and '/admin/pilotage' in html


# ===========================================================================
#  4. Vérification de la sauvegarde
# ===========================================================================

def _touch(path, size=10, age_hours=1.0, now=None):
    now = now or datetime.now()
    with open(path, 'wb') as f:
        f.write(b'x' * size)
    ts = (now - timedelta(hours=age_hours)).timestamp()
    os.utime(path, (ts, ts))


class TestVerifSauvegarde:

    def _dirs(self, tmp_path):
        local = tmp_path / 'backups'; remote = tmp_path / 'share' / 'Backups_Intranet'
        local.mkdir(); remote.mkdir(parents=True)
        return str(local), str(remote), str(tmp_path / 'share')

    def test_tout_ok_aucune_anomalie(self, tmp_path):
        local, remote, mount = self._dirs(tmp_path)
        now = datetime.now()
        for name in ('intranet_db_2026-09-29.sql.gz', 'uploads_2026-09-29.tar.gz'):
            _touch(os.path.join(local, name), age_hours=5, now=now)
            _touch(os.path.join(remote, name), age_hours=5, now=now)
        anomalies, details = pilotage.check_backup_state(local, remote, mount, now=now, min_free_gb=5,
                                                         is_mounted=True, free_gb=120.0)
        assert anomalies == []
        assert details['mounted'] is True and details['free_gb'] == 120.0
        assert set(details['local']) == {'base de données', 'fichiers joints'}

    def test_fichiers_absents(self, tmp_path):
        local, remote, mount = self._dirs(tmp_path)
        anomalies, _ = pilotage.check_backup_state(local, remote, mount, is_mounted=True, free_gb=50)
        assert len(anomalies) == 2
        assert all('Aucune sauvegarde locale' in a for a in anomalies)

    def test_fichier_vieux_et_vide(self, tmp_path):
        local, remote, mount = self._dirs(tmp_path)
        now = datetime.now()
        _touch(os.path.join(local, 'intranet_db_2026-09-27.sql.gz'), age_hours=40, now=now)  # trop vieux
        _touch(os.path.join(local, 'uploads_2026-09-29.tar.gz'), size=0, age_hours=2, now=now)  # vide
        _touch(os.path.join(remote, 'intranet_db_2026-09-27.sql.gz'), age_hours=40, now=now)
        _touch(os.path.join(remote, 'uploads_2026-09-29.tar.gz'), age_hours=2, now=now)
        anomalies, _ = pilotage.check_backup_state(local, remote, mount, now=now, max_age_hours=26,
                                                   is_mounted=True, free_gb=50)
        assert any('date de 40 h' in a and 'base de données' in a for a in anomalies)
        assert any('est vide' in a and 'fichiers joints' in a for a in anomalies)
        assert len(anomalies) == 2

    def test_partage_non_monte_ou_copie_absente(self, tmp_path):
        local, remote, mount = self._dirs(tmp_path)
        now = datetime.now()
        _touch(os.path.join(local, 'intranet_db_2026-09-29.sql.gz'), now=now)
        _touch(os.path.join(local, 'uploads_2026-09-29.tar.gz'), now=now)
        anomalies, details = pilotage.check_backup_state(local, remote, mount, now=now, is_mounted=False, free_gb=50)
        assert anomalies == [f"Le partage de sauvegarde {mount} n'est pas monté : aucune copie hors de la VM."]
        # Monté mais copie distante absente pour les uploads
        _touch(os.path.join(remote, 'intranet_db_2026-09-29.sql.gz'), now=now)
        anomalies, _ = pilotage.check_backup_state(local, remote, mount, now=now, is_mounted=True, free_gb=50)
        assert len(anomalies) == 1 and 'copie distante de la fichiers joints' in anomalies[0]

    def test_espace_faible(self, tmp_path):
        local, remote, mount = self._dirs(tmp_path)
        now = datetime.now()
        for name in ('intranet_db_2026-09-29.sql.gz', 'uploads_2026-09-29.tar.gz'):
            _touch(os.path.join(local, name), now=now); _touch(os.path.join(remote, name), now=now)
        anomalies, _ = pilotage.check_backup_state(local, remote, mount, now=now, min_free_gb=5,
                                                   is_mounted=True, free_gb=3.2)
        assert anomalies == ["Espace libre sur le partage de sauvegarde : 3.2 Go, sous le seuil de 5 Go."]
        # Espace réel mesuré sur le répertoire distant quand free_gb n'est pas injecté
        anomalies, details = pilotage.check_backup_state(local, remote, mount, now=now, min_free_gb=0,
                                                         is_mounted=True)
        assert anomalies == [] and details['free_gb'] is not None

    def test_alerte_groupee_aux_admins(self, db_session, sent_mails):
        make_user(role=UserRole.ADMIN, username='admin_a')
        make_user(role=UserRole.ADMIN, username='admin_b')
        make_user(role=UserRole.MANAGER, username='pas_admin')
        rcpts = pilotage.admin_emails()
        assert rcpts == ['admin_a@test.lan', 'admin_b@test.lan']
        pilotage.send_backup_alert(['Anomalie 1', 'Anomalie 2'], {'mounted': False, 'free_gb': None}, rcpts)
        assert len(sent_mails) == 1
        m = sent_mails[0]
        assert m['kind'] == 'digest' and sorted(m['recipients']) == rcpts
        assert '2 anomalie(s)' in m['subject'] and 'Anomalie 2' in m['html']


# ===========================================================================
#  Modèles / migration
# ===========================================================================

def test_modeles_lot5(db_session):
    db.session.add(AppSetting(key='x', value='1')); db.session.commit()
    assert AppSetting.query.get('x').value == '1'
    t = EscalationTrace(item_type='ticket', item_id=1, level='rappel', sent_on=datetime.now().date())
    db.session.add(t); db.session.commit()
    from sqlalchemy.exc import IntegrityError
    db.session.add(EscalationTrace(item_type='ticket', item_id=1, level='rappel', sent_on=datetime.now().date()))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_migration_lot5_coherente():
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations', 'versions', 'a5a5a5a5a5a5_lot5_pilotage.py')
    spec = importlib.util.spec_from_file_location('mig_lot5', path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    assert mod.revision == 'a5a5a5a5a5a5' and mod.down_revision == 'e4c7d9a2b6f1'
