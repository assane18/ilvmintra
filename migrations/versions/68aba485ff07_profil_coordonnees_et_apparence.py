"""profil: coordonnées éditables + préférences d'apparence

Revision ID: 68aba485ff07
Revises: 9d13d3b4a085
Create Date: 2026-09-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '68aba485ff07'
down_revision = '9d13d3b4a085'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phone', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('office', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('theme_mode', sa.String(length=10), nullable=True, server_default='auto'))
        batch_op.add_column(sa.Column('font_scale', sa.String(length=10), nullable=True, server_default='normal'))
        batch_op.add_column(sa.Column('density', sa.String(length=12), nullable=True, server_default='comfortable'))
        batch_op.add_column(sa.Column('high_contrast', sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('high_contrast')
        batch_op.drop_column('density')
        batch_op.drop_column('font_scale')
        batch_op.drop_column('theme_mode')
        batch_op.drop_column('office')
        batch_op.drop_column('phone')
