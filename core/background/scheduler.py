from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
from core.memory.store import init_db, create_session
import uuid
import json

scheduler = AsyncIOScheduler()

async def scheduled_session_job(agent_id: str, goal: str, environment: dict):
    from core.gateway.api import execute_session
    session_id = str(uuid.uuid4())
    conn = init_db()
    try:
        create_session(conn, session_id, agent_id, goal, environment)
    finally:
        conn.close()
    
    # We call execute_session. Since we are in the scheduler, we run it directly.
    await execute_session(session_id, agent_id, goal)

def add_agent_cron_job(cron_expr: str, agent_id: str, goal: str, environment: dict = None):
    if environment is None:
        environment = {}
        
    trigger = CronTrigger.from_crontab(cron_expr)
    job = scheduler.add_job(
        scheduled_session_job,
        trigger=trigger,
        args=[agent_id, goal, environment]
    )
    return job.id

def start_scheduler():
    if not scheduler.running:
        scheduler.start()
