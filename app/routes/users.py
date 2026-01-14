from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import User, UserRole, ServiceType
from app import db

users_bp = Blueprint('users', __name__)

@users_bp.route('/admin/users')
@login_required
def list_users():
    user_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    if 'ADMIN' not in user_role:
        flash("Accès réservé aux administrateurs.", "danger")
        return redirect(url_for('main.user_portal'))
    
    users = User.query.all()
    roles = [r.value for r in UserRole]
    services = [s.value for s in ServiceType]
    
    return render_template('admin_users.html', users=users, roles=roles, services=services)

@users_bp.route('/admin/users/edit/<int:id>', methods=['POST'])
@login_required
def edit_user(id):
    user_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    if 'ADMIN' not in user_role:
        return redirect(url_for('main.user_portal'))
        
    user = User.query.get_or_404(id)
    user.fullname = request.form.get('fullname')
    
    role_value = request.form.get('role')
    for r in UserRole:
        if r.value == role_value:
            user.role = r
            break
            
    # CORRECTION CRITIQUE : Utilisation de set_allowed_services au lieu de service_department
    service_value = request.form.get('service')
    if service_value and service_value != 'None':
        # On définit le service comme unique service autorisé
        user.set_allowed_services([service_value])
        # On peut aussi définir l'origine par défaut
        user.set_origin_services([service_value])
    else:
        user.set_allowed_services([])
        
    db.session.commit()
    flash(f'Utilisateur {user.fullname} mis à jour.', 'success')
    return redirect(url_for('users.list_users'))

@users_bp.route('/admin/users/delete/<int:id>')
@login_required
def delete_user(id):
    user_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    if 'ADMIN' not in user_role:
        return redirect(url_for('main.user_portal'))
        
    user = User.query.get_or_404(id)
    if user.id != current_user.id:
        db.session.delete(user)
        db.session.commit()
        flash('Utilisateur supprimé.', 'success')
    else:
        flash('Impossible de se supprimer soi-même.', 'danger')
        
    return redirect(url_for('users.list_users'))
