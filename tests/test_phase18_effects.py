import pytest
import asyncio
from core.agent_engine import EffectStack

@pytest.mark.asyncio
async def test_effect_stack_rollback_executes_disposers():
    stack = EffectStack()
    disposed = False

    def disposer():
        nonlocal disposed
        disposed = True

    stack.push("test_invoker", disposer)
    await stack.rollback()
    assert disposed is True

@pytest.mark.asyncio
async def test_effect_stack_rollback_lifo_order():
    stack = EffectStack()
    log = []

    def disposer1():
        log.append(1)

    def disposer2():
        log.append(2)

    stack.push("invoker1", disposer1)
    stack.push("invoker2", disposer2)

    await stack.rollback()

    assert log == [2, 1]
