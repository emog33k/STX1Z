"""initial schema

Revision ID: a5bd7f165773
Revises: 
Create Date: 2026-08-22 07:44:08.383746+00:00
"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a5bd7f165773'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('genres',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('genres', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_genres_slug'), ['slug'], unique=True)

    op.create_table('titles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('type', sa.Enum('movie', 'series', name='titletype', native_enum=False, length=20), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('name_normalized', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('poster_url', sa.String(length=2048), nullable=True),
    sa.Column('backdrop_url', sa.String(length=2048), nullable=True),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('embed_url', sa.String(length=2048), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint('year IS NULL OR (year >= 1888 AND year <= 2200)', name='ck_titles_year'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name_normalized', 'year', 'type', name='uq_titles_name_year_type')
    )
    with op.batch_alter_table('titles', schema=None) as batch_op:
        batch_op.create_index('ix_titles_created_at', ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_titles_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_titles_name_normalized'), ['name_normalized'], unique=False)
        batch_op.create_index(batch_op.f('ix_titles_type'), ['type'], unique=False)
        batch_op.create_index('ix_titles_type_year', ['type', 'year'], unique=False)
        batch_op.create_index(batch_op.f('ix_titles_year'), ['year'], unique=False)

    op.create_table('episodes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title_id', sa.Integer(), nullable=False),
    sa.Column('season_number', sa.Integer(), nullable=False),
    sa.Column('episode_number', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('embed_url', sa.String(length=2048), nullable=True),
    sa.CheckConstraint('episode_number >= 1', name='ck_episodes_episode_number'),
    sa.CheckConstraint('season_number >= 1', name='ck_episodes_season_number'),
    sa.ForeignKeyConstraint(['title_id'], ['titles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('title_id', 'season_number', 'episode_number', name='uq_episodes_position')
    )
    with op.batch_alter_table('episodes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_episodes_title_id'), ['title_id'], unique=False)

    op.create_table('title_genres',
    sa.Column('title_id', sa.Integer(), nullable=False),
    sa.Column('genre_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['genre_id'], ['genres.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['title_id'], ['titles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('title_id', 'genre_id')
    )
    with op.batch_alter_table('title_genres', schema=None) as batch_op:
        batch_op.create_index('ix_title_genres_genre_id', ['genre_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('title_genres', schema=None) as batch_op:
        batch_op.drop_index('ix_title_genres_genre_id')

    op.drop_table('title_genres')
    with op.batch_alter_table('episodes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_episodes_title_id'))

    op.drop_table('episodes')
    with op.batch_alter_table('titles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_titles_year'))
        batch_op.drop_index('ix_titles_type_year')
        batch_op.drop_index(batch_op.f('ix_titles_type'))
        batch_op.drop_index(batch_op.f('ix_titles_name_normalized'))
        batch_op.drop_index(batch_op.f('ix_titles_name'))
        batch_op.drop_index('ix_titles_created_at')

    op.drop_table('titles')
    with op.batch_alter_table('genres', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_genres_slug'))

    op.drop_table('genres')
