from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, current_app
from flask_login import login_required, current_user
from app.models import Materiel, Pret, UserRole, ServiceType
from app import db
import pandas as pd
import os
from datetime import datetime
from sqlalchemy.exc import IntegrityError

inventaire_bp = Blueprint('inventaire', __name__)

@inventaire_bp.route('/inventaire', methods=['GET', 'POST'])
@login_required
def liste():
    # SÉCURITÉ : Admin ou (Tech/Manager/Directeur) du service INFO
    user_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    user_services = current_user.get_allowed_services()
    
    is_admin = 'ADMIN' in user_role
    
    # CORRECTION : On autorise SOLVER, MANAGER et DIRECTEUR s'ils sont du service INFO
    is_allowed_role = 'SOLVER' in user_role or 'MANAGER' in user_role or 'DIRECTEUR' in user_role
    is_tech_info = is_allowed_role and ('INFORMATIQUE' in user_services or 'INFO' in user_services)
    
    if not (is_admin or is_tech_info):
        flash("Accès réservé au service Informatique.", "danger")
        return redirect(url_for('main.user_portal'))

    materiels = Materiel.query.all()
    return render_template('inventaire.html', materiels=materiels)

@inventaire_bp.route('/inventaire/add', methods=['POST'])
@login_required
def ajouter():
    # Vérification droits pour l'ajout
    user_role = str(current_user.role.value).upper() if hasattr(current_user.role, 'value') else str(current_user.role).upper()
    user_services = current_user.get_allowed_services()

    is_admin = 'ADMIN' in user_role
    is_allowed_role = 'SOLVER' in user_role or 'MANAGER' in user_role or 'DIRECTEUR' in user_role
    is_tech_info = is_allowed_role and ('INFORMATIQUE' in user_services or 'INFO' in user_services)

    if not (is_admin or is_tech_info):
        return redirect(url_for('main.user_portal'))

    categorie = request.form.get('categorie')
    modele = request.form.get('modele')
    sn = request.form.get('sn')
    hostname = request.form.get('hostname')
    imei = request.form.get('imei')

    if Materiel.query.filter_by(sn=sn).first():
        flash(f'Erreur : Le numéro de série {sn} existe déjà.', 'danger')
    else:
        new_mat = Materiel(categorie=categorie, modele=modele, sn=sn, hostname=hostname, imei=imei)
        db.session.add(new_mat)
        db.session.commit()
        flash('Matériel ajouté.', 'success')

    return redirect(url_for('inventaire.liste'))

@inventaire_bp.route('/inventaire/edit/<int:id>', methods=['POST'])
@login_required
def modifier(id):
    mat = Materiel.query.get_or_404(id)
    mat.categorie = request.form.get('categorie')
    mat.modele = request.form.get('modele')
    mat.sn = request.form.get('sn')
    mat.hostname = request.form.get('hostname')
    mat.imei = request.form.get('imei')
    db.session.commit()
    flash('Matériel modifié.', 'success')
    return redirect(url_for('inventaire.liste'))

@inventaire_bp.route('/inventaire/delete/<int:id>')
@login_required
def supprimer(id):
    mat = Materiel.query.get_or_404(id)
    db.session.delete(mat)
    db.session.commit()
    flash('Matériel supprimé.', 'success')
    return redirect(url_for('inventaire.liste'))

@inventaire_bp.route('/export/stock')
@login_required
def export_stock():
    materiels = Materiel.query.all()
    data = []
    for m in materiels:
        data.append({
            'Categorie': m.categorie,
            'Modele': m.modele,
            'SN': m.sn,
            'Hostname': m.hostname,
            'IMEI': m.imei,
            'Statut': m.statut
        })
    
    df = pd.DataFrame(data)
    export_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(export_dir, exist_ok=True)
    filename = f'Export_Stock_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    path = os.path.join(export_dir, filename)
    
    df.to_excel(path, index=False)
    return send_file(path, as_attachment=True)

@inventaire_bp.route('/import/stock', methods=['POST'])
@login_required
def import_stock():
    if 'file' not in request.files: return redirect(url_for('inventaire.liste'))
    file = request.files['file']
    if file.filename == '': return redirect(url_for('inventaire.liste'))
        
    try:
        df = pd.read_excel(file)
        if 'SN' not in df.columns:
            flash('Erreur format : Colonne "SN" manquante.', 'danger')
            return redirect(url_for('inventaire.liste'))
            
        count = 0
        for _, row in df.iterrows():
            sn_val = str(row['SN']).strip()
            if not Materiel.query.filter_by(sn=sn_val).first():
                db.session.add(Materiel(
                    categorie=row.get('Categorie','Autre'), 
                    modele=row.get('Modele','Inconnu'), 
                    sn=sn_val, 
                    hostname=row.get('Hostname',''), 
                    imei=str(row.get('IMEI','')), 
                    statut='Disponible'
                ))
                count += 1
        db.session.commit()
        flash(f'Import terminé : {count} matériels ajoutés.', 'success')
    except Exception as e:
        flash(f'Erreur import : {e}', 'danger')
        
    return redirect(url_for('inventaire.liste'))
