"""Lot 8 — pages d'administration « Reporting et conformité » :
  /admin/audit          journal d'audit (filtres, pagination, export CSV)
  /admin/rapports       rapports mensuels PDF (liste, téléchargement, génération)
  /admin/rgpd           plan de purge RGPD (aperçu) + exécution confirmée
Toutes réservées aux ADMIN. Fournit aussi le global Jinja `audit_history`
utilisé par tickets/_audit_history.html (détail d'un ticket, équipe uniquement).
"""
import csv
import io
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   make_response, send_file, abort, current_app)
from flask_login import login_required, current_user

from app import db
from app.decorators import admin_required
from app.models import AuditLog
from app.audit import ACTION_LABELS, action_label, history_for, log_action

audit_bp = Blueprint('audit', __name__)

PER_PAGE = 50


@audit_bp.app_template_global()
def audit_history(target_type, target_id, limit=30):
    return history_for(target_type, target_id, limit)


@audit_bp.app_template_filter('audit_label')
def _audit_label_filter(action):
    return action_label(action)


def _parse_date(value, end=False):
    if not value:
        return None
    try:
        d = datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None
    return d.replace(hour=23, minute=59, second=59) if end else d


def _filtered_query():
    q = AuditLog.query
    f = {
        'user': (request.args.get('user') or '').strip(),
        'action': (request.args.get('action') or '').strip(),
        'target': (request.args.get('target') or '').strip(),
        'start': (request.args.get('start') or '').strip(),
        'end': (request.args.get('end') or '').strip(),
    }
    if f['user']:
        q = q.filter(AuditLog.username.ilike(f"%{f['user']}%"))
    if f['action']:
        if f['action'].endswith('.'):
            q = q.filter(AuditLog.action.like(f"{f['action']}%"))
        else:
            q = q.filter(AuditLog.action == f['action'])
    if f['target']:
        like = f"%{f['target']}%"
        q = q.filter(db.or_(AuditLog.target_ref.ilike(like), AuditLog.details.ilike(like),
                            AuditLog.target_type.ilike(like)))
    start = _parse_date(f['start'])
    end = _parse_date(f['end'], end=True)
    if start:
        q = q.filter(AuditLog.timestamp >= start)
    if end:
        q = q.filter(AuditLog.timestamp <= end)
    return q.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()), f


# ---------------------------------------------------------------------------
#  Journal d'audit
# ---------------------------------------------------------------------------
@audit_bp.route('/admin/audit')
@login_required
@admin_required
def audit_log():
    q, filters = _filtered_query()
    page = max(1, request.args.get('page', 1, type=int))
    total = q.count()
    entries = q.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    pages = max(1, -(-total // PER_PAGE))
    domains = sorted({a.split('.')[0] for a in ACTION_LABELS})
    return render_template('admin_audit.html', entries=entries, filters=filters, page=page, pages=pages,
                           total=total, per_page=PER_PAGE, action_labels=ACTION_LABELS, domains=domains)


@audit_bp.route('/admin/audit/export.csv')
@login_required
@admin_required
def audit_export():
    q, _ = _filtered_query()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(['Horodatage', 'Utilisateur', 'Action', 'Libellé', 'Type cible', 'Id cible', 'Référence', 'Détails', 'IP'])
    for e in q.limit(50000).all():
        w.writerow([e.timestamp.strftime('%Y-%m-%d %H:%M:%S') if e.timestamp else '', e.username or '',
                    e.action, action_label(e.action), e.target_type or '', e.target_id or '',
                    e.target_ref or '', e.details or '', e.ip or ''])
    resp = make_response('﻿' + buf.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f"attachment; filename=audit_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return resp


# ---------------------------------------------------------------------------
#  Rapports mensuels
# ---------------------------------------------------------------------------
@audit_bp.route('/admin/rapports', methods=['GET', 'POST'])
@login_required
@admin_required
def rapports():
    from app import reporting
    if request.method == 'POST':
        try:
            year, month = (int(x) for x in request.form.get('month', '').split('-'))
            if not 1 <= month <= 12 or year < 2020:
                raise ValueError
        except ValueError:
            flash("Mois invalide.", "danger")
            return redirect(url_for('audit.rapports'))
        try:
            path, pdf, shared = reporting.generate_and_store(year, month)
            log_action('report.generate', ('Rapport', None, f"{year:04d}-{month:02d}"),
                       details=f"{len(pdf)} octets" + (" ; copié sur le partage" if shared else ''), commit=True)
            recipients = []
            if request.form.get('send'):
                recipients = reporting.send_monthly_report(year, month, pdf)
            flash(f"Rapport {reporting.MONTHS_FR[month]} {year} généré"
                  + (f" et envoyé à {len(recipients)} destinataire(s)" if recipients else '') + ".", "success")
        except Exception as e:
            current_app.logger.exception("Génération du rapport mensuel")
            flash(f"Génération impossible : {e}", "danger")
        return redirect(url_for('audit.rapports'))

    py, pm = reporting.previous_month()
    return render_template('admin_rapports.html', reports=reporting.list_reports(),
                           default_month=f"{py:04d}-{pm:02d}", reports_dir=reporting.reports_dir(),
                           share_dir=reporting.share_dir())


@audit_bp.route('/admin/rapports/<int:year>-<int:month>.pdf')
@login_required
@admin_required
def rapport_download(year, month):
    from app import reporting
    import os
    if not 1 <= month <= 12:
        abort(404)
    path = reporting.report_path(year, month)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype='application/pdf', as_attachment=True,
                     download_name=reporting.report_filename(year, month))


@audit_bp.route('/admin/rapports/apercu/<int:year>-<int:month>')
@login_required
@admin_required
def rapport_preview(year, month):
    """Aperçu HTML du rapport (sans PDF) — utile pour vérifier les chiffres."""
    from app import reporting
    if not 1 <= month <= 12:
        abort(404)
    return reporting.build_monthly_report(year, month)


# ---------------------------------------------------------------------------
#  RGPD
# ---------------------------------------------------------------------------
@audit_bp.route('/admin/rgpd', methods=['GET', 'POST'])
@login_required
@admin_required
def rgpd():
    from app import rgpd as rgpd_mod
    if request.method == 'POST':
        c1 = (request.form.get('confirm1') or '').strip()
        c2 = (request.form.get('confirm2') or '').strip()
        if c1 != 'PURGER' or c2 != 'PURGER':
            flash("Confirmation incorrecte : saisissez PURGER dans les deux champs. Rien n'a été modifié.", "danger")
            return redirect(url_for('audit.rgpd'))
        plan = rgpd_mod.plan_purge()
        if not plan['operations']:
            flash("Rien à purger : le plan est vide.", "info")
            return redirect(url_for('audit.rgpd'))
        try:
            result = rgpd_mod.apply_purge(plan, actor=current_user._get_current_object())
            flash(f"Purge exécutée : {result['summary']}. Journal : {result['log_path'] or 'non écrit'}.", "success")
        except Exception as e:
            current_app.logger.exception("Purge RGPD")
            flash(f"Purge annulée (aucune modification) : {e}", "danger")
        return redirect(url_for('audit.rgpd'))

    plan = rgpd_mod.plan_purge()
    preview = {}
    for op in plan['operations']:
        preview.setdefault(op['rule'], []).append(op)
    last_purges = (AuditLog.query.filter_by(action='rgpd.purge')
                   .order_by(AuditLog.timestamp.desc()).limit(5).all())
    return render_template('admin_rgpd.html', plan=plan, preview=preview, last_purges=last_purges,
                           total_ops=len(plan['operations']), log_dir=rgpd_mod.log_dir())
