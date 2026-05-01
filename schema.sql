PRAGMA foreign_keys = ON;

-- ============================================================
-- TABLES
-- ============================================================

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

-- ============================================================
-- TRIGGERS
-- ============================================================

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

-- ============================================================
-- VIEWS
-- ============================================================

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
JOIN Drug d ON b.drug_id = d.drug_id
LEFT JOIN Supplier s ON b.supplier_id = s.supplier_id;

CREATE VIEW IF NOT EXISTS vw_ExpiredBatches AS
SELECT b.batch_id, d.name AS drug_name, d.category, b.exp_date,
       b.quantity, b.location, s.name AS supplier,
       CAST(julianday('now') - julianday(b.exp_date) AS INTEGER) AS days_overdue
FROM Batch b
JOIN Drug d ON b.drug_id = d.drug_id
LEFT JOIN Supplier s ON b.supplier_id = s.supplier_id
WHERE date(b.exp_date) < date('now');

CREATE VIEW IF NOT EXISTS vw_ExpiringBatches AS
SELECT b.batch_id, d.name AS drug_name, d.category, b.exp_date,
       b.quantity, b.location, s.name AS supplier,
       CAST(julianday(b.exp_date) - julianday('now') AS INTEGER) AS days_left
FROM Batch b
JOIN Drug d ON b.drug_id = d.drug_id
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
LEFT JOIN Patient p ON b.patient_id = p.patient_id
LEFT JOIN BillItem bi ON b.bill_id = bi.bill_id
GROUP BY b.bill_id;

-- ============================================================
-- SEED DATA
-- ============================================================

INSERT OR IGNORE INTO Supplier(supplier_id, name, contact, address) VALUES
(1,'MedSupply Co.','9800001111','Kolkata, WB'),
(2,'PharmaDist','9800002222','Mumbai, MH'),
(3,'HealthBridge','9800003333','Delhi, DL');

INSERT OR IGNORE INTO Users(username, role, password) VALUES
('admin','admin','admin123'),
('pharma1','pharmacist','pharma123');

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
