"""
Drug Expiry Management System
Flask + SQLite | DBMS University Project
Features: Inventory, Expiry Alerts, Billing, Patient Records, PDF Receipts
"""

import sqlite3, os, csv, io, json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, jsonify, send_file

app = Flask(__name__)
app.secret_key = "drugwatch_secret_2024"

DB_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drugwatch.db")
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "medicine_dataset.csv")

# ══════════════════════════════════════════════════════════════
#  EMBEDDED SQL SCHEMA
# ══════════════════════════════════════════════════════════════
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS MedicineCatalog (
    med_id            INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    therapeutic_class TEXT,
    chemical_class    TEXT,
    habit_forming     TEXT,
    action_class      TEXT,
    uses              TEXT,
    side_effects      TEXT,
    substitutes       TEXT
);

CREATE TABLE IF NOT EXISTS Drug (
    drug_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    manufacturer TEXT    NOT NULL,
    price        REAL    NOT NULL DEFAULT 0.0,
    med_id       INTEGER,
    FOREIGN KEY (med_id) REFERENCES MedicineCatalog(med_id)
);

CREATE TABLE IF NOT EXISTS Supplier (
    supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    contact     TEXT,
    address     TEXT
);

CREATE TABLE IF NOT EXISTS Batch (
    batch_id    TEXT    PRIMARY KEY,
    drug_id     INTEGER NOT NULL,
    supplier_id INTEGER,
    mfg_date    TEXT    NOT NULL,
    exp_date    TEXT    NOT NULL,
    quantity    INTEGER NOT NULL CHECK(quantity >= 0),
    location    TEXT,
    FOREIGN KEY (drug_id)     REFERENCES Drug(drug_id)         ON DELETE CASCADE,
    FOREIGN KEY (supplier_id) REFERENCES Supplier(supplier_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS Users (
    user_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT    NOT NULL UNIQUE,
    role     TEXT    NOT NULL CHECK(role IN ('admin','pharmacist')),
    password TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS Patient (
    patient_id TEXT    PRIMARY KEY,
    name       TEXT    NOT NULL,
    phone      TEXT,
    email      TEXT,
    address    TEXT,
    created_at TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS Bill (
    bill_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_number    TEXT    NOT NULL UNIQUE,
    patient_id     TEXT,
    billed_by      TEXT    NOT NULL,
    bill_date      TEXT    DEFAULT (datetime('now')),
    subtotal       REAL    NOT NULL DEFAULT 0,
    discount       REAL    NOT NULL DEFAULT 0,
    gst_pct        REAL    NOT NULL DEFAULT 0,
    gst_amount     REAL    NOT NULL DEFAULT 0,
    total          REAL    NOT NULL DEFAULT 0,
    payment_method TEXT    DEFAULT 'Cash',
    notes          TEXT,
    FOREIGN KEY (patient_id) REFERENCES Patient(patient_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS BillItem (
    item_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id    INTEGER NOT NULL,
    batch_id   TEXT    NOT NULL,
    drug_name  TEXT    NOT NULL,
    quantity   INTEGER NOT NULL CHECK(quantity > 0),
    unit_price REAL    NOT NULL,
    amount     REAL    NOT NULL,
    FOREIGN KEY (bill_id)  REFERENCES Bill(bill_id)  ON DELETE CASCADE,
    FOREIGN KEY (batch_id) REFERENCES Batch(batch_id)
);

CREATE TABLE IF NOT EXISTS AuditLog (
    log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT NOT NULL,
    table_name TEXT NOT NULL,
    record_id  TEXT NOT NULL,
    details    TEXT,
    done_by    TEXT DEFAULT 'system',
    timestamp  TEXT DEFAULT (datetime('now'))
);

-- TRIGGERS
CREATE TRIGGER IF NOT EXISTS trg_batch_insert
AFTER INSERT ON Batch
BEGIN
    INSERT INTO AuditLog(action, table_name, record_id, details)
    VALUES ('INSERT','Batch', NEW.batch_id,
        'DrugID:'||NEW.drug_id||' Qty:'||NEW.quantity||' Exp:'||NEW.exp_date);
END;

CREATE TRIGGER IF NOT EXISTS trg_batch_delete
AFTER DELETE ON Batch
BEGIN
    INSERT INTO AuditLog(action, table_name, record_id, details)
    VALUES ('DELETE','Batch', OLD.batch_id,
        'DrugID:'||OLD.drug_id||' WasQty:'||OLD.quantity);
END;

CREATE TRIGGER IF NOT EXISTS trg_batch_qty_update
AFTER UPDATE OF quantity ON Batch
BEGIN
    INSERT INTO AuditLog(action, table_name, record_id, details)
    VALUES ('UPDATE','Batch', NEW.batch_id,
        'Qty:'||OLD.quantity||'->'||NEW.quantity);
END;

CREATE TRIGGER IF NOT EXISTS trg_bill_insert
AFTER INSERT ON Bill
BEGIN
    INSERT INTO AuditLog(action, table_name, record_id, details)
    VALUES ('INSERT','Bill', NEW.bill_number,
        'Total:Rs.'||NEW.total||' By:'||NEW.billed_by);
END;

-- VIEWS
CREATE VIEW IF NOT EXISTS vw_Inventory AS
SELECT b.batch_id, d.drug_id, d.name AS drug_name, d.category,
       d.manufacturer, d.price, s.name AS supplier,
       b.mfg_date, b.exp_date, b.quantity, b.location,
       CAST(julianday(b.exp_date) - julianday('now') AS INTEGER) AS days_left,
       CASE
           WHEN date(b.exp_date) < date('now')              THEN 'expired'
           WHEN date(b.exp_date) <= date('now','+30 days')  THEN 'critical'
           WHEN date(b.exp_date) <= date('now','+90 days')  THEN 'warning'
           ELSE 'good'
       END AS status
FROM Batch b
JOIN  Drug     d ON b.drug_id     = d.drug_id
LEFT JOIN Supplier s ON b.supplier_id = s.supplier_id;

CREATE VIEW IF NOT EXISTS vw_ExpiredBatches AS
SELECT b.batch_id, d.name AS drug_name, d.category, b.exp_date,
       b.quantity, b.location, s.name AS supplier,
       CAST(julianday('now') - julianday(b.exp_date) AS INTEGER) AS days_overdue
FROM Batch b JOIN Drug d ON b.drug_id = d.drug_id
LEFT JOIN Supplier s ON b.supplier_id = s.supplier_id
WHERE date(b.exp_date) < date('now');

CREATE VIEW IF NOT EXISTS vw_ExpiringBatches AS
SELECT b.batch_id, d.name AS drug_name, d.category, b.exp_date,
       b.quantity, b.location, s.name AS supplier,
       CAST(julianday(b.exp_date) - julianday('now') AS INTEGER) AS days_left
FROM Batch b JOIN Drug d ON b.drug_id = d.drug_id
LEFT JOIN Supplier s ON b.supplier_id = s.supplier_id
WHERE date(b.exp_date) >= date('now')
  AND date(b.exp_date) <= date('now','+90 days');

CREATE VIEW IF NOT EXISTS vw_BillSummary AS
SELECT b.bill_id, b.bill_number, b.bill_date, b.total, b.subtotal,
       b.discount, b.gst_pct, b.gst_amount,
       b.payment_method, b.billed_by, b.notes, b.patient_id,
       COALESCE(p.name,'Walk-in') AS patient_name,
       COALESCE(p.phone,'') AS patient_phone,
       COUNT(bi.item_id) AS item_count
FROM Bill b
LEFT JOIN Patient  p  ON b.patient_id = p.patient_id
LEFT JOIN BillItem bi ON b.bill_id    = bi.bill_id
GROUP BY b.bill_id;

-- SEED
INSERT OR IGNORE INTO Supplier(supplier_id, name, contact, address) VALUES
(1,'MedSupply Co.','9800001111','Kolkata, WB'),
(2,'PharmaDist','9800002222','Mumbai, MH'),
(3,'HealthBridge','9800003333','Delhi, DL');

INSERT OR IGNORE INTO Users(username, role, password) VALUES
('admin','admin','admin123'),
('pharma1','pharmacist','pharma123');
"""

SEED_DRUGS_SQL = """
INSERT OR IGNORE INTO Drug(drug_id, name, category, manufacturer, price) VALUES
(1,'Amoxicillin','Antibiotic','Sun Pharma',45.00),
(2,'Paracetamol','Analgesic','Cipla',12.00),
(3,'Metformin','Antidiabetic','Dr. Reddys',38.00),
(4,'Atorvastatin','Statin','Pfizer',95.00),
(5,'Omeprazole','Antacid','Zydus',28.00),
(6,'Cetirizine','Antihistamine','Abbott',22.00);

INSERT OR IGNORE INTO Batch(batch_id,drug_id,supplier_id,mfg_date,exp_date,quantity,location) VALUES
('B001',1,1,'2023-06-01','2025-06-01',500,'Rack A1'),
('B002',1,2,'2024-01-15','2026-01-15',300,'Rack A2'),
('B003',2,1,'2023-11-01','2025-03-20',1200,'Rack B1'),
('B004',3,3,'2022-05-10','2025-02-05',80,'Rack C2'),
('B005',4,2,'2024-03-01','2026-03-01',450,'Rack D1'),
('B006',5,1,'2023-08-20','2025-04-10',220,'Rack E1'),
('B007',6,3,'2024-02-14','2027-02-14',600,'Rack F3'),
('B008',2,2,'2024-05-01','2026-05-01',900,'Rack B2'),
('B009',3,3,'2023-09-15','2025-02-28',40,'Rack C1');

INSERT OR IGNORE INTO Patient(patient_id, name, phone, email, address) VALUES
('CUST-000001','Rajesh Kumar','9876543210','rajesh@email.com','Bhubaneswar, Odisha'),
('CUST-000002','Priya Sharma','9812345678','priya@email.com','Cuttack, Odisha'),
('CUST-000003','Anand Das','9898989898','anand@email.com','Puri, Odisha');
"""

# ══════════════════════════════════════════════════════════════
#  DB HELPERS
# ══════════════════════════════════════════════════════════════

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.executescript(SEED_DRUGS_SQL)
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM MedicineCatalog").fetchone()[0]
    if count == 0 and os.path.exists(CSV_PATH):
        print("[DrugWatch] Importing medicine catalog (~30s)...")
        batch = []
        with open(CSV_PATH, encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                uses    = ', '.join(filter(None,[row.get(f'use{i}','') for i in range(5)]))
                side_fx = ', '.join(filter(None,[row.get(f'sideEffect{i}','') for i in range(42)]))
                subs    = ', '.join(filter(None,[row.get(f'substitute{i}','') for i in range(5)]))
                batch.append((int(row['id']), row['name'].strip().title(),
                    row.get('Therapeutic Class','').strip(), row.get('Chemical Class','').strip(),
                    row.get('Habit Forming','').strip(), row.get('Action Class','').strip(),
                    uses, side_fx, subs))
                if len(batch) >= 5000:
                    conn.executemany("INSERT OR IGNORE INTO MedicineCatalog VALUES(?,?,?,?,?,?,?,?,?)", batch)
                    conn.commit(); batch = []
        if batch:
            conn.executemany("INSERT OR IGNORE INTO MedicineCatalog VALUES(?,?,?,?,?,?,?,?,?)", batch)
            conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM MedicineCatalog").fetchone()[0]
        print(f"[DrugWatch] Catalog ready: {total:,} medicines.")
    conn.close()
    print("[DrugWatch] Database ready.")

def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv  = cur.fetchall()
    return (rv[0] if rv else None) if one else rv

def mutate(sql, args=()):
    db = get_db(); cur = db.execute(sql, args); db.commit(); return cur

def get_stats():
    rows = query("SELECT status, COUNT(*) as cnt FROM vw_Inventory GROUP BY status")
    stats = {"expired":0,"critical":0,"warning":0,"good":0}
    for r in rows: stats[r["status"]] = r["cnt"]
    stats["total"]     = sum(stats.values())
    stats["total_qty"] = query("SELECT COALESCE(SUM(quantity),0) as s FROM Batch",one=True)["s"]
    stats["drugs"]     = query("SELECT COUNT(*) as c FROM Drug",one=True)["c"]
    stats["catalog"]   = query("SELECT COUNT(*) as c FROM MedicineCatalog",one=True)["c"]
    stats["suppliers"] = query("SELECT COUNT(*) as c FROM Supplier",one=True)["c"]
    stats["patients"]  = query("SELECT COUNT(*) as c FROM Patient",one=True)["c"]
    stats["bills"]     = query("SELECT COUNT(*) as c FROM Bill",one=True)["c"]
    stats["revenue"]   = query("SELECT COALESCE(SUM(total),0) as s FROM Bill",one=True)["s"]
    return stats

def next_patient_id():
    row = query("SELECT patient_id FROM Patient ORDER BY patient_id DESC LIMIT 1", one=True)
    if not row: return "CUST-000001"
    last = int(row["patient_id"].split("-")[1])
    return f"CUST-{last+1:06d}"

def next_bill_number():
    today = datetime.now().strftime("%Y%m%d")
    row   = query("SELECT COUNT(*) as c FROM Bill WHERE bill_number LIKE ?", (f"BILL-{today}-%",), one=True)
    return f"BILL-{today}-{row['c']+1:04d}"

# ══════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session: return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session: return redirect(url_for("login"))
        if session["user"]["role"] != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

@app.route("/", methods=["GET","POST"])
def login():
    if "user" in session: return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        u = request.form["username"].strip()
        p = request.form["password"].strip()
        user = query("SELECT * FROM Users WHERE username=? AND password=?", (u,p), one=True)
        if user:
            session["user"] = dict(user)
            return redirect(url_for("dashboard"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

# ══════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    stats = get_stats()
    if session["user"]["role"] == "admin":
        alerts       = query("SELECT * FROM vw_Inventory WHERE status IN ('expired','critical','warning') ORDER BY days_left ASC LIMIT 8")
        recent_audit = query("SELECT * FROM AuditLog ORDER BY timestamp DESC LIMIT 5")
        recent_bills = query("SELECT * FROM vw_BillSummary ORDER BY bill_date DESC LIMIT 5")
        return render_template("dashboard_admin.html", stats=stats, alerts=alerts,
                               recent_audit=recent_audit, recent_bills=recent_bills)
    else:
        my_batches = query("SELECT * FROM vw_Inventory WHERE status IN ('critical','warning') ORDER BY days_left ASC LIMIT 10")
        low_stock  = query("SELECT * FROM vw_Inventory WHERE quantity < 100 ORDER BY quantity ASC LIMIT 8")
        return render_template("dashboard_pharma.html", stats=stats, my_batches=my_batches, low_stock=low_stock)

# ══════════════════════════════════════════════════════════════
#  INVENTORY
# ══════════════════════════════════════════════════════════════

@app.route("/inventory")
@login_required
def inventory():
    sf = request.args.get("status","all"); sq = request.args.get("q","").strip()
    sql = "SELECT * FROM vw_Inventory WHERE 1=1"; args = []
    if sf != "all": sql += " AND status=?"; args.append(sf)
    if sq:
        sql += " AND (drug_name LIKE ? OR batch_id LIKE ? OR supplier LIKE ? OR location LIKE ?)"
        args += [f"%{sq}%"]*4
    sql += " ORDER BY days_left ASC"
    return render_template("inventory.html", batches=query(sql,args),
                           drugs=query("SELECT * FROM Drug ORDER BY name"),
                           suppliers=query("SELECT * FROM Supplier ORDER BY name"),
                           status_filter=sf, search=sq)

@app.route("/inventory/add", methods=["POST"])
@login_required
def add_batch():
    drug_id=request.form["drug_id"]; sup=request.form.get("supplier_id") or None
    mfg=request.form["mfg_date"]; exp=request.form["exp_date"]
    qty=request.form["quantity"]; loc=request.form.get("location","")
    count = query("SELECT COUNT(*) as c FROM Batch",one=True)["c"]
    bid = f"B{count+1:03d}"
    while query("SELECT 1 FROM Batch WHERE batch_id=?", (bid,), one=True):
        count+=1; bid=f"B{count+1:03d}"
    try:
        mutate("INSERT INTO Batch VALUES(?,?,?,?,?,?,?)",(bid,drug_id,sup,mfg,exp,qty,loc))
        flash(f"Batch {bid} added!","success")
    except Exception as e:
        flash(f"Error: {e}","danger")
    return redirect(url_for("inventory"))

@app.route("/inventory/delete/<batch_id>")
@admin_required
def delete_batch(batch_id):
    mutate("DELETE FROM Batch WHERE batch_id=?",(batch_id,))
    flash(f"Batch {batch_id} deleted.","info")
    return redirect(url_for("inventory"))

@app.route("/inventory/update_qty", methods=["POST"])
@login_required
def update_qty():
    mutate("UPDATE Batch SET quantity=? WHERE batch_id=?",
           (request.form["quantity"],request.form["batch_id"]))
    flash("Stock updated.","success")
    return redirect(url_for("inventory"))

# ══════════════════════════════════════════════════════════════
#  ALERTS
# ══════════════════════════════════════════════════════════════

@app.route("/alerts")
@login_required
def alerts():
    expired  = query("SELECT * FROM vw_ExpiredBatches ORDER BY days_overdue DESC")
    expiring = query("SELECT * FROM vw_ExpiringBatches ORDER BY days_left ASC")
    critical = [r for r in expiring if r["days_left"] <= 30]
    warning  = [r for r in expiring if r["days_left"]  > 30]
    low_stock= query("SELECT * FROM vw_Inventory WHERE quantity < 100 ORDER BY quantity ASC")
    return render_template("alerts.html", expired=expired, critical=critical,
                           warning=warning, low_stock=low_stock)

# ══════════════════════════════════════════════════════════════
#  DRUGS
# ══════════════════════════════════════════════════════════════

@app.route("/drugs")
@login_required
def drugs():
    drug_list = query("""
        SELECT d.*, COUNT(b.batch_id) AS batch_count,
               COALESCE(SUM(b.quantity),0) AS total_qty,
               m.therapeutic_class, m.habit_forming
        FROM Drug d
        LEFT JOIN Batch b ON d.drug_id=b.drug_id
        LEFT JOIN MedicineCatalog m ON d.med_id=m.med_id
        GROUP BY d.drug_id ORDER BY d.name
    """)
    return render_template("drugs.html", drugs=drug_list)

@app.route("/drugs/add", methods=["POST"])
@login_required
def add_drug():
    name=request.form["name"].strip(); cat=request.form["category"].strip()
    mfr=request.form["manufacturer"].strip()
    price=float(request.form.get("price",0) or 0)
    med_id=request.form.get("med_id") or None
    if not name: flash("Drug name required.","danger"); return redirect(url_for("drugs"))
    mutate("INSERT INTO Drug(name,category,manufacturer,price,med_id) VALUES(?,?,?,?,?)",
           (name,cat,mfr,price,med_id))
    flash(f"'{name}' registered.","success")
    return redirect(url_for("drugs"))

@app.route("/drugs/delete/<int:drug_id>")
@admin_required
def delete_drug(drug_id):
    mutate("DELETE FROM Drug WHERE drug_id=?",(drug_id,))
    flash("Drug removed.","info"); return redirect(url_for("drugs"))

# ══════════════════════════════════════════════════════════════
#  MEDICINE CATALOG
# ══════════════════════════════════════════════════════════════

@app.route("/catalog")
@login_required
def catalog():
    search=request.args.get("q","").strip(); tc=request.args.get("tc","").strip()
    page=max(1,int(request.args.get("page",1))); per_page=30; offset=(page-1)*per_page
    sql="SELECT * FROM MedicineCatalog WHERE 1=1"; args=[]
    if search: sql+=" AND name LIKE ?"; args.append(f"%{search}%")
    if tc:     sql+=" AND therapeutic_class=?"; args.append(tc)
    total=get_db().execute(sql.replace("SELECT *","SELECT COUNT(*)"),args).fetchone()[0]
    sql+=f" ORDER BY name LIMIT {per_page} OFFSET {offset}"
    return render_template("catalog.html", medicines=query(sql,args), search=search,
                           tc_filter=tc, page=page, total_pages=(total+per_page-1)//per_page,
                           total=total,
                           tclasses=query("SELECT DISTINCT therapeutic_class FROM MedicineCatalog WHERE therapeutic_class!='' ORDER BY therapeutic_class"))

@app.route("/catalog/<int:med_id>")
@login_required
def medicine_detail(med_id):
    med=query("SELECT * FROM MedicineCatalog WHERE med_id=?",(med_id,),one=True)
    if not med: flash("Not found.","danger"); return redirect(url_for("catalog"))
    return render_template("medicine_detail.html", med=med)

# ══════════════════════════════════════════════════════════════
#  PATIENTS
# ══════════════════════════════════════════════════════════════

@app.route("/patients")
@login_required
def patients():
    sq=request.args.get("q","").strip()
    sql="""SELECT p.*, COUNT(b.bill_id) AS total_bills,
                  COALESCE(SUM(b.total),0) AS total_spent
           FROM Patient p LEFT JOIN Bill b ON p.patient_id=b.patient_id
           WHERE 1=1"""
    args=[]
    if sq:
        sql+=" AND (p.name LIKE ? OR p.phone LIKE ? OR p.patient_id LIKE ?)"
        args+=[f"%{sq}%"]*3
    sql+=" GROUP BY p.patient_id ORDER BY p.created_at DESC"
    return render_template("patients.html", patients=query(sql,args), search=sq)

@app.route("/patients/add", methods=["POST"])
@login_required
def add_patient():
    name=request.form["name"].strip()
    if not name: flash("Name required.","danger"); return redirect(url_for("patients"))
    pid=next_patient_id()
    mutate("INSERT INTO Patient(patient_id,name,phone,email,address) VALUES(?,?,?,?,?)",
           (pid,name,request.form.get("phone",""),request.form.get("email",""),request.form.get("address","")))
    flash(f"Patient {pid} added.","success")
    return redirect(url_for("patients"))

@app.route("/patients/edit/<patient_id>", methods=["POST"])
@login_required
def edit_patient(patient_id):
    mutate("UPDATE Patient SET name=?,phone=?,email=?,address=? WHERE patient_id=?",
           (request.form["name"],request.form.get("phone",""),
            request.form.get("email",""),request.form.get("address",""),patient_id))
    flash("Patient updated.","success"); return redirect(url_for("patients"))

@app.route("/patients/<patient_id>")
@login_required
def patient_detail(patient_id):
    patient=query("SELECT * FROM Patient WHERE patient_id=?",(patient_id,),one=True)
    if not patient: flash("Not found.","danger"); return redirect(url_for("patients"))
    bills=query("""
        SELECT b.*, COUNT(bi.item_id) AS item_count
        FROM Bill b LEFT JOIN BillItem bi ON b.bill_id=bi.bill_id
        WHERE b.patient_id=? GROUP BY b.bill_id ORDER BY b.bill_date DESC
    """,(patient_id,))
    history=query("""
        SELECT bi.drug_name, SUM(bi.quantity) AS total_qty,
               SUM(bi.amount) AS total_spent, COUNT(*) AS times_bought
        FROM BillItem bi JOIN Bill b ON bi.bill_id=b.bill_id
        WHERE b.patient_id=?
        GROUP BY bi.drug_name ORDER BY total_qty DESC
    """,(patient_id,))
    return render_template("patient_detail.html", patient=patient,
                           bills=bills, total_spent=sum(b["total"] for b in bills), history=history)

@app.route("/patients/delete/<patient_id>")
@admin_required
def delete_patient(patient_id):
    mutate("DELETE FROM Patient WHERE patient_id=?",(patient_id,))
    flash("Patient removed. Bills preserved.","info"); return redirect(url_for("patients"))

@app.route("/api/patients/search")
@login_required
def api_search_patients():
    q=request.args.get("q","").strip()
    rows=query("SELECT patient_id,name,phone FROM Patient WHERE name LIKE ? OR phone LIKE ? LIMIT 8",
               (f"%{q}%",f"%{q}%"))
    return jsonify([dict(r) for r in rows])

@app.route("/api/drugs/search")
@login_required
def api_search_drugs():
    q=request.args.get("q","").strip()
    rows=query("""
        SELECT b.batch_id, d.name AS drug_name, d.price, b.quantity, b.exp_date
        FROM Batch b JOIN Drug d ON b.drug_id=d.drug_id
        WHERE d.name LIKE ? AND b.quantity > 0 AND date(b.exp_date) >= date('now')
        ORDER BY b.exp_date ASC LIMIT 10
    """,(f"%{q}%",))
    return jsonify([dict(r) for r in rows])

# ══════════════════════════════════════════════════════════════
#  BILLING
# ══════════════════════════════════════════════════════════════

@app.route("/billing")
@login_required
def billing():
    return render_template("billing.html",
                           patients=query("SELECT * FROM Patient ORDER BY name"))

@app.route("/billing/create", methods=["POST"])
@login_required
def create_bill():
    patient_id = request.form.get("patient_id") or None
    items      = json.loads(request.form.get("items","[]"))
    discount   = float(request.form.get("discount",0) or 0)
    gst_pct    = float(request.form.get("gst_pct",0) or 0)
    payment    = request.form.get("payment_method","Cash")
    notes      = request.form.get("notes","")
    billed_by  = session["user"]["username"]

    if not items:
        flash("Cart is empty.","danger"); return redirect(url_for("billing"))

    subtotal   = sum(i["quantity"]*i["unit_price"] for i in items)
    gst_amount = round((subtotal-discount)*gst_pct/100, 2)
    total      = round(subtotal - discount + gst_amount, 2)
    bill_number = next_bill_number()

    db = get_db()
    try:
        cur = db.execute("""
            INSERT INTO Bill(bill_number,patient_id,billed_by,subtotal,discount,
                             gst_pct,gst_amount,total,payment_method,notes)
            VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (bill_number,patient_id,billed_by,subtotal,discount,gst_pct,gst_amount,total,payment,notes))
        bill_id = cur.lastrowid
        for item in items:
            db.execute("INSERT INTO BillItem(bill_id,batch_id,drug_name,quantity,unit_price,amount) VALUES(?,?,?,?,?,?)",
                       (bill_id,item["batch_id"],item["drug_name"],item["quantity"],
                        item["unit_price"],round(item["quantity"]*item["unit_price"],2)))
            db.execute("UPDATE Batch SET quantity=quantity-? WHERE batch_id=?",
                       (item["quantity"],item["batch_id"]))
        db.commit()
        flash(f"Bill {bill_number} created!","success")
        return redirect(url_for("bill_detail", bill_id=bill_id))
    except Exception as e:
        db.rollback()
        flash(f"Error: {e}","danger")
        return redirect(url_for("billing"))

# ══════════════════════════════════════════════════════════════
#  BILLS
# ══════════════════════════════════════════════════════════════

@app.route("/bills")
@login_required
def bills():
    sq=request.args.get("q","").strip()
    from_dt=request.args.get("from",""); to_dt=request.args.get("to","")
    sql="SELECT * FROM vw_BillSummary WHERE 1=1"; args=[]
    if sq:
        sql+=" AND (bill_number LIKE ? OR patient_name LIKE ?)"; args+=[f"%{sq}%"]*2
    if from_dt: sql+=" AND date(bill_date) >= ?"; args.append(from_dt)
    if to_dt:   sql+=" AND date(bill_date) <= ?"; args.append(to_dt)
    sql+=" ORDER BY bill_date DESC"
    return render_template("bills.html", bills=query(sql,args),
                           search=sq, from_dt=from_dt, to_dt=to_dt)

@app.route("/bills/<int:bill_id>")
@login_required
def bill_detail(bill_id):
    bill=query("SELECT * FROM vw_BillSummary WHERE bill_id=?",(bill_id,),one=True)
    if not bill: flash("Not found.","danger"); return redirect(url_for("bills"))
    items=query("SELECT * FROM BillItem WHERE bill_id=?",(bill_id,))
    return render_template("bill_detail.html", bill=bill, items=items)

# ══════════════════════════════════════════════════════════════
#  PDF RECEIPT
# ══════════════════════════════════════════════════════════════

@app.route("/bills/<int:bill_id>/pdf")
@login_required
def download_pdf(bill_id):
    from reportlab.lib.pagesizes import A5
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

    bill      = query("SELECT * FROM vw_BillSummary WHERE bill_id=?",(bill_id,),one=True)
    full_bill = query("SELECT * FROM Bill WHERE bill_id=?",(bill_id,),one=True)
    items     = query("SELECT * FROM BillItem WHERE bill_id=?",(bill_id,))
    if not bill: flash("Not found.","danger"); return redirect(url_for("bills"))

    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=A5,
                               rightMargin=12*mm, leftMargin=12*mm,
                               topMargin=10*mm,   bottomMargin=10*mm)
    styles = getSampleStyleSheet()
    dark   = colors.HexColor("#0d1117"); red  = colors.HexColor("#ff3b3b")
    muted  = colors.HexColor("#8b949e"); green= colors.HexColor("#00e576")
    white  = colors.white

    def ps(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    elems = []

    # Header
    hdr = Table([[
        Paragraph("<font color='white'><b>DrugWatch Pharmacy</b></font><br/><font color='#8b949e' size='7'>Drug Expiry Management System</font>",
                  ps("h", fontSize=13, textColor=white, leading=16)),
        Paragraph(f"<font color='#ff6b6b'><b>{bill['bill_number']}</b></font><br/><font color='#8b949e' size='7'>{bill['bill_date'][:10]}</font>",
                  ps("hr", fontSize=10, textColor=white, alignment=TA_RIGHT, leading=14))
    ]], colWidths=[75*mm, 45*mm])
    hdr.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),dark),("PADDING",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    elems.append(hdr); elems.append(Spacer(1,4*mm))

    # Patient info
    info = Table([[
        Paragraph(f"<b>Patient:</b> {bill['patient_name']}", ps("i1",fontSize=9,textColor=colors.HexColor("#e6edf3"))),
        Paragraph(f"<b>Payment:</b> {bill['payment_method']}", ps("i2",fontSize=9,textColor=colors.HexColor("#e6edf3"),alignment=TA_RIGHT))
    ],[
        Paragraph(f"<b>Phone:</b> {bill['patient_phone'] or 'Walk-in'}", ps("i3",fontSize=9,textColor=colors.HexColor("#8b949e"))),
        Paragraph(f"<b>Billed by:</b> {bill['billed_by']}", ps("i4",fontSize=9,textColor=colors.HexColor("#8b949e"),alignment=TA_RIGHT))
    ]], colWidths=[75*mm,45*mm])
    info.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#161b22")),("PADDING",(0,0),(-1,-1),6)]))
    elems.append(info); elems.append(Spacer(1,4*mm))

    # Items
    tdata = [["Medicine","Qty","Rate","Amount"]]
    for item in items:
        tdata.append([item["drug_name"], str(item["quantity"]),
                      f"Rs.{item['unit_price']:.2f}", f"Rs.{item['amount']:.2f}"])
    itbl = Table(tdata, colWidths=[62*mm,13*mm,27*mm,25*mm])
    itbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),dark),("TEXTCOLOR",(0,0),(-1,0),white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("ALIGN",(1,0),(-1,-1),"RIGHT"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#0a0e14"),colors.HexColor("#161b22")]),
        ("TEXTCOLOR",(0,1),(-1,-1),colors.HexColor("#e6edf3")),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#21262d")),("PADDING",(0,0),(-1,-1),5),
    ]))
    elems.append(itbl); elems.append(Spacer(1,3*mm))

    # Totals
    tots = [["Subtotal", f"Rs. {full_bill['subtotal']:.2f}"]]
    if full_bill["discount"] > 0:
        tots.append(["Discount", f"- Rs. {full_bill['discount']:.2f}"])
    if full_bill["gst_amount"] > 0:
        tots.append([f"GST ({full_bill['gst_pct']}%)", f"Rs. {full_bill['gst_amount']:.2f}"])
    tots.append(["TOTAL", f"Rs. {full_bill['total']:.2f}"])
    ttbl = Table(tots, colWidths=[100*mm, 27*mm])
    ttbl.setStyle(TableStyle([
        ("ALIGN",(1,0),(1,-1),"RIGHT"),("FONTSIZE",(0,0),(-1,-1),8),
        ("TEXTCOLOR",(0,0),(-1,-2),muted),("PADDING",(0,0),(-1,-1),4),
        ("BACKGROUND",(0,-1),(-1,-1),dark),("TEXTCOLOR",(0,-1),(-1,-1),green),
        ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,-1),(-1,-1),11),
    ]))
    elems.append(ttbl); elems.append(Spacer(1,5*mm))
    elems.append(HRFlowable(width="100%",thickness=0.5,color=colors.HexColor("#21262d")))
    elems.append(Spacer(1,3*mm))
    elems.append(Paragraph("Thank you for choosing DrugWatch Pharmacy.",
                            ps("ft",fontSize=8,textColor=muted,alignment=TA_CENTER)))

    if bill["notes"]:
        elems.append(Spacer(1,2*mm))
        elems.append(Paragraph(f"Note: {bill['notes']}",
                                ps("nt",fontSize=7,textColor=muted,alignment=TA_CENTER)))

    doc.build(elems)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name=f"{bill['bill_number']}.pdf",
                     mimetype="application/pdf")

