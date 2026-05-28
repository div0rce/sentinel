"""ORM metadata invariants that must stay aligned with the M1 migration."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from backend.app.models import SCHEMA_EMBEDDING_DIM, Chunk

ROOT = Path(__file__).resolve().parents[2]
INITIAL_MIGRATION = ROOT / "backend/alembic/versions/20260528_0001_initial_schema.py"


def _load_initial_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("initial_schema", INITIAL_MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chunk_embedding_metadata_is_canonical_vector_1536() -> None:
    column_type = cast(Any, Chunk.__table__.c.embedding.type)

    assert SCHEMA_EMBEDDING_DIM == 1536
    assert column_type.dim == SCHEMA_EMBEDDING_DIM
    assert str(column_type) == "VECTOR(1536)"


def test_runtime_embedding_dim_env_does_not_change_orm_metadata() -> None:
    env = os.environ.copy()
    env["EMBEDDING_DIM"] = "1024"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from backend.app.models import Chunk, SCHEMA_EMBEDDING_DIM; "
                "print(json.dumps({'schema_dim': SCHEMA_EMBEDDING_DIM, "
                "'column_dim': Chunk.__table__.c.embedding.type.dim}))"
            ),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"schema_dim": 1536, "column_dim": 1536}


def test_schema_embedding_dim_matches_initial_migration() -> None:
    migration = _load_initial_migration()

    assert migration.EMBEDDING_DIM == SCHEMA_EMBEDDING_DIM
