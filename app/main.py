

import os
from pathlib import Path
from datetime import datetime, timezone, date

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient, ASCENDING
from pymongo.errors import PyMongoError, DuplicateKeyError
from bson import ObjectId

# --------------------------------------------------
# 1. APP AND MONGODB CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI is missing from .env")

app = FastAPI(
    title="Employee Attendance & Analytics API",
    version="1.0.0"
)

client = MongoClient(
    MONGO_URI,
    tz_aware=True,
    serverSelectionTimeoutMS=10000
)

db = client[MONGO_DB]

# Define collections FIRST
employees = db["employees"]
logs = db["attendance_logs"]
audit_logs = db["attendance_audit_logs"]

# Create indexes AFTER defining collections
employees.create_index("employee_code", unique=True)
employees.create_index("email", unique=True)

logs.create_index(
    [("employee_id", ASCENDING), ("date", ASCENDING)],
    unique=True
)

# Keep all your existing models, helper functions,
# and API endpoints below this section.



# --------------------------------------------------
# 2. REQUEST MODELS
# --------------------------------------------------

class EmployeeCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=150)
    department: str = Field(min_length=1, max_length=100)
    designation: str = Field(min_length=1, max_length=100)

    
class AttendanceCorrection(BaseModel):
    check_in: datetime | None = None
    check_out: datetime | None = None
    reason: str = Field(min_length=5, max_length=500)
    corrected_by: str = Field(min_length=2, max_length=100)



# --------------------------------------------------
# 3. HELPER FUNCTIONS
# --------------------------------------------------

def serialize_employee(employee):
    employee["_id"] = str(employee["_id"])
    return employee


def serialize_log(record):
    record["_id"] = str(record["_id"])
    record["employee_id"] = str(record["employee_id"])
    return record


def serialize_doc(document):
    if document is None:
        return None

    document = dict(document)
    document["_id"] = str(document["_id"])
    return document



def parse_object_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(
            status_code=400,
            detail="Invalid employee ID"
        )
    return ObjectId(value)


def utc_now():
    return datetime.now(timezone.utc)


def today_utc():
    return date.today() if False else utc_now().date()


# --------------------------------------------------
# 4. HOME AND HEALTH
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "Employee Attendance & Analytics API is running"
    }


@app.get("/health")
def health_check():
    try:
        client.admin.command("ping")
        return {
            "status": "healthy",
            "mongodb": "connected"
        }
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="MongoDB is unavailable"
        )


# --------------------------------------------------
# 5. EMPLOYEE MANAGEMENT
# --------------------------------------------------

@app.post("/employees", status_code=201)
def register_employee(employee: EmployeeCreate):
    document = employee.model_dump()
    document["active"] = True
    document["created_at"] = utc_now()

    try:
        result = employees.insert_one(document)
        saved = employees.find_one({"_id": result.inserted_id})
        return serialize_employee(saved)

    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Employee already exists"
        )
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Could not save employee to MongoDB"
        )


@app.get("/employees")
def list_employees(
    active_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0)
):
    query = {"active": True} if active_only else {}

    try:
        total = employees.count_documents(query)
        results = list(
            employees.find(query)
            .sort("name", ASCENDING)
            .skip(skip)
            .limit(limit)
        )

        return {
            "total": total,
            "employees": [
                serialize_employee(item) for item in results
            ]
        }
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Could not retrieve employees"
        )


@app.get("/employees/{employee_id}")
def get_employee(employee_id: str):
    oid = parse_object_id(employee_id)

    try:
        employee = employees.find_one({"_id": oid})

        if not employee:
            raise HTTPException(
                status_code=404,
                detail="Employee not found"
            )

        return serialize_employee(employee)
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Could not retrieve employee"
        )


# --------------------------------------------------
# 6. ATTENDANCE CHECK-IN
# --------------------------------------------------

@app.post("/attendance/check-in", status_code=201)
def check_in(employee_id: str):
    oid = parse_object_id(employee_id)

    try:
        employee = employees.find_one({
            "_id": oid,
            "active": True
        })

        if not employee:
            raise HTTPException(
                status_code=404,
                detail="Active employee not found"
            )

        now = utc_now()
        day = now.date().isoformat()

        record = {
            "employee_id": oid,
            "date": day,
            "check_in": now,
            "check_out": None,
            "status": "checked_in"
        }

        result = logs.insert_one(record)
        saved = logs.find_one({"_id": result.inserted_id})

        return serialize_log(saved)

    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Attendance already exists for this employee today"
        )
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Could not record check-in"
        )


# --------------------------------------------------
# 7. ATTENDANCE CHECK-OUT
# --------------------------------------------------

