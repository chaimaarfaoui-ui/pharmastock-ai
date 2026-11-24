import random
from datetime import date, timedelta
import pytest
from tests.conftest import login, make_user, register
from tests.test_api_planning import FAST, run_job

API = "/api/v1"


def up(client, h, kind, text, dry=True, name="data.csv", raw=None):
    body = raw if raw is not None else text.encode("utf-8")
    return client.post(f"{API}/imports/{kind}?dry_run={'true' if dry else 'false'}", headers=h, files={"file": (name, body, "text/csv")})


def med_count(client, h):
    return client.get(f"{API}/medicines?limit=200", headers=h).json()["total"]


MEDS = "name,brand,active_ingredient,dosage,formulation,category,purchase_price,selling_price,min_stock_threshold\n" \
       "Paracetamol 500mg,Generic,paracetamol,500mg,tablet,Analgesics,0.05,0.08,100\n" \
       "Amoxicillin 500mg,,amoxicillin,500mg,capsule,Antibiotics,\"0,20\",0.30,50\n"


def test_dry_run_changes_nothing_then_commit_imports(client, admin):
    r = up(client, admin, "medicines", MEDS, dry=True).json()
    assert r["error_count"] == 0 and r["committed"] is False and r["would_create"] == {"medicines": 2, "categories": 2}
    assert med_count(client, admin) == 0                                  # dry run leaves no trace
    r = up(client, admin, "medicines", MEDS, dry=False).json()
    assert r["committed"] is True and r["created"]["medicines"] == 2
    meds = {m["name"]: m for m in client.get(f"{API}/medicines", headers=admin).json()["items"]}
    assert meds["Amoxicillin 500mg"]["purchase_price"] == "0.20" and meds["Paracetamol 500mg"]["category_name"] == "Analgesics"   # '0,20' decimal comma accepted
    dup = up(client, admin, "medicines", MEDS, dry=False).json()           # importing the same file again
    assert dup["error_count"] == 2 and dup["committed"] is False and med_count(client, admin) == 2


def test_row_errors_are_reported_with_row_numbers_and_nothing_is_imported(client, admin):
    bad = "name,purchase_price,min_stock_threshold\nGood Drug,1.5,10\n,2,5\nBad Price,abc,5\nNeg,-1,5\nFrac,1,2.5\n" + "X" * 300 + ",1,1\n"
    r = up(client, admin, "medicines", bad, dry=False).json()
    assert r["committed"] is False and med_count(client, admin) == 0
    where = {(e["row"], e["column"]) for e in r["errors"]}
    assert {(3, "name"), (4, "purchase_price"), (5, "purchase_price"), (6, "min_stock_threshold"), (7, "name")} <= where


def test_file_level_rejections(client, admin):
    assert up(client, admin, "medicines", "name\nx\n", name="data.xlsx").status_code == 422                    # wrong extension
    assert up(client, admin, "medicines", "", raw=b"").status_code == 422                                      # empty
    assert up(client, admin, "medicines", "", raw=b"name\nx\x00y\n").status_code == 422                        # binary
    assert up(client, admin, "medicines", "", raw="name\ncaf\u00e9\n".encode("latin-1")).status_code == 422   # not UTF-8
    assert up(client, admin, "medicines", "purchase_price\n1\n").status_code == 422                            # missing required column
    assert up(client, admin, "medicines", "name,name\na,b\n").status_code == 422                               # duplicate header
    assert up(client, admin, "medicines", "name\n").status_code == 422                                         # no rows
    big = "name\n" + "\n".join(f"Drug {i}" for i in range(5001)) + "\n"
    assert up(client, admin, "medicines", big).status_code == 422                                              # too many rows
    assert up(client, admin, "medicines", "", raw=b"name\n" + b"a" * (2 * 1024 * 1024 + 10)).status_code == 422  # too big
    assert up(client, admin, "patients", "name\nx\n").status_code == 422                                      # unknown kind
    assert med_count(client, admin) == 0


def test_semicolon_files_and_unknown_columns(client, admin):
    r = up(client, admin, "medicines", "name;dosage;patient_name\nAspirin;100mg;secret\n", dry=False).json()
    assert r["committed"] is True and any("patient_name" in w for w in r["warnings"])           # extra column ignored, and flagged


