-- ============================================================
--  Drug Expiry Management System
--  DBMS University Project | SQLite Schema
--  Team: Ayush Kumar, Anubhab Das, Abhijoy Debnath, Aditya Sengupta
-- ============================================================

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────
-- TABLE 1: MedicineCatalog
-- Populated from medicine_dataset.csv (248,218 real medicines)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS MedicineCatalog (
    med_id            INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL,
    therapeutic_class TEXT,
    chemical_class    TEXT,
    habit_forming     TEXT,
    action_class      TEXT,
    uses              TEXT,       -- comma-separated (use0..use4)
    side_effects      TEXT,       -- comma-separated (sideEffect0..sideEffect41)
    substitutes       TEXT        -- comma-separated (substitute0..substitute4)
);

-- ─────────────────────────────────────────────────────────────
-- TABLE 2: Drug
-- Medicines registered in THIS pharmacy's inventory
-- References MedicineCatalog for rich drug info (optional FK)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS Drug (
    drug_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    manufacturer TEXT    NOT NULL,
    med_id       INTEGER,                             -- optional link to catalog
    FOREIGN KEY (med_id) REFERENCES MedicineCatalog(med_id)
);

-- ─────────────────────────────────────────────────────────────
-- TABLE 3: Supplier
-- Vendors who supply drug batches to the pharmacy
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS Supplier (
    supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    contact     TEXT,
    address     TEXT
);

-- ─────────────────────────────────────────────────────────────
-- TABLE 4: Batch
-- Core table — one row per physical batch of a drug
-- Tracks manufacturing date, expiry date, quantity, location
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS Batch (
    batch_id    TEXT    PRIMARY KEY,                 -- e.g. B001, B002
    drug_id     INTEGER NOT NULL,
    supplier_id INTEGER,
    mfg_date    TEXT    NOT NULL,                    -- YYYY-MM-DD
    exp_date    TEXT    NOT NULL,                    -- YYYY-MM-DD
    quantity    INTEGER NOT NULL CHECK(quantity >= 0),
    location    TEXT,                                -- e.g. Rack A1
    FOREIGN KEY (drug_id)     REFERENCES Drug(drug_id)         ON DELETE CASCADE,
    FOREIGN KEY (supplier_id) REFERENCES Supplier(supplier_id) ON DELETE SET NULL
);

-- ─────────────────────────────────────────────────────────────
-- TABLE 5: Users
-- Role-based access: admin vs pharmacist
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS Users (
    user_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT    NOT NULL UNIQUE,
    role     TEXT    NOT NULL CHECK(role IN ('admin', 'pharmacist')),
    password TEXT    NOT NULL
);

-- ─────────────────────────────────────────────────────────────
-- TABLE 6: AuditLog
-- Auto-populated by SQL triggers — never written to manually
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS AuditLog (
    log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT    NOT NULL,                     -- INSERT / UPDATE / DELETE
    table_name TEXT    NOT NULL,
    record_id  TEXT    NOT NULL,
    details    TEXT,
    done_by    TEXT    DEFAULT 'system',
    timestamp  TEXT    DEFAULT (datetime('now'))
);


-- ============================================================
--  TRIGGERS
--  Automatically log every INSERT / UPDATE / DELETE on Batch
-- ============================================================

-- Trigger 1: Log new batch insertion
CREATE TRIGGER IF NOT EXISTS trg_batch_insert
AFTER INSERT ON Batch
BEGIN
    INSERT INTO AuditLog(action, table_name, record_id, details)
    VALUES (
        'INSERT', 'Batch', NEW.batch_id,
        'DrugID: ' || NEW.drug_id ||
        ' | Qty: '  || NEW.quantity ||
        ' | Exp: '  || NEW.exp_date
    );
END;

-- Trigger 2: Log batch deletion
CREATE TRIGGER IF NOT EXISTS trg_batch_delete
AFTER DELETE ON Batch
BEGIN
    INSERT INTO AuditLog(action, table_name, record_id, details)
    VALUES (
        'DELETE', 'Batch', OLD.batch_id,
        'DrugID: ' || OLD.drug_id ||
        ' | WasQty: ' || OLD.quantity
    );
END;

-- Trigger 3: Log quantity updates
CREATE TRIGGER IF NOT EXISTS trg_batch_qty_update
AFTER UPDATE OF quantity ON Batch
BEGIN
    INSERT INTO AuditLog(action, table_name, record_id, details)
    VALUES (
        'UPDATE', 'Batch', NEW.batch_id,
        'Qty changed: ' || OLD.quantity || ' → ' || NEW.quantity
    );
