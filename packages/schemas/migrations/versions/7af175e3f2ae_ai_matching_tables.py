"""ai matching tables

The shared core of AI matching (docs/ai/broker-api.md, makhzan_schemas.ai):
the judges as scored (`ai_model_versions`: a model version read through a
prompt version), the workers that score for them (`ai_workers`, a token's
sha256 each, and the model keys each serves), what the candidates trigger
last saw of each listing (`ai_listing_state`), the job queue (`ai_jobs`), the
scores (`ai_scores`, idempotent on the request's sha256), the decisions
(`ai_decisions`, one standing per pipeline and pair) and flags for a person
(`ai_flags`). Pairs are stored with `listing_a < listing_b`, as
`grouping_overrides` stores them.

Model keys, pipeline and stage names are plain strings validated against the
registry in code (`makhzan_schemas.ai.pipelines`), not database enums, so a
new model or pipeline needs no migration. No host slots or host groups: each
worker's configuration decides what runs (owner, 2026-11-17).

`listings.matched_via` and `matched_ai_decision_id` are written only by the
regroup. Expand-only and nullable: existing rows stay null (read as "rules")
until the next regroup. `matched_ai_decision_id` is not a foreign key, like
`products.min_price_listing_id`: `ai_decisions` already points at listings.

`worker_state['ai_matching']` starts at off (P4): nothing merges on an AI
decision until the owner sets it live. There is no shadow mode and no
per-decision shadow flag (owner, 2026-11-17).

Revision ID: 7af175e3f2ae
Revises: 96d1051aab62
Create Date: 2026-11-17 13:11:32.270127

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7af175e3f2ae"
down_revision: str | Sequence[str] | None = "96d1051aab62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ai_model_versions",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("model", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("weights_revision", sa.String(length=64), nullable=False),
        sa.Column("scoring", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_ai_model_version_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model", "model_version", "prompt_version", name="uq_ai_model_version_judge"
        ),
    )
    op.create_table(
        "ai_workers",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("token_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("models", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_hello", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("cardinality(models) > 0", name="ck_ai_worker_models"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("token_sha256"),
    )
    op.create_table(
        "ai_decisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("pipeline", sa.String(length=32), nullable=False),
        sa.Column("listing_a", sa.UUID(), nullable=False),
        sa.Column("listing_b", sa.UUID(), nullable=False),
        sa.Column("outcome", sa.String(length=8), nullable=False),
        sa.Column("decided_by", sa.String(length=32), nullable=False),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_version", sa.String(length=16), nullable=False),
        sa.Column("content_sha256_a", sa.LargeBinary(length=32), nullable=False),
        sa.Column("content_sha256_b", sa.LargeBinary(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="standing", nullable=False),
        sa.Column("effect", sa.String(length=16), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(length=100), nullable=True),
        sa.Column("revoke_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'revoked') = (revoked_at IS NOT NULL)", name="ck_ai_decision_revoked_at"
        ),
        sa.CheckConstraint(
            "effect IS NULL OR effect IN ('in_effect', 'blocked', 'inactive', 'overridden')",
            name="ck_ai_decision_effect",
        ),
        sa.CheckConstraint("outcome IN ('same', 'not_same')", name="ck_ai_decision_outcome"),
        sa.CheckConstraint(
            "state IN ('standing', 'stale', 'revoked')", name="ck_ai_decision_state"
        ),
        sa.CheckConstraint("listing_a < listing_b", name="ck_ai_decision_ordered"),
        sa.ForeignKeyConstraint(["listing_a"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_b"], ["listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_decision_listing_a", "ai_decisions", ["listing_a"], unique=False)
    op.create_index("ix_ai_decision_listing_b", "ai_decisions", ["listing_b"], unique=False)
    op.create_index(
        "uq_ai_decision_standing_pair",
        "ai_decisions",
        ["pipeline", "listing_a", "listing_b"],
        unique=True,
        postgresql_where=sa.text("state = 'standing'"),
    )
    op.create_table(
        "ai_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("pipeline", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("model_version_id", sa.SmallInteger(), nullable=False),
        sa.Column("listing_a", sa.UUID(), nullable=False),
        sa.Column("listing_b", sa.UUID(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), server_default="3", nullable=False),
        sa.Column("lease_id", sa.UUID(), nullable=True),
        sa.Column("leased_by", sa.SmallInteger(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_sha256", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_sha256_a", sa.LargeBinary(length=32), nullable=True),
        sa.Column("content_sha256_b", sa.LargeBinary(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'leased') = (lease_id IS NOT NULL)", name="ck_ai_job_leased_has_lease"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'leased', 'done', 'cancelled', 'dead')", name="ck_ai_job_status"
        ),
        sa.CheckConstraint("listing_a < listing_b", name="ck_ai_job_ordered"),
        sa.ForeignKeyConstraint(
            ["leased_by"],
            ["ai_workers.id"],
        ),
        sa.ForeignKeyConstraint(["listing_a"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_b"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["ai_model_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_job_lease",
        "ai_jobs",
        ["model_version_id", sa.literal_column("priority DESC"), "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_ai_job_lease_expiry",
        "ai_jobs",
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'leased'"),
    )
    op.create_index("ix_ai_job_pair", "ai_jobs", ["listing_a", "listing_b"], unique=False)
    op.create_index(
        "uq_ai_job_open_pair",
        "ai_jobs",
        ["pipeline", "stage", "model_version_id", "listing_a", "listing_b"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'leased')"),
    )
    op.create_table(
        "ai_listing_state",
        sa.Column("listing_id", sa.UUID(), nullable=False),
        sa.Column("content_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("content_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidates_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidates_sha256", sa.LargeBinary(length=32), nullable=True),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("listing_id"),
    )
    op.create_table(
        "ai_flags",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("listing_a", sa.UUID(), nullable=True),
        sa.Column("listing_b", sa.UUID(), nullable=True),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("model_version_id", sa.SmallInteger(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("resolved_by", sa.String(length=100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('rules_low_kev', 'poison_job', 'blocked_same', 'version_drift')",
            name="ck_ai_flag_kind",
        ),
        sa.CheckConstraint("status IN ('open', 'dismissed', 'actioned')", name="ck_ai_flag_status"),
        sa.CheckConstraint(
            "listing_a IS NULL OR listing_b IS NULL OR listing_a < listing_b",
            name="ck_ai_flag_ordered",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["ai_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["listing_a"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_b"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["ai_model_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_ai_flag_open",
        "ai_flags",
        ["kind", "listing_a", "listing_b"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        postgresql_nulls_not_distinct=True,
    )
    op.create_table(
        "ai_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("model_version_id", sa.SmallInteger(), nullable=False),
        sa.Column("listing_a", sa.UUID(), nullable=False),
        sa.Column("listing_b", sa.UUID(), nullable=False),
        sa.Column("reading_order", sa.String(length=2), nullable=False),
        sa.Column("request_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("content_sha256_a", sa.LargeBinary(length=32), nullable=False),
        sa.Column("content_sha256_b", sa.LargeBinary(length=32), nullable=False),
        sa.Column("p", sa.Float(), nullable=False),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("seconds", sa.Float(), nullable=True),
        sa.Column("device", sa.String(length=16), nullable=True),
        sa.Column("dtype", sa.String(length=16), nullable=True),
        sa.Column("threads", sa.SmallInteger(), nullable=True),
        sa.Column("worker_id", sa.SmallInteger(), nullable=True),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "scored_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("reading_order IN ('ab', 'ba')", name="ck_ai_score_order"),
        sa.CheckConstraint("listing_a < listing_b", name="ck_ai_score_ordered"),
        sa.CheckConstraint("p >= 0 AND p <= 1", name="ck_ai_score_p"),
        sa.ForeignKeyConstraint(["job_id"], ["ai_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["listing_a"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_b"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["ai_model_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["ai_workers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_version_id", "request_sha256", name="uq_ai_score_request"),
    )
    op.create_index("ix_ai_score_pair", "ai_scores", ["listing_a", "listing_b"], unique=False)
    op.add_column("listings", sa.Column("matched_via", sa.String(length=8), nullable=True))
    op.add_column("listings", sa.Column("matched_ai_decision_id", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "ck_listing_matched_via",
        "listings",
        "matched_via IS NULL OR matched_via IN ('rules', 'ai')",
    )
    op.create_check_constraint(
        "ck_listing_matched_ai_decision",
        "listings",
        "matched_ai_decision_id IS NULL OR matched_via = 'ai'",
    )
    # Off until the owner says live (P4). A missing row reads as off too.
    op.execute(
        "INSERT INTO worker_state (key, value) VALUES ('ai_matching', '{\"mode\": \"off\"}') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM worker_state WHERE key = 'ai_matching'")
    op.drop_constraint("ck_listing_matched_ai_decision", "listings", type_="check")
    op.drop_constraint("ck_listing_matched_via", "listings", type_="check")
    op.drop_column("listings", "matched_ai_decision_id")
    op.drop_column("listings", "matched_via")
    op.drop_index("ix_ai_score_pair", table_name="ai_scores")
    op.drop_table("ai_scores")
    op.drop_index(
        "uq_ai_flag_open", table_name="ai_flags", postgresql_where=sa.text("status = 'open'")
    )
    op.drop_table("ai_flags")
    op.drop_table("ai_listing_state")
    op.drop_index(
        "uq_ai_job_open_pair",
        table_name="ai_jobs",
        postgresql_where=sa.text("status IN ('queued', 'leased')"),
    )
    op.drop_index("ix_ai_job_pair", table_name="ai_jobs")
    op.drop_index(
        "ix_ai_job_lease_expiry",
        table_name="ai_jobs",
        postgresql_where=sa.text("status = 'leased'"),
    )
    op.drop_index(
        "ix_ai_job_lease", table_name="ai_jobs", postgresql_where=sa.text("status = 'queued'")
    )
    op.drop_table("ai_jobs")
    op.drop_index(
        "uq_ai_decision_standing_pair",
        table_name="ai_decisions",
        postgresql_where=sa.text("state = 'standing'"),
    )
    op.drop_index("ix_ai_decision_listing_b", table_name="ai_decisions")
    op.drop_index("ix_ai_decision_listing_a", table_name="ai_decisions")
    op.drop_table("ai_decisions")
    op.drop_table("ai_workers")
    op.drop_table("ai_model_versions")
