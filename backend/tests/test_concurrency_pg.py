"""Row-locking tests. SQLite ignores SELECT ... FOR UPDATE, so these only run on PostgreSQL:

    TEST_DATABASE_URL=postgresql+psycopg://user:pw@localhost/pharmatest pytest tests/test_concurrency_pg.py

They fire many simultaneous operations at limited stock and assert the invariants the ledger promises:
no overselling, no negative batches, and ledger sum == batch quantity.
"""
import threading
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models import Batch, InventoryMovement
from app.services import movements as mv
from tests.conftest import TEST_DB_URL, add_med, receive, register, login

pytestmark = pytest.mark.skipif(not (TEST_DB_URL or "").startswith("postgresql"),
                                reason="row-lock behaviour needs a real PostgreSQL (set TEST_DATABASE_URL)")


@pytest.fixture()
def setup(client):
    register(client)
    h = login(client, "a@example.com")
    med = add_med(client, h)
    me = client.get("/api/v1/auth/me", headers=h).json()
    engine = create_engine(TEST_DB_URL, pool_size=30, max_overflow=10)
    yield {"client": client, "h": h, "med": med["id"], "pharmacy_id": me["pharmacy_id"],
           "Session": sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)}
    engine.dispose()


def _run_parallel(n, worker):
    barrier = threading.Barrier(n)
    results = [None] * n

    def go(i):
        barrier.wait()                      # release all threads at the same instant
        try:
            results[i] = ("ok", worker(i))
        except mv.InventoryError as e:      # business-rule rejection is an expected outcome
            results[i] = ("rejected", e.code)
        except Exception as e:              # anything else (deadlock, constraint violation) is a failure
            results[i] = ("error", repr(e))

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    return results


def _sell(ctx, qty):
    def worker(_i):
        with ctx["Session"]() as db:
            try:
                mv.allocate_fefo(db, pharmacy_id=ctx["pharmacy_id"], medicine_id=ctx["med"], quantity=qty,
                                 movement_type="sale", user_id=None)
                db.commit()
            except Exception:
                db.rollback()
                raise
    return worker


def _assert_ledger_consistent(ctx):
    with ctx["Session"]() as db:
        for b in db.scalars(select(Batch).where(Batch.pharmacy_id == ctx["pharmacy_id"])):
            ledger = db.scalar(select(func.coalesce(func.sum(InventoryMovement.quantity), 0))
                               .where(InventoryMovement.batch_id == b.id))
            assert 0 <= b.quantity_remaining <= b.quantity_received
            assert ledger == b.quantity_remaining, f"batch {b.id}: ledger {ledger} != remaining {b.quantity_remaining}"


def test_parallel_sales_never_oversell_one_batch(setup):
    c = setup
    receive(c["client"], c["h"], c["med"], "B1", 200, 10)
    res = _run_parallel(25, _sell(c, 1))
    assert not [r for r in res if r[0] == "error"], res
    assert sum(r[0] == "ok" for r in res) == 10           # exactly the 10 units that existed
    assert sum(r[0] == "rejected" for r in res) == 15
    _assert_ledger_consistent(c)
    with c["Session"]() as db:
        assert db.scalar(select(func.sum(Batch.quantity_remaining))) == 0


def test_parallel_sales_across_two_batches_follow_fefo_without_deadlock(setup):
    c = setup
    receive(c["client"], c["h"], c["med"], "EARLY", 100, 5)
    receive(c["client"], c["h"], c["med"], "LATE", 200, 5)
    res = _run_parallel(8, _sell(c, 2))                   # each sale may span both batches
    assert not [r for r in res if r[0] == "error"], res
    assert sum(r[0] == "ok" for r in res) == 5            # 10 units / 2 per sale
    _assert_ledger_consistent(c)
    with c["Session"]() as db:
        early = db.scalar(select(Batch).where(Batch.batch_number == "EARLY"))
        late = db.scalar(select(Batch).where(Batch.batch_number == "LATE"))
        assert early.quantity_remaining == 0 and late.quantity_remaining == 0


def test_parallel_sales_and_write_offs_share_stock_safely(setup):
    c = setup
    batch_id = receive(c["client"], c["h"], c["med"], "B1", 200, 10)

    def write_off(_i):
        with c["Session"]() as db:
            try:
                mv.write_off(db, pharmacy_id=c["pharmacy_id"], batch_id=batch_id, quantity=1,
                             reason="damaged", user_id=None)
                db.commit()
            except Exception:
                db.rollback()
                raise

    sell = _sell(c, 1)
    res = _run_parallel(16, lambda i: sell(i) if i % 2 == 0 else write_off(i))
    assert not [r for r in res if r[0] == "error"], res
    assert sum(r[0] == "ok" for r in res) == 10
    _assert_ledger_consistent(c)


def test_parallel_receipts_to_same_medicine_all_succeed(setup):
    c = setup

    def recv(i):
        with c["Session"]() as db:
            mv.receive_batch(db, pharmacy_id=c["pharmacy_id"], medicine_id=c["med"], batch_number=f"R{i}",
                             expiration_date=date.today() + timedelta(days=100), quantity=3, unit_cost="1.00",
                             supplier_id=None, received_date=date.today(), user_id=None)
            db.commit()

    res = _run_parallel(12, recv)
    assert all(r[0] == "ok" for r in res), res
    _assert_ledger_consistent(c)
    with c["Session"]() as db:
        assert db.scalar(select(func.sum(Batch.quantity_remaining))) == 36