END;


-- ============================================================
--  VIEWS
--  Pre-built queries for expiry status and alerts
-- ============================================================

-- View 1: Full inventory with computed expiry status
CREATE VIEW IF NOT EXISTS vw_Inventory AS
SELECT
    b.batch_id,
    d.drug_id,
    d.name              AS drug_name,
    d.category,
    d.manufacturer,
    s.name              AS supplier,
    b.mfg_date,
    b.exp_date,
    b.quantity,
    b.location,
    CAST(julianday(b.exp_date) - julianday('now') AS INTEGER) AS days_left,
    CASE
        WHEN date(b.exp_date) < date('now')                THEN 'expired'
        WHEN date(b.exp_date) <= date('now', '+30 days')   THEN 'critical'
        WHEN date(b.exp_date) <= date('now', '+90 days')   THEN 'warning'
        ELSE                                                    'good'
    END AS status
FROM Batch b
JOIN  Drug     d ON b.drug_id     = d.drug_id
LEFT JOIN Supplier s ON b.supplier_id = s.supplier_id;

-- View 2: Already-expired batches with days overdue
CREATE VIEW IF NOT EXISTS vw_ExpiredBatches AS
SELECT
    b.batch_id,
    d.name  AS drug_name,
    d.category,
    b.exp_date,
    b.quantity,
    b.location,
    s.name  AS supplier,
    CAST(julianday('now') - julianday(b.exp_date) AS INTEGER) AS days_overdue
FROM Batch b
JOIN  Drug     d ON b.drug_id     = d.drug_id
LEFT JOIN Supplier s ON b.supplier_id = s.supplier_id
WHERE date(b.exp_date) < date('now');

-- View 3: Batches expiring within the next 90 days
CREATE VIEW IF NOT EXISTS vw_ExpiringBatches AS
SELECT
    b.batch_id,
    d.name  AS drug_name,
    d.category,
    b.exp_date,
    b.quantity,
    b.location,
    s.name  AS supplier,
    CAST(julianday(b.exp_date) - julianday('now') AS INTEGER) AS days_left
FROM Batch b
JOIN  Drug     d ON b.drug_id     = d.drug_id
LEFT JOIN Supplier s ON b.supplier_id = s.supplier_id
WHERE date(b.exp_date) >= date('now')
  AND date(b.exp_date) <= date('now', '+90 days');


-- ============================================================
--  SEED DATA
-- ============================================================

INSERT OR IGNORE INTO Supplier(supplier_id, name, contact, address) VALUES
(1, 'MedSupply Co.', '9800001111', 'Kolkata, WB'),
(2, 'PharmaDist',    '9800002222', 'Mumbai, MH'),
(3, 'HealthBridge',  '9800003333', 'Delhi, DL');

INSERT OR IGNORE INTO Users(username, role, password) VALUES
('admin',   'admin',       'admin123'),
('pharma1', 'pharmacist',  'pharma123');

INSERT OR IGNORE INTO Drug(drug_id, name, category, manufacturer) VALUES
(1, 'Amoxicillin',  'Antibiotic',    'Sun Pharma'),
(2, 'Paracetamol',  'Analgesic',     'Cipla'),
(3, 'Metformin',    'Antidiabetic',  'Dr. Reddys'),
(4, 'Atorvastatin', 'Statin',        'Pfizer'),
(5, 'Omeprazole',   'Antacid',       'Zydus'),
(6, 'Cetirizine',   'Antihistamine', 'Abbott');

INSERT OR IGNORE INTO Batch(batch_id, drug_id, supplier_id, mfg_date, exp_date, quantity, location) VALUES
('B001', 1, 1, '2023-06-01', '2025-06-01', 500,  'Rack A1'),
('B002', 1, 2, '2024-01-15', '2026-01-15', 300,  'Rack A2'),
('B003', 2, 1, '2023-11-01', '2025-03-20', 1200, 'Rack B1'),
('B004', 3, 3, '2022-05-10', '2025-02-05', 80,   'Rack C2'),
('B005', 4, 2, '2024-03-01', '2026-03-01', 450,  'Rack D1'),
('B006', 5, 1, '2023-08-20', '2025-04-10', 220,  'Rack E1'),
('B007', 6, 3, '2024-02-14', '2027-02-14', 600,  'Rack F3'),
('B008', 2, 2, '2024-05-01', '2026-05-01', 900,  'Rack B2'),
('B009', 3, 3, '2023-09-15', '2025-02-28', 40,   'Rack C1');
