"""Ajout du service MEDIATEAM

Revision ID: e6f92b1c7d34
Revises: d5a71c3f8b6e
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e6f92b1c7d34'
down_revision = 'd5a71c3f8b6e'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE servicetype ADD VALUE IF NOT EXISTS 'MEDIATEAM'")


def downgrade():
    # PostgreSQL ne permet pas de retirer une valeur d'un type enum existant
    # sans recréer le type entier — pas fait ici.
    pass
