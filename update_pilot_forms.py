"""Recrée les formulaires pilotes existants avec la définition à jour
(parité exacte de ticket : catégorie/titre/description/uid/colonnes
structurées). Contrairement à seed_pilot_forms.py (idempotent, ignore un slug
déjà existant), ce script SUPPRIME d'abord les FormDefinition pilotes visées
(et leurs soumissions/fichiers de soumission éventuels) avant de rappeler les
fonctions seed_* pour les recréer proprement. Sans danger : ces pilotes sont
tous is_active=False (jamais exposés sur le portail), les rares soumissions
de test qu'ils contiennent proviennent uniquement des vérifications de ce
chantier.

Usage : python update_pilot_forms.py
"""
from app import create_app, db
from app.models import FormDefinition, FormSubmission, FormSubmissionFile
import seed_pilot_forms as seeds

app = create_app()

PILOT_SLUGS = [
    'sejour-v2', 'publication-v2', 'fcpi-v2', 'info-v2', 'drh-v2',
    'imago-v2', 'materiel-v2', 'tech-v2', 'generaux-v2',
]


def wipe_pilot(slug):
    fd = FormDefinition.query.filter_by(slug=slug).first()
    if not fd:
        return
    sub_ids = [s.id for s in FormSubmission.query.filter_by(form_definition_id=fd.id).all()]
    if sub_ids:
        FormSubmissionFile.query.filter(FormSubmissionFile.submission_id.in_(sub_ids)).delete(synchronize_session=False)
        FormSubmission.query.filter(FormSubmission.id.in_(sub_ids)).delete(synchronize_session=False)
    db.session.delete(fd)  # cascade sur fields/steps/dispatch_targets
    db.session.commit()
    print(f"{slug} (id={fd.id}) supprimé pour recréation.")


if __name__ == '__main__':
    with app.app_context():
        for slug in PILOT_SLUGS:
            wipe_pilot(slug)

        seeds.seed_sejour()
        seeds.seed_publication()
        seeds.seed_fcpi()
        seeds.seed_info()
        seeds.seed_drh()
        seeds.seed_imago()
        seeds.seed_materiel()
        seeds.seed_tech()
        seeds.seed_generaux()
        print("Formulaires pilotes recréés avec la parité de ticket à jour.")
