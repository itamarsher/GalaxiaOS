"""Baseline schema.

Creates the pgvector extension, then materialises every table from the ORM
metadata (a legitimate baseline pattern for an initial migration), and adds the
HNSW index for memory-entry embeddings. Subsequent migrations use autogenerate.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-12
"""

from alembic import op

from app.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_entries_embedding "
        "ON memory_entries USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP INDEX IF EXISTS ix_memory_entries_embedding")
    Base.metadata.drop_all(bind=bind)
