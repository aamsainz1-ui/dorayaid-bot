# Dorayaid Bot (@Dorayaist_bot)

Bot อ่านสลิปโอนเงินอัตโนมัติผ่าน Telegram

## ติดตั้ง

### System packages
```bash
apt install -y tesseract-ocr tesseract-ocr-tha
```

### Python packages
```bash
pip install requests pillow opencv-python-headless numpy pytesseract openpyxl
```

### API Keys
- **Gemini 2.5 Flash** — ตั้งค่า `GEMINI_API_KEY` ในไฟล์ bot หรือ env
- **Telegram Bot Token** — ตั้งค่า `BOT_TOKEN` ในไฟล์ bot

### รัน
```bash
pm2 start dorayaid_bot.py --name dorayaid-bot --interpreter python3
```

### Cron สรุปรายวัน (00:10 BKK)
```bash
crontab -e
# เพิ่ม:
10 17 * * * python3 /path/to/dorayaid_summary_cron.py >> /tmp/dorayaid_summary.log 2>&1
```

## ไฟล์ทั้งหมด
| ไฟล์ | หน้าที่ |
|---|---|
| `dorayaid_bot.py` | ตัว bot หลัก |
| `dorayaid_summary_cron.py` | cron สรุปรายวัน |
| `dorayaid_transfers.json` | DB รายการโอน (auto-created) |
| `dorayaid_offset.txt` | Telegram offset (auto-created) |
| `dorayaid_processed.json` | message_id ที่ประมวลผลแล้ว (auto-created) |
| `dorayaid_stats.json` | สถิติรายวัน (auto-created) |
| `dorayaid_excel/` | ไฟล์ Excel สรุปรายเดือน (auto-created) |

## Commands
| Command | หน้าที่ |
|---|---|
| `/summary` | สรุปยอดวันนี้ |
| `/excel` | ส่ง Excel สรุป |
| `/status` | สถานะบอท |
| `/help` | คำสั่งทั้งหมด |
| `/reset` | ล้างข้อมูล เริ่มนับใหม่ |

## OCR Flow
1. รับรูปจากกลุ่ม Telegram
2. **Gemini 2.5 Flash** อ่านสลิป (primary — เร็ว 1-2 วิ)
3. **tesseract** เป็น fallback ถ้า Gemini พลาด
4. Dedup ด้วย **เลขอ้างอิง (ref_code)** — ถ้าไม่มี fallback เป็น ยอด+ผู้รับ+เวลา
5. บันทึกลง JSON + react ✅/ℹ️
6. แสดงยอดรวมวันนี้ แยกตามคนส่งรูป

## ฟอร์มสรุป
```
📊 สรุปยอดวันนี้ (DD/MM/YYYY)
💰 ยอดรวม: X บาท (N รายการ)
━━━━━━━━━━━━━━━
📸 สลิปทั้งหมด: X รูป
✅ บันทึกได้: X รายการ
🔄 สลิปซ้ำ: X รูป
⚠️ มีปัญหา: X รูป
━━━━━━━━━━━━━━━
👤 ชื่อ — N รายการ | X บาท
```

## Dependencies
| Package | ใช้ทำอะไร |
|---|---|
| `requests` | Telegram API + Gemini API |
| `pillow` | อ่าน/แปลงรูป |
| `opencv-python-headless` | preprocessing รูปก่อน OCR |
| `numpy` | ใช้กับ OpenCV |
| `pytesseract` | OCR fallback |
| `openpyxl` | สร้าง Excel |
| `tesseract-ocr` | OCR engine (system) |
| `tesseract-ocr-tha` | ภาษาไทย (system) |
