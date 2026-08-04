import os
import requests
import json
import secrets
import sqlite3
from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

# ============================================================
# CONFIGURATION
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8679853739:AAEcdk9DWC51lVO1EXvmamgyWSpkp2Vfdk0")
ADMIN_ID = os.getenv("ADMIN_ID", "5738022147")
REFERRAL_BONUS_RATE = 0.05  # 5%
TOTAL_PROFIT_RATE = 0.20   # 20% Total Return
INVESTMENT_DAYS = 7
TOTAL_HOURS = INVESTMENT_DAYS * 24  # 168 Hours

# Fixed allowed investment plans
ALLOWED_PLANS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

# ============================================================
# SQLITE DATABASE
# ============================================================
def get_db():
    db = sqlite3.connect('usdtpilot.db', timeout=10)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE NOT NULL,
            username TEXT,
            balance REAL DEFAULT 0,
            active_deposit REAL DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            type TEXT,
            amount REAL,
            status TEXT DEFAULT 'PENDING',
            description TEXT,
            txid TEXT,
            network TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            amount REAL,
            total_profit REAL,
            hourly_profit REAL,
            profit_accumulated REAL DEFAULT 0,
            hours_passed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ACTIVE',
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            maturity_date TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id TEXT,
            referred_id TEXT,
            bonus REAL,
            status TEXT DEFAULT 'COMPLETED',
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            subject TEXT,
            message TEXT,
            status TEXT DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            title TEXT,
            message TEXT,
            is_read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    db.commit()
    db.close()

init_db()

# ============================================================
# AUTOMATIC HOURLY PROFIT SCHEDULER
# ============================================================
def process_hourly_profits():
    """Runs every hour: Distributes profit to user balance automatically"""
    db = get_db()
    active_invs = db.execute("SELECT * FROM investments WHERE status = 'ACTIVE'").fetchall()
    
    for inv in active_invs:
        inv_id = inv['id']
        user_id = inv['user_id']
        hourly_profit = inv['hourly_profit']
        hours_passed = inv['hours_passed'] + 1
        
        # Add hourly profit directly to main balance
        db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (hourly_profit, user_id))
        
        # Update investment record
        if hours_passed >= TOTAL_HOURS:
            # Plan Completed (Release capital back + finish plan)
            db.execute('''
                UPDATE investments 
                SET hours_passed = ?, profit_accumulated = profit_accumulated + ?, status = 'COMPLETED'
                WHERE id = ?
            ''', (hours_passed, hourly_profit, inv_id))
            
            db.execute("UPDATE users SET active_deposit = active_deposit - ? WHERE telegram_id = ?", (inv['amount'], user_id))
            
            create_notification(user_id, "🎉 Investment Completed", f"Your investment of ${inv['amount']} USDT has fully matured after 7 days!")
        else:
            db.execute('''
                UPDATE investments 
                SET hours_passed = ?, profit_accumulated = profit_accumulated + ?
                WHERE id = ?
            ''', (hours_passed, hourly_profit, inv_id))

    db.commit()
    db.close()

