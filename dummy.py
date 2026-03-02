import sqlite3
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random

DB = "leave.db"

# 🇿🇦 South African Names
FIRST_NAMES = [
    "Sipho", "Thabo", "Lerato", "Nomsa", "Ayanda", "Sibusiso", "Zanele",
    "Themba", "Nokuthula", "Mpho", "Lindiwe", "Andile", "Bongani",
    "Nandi", "Tshepo", "Kagiso", "Busisiwe", "Zola", "Khaya",
    "Naledi", "Vusi", "Simphiwe", "Luyanda", "Amahle", "Tumi",
    "Neo", "Refilwe", "Hlengiwe", "Sandile", "Mandla"
]

LAST_NAMES = [
    "Dlamini", "Nkosi", "Mokoena", "Khumalo", "Ndlovu",
    "Mthembu", "Zulu", "Mabena", "Sithole", "Mahlangu",
    "Molefe", "Tshabalala", "Cele", "Mabaso", "Hadebe",
    "Gumede", "Mokoena", "Ngcobo", "Mtshali", "Khoza"
]

def random_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

def random_email(name, index):
    clean = name.lower().replace(" ", ".")
    return f"{clean}{index}@company.co.za"

def create_dummy_data():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("Creating 30 South African employees...")

    user_ids = []

    # Create 30 employees
    for i in range(30):
        name = random_name()
        email = random_email(name, i)
        password = generate_password_hash("password123")

        try:
            cursor.execute("""
            INSERT INTO users (name, email, password, role)
            VALUES (?, ?, ?, ?)
            """, (name, email, password, "employee"))

            user_ids.append(cursor.lastrowid)
        except sqlite3.IntegrityError:
            continue

    conn.commit()

    print("Creating leave data for last 3 months...")

    statuses = ["Pending", "Approved", "Rejected"]
    reasons = [
        "Family responsibility",
        "Medical leave",
        "Traditional ceremony",
        "Personal leave",
        "Vacation leave"
    ]

    today = datetime.today()

    for user_id in user_ids:
        for month_offset in range(3):
            month_date = today - timedelta(days=30 * month_offset)

            # Each employee gets 1–3 leave requests per month
            for _ in range(random.randint(1, 3)):
                start_day = random.randint(1, 20)
                start_date = month_date.replace(day=1) + timedelta(days=start_day)
                duration = random.randint(1, 5)
                end_date = start_date + timedelta(days=duration)

                cursor.execute("""
                INSERT INTO leave_requests
                (user_id, start_date, end_date, reason, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    start_date.strftime("%Y-%m-%d"),
                    end_date.strftime("%Y-%m-%d"),
                    random.choice(reasons),
                    random.choice(statuses),
                    datetime.now().isoformat()
                ))

    conn.commit()
    conn.close()

    print("✅ Dummy South African data successfully created!")

if __name__ == "__main__":
    create_dummy_data()