"""
server.py — เว็บเซิร์ฟเวอร์ของระบบจองโต๊ะ
ใช้ http.server (ไลบรารีมาตรฐาน) ไม่ต้องติดตั้ง Flask/Django

รัน:  python3 server.py
เปิด: http://localhost:8000            (หน้าลูกค้าจองโต๊ะ)
      http://localhost:8000/admin.html (หน้าแอดมินดูรายการจอง — ต้องใส่รหัสผ่าน)

ตั้งรหัสผ่านแอดมินด้วย env var ADMIN_USER / ADMIN_PASSWORD
(ถ้าไม่ตั้ง ADMIN_PASSWORD จะใช้ค่าเริ่มต้น "changeme" — อย่าใช้ค่านี้ตอน deploy จริง)

ตั้ง env var LINE_CHANNEL_ACCESS_TOKEN เพื่อแจ้งเตือนเข้า LINE OA ทุกครั้งที่มีการจองใหม่
(ไม่ตั้งก็ได้ ระบบจองยังทำงานปกติ แค่จะไม่ส่งแจ้งเตือน)
"""
import base64
import hmac
import json
import os
import re
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db

# กันข้อความไทยพังตอน print บน Windows console (cp1252)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PORT = int(os.environ.get("PORT", "8000"))
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "public")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
if ADMIN_PASSWORD == "changeme":
    print("⚠ คำเตือน: ยังใช้รหัสผ่านแอดมินเริ่มต้น — ตั้ง env var ADMIN_PASSWORD ก่อน deploy จริง")

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")


def notify_line(message):
    """ส่งข้อความแจ้งเตือนเข้า LINE OA (broadcast ถึงทุกคนที่แอดเพื่อนไว้) แบบไม่บล็อกการตอบกลับลูกค้า"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return

    def _send():
        try:
            req = urllib.request.Request(
                "https://api.line.me/v2/bot/message/broadcast",
                data=json.dumps({"messages": [{"type": "text", "text": message}]}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print("แจ้งเตือน LINE ไม่สำเร็จ:", e)

    threading.Thread(target=_send, daemon=True).start()

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "BarBooking/1.0"

    # ---------- helper ----------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _is_authorized(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
            user, _, pwd = decoded.partition(":")
        except Exception:
            return False
        return hmac.compare_digest(user, ADMIN_USER) and hmac.compare_digest(pwd, ADMIN_PASSWORD)

    def _require_auth(self):
        body = "ต้องเข้าสู่ระบบก่อนใช้งานหน้าแอดมิน".encode("utf-8")
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="HOLLOW admin"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path):
        # ป้องกัน path traversal
        if path in ("", "/"):
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(PUBLIC_DIR, safe)
        if not os.path.abspath(full).startswith(os.path.abspath(PUBLIC_DIR)):
            self.send_error(403)
            return
        if not os.path.isfile(full):
            self.send_error(404, "ไม่พบไฟล์")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- routing ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/tables":
            return self._send_json({"tables": db.list_tables()})

        if path == "/api/availability":
            date = (qs.get("date", [""])[0]).strip()
            time = (qs.get("time", [""])[0]).strip()
            if not date or not time:
                return self._send_json({"error": "ต้องระบุ date และ time"}, 400)
            return self._send_json({"taken": db.taken_table_ids(date, time)})

        if path == "/api/reservations":
            if not self._is_authorized():
                return self._require_auth()
            date = (qs.get("date", [None])[0])
            return self._send_json({"reservations": db.list_reservations(date)})

        if path == "/api/walkin-sales":
            if not self._is_authorized():
                return self._require_auth()
            date = (qs.get("date", [None])[0])
            return self._send_json({"sales": db.list_walkin_sales(date)})

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if path in ("/admin.html", "/admin.js"):
            if not self._is_authorized():
                return self._require_auth()
            return self._serve_static(path)

        # ไฟล์ static
        return self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/reservations":
            data = self._read_json()
            try:
                res_id = db.create_reservation(data)
                table_name = db.get_table_name(data.get("table_id"))
                notify_line(
                    "🔔 มีการจองโต๊ะใหม่!\n"
                    f"โต๊ะ: {table_name}\n"
                    f"วันที่: {data.get('res_date')} เวลา {data.get('res_time')} น.\n"
                    f"จำนวน: {data.get('party_size')} คน\n"
                    f"ชื่อ: {data.get('customer_name')}\n"
                    f"เบอร์: {data.get('phone')}\n"
                    f"IG: {data.get('instagram')}"
                )
                return self._send_json({"ok": True, "id": res_id}, 201)
            except db.BookingError as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)
            except Exception as e:
                return self._send_json({"ok": False, "error": "เกิดข้อผิดพลาดภายในระบบ"}, 500)

        m = re.match(r"^/api/reservations/(\d+)/cancel$", path)
        if m:
            if not self._is_authorized():
                return self._require_auth()
            ok = db.cancel_reservation(int(m.group(1)))
            return self._send_json({"ok": ok})

        m = re.match(r"^/api/reservations/(\d+)/checkout$", path)
        if m:
            if not self._is_authorized():
                return self._require_auth()
            data = self._read_json()
            try:
                ok = db.checkout_reservation(int(m.group(1)), data.get("paid_amount"))
                return self._send_json({"ok": ok})
            except db.BookingError as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)

        m = re.match(r"^/api/reservations/(\d+)/items$", path)
        if m:
            if not self._is_authorized():
                return self._require_auth()
            data = self._read_json()
            try:
                item_id = db.add_order_item(
                    int(m.group(1)), data.get("name"), data.get("qty"), data.get("unit_price")
                )
                return self._send_json({"ok": True, "id": item_id}, 201)
            except db.BookingError as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)

        m = re.match(r"^/api/order-items/(\d+)/qty$", path)
        if m:
            if not self._is_authorized():
                return self._require_auth()
            data = self._read_json()
            try:
                db.update_order_item_qty(int(m.group(1)), data.get("qty"))
                return self._send_json({"ok": True})
            except db.BookingError as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)

        m = re.match(r"^/api/order-items/(\d+)/remove$", path)
        if m:
            if not self._is_authorized():
                return self._require_auth()
            try:
                db.remove_order_item(int(m.group(1)))
                return self._send_json({"ok": True})
            except db.BookingError as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)

        if path == "/api/walkin-sales":
            if not self._is_authorized():
                return self._require_auth()
            data = self._read_json()
            try:
                sale_id = db.add_walkin_sale(
                    data.get("sale_date"), data.get("note"), data.get("paid_amount")
                )
                return self._send_json({"ok": True, "id": sale_id}, 201)
            except db.BookingError as e:
                return self._send_json({"ok": False, "error": str(e)}, 400)

        m = re.match(r"^/api/walkin-sales/(\d+)/delete$", path)
        if m:
            if not self._is_authorized():
                return self._require_auth()
            ok = db.delete_walkin_sale(int(m.group(1)))
            return self._send_json({"ok": ok})

        self.send_error(404)

    def log_message(self, fmt, *args):
        # log แบบสั้น ๆ
        print("  %s - %s" % (self.address_string(), fmt % args))


def main():
    db.init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("=" * 48)
    print("  ระบบจองโต๊ะพร้อมใช้งาน")
    print(f"  ลูกค้า : http://localhost:{PORT}")
    print(f"  แอดมิน : http://localhost:{PORT}/admin.html  (user: {ADMIN_USER})")
    print("  กด Ctrl+C เพื่อหยุด")
    print("=" * 48)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nปิดเซิร์ฟเวอร์แล้ว")
        server.shutdown()


if __name__ == "__main__":
    main()
