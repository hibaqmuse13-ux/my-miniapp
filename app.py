import os
import requests
import json
import secrets
import sqlite3
import threading
import telebot
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
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://yourdomain.com")  # Replace with your actual domain/GitHub Pages URL

INVESTMENT_DAYS = 14
TOTAL_HOURS = INVESTMENT_DAYS * 24  # 336 Hours (2 Weeks)

# Initialize TeleBot
bot = telebot.TeleBot(BOT_TOKEN)

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
            profit REAL DEFAULT 0,
            pending_referral_balance REAL DEFAULT 0,
            total_deposits REAL DEFAULT 0,
            total_withdrawals REAL DEFAULT 0,
            referral_count INTEGER DEFAULT 0,
            roi INTEGER DEFAULT 25,
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
        
        db.execute("UPDATE users SET balance = balance + ?, profit = profit + ? WHERE telegram_id = ?", (hourly_profit, hourly_profit, user_id))
        
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
# TELEGRAM BOT HANDLERS (/start & callbacks)
# ============================================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    
    get_user(user_id)
    db = get_db()
    db.execute('UPDATE users SET username = ? WHERE telegram_id = ?', (username, str(user_id)))
    db.commit()
    db.close()
    
    markup = telebot.types.InlineKeyboardMarkup()
    webapp_btn = telebot.types.InlineKeyboardButton(
        text="🚀 Open CoreXBot App", 
        web_app=telebot.types.WebAppInfo(url=WEBAPP_URL)
    )
    markup.add(webapp_btn)
    
    welcome_text = (
        f"👋 Welcome to <b>CoreXBot</b>, {username}!\n\n"
        "Secure USDT Investment & Earning Platform.\n"
        "Click the button below to open your dashboard and start earning hourly profits!"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_admin_callbacks(call):
    data = call.data
    db = get_db()
    
    if data.startswith("app_") or data.startswith("canc_"):
        parts = data.split("_")
        action = parts[0] # app or canc
        tx_id = parts[1]
        
        tx = db.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        if not tx:
            bot.answer_callback_query(call.id, "⚠️ Transaction not found!")
            db.close()
            return
            
        user_id = tx['user_id']
        amount = abs(tx['amount'])
        tx_type = tx['type']
        
        if action == "app":
            db.execute("UPDATE transactions SET status = 'COMPLETED' WHERE id = ?", (tx_id,))
            
            if tx_type == 'DEPOSIT':
                db.execute("UPDATE users SET balance = balance + ?, total_deposits = total_deposits + ? WHERE telegram_id = ?", (amount, amount, user_id))
                create_notification(user_id, "✅ Deposit Approved", f"Your deposit of ${amount} USDT has been successfully approved and credited!")
            elif tx_type == 'WITHDRAWAL':
                create_notification(user_id, "✅ Withdrawal Approved", f"Your withdrawal of ${amount} USDT has been successfully processed and sent!")
                
            db.commit()
            try:
                bot.edit_message_text(f"{call.message.text}\n\n✅ <b>STATUS: APPROVED</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
            except:
                pass
            bot.answer_callback_query(call.id, "Successfully Approved!")
            
        elif action == "canc":
            db.execute("UPDATE transactions SET status = 'CANCELLED' WHERE id = ?", (tx_id,))
            
            if tx_type == 'WITHDRAWAL':
                db.execute("UPDATE users SET balance = balance + ?, total_withdrawals = total_withdrawals - ? WHERE telegram_id = ?", (amount, amount, user_id))
                create_notification(user_id, "❌ Withdrawal Cancelled", f"Your withdrawal request of ${amount} USDT was cancelled. Funds returned to balance.")
            elif tx_type == 'DEPOSIT':
                create_notification(user_id, "❌ Deposit Cancelled", f"Your deposit request of ${amount} USDT was rejected or cancelled.")
                
            db.commit()
            try:
                bot.edit_message_text(f"{call.message.text}\n\n❌ <b>STATUS: CANCELLED</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
            except:
                pass
            bot.answer_callback_query(call.id, "Transaction Cancelled!")
            
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

@app.route('/api/invest', methods=['POST'])
def invest_plan():
    data = request.json
    user_id = str(data.get('user_id'))
    amount = float(data.get('amount', 0))
    
    user = get_user(user_id)
    if user['balance'] < amount:
        return jsonify({"status": "error", "message": "⚠️ Insufficient balance to deploy investment plan!"})
    
    daily_rate = 0.35 if amount >= 150 else 0.25
    total_profit = amount * daily_rate * INVESTMENT_DAYS
    hourly_profit = total_profit / TOTAL_HOURS
    
    maturity_date = datetime.now() + timedelta(days=INVESTMENT_DAYS)
    
    db = get_db()
    db.execute("UPDATE users SET balance = balance - ?, active_deposit = active_deposit + ? WHERE telegram_id = ?", 
               (amount, amount, user_id))
    
    db.execute('''
        INSERT INTO investments (user_id, amount, total_profit, hourly_profit, maturity_date, status)
        VALUES (?, ?, ?, ?, ?, 'ACTIVE')
    ''', (user_id, amount, total_profit, hourly_profit, maturity_date))
    
    db.execute('''
        INSERT INTO transactions (user_id, type, amount, status, description)
        VALUES (?, 'INVESTMENT', ?, 'COMPLETED', ?)
    ''', (user_id, -amount, f"Invested in ${amount} Plan"))
    
    db.commit()
    db.close()
    
    return jsonify({"status": "success", "message": f"Successfully invested ${amount} USDT!"})

@app.route('/api/deposit/request', methods=['POST'])
def deposit_request():
    user_id = str(request.form.get('user_id'))
    amount = float(request.form.get('amount', 0))
    network = request.form.get('network', 'TRC20')
    txid = request.form.get('txid', '')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        INSERT INTO transactions (user_id, type, amount, status, description, txid, network)
        VALUES (?, 'DEPOSIT', ?, 'PENDING', ?, ?, ?)
    ''', (user_id, amount, f"Deposit via {network}", txid, network))
    tx_id = cursor.lastrowid
    db.commit()
    db.close()
    
    markup = telebot.types.InlineKeyboardMarkup()
    btn_approve = telebot.types.InlineKeyboardButton("✅ Approve", callback_data=f"app_{tx_id}")
    btn_cancel = telebot.types.InlineKeyboardButton("❌ Cancel", callback_data=f"canc_{tx_id}")
    markup.add(btn_approve, btn_cancel)
    
    admin_msg = f"🔔 <b>New Deposit Request</b>\nTxID: <code>{tx_id}</code>\nUser: <code>{user_id}</code>\nAmount: <b>${amount} USDT</b>\nNetwork: {network}\nTX: <code>{txid}</code>"
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": ADMIN_ID, "text": admin_msg, "parse_mode": "HTML", "reply_markup": markup.to_dict()})
    
    return jsonify({"status": "success", "message": "Deposit request submitted successfully. Awaiting confirmation."})

@app.route('/api/withdraw/request', methods=['POST'])
def withdraw_request():
    data = request.json
    user_id = str(data.get('user_id'))
    amount = float(data.get('amount', 0))
    address = data.get('address', '')
    
    user = get_user(user_id)
    if user['balance'] < amount:
        return jsonify({"status": "error", "message": "⚠️ Insufficient available balance!"})
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        INSERT INTO transactions (user_id, type, amount, status, description, network)
        VALUES (?, 'WITHDRAWAL', ?, 'PENDING', ?, ?)
    ''', (user_id, -amount, f"Withdrawal to {address[:8]}...", "TRC20"))
    tx_id = cursor.lastrowid
    db.commit()
    db.close()
    
    markup = telebot.types.InlineKeyboardMarkup()
    btn_approve = telebot.types.InlineKeyboardButton("✅ Approve", callback_data=f"app_{tx_id}")
    btn_cancel = telebot.types.InlineKeyboardButton("❌ Cancel", callback_data=f"canc_{tx_id}")
    markup.add(btn_approve, btn_cancel)
    
    admin_msg = f"📤 <b>New Withdrawal Request</b>\nTxID: <code>{tx_id}</code>\nUser: <code>{user_id}</code>\nAmount: <b>${amount} USDT</b>\nAddress: <code>{address}</code>"
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": ADMIN_ID, "text": admin_msg, "parse_mode": "HTML", "reply_markup": markup.to_dict()})
    
    return jsonify({"status": "success", "message": "Withdrawal request submitted successfully!"})

@app.route('/api/support/send', methods=['POST'])
def send_support_ticket():
    data = request.json
    user_id = str(data.get('user_id'))
    username = data.get('username', 'User')
    subject = data.get('subject', '')
    message = data.get('message', '')
    
    db = get_db()
    db.execute('''
        INSERT INTO support_tickets (user_id, username, subject, message, status)
        VALUES (?, ?, ?, ?, 'PENDING')
    ''', (user_id, username, subject, message))
    db.commit()
    db.close()
    
    send_telegram(ADMIN_ID, f"🎫 <b>New Support Ticket</b>\nFrom: {username} (<code>{user_id}</code>)\nSubject: {subject}\nMessage: {message}")
    
    return jsonify({"status": "success", "message": "Support ticket sent successfully!"})

@app.route('/api/support/tickets/<user_id>', methods=['GET'])
def get_user_tickets(user_id):
    db = get_db()
    tickets = db.execute("SELECT * FROM support_tickets WHERE user_id = ? ORDER BY date DESC", (str(user_id),)).fetchall()
    db.close()
    return jsonify({"status": "success", "tickets": [dict(t) for t in tickets]})

@app.route('/api/admin/users', methods=['GET'])
def admin_users():
    db = get_db()
    users = db.execute("SELECT telegram_id, username, balance, active_deposit, created_at FROM users ORDER BY created_at DESC LIMIT 50").fetchall()
    db.close()
    return jsonify({"status": "success", "users": [dict(u) for u in users]})

@app.route('/api/admin/ranking', methods=['GET'])
def admin_ranking():
    db = get_db()
    ranking = db.execute('''
        SELECT u.telegram_id, u.username, SUM(i.amount) as total_invested, COUNT(i.id) as total_plans 
        FROM users u 
        JOIN investments i ON u.telegram_id = i.user_id 
        GROUP BY u.telegram_id 
        ORDER BY total_invested DESC LIMIT 10
    ''').fetchall()
    db.close()
    return jsonify({"status": "success", "ranking": [dict(r) for r in ranking]})

def run_bot():
    try:
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print(f"Bot polling error: {e}")

if __name__ == '__main__':
    # Start Telegram bot polling in a background thread so Flask can run concurrently
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    app.run(host='0.0.0.0', port=5000, debug=True)
