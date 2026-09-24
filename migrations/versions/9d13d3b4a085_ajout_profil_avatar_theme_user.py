"""ajout profil avatar/theme sur User

Revision ID: 9d13d3b4a085
Revises: b1e6f4a08c92
Create Date: 2026-09-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9d13d3b4a085'
down_revision = 'b1e6f4a08c92'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar_photo', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('avatar_initials', sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column('theme_color', sa.String(length=20), nullable=True, server_default='teal'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('theme_color')
        batch_op.drop_column('avatar_initials')
        batch_op.drop_column('avatar_photo')
