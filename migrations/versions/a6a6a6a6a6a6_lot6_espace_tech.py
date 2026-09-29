"""Lot 6 — Espace Tech au quotidien : notes internes, pièces jointes du chat,
tickets liés (doublons).

Revision ID: a6a6a6a6a6a6
Revises: a5a5a5a5a5a5
Create Date: 2026-09-29 09:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a6a6a6a6a6a6'
down_revision = 'a5a5a5a5a5a5'
branch_labels = None
depends_on = None


def upgrade():
    # Tickets liés : un doublon pointe vers son ticket maître.
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_tickets_parent_id', 'tickets', ['parent_id'], ['id'])

    # Chat : note interne (équipe seulement) + pièces jointes (liste JSON de noms).
    with op.batch_alter_table('ticket_messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_internal', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('attachments_json', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('ticket_messages', schema=None) as batch_op:
        batch_op.drop_column('attachments_json')
        batch_op.drop_column('is_internal')

    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_constraint('fk_tickets_parent_id', type_='foreignkey')
        batch_op.drop_column('parent_id')
