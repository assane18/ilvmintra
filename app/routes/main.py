from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import UserRole, Ticket, FormDefinition, User
from app import db
from app.decorators import admin_required

main_bp = Blueprint('main', __name__)

# Pilotes du moteur de formulaires déjà basculés en direct avec leur propre
# tuile dédiée dans portal.html (icône/texte historique conservés, juste le
# lien qui pointe désormais vers forms.new_submission) — à exclure de la
# boucle active_forms générique ci-dessous pour ne pas les afficher deux fois.
LIVE_PILOT_SLUGS = {'info-v2', 'imago-v2', 'drh-v2', 'materiel-v2', 'tech-v2', 'generaux-v2', 'sejour-v2', 'publication-v2'}

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

    active_forms = FormDefinition.query.filter_by(is_active=True)\
        .filter(FormDefinition.slug.notin_(LIVE_PILOT_SLUGS))\
        .order_by(FormDefinition.name).all()

    return render_template('portal.html', user=current_user, tickets=recent_tickets, active_forms=active_forms)

@main_bp.route('/my_history')
@login_required
def my_history():
    # Récupération du terme de recherche depuis l'URL (?q=...)
    search_query = request.args.get('q', '')
    
    # Base de la requête : les tickets dont l'utilisateur est l'auteur
    query = Ticket.query.filter_by(author_id=current_user.id)
    
    # Si une recherche est saisie, on applique le filtre
    if search_query:
        query = query.filter(
            db.or_(
                Ticket.title.ilike(f'%{search_query}%'),
                Ticket.uid_public.ilike(f'%{search_query}%'),
                Ticket.description.ilike(f'%{search_query}%')
            )
        )
    
    # Exécution de la requête avec tri par date décroissante
    tickets = query.order_by(Ticket.created_at.desc()).all()
    
    return render_template('my_history.html', tickets=tickets, search_query=search_query)

@main_bp.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    return render_template(
        'admin_hub.html',
        users_count=User.query.count(),
        forms_count=FormDefinition.query.count(),
        active_forms_count=FormDefinition.query.filter_by(is_active=True).count(),
    )

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

@main_bp.route('/help')
@login_required
def help_center():
    return render_template('help.html')
