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
BOT_TOKEN = os.getenv("BOT_TOKEN", "8641054545:AAE-ETeHuB3ki-pGG0FwysQOi73gSOtz_eE")
ADMIN_ID = os.getenv("ADMIN_ID", "5738022147")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://my-miniapp-4uo7.onrender.com/")

TOTAL_PROFIT_RATE = 0.20   # 20% Total Return
INVESTMENT_DAYS = 7
TOTAL_HOURS = INVESTMENT_DAYS * 24  # 168 Hours

# Added VIP Plan amounts here (Standard + VIP plans)
ALLOWED_PLANS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 150, 200, 250, 300, 350, 400, 450, 500]

# Memory storage for tracking admin replies
admin_waiting_reply = {}

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

        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            username TEXT,
            subject TEXT,
            message TEXT,
            status TEXT DEFAULT 'PENDING',
            admin_reply TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        response = requests.post(url, json=payload, timeout=5)
        return response.json()
    except:
        return None

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
    investments = db.execute("SELECT * FROM investments WHERE user_id = ? AND status = 'ACTIVE'", (str(user_id),)).fetchall()
    
    db.close()
    
    return jsonify({
        "user": user,
        "macaamilo": [dict(t) for t in transactions],
        "maalgashi": [dict(i) for i in investments]
    })

@app.route('/api/public/activities', methods=['GET'])
def public_activities():
    db = get_db()
    txs = db.execute('''
        SELECT t.user_id, t.type, t.amount, t.network, t.date, u.username 
        FROM transactions t 
        JOIN users u ON t.user_id = u.telegram_id 
        WHERE t.status = 'COMPLETED' 
        ORDER BY t.date DESC LIMIT 10
    ''').fetchall()
    db.close()
    return jsonify({"status": "success", "activities": [dict(tx) for tx in txs]})

@app.route('/api/deposit/request', methods=['POST'])
def request_deposit():
    user_id = request.form.get('user_id')
    username = request.form.get('username', 'User')
    network = request.form.get('network', 'TRC20')
    txid = request.form.get('txid', '')
    amount = float(request.form.get('amount', 0))
    screenshot = request.files.get('screenshot')
    
    if amount < 10:
        return jsonify({"status": "error", "message": "⚠️ Minimum deposit is $10 USDT"})
    if not txid and not screenshot:
        return jsonify({"status": "error", "message": "⚠️ Please enter TXID or upload a screenshot!"})
        
    db = get_db()
    pending_dep = db.execute("SELECT * FROM transactions WHERE user_id = ? AND type = 'DEPOSIT' AND status = 'PENDING'", (str(user_id),)).fetchone()
    if pending_dep:
        db.close()
        return jsonify({"status": "error", "message": "⚠️ Please wait for your pending deposit request to be processed before submitting a new one."})

    cursor = db.cursor()
    cursor.execute('INSERT INTO transactions (user_id, type, amount, status, txid, network, description) VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (user_id, 'DEPOSIT', amount, 'PENDING', txid if txid else 'SCREENSHOT_UPLOADED', network, f'Deposit via {network}'))
    tx_id = cursor.lastrowid
    db.commit()
    db.close()
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ Approve", "callback_data": f"approve_dep_{tx_id}"},
             {"text": "❌ Reject", "callback_data": f"reject_dep_{tx_id}"}]
        ]
    }
    
    txid_display = txid if txid else 'N/A (See Screenshot)'
    admin_msg = f"📥 <b>NEW DEPOSIT REQUEST</b>\n\nUser: {username}\nID: <code>{user_id}</code>\nAmount: <b>${amount} USDT</b>\nNetwork: {network}\nTXID: <code>{txid_display}</code>"
    
    if screenshot:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        files = {'photo': (screenshot.filename, screenshot.read(), screenshot.content_type)}
        payload = {
            "chat_id": ADMIN_ID,
            "caption": admin_msg,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(keyboard)
        }
        try:
            requests.post(url, data=payload, files=files, timeout=10)
        except:
            send_telegram(ADMIN_ID, admin_msg, keyboard)
    else:
        send_telegram(ADMIN_ID, admin_msg, keyboard)
    
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
    
    pending_with = db.execute("SELECT * FROM transactions WHERE user_id = ? AND type = 'WITHDRAWAL' AND status = 'PENDING'", (user_id,)).fetchone()
    if pending_with:
        db.close()
        return jsonify({"status": "error", "message": "⚠️ Please wait for your pending withdrawal request to be processed before submitting a new one."})

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
    cursor = db.cursor()
    cursor.execute('INSERT INTO transactions (user_id, type, amount, status, txid, network, description) VALUES (?, ?, ?, ?, ?, ?, ?)',
               (user_id, 'WITHDRAWAL', -amount, 'PENDING', 'N/A', 'TRC20', f'Withdrawal to {address}'))
    tx_id = cursor.lastrowid
    db.commit()
    db.close()
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ Approve", "callback_data": f"approve_with_{tx_id}"},
             {"text": "❌ Reject", "callback_data": f"reject_with_{tx_id}"}]
        ]
    }
    admin_msg = f"📤 <b>NEW WITHDRAWAL REQUEST</b>\n\nUser ID: <code>{user_id}</code>\nAmount: <b>${amount} USDT</b>\nAddress: <code>{address}</code>"
    send_telegram(ADMIN_ID, admin_msg, keyboard)
    
    return jsonify({"status": "success", "message": "✅ Withdrawal request submitted successfully!"})