def test_receipts_and_sales_history_follow_fefo_and_keep_dates(client, admin):
    up(client, admin, "medicines", MEDS, dry=False)
    today = date.today()
    d = lambda n: str(today - timedelta(days=n))
    receipts = ("medicine,batch_number,expiration_date,quantity,unit_cost,received_date\n"
                f"Paracetamol 500mg,LATE,{today + timedelta(days=300)},100,0.05,{d(50)}\n"
                f"Paracetamol 500mg,EARLY,{today + timedelta(days=200)},50,0.05,{d(50)}\n")
    assert up(client, admin, "receipts", receipts, dry=False).json()["created"]["batches"] == 2
    sales = f"date,medicine,quantity\n{d(40)},Paracetamol 500mg,30\n{d(39)},Paracetamol 500mg,40\n"
    r = up(client, admin, "sales", sales, dry=False).json()
    assert r["committed"] is True and r["created"]["sales"] == 2
    batches = {b["batch_number"]: b for b in client.get(f"{API}/batches?limit=50&include_empty=true", headers=admin).json()["items"]}
    assert batches["EARLY"]["quantity_remaining"] == 0 and batches["LATE"]["quantity_remaining"] == 100 - (70 - 50)   # earliest expiry first
    mv = client.get(f"{API}/inventory/movements?movement_type=sale&limit=50", headers=admin).json()["items"]
    assert {m["occurred_at"][:10] for m in mv} == {d(40), d(39)}                                                   # recorded on their real days


def test_sales_exceeding_stock_on_that_day_are_rejected_atomically(client, admin):
    up(client, admin, "medicines", MEDS, dry=False)
    today = date.today()
    up(client, admin, "receipts", f"medicine,batch_number,expiration_date,quantity,unit_cost,received_date\nParacetamol 500mg,B1,{today + timedelta(days=90)},50,0.05,{today - timedelta(days=10)}\n", dry=False)
    early = up(client, admin, "sales", f"date,medicine,quantity\n{today - timedelta(days=20)},Paracetamol 500mg,5\n", dry=False).json()   # before the stock arrived
    assert early["committed"] is False and "only 0 usable" in early["errors"][0]["message"]
    mixed = f"date,medicine,quantity\n{today - timedelta(days=5)},Paracetamol 500mg,30\n{today - timedelta(days=4)},Paracetamol 500mg,30\n"
    r = up(client, admin, "sales", mixed, dry=False).json()
    assert r["committed"] is False and r["error_count"] == 1 and r["errors"][0]["row"] == 3     # second sale would need 60 of 50
    assert client.get(f"{API}/batches", headers=admin).json()["items"][0]["quantity_remaining"] == 50        # nothing was applied


def test_history_cannot_be_inserted_before_live_sales(client, admin):
    up(client, admin, "medicines", MEDS, dry=False)
    today = date.today()
    up(client, admin, "receipts", f"medicine,batch_number,expiration_date,quantity,unit_cost,received_date\nParacetamol 500mg,B1,{today + timedelta(days=90)},50,0.05,{today - timedelta(days=30)}\n", dry=False)
    para = next(m for m in client.get(f"{API}/medicines", headers=admin).json()["items"] if m["name"].startswith("Paracetamol"))
    assert client.post(f"{API}/sales", headers=admin, json={"medicine_id": para["id"], "quantity": 1}).status_code == 201
    r = up(client, admin, "sales", f"date,medicine,quantity\n{today - timedelta(days=3)},Paracetamol 500mg,1\n", dry=False).json()
    assert r["committed"] is False and "already exist" in r["errors"][0]["message"]


def test_receipts_validation(client, admin):
    up(client, admin, "medicines", MEDS, dry=False)
    today = date.today()
    h = "medicine,batch_number,expiration_date,quantity,unit_cost,received_date,supplier\n"
    rows = (f"Nothing,B1,{today + timedelta(days=9)},5,1,,\n"                                         # unknown medicine
            f"Paracetamol 500mg,B2,{today - timedelta(days=9)},5,1,{today - timedelta(days=2)},\n"      # expired before it was received
            f"Paracetamol 500mg,B3,{today + timedelta(days=9)},5,1,{today + timedelta(days=3)},\n"      # received in the future
            f"Paracetamol 500mg,B4,{today + timedelta(days=9)},5,1,,Ghost Supplier\n"                   # unknown supplier
            f"Paracetamol 500mg,B5,{today + timedelta(days=9)},5,\n"                                    # missing cost
            f"Paracetamol 500mg,B6,31-12-2030,5,1\n")                                                   # wrong date format
    r = up(client, admin, "receipts", h + rows).json()
    assert r["error_count"] >= 6 and {e["row"] for e in r["errors"]} == {2, 3, 4, 5, 6, 7}
    assert up(client, admin, "receipts", h + f"Paracetamol 500mg,DUP,{today + timedelta(days=9)},5,1\nParacetamol 500mg,dup,{today + timedelta(days=9)},5,1\n").json()["error_count"] == 1


