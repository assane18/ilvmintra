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
    # SÉCURITÉ : Seuls les Admins ou les Techniciens INFORMATIQUE ont accès
    user_role = str(current_user.role).upper()
    
    # On gère le cas où service_department est None ou Enum
    user_service = ""
    if current_user.service_department:
        # Si c'est un Enum, on prend .name, sinon on convertit en string
        user_service = getattr(current_user.service_department, 'name', str(current_user.service_department)).upper()
    
    # DEBUG (A supprimer en prod si besoin)
    # print(f"DEBUG ACCESS INVENTAIRE: Role={user_role}, Service={user_service}")

    is_admin = 'ADMIN' in user_role
    # On vérifie si 'INFO' est dans le nom du service (ex: 'INFORMATIQUE' ou 'INFO')
    is_tech_info = 'SOLVER' in user_role and ('INFO' in user_service or 'INFORMATIQUE' in user_service)
    
    if not (is_admin or is_tech_info):
        flash("Accès réservé à la DSI (Admin ou Tech Info).", "danger")
        return redirect(url_for('main.user_portal'))

    if request.method == 'POST':
        try:
            sn_check = request.form.get('sn')
            if Materiel.query.filter_by(sn=sn_check).first():
                flash(f'ERREUR : Le S/N "{sn_check}" existe déjà !', 'error')
            else:
                m = Materiel(
                    categorie=request.form.get('categorie'), 
                    modele=request.form.get('modele'),
                    sn=sn_check, 
                    hostname=request.form.get('hostname'),
                    imei=request.form.get('imei'), 
                    statut='Disponible'
                )
                db.session.add(m)
                db.session.commit()
                flash('Matériel ajouté avec succès.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Erreur doublon S/N.', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur technique : {str(e)}', 'error')
            
    stock = Materiel.query.all()
    return render_template('inventaire.html', stock=stock)

@inventaire_bp.route('/materiel/<int:id>/update', methods=['POST'])
@login_required
def edit_materiel(id):
    m = Materiel.query.get_or_404(id)
    m.modele = request.form.get('modele')
    m.sn = request.form.get('sn')
    m.hostname = request.form.get('hostname')
    m.imei = request.form.get('imei')
    m.categorie = request.form.get('categorie')
    try:
        db.session.commit()
        flash('Fiche matériel mise à jour.', 'success')
    except:
        db.session.rollback()
        flash('Erreur : S/N déjà existant.', 'error')
    return redirect(url_for('inventaire.liste'))

@inventaire_bp.route('/materiel/<int:id>/delete')
@login_required
def delete_materiel(id):
    if Pret.query.filter_by(materiel_id=id).first():
        flash('Impossible de supprimer : ce matériel a un historique de prêts.', 'error')
    else:
        m = Materiel.query.get_or_404(id)
        db.session.delete(m)
        db.session.commit()
        flash('Matériel supprimé du stock.', 'success')
    return redirect(url_for('inventaire.liste'))

# --- IMPORT / EXPORT (Excel) ---

@inventaire_bp.route('/export/stock')
@login_required
def export_stock():
    data = []
    for m in Materiel.query.all():
        data.append({
            'Categorie': m.categorie, 
            'Modele': m.modele, 
            'SN': m.sn, 
            'Hostname': m.hostname, 
            'IMEI': m.imei, 
            'Statut': m.statut
        })
    df = pd.DataFrame(data)
    
    export_dir = os.path.join(current_app.root_path, 'static', 'exports')
    os.makedirs(export_dir, exist_ok=True)
    
    filename = f'Export_Stock_{datetime.now().strftime("%Y%m%d")}.xlsx'
    path = os.path.join(export_dir, filename)
    
    df.to_excel(path, index=False)
    return send_file(path, as_attachment=True)

@inventaire_bp.route('/import/stock', methods=['POST'])
@login_required
def import_stock():
    if 'file' not in request.files:
        return redirect(url_for('inventaire.liste'))
    
    file = request.files['file']
    if file.filename == '':
        return redirect(url_for('inventaire.liste'))
        
    try:
        df = pd.read_excel(file)
        c = 0
        if 'SN' not in df.columns:
            flash('Erreur format : Colonne "SN" manquante.', 'error')
            return redirect(url_for('inventaire.liste'))
            
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
                c += 1
        db.session.commit()
        flash(f'Import terminé : {c} nouveaux matériels ajoutés.', 'success')
    except Exception as e:
        flash(f'Erreur lors de l\'import : {str(e)}', 'error')
        
    return redirect(url_for('inventaire.liste'))
