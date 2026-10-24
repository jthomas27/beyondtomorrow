"""Moving a workflow must preserve project-relative input and corpus keys."""
from unittest.mock import AsyncMock

from pipeline.workflows import index


async def test_index_uses_project_root_after_module_move(tmp_path, monkeypatch):
    (tmp_path / "document.txt").write_text("A document for the corpus.")
    monkeypatch.setattr(index, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("pipeline.setup.init_openai", lambda: None)
    monkeypatch.setattr("pipeline.db.close_pool", AsyncMock())
    monkeypatch.setattr("pipeline.tools.corpus._is_source_indexed", AsyncMock(return_value=False))
    store = AsyncMock(return_value="Indexed")
    monkeypatch.setattr("pipeline.tools.corpus._index_document_impl", store)
    await index._run_index("INDEX: document.txt")
    assert store.await_args.args[:3] == (
        "A document for the corpus.", "document.txt", "article",
    )
