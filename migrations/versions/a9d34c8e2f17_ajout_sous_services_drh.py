"""Ajout des sous-services DRH (Paie/Carrière, Recrutement/Formation, Effectifs/Social)

Revision ID: a9d34c8e2f17
Revises: f7a2c9e1b503
Create Date: 2026-09-24 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'a9d34c8e2f17'
down_revision = 'f7a2c9e1b503'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE servicetype ADD VALUE IF NOT EXISTS 'DRH_PAIE_CARRIERE'")
    op.execute("ALTER TYPE servicetype ADD VALUE IF NOT EXISTS 'DRH_RECRUTEMENT_FORMATION'")
    op.execute("ALTER TYPE servicetype ADD VALUE IF NOT EXISTS 'DRH_EFFECTIFS_SOCIAL'")


def downgrade():
    # PostgreSQL ne permet pas de retirer une valeur d'un type enum existant
    # sans recréer le type entier — pas fait ici.
    pass
