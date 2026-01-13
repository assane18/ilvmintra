from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import User, UserRole, ServiceType
from app import db

users_bp = Blueprint('users', __name__)

@users_bp.route('/admin/users')
@login_required
def list_users():
    # Sécurité : Admin Only
    # On convertit en string pour être sûr
    if 'ADMIN' not in str(current_user.role).upper():
        flash("Accès réservé aux administrateurs.", "danger")
        return redirect(url_for('main.user_portal'))
    
    users = User.query.all()
    
    # Préparation des listes pour les menus déroulants
    roles = [r.value for r in UserRole]
    services = [s.value for s in ServiceType]
    
    return render_template('admin_users.html', users=users, roles=roles, services=services)

@users_bp.route('/admin/users/edit/<int:id>', methods=['POST'])
@login_required
def edit_user(id):
    if 'ADMIN' not in str(current_user.role).upper():
        return redirect(url_for('main.user_portal'))
        
    user = User.query.get_or_404(id)
    
    # Mise à jour du nom
    user.fullname = request.form.get('fullname')
    
    # Mise à jour du Rôle
    role_value = request.form.get('role')
    # On cherche l'Enum correspondant à la valeur (ex: 'SOLVER' -> UserRole.SOLVER)
    for r in UserRole:
        if r.value == role_value:
            user.role = r
            break
            
    # Mise à jour du Service
    service_value = request.form.get('service')
    if service_value and service_value != 'None':
        for s in ServiceType:
            if s.value == service_value:
                user.service_department = s
                break
    else:
        user.service_department = None
        
    db.session.commit()
    flash(f'Utilisateur {user.fullname} mis à jour.', 'success')
    return redirect(url_for('users.list_users'))

@users_bp.route('/admin/users/delete/<int:id>')
@login_required
def delete_user(id):
    if 'ADMIN' not in str(current_user.role).upper():
        return redirect(url_for('main.user_portal'))
        
    user = User.query.get_or_404(id)
    
    if user.id == current_user.id:
        flash("Impossible de supprimer votre propre compte !", "danger")
    else:
        db.session.delete(user)
        db.session.commit()
        flash('Compte supprimé.', 'success')
        
    return redirect(url_for('users.list_users'))