@app.post("/attendance/check-out")
def check_out(employee_id: str):
    oid = parse_object_id(employee_id)
    day = utc_now().date().isoformat()
    now = utc_now()

    try:
        result = logs.update_one(
            {
                "employee_id": oid,
                "date": day,
                "check_out": None
            },
            {
                "$set": {
                    "check_out": now,
                    "status": "checked_out"
                }
            }
        )

        if result.matched_count == 0:
            existing = logs.find_one({
                "employee_id": oid,
                "date": day
            })

            if not existing:
                raise HTTPException(
                    status_code=404,
                    detail="No check-in found for this employee today"
                )

            raise HTTPException(
                status_code=409,
                detail="Employee has already checked out"
            )

        saved = logs.find_one({
            "employee_id": oid,
            "date": day
        })

        return serialize_log(saved)

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Could not record check-out"
        )


# --------------------------------------------------
# 8. VIEW ATTENDANCE RECORDS
# --------------------------------------------------

@app.get("/attendance")
def list_attendance(
    attendance_date: date | None = None,
    employee_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500)
):
    query = {}

    if attendance_date:
        query["date"] = attendance_date.isoformat()

    if employee_id:
        query["employee_id"] = parse_object_id(employee_id)

    try:
        results = list(
            logs.find(query)
            .sort("check_in", -1)
            .limit(limit)
        )

        return {
            "count": len(results),
            "attendance": [
                serialize_log(item) for item in results
            ]
        }
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Could not retrieve attendance records"
        )


# --------------------------------------------------
# 9. DAILY ATTENDANCE ANALYTICS
# --------------------------------------------------


@app.get("/analytics/daily")
def daily_analytics(report_date: date | None = Query(default=None)):
    target_date = report_date or today_utc()
    date_string = target_date.isoformat()

    # Count active employees
    active_employees = employees.count_documents(
        {"active": True}
    )

    # Aggregate attendance records for the selected date
    pipeline = [
        {
            "$match": {
                "date": date_string
            }
        },
        {
            "$group": {
                "_id": None,
                "total_records": {"$sum": 1},

                "present": {
                    "$sum": {
                        "$cond": [
                            {
                                "$ne": [
                                    {"$ifNull": ["$check_in", None]},
                                    None
                                ]
                            },
                            1,
                            0
                        ]
                    }
                },

                "checked_out": {
                    "$sum": {
                        "$cond": [
                            {
                                "$ne": [
                                    {"$ifNull": ["$check_out", None]},
                                    None
                                ]
                            },
                            1,
                            0
                        ]
                    }
                },

                "currently_checked_in": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$ne": [
                                            {"$ifNull": ["$check_in", None]},
                                            None
                                        ]
                                    },
                                    {
                                        "$eq": [
                                            {"$ifNull": ["$check_out", None]},
                                            None
                                        ]
                                    }
                                ]
                            },
                            1,
                            0
                        ]
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "total_records": 1,
                "present": 1,
                "checked_out": 1,
                "currently_checked_in": 1
            }
        }
    ]

    results = list(logs.aggregate(pipeline))

    # Handle dates with no attendance records
    stats = results[0] if results else {
        "total_records": 0,
        "present": 0,
        "checked_out": 0,
        "currently_checked_in": 0
    }

    absent = max(active_employees - stats["present"], 0)

    attendance_percentage = (
        round(stats["present"] / active_employees * 100, 2)
        if active_employees > 0
        else 0
    )

    return {
        "date": date_string,
        "active_employees": active_employees,
        "total_records": stats["total_records"],
        "present": stats["present"],
        "absent": absent,
        "checked_out": stats["checked_out"],
        "currently_checked_in": stats["currently_checked_in"],
        "attendance_percentage": attendance_percentage
    }




# --------------------------------------------------
# 10. EMPLOYEE ATTENDANCE SUMMARY
# --------------------------------------------------

@app.get("/analytics/employee/{employee_id}")
def employee_analytics(employee_id: str):
    emp_id = parse_object_id(employee_id)

    try:
        employee = employees.find_one({"_id": emp_id})

        if not employee:
            raise HTTPException(
                status_code=404,
                detail="Employee not found"
            )

        pipeline = [
            {
                "$match": {
                    "employee_id": emp_id
                }
            },
            {
                "$group": {
                    "_id": "$employee_id",
                    "total_attendance_days": {"$sum": 1},
                    "total_check_ins": {
                        "$sum": {
                            "$cond": [
                                {"$ne": ["$check_in", None]},
                                1,
                                0
                            ]
                        }
                    },
                    "completed_checkouts": {
                        "$sum": {
                            "$cond": [
                                {"$ne": ["$check_out", None]},
                                1,
                                0
                            ]
                        }
                    },
                    "currently_checked_in": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$ne": ["$check_in", None]},
                                        {"$eq": ["$check_out", None]}
                                    ]
                                },
                                1,
                                0
                            ]
                        }
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "total_attendance_days": 1,
                    "total_check_ins": 1,
                    "completed_checkouts": 1,
                    "currently_checked_in": 1
                }
            }
        ]

        results = list(logs.aggregate(pipeline))

        stats = results[0] if results else {
            "total_attendance_days": 0,
            "total_check_ins": 0,
            "completed_checkouts": 0,
            "currently_checked_in": 0
        }

        return {
            "employee": serialize_doc(employee),
            "analytics": stats
        }

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Could not retrieve employee analytics"
        )
