"""
db.py — จัดการฐานข้อมูล SQLite ทั้งหมดของระบบจองโต๊ะ
ใช้เฉพาะไลบรารีมาตรฐานของ Python (sqlite3) ไม่ต้องติดตั้งอะไรเพิ่ม
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(__file__), "bar.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS tables (
    id       INTEGER PRIMARY KEY,
    code     TEXT UNIQUE NOT NULL,   -- t1..t7, bar1..bar5
    name     TEXT NOT NULL,          -- ชื่อที่แสดง เช่น 'โต๊ะ 1'
    zone     TEXT NOT NULL,          -- 'table' หรือ 'bar'
    capacity INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reservations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id      INTEGER NOT NULL,
    res_date      TEXT NOT NULL,      -- 'YYYY-MM-DD'
    res_time      TEXT NOT NULL,      -- 'HH:MM'
    party_size    INTEGER NOT NULL,
    customer_name TEXT NOT NULL,
    phone         TEXT NOT NULL,
    instagram     TEXT NOT NULL,
    note          TEXT,
    status        TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed / completed / cancelled
    paid_amount   INTEGER,           -- ยอดที่ลูกค้าจ่าย (ใส่ตอนเช็คบิล)
    checked_out_at TEXT,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (table_id) REFERENCES tables(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    reservation_id INTEGER NOT NULL,
    name           TEXT NOT NULL,
    qty            INTEGER NOT NULL,
    unit_price     INTEGER NOT NULL,
    FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE CASCADE
);

-- กันจองซ้ำโต๊ะเดิม วัน+เวลาเดิม (เฉพาะที่ยัง confirmed)
CREATE INDEX IF NOT EXISTS idx_res_slot
    ON reservations (table_id, res_date, res_time, status);
"""

# โต๊ะทั้งหมดตามแปลนร้าน (โต๊ะ 1-7 + บาร์ 1-5)
SEED_TABLES = [
    # (code, name, zone, capacity)
    ("t1", "โต๊ะ 1", "table", 2),
    ("t2", "โต๊ะ 2", "table", 6),
    ("t3", "โต๊ะ 3", "table", 6),
    ("t4", "โต๊ะ 4", "table", 3),
    ("t5", "โต๊ะ 5", "table", 3),
    ("t6", "โต๊ะ 6", "table", 3),
    ("t7", "โต๊ะ 7", "table", 6),
    ("bar1", "บาร์ 1", "bar", 1),
    ("bar2", "บาร์ 2", "bar", 1),
    ("bar3", "บาร์ 3", "bar", 1),
    ("bar4", "บาร์ 4", "bar", 1),
    ("bar5", "บาร์ 5", "bar", 1),
]


def init_db():
    """สร้างตารางและใส่ข้อมูลตั้งต้น (โต๊ะ) ถ้ายังไม่มี"""
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        # seed โต๊ะ
        if conn.execute("SELECT COUNT(*) c FROM tables").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT INTO tables (code, name, zone, capacity) VALUES (?,?,?,?)",
                SEED_TABLES,
            )
        # migration: ฐานข้อมูลเก่าอาจยังไม่มีคอลัมน์ instagram
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(reservations)").fetchall()}
        if "instagram" not in cols:
            conn.execute("ALTER TABLE reservations ADD COLUMN instagram TEXT NOT NULL DEFAULT ''")
        if "paid_amount" not in cols:
            conn.execute("ALTER TABLE reservations ADD COLUMN paid_amount INTEGER")
        if "checked_out_at" not in cols:
            conn.execute("ALTER TABLE reservations ADD COLUMN checked_out_at TEXT")
        conn.commit()
    finally:
        conn.close()


# ---------- ฟังก์ชันอ่านข้อมูล ----------

