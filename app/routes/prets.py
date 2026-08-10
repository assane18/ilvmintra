from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, current_app
from flask_login import login_required, current_user
from app.models import Materiel, Pret
from app import db
import pandas as pd
import os
from datetime import datetime

prets_bp = Blueprint('prets', __name__)

@prets_bp.route('/prets', methods=['GET', 'POST'])
@login_required
def liste_prets():
    if request.method == 'POST':
        materiel_id = request.form.get('materiel_id')
        nom         = request.form.get('nom', '').strip()
        prenom      = request.form.get('prenom', '').strip()
        service     = request.form.get('service', '').strip()
        type_pret   = request.form.get('type_pret', '')

        mat = Materiel.query.get(materiel_id)
        if not mat:
            flash('Matériel introuvable.', 'danger')
        elif mat.statut != 'Disponible':
            flash('Ce matériel n\'est pas disponible.', 'danger')
        else:
            pret = Pret(
                materiel_id       = mat.id,
                technicien_id     = current_user.id,
                nom_emprunteur    = nom,
                prenom_emprunteur = prenom,
                service_emprunteur= service,
                date_sortie       = datetime.now(),
                statut_dossier    = 'En cours',
                type_pret         = type_pret,
            )
            mat.statut = 'En prêt'
            db.session.add(pret)
            db.session.commit()
            flash(f'Prêt créé : {mat.modele} ({mat.sn}) → {nom} {prenom}.', 'success')
        return redirect(url_for('prets.liste_prets'))

    # Logique GET (Affichage + Recherche)
    search_query = request.args.get('q', '')
    # On fait une jointure avec Materiel pour pouvoir chercher par SN ou Modèle dans les prêts
    query = Pret.query.join(Materiel)
    
    if search_query:
        query = query.filter(
            db.or_(
                Pret.nom_emprunteur.ilike(f'%{search_query}%'),
                Pret.prenom_emprunteur.ilike(f'%{search_query}%'),
                Pret.service_emprunteur.ilike(f'%{search_query}%'),
                Materiel.modele.ilike(f'%{search_query}%'),
                Materiel.sn.ilike(f'%{search_query}%')
            )
        )

    liste_prets = query.order_by(Pret.date_sortie.desc()).all()
    materiels_dispo = Materiel.query.filter_by(statut='Disponible').all()
    
    return render_template('prets.html', 
                           materiels=materiels_dispo, 
                           prets=liste_prets, 
                           search_query=search_query)

@prets_bp.route('/pret/<int:id>/retour', methods=['POST'])
@login_required
def valider_retour(id):
    pret = Pret.query.get_or_404(id)
    if pret.statut_dossier == 'En cours':
        try:
            d_ret = datetime.strptime(request.form.get('custom_date_retour'), '%Y-%m-%dT%H:%M') if request.form.get('custom_date_retour') else datetime.now()
        except:
            d_ret = datetime.now()
            
        pret.date_retour_reelle = d_ret
        pret.etat_ecran_retour = request.form.get('etat_ecran_retour')
        pret.etat_clavier_retour = request.form.get('etat_clavier_retour')
        pret.etat_coque_retour = request.form.get('etat_coque_retour')
        pret.statut_dossier = 'Terminé'
        
        if pret.materiel:
            pret.materiel.statut = 'Disponible'
            
        db.session.commit()
        flash('Retour matériel validé.', 'success')
        
    return redirect(url_for('prets.liste_prets'))

@prets_bp.route('/pret/<int:id>/delete')
@login_required
def delete_pret(id):
    pret = Pret.query.get_or_404(id)
    if pret.materiel and pret.statut_dossier == 'En cours':
        pret.materiel.statut = 'Disponible'
    db.session.delete(pret)
    db.session.commit()
    flash('Dossier de prêt supprimé.', 'success')
    return redirect(url_for('prets.liste_prets'))

# --- EXPORT / IMPORT PRÊTS ---

@prets_bp.route('/export/prets')
@login_required
def export_prets():
    prets = Pret.query.all()
    data = []
    for p in prets:
        data.append({
            'ID_Pret': p.id,
            'Materiel_SN': p.materiel.sn if p.materiel else 'Inconnu',
            'Materiel_Modele': p.materiel.modele if p.materiel else 'Inconnu',
            'Type': p.materiel.categorie if p.materiel else '',
            'Emprunteur': f"{p.nom_emprunteur} {p.prenom_emprunteur}",
            'Service': p.service_emprunteur,
            'Date_Sortie': p.date_sortie.strftime('%Y-%m-%d %H:%M') if p.date_sortie else '',
            'Date_Retour': p.date_retour_reelle.strftime('%Y-%m-%d %H:%M') if p.date_retour_reelle else '',
            'Statut': p.statut_dossier
        })
    
    df = pd.DataFrame(data)
    export_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(export_dir, exist_ok=True)
    filename = f'Export_Prets_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    path = os.path.join(export_dir, filename)
    
    df.to_excel(path, index=False)
    return send_file(path, as_attachment=True)

@prets_bp.route('/import/prets', methods=['POST'])
@login_required
def import_prets():
    if 'file' not in request.files: return redirect(url_for('prets.liste_prets'))
    file = request.files['file']
    if file.filename == '': return redirect(url_for('prets.liste_prets'))
    
    try:
        df = pd.read_excel(file)

        def col(row, *keys):
            for k in keys:
                if k in row and str(row[k]).strip() not in ('', 'nan', 'NaT', 'nat', 'None'):
                    return str(row[k]).strip()
            return ''

        count = 0
        skipped = 0
        for _, row in df.iterrows():
            sn = col(row, 'SN', 'Materiel_SN')
            if not sn:
                continue

            mat = Materiel.query.filter_by(sn=sn).first()

            # Créer le matériel s'il n'existe pas encore
            if not mat:
                mat = Materiel(
                    sn=sn,
                    modele=col(row, 'Materiel_Modele', 'Modele') or 'Importé',
                    categorie=col(row, 'Type', 'Categorie', 'Materiel_Type') or 'Autre',
                    statut='Disponible'
                )
                db.session.add(mat)
                db.session.flush()

            if mat.statut != 'Disponible':
                skipped += 1
                continue

            try:
                _d = pd.to_datetime(col(row, 'Date_Sortie'))
                d_out = datetime.now() if pd.isna(_d) else _d.to_pydatetime()
            except Exception:
                d_out = datetime.now()

            nom_complet = col(row, 'Emprunteur', 'Nom', 'nom_emprunteur') or 'Import'
            parts = nom_complet.split(' ', 1)

            pret = Pret(
                materiel_id       = mat.id,
                technicien_id     = current_user.id,
                nom_emprunteur    = col(row, 'Nom') or parts[0],
                prenom_emprunteur = col(row, 'Prenom') or (parts[1] if len(parts) > 1 else ''),
                service_emprunteur= col(row, 'Service') or '',
                statut_dossier    = 'En cours',
                date_sortie       = d_out,
                type_pret         = col(row, 'Type_Pret', 'type_pret') or '',
            )
            mat.statut = 'En prêt'
            db.session.add(pret)
            count += 1

        db.session.commit()
        msg = f'Import terminé : {count} prêt(s) créé(s)'
        if skipped:
            msg += f', {skipped} ignoré(s) (matériel déjà en prêt)'
        flash(msg, 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur import : {e}', 'danger')
        
    return redirect(url_for('prets.liste_prets'))
