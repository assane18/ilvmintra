"""users : index unique sur lower(username) — un seul compte par identifiant, quelle que soit la casse

Revision ID: c9e1a7b3d5f2
Revises: b7d4e2f19c03
Create Date: 2026-09-28 17:00:00.000000

Prérequis : aucun doublon de casse en base (fusion faite le 2026-09-28).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9e1a7b3d5f2'
down_revision = 'b7d4e2f19c03'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_users_username_lower', 'users', [sa.text('lower(username)')], unique=True)


def downgrade():
    op.drop_index('ix_users_username_lower', table_name='users')
