import pytest
from core.background.scheduler import add_agent_cron_job, start_scheduler, scheduler

@pytest.mark.asyncio
async def test_scheduler_adds_jobs():
    start_scheduler()
    
    job_id = add_agent_cron_job("* * * * *", "test_agent", "Test scheduled goal")
    job = scheduler.get_job(job_id)
    assert job is not None
    assert job.args[0] == "test_agent"
    assert job.args[1] == "Test scheduled goal"
