"""délais cibles (SLA) par service/catégorie + traçabilité des validations manager

Revision ID: e4c7d9a2b6f1
Revises: d2f8b4c6a1e7
Create Date: 2026-09-28 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4c7d9a2b6f1'
down_revision = 'd2f8b4c6a1e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sla_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('service', sa.String(length=60), nullable=False, index=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('hours', sa.Integer(), nullable=False, server_default='24'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
    )
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('validated_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('validated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    with op.batch_alter_table('form_submissions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_validated_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('validated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))


def downgrade():
    with op.batch_alter_table('form_submissions', schema=None) as batch_op:
        batch_op.drop_column('validated_by_id')
        batch_op.drop_column('last_validated_at')
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_column('validated_by_id')
        batch_op.drop_column('validated_at')
    op.drop_table('sla_rules')
