"""Lot 5 — délais et pilotage : paramètres applicatifs (app_settings) et trace
des escalades de validation (escalation_traces).

Revision ID: a5a5a5a5a5a5
Revises: e4c7d9a2b6f1
Create Date: 2026-09-29 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a5a5a5a5a5a5'
down_revision = 'e4c7d9a2b6f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=60), primary_key=True),
        sa.Column('value', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'escalation_traces',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_type', sa.String(length=20), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('sent_on', sa.Date(), nullable=False),
        sa.Column('recipients', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('item_type', 'item_id', 'level', 'sent_on', name='uq_escalation_trace_day'),
    )
    op.create_index('ix_escalation_traces_sent_on', 'escalation_traces', ['sent_on'])


def downgrade():
    op.drop_index('ix_escalation_traces_sent_on', table_name='escalation_traces')
    op.drop_table('escalation_traces')
    op.drop_table('app_settings')
