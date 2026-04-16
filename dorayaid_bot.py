#!/usr/bin/env python3
"""Dorayaid Bot — เช็คสลิปโอนเงิน อ่านยอดด้วย MiniMax Vision"""
import requests, json, re, os, time, base64
from datetime import datetime, timedelta
# EasyOCR removed - ใช้ Gemini 2.5 Flash เป็นตัวหลักแทน

BOT_TOKEN = os.getenv("DORAYAID_BOT_TOKEN", "")
GROUP_ID = int(os.getenv("DORAYAID_GROUP_ID", "-5248748067"))
LOG_FILE = os.getenv("DORAYAID_LOG_FILE", "/root/dorayaid_transfers.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

def today_bkk():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")

def now_bkk():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")

def send(chat_id, text, reply_to=None):
    d = {"chat_id": chat_id, "text": text}
    if reply_to: d["reply_to_message_id"] = reply_to
    try:
        r = requests.post(f"{BASE}/sendMessage", json=d, timeout=10)
        print(f"[send] {r.status_code} {r.text[:100]}")
    except Exception as e:
        print(f"[send error] {e}")

def react(chat_id, msg_id, emoji="✅"):
    try:
        requests.post(f"{BASE}/setMessageReaction", json={
            "chat_id": chat_id, "message_id": msg_id,
            "reaction": [{"type": "emoji", "emoji": emoji}]
        }, timeout=10)
    except: pass

def load_db():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f: return json.load(f)
    return {"transfers": []}

def save_db(db):
    with open(LOG_FILE, "w") as f: json.dump(db, f, ensure_ascii=False, indent=2)

def read_slip_vision(img_path):
    """อ่านสลิปด้วย Gemini เป็นหลัก, tesseract เป็น fallback"""
    import re as re2
    amount, account, receiver, sender_name, slip_time = None, "", "", "", ""
    tx_type = "ไม่ระบุ"

    # === Gemini 2.5 Flash (ตัวหลัก) ===
    gemini_ok = False
    if GEMINI_API_KEY:
        try:
            with open(img_path, 'rb') as f:
                img_b64 = base64.b64encode(f.read()).decode()
            gr = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "parts": [
                            {"text": """วิเคราะห์ภาพนี้ (อาจเป็นสลิปตรงๆ หรือสลิปที่อยู่ในรูปแคปหน้าจอ/แชท ให้ดึงข้อมูลสลิปที่เห็นในภาพ):
1) ถ้าเห็นสลิปโอนเงิน/จ่ายบิล/ชำระเงิน → ตอบ JSON: {"type":"slip","amount":number,"sender":"ชื่อผู้โอน","receiver":"ชื่อผู้รับ","bank_name":"ธนาคาร","date":"DD/MM/YYYY","time":"HH:MM","tx_type":"ฝาก/ถอน","ref_code":"เลขอ้างอิง/รหัสอ้างอิง"}
bank_name ต้องระบุเสมอ: SCB=ไทยพาณิชย์, KBANK=กสิกรไทย, KTB=กรุงไทย, BBL=กรุงเทพ, TTB=ทหารไทยธนชาต, BAY=กรุงศรีอยุธยา, GSB=ออมสิน, BAAC=ธ.ก.ส., GHB=อาคารสงเคราะห์, CIMB=ซีไอเอ็มบี, TISCO=ทิสโก้, KKP=เกียรตินาคิน, LHFG=แลนด์, UOB=ยูโอบี, ICBC=ไอซีบีซี, TrueMoney=ทรูมันนี่, PromptPay=พร้อมเพย์ — ใช้ชื่อย่อภาษาอังกฤษ (SCB, KBANK, KTB, BBL ฯลฯ) ห้ามเว้นว่าง
2) ถ้าเป็นหน้าเว็บ/แดชบอร์ด → ตอบ JSON: {"type":"web","deposit":number,"withdraw":number}
3) ถ้าไม่ใช่ทั้งสอง → ตอบ JSON: {"type":"other"}
สำคัญ: ถ้าเห็นสลิปในภาพไม่ว่าจะชัดแค่ไหน ให้พยายามอ่านให้ได้ ตอบ JSON เท่านั้น"""},
                            {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                        ]
                    }]
                },
                timeout=15
            )
            gt = gr.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            m = re2.search(r"\{.*\}", gt, re2.DOTALL)
            if m:
                gd = json.loads(m.group(0))
                gtype = gd.get("type", "")
                print(f"[gemini] type={gtype} data={gd}")
                if gtype == "web":
                    dep = float(str(gd.get("deposit", 0)).replace(',',''))
                    wd = float(str(gd.get("withdraw", 0)).replace(',',''))
                    return dep - wd, "", f"__WEB__:{dep}:{wd}", "", "", "ไม่ใช่สลิป"
                elif gtype == "other":
                    # retry: บังคับหาสลิปซ้อนในภาพ
                    try:
                        gr2 = requests.post(
                            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                            headers={"Content-Type": "application/json"},
                            json={"contents": [{"parts": [
                                {"text": "ในภาพนี้มีสลิปโอนเงินซ่อนอยู่ (อาจเป็นแคปหน้าจอ/ถ่ายจากมือถืออีกที) ช่วยหาสลิปแล้วดึงข้อมูล ตอบ JSON: {\"type\":\"slip\",\"amount\":number,\"sender\":\"ชื่อผู้โอน\",\"receiver\":\"ชื่อผู้รับ\",\"bank_name\":\"ธนาคาร\",\"time\":\"HH:MM\",\"tx_type\":\"ฝาก/ถอน\"} ถ้าไม่เห็นจริงๆ ตอบ {\"type\":\"other\"}"},
                                {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                            ]}]},
                            timeout=15
                        )
                        gt2 = gr2.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        m2 = re2.search(r"\{.*\}", gt2, re2.DOTALL)
                        if m2:
                            gd2 = json.loads(m2.group(0))
                            if gd2.get("type") == "slip" and gd2.get("amount"):
                                print(f"[gemini-retry] found slip: {gd2}")
                                amount = float(str(gd2.get('amount',0)).replace(',',''))
                                sender_name = str(gd2.get('sender', '')).strip()
                                receiver = str(gd2.get('receiver', '')).strip()
                                account = str(gd2.get('bank_name', '')).strip()
                                st = str(gd2.get('time', '')).strip()
                                if re2.search(r'\d{1,2}:\d{2}', st):
                                    slip_time = st + (' น.' if 'น.' not in st else '')
                                gt_tx = str(gd2.get('tx_type', '')).strip()
                                if gt_tx in ('ฝาก', 'ถอน'): tx_type = gt_tx
                                gemini_ok = amount > 0
                            else:
                                return None, "", "__NON_SLIP__", "", "", "ไม่ใช่สลิป"
                        else:
                            return None, "", "__NON_SLIP__", "", "", "ไม่ใช่สลิป"
                    except:
                        return None, "", "__NON_SLIP__", "", "", "ไม่ใช่สลิป"
                elif gtype == "slip":
                    ga = gd.get("amount")
                    try: amount = float(str(ga).replace(',','')) if ga else None
                    except: amount = None
                    sender_name = str(gd.get("sender", "")).strip()
                    receiver = str(gd.get("receiver", "")).strip()
                    account = str(gd.get("bank_name", "") or gd.get("bank", "")).strip()
                    st = str(gd.get("time", "")).strip()
                    if re2.search(r"\d{1,2}:\d{2}", st):
                        slip_time = st + (" น." if "น." not in st else "")
                    ref_code = str(gd.get("ref_code", "")).strip()
                    gt_tx = str(gd.get("tx_type", "")).strip()
                    if gt_tx in ("ฝาก", "ถอน"): tx_type = gt_tx
                    gemini_ok = amount is not None and amount > 0
        except Exception as e:
            inc_stat('gemini_fail')
            print(f"[gemini-err] {e}")

    # === tesseract fallback (เฉพาะ Gemini พลาด) ===
    if gemini_ok and amount and amount > 0:
        inc_stat('gemini_ok')
        # Gemini สำเร็จ — ข้าม tesseract เลย
        txt = ""
        txt_tess = ""
        print(f"[skip-tess] gemini ok, amount={amount}")
    else:
        try:
            from PIL import Image
            import cv2, numpy as np, pytesseract
            img_cv = cv2.imread(img_path)
            img_cv = cv2.resize(img_cv, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            img = Image.fromarray(thresh)
            txt1 = pytesseract.image_to_string(img, config=r'-l tha+eng --oem 1 --psm 6 --dpi 300')
            txt2 = pytesseract.image_to_string(img, config=r'-l tha+eng --oem 1 --psm 11 --dpi 300')
            txt_tess = (txt1 or "") + "\n" + (txt2 or "")
            txt = txt_tess
            print(f"[ocr-tess] {txt_tess[:150]}")

        except Exception as e:
            print(f"[ocr-tess error] {e}")
            txt = ""
            txt_tess = ""
        # กันเคสอ่านข้อความบอทย้อนกลับจากภาพแชต (feedback loop)
        bot_echo_kw = ("รับสลิปแล้วค่ะ" in txt) or ("ยอดรวมวันนี้" in txt) or ("ประเภท:" in txt and "บาท" in txt)
        if bot_echo_kw:
            return None, "", "__NON_SLIP__", "", "", "ไม่ใช่สลิป"

        # กันเคสแคปหน้าแชต/รูปที่ไม่ใช่สลิปจริง (แต่รองรับทั้งโอนเงิน/จ่ายบิล)
        has_amount_kw = ("จำนวนเงิน" in txt or "จํานวนเงิน" in txt)
        has_slip_kw = ("โอนเงินสําเร็จ" in txt or "โอนเงินสำเร็จ" in txt or "อนเงินสําเร็จ" in txt or "อนเงินสำเร็จ" in txt or "จ่ายบิลสําเร็จ" in txt or "จ่ายบิลสำเร็จ" in txt or "ชําระเงินสําเร็จ" in txt or "ชำระเงินสำเร็จ" in txt or "สําเร็จ" in txt or "สำเร็จ" in txt or "ไปยัง" in txt or "ถึง" in txt or "รหัสอ้างอิง" in txt or "รหัสย" in txt or "make" in txt.lower())
        if ("ฝาก" in txt or "รับเงิน" in txt or "เงินเข้า" in txt):
            tx_type = "ฝาก"
        else:
            tx_type = "ถอน"
        if not (has_amount_kw or has_slip_kw):
            # ไม่ใช่สลิป: อ่านแบบหน้าสรุปเว็บ (ชุดหลักบนสุด)
            if GEMINI_API_KEY:
                try:
                    with open(img_path, 'rb') as f:
                        img_b64 = base64.b64encode(f.read()).decode()
                    gr = requests.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                        headers={"Content-Type": "application/json"},
                        json={
                            "contents": [{
                                "parts": [
                                    {"text": "ภาพนี้เป็นหน้าสรุปเว็บ ไม่ใช่สลิป ให้ดึงเฉพาะชุดตัวเลขหลักบนสุดเท่านั้น แล้วตอบ JSON: {\"deposit\": number|null, \"withdraw\": number|null}"},
                                    {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                                ]
                            }]
                        },
                        timeout=10
                    )
                    gt = gr.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    m = re2.search(r"\{.*\}", str(gt), re2.DOTALL)
                    if m:
                        gd = json.loads(m.group(0))
                        dep = gd.get("deposit")
                        wd = gd.get("withdraw")
                        try:
                            dep = float(str(dep).replace(',', '')) if dep is not None else 0.0
                        except:
                            dep = 0.0
                        try:
                            wd = float(str(wd).replace(',', '')) if wd is not None else 0.0
                        except:
                            wd = 0.0
                        return dep - wd, "", f"__WEB__:{dep}:{wd}", "", "", "ไม่ใช่สลิป"
                except Exception as ge:
                    print(f"[gemini non-slip error] {ge}")
            return None, "", "__NON_SLIP__", "", "", "ไม่ใช่สลิป"
        names = re2.findall(r"(?:นาย|นาง|น\.ส\.|นางสาว)\s*[^\n]{2,30}", txt)
        if len(names) >= 2:
            sender_name = names[0].strip()
            receiver = names[1].strip()
        elif len(names) == 1:
            receiver = names[0].strip()

        # fallback จับชื่อจากบรรทัด "จาก" / "ไปยัง" / "ถึง" (รองรับหลายธนาคาร)
        if not sender_name:
            m_from = re2.search(r"(?:จาก|ผู้โอน|ต้นทาง)\s*[:：]?\s*([^\n]{3,40})", txt)
            if m_from:
                sender_name = m_from.group(1).strip()
        if not receiver:
            m_to = re2.search(r"(?:ไปยัง|ถึง|ผู้รับ|ปลายทาง)\s*[:：]?\s*([^\n]{3,40})", txt)
            if m_to:
                receiver = m_to.group(1).strip()

        # clean เศษ OCR
        sender_name = re2.sub(r"\s{2,}", " ", sender_name).strip(" -:|/\\")
        receiver = re2.sub(r"\s{2,}", " ", receiver).strip(" -:|/\\")

        def _norm_amount_token(token):
            s = (token or '').replace(' ', '')
            if not s:
                return None
            # หลายตัวคั่น ให้ตัวสุดท้ายเป็นทศนิยม
            if s.count('.') + s.count(',') > 1:
                s2 = re2.sub(r'[^\d\.,]', '', s)
                sep_pos = max(s2.rfind('.'), s2.rfind(','))
                whole = re2.sub(r'[^\d]', '', s2[:sep_pos])
                dec = re2.sub(r'[^\d]', '', s2[sep_pos+1:])[:2]
                if whole and dec:
                    try:
                        return float(f"{int(whole)}.{dec}")
                    except:
                        return None
                return None
            s = s.replace(',', '.')
            try:
                return float(s)
            except:
                return None

        def _extract_amount(text_blob):
            if not text_blob:
                return None
            # 1) โฟกัสบรรทัดใกล้คำว่า จำนวนเงิน เท่านั้น
            lines = text_blob.splitlines()
            for i, line in enumerate(lines):
                if ('จำนวนเงิน' in line) or ('จํานวนเงิน' in line):
                    window = '\n'.join(lines[i:i+3])
                    toks = re2.findall(r"\d{1,3}(?:[\.,]\d{3})+[\.,]\d{2}|\d+[\.,]\d{2}", window)
                    vals = [_norm_amount_token(t) for t in toks]
                    vals = [v for v in vals if v is not None and v > 0]
                    if vals:
                        return max(vals)
            # 2) fallback ทั้งข้อความ แต่ตัดค่าธรรมเนียม/ยอด 0
            toks = re2.findall(r"\d{1,3}(?:[\.,]\d{3})+[\.,]\d{2}|\d+[\.,]\d{2}", text_blob)
            vals = [_norm_amount_token(t) for t in toks]
            vals = [v for v in vals if v is not None and v > 0.99]
            return max(vals) if vals else None

        # cross-vote: Gemini (primary) vs tesseract (fallback)
        amount_tess = _extract_amount(txt_tess)
        if gemini_ok and amount:
            # Gemini ได้แล้ว — ใช้ Gemini, tess เป็นตัวเทียบ
            if amount_tess and abs(amount - amount_tess) / max(amount, amount_tess) <= 0.15:
                print(f"[cross] gemini={amount} tess={amount_tess} MATCH")
            else:
                print(f"[cross] gemini={amount} tess={amount_tess} ใช้gemini")
        else:
            # Gemini พลาด — fallback ใช้ tess
            if amount_tess:
                amount = amount_tess
            print(f"[cross] gemini=FAIL tess={amount_tess} ใช้tess")
        amount_candidates = [x for x in [amount_tess, amount] if x is not None and x > 0]

        # second pass เฉพาะ tesseract ถ้ายอดยังเล็กผิดปกติ (กันตกหลัก 7,100 -> 710 / 37,500 -> 375)
        if amount is not None and amount < 1000:
            try:
                data = pytesseract.image_to_data(img, lang='tha+eng', config=r'--oem 1 --psm 6', output_type=pytesseract.Output.DICT)
                keys = data.get('text', [])
                target_i = -1
                for i, w in enumerate(keys):
                    w = (w or '').strip()
                    if 'จำนวนเงิน' in w or 'จํานวนเงิน' in w or w == 'จำนวน' or w == 'จํานวน':
                        target_i = i
                        break
                if target_i >= 0:
                    y = data['top'][target_i]
                    h = data['height'][target_i]
                    y1 = max(0, y - 10)
                    y2 = min(thresh.shape[0], y + h + 120)
                    roi = thresh[y1:y2, :]
                    roi_txt = pytesseract.image_to_string(roi, config=r'--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789.,')
                    cand2 = re2.findall(r"\d{1,3}(?:[\.,]\d{3})+[\.,]\d{2}|\d+[\.,]\d{2}", roi_txt)
                    parsed = []
                    for c in cand2:
                        s = c.replace(' ', '')
                        if s.count('.') + s.count(',') > 1:
                            s2 = re2.sub(r'[^\d\.,]', '', s)
                            sep_pos = max(s2.rfind('.'), s2.rfind(','))
                            whole = re2.sub(r'[^\d]', '', s2[:sep_pos])
                            dec = re2.sub(r'[^\d]', '', s2[sep_pos+1:])[:2]
                            if whole and dec:
                                s = f"{whole}.{dec}"
                            else:
                                continue
                        else:
                            s = s.replace(',', '.')
                        try:
                            parsed.append(float(s))
                        except:
                            pass
                    if parsed:
                        amount = max(amount or 0, max(parsed))
            except Exception:
                pass

        t = re2.search(r"(\d{1,2}:\d{2}:\d{2}\s*น\.)", txt)
        if not t: t = re2.search(r"(\d{1,2}:\d{2}\s*น\.)", txt)
        if t: slip_time = t.group(1).strip()

        # (Gemini เป็นตัวหลักแล้ว ไม่ต้อง fallback ซ้ำ)

        # รวมผลทุกตัว (tess + paddle + gemini) เพื่อกันพลาดหลายรูปแบบ
        if amount_candidates:
            best = None
            best_score = -1
            for c in amount_candidates:
                score = 0
                for d in amount_candidates:
                    if c == d:
                        score += 1
                    elif abs(c - d) / max(c, d) <= 0.15:
                        score += 1
                if score > best_score or (score == best_score and (best is None or c > best)):
                    best, best_score = c, score
            amount = best
            # ถ้าค่าผิดกันมากทุกตัว ให้ถือว่าไม่มั่นใจ
            if len(amount_candidates) >= 2 and best_score < 2:
                return None, "", "__UNCERTAIN__", "", "", "ไม่ระบุ"

        # confidence gate
        if amount is None or amount <= 0:
            return None, "", "", "", "", tx_type

        if not sender_name:
            sender_name = "ไม่ระบุ"
        if not receiver:
            receiver = "ไม่ระบุ"
        if not slip_time:
            slip_time = "ไม่ระบุ"


    return amount, account, receiver, sender_name, slip_time, tx_type

def send_excel(chat_id):
    try:
        import openpyxl
        db = load_db()
        today = today_bkk()
        trans = [t for t in db["transfers"] if t["date"].startswith(today)]
        if not trans: return
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = today
        ws.append(["#", "ผู้ส่ง", "ยอด (บาท)", "ผู้โอน", "ผู้รับ", "ธนาคาร", "เวลา", "วันที่", "ประเภท"])
        # เรียงตาม sender
        from collections import OrderedDict
        by_tg = OrderedDict()
        for t in trans:
            s = t.get('tg_sender', t.get('sender', 'ไม่ระบุ'))
            by_tg.setdefault(s, []).append(t)
        idx = 1
        for tg_name, items in by_tg.items():
            sender_total = sum(t.get('amount',0) for t in items)
            ws.append(["", f"👤 {tg_name} ({len(items)} รายการ)", sender_total, "", "", "", "", "", ""])
            for t in items:
                ws.append([idx, t.get('sender',''), t.get('amount',0), t.get('bank',''), t.get('receiver',''), t.get('bank_name',''), t.get('slip_time',''), t.get('date',''), t.get('type','ไม่ระบุ')])
                idx += 1
        # ยอดรวมทั้งหมด
        total = sum(t.get('amount',0) for t in trans)
        ws.append(["", "รวมทั้งหมด", total, "", "", "", "", "", ""])
        # ปรับความกว้างคอลัมน์
        for col in ws.columns:
            max_len = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = max(12, max_len + 2)
        path = f"/tmp/slip_summary_{today}.xlsx"
        wb.save(path)
        with open(path, "rb") as f:
            requests.post(f"{BASE}/sendDocument", data={"chat_id": chat_id, "caption": f"📅 Excel สรุปยอดโอน {today}"}, files={"document": (f"slip_{today}.xlsx", f)}, timeout=15)
        os.remove(path)
    except Exception as e:
        print(f"[excel error] {e}")

def make_summary():
    db = load_db()
    today = today_bkk()
    trans = [t for t in db["transfers"] if t["date"].startswith(today)]
    if not trans:
        return "📊 สรุปยอดวันนี้\nยังไม่มีรายการค่ะ"

    slip_trans = [t for t in trans if t.get("category", "slip") == "slip"]
    other_trans = [t for t in trans if t.get("category", "slip") != "slip"]

    total = sum(t["amount"] for t in slip_trans)
    deposit_total = sum(t["amount"] for t in slip_trans if t.get("type") == "ฝาก")
    withdraw_total = sum(t["amount"] for t in slip_trans if t.get("type") == "ถอน")
    net_total = deposit_total - withdraw_total

    bkk_now = (datetime.utcnow() + timedelta(hours=7)).strftime("%d/%m/%Y")
    stats = load_stats()
    txt = f"📊 สรุปยอดวันนี้ ({bkk_now})\n"
    txt += f"💰 ยอดรวม: {total:,.2f} บาท ({len(slip_trans)} รายการ)\n"
    txt += f"━━━━━━━━━━━━━━━\n"
    tp = stats.get('total_photos', 0)
    gok = stats.get('gemini_ok', 0)
    gfail = stats.get('gemini_fail', 0)
    dups = stats.get('dup_slips', 0)
    if tp > 0:
        txt += f"📸 สลิปทั้งหมด: {tp} รูป\n"
        txt += f"✅ บันทึกได้: {len(slip_trans)} รายการ\n"
        txt += f"🔄 สลิปซ้ำ: {dups} รูป\n"
        txt += f"⚠️ มีปัญหา: {gfail} รูป\n"
        txt += f"━━━━━━━━━━━━━━━\n"

    from collections import OrderedDict
    by_tg = OrderedDict()
    for t in slip_trans:
        s = t.get('tg_sender', t.get('sender', 'ไม่ระบุ'))
        by_tg.setdefault(s, []).append(t)

    for tg_name, items in by_tg.items():
        sender_total = sum(t['amount'] for t in items)
        txt += f"👤 {tg_name} — {len(items)} รายการ | {sender_total:,.2f} บาท\n"

    # แยกรายการทรูมันนี่
    true_trans = [t for t in slip_trans if any(kw in (t.get('receiver','') + t.get('bank','')).lower() for kw in ['ทรู', 'truemoney', 'true', 'มันนี่', 'tmn'])]
    if true_trans:
        true_total = sum(t['amount'] for t in true_trans)
        txt += f"━━━━━━━━━━━━━━━\n"
        txt += f"📱 TrueMoney: {len(true_trans)} รายการ | {true_total:,.2f} บาท\n"
        true_by_tg = {}
        for t in true_trans:
            s = t.get('tg_sender', t.get('sender', 'ไม่ระบุ'))
            true_by_tg.setdefault(s, []).append(t)
        for s, items in true_by_tg.items():
            st = sum(t['amount'] for t in items)
            txt += f"   └ {s}: {len(items)} รายการ | {st:,.2f} บาท\n"

    # ยอดเว็บ
    web_trans = [t for t in trans if t.get('category') == 'web']
    if web_trans:
        web_dep = sum(t['amount'] for t in web_trans if t.get('type') == 'ฝาก')
        web_wd = sum(t['amount'] for t in web_trans if t.get('type') == 'ถอน')
        web_net = web_dep - web_wd
        txt += f"━━━━━━━━━━━━━━━\n"
        txt += f"🌐 ยอดเว็บ: {len(web_trans)} รายการ\n"
        txt += f"🟢 ฝาก: {web_dep:,.2f} บาท\n"
        txt += f"🔴 ถอน: {web_wd:,.2f} บาท\n"
        txt += f"📊 สุทธิ: {web_net:,.2f} บาท\n"

    return txt

OFFSET_FILE = "/root/dorayaid_offset.txt"
PROCESSED_FILE = "/root/dorayaid_processed.json"
def load_processed():
    try:
        return set(json.load(open(PROCESSED_FILE)))
    except:
        return set()
def save_processed(s):
    # เก็บแค่ 500 รายการล่าสุด
    lst = list(s)[-500:]
    json.dump(lst, open(PROCESSED_FILE, 'w'))
def load_offset():
    try:
        return int(open(OFFSET_FILE).read().strip())
    except:
        return 0
def save_offset(v):
    open(OFFSET_FILE, 'w').write(str(v))
offset = load_offset()
processed = load_processed()

# Daily stats
STATS_FILE = "/root/dorayaid_stats.json"
def load_stats():
    try:
        return json.load(open(STATS_FILE))
    except:
        return {}
def save_stats(s):
    json.dump(s, open(STATS_FILE, 'w'), ensure_ascii=False)
def inc_stat(key):
    s = load_stats()
    today = today_bkk()
    if s.get('date') != today:
        s = {'date': today}
    s[key] = s.get(key, 0) + 1
    save_stats(s)

def poll():
    global offset
    try:
        r = requests.get(f"{BASE}/getUpdates",
            params={"offset": offset, "timeout": 55, "allowed_updates": ["message"]},
            timeout=65)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, OSError) as e:
        print(f"[poll] network error, retry in 5s: {e}")
        time.sleep(5)
        return
    updates = r.json().get("result", [])
    for u in updates:
        offset = u["update_id"] + 1
        save_offset(offset)
        msg = u.get("message", {})
        if not msg: continue
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "")
        if chat_id != GROUP_ID: continue

        msg_id = msg.get("message_id")
        if str(msg_id) in processed:
            continue
        processed.add(str(msg_id))
        save_processed(processed)
        sender = msg.get("from", {}).get("first_name", "ไม่ทราบ")
        photos = msg.get("photo")

        # text commands ทำก่อน photo
        cmd_raw = (text or "").strip().lower()
        cmd = cmd_raw.split()[0] if cmd_raw else ""
        if cmd.startswith("/"):
            cmd = cmd[1:]
        if "@" in cmd:
            cmd = cmd.split("@", 1)[0]

        if cmd in ["update"] or cmd_raw == "อัพเดท":
            # ดึงยอดเว็บล่าสุดจาก DB
            db = load_db()
            today_key = today_bkk()
            web_trans = [t for t in db['transfers'] if t.get('category') == 'web' and t['date'].startswith(today_key)]
            if not web_trans:
                send(chat_id, "ยังไม่มียอดเว็บวันนี้ค่ะ ส่งรูปหน้าเว็บเข้ามาแล้วบอทจะจับยอดให้อัตโนมัติค่ะ", reply_to=msg_id)
                continue
            dep_total = sum(t['amount'] for t in web_trans if t.get('type') == 'ฝาก')
            wd_total = sum(t['amount'] for t in web_trans if t.get('type') == 'ถอน')
            net = dep_total - wd_total
            # หายอดล่าสุด
            last = web_trans[-1]
            last_time = last.get('date', '?')
            # ยอดสลิปวันนี้
            slip_trans = [t for t in db['transfers'] if t['date'].startswith(today_key) and t.get('category','slip') == 'slip']
            slip_total = sum(t['amount'] for t in slip_trans)
            txt = f"📊 สรุปยอดวันนี้\n"
            txt += f"━━━━━━━━━━━━━━━\n"
            txt += f"🌐 ยอดเว็บ:\n"
            txt += f"🟢 ฝาก: {dep_total:,.2f} บาท\n"
            txt += f"🔴 ถอน: {wd_total:,.2f} บาท\n"
            txt += f"📊 สุทธิ: {net:,.2f} บาท\n"
            txt += f"━━━━━━━━━━━━━━━\n"
            txt += f"🧳 ยอดสลิป: {slip_total:,.2f} บาท ({len(slip_trans)} รายการ)\n"
            txt += f"━━━━━━━━━━━━━━━\n"
            txt += f"⏰ ล่าสุด: {last_time}"
            send(chat_id, txt, reply_to=msg_id)
            continue

        if cmd in ["summary"] or cmd_raw == "สรุป":
            send(chat_id, make_summary())
            send_excel(chat_id)
            continue
        elif cmd in ["detail", "แยก"]:
            db = load_db()
            today_key = today_bkk()
            slip = [t for t in db['transfers'] if t['date'].startswith(today_key) and t.get('category','slip') == 'slip']
            if not slip:
                send(chat_id, "ยังไม่มีรายการวันนี้ค่ะ", reply_to=msg_id)
                continue
            true_kw = ['ทรู','truemoney','true','มันนี่','tmn']
            by_tg = {}
            for t in slip:
                s = t.get('tg_sender', 'ไม่ระบุ')
                by_tg.setdefault(s, []).append(t)
            bkk_now = (datetime.utcnow() + timedelta(hours=7)).strftime('%d/%m/%Y')
            for tg_name, items in by_tg.items():
                total = sum(t['amount'] for t in items)
                true_items = [t for t in items if any(k in (t.get('receiver','')+t.get('bank','')).lower() for k in true_kw)]
                true_total = sum(t['amount'] for t in true_items)
                dep = sum(t['amount'] for t in items if t.get('type') == 'ฝาก')
                wd = sum(t['amount'] for t in items if t.get('type') == 'ถอน')
                transfer = sum(t['amount'] for t in items if t.get('type') not in ['ฝาก','ถอน'])
                txt = f"👤 {tg_name} ({bkk_now})\n"
                txt += f"━━━━━━━━━━━━━━━\n"
                txt += f"💰 ยอดรวม: {total:,.2f} บาท ({len(items)} รายการ)\n"
                if true_items:
                    txt += f"📱 TrueMoney: {len(true_items)} รายการ | {true_total:,.2f} บาท\n"
                send(chat_id, txt)
            continue
        elif cmd in ["excel"]:
            send_excel(chat_id)
            continue
        elif cmd in ["status"]:
            db = load_db()
            today_key = today_bkk()
            today_trans = [t for t in db["transfers"] if t["date"].startswith(today_key)]
            total = sum(t["amount"] for t in today_trans)
            count = len(today_trans)
            all_count = len(db.get("transfers", []))
            stats = load_stats()
            tp = stats.get('total_photos', 0)
            gok = stats.get('gemini_ok', 0)
            gfail = stats.get('gemini_fail', 0)
            dups = stats.get('dup_slips', 0)
            import subprocess
            try:
                pm2_out = subprocess.check_output(["pm2", "show", "dorayaid-bot"], text=True, timeout=5)
                uptime = ""
                restarts = ""
                for line in pm2_out.split("\n"):
                    if "uptime" in line: uptime = line.split("\u2502")[2].strip() if "\u2502" in line else ""
                    if "restarts" in line and "unstable" not in line: restarts = line.split("\u2502")[2].strip() if "\u2502" in line else ""
            except:
                uptime = "?"
                restarts = "?"
            txt = f"🤖 สถานะ Dorayaid Bot\n"
            txt += f"━━━━━━━━━━━━━━━\n"
            txt += f"✅ สถานะ: ทำงานปกติ\n"
            txt += f"⏱ Uptime: {uptime}\n"
            txt += f"🔄 Restarts: {restarts}\n"
            txt += f"━━━━━━━━━━━━━━━\n"
            txt += f"📊 วันนี้: {count} รายการ | {total:,.2f} บาท\n"
            txt += f"📸 รูปทั้งหมด: {tp} | ✅ อ่านได้: {gok} | ❌ พลาด: {gfail} | 🔄 ซ้ำ: {dups}\n"
            txt += f"━━━━━━━━━━━━━━━\n"
            txt += f"📁 DB ทั้งหมด: {all_count} รายการ\n"
            txt += f"🧠 OCR: Gemini 2.5 Flash (primary) + Tesseract (fallback)"
            send(chat_id, txt, reply_to=msg_id)
            continue
        elif cmd in ["help"]:
            send(chat_id, "📚 คำสั่งทั้งหมด:\n/summary — สรุปยอดวันนี้ (สลิป+ทรู+เว็บ)\n/detail — สรุปแยกรายคน\n/update — ดูยอดเว็บล่าสุด\n/excel — ส่ง Excel สรุป\n/status — สถานะบอท\n/reset — ล้างวันนี้ (มี backup)\n📸 ส่งรูปสลิป/หน้าเว็บ — จับยอดอัตโนมัติ", reply_to=msg_id)
            continue
        elif (cmd in ["reset"] or cmd_raw == "reset"):
            print(f"[cmd] reset from {msg.get('from', {}).get('id')}")
            db = load_db()
            today_key = today_bkk()
            today_trans = [t for t in db["transfers"] if t["date"].startswith(today_key)]
            old_count = len(today_trans)
            # archive ข้อมูลวันนี้ก่อนลบ + ส่ง Excel backup
            if today_trans:
                archive_dir = "/root/dorayaid_archive/"
                os.makedirs(archive_dir, exist_ok=True)
                ts = (datetime.utcnow() + timedelta(hours=7)).strftime("%H%M")
                archive_file = f"{archive_dir}dorayaid_{today_key}_{ts}.json"
                json.dump(today_trans, open(archive_file, 'w'), ensure_ascii=False, indent=2)
                # สร้าง Excel backup
                try:
                    import openpyxl
                    from collections import OrderedDict
                    excel_dir = "/root/dorayaid_excel/"
                    os.makedirs(excel_dir, exist_ok=True)
                    wb = openpyxl.Workbook()
                    ws = wb.active
                    ws.title = f"Backup {today_key}"
                    ws.append(["วันที่", "เวลา", "ผู้โอน", "คนส่งรูป", "ผู้รับ", "ยอด", "ธนาคาร", "ประเภท"])
                    by_tg = OrderedDict()
                    for t in today_trans:
                        s = t.get('tg_sender', 'ไม่ระบุ')
                        by_tg.setdefault(s, []).append(t)
                    for tg_name, items in by_tg.items():
                        ws.append([])
                        ws.append([f"--- {tg_name} ---"])
                        for t in sorted(items, key=lambda x: x.get('time', '')):
                            ws.append([t.get('date',''), t.get('slip_time',''), t.get('sender',''), t.get('tg_sender',''), t.get('receiver',''), t.get('amount',0), t.get('bank',''), t.get('type','')])
                        ws.append(['', '', '', '', 'รวม', sum(t['amount'] for t in items)])
                    ws.append([])
                    ws.append(['', '', '', '', 'รวมทั้งหมด', sum(t['amount'] for t in today_trans)])
                    excel_file = f"{excel_dir}backup_{today_key}_{ts}.xlsx"
                    wb.save(excel_file)
                    # ส่ง Excel เข้ากลุ่ม
                    with open(excel_file, 'rb') as ef:
                        requests.post(f"{BASE}/sendDocument", data={"chat_id": chat_id, "caption": f"📁 Backup วันนี้ ({old_count} รายการ)"}, files={"document": ef}, timeout=30)
                except Exception as e:
                    print(f"[reset excel error] {e}")
                print(f"[archive] saved {old_count} records to {archive_file}")
            db["transfers"] = [t for t in db["transfers"] if not t["date"].startswith(today_key)]
            save_db(db)
            save_stats({'date': today_key})
            react(chat_id, msg_id, "✅")
            send(chat_id, f"🗑 ลบข้อมูลวันนี้แล้วค่ะ ({old_count} รายการ) ยอดเริ่มนับใหม่", reply_to=msg_id)
            continue

        if photos:
            inc_stat('total_photos')
            file_id = photos[-1]["file_id"]
            fr = requests.get(f"{BASE}/getFile", params={"file_id": file_id}, timeout=10).json()
            fp = fr["result"]["file_path"]
            img_data = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}", timeout=15).content
            tmp = f"/tmp/slip_{msg_id}.jpg"
            with open(tmp, "wb") as f: f.write(img_data)

            amount, account, receiver, sender_name, slip_time, tx_type = read_slip_vision(tmp)
            os.remove(tmp)

            if receiver and str(receiver).startswith("__WEB__:"):
                react(chat_id, msg_id, "ℹ️")
                try:
                    _, dep, wd = str(receiver).split(":", 2)
                    dep_v = float(dep)
                    wd_v = float(wd)
                    net_v = dep_v - wd_v
                    # เก็บยอดเว็บลง DB
                    db2 = load_db()
                    db2['transfers'].append({'date': now_bkk(), 'amount': dep_v, 'sender': 'เว็บ', 'receiver': '-', 'bank': '-', 'type': 'ฝาก', 'tg_sender': sender, 'category': 'web', 'msg_id': msg_id})
                    if wd_v > 0:
                        db2['transfers'].append({'date': now_bkk(), 'amount': wd_v, 'sender': 'เว็บ', 'receiver': '-', 'bank': '-', 'type': 'ถอน', 'tg_sender': sender, 'category': 'web', 'msg_id': msg_id})
                    save_db(db2)
                    send(chat_id, f"📊 ยอดเว็บล่าสุด\n🟢 ฝาก: {dep_v:,.2f} บาท\n🔴 ถอน: {wd_v:,.2f} บาท\n📊 สุทธิ: {net_v:,.2f} บาท", reply_to=msg_id)
                except:
                    send(chat_id, "ℹ️ รูปนี้ไม่ใช่สลิปค่ะ", reply_to=msg_id)
            elif receiver == "__NON_SLIP__" or tx_type == "ไม่ใช่สลิป":
                react(chat_id, msg_id, "ℹ️")
                send(chat_id, "ℹ️ รูปนี้ไม่ใช่สลิปค่ะ", reply_to=msg_id)
            elif receiver == "__UNCERTAIN__":  
                react(chat_id, msg_id, "⚠️")
                send(chat_id, "⚠️ ไม่มั่นใจยอดจากสลิปนี้ กรุณาส่งรูปใหม่ให้ชัดขึ้นค่ะ", reply_to=msg_id)
            elif amount:
                db = load_db()
                today_key = today_bkk()
                # กันสลิปซ้ำ: ใช้เลขอ้างอิง (ref_code) ถ้ามี ไม่งั้น fallback เป็น amount+receiver+slip_time
                rc = locals().get('ref_code', '').strip()
                if rc and len(rc) > 3:
                    fp = f"ref|{rc}"
                else:
                    fp = f"{float(amount):.2f}|{(receiver or '').strip()}|{(slip_time or '').strip()}"
                dup = False
                for t in db.get("transfers", []):
                    if not t.get("date", "").startswith(today_key):
                        continue
                    tfp = t.get('fingerprint', '')
                    if not tfp:
                        tfp = f"{float(t.get('amount',0)):.2f}|{(t.get('receiver','') or '').strip()}|{(t.get('slip_time','') or '').strip()}"
                    if fp == tfp:
                        dup = True
                        break
                if dup:
                    inc_stat('dup_slips')
                    react(chat_id, msg_id, "ℹ️")
                    send(chat_id, "ℹ️ สลิปนี้ซ้ำกับรายการเดิมแล้วค่ะ ไม่นับเพิ่ม", reply_to=msg_id)
                    continue

                tg_user = msg.get("from", {})
                tg_name = (tg_user.get("first_name", "") + " " + tg_user.get("last_name", "")).strip() or "ไม่ทราบ"
                db["transfers"].append({
                    "date": today_bkk(), "time": now_bkk(),
                    "sender": sender, "tg_sender": tg_name, "amount": float(amount),
                    "account": account, "receiver": receiver, "bank": sender_name, "slip_time": slip_time, "type": tx_type,
                    "category": "slip", "fingerprint": fp
                })
                save_db(db)
                react(chat_id, msg_id, "✅")
                # คำนวณยอดรวมวันนี้ (แยกฝาก/ถอน)
                db2 = load_db()
                today_trans = [t for t in db2["transfers"] if t["date"].startswith(today_bkk()) and t.get("category", "slip") == "slip"]
                total = sum(t["amount"] for t in today_trans)
                deposit_total = sum(t["amount"] for t in today_trans if t.get("type") == "ฝาก")
                withdraw_total = sum(t["amount"] for t in today_trans if t.get("type") == "ถอน")
                net_total = deposit_total - withdraw_total
                count = len(today_trans)

                slip_time_disp = slip_time if (slip_time and str(slip_time).strip().lower() != "none") else "ไม่ระบุ"
                sender_disp = sender_name if sender_name else "ไม่ระบุ"
                receiver_disp = receiver if receiver else "ไม่ระบุ"

                reply = f"✅ รับสลิปแล้วค่ะ\n"
                reply += f"💰 ยอด: {float(amount):,.2f} บาท\n"

                reply += f"👤 ผู้โอน: {sender_disp}\n"
                reply += f"👥 ผู้รับ: {receiver_disp}\n"
                reply += f"🕐 {slip_time_disp}\n"
                reply += f"━━━━━━━━━━━━━━━\n"
                reply += f"📊 ยอดรวมวันนี้: {total:,.2f} บาท ({count} รายการ)"
                send(chat_id, reply, reply_to=msg_id)
            else:
                react(chat_id, msg_id, "❌")
                send(chat_id, "❌ อ่านสลิปไม่ได้ค่ะ กรุณาส่งรูปใหม่", reply_to=msg_id)



ALERT_USER_ID = int(os.getenv("DORAYAID_ALERT_USER_ID", "0"))  # @ppxv88

def send_alert(text):
    """ส่งแจ้งเตือนหา @ppxv88"""
    try:
        requests.post(f"{BASE}/sendMessage", json={"chat_id": ALERT_USER_ID, "text": text}, timeout=10)
    except:
        pass

if __name__ == "__main__":
    print("🤖 Dorayaid Bot starting...")
    send_alert("✅ Dorayaid Bot เริ่มทำงานแล้วค่ะ")
    error_count = 0
    while True:
        try:
            poll()
            error_count = 0
        except KeyboardInterrupt:
            send_alert("⚠️ Dorayaid Bot หยุดทำงาน (manual stop)")
            break
        except SystemExit:
            send_alert("⚠️ Dorayaid Bot หยุดทำงาน (system exit)")
            break
        except Exception as e:
            error_count += 1
            print(f"[error] {e}")
            if error_count >= 3:
                send_alert(f"❌ Dorayaid Bot มีปัญหาต่อเนื่อง ({error_count} ครั้ง)\n{str(e)[:200]}")
                error_count = 0
            try:
                time.sleep(10)
            except:
                break
