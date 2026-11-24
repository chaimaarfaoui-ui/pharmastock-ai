from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile
from sqlalchemy.orm import Session
from app.api.deps import require_permission
from app.core.db import get_db
from app.models import Pharmacy, User
from app.services.audit import log_action
from app.services.importer import MAX_BYTES, SPECS, ImportRejected, parse_csv, run_import

router = APIRouter(prefix="/imports", tags=["import"])


@router.get("/formats")
def formats(u: User = Depends(require_permission("inventory:write"))):
    return {"order": ["medicines", "receipts", "sales"], "formats": SPECS, "max_bytes": MAX_BYTES,
            "notes": ["UTF-8 CSV, comma or semicolon separated, dates as YYYY-MM-DD.",
                      "Import medicines first, then stock receipts (opening stock and deliveries), then sales history.",
                      "Do not include any information that identifies patients."]}


@router.post("/{kind}")
def import_csv(kind: str = Path(pattern="^(medicines|receipts|sales)$"), file: UploadFile = File(...), dry_run: bool = Query(True),
               u: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    """dry_run=true checks the file and reports exactly what would happen; dry_run=false imports only if there are no errors."""
    if db.get(Pharmacy, u.pharmacy_id).data_source == "synthetic":
        raise HTTPException(409, "This pharmacy holds synthetic demo data. Importing real data into it would mix the two; register a separate pharmacy.")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(422, "Only .csv files are accepted")
    raw = file.file.read(MAX_BYTES + 1)
    try:
        rows, warnings = parse_csv(raw, kind)
    except ImportRejected as e:
        raise HTTPException(422, str(e))
    res = run_import(db, u.pharmacy_id, u.id, kind, rows, warnings)
    committed = False
    if dry_run or res.error_count:
        db.rollback()                       # nothing from the file is kept
    else:
        log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action=f"import.{kind}", details={"rows": res.rows, **res.created})
        db.commit(); committed = True
    return {"kind": kind, "dry_run": dry_run, "committed": committed, "rows": res.rows, "error_count": res.error_count,
            "errors": res.errors, "errors_truncated": res.error_count > len(res.errors), "warnings": res.warnings,
            "would_create" if not committed else "created": res.created, "preview": res.preview}
