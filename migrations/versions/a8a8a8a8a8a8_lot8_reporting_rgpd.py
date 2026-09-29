"""Lot 8 : journal d'audit (reporting et conformité RGPD)

Revision ID: a8a8a8a8a8a8
Revises: a7a7a7a7a7a7
Create Date: 2026-09-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8a8a8a8a8a8'
down_revision = 'a7a7a7a7a7a7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('username', sa.String(length=64), nullable=True),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('target_type', sa.String(length=40), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('target_ref', sa.String(length=100), nullable=True),
        sa.Column('details', sa.String(length=500), nullable=True),
        sa.Column('ip', sa.String(length=45), nullable=True),
    )
    op.create_index('ix_audit_logs_timestamp', 'audit_logs', ['timestamp'])
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_target_id', 'audit_logs', ['target_id'])


def downgrade():
    op.drop_index('ix_audit_logs_target_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_index('ix_audit_logs_user_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_timestamp', table_name='audit_logs')
    op.drop_table('audit_logs')