def list_tables():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, code, name, zone, capacity FROM tables ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def taken_table_ids(res_date, res_time):
    """คืนรายการ id ของโต๊ะที่ถูกจองไปแล้วในวัน+เวลาที่ระบุ"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT DISTINCT table_id FROM reservations
               WHERE res_date = ? AND res_time = ? AND status = 'confirmed'""",
            (res_date, res_time),
        ).fetchall()
        return [r["table_id"] for r in rows]
    finally:
        conn.close()


def list_reservations(res_date=None):
    """รายการการจอง (สำหรับหน้าแอดมิน) พร้อมชื่อโต๊ะและรายการที่สั่ง"""
    conn = get_conn()
    try:
        params = []
        where = "WHERE r.status != 'deleted'"
        if res_date:
            where += " AND r.res_date = ?"
            params.append(res_date)
        rows = conn.execute(
            f"""SELECT r.*, t.name AS table_name, t.capacity
                FROM reservations r JOIN tables t ON t.id = r.table_id
                {where}
                ORDER BY r.res_date, r.res_time, t.id""",
            params,
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            items = conn.execute(
                "SELECT id, name, qty, unit_price FROM order_items WHERE reservation_id = ? ORDER BY id",
                (r["id"],),
            ).fetchall()
            d["items"] = [dict(i) for i in items]
            d["order_total"] = sum(i["qty"] * i["unit_price"] for i in d["items"])
            result.append(d)
        return result
    finally:
        conn.close()


# ---------- ฟังก์ชันเขียนข้อมูล ----------

class BookingError(Exception):
    """ข้อผิดพลาดที่คาดไว้ (แสดงข้อความให้ผู้ใช้ได้)"""
    pass


def create_reservation(data):
    """
    สร้างการจองใหม่ ตรวจสอบความถูกต้องและกันจองซ้ำภายใน transaction เดียว
    data = {table_id, res_date, res_time, party_size, customer_name, phone, instagram, note}
    """
    table_id = data.get("table_id")
    res_date = (data.get("res_date") or "").strip()
    res_time = (data.get("res_time") or "").strip()
    party_size = int(data.get("party_size") or 0)
    name = (data.get("customer_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    instagram = (data.get("instagram") or "").strip()
    note = (data.get("note") or "").strip()

    # ตรวจข้อมูลเบื้องต้น
    if not res_date or not res_time:
        raise BookingError("กรุณาเลือกวันและเวลา")
    if party_size < 1:
        raise BookingError("จำนวนคนต้องมากกว่า 0")
    if not name:
        raise BookingError("กรุณากรอกชื่อผู้จอง")
    if len(phone) < 8:
        raise BookingError("กรุณากรอกเบอร์โทรให้ถูกต้อง")
    if not instagram:
        raise BookingError("กรุณากรอกไอดีไอจี")

    conn = get_conn()
    try:
        # BEGIN IMMEDIATE เพื่อกัน race condition ตอนคนสองคนจองโต๊ะเดียวกันพร้อมกัน
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")

        table = conn.execute(
            "SELECT id, name, capacity FROM tables WHERE id = ?", (table_id,)
        ).fetchone()
        if not table:
            raise BookingError("ไม่พบโต๊ะที่เลือก")
        # หมายเหตุ: อนุญาตให้จองจำนวนคนมากกว่าจำนวนเก้าอี้ได้ (ไม่จำกัดตามความจุ)

        clash = conn.execute(
            """SELECT id FROM reservations
               WHERE table_id = ? AND res_date = ? AND res_time = ? AND status = 'confirmed'""",
            (table_id, res_date, res_time),
        ).fetchone()
        if clash:
            raise BookingError(
                f"{table['name']} ถูกจองไปแล้วในเวลานี้ กรุณาเลือกโต๊ะหรือเวลาอื่น"
            )

        cur = conn.execute(
            """INSERT INTO reservations
               (table_id, res_date, res_time, party_size, customer_name, phone, instagram, note, status, created_at)
               VALUES (?,?,?,?,?,?,?,?, 'confirmed', ?)""",
            (table_id, res_date, res_time, party_size, name, phone, instagram, note,
             datetime.now().isoformat(timespec="seconds")),
        )
        res_id = cur.lastrowid

        conn.execute("COMMIT")
        return res_id
    except BookingError:
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def cancel_reservation(res_id):
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE reservations SET status = 'cancelled' WHERE id = ? AND status = 'confirmed'",
            (res_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def checkout_reservation(res_id, paid_amount):
    """
    เช็คบิล: บันทึกยอดที่ลูกค้าจ่ายและปิดการจอง (status='completed')
    ทำให้โต๊ะนี้ว่างสำหรับวัน+เวลาเดิมทันที (taken_table_ids นับเฉพาะ status='confirmed')
    """
    try:
        amount = int(paid_amount)
    except (TypeError, ValueError):
        raise BookingError("กรุณาระบุยอดที่ลูกค้าจ่ายเป็นตัวเลข")
    if amount < 0:
        raise BookingError("ยอดเงินต้องไม่ติดลบ")

    conn = get_conn()
    try:
        cur = conn.execute(
            """UPDATE reservations SET status = 'completed', paid_amount = ?, checked_out_at = ?
               WHERE id = ? AND status = 'confirmed'""",
            (amount, datetime.now().isoformat(timespec="seconds"), res_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def add_order_item(reservation_id, name, qty, unit_price):
    """เพิ่มรายการที่ลูกค้าสั่ง (เฉพาะการจองที่ยัง confirmed อยู่)"""
    name = (name or "").strip()
    if not name:
        raise BookingError("กรุณาระบุชื่อรายการ")
    try:
        qty = int(qty)
        unit_price = int(unit_price)
    except (TypeError, ValueError):
        raise BookingError("จำนวนและราคาต้องเป็นตัวเลข")
    if qty < 1:
        raise BookingError("จำนวนต้องมากกว่า 0")
    if unit_price < 0:
        raise BookingError("ราคาต้องไม่ติดลบ")

    conn = get_conn()
    try:
        res = conn.execute(
            "SELECT id FROM reservations WHERE id = ? AND status = 'confirmed'", (reservation_id,)
        ).fetchone()
        if not res:
            raise BookingError("ไม่พบการจองนี้ หรือปิดบิลไปแล้ว")
        cur = conn.execute(
            "INSERT INTO order_items (reservation_id, name, qty, unit_price) VALUES (?,?,?,?)",
            (reservation_id, name, qty, unit_price),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_order_item_qty(item_id, qty):
    """ปรับจำนวนรายการที่สั่ง — ถ้าจำนวน <= 0 จะลบรายการนั้นทิ้ง"""
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise BookingError("จำนวนต้องเป็นตัวเลข")

    conn = get_conn()
    try:
        row = conn.execute(
            """SELECT oi.id FROM order_items oi
               JOIN reservations r ON r.id = oi.reservation_id
               WHERE oi.id = ? AND r.status = 'confirmed'""",
            (item_id,),
        ).fetchone()
        if not row:
            raise BookingError("ไม่พบรายการนี้ หรือปิดบิลไปแล้ว")
        if qty <= 0:
            conn.execute("DELETE FROM order_items WHERE id = ?", (item_id,))
        else:
            conn.execute("UPDATE order_items SET qty = ? WHERE id = ?", (qty, item_id))
        conn.commit()
    finally:
        conn.close()


def remove_order_item(item_id):
    conn = get_conn()
    try:
        row = conn.execute(
            """SELECT oi.id FROM order_items oi
               JOIN reservations r ON r.id = oi.reservation_id
               WHERE oi.id = ? AND r.status = 'confirmed'""",
            (item_id,),
        ).fetchone()
        if not row:
            raise BookingError("ไม่พบรายการนี้ หรือปิดบิลไปแล้ว")
        conn.execute("DELETE FROM order_items WHERE id = ?", (item_id,))
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("สร้างฐานข้อมูลเรียบร้อย ->", DB_PATH)
    print("จำนวนโต๊ะ:", len(list_tables()))
