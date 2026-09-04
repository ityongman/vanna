import numpy as np
import pytest

from vanna.capabilities.schema_vector_store import SchemaColumn, SchemaTable
from vanna.integrations.vector.faiss.schema_vector_store import FAISSSchemaVectorStore


def embed_fn(texts):
    vecs = []
    for t in texts:
        v = np.zeros(4, dtype="float32")
        v[0] = float(len(t))
        vecs.append(v)
    return np.asarray(vecs, dtype="float32")


async def make_store(tmp_path):
    store = FAISSSchemaVectorStore(persist_dir=str(tmp_path), embed_fn=embed_fn)
    t1 = SchemaTable(
        table_name="users",
        columns=[SchemaColumn(column_name="id", table_name="users", data_type="INTEGER")],
    )
    t2 = SchemaTable(
        table_name="orders",
        columns=[SchemaColumn(column_name="id", table_name="orders", data_type="INTEGER")],
    )
    await store.ingest_schema([t1, t2], [], "ns_a")
    return store


@pytest.mark.asyncio
async def test_list_tables(tmp_path):
    store = await make_store(tmp_path)
    tables = await store.list_tables("ns_a")
    names = {t.table_name for t in tables}
    assert names == {"users", "orders"}


@pytest.mark.asyncio
async def test_remove_table(tmp_path):
    store = await make_store(tmp_path)
    removed = await store.remove_table("users", "ns_a")
    assert removed == 1
    tables = await store.list_tables("ns_a")
    assert [t.table_name for t in tables] == ["orders"]
