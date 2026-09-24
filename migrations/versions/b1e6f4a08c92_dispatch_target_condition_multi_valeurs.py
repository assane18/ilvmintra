"""form engine: condition de destinataire (FormDispatchTarget) à plusieurs valeurs

Revision ID: b1e6f4a08c92
Revises: a9d34c8e2f17
Create Date: 2026-09-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1e6f4a08c92'
down_revision = 'a9d34c8e2f17'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('form_dispatch_targets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('condition_values_json', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('form_dispatch_targets', schema=None) as batch_op:
        batch_op.drop_column('condition_values_json')