# ============================================================
# SUPPORT TICKET ENDPOINTS & INLINE REPLY SYSTEM
# ============================================================
@app.route('/api/support/send', methods=['POST'])
def send_support():
    data = request.json or request.form
    user_id = str(data.get('user_id', 'Unknown'))
    username = data.get('username', 'User')
    
    subject = data.get('subject') or data.get('subject_field') or 'General Inquiry'
    message = data.get('message') or data.get('message_detail') or data.get('text') or ''
    
    if not message.strip():
        return jsonify({"status": "error", "message": "⚠️ Please enter your message!"})
        
    db = get_db()
    
    pending_ticket = db.execute("SELECT * FROM support_tickets WHERE user_id = ? AND status = 'PENDING'", (user_id,)).fetchone()
    if pending_ticket:
        db.close()
        return jsonify({"status": "error", "message": "⚠️ You already have a pending support ticket. Please wait for a reply before submitting a new one."})

    db.execute('INSERT INTO support_tickets (user_id, username, subject, message, status) VALUES (?, ?, ?, ?, ?)', 
               (user_id, username, subject, message, 'PENDING'))
    db.commit()
    db.close()
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "💬 Reply to Ticket", "callback_data": f"reply_ticket_{user_id}"}]
        ]
    }
    
    admin_msg = f"🛠️ <b>NEW SUPPORT TICKET</b>\n\nUser: {username}\nID: <code>{user_id}</code>\nSubject: <b>{subject}</b>\nStatus: PENDING\n\nMessage:\n<i>{message}</i>"
    send_telegram(ADMIN_ID, admin_msg, keyboard)
    
    return jsonify({"status": "success", "message": "✅ Support message sent successfully! Admin will contact you soon."})

@app.route('/api/support/tickets/<user_id>', methods=['GET'])
def get_user_tickets(user_id):
    db = get_db()
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    cursor.execute('SELECT id, subject, message, status, admin_reply, date FROM support_tickets WHERE user_id = ? ORDER BY id DESC', (str(user_id),))
    rows = cursor.fetchall()
    tickets = [dict(row) for row in rows]
    db.close()
    
    return jsonify({"status": "success", "tickets": tickets})

# ============================================================
# ADMIN & TRACKING ENDPOINTS
# ============================================================
@app.route('/api/admin/users', methods=['GET'])
def admin_get_users():
    db = get_db()
    users = db.execute('SELECT telegram_id, username, balance, active_deposit, referral_code, created_at, last_login FROM users ORDER BY created_at DESC').fetchall()
    db.close()
    return jsonify({"status": "success", "users": [dict(u) for u in users]})

@app.route('/api/admin/ranking', methods=['GET'])
def admin_investment_ranking():
    db = get_db()
    ranking = db.execute('''
        SELECT u.telegram_id, u.username, SUM(i.amount) as total_invested, COUNT(i.id) as total_plans
        FROM investments i 
        JOIN users u ON i.user_id = u.telegram_id 
        GROUP BY i.user_id 
        ORDER BY total_invested DESC
    ''').fetchall()
    db.close()
    return jsonify({"status": "success", "ranking": [dict(r) for r in ranking]})

