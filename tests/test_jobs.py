from pipeline.db import transaction
from pipeline.fetch import jobs


def test_enqueue_is_idempotent(conn):
    assert jobs.enqueue(conn, "items", ["1", "2", "3"]) == 3
    assert jobs.enqueue(conn, "items", ["2", "3", "4"]) == 1
    assert jobs.counts(conn)["items"] == {"pending": 4, "done": 0, "failed": 0}


def test_claim_in_insertion_order_and_done_not_reclaimed(conn):
    jobs.enqueue(conn, "items", ["30", "4", "100"])
    assert jobs.claim(conn, "items", 2) == ["30", "4"]
    with transaction(conn):
        jobs.mark_done(conn, "items", ["30", "4"])
    assert jobs.claim(conn, "items", 10) == ["100"]


def test_claim_without_done_leaves_jobs_pending(conn):
    """Simulates a crash between claim and commit: nothing is lost."""
    jobs.enqueue(conn, "items", ["1", "2"])
    jobs.claim(conn, "items", 2)
    assert jobs.claim(conn, "items", 2) == ["1", "2"]


def test_rollback_keeps_job_pending(conn):
    jobs.enqueue(conn, "items", ["1"])
    try:
        with transaction(conn):
            jobs.mark_done(conn, "items", ["1"])
            raise RuntimeError("crash mid-write")
    except RuntimeError:
        pass
    assert jobs.pending_count(conn, "items") == 1


def test_failed_after_max_attempts_then_retry(conn):
    jobs.enqueue(conn, "items", ["1"])
    jobs.mark_failed_attempt(conn, "items", ["1"], "boom", max_attempts=2)
    assert jobs.pending_count(conn, "items") == 1
    jobs.mark_failed_attempt(conn, "items", ["1"], "boom", max_attempts=2)
    assert jobs.counts(conn)["items"]["failed"] == 1
    assert jobs.retry_failed(conn, "items") == 1
    assert jobs.pending_count(conn, "items") == 1


def test_requeue_stale(conn):
    jobs.enqueue(conn, "items", ["1"])
    with transaction(conn):
        jobs.mark_done(conn, "items", ["1"])
    assert jobs.requeue_stale(conn, "items", older_than_s=3600) == 0
    assert jobs.requeue_stale(conn, "items", older_than_s=-1) == 1
