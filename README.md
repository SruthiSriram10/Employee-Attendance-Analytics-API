# Employee Attendance & Analytics API

FastAPI + MongoDB implementation for the candidate assignment.

## Requirements
- Python 3.10+
- MongoDB 6.0+ (7.0 recommended)

## Run locally
```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
```

Set `MONGO_URI` and `MONGO_DB` in your environment (or a local `.env` file). Example:
```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

Start MongoDB, then run:
```bash
python sample_seed.py
uvicorn app.main:app --port 8000 --reload
```

Interactive API docs: http://127.0.0.1:8000/docs

Indexes are created idempotently on application startup. Do not commit `.env`, credentials, virtual environments, or secrets.

## Implementation notes
- Instants are stored as BSON datetimes and exposed as epoch milliseconds.
- Attendance dates and shift times follow the contract's IST rules.
- Unique indexes enforce employee-code and employee/date uniqueness.
- Analytics are implemented with MongoDB aggregation pipelines.
- `REVIEW.md` records starter defects; `DECISIONS.md` explains key design choices.

## Before submission
Run the API against MongoDB 7.0 and test boundary cases, including concurrent punch-ins/punch-outs, overnight shifts, half-day rounding, legacy documents, employee-month working days, leaderboard ties, and trend ranges. The provided nine sample records are not sufficient by themselves to prove every hidden edge case.
