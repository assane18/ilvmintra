"""form engine: scoping des champs mappés par destinataire

Revision ID: b3c7e2f4a891
Revises: a1f3c9d07b22
Create Date: 2026-09-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3c7e2f4a891'
down_revision = 'a1f3c9d07b22'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('form_dispatch_targets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('included_mapped_fields_json', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('form_dispatch_targets', schema=None) as batch_op:
        batch_op.drop_column('included_mapped_fields_json')
