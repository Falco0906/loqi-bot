"""Workflow Scheduler — lightweight scheduler for delayed execution.

Supports both asyncio (preferred) and threading.Timer (fallback).
No cron, no Celery.
"""

import asyncio
import threading
from typing import Optional, Callable


_scheduled_tasks: dict[str, object] = {}
_scheduler_lock = threading.Lock()


def _log(msg: str) -> None:
    print(f"[workflow_scheduler] {msg}")


def schedule(workflow_id: str, delay_seconds: float, callback: Callable, *args) -> bool:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return _schedule_async(workflow_id, delay_seconds, callback, args)
    except RuntimeError:
        pass
    return _schedule_thread(workflow_id, delay_seconds, callback, args)


def _schedule_async(workflow_id: str, delay_seconds: float, callback: Callable, args: tuple) -> bool:
    loop = asyncio.get_event_loop()

    async def _run():
        await asyncio.sleep(delay_seconds)
        try:
            _log(f"Executing scheduled callback for {workflow_id}")
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            _log(f"Scheduled callback failed for {workflow_id}: {e}")
        finally:
            with _scheduler_lock:
                _scheduled_tasks.pop(workflow_id, None)

    with _scheduler_lock:
        if workflow_id in _scheduled_tasks:
            _cancel_existing(workflow_id)
        task = loop.create_task(_run())
        _scheduled_tasks[workflow_id] = task
    _log(f"Scheduled async {workflow_id} in {delay_seconds}s")
    return True


def _schedule_thread(workflow_id: str, delay_seconds: float, callback: Callable, args: tuple) -> bool:
    timer = threading.Timer(delay_seconds, lambda: _thread_execute(workflow_id, callback, args))
    timer.daemon = True
    with _scheduler_lock:
        if workflow_id in _scheduled_tasks:
            _cancel_existing(workflow_id)
        _scheduled_tasks[workflow_id] = timer
    timer.start()
    _log(f"Scheduled thread {workflow_id} in {delay_seconds}s")
    return True


def _thread_execute(workflow_id: str, callback: Callable, args: tuple) -> None:
    try:
        _log(f"Executing scheduled callback for {workflow_id}")
        callback(*args)
    except Exception as e:
        _log(f"Scheduled callback failed for {workflow_id}: {e}")
    finally:
        with _scheduler_lock:
            _scheduled_tasks.pop(workflow_id, None)


def _cancel_existing(workflow_id: str) -> None:
    existing = _scheduled_tasks.get(workflow_id)
    if existing is None:
        return
    if isinstance(existing, asyncio.Task) and not existing.done():
        existing.cancel()
    elif isinstance(existing, threading.Timer):
        existing.cancel()


def cancel_scheduled(workflow_id: str) -> bool:
    with _scheduler_lock:
        task = _scheduled_tasks.pop(workflow_id, None)
        if task is None:
            return False
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()
        elif isinstance(task, threading.Timer):
            task.cancel()
        _log(f"Cancelled scheduled task for {workflow_id}")
        return True
    return False


def cancel_all() -> int:
    count = 0
    with _scheduler_lock:
        for wid, task in list(_scheduled_tasks.items()):
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
                count += 1
            elif isinstance(task, threading.Timer):
                task.cancel()
                count += 1
        _scheduled_tasks.clear()
    _log(f"Cancelled {count} scheduled tasks")
    return count
