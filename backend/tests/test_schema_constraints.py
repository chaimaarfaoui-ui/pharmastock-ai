import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.db import Base
from app.models import Batch, Medicine, Pharmacy


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        p = Pharmacy(name="P")
        s.add(p); s.flush()
        m = Medicine(pharmacy_id=p.id, name="Paracetamol")
        s.add(m); s.flush()
        s.info["ids"] = (p.id, m.id)
        yield s


def _batch(db, **kw):
    pid, mid = db.info["ids"]
    base = dict(pharmacy_id=pid, medicine_id=mid, batch_number="B1", expiration_date=date(2027, 1, 1),
                quantity_received=100, quantity_remaining=100, unit_cost=1, received_date=date(2026, 1, 1))
    base.update(kw)
    return Batch(**base)


def test_negative_remaining_rejected(db):
    db.add(_batch(db, quantity_remaining=-1))
    with pytest.raises(IntegrityError):
        db.flush()


def test_remaining_cannot_exceed_received(db):
    db.add(_batch(db, quantity_remaining=101))
    with pytest.raises(IntegrityError):
        db.flush()


def test_duplicate_batch_number_rejected(db):
    db.add(_batch(db)); db.flush()
    db.add(_batch(db))
    with pytest.raises(IntegrityError):
        db.flush()