# ============================================================
# TELEGRAM WEBHOOK
# ============================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    global admin_waiting_reply
    update = request.json
    
    if update and "message" in update:
        msg = update["message"]
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "")
        
        # Handle Admin replies
        if chat_id == str(ADMIN_ID) and chat_id in admin_waiting_reply:
            user_id = admin_waiting_reply[chat_id]
            reply_text = text
            
            del admin_waiting_reply[chat_id]
            
            db = get_db()
            ticket = db.execute("SELECT * FROM support_tickets WHERE user_id = ? AND status = 'PENDING' ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
            
            if ticket:
                ticket_id = ticket['id']
                db.execute("UPDATE support_tickets SET status = 'COMPLETED', admin_reply = ? WHERE id = ?", (reply_text, ticket_id))
                db.commit()
            db.close()
            
            send_telegram(user_id, f"✅ <b>Support Ticket Resolved!</b>\n\n📩 <b>Admin Reply:</b>\n{reply_text}")
            send_telegram(ADMIN_ID, f"✅ Reply successfully sent to user ID <code>{user_id}</code>, ticket status updated to <b>COMPLETED</b>.")
            
            return jsonify({"status": "ok"})
            
        # Handle /start command for users to open the WebApp
        if text.startswith("/start"):
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🚀 Open App", "web_app": {"url": WEBAPP_URL}}]
                ]
            }
            send_telegram(chat_id, "🚀 <b>CoreX Investment Platform</b>\n\nSecure, transparent, and automated USDT growth. Click the button below to launch the app:", keyboard)
            return jsonify({"status": "ok"})

    if update and "callback_query" in update:
        query = update["callback_query"]
        query_id = query["id"]
        data = query["data"]
        chat_id = str(query["message"]["chat"]["id"])
        message_id = query["message"]["message_id"]
        
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": query_id})
        
        has_photo = "photo" in query["message"]
        edit_method = "editMessageCaption" if has_photo else "editMessageText"
        content_key = "caption" if has_photo else "text"

        if data.startswith("reply_ticket_"):
            user_id = data.split("_")[2]
            admin_waiting_reply[chat_id] = user_id
            
            send_telegram(chat_id, f"✍️ Please type your reply message to this user (ID: <code>{user_id}</code>):")
            return jsonify({"status": "ok"})

        if data.startswith("approve_dep_"):
            tx_id = data.split("_")[2]
            db = get_db()
            tx = db.execute("SELECT * FROM transactions WHERE id = ? AND status = 'PENDING'", (tx_id,)).fetchone()
            
            if tx:
                user_id = tx['user_id']
                amount = tx['amount']
                
                db.execute("UPDATE transactions SET status = 'COMPLETED' WHERE id = ?", (tx_id,))
                db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, user_id))
                db.commit()
                
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{edit_method}", json={
                    "chat_id": chat_id, "message_id": message_id,
                    content_key: f"✅ <b>DEPOSIT APPROVED & CONFIRMED</b>\nUser: <code>{user_id}</code>\nAmount: +${amount} USDT\nStatus: Balance Updated!",
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []}
                })
                
                send_telegram(user_id, f"🎉 <b>Deposit Approved!</b>\n\nYour deposit of <b>${amount} USDT</b> has been credited to your balance successfully.")
            db.close()
            
        elif data.startswith("reject_dep_"):
            tx_id = data.split("_")[2]
            db = get_db()
            tx = db.execute("SELECT * FROM transactions WHERE id = ? AND status = 'PENDING'", (tx_id,)).fetchone()
            
            if tx:
                user_id = tx['user_id']
                amount = tx['amount']
                
                db.execute("UPDATE transactions SET status = 'REJECTED' WHERE id = ?", (tx_id,))
                db.commit()
                
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{edit_method}", json={
                    "chat_id": chat_id, "message_id": message_id,
                    content_key: f"❌ <b>DEPOSIT REJECTED</b>\nUser: <code>{user_id}</code>\nAmount: ${amount} USDT",
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []}
                })
                
                send_telegram(user_id, f"❌ <b>Deposit Rejected</b>\n\nUnfortunately, your deposit request of <b>${amount} USDT</b> was rejected.\nPlease check your TXID or screenshot, or contact Support if you have any issues.")
            db.close()

        elif data.startswith("approve_with_"):
            tx_id = data.split("_")[2]
            db = get_db()
            tx = db.execute("SELECT * FROM transactions WHERE id = ? AND status = 'PENDING'", (tx_id,)).fetchone()
            
            if tx:
                user_id = tx['user_id']
                amount = abs(float(tx['amount']))
                
                db.execute("UPDATE transactions SET status = 'COMPLETED' WHERE id = ?", (tx_id,))
                db.commit()
                
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{edit_method}", json={
                    "chat_id": chat_id, "message_id": message_id,
                    content_key: f"✅ <b>WITHDRAWAL APPROVED & CONFIRMED</b>\nUser: <code>{user_id}</code>\nAmount: ${amount} USDT",
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []}
                })
                send_telegram(user_id, f"🎉 <b>Withdrawal Approved!</b>\n\nYour withdrawal of <b>${amount} USDT</b> has been successfully processed.")
            db.close()

        elif data.startswith("reject_with_"):
            tx_id = data.split("_")[2]
            db = get_db()
            tx = db.execute("SELECT * FROM transactions WHERE id = ? AND status = 'PENDING'", (tx_id,)).fetchone()
            
            if tx:
                user_id = tx['user_id']
                amount = abs(float(tx['amount']))
                
                db.execute("UPDATE transactions SET status = 'REJECTED' WHERE id = ?", (tx_id,))
                db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, user_id))
                db.commit()
                
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{edit_method}", json={
                    "chat_id": chat_id, "message_id": message_id,
                    content_key: f"❌ <b>WITHDRAWAL REJECTED & REFUNDED</b>\nUser: <code>{user_id}</code>\nAmount: ${amount} USDT",
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []}
                })
                send_telegram(user_id, f"⚠️ <b>Withdrawal Rejected</b>\n\nYour withdrawal request of ${amount} USDT was rejected. The amount has been refunded to your balance.")
            db.close()

    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
