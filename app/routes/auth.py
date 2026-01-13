from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, make_response, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, UserRole, ServiceType
from app import db
from ldap3 import Server, Connection, ALL, SIMPLE
from functools import wraps
from sqlalchemy.exc import DataError, StatementError

auth_bp = Blueprint('auth', __name__)

# --- ANTI-CACHE RENFORCÉ (CRITIQUE POUR LE BOUTON RETOUR) ---
def nocache(view):
    @wraps(view)
    def no_cache(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    return no_cache

# ... (Fonctions get_ldap_connection et parse_ad_groups inchangées) ...
def get_ldap_connection(username, password):
    LDAP_SERVER_URL = current_app.config.get('LDAP_SERVER', 'ldap://192.168.1.9') 
    LDAP_DOMAIN_PREFIX = current_app.config.get('LDAP_DOMAIN', 'ILVM\\') 
    LDAP_BASE_DN = current_app.config.get('LDAP_BASE_DN', 'dc=ilvm,dc=lan')
    
    try:
        server = Server(LDAP_SERVER_URL, get_info=ALL, connect_timeout=5)
        clean_username = username.split('@')[0].split('\\')[-1]
        user_dn = f"{LDAP_DOMAIN_PREFIX}{clean_username}"
        conn = Connection(server, user=user_dn, password=password, authentication=SIMPLE, auto_bind=True)
        return conn, LDAP_BASE_DN, None
    except Exception as e:
        return None, None, str(e)

def parse_ad_groups(groups_entry):
    groups_list = [str(g).upper().split(',')[0].replace('CN=', '') for g in groups_entry]
    role = UserRole.USER
    origin_services = []
    allowed_services = []

    for group in groups_list:
        if group.startswith('GR-'):
            role_suffix = group.replace('GR-', '')
            if role_suffix == 'DIRECTEUR': role = UserRole.DIRECTEUR
            elif role_suffix == 'MANAGER' and role != UserRole.DIRECTEUR: role = UserRole.MANAGER
            elif role_suffix == 'SOLVER' and role != UserRole.DIRECTEUR and role != UserRole.MANAGER: role = UserRole.SOLVER
            elif role_suffix == 'ADMIN': role = UserRole.ADMIN

        elif group.startswith('GS-'):
            svc_name = group.replace('GS-', '')
            # Mapping simplifié
            if svc_name in ['INFORMATIQUE', 'INFO']: allowed_services.append(ServiceType.INFO.value)
            elif svc_name == 'DAF': allowed_services.append(ServiceType.DAF.value)
            elif svc_name in ['TECHNIQUE', 'TECH']: allowed_services.append(ServiceType.TECH.value)
            elif svc_name == 'GENERAUX': allowed_services.append(ServiceType.GEN.value)
            # ... autres mappings ...
            else: allowed_services.append(svc_name)

        elif group.startswith('GU-'):
            origin_services.append(group.replace('GU-', ''))

    if role == UserRole.SOLVER and not allowed_services: role = UserRole.USER
    return role, origin_services, allowed_services

@auth_bp.route('/login', methods=['GET', 'POST'])
@nocache 
def login():
    if current_user.is_authenticated:
        return redirect_by_role(current_user)

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn, base_dn, error_msg = get_ldap_connection(username, password)
        
        if conn:
            try:
                clean_user = username.split('@')[0].split('\\')[-1]
                search_filter = f'(sAMAccountName={clean_user})'
                conn.search(base_dn, search_filter, attributes=['memberOf', 'displayName', 'mail'])
                
                if not conn.entries:
                    flash("Utilisateur introuvable.", "warning")
                    return render_template('auth/login.html')
                    
                user_entry = conn.entries[0]
                role, origins, alloweds = parse_ad_groups(user_entry.memberOf)
                
                user = User.query.filter_by(username=clean_user).first()
                if not user:
                    user = User(username=clean_user)
                    db.session.add(user)
                
                user.fullname = str(user_entry.displayName) if user_entry.displayName else clean_user
                user.email = str(user_entry.mail) if user_entry.mail else f"{clean_user}@ilvm.lan"
                
                # Vérifier la validité du rôle dans le contexte de la base de données
                # Si la base de données ne prend pas en charge le rôle (par exemple DIRECTEUR n'est pas dans l'énumération), cette affectation est correcte en Python
                # mais le commit échouera.
                user.role = role
                user.set_origin_services(origins)
                user.set_allowed_services(alloweds)
                
                if clean_user.lower() == 'administrateur': user.role = UserRole.ADMIN
                
                try:
                    db.session.commit()
                except (DataError, StatementError) as db_err:
                    db.session.rollback()
                    if "invalid input value for enum" in str(db_err) or "InvalidTextRepresentation" in str(db_err):
                        flash("Erreur Base de Données : Le rôle 'DIRECTEUR' n'est pas reconnu par la base. Veuillez exécuter la migration ou 'ALTER TYPE userrole ADD VALUE ''DIRECTEUR'';' dans PostgreSQL.", "danger")
                        print(f"ERREUR ENUM BDD: {db_err}")
                        return render_template('auth/login.html')
                    else:
                        raise db_err

                login_user(user)
                return redirect_by_role(user)
                
            except Exception as e:
                flash(f"Erreur technique : {e}", "danger")
                print(f"ERREUR CONNEXION: {e}")
        else:
            flash(f"Échec connexion : {error_msg}", "danger")

    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
@nocache
def logout():
    session.clear() # Vide tout le cache session server-side
    logout_user()
    flash("Déconnecté.", "info")
    return redirect(url_for('auth.login'))

def redirect_by_role(user):
    """
    Logique de redirection stricte :
    1. ADMIN -> Solver Dashboard
    2. DIRECTEUR / MANAGER -> Manager Dashboard (Validation)
    3. SOLVER -> Solver Dashboard (Traitement)
    4. USER -> Portail
    """
    # Conversion robuste en string pour comparaison
    role = str(user.role.value).upper() if hasattr(user.role, 'value') else str(user.role).upper()
    
    if 'ADMIN' in role:
        return redirect(url_for('tickets.solver_dashboard'))
    
    # Correction pour le DIRECTEUR qui était renvoyé vers le portail user par erreur
    if 'DIRECTEUR' in role or 'MANAGER' in role:
        return redirect(url_for('tickets.manager_dashboard'))
        
    if 'SOLVER' in role:
        return redirect(url_for('tickets.solver_dashboard'))
    
    return redirect(url_for('main.user_portal'))
