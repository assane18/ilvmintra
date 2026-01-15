from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import User, UserRole, ServiceType
from app import db

users_bp = Blueprint('users', __name__)

@users_bp.route('/admin/users')
@login_required
def list_users():
    # Sécurité : Admin Only
    if 'ADMIN' not in str(current_user.role.value).upper():
        flash("Accès réservé aux administrateurs.", "danger")
        return redirect(url_for('main.user_portal'))
    
    users = User.query.all()
    
    # Préparation des listes pour les menus déroulants
    roles = [r.value for r in UserRole]
    # On récupère juste les noms des services
    services = [s.value for s in ServiceType]
    
    return render_template('admin_users.html', users=users, roles=roles, services=services)

@users_bp.route('/admin/users/edit/<int:id>', methods=['POST'])
@login_required
def edit_user(id):
    if 'ADMIN' not in str(current_user.role.value).upper():
        return redirect(url_for('main.user_portal'))
        
    user = User.query.get_or_404(id)
    
    # Mise à jour du nom
    user.fullname = request.form.get('fullname')
    
    # Mise à jour du Rôle
    role_value = request.form.get('role')
    # On cherche l'Enum correspondant à la valeur
    for r in UserRole:
        if r.value == role_value:
            user.role = r
            break
            
    # Mise à jour du Service Technique (GS - Allowed Services)
    # Dans l'admin simple, on assigne un seul service principal pour l'instant
    service_value = request.form.get('service')
    
    if service_value and service_value != 'None':
        # On définit ce service comme le SEUL service autorisé et d'origine
        # C'est une simplification pour l'interface admin basique
        user.set_allowed_services([service_value])
        user.set_origin_services([service_value])
    else:
        # Si aucun service sélectionné, on vide les listes
        user.set_allowed_services([])
        # On ne vide pas forcément l'origine si on veut garder l'historique, mais ici on reset tout
        # user.set_origin_services([]) 
        
    db.session.commit()
    flash(f'Utilisateur {user.fullname} mis à jour.', 'success')
    return redirect(url_for('users.list_users'))

@users_bp.route('/admin/users/delete/<int:id>')
@login_required
def delete_user(id):
    if 'ADMIN' not in str(current_user.role.value).upper():
        return redirect(url_for('main.user_portal'))
        
    user = User.query.get_or_404(id)
    
    if user.id != current_user.id:
        db.session.delete(user)
        db.session.commit()
        flash('Utilisateur supprimé.', 'success')
    else:
        flash('Impossible de se supprimer soi-même.', 'danger')
        
    return redirect(url_for('users.list_users'))
