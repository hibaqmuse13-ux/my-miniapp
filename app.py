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
TOTAL_PROFIT_RATE = 0.20   # 20% Total Return
INVESTMENT_DAYS = 7
TOTAL_HOURS = INVESTMENT_DAYS * 24  # 168 Hours

ALLOWED_PLANS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 150, 200, 350, 400, 450, 500]

# ============================================================
# SQLITE DATABASE INITIALIZATION
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
    db = get_db()
    active_invs = db.execute("SELECT * FROM investments WHERE status = 'ACTIVE'").fetchall()
    
    for inv in active_invs:
        inv_id = inv['id']
        user_id = inv['user_id']
        hourly_profit = inv['hourly_profit']
        hours_passed = inv['hours_passed'] + 1
        
        db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (hourly_profit, user_id))
        
        if hours_passed >= TOTAL_HOURS:
            db.execute('''
                UPDATE investments 
                SET hours_passed = ?, profit_accumulated = profit_accumulated + ?, status = 'COMPLETED'
                WHERE id = ?
            ''', (hours_passed, hourly_profit, inv_id))
            
            db.execute("UPDATE users SET active_deposit = active_deposit - ? WHERE telegram_id = ?", (inv['amount'], user_id))
            create_notification(user_id, "🎉 Plan Completed", f"Your investment of ${inv['amount']} USDT has fully matured!")
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
    if not user:
        ref_code = secrets.token_hex(4).upper()
        db.execute('INSERT INTO users (telegram_id, username, referral_code, created_at, last_login) VALUES (?, ?, ?, ?, ?)',
                   (str(user_id), 'User', ref_code, datetime.now(), datetime.now()))
        db.commit()
        user = db.execute('SELECT * FROM users WHERE telegram_id = ?', (str(user_id),)).fetchone()
    db.close()
    return dict(user) if user else None

def create_notification(user_id, title, message):
    db = get_db()
    db.execute('INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)', (str(user_id), title, message))
    db.commit()
    db.close()

# ============================================================
# WEB & API ROUTES
# ============================================================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/auth/verify', methods=['POST'])
def verify_user():
    data = request.json
    user_id = str(data.get('user_id'))
    username = data.get('username', 'User')
    
    get_user(user_id)
    db = get_db()
    db.execute('UPDATE users SET username = ?, last_login = ? WHERE telegram_id = ?', (username, datetime.now(), user_id))
    db.commit()
    db.close()
    
    return jsonify({"status": "success", "user": get_user(user_id)})

