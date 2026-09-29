"""Lot 5 — page d'administration « Pilotage » (/admin/pilotage) : seuils
d'escalade des validations, seuil d'espace du partage de sauvegarde, masquage
du bandeau d'état du portail, aperçu du bandeau et dernières escalades."""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from app import db
from app.decorators import admin_required
from app.models import EscalationTrace
from app.pilotage import (SETTING_DEFAULTS, SETTING_LABELS, all_settings, set_setting,
                          cached_health_notices, reset_health_cache)

pilotage_bp = Blueprint('pilotage', __name__)

_INT_KEYS = ('escalade_rappel_jours', 'escalade_directeur_jours', 'sauvegarde_espace_min_go')


@pilotage_bp.route('/admin/pilotage', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_pilotage():
    if request.method == 'POST':
        errors = []
        for key in _INT_KEYS:
            raw = (request.form.get(key) or '').strip()
            try:
                val = int(raw)
                if val < 0:
                    raise ValueError
            except ValueError:
                errors.append(f"« {SETTING_LABELS[key]} » : nombre entier positif attendu (reçu « {raw} »).")
                continue
            set_setting(key, val, commit=False)
        set_setting('bandeau_etat_masque', '1' if request.form.get('bandeau_etat_masque') == '1' else '0', commit=False)
        if errors:
            db.session.rollback()
            for e in errors:
                flash(e, 'danger')
        else:
            db.session.commit()
            reset_health_cache()
            flash('Paramètres de pilotage enregistrés.', 'success')
        return redirect(url_for('pilotage.admin_pilotage'))

    settings = all_settings()
    since = datetime.now().date() - timedelta(days=14)
    traces = EscalationTrace.query.filter(EscalationTrace.sent_on >= since)\
        .order_by(EscalationTrace.created_at.desc()).limit(50).all()
    return render_template('admin_pilotage.html', settings=settings, labels=SETTING_LABELS,
                           defaults=SETTING_DEFAULTS, traces=traces,
                           health_notices=cached_health_notices())
