"""widen form_submissions.uid_public (was too short for long form slugs)

Revision ID: a1f3c9d07b22
Revises: dea2e0a6d97c
Create Date: 2026-09-16 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1f3c9d07b22'
down_revision = 'dea2e0a6d97c'
branch_labels = None
depends_on = None


def upgrade():
    # form_definitions.slug tolère jusqu'à 60 caractères mais l'uid généré
    # pour une soumission ("FRM-{slug}-{date}-{compteur}") ajoute 17
    # caractères fixes de préfixe/suffixe : avec l'ancienne limite de 40
    # caractères, tout formulaire dont le slug dépassait ~23 caractères
    # (ex: "demande-cr-ation-de-formulaire") faisait planter la soumission
    # (StringDataRightTruncation). On passe à 100 pour couvrir le pire cas
    # (60 + 17) avec de la marge.
    with op.batch_alter_table('form_submissions', schema=None) as batch_op:
        batch_op.alter_column('uid_public',
                               existing_type=sa.String(length=40),
                               type_=sa.String(length=100),
                               existing_nullable=True)


def downgrade():
    with op.batch_alter_table('form_submissions', schema=None) as batch_op:
        batch_op.alter_column('uid_public',
                               existing_type=sa.String(length=100),
                               type_=sa.String(length=40),
                               existing_nullable=True)