@app.route('/api/user/<user_id>', methods=['GET'])
def get_user_data(user_id):
    user = get_user(user_id)
    db = get_db()
    
    transactions = db.execute('SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC LIMIT 20', (str(user_id),)).fetchall()
    investments = db.execute('SELECT * FROM investments WHERE user_id = ? AND status = \'ACTIVE\'', (str(user_id),)).fetchall()
    
    db.close()
    
    return jsonify({
        "user": user,
        "macaamilo": [dict(t) for t in transactions],
        "maalgashi": [dict(i) for i in investments]
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
        return jsonify({"status": "error", "message": "⚠️ Minimum deposit is $10 USDT"})
    if not txid:
        return jsonify({"status": "error", "message": "⚠️ Please enter a valid TXID / Hash!"})
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute('INSERT INTO transactions (user_id, type, amount, status, txid, network, description) VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (user_id, 'DEPOSIT', amount, 'PENDING', txid, network, f'Deposit via {network}'))
    db.commit()
    db.close()
    
    # Fariinta Admin-ka oo aan lahayn badhamada balse ku tusaysa amarka /approve
    admin_msg = f"📥 <b>NEW DEPOSIT REQUEST</b>\n\nUser: {username}\nID: <code>{user_id}</code>\nAmount: <b>${amount} USDT</b>\nNetwork: {network}\nTXID: <code>{txid}</code>\n\n💡 <i>Si aad u ansixisid, ku jawaab ama qor:</i>\n<code>/approve {user_id} {amount}</code>"
    send_telegram(ADMIN_ID, admin_msg)
    
    return jsonify({"status": "success", "message": "✅ Deposit request submitted successfully! Pending approval."})

@app.route('/api/invest', methods=['POST'])
def invest():
    data = request.json
    user_id = str(data.get('user_id'))
    amount = int(data.get('amount', 0))
    
    if amount not in ALLOWED_PLANS:
        return jsonify({"status": "error", "message": "⚠️ Invalid Investment Plan!"})
    
    user = get_user(user_id)
    if not user or user['balance'] < amount:
        return jsonify({"status": "error", "message": "⚠️ Insufficient balance! Please deposit first."})
    
    total_profit = amount * TOTAL_PROFIT_RATE
    hourly_profit = total_profit / TOTAL_HOURS
    maturity_date = datetime.now() + timedelta(days=INVESTMENT_DAYS)
    
    db = get_db()
    db.execute('UPDATE users SET balance = balance - ?, active_deposit = active_deposit + ? WHERE telegram_id = ?', (amount, amount, user_id))
    db.execute('''
        INSERT INTO investments (user_id, amount, total_profit, hourly_profit, maturity_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, amount, total_profit, hourly_profit, maturity_date))
    db.execute('INSERT INTO transactions (user_id, type, amount, status, description) VALUES (?, ?, ?, ?, ?)',
               (user_id, 'INVESTMENT', -amount, 'COMPLETED', f'Invested ${amount} USDT'))
    db.commit()
    db.close()
    
    create_notification(user_id, "🚀 Investment Started", f"Successfully invested ${amount} USDT!")
    return jsonify({"status": "success", "message": f"🎉 Successfully invested ${amount} USDT!"})

@app.route('/api/withdraw/request', methods=['POST'])
def request_withdrawal():
    data = request.json
    user_id = str(data.get('user_id'))
    address = data.get('address')
    amount = float(data.get('amount', 0))
    
    if amount < 10:
        return jsonify({"status": "error", "message": "⚠️ Minimum withdrawal is $10 USDT"})
    if not address:
        return jsonify({"status": "error", "message": "⚠️ Please provide a wallet address!"})
    
    db = get_db()
    active_inv = db.execute("SELECT * FROM investments WHERE user_id = ? AND status = 'ACTIVE'", (user_id,)).fetchone()
    
    if active_inv:
        start_time = datetime.strptime(active_inv['start_date'], '%Y-%m-%d %H:%M:%S')
        if datetime.now() < start_time + timedelta(days=INVESTMENT_DAYS):
            db.close()
            return jsonify({"status": "error", "message": "🔒 Withdrawal locked! Active investment must complete 7 days."})

    user = get_user(user_id)
    if not user or user['balance'] < amount:
        db.close()
        return jsonify({"status": "error", "message": "⚠️ Insufficient balance!"})
    
    db.execute('UPDATE users SET balance = balance - ? WHERE telegram_id = ?', (amount, user_id))
    db.execute('INSERT INTO transactions (user_id, type, amount, status, description) VALUES (?, ?, ?, ?, ?)',
               (user_id, 'WITHDRAWAL', -amount, 'PENDING', f'Withdrawal to {address}'))
    db.commit()
    db.close()
    
    admin_msg = f"📤 <b>NEW WITHDRAWAL REQUEST</b>\n\nUser ID: <code>{user_id}</code>\nAmount: ${amount} USDT\nAddress: <code>{address}</code>"
    send_telegram(ADMIN_ID, admin_msg)
    
    return jsonify({"status": "success", "message": "✅ Withdrawal request submitted successfully!"})

# ============================================================
# TELEGRAM WEBHOOK (TEXT COMMAND APPROVAL SYSTEM)
# ============================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    if update and "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
        
        # Kaliya ha aqoonsado haddii uu Admin-ku soo diro amarka /approve
        if text.startswith("/approve") and str(chat_id) == str(ADMIN_ID):
            parts = text.split()
            if len(parts) >= 3:
                target_user_id = parts[1]
                amount = float(parts[2])
                
                db = get_db()
                # 1. Ku dar lacagta balance-ka user-ka si toos ah
                db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, target_user_id))
                db.commit()
                db.close()
                
                # 2. Xaqiijin u dir Admin-ka
                send_telegram(ADMIN_ID, f"✅ Si guul leh ayaa loogu shubay <b>${amount} USDT</b> User-ka: <code>{target_user_id}</code>")
                
                # 3. Ogeaysii User-ka Telegram-kiisa
                send_telegram(target_user_id, f"🎉 <b>Deposit Approved!</b>\n\nYour deposit of <b>${amount} USDT</b> has been credited to your balance successfully.")

    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
