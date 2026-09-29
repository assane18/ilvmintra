"""Lot 7 — organisation des demandes : délégations de validation, demande au
nom de quelqu'un d'autre (tickets.created_by_id, form_submissions.created_by_id)

Revision ID: a7a7a7a7a7a7
Revises: a6a6a6a6a6a6
Create Date: 2026-09-29 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7a7a7a7a7a7'
down_revision = 'a6a6a6a6a6a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'validation_delegations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('delegator_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('delegate_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_validation_delegations_delegator_id', 'validation_delegations', ['delegator_id'])
    op.create_index('ix_validation_delegations_delegate_id', 'validation_delegations', ['delegate_id'])

    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    with op.batch_alter_table('form_submissions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))


def downgrade():
    with op.batch_alter_table('form_submissions', schema=None) as batch_op:
        batch_op.drop_column('created_by_id')
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_column('created_by_id')
    op.drop_index('ix_validation_delegations_delegate_id', table_name='validation_delegations')
    op.drop_index('ix_validation_delegations_delegator_id', table_name='validation_delegations')
    op.drop_table('validation_delegations')
