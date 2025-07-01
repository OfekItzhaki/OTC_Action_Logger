import os
import time
import psutil
import json
import sqlite3
from ib_insync import *
from datetime import datetime, timezone
import threading
from dotenv import load_dotenv
import telegram
import asyncio

# === Load ENV Variables ===
load_dotenv()
TWS_PROCESS_NAME = os.getenv('TWS_PROCESS_NAME', 'tws.exe')
IBKR_HOST = os.getenv('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.getenv('IBKR_PORT', 7497))
IBKR_CLIENT_ID = int(os.getenv('IBKR_CLIENT_ID', 123))
DB_FILE = os.getenv('DB_FILE', 'ibkr_activity_log.db')
JSON_LOG_FILE = os.getenv('JSON_LOG_FILE', 'ibkr_activity_log.json')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# === Init Telegram ===
bot = telegram.Bot(token=TELEGRAM_TOKEN)

# === SQLite Setup ===
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS activity (
                     timestamp TEXT,
                     event_type TEXT,
                     description TEXT,
                     raw_data TEXT
                     )''')
        conn.commit()

# === Async Telegram Notification ===
async def send_telegram_message(message):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except Exception as e:
        print(f"[WARNING] Failed to send Telegram message: {e}")

# === Logging Functions ===
def log_event(event_type, description, raw_data):
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = {
        'timestamp': timestamp,
        'event_type': event_type,
        'description': description,
        'raw_data': raw_data
    }

    # SQLite
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO activity VALUES (?, ?, ?, ?)",
                  (timestamp, event_type, description, json.dumps(raw_data)))
        conn.commit()

    # JSON
    logs = []
    if os.path.exists(JSON_LOG_FILE):
        try:
            with open(JSON_LOG_FILE, 'r') as f:
                logs = json.load(f)
        except json.JSONDecodeError:
            logs = []
    logs.append(entry)
    with open(JSON_LOG_FILE, 'w') as f:
        json.dump(logs, f, indent=2)

    # Telegram (optional, customize verbosity)
    asyncio.run(send_telegram_message(f"[{event_type}] {description}"))

# === TWS Detection ===
def is_tws_running():
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and TWS_PROCESS_NAME.lower() in proc.info['name'].lower():
            return True
    return False

# === IBKR Event Handlers ===
def setup_ibkr_event_listeners(ib):
    def handle_order_status(order):
        log_event("OrderStatus", f"Order status: {order.status}", order.__dict__)

    def handle_execution(trade, fill):
        log_event("Execution", f"Trade executed: {fill.execution.side} {fill.execution.shares} @ {fill.execution.price}", fill.__dict__)

    def handle_open_order(order, contract, order_state):
        log_event("OpenOrder", f"New order detected: {order.action} {order.totalQuantity}", order.__dict__)

    ib.orderStatusEvent += handle_order_status
    ib.execDetailsEvent += handle_execution
    ib.openOrderEvent += handle_open_order

# === Main Process ===
def monitor_ibkr():
    init_db()
    print("[INFO] Waiting for IBKR TWS to start...")

    while True:
        if is_tws_running():
            print("[INFO] TWS detected. Connecting...")
            ib = IB()
            try:
                ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID)
                setup_ibkr_event_listeners(ib)
                print("[INFO] Connected and monitoring started.")
                ib.run()
            except Exception as e:
                log_event("Error", f"Failed to connect or monitor: {e}", {})
                time.sleep(10)
        else:
            time.sleep(5)

# === Start ===
if __name__ == '__main__':
    threading.Thread(target=monitor_ibkr, daemon=True).start()
    while True:
        time.sleep(60)  # Keep main thread alive
