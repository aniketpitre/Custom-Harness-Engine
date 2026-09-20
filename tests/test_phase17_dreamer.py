import pytest
from core.memory.store import init_db
from core.memory.dreamer import run_memory_consolidation
import uuid
import datetime

@pytest.fixture
def temp_db_with_memories(tmp_path, monkeypatch):
    db_path = tmp_path / "test_memory.db"
    
    def mock_init_db():
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                authorship TEXT NOT NULL CHECK (authorship IN ('human-authored','agent-created')),
                provenance TEXT NOT NULL CHECK (provenance IN ('user-input','tool-observed','external-fetched','human-reviewed')),
                domain TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                use_count INTEGER NOT NULL DEFAULT 0
            );
        """)
        return conn

    monkeypatch.setattr("core.memory.dreamer.init_db", mock_init_db)
    
    conn = mock_init_db()
    c = conn.cursor()
    # Insert 2 agent-created memories
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    c.execute("INSERT INTO memory_entries VALUES (?, ?, 'agent-created', 'tool-observed', 'devops', ?, NULL, 2)", (str(uuid.uuid4()), "Memory 1", now))
    c.execute("INSERT INTO memory_entries VALUES (?, ?, 'agent-created', 'tool-observed', 'devops', ?, NULL, 2)", (str(uuid.uuid4()), "Memory 2", now))
    conn.commit()
    conn.close()
    return db_path

@pytest.mark.asyncio
async def test_run_memory_consolidation(temp_db_with_memories, monkeypatch):
    async def mock_acompletion(*args, **kwargs):
        class MockMessage:
            def __init__(self):
                self.content = "Consolidated summary"
        class MockChoice:
            def __init__(self):
                self.message = MockMessage()
        class MockResponse:
            def __init__(self):
                self.choices = [MockChoice()]
        return MockResponse()

    monkeypatch.setattr("litellm.acompletion", mock_acompletion)
    monkeypatch.setattr("core.secrets.get_secret", lambda a, b: "mock-secret")

    themes = await run_memory_consolidation()
    assert len(themes) == 1
    assert themes[0] == "Consolidated summary"
    
    # Check DB
    import sqlite3
    conn = sqlite3.connect(temp_db_with_memories)
    c = conn.cursor()
    c.execute("SELECT content FROM memory_entries")
    rows = c.fetchall()
    
    # Only 1 memory left
    assert len(rows) == 1
    assert "CONSOLIDATED THEME: Consolidated summary" in rows[0][0]

