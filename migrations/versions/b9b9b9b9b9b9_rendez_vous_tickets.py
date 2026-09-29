"""rendez-vous sur ticket : propositions, réponses du demandeur, rappels

Revision ID: b9b9b9b9b9b9
Revises: a8a8a8a8a8a8
Create Date: 2026-09-29 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9b9b9b9b9b9'
down_revision = 'a8a8a8a8a8a8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'appointments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id'), nullable=False, index=True),
        sa.Column('proposed_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='proposed', index=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('response_comment', sa.Text(), nullable=True),
        sa.Column('slots_json', sa.Text(), nullable=True),
        sa.Column('direct', sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.Column('reminder_sent_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('appointments')
