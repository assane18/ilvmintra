from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import Materiel, Pret
from app import db
from datetime import datetime

prets_bp = Blueprint('prets', __name__)

@prets_bp.route('/prets', methods=['GET', 'POST'])
@login_required
def liste_prets():
    # Gestion de la création d'un prêt (POST)
    if request.method == 'POST':
        if 'action_pret' in request.form:
            materiel_id = request.form.get('materiel_id')
            mat = Materiel.query.get(materiel_id)
            
            if mat and mat.statut == 'Disponible':
                # Gestion des dates
                try:
                    d_out = datetime.strptime(request.form.get('custom_date_sortie'), '%Y-%m-%dT%H:%M') if request.form.get('custom_date_sortie') else datetime.now()
                except:
                    d_out = datetime.now()
                
                # Création du Prêt
                pret = Pret(
                    materiel_id=mat.id,
                    technicien_id=current_user.id,
                    nom_emprunteur=request.form.get('nom'),
                    prenom_emprunteur=request.form.get('prenom'),
                    service_emprunteur=request.form.get('service'),
                    type_pret=request.form.get('type_pret'),
                    accessoires=", ".join(request.form.getlist('accessoires')),
                    etat_ecran_sortie=request.form.get('etat_ecran'),
                    etat_clavier_sortie=request.form.get('etat_clavier'),
                    etat_coque_sortie=request.form.get('etat_coque'),
                    date_sortie=d_out,
                    statut_dossier='En cours'
                )
                
                # Mise à jour statut matériel
                mat.statut = 'Prêté'
                
                db.session.add(pret)
                db.session.commit()
                flash('Prêt enregistré avec succès.', 'success')
            else:
                flash('Erreur : Matériel introuvable ou déjà prêté.', 'danger')

    # Affichage (GET)
    # On récupère le matériel dispo pour le formulaire et la liste des prêts
    materiels_dispo = Materiel.query.filter_by(statut='Disponible').all()
    liste_prets = Pret.query.order_by(Pret.statut_dossier.asc(), Pret.date_sortie.desc()).all()
    
    return render_template('prets.html', materiels=materiels_dispo, prets=liste_prets)

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
        
        # Libération du matériel
        if pret.materiel:
            pret.materiel.statut = 'Disponible'
            
        db.session.commit()
        flash('Retour matériel validé.', 'success')
        
    return redirect(url_for('prets.liste_prets'))

@prets_bp.route('/pret/<int:id>/delete')
@login_required
def delete_pret(id):
    pret = Pret.query.get_or_404(id)
    
    # Si on supprime un prêt en cours, on rend le matériel disponible
    if pret.statut_dossier == 'En cours' and pret.materiel:
        pret.materiel.statut = 'Disponible'
        
    db.session.delete(pret)
    db.session.commit()
    flash('Dossier de prêt supprimé.', 'success')
    return redirect(url_for('prets.liste_prets'))
