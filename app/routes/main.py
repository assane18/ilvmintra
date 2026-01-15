from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import UserRole, Ticket

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    return redirect(url_for('main.user_portal'))

@main_bp.route('/portal')
@login_required
def user_portal():
    # Récupérer les 15 derniers tickets de l'utilisateur connecté
    recent_tickets = Ticket.query.filter_by(author_id=current_user.id)\
                                 .order_by(Ticket.created_at.desc())\
                                 .limit(15).all()
    
    return render_template('portal.html', user=current_user, tickets=recent_tickets)

@main_bp.route('/my_history')
@login_required
def my_history():
    # Historique complet
    tickets = Ticket.query.filter_by(author_id=current_user.id).order_by(Ticket.created_at.desc()).all()
    return render_template('my_history.html', tickets=tickets)

@main_bp.route('/admin/dashboard')
@login_required
def admin_dashboard():
    # Sécurité : Admin Only
    if 'ADMIN' not in str(current_user.role.value).upper():
        return redirect(url_for('main.user_portal'))
    return redirect(url_for('users.list_users'))

@main_bp.route('/dashboard')
@login_required
def dashboard():
    # Redirection intelligente selon le rôle
    role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    
    if 'ADMIN' in role:
        return redirect(url_for('tickets.solver_dashboard'))
    elif 'MANAGER' in role or 'DIRECTEUR' in role:
        return redirect(url_for('tickets.manager_dashboard'))
    elif 'SOLVER' in role:
        return redirect(url_for('tickets.solver_dashboard'))
    
    return redirect(url_for('main.user_portal'))

