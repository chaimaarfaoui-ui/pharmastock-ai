# Importing your own data

**Never import anything that identifies a patient.** The system needs only product, date and quantity. Real pharmacy data must be authorised and anonymised by your organisation before it is imported; this tool does not anonymise anything for you.

Open **Import Data** (manager or admin). Import in this order: **1. medicines, 2. stock receipts, 3. sales history.** Each page of the flow downloads a template.

| File | Required columns | Optional columns |
|---|---|---|
| medicines | name | brand, active_ingredient, dosage, formulation, category, purchase_price, selling_price, min_stock_threshold |
| receipts | medicine, batch_number, expiration_date, quantity, unit_cost | received_date, supplier |
| sales | date, medicine, quantity | unit_price, type (sale or dispense) |

## Rules the importer enforces
* UTF-8 text CSV, `.csv` extension, up to 2 MB and 5,000 rows. Comma or semicolon separators (Excel in French/Arabic locales uses semicolons). Dates as `YYYY-MM-DD`.
* **Check first, then import.** "Check file" runs the complete import inside a transaction and rolls it back, so the report shows exactly what would happen.
* **All or nothing.** If any row has a problem, nothing is imported. Problems are listed with row number and column.
* A row with more cells than the header is an error (typically a decimal comma such as `0,06` in a comma-separated file). Use a semicolon-separated file, or a decimal point.
* Medicine names must match the catalogue exactly (case-insensitive); ambiguous or unknown names are rejected. Duplicate batch numbers are rejected.
* Receipts: the expiry date cannot be before the received date; the received date cannot be in the future; unknown suppliers are rejected.
* Sales are applied **oldest first**, first-expired-first-out, against stock that had already been received on that date. A sale for stock that did not exist that day is rejected, so history cannot create negative stock. Sales cannot be inserted before sales already recorded for the same medicine.
* A pharmacy holding synthetic demo data refuses imports, so real and synthetic data are never mixed. Register a separate pharmacy for real data.
* Every successful import is recorded in the audit log (type and counts only; the file is not stored).

## Why history needs receipts first
Forecasting reconstructs daily stock from the movement ledger to find out-of-stock days. Opening stock and past deliveries must therefore be imported with their real dates before the sales history, or the system cannot tell a quiet day from an empty shelf.