def test_permissions_tenancy_and_synthetic_guard(client, admin):
    emp = make_user(client, admin, "emp@example.com", "employee")
    assert up(client, emp, "medicines", MEDS).status_code == 403
    up(client, admin, "medicines", MEDS, dry=False)
    register(client, "Other", "b@example.com"); hb = login(client, "b@example.com")
    r = up(client, hb, "receipts", f"medicine,batch_number,expiration_date,quantity,unit_cost\nParacetamol 500mg,B1,{date.today() + timedelta(days=9)},5,1\n").json()
    assert r["error_count"] == 1 and "unknown medicine" in r["errors"][0]["message"]       # another pharmacy's catalogue is invisible
    run_job(client, hb, "/demo/seed", {"days": 120, "n_medicines": 3})                       # hb is now a synthetic pharmacy
    assert up(client, hb, "medicines", MEDS).status_code == 409


def test_imported_history_feeds_forecasting_end_to_end(client, admin):
    rng, today = random.Random(1), date.today()
    up(client, admin, "medicines", "name,min_stock_threshold\nHistory Drug,20\n", dry=False)
    rec = "medicine,batch_number,expiration_date,quantity,unit_cost,received_date\n"
    sales = "date,medicine,quantity\n"
    for k in range(0, 130, 10):
        rec += f"History Drug,B{k},{today + timedelta(days=400)},400,1,{today - timedelta(days=140 - k)}\n"
    for day in range(130, 0, -1):
        sales += f"{today - timedelta(days=day)},History Drug,{rng.randint(5, 15)}\n"
    assert up(client, admin, "receipts", rec, dry=False).json()["committed"]
    r = up(client, admin, "sales", sales, dry=False).json()
    assert r["committed"] is True and r["created"]["sales"] == 130
    j = run_job(client, admin, "/forecasts/run", {"models": FAST, "refresh_alerts": False})
    res = j["result"]["results"][0]
    assert res["selected_model"] in FAST and res["confidence"] == "validated"
    mid = client.get(f"{API}/medicines", headers=admin).json()["items"][0]["id"]
    f = client.get(f"{API}/forecasts/{mid}", headers=admin).json()
    assert f["data_source"] == "real" and 5 < f["totals"]["next_7_days"] / 7 < 15      # forecast is in the range of the imported demand


def test_sales_rows_are_applied_in_date_order_not_file_order(client, admin):
    """One batch of 10; two sales of 10 on different days, listed newest-first. Chronologically the EARLIER sale gets the
    stock and the LATER one must be the failing row, whatever order the file lists them in."""
    up(client, admin, "medicines", "name\nOrder Drug\n", dry=False)
    today = date.today()
    up(client, admin, "receipts", f"medicine,batch_number,expiration_date,quantity,unit_cost,received_date\nOrder Drug,B1,{today + timedelta(days=90)},10,1,{today - timedelta(days=10)}\n", dry=False)
    newest_first = f"date,medicine,quantity\n{today - timedelta(days=4)},Order Drug,10\n{today - timedelta(days=5)},Order Drug,10\n"
    r = up(client, admin, "sales", newest_first, dry=True).json()
    assert r["error_count"] == 1 and r["errors"][0]["row"] == 2        # row 2 is the later date (day -4): it is the one left without stock


def test_decimal_comma_in_a_comma_file_is_an_error_not_silently_zero(client, admin):
    """A row with more cells than the header used to lose the extra cell and read the price as 0 with no error."""
    r = up(client, admin, "medicines", "name,dosage,purchase_price\nAspirin,100mg,0.03\nIbuprofen,200mg,0,06\n", dry=False).json()
    assert r["committed"] is False and med_count(client, admin) == 0
    assert r["error_count"] == 1 and r["errors"][0]["row"] == 3 and "decimal comma" in r["errors"][0]["message"]
    ok = up(client, admin, "medicines", "name;dosage;purchase_price\nAspirin;100mg;0,03\nIbuprofen;200mg;0,06\n", dry=False).json()
    assert ok["committed"] is True                                         # the same data in a semicolon file is fine
