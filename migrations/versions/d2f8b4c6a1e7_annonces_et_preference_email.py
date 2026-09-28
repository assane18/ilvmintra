"""annonces du portail + préférence e-mail par utilisateur

Revision ID: d2f8b4c6a1e7
Revises: c9e1a7b3d5f2
Create Date: 2026-09-28 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2f8b4c6a1e7'
down_revision = 'c9e1a7b3d5f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_mode', sa.String(length=10), nullable=True, server_default='all'))
    op.create_table(
        'announcements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('level', sa.String(length=10), nullable=True, server_default='info'),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )


def downgrade():
    op.drop_table('announcements')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('email_mode')
