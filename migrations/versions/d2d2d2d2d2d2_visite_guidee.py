"""visite guidée interactive : date de fin (ou d'abandon) de la visite

Revision ID: d2d2d2d2d2d2
Revises: c1c1c1c1c1c1
Create Date: 2026-11-18 00:00:00.000000

Les comptes déjà existants sont marqués « visite faite » : la visite ne se
lance d'elle-même qu'à la première connexion des nouveaux comptes. Chacun
peut la relancer depuis Aide / Tuto.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd2d2d2d2d2d2'
down_revision = 'c1c1c1c1c1c1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tour_done_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE users SET tour_done_at = CURRENT_TIMESTAMP")


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('tour_done_at')
