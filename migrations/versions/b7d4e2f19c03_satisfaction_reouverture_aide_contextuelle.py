"""tickets: satisfaction + réouverture ; aide contextuelle + réponses types

Revision ID: b7d4e2f19c03
Revises: 68aba485ff07
Create Date: 2026-09-28 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d4e2f19c03'
down_revision = '68aba485ff07'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('satisfaction', sa.SmallInteger(), nullable=True))
        batch_op.add_column(sa.Column('satisfaction_comment', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('satisfaction_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('reopen_count', sa.Integer(), nullable=True, server_default='0'))

    op.create_table(
        'help_tips',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('context', sa.String(length=60), nullable=False, index=True),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('link', sa.String(length=255), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
    )
    op.create_table(
        'canned_responses',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('service', sa.String(length=60), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
    )


def downgrade():
    op.drop_table('canned_responses')
    op.drop_table('help_tips')
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_column('reopen_count')
        batch_op.drop_column('satisfaction_at')
        batch_op.drop_column('satisfaction_comment')
        batch_op.drop_column('satisfaction')
