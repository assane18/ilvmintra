"""form engine: condition_field à plusieurs valeurs déclenchantes

Revision ID: d5a71c3f8b6e
Revises: c4d81f6e9a02
Create Date: 2026-09-22 00:00:00.000000

"""
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5a71c3f8b6e'
down_revision = 'c4d81f6e9a02'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('form_fields', schema=None) as batch_op:
        batch_op.add_column(sa.Column('condition_values_json', sa.Text(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, condition_value FROM form_fields WHERE condition_value IS NOT NULL"
    )).fetchall()
    for row_id, value in rows:
        conn.execute(
            sa.text("UPDATE form_fields SET condition_values_json = :vals WHERE id = :id"),
            {"vals": json.dumps([value]), "id": row_id},
        )

    with op.batch_alter_table('form_fields', schema=None) as batch_op:
        batch_op.drop_column('condition_value')


def downgrade():
    with op.batch_alter_table('form_fields', schema=None) as batch_op:
        batch_op.add_column(sa.Column('condition_value', sa.String(length=255), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, condition_values_json FROM form_fields WHERE condition_values_json IS NOT NULL"
    )).fetchall()
    for row_id, values_json in rows:
        try:
            values = json.loads(values_json) or []
        except (ValueError, TypeError):
            values = []
        first = values[0] if values else None
        conn.execute(
            sa.text("UPDATE form_fields SET condition_value = :v WHERE id = :id"),
            {"v": first, "id": row_id},
        )

    with op.batch_alter_table('form_fields', schema=None) as batch_op:
        batch_op.drop_column('condition_values_json')
