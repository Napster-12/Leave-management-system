from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, g
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime
import pandas as pd
from collections import defaultdict
import pyotp
import qrcode
import base64
from io import BytesIO
import os

app = Flask(__name__)
app.secret_key = "super-secret-key"
DB = "leave.db"

# ================= DATABASE =================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB, timeout=10)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    with sqlite3.connect(DB) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            totp_secret TEXT,
            qr_shown INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            start_date TEXT,
            end_date TEXT,
            reason TEXT,
            status TEXT DEFAULT 'Pending',
            admin_comment TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """)

# ================= UTILS =================
def calculate_total_days(start_date, end_date):
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    return (e - s).days + 1

# ================= ROUTES =================
@app.route("/")
def landing():
    return render_template("landing.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            db = get_db()
            db.execute(
                "INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)",
                (
                    request.form["name"],
                    request.form["email"],
                    generate_password_hash(request.form["password"]),
                    request.form["role"]
                )
            )
            db.commit()
            flash("Registration successful")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already exists")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["name"] = user["name"]

            # Generate TOTP secret if not exists
            if not user["totp_secret"]:
                totp_secret = pyotp.random_base32()
                db.execute(
                    "UPDATE users SET totp_secret=?, qr_shown=0 WHERE id=?",
                    (totp_secret, user["id"])
                )
                db.commit()
            else:
                totp_secret = user["totp_secret"]

            # Refresh user after update
            user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()

            if not user["qr_shown"]:
                totp_uri = pyotp.TOTP(totp_secret).provisioning_uri(
                    name=user["email"],
                    issuer_name="LeaveManagementSystem"
                )
                img = qrcode.make(totp_uri)
                buffer = BytesIO()
                img.save(buffer, format="PNG")
                qr_code_b64 = base64.b64encode(buffer.getvalue()).decode()
                db.execute("UPDATE users SET qr_shown=1 WHERE id=?", (user["id"],))
                db.commit()
                return render_template("register_qr.html", qr_code_b64=qr_code_b64, name=user["name"])

            return redirect(url_for("two_factor"))

        flash("Invalid email or password")
    return render_template("login.html")

@app.route("/two-factor", methods=["GET", "POST"])
def two_factor():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    totp = pyotp.TOTP(user["totp_secret"])

    if request.method == "POST":
        token = request.form["token"]
        if totp.verify(token):
            return redirect(url_for("dashboard"))
        flash("Invalid 2FA code")

    return render_template("two_factor.html", name=user["name"])

# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    page = request.args.get("page", 1, type=int)
    per_page = 6
    offset = (page - 1) * per_page

    # ADMIN DASHBOARD
    if session["role"] == "admin":
        total_leaves_count = db.execute("SELECT COUNT(*) as count FROM leave_requests").fetchone()["count"]

        rows = db.execute("""
            SELECT lr.*, u.name as name
            FROM leave_requests lr
            JOIN users u ON u.id = lr.user_id
            ORDER BY lr.start_date DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()

        leaves = []
        approved = pending = rejected = 0
        monthly = defaultdict(int)

        for r in rows:
            leave = dict(r)
            leave["total_days"] = calculate_total_days(r["start_date"], r["end_date"])
            leaves.append(leave)

            if r["status"] == "Approved":
                approved += 1
            elif r["status"] == "Pending":
                pending += 1
            elif r["status"] == "Rejected":
                rejected += 1

            monthly[r["start_date"][:7]] += 1

        total_pages = (total_leaves_count + per_page - 1) // per_page

        return render_template(
            "admin_dashboard.html",
            leaves=leaves,
            total_leaves=total_leaves_count,
            approved_count=approved,
            pending_count=pending,
            rejected_count=rejected,
            months=list(monthly.keys()),
            monthly_counts=list(monthly.values()),
            page=page,
            total_pages=total_pages
        )

    # EMPLOYEE DASHBOARD
    total_leaves_count = db.execute(
        "SELECT COUNT(*) as count FROM leave_requests WHERE user_id=?",
        (session["user_id"],)
    ).fetchone()["count"]

    rows = db.execute("""
        SELECT * FROM leave_requests
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (session["user_id"], per_page, offset)).fetchall()

    leaves = []
    approved = pending = rejected = total_days = 0

    for r in rows:
        days = calculate_total_days(r["start_date"], r["end_date"])
        leave = dict(r)
        leave["total_days"] = days
        leaves.append(leave)
        total_days += days

        if r["status"] == "Approved":
            approved += 1
        elif r["status"] == "Pending":
            pending += 1
        elif r["status"] == "Rejected":
            rejected += 1

    total_pages = (total_leaves_count + per_page - 1) // per_page

    return render_template(
        "employee_dashboard.html",
        leaves=leaves,
        total=total_leaves_count,
        approved=approved,
        pending=pending,
        rejected=rejected,
        total_days=total_days,
        page=page,
        total_pages=total_pages
    )

# ================= LEAVE ROUTES =================
@app.route("/apply", methods=["GET", "POST"])
def apply_leave():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        db = get_db()
        db.execute("""
            INSERT INTO leave_requests (user_id,start_date,end_date,reason,created_at)
            VALUES (?,?,?,?,?)
        """, (
            session["user_id"],
            request.form["start"],
            request.form["end"],
            request.form["reason"],
            datetime.now().isoformat()
        ))
        db.commit()
        flash("Leave request submitted")
        return redirect(url_for("dashboard"))

    return render_template("apply_leave.html")

@app.route("/approve/<int:leave_id>")
def approve_leave(leave_id):
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))

    db = get_db()
    db.execute("UPDATE leave_requests SET status='Approved' WHERE id=?", (leave_id,))
    db.commit()
    flash("Leave approved")
    return redirect(url_for("dashboard"))

@app.route("/reject/<int:leave_id>", methods=["POST"])
def reject_leave(leave_id):
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))

    comment = request.form["admin_comment"]
    db = get_db()
    db.execute(
        "UPDATE leave_requests SET status='Rejected', admin_comment=? WHERE id=?",
        (comment, leave_id)
    )
    db.commit()
    flash("Leave rejected with comment")
    return redirect(url_for("dashboard"))

@app.route("/export-leaves")
def export_leaves():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))

    db = get_db()
    rows = db.execute("""
        SELECT u.name, lr.start_date, lr.end_date, lr.reason, lr.status, lr.admin_comment
        FROM leave_requests lr
        JOIN users u ON u.id = lr.user_id
    """).fetchall()

    data = []
    for r in rows:
        data.append({
            "Employee": r["name"],
            "Start Date": r["start_date"],
            "End Date": r["end_date"],
            "Days": calculate_total_days(r["start_date"], r["end_date"]),
            "Reason": r["reason"],
            "Status": r["status"],
            "Admin Comment": r["admin_comment"]
        })

    df = pd.DataFrame(data)
    file = "leave_report.xlsx"
    df.to_excel(file, index=False)
    return send_file(file, as_attachment=True)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))

# ================= MAIN =================
if __name__ == "__main__":
    init_db()
    app.run(debug=True, use_reloader=False)