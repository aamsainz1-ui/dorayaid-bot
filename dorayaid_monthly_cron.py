#!/usr/bin/env python3
"""Dorayaid Bot — สรุปรายเดือน auto (รันวันที่ 1 ของเดือน 00:30 BKK)"""
import json, os, requests
from datetime import datetime, timedelta
from collections import OrderedDict

BOT_TOKEN = os.getenv("DORAYAID_BOT_TOKEN", "")
GROUP_ID = int(os.getenv("DORAYAID_GROUP_ID", "-5248748067"))
LOG_FILE = os.getenv("DORAYAID_LOG_FILE", "/root/dorayaid_transfers.json")
EXCEL_DIR = "/root/dorayaid_excel/"
BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

def load_db():
    try:
        return json.load(open(LOG_FILE))
    except:
        return {"transfers": []}

def send(text):
    requests.post(f"{BASE}/sendMessage", json={"chat_id": GROUP_ID, "text": text}, timeout=10)

def send_file(path, caption=""):
    with open(path, "rb") as f:
        requests.post(f"{BASE}/sendDocument", data={"chat_id": GROUP_ID, "caption": caption}, files={"document": f}, timeout=30)

def run():
    # สรุปเดือนที่แล้ว
    now = datetime.utcnow() + timedelta(hours=7)
    last_month = (now.replace(day=1) - timedelta(days=1))
    ym = last_month.strftime("%Y-%m")
    month_name = last_month.strftime("%m/%Y")

    db = load_db()
    trans = [t for t in db["transfers"] if t["date"].startswith(ym) and t.get("category", "slip") == "slip"]

    if not trans:
        send(f"📊 สรุปเดือน {month_name}\nไม่มีรายการค่ะ")
        return

    total = sum(t["amount"] for t in trans)

    # แยกตาม tg_sender
    by_tg = OrderedDict()
    for t in trans:
        s = t.get("tg_sender", "ไม่ระบุ")
        by_tg.setdefault(s, []).append(t)

    # แยกตามวัน
    by_date = OrderedDict()
    for t in trans:
        d = t["date"][:10]
        by_date.setdefault(d, []).append(t)

    txt = f"📊 สรุปรายเดือน ({month_name})\n"
    txt += f"💰 ยอดรวม: {total:,.2f} บาท ({len(trans)} รายการ)\n"
    txt += f"📅 จำนวนวัน: {len(by_date)} วัน\n"
    txt += f"━━━━━━━━━━━━━━━\n"

    for tg_name, items in by_tg.items():
        st = sum(t["amount"] for t in items)
        txt += f"👤 {tg_name} — {len(items)} รายการ | {st:,.2f} บาท\n"

    send(txt)

    # สร้าง Excel
    try:
        import openpyxl
        os.makedirs(EXCEL_DIR, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"สรุป {month_name}"
        ws.append(["วันที่", "เวลา", "ผู้โอน", "คนส่งรูป", "ผู้รับ", "ยอด", "ธนาคาร", "ประเภท"])

        for tg_name, items in by_tg.items():
            ws.append([])
            ws.append([f"--- {tg_name} ---"])
            for t in sorted(items, key=lambda x: x.get("time", "")):
                ws.append([
                    t.get("date", ""), t.get("slip_time", ""),
                    t.get("sender", ""), t.get("tg_sender", ""),
                    t.get("receiver", ""), t.get("amount", 0),
                    t.get("bank", ""), t.get("type", "")
                ])
            st = sum(t["amount"] for t in items)
            ws.append(["", "", "", "", "รวม", st])

        ws.append([])
        ws.append(["", "", "", "", "รวมทั้งหมด", total])

        fname = f"{EXCEL_DIR}dorayaid_{ym}.xlsx"
        wb.save(fname)
        send_file(fname, f"📎 Excel สรุปเดือน {month_name}")
    except Exception as e:
        print(f"[monthly excel error] {e}")

    # Archive: ลบรายการเดือนเก่า (เก็บไว้ 3 เดือน)
    cutoff = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    old_count = len(db["transfers"])
    db["transfers"] = [t for t in db["transfers"] if t["date"] >= cutoff]
    new_count = len(db["transfers"])
    if old_count != new_count:
        json.dump(db, open(LOG_FILE, "w"), ensure_ascii=False)
        print(f"[monthly] cleaned {old_count - new_count} old records")

if __name__ == "__main__":
    run()
