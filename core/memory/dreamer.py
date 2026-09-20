from core.memory.store import init_db
import litellm
import json
import uuid
from datetime import datetime, timezone

async def run_memory_consolidation():
    conn = init_db()
    try:
        # Fetch frequently accessed generic or devops memories
        c = conn.cursor()
        c.execute("""
            SELECT id, content, domain, use_count 
            FROM memory_entries 
            WHERE use_count > 0 AND authorship = 'agent-created'
            ORDER BY created_at ASC
        """)
        memories = c.fetchall()
        
        if len(memories) < 2:
            return # Nothing to consolidate
            
        grouped_by_domain = {}
        for m in memories:
            domain = m[2]
            grouped_by_domain.setdefault(domain, []).append(m)
            
        from core.secrets import get_secret
        import os
        model = os.getenv("HARNESS_MODEL") or os.getenv("GROK_MODEL") or "groq/openai/gpt-oss-120b"
        api_key = get_secret("groq", "api_key")
        
        consolidated_themes = []
        
        for domain, mem_list in grouped_by_domain.items():
            if len(mem_list) < 2:
                continue
                
            contents = [m[1] for m in mem_list]
            prompt = (
                "You are a memory consolidation assistant. Read the following memories and output a single, unified summary "
                "that condenses them, removing duplicates and stale configurations. Keep technical details intact.\n\nMemories:\n"
                + "\n".join(f"- {c}" for c in contents)
            )
            
            response = await litellm.acompletion(
                model=model,
                api_key=api_key,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = response.choices[0].message.content
            
            new_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            
            c.execute("""
                INSERT INTO memory_entries (id, content, authorship, provenance, domain, created_at, use_count)
                VALUES (?, ?, 'agent-created', 'tool-observed', ?, ?, 1)
            """, (new_id, f"CONSOLIDATED THEME: {summary}", domain, now))
            
            # Delete old memories
            ids_to_drop = [m[0] for m in mem_list]
            c.execute(f"DELETE FROM memory_entries WHERE id IN ({','.join(['?']*len(ids_to_drop))})", ids_to_drop)
            
            consolidated_themes.append(summary)
            
        conn.commit()
        return consolidated_themes
    finally:
        conn.close()
