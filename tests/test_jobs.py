import time

from app.jobs import JOBS


def test_job_success():
    def work(progress):
        progress(0.5, "наполовину")
        return {"done": True}

    job = JOBS.submit("test", work)
    assert JOBS.wait_idle(10)
    snapshot = job.snapshot()
    assert snapshot["status"] == "done"
    assert snapshot["progress"] == 1.0
    assert snapshot["result"] == {"done": True}
    assert "наполовину" in snapshot["log"]


def test_job_failure():
    def work(progress):
        raise RuntimeError("сломалось")

    job = JOBS.submit("test", work)
    assert JOBS.wait_idle(10)
    snapshot = job.snapshot()
    assert snapshot["status"] == "failed"
    assert "сломалось" in snapshot["error"]
