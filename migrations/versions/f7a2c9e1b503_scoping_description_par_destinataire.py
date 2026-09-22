"""form engine: scoping de la description générique par destinataire

Revision ID: f7a2c9e1b503
Revises: e6f92b1c7d34
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f7a2c9e1b503'
down_revision = 'e6f92b1c7d34'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('form_dispatch_targets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('included_description_fields_json', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('form_dispatch_targets', schema=None) as batch_op:
        batch_op.drop_column('included_description_fields_json')