scheduler = BackgroundScheduler()
scheduler.add_job(func=process_hourly_profits, trigger="interval", hours=1)
scheduler.start()

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def send_telegram(chat_id, text, keyboard=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass

def get_user(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE telegram_id = ?', (str(user_id),)).fetchone()
    db.close()
    if not user:
        ref_code = secrets.token_hex(4).upper()
        db = get_db()
        db.execute('INSERT INTO users (telegram_id, username, referral_code, created_at, last_login) VALUES (?, ?, ?, ?, ?)',
                   (str(user_id), 'User', ref_code, datetime.now(), datetime.now()))
        db.commit()
        db.close()
        user = get_user(user_id)
    return dict(user) if user else None

def create_notification(user_id, title, message):
    db = get_db()
    db.execute('INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)', (str(user_id), title, message))
    db.commit()
    db.close()

# ============================================================
# API ENDPOINTS
# ============================================================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/auth/verify', methods=['POST'])
def verify_user():
    data = request.json
    user_id = str(data.get('user_id'))
    username = data.get('username', 'User')
    
    user = get_user(user_id)
    db = get_db()
    db.execute('UPDATE users SET username = ?, last_login = ? WHERE telegram_id = ?', (username, datetime.now(), user_id))
    db.commit()
    db.close()
    
    return jsonify({"status": "success", "user": user})

@app.route('/api/user/<user_id>', methods=['GET'])
def get_user_data(user_id):
    user = get_user(user_id)
    db = get_db()
    
    transactions = db.execute('SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC LIMIT 20', (str(user_id),)).fetchall()
    investments = db.execute('SELECT * FROM investments WHERE user_id = ? AND status = \'ACTIVE\'', (str(user_id),)).fetchall()
    notifications = db.execute('SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC', (str(user_id),)).fetchall()
    
    db.close()
    
    return jsonify({
        "user": user,
        "macaamilo": [dict(t) for t in transactions],
        "maalgashi": [dict(i) for i in investments],
        "ogeysiis": [dict(n) for n in notifications]
    })

@app.route('/api/deposit/request', methods=['POST'])
def request_deposit():
    data = request.json
    user_id = str(data.get('user_id'))
    username = data.get('username', 'User')
    network = data.get('network', 'TRC20')
    txid = data.get('txid')
    amount = float(data.get('amount', 0))
    
    if amount < 10:
        return jsonify({"status": "error", "message": "Minimum deposit is $10 USDT"})
    if not txid:
        return jsonify({"status": "error", "message": "TXID is required"})
        
    db = get_db()
    db.execute('INSERT INTO transactions (user_id, type, amount, status, txid, network, description) VALUES (?, ?, ?, ?, ?, ?, ?)',
               (user_id, 'DEPOSIT', amount, 'PENDING', txid, network, f'Deposit via {network}'))
    db.commit()
    db.close()
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ Approve", "callback_data": f"approve_deposit_{user_id}_{amount}"},
             {"text": "❌ Reject", "callback_data": f"reject_deposit_{user_id}"}]
        ]
    }
    admin_msg = f"📥 <b>NEW DEPOSIT</b>\n\nUser: {username}\nID: <code>{user_id}</code>\nAmount: ${amount} USDT\nNetwork: {network}\nTXID: <code>{txid}</code>"
    send_telegram(ADMIN_ID, admin_msg, keyboard)
    
    return jsonify({"status": "success", "message": "Deposit request sent to Admin!"})

