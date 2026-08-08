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
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://yourdomain.com")

INVESTMENT_DAYS = 14
TOTAL_HOURS = INVESTMENT_DAYS * 24  # 336 Hours (2 Weeks)

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
            message TEXT,
            status TEXT DEFAULT 'UNREAD',
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            username TEXT,
            subject TEXT,
            message TEXT,
            admin_reply TEXT,
            status TEXT DEFAULT 'PENDING',
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    db.close()

init_db()

def send_telegram(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        print(f"Telegram send error: {e}")

@app.route('/')
def index():
    return render_template('index.html')

def get_user(telegram_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE telegram_id = ?", (str(telegram_id),)).fetchone()
    db.close()
    if not user:
        db = get_db()
        db.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (str(telegram_id), f"User_{telegram_id}"))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE telegram_id = ?", (str(telegram_id),)).fetchone()
        db.close()
    return dict(user)

@app.route('/api/auth/verify', methods=['POST'])
def auth_verify():
    data = request.json or {}
    user_id = str(data.get('user_id'))
    username = data.get('username', f"User_{user_id}")
    
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
    if not user:
        db.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (user_id, username))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
    else:
        db.execute("UPDATE users SET username = ?, last_login = CURRENT_TIMESTAMP WHERE telegram_id = ?", (username, user_id))
        db.commit()
    db.close()
    return jsonify({"status": "success", "user": dict(user)})

@app.route('/api/user/<user_id>', methods=['GET'])
def get_user_data(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,)).fetchone()
    macaamilo = db.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
    maalgashi = db.execute("SELECT * FROM investments WHERE user_id = ? AND status = 'ACTIVE'", (user_id,)).fetchall()
    db.close()
    
    return jsonify({
        "user": dict(user) if user else {},
        "macaamilo": [dict(row) for row in macaamilo],
        "maalgashi": [dict(row) for row in maalgashi]
    })

@app.route('/api/invest', methods=['POST'])
def invest_plan():
    data = request.json or {}
    user_id = str(data.get('user_id'))
    try:
        amount = float(data.get('amount', 0))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "⚠️ Invalid investment amount!"})
    
    user = get_user(user_id)
    if user['balance'] < amount:
        return jsonify({"status": "error", "message": "⚠️ Insufficient balance for this investment!"})
    
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
    ''', (user_id, -amount, f"Investment deployed for ${amount} Plan"))
    
    db.commit()
    db.close()
    
    return jsonify({"status": "success", "message": f"Successfully invested ${amount} USDT!"})

@app.route('/api/deposit/request', methods=['POST'])
def deposit_request():
    user_id = str(request.form.get('user_id', ''))
    amt_str = request.form.get('amount', '0')
    try:
        amount = float(amt_str)
    except (ValueError, TypeError):
        amount = 0.0
        
    network = request.form.get('network', 'TRC20')
    txid = request.form.get('txid', '')
    
    db = get_db()
    db.execute('''
        INSERT INTO transactions (user_id, type, amount, status, description, txid, network)
        VALUES (?, 'DEPOSIT', ?, 'PENDING', ?, ?, ?)
    ''', (user_id, amount, f"Deposit via {network}", txid, network))
    
    db.commit()
    db.close()
    
    send_telegram(ADMIN_ID, f"🔔 <b>New Deposit Request</b>\nUser: <code>{user_id}</code>\nAmount: <b>${amount} USDT</b>\nNetwork: {network}\nTXID: <code>{txid}</code>")
    
    return jsonify({"status": "success", "message": "Deposit request submitted successfully. Awaiting confirmation."})

@app.route('/api/withdraw/request', methods=['POST'])
def withdraw_request():
    data = request.json or {}
    user_id = str(data.get('user_id'))
    try:
        amount = float(data.get('amount', 0))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "⚠️ Invalid withdrawal amount!"})
        
    address = data.get('address', '')
    
    user = get_user(user_id)
    if user['balance'] < amount:
        return jsonify({"status": "error", "message": "⚠️ Insufficient balance!"})
    
    db = get_db()
    db.execute("UPDATE users SET balance = balance - ?, total_withdrawals = total_withdrawals + ? WHERE telegram_id = ?", 
               (amount, amount, user_id))
    
    db.execute('''
        INSERT INTO transactions (user_id, type, amount, status, description, network)
        VALUES (?, 'WITHDRAWAL', ?, 'PENDING', ?, ?)
    ''', (user_id, -amount, f"Withdrawal to {address[:8]}...", "TRC20"))
    
    db.commit()
    db.close()
    
    send_telegram(ADMIN_ID, f"📤 <b>New Withdrawal Request</b>\nUser: <code>{user_id}</code>\nAmount: <b>${amount} USDT</b>\nAddress: <code>{address}</code>")
    
    return jsonify({"status": "success", "message": "Withdrawal request submitted successfully!"})

@app.route('/api/support/send', methods=['POST'])
def support_send():
    data = request.json or {}
    user_id = str(data.get('user_id'))
    username = data.get('username', f"User_{user_id}")
    subject = data.get('subject', '')
    message = data.get('message', '')
    
    db = get_db()
    db.execute('''
        INSERT INTO tickets (user_id, username, subject, message, status)
        VALUES (?, ?, ?, ?, 'PENDING')
    ''', (user_id, username, subject, message))
    db.commit()
    db.close()
    
    send_telegram(ADMIN_ID, f"📩 <b>New Support Ticket</b>\nUser: <code>{user_id}</code> ({username})\nSubject: <b>{subject}</b>\nMessage: {message}")
    return jsonify({"status": "success", "message": "Support ticket submitted successfully!"})

@app.route('/api/support/tickets/<user_id>', methods=['GET'])
def get_user_tickets(user_id):
    db = get_db()
    tickets = db.execute("SELECT * FROM tickets WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
    db.close()
    return jsonify({"status": "success", "tickets": [dict(t) for t in tickets]})

@app.route('/api/admin/users', methods=['GET'])
def admin_users():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY id DESC LIMIT 50").fetchall()
    db.close()
    return jsonify({"status": "success", "users": [dict(u) for u in users]})

@app.route('/api/admin/ranking', methods=['GET'])
def admin_ranking():
    db = get_db()
    ranking = db.execute('''
        SELECT u.telegram_id, u.username, SUM(i.amount) as total_invested, COUNT(i.id) as total_plans 
        FROM users u JOIN investments i ON u.telegram_id = i.user_id 
        GROUP BY u.telegram_id ORDER BY total_invested DESC LIMIT 10
    ''').fetchall()
    db.close()
    return jsonify({"status": "success", "ranking": [dict(r) for r in ranking]})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