# ══════════════════════════════════════════════════════════════
#  SUPPLIERS
# ══════════════════════════════════════════════════════════════

@app.route("/suppliers")
@login_required
def suppliers():
    return render_template("suppliers.html",
        suppliers=query("SELECT s.*, COUNT(b.batch_id) AS batch_count FROM Supplier s LEFT JOIN Batch b ON s.supplier_id=b.supplier_id GROUP BY s.supplier_id"))

@app.route("/suppliers/add", methods=["POST"])
@login_required
def add_supplier():
    mutate("INSERT INTO Supplier(name,contact,address) VALUES(?,?,?)",
           (request.form["name"],request.form.get("contact",""),request.form.get("address","")))
    flash("Supplier added.","success"); return redirect(url_for("suppliers"))

# ══════════════════════════════════════════════════════════════
#  REPORTS
# ══════════════════════════════════════════════════════════════

@app.route("/reports")
@login_required
def reports():
    stats = get_stats()
    return render_template("reports.html", stats=stats,
        status_dist=query("SELECT status, COUNT(*) as cnt, SUM(quantity) as qty FROM vw_Inventory GROUP BY status"),
        cat_dist=query("SELECT d.category, COUNT(b.batch_id) as batches, COALESCE(SUM(b.quantity),0) as total_qty FROM Drug d LEFT JOIN Batch b ON d.drug_id=b.drug_id GROUP BY d.category ORDER BY total_qty DESC"),
        sup_dist=query("SELECT s.name, COUNT(b.batch_id) as batches, COALESCE(SUM(b.quantity),0) as total_qty FROM Supplier s LEFT JOIN Batch b ON s.supplier_id=b.supplier_id GROUP BY s.supplier_id ORDER BY total_qty DESC"),
        tc_dist=query("SELECT therapeutic_class, COUNT(*) as cnt FROM MedicineCatalog WHERE therapeutic_class!='' GROUP BY therapeutic_class ORDER BY cnt DESC LIMIT 10"),
        pay_dist=query("SELECT payment_method, COUNT(*) as cnt, SUM(total) as revenue FROM Bill GROUP BY payment_method ORDER BY revenue DESC"))

# ══════════════════════════════════════════════════════════════
#  AUDIT LOG
# ══════════════════════════════════════════════════════════════

@app.route("/audit")
@admin_required
def audit():
    return render_template("audit.html",
                           logs=query("SELECT * FROM AuditLog ORDER BY timestamp DESC LIMIT 100"))

# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    print("="*52)
    print("  DrugWatch -> http://127.0.0.1:5000")
    print("  Admin     : admin   / admin123")
    print("  Pharmacist: pharma1 / pharma123")
    print("="*52)
    app.run(debug=True)
