"""profil: préférence de style visuel (thème "verre")

Revision ID: c1c1c1c1c1c1
Revises: b9b9b9b9b9b9
Create Date: 2026-11-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1c1c1c1c1c1'
down_revision = 'b9b9b9b9b9b9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('theme_style', sa.String(length=10), nullable=True, server_default='flat'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('theme_style')
