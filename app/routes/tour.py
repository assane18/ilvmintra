"""Visite guidée interactive (2026-11-18).

La visite elle-même est entièrement côté navigateur (static/js/tour.js,
étapes définies par rôle dans templates/_tour.html) et ne déclenche aucune
action métier. Le serveur ne fait que retenir qu'elle a été terminée ou
passée, pour ne plus la lancer d'elle-même.
"""
from datetime import datetime

from flask import Blueprint
from flask_login import login_required, current_user

from app import db

tour_bp = Blueprint('tour', __name__)


@tour_bp.route('/tour/done', methods=['POST'])
@login_required
def done():
    if current_user.tour_done_at is None:
        current_user.tour_done_at = datetime.utcnow()
        db.session.commit()
    return '', 204


@tour_bp.route('/tour/steps')
@login_required
def steps():
    """Étapes de la visite pour le rôle de l'utilisateur (JSON)."""
    from flask import render_template, Response
    return Response(render_template('tour_steps.json').strip(), mimetype='application/json',
                    headers={'Cache-Control': 'no-store'})