@app.route('/api/invest', methods=['POST'])
def invest():
    data = request.json
    user_id = str(data.get('user_id'))
    amount = int(data.get('amount', 0))
    
    # Strict Plan Check
    if amount not in ALLOWED_PLANS:
        return jsonify({"status": "error", "message": "Invalid Investment Plan! Choose between $10 and $100."})
    
    user = get_user(user_id)
    if not user or user['balance'] < amount:
        return jsonify({"status": "error", "message": "Insufficient balance! Please deposit first."})
    
    total_profit = amount * TOTAL_PROFIT_RATE
    hourly_profit = total_profit / TOTAL_HOURS
    maturity_date = datetime.now() + timedelta(days=INVESTMENT_DAYS)
    
    db = get_db()
    # Deduct plan amount from balance
    db.execute('UPDATE users SET balance = balance - ?, active_deposit = active_deposit + ? WHERE telegram_id = ?', (amount, amount, user_id))
    
    # Register Investment Plan
    db.execute('''
        INSERT INTO investments (user_id, amount, total_profit, hourly_profit, maturity_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, amount, total_profit, hourly_profit, maturity_date))
    
    # Record Transaction
    db.execute('INSERT INTO transactions (user_id, type, amount, status, description) VALUES (?, ?, ?, ?, ?)',
               (user_id, 'INVESTMENT', -amount, 'COMPLETED', f'Invested ${amount} USDT'))
    
    db.commit()
    db.close()
    
    create_notification(user_id, "🚀 Investment Started", f"Successfully invested ${amount} USDT. Profit will be added every hour for 7 days!")
    return jsonify({"status": "success", "message": f"Successfully invested ${amount} USDT!"})

@app.route('/api/withdraw/request', methods=['POST'])
def request_withdrawal():
    data = request.json
    user_id = str(data.get('user_id'))
    address = data.get('address')
    amount = float(data.get('amount', 0))
    network = data.get('network', 'TRC20')
    
    if amount < 10:
        return jsonify({"status": "error", "message": "Minimum withdrawal is $10 USDT"})
    
    db = get_db()
    # Check 7 days lock requirement
    active_inv = db.execute("SELECT * FROM investments WHERE user_id = ? AND status = 'ACTIVE'", (user_id,)).fetchone()
    
    if active_inv:
        start_time = datetime.strptime(active_inv['start_date'], '%Y-%m-%d %H:%M:%S')
        if datetime.now() < start_time + timedelta(days=INVESTMENT_DAYS):
            db.close()
            return jsonify({"status": "error", "message": "Withdrawal locked! You must wait 7 days for active investments to finish."})

    user = get_user(user_id)
    if not user or user['balance'] < amount:
        db.close()
        return jsonify({"status": "error", "message": "Insufficient balance!"})
    
    db.execute('UPDATE users SET balance = balance - ? WHERE telegram_id = ?', (amount, user_id))
    db.execute('INSERT INTO transactions (user_id, type, amount, status, description, network) VALUES (?, ?, ?, ?, ?, ?)',
               (user_id, 'WITHDRAWAL', -amount, 'PENDING', f'Withdrawal to {network}', network))
    db.commit()
    db.close()
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ Approve", "callback_data": f"approve_withdraw_{user_id}_{amount}"},
             {"text": "❌ Reject", "callback_data": f"reject_withdraw_{user_id}"}]
        ]
    }
    admin_msg = f"📤 <b>NEW WITHDRAWAL</b>\n\nUser ID: <code>{user_id}</code>\nAmount: ${amount} USDT\nNetwork: {network}\nAddress: <code>{address}</code>"
    send_telegram(ADMIN_ID, admin_msg, keyboard)
    
    return jsonify({"status": "success", "message": "Withdrawal request submitted to Admin!"})

# ============================================================
# TELEGRAM WEBHOOK (ADMIN APPROVALS)
# ============================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    if "callback_query" in update:
        query = update["callback_query"]
        data = query["data"]
        chat_id = query["message"]["chat"]["id"]
        message_id = query["message"]["message_id"]
        
        if data.startswith("approve_deposit_"):
            parts = data.split("_")
            user_id, amount = parts[2], float(parts[3])
            
            db = get_db()
            db.execute("UPDATE transactions SET status = 'COMPLETED' WHERE user_id = ? AND type = 'DEPOSIT' AND status = 'PENDING'", (user_id,))
            db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, user_id))
            db.commit()
            db.close()
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id, "message_id": message_id,
                "text": f"✅ <b>DEPOSIT APPROVED</b>\nUser: <code>{user_id}</code>\nAmount: +${amount} USDT", "parse_mode": "HTML"
            })
            send_telegram(user_id, f"🎉 Your deposit of <b>${amount} USDT</b> was approved!")
            
        elif data.startswith("approve_withdraw_"):
            parts = data.split("_")
            user_id, amount = parts[2], float(parts[3])
            
            db = get_db()
            db.execute("UPDATE transactions SET status = 'COMPLETED' WHERE user_id = ? AND type = 'WITHDRAWAL' AND status = 'PENDING'", (user_id,))
            db.commit()
            db.close()
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id, "message_id": message_id,
                "text": f"✅ <b>WITHDRAWAL APPROVED</b>\nUser: <code>{user_id}</code>\nAmount: -${amount} USDT", "parse_mode": "HTML"
            })
            send_telegram(user_id, f"✅ Your withdrawal of <b>${amount} USDT</b> was sent!")

    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
