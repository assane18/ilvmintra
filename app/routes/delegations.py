"""Lot 7 — routes « Organisation des demandes » : délégations de validation
(déclaration depuis le profil, annulation, vue ADMIN) et recherche d'agents
(autocomplétion partagée par le bloc « au nom de quelqu'un d'autre » des
formulaires et par le choix du délégué). La logique est dans app/delegation.py.

Blueprint séparé (chantiers parallèles sur tickets.py / forms.py), enregistré
sous /delegations dans app/__init__.py. Le bloc « Mes délégations » du profil
est alimenté par un context processor (pas de retouche de main.profile).
"""
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.decorators import admin_required
from app.delegation import (DELEGATE_ROLES, can_cancel_delegation, can_manage_delegations,
                            cancel_delegation, create_delegation, created_for_label, delegations_of,
                            parse_period, search_users, user_to_json)
from app.models import User, ValidationDelegation

delegations_bp = Blueprint('delegations', __name__)


@delegations_bp.app_context_processor
def _lot7_template_helpers():
    """Helpers Jinja : bloc « Mes délégations » du profil et libellé « Demande
    créée par Z pour le compte de A » (detail.html / view_submission.html)."""
    def lot7_delegations_context():
        if not current_user.is_authenticated or not can_manage_delegations(current_user):
            return None
        given, received = delegations_of(current_user)
        now = datetime.now()
        return {
            'given': [d for d in given if d.state(now) in ('active', 'upcoming')],
            'given_past': [d for d in given if d.state(now) in ('expired', 'cancelled')][:5],
            'received': [d for d in received if d.state(now) in ('active', 'upcoming')],
            'today': now.strftime('%Y-%m-%d'),
            'is_admin': current_user.role.value == 'ADMIN',
        }
    return {'lot7_delegations_context': lot7_delegations_context,
            'lot7_created_for_label': created_for_label}


@delegations_bp.route('/new', methods=['POST'])
@login_required
def new_delegation():
    """« X valide à ma place du … au … » (formulaire du profil, onglet Mon compte)."""
    raw_id = (request.form.get('delegate_id') or '').strip()
    delegate = User.query.get(int(raw_id)) if raw_id.isdigit() else None
    starts_at, ends_at = parse_period(request.form.get('starts_at'), request.form.get('ends_at'))
    d, error = create_delegation(current_user, delegate, starts_at, ends_at, request.form.get('reason'))
    if error:
        db.session.rollback()
        flash(error, 'danger')
    else:
        db.session.commit()
        flash(f"Délégation enregistrée : {delegate.fullname or delegate.username} valide à votre place "
              f"du {starts_at.strftime('%d/%m/%Y')} au {ends_at.strftime('%d/%m/%Y')}.", 'success')
    return redirect(url_for('main.profile', tab='account'))


@delegations_bp.route('/<int:delegation_id>/cancel', methods=['POST'])
@login_required
def cancel(delegation_id):
    d = ValidationDelegation.query.get_or_404(delegation_id)
    if not can_cancel_delegation(current_user, d):
        flash("Vous ne pouvez annuler que vos propres délégations.", 'danger')
        return redirect(url_for('main.profile', tab='account'))
    cancel_delegation(d, current_user)
    db.session.commit()
    flash("Délégation annulée.", 'success')
    if request.form.get('next') == 'admin' and current_user.role.value == 'ADMIN':
        return redirect(url_for('delegations.admin_list'))
    return redirect(url_for('main.profile', tab='account'))


@delegations_bp.route('/admin')
@login_required
@admin_required
def admin_list():
    """Toutes les délégations (actives, à venir, expirées, annulées) — l'ADMIN
    peut annuler n'importe laquelle."""
    now = datetime.now()
    show = request.args.get('show', 'current')
    rows = ValidationDelegation.query.order_by(ValidationDelegation.starts_at.desc()).all()
    if show == 'current':
        rows = [d for d in rows if d.state(now) in ('active', 'upcoming')]
    return render_template('delegations/admin.html', delegations=rows, show=show, now=now)


@delegations_bp.route('/users/search')
@login_required
def users_search():
    """Autocomplétion : ?q=<texte>[&scope=validators] -> 10 résultats max
    (nom + service). `scope=validators` limite aux rôles pouvant recevoir une
    délégation (MANAGER/DIRECTEUR/ADMIN). L'utilisateur connecté est exclu."""
    roles = DELEGATE_ROLES if request.args.get('scope') == 'validators' else None
    users = search_users(request.args.get('q', ''), limit=10, roles=roles, exclude_id=current_user.id)
    return jsonify([user_to_json(u) for u in users])
