"""Ajout du service COMMUNICATION

Revision ID: c4d81f6e9a02
Revises: b3c7e2f4a891
Create Date: 2026-09-21 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c4d81f6e9a02'
down_revision = 'b3c7e2f4a891'
branch_labels = None
depends_on = None


def upgrade():
    # Nouvelle valeur sur le type enum PostgreSQL natif "servicetype" (utilisé
    # par tickets.target_service et form_dispatch_targets.target_service).
    op.execute("ALTER TYPE servicetype ADD VALUE IF NOT EXISTS 'COMMUNICATION'")


def downgrade():
    # PostgreSQL ne permet pas de retirer une valeur d'un type enum existant
    # sans recréer le type entier — pas fait ici (aucune donnée ne dépend
    # encore de cette valeur au moment de cette migration).
    pass
