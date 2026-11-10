import os
import sqlite3
from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# Xogtaaga saxda ah ee Bot-ka iyo Admin-ka
BOT_TOKEN = "8917773815:AAHoyZ0_U6Q5YHy5M9t0wutYqi1JlQZoVgw"
ADMIN_CHAT_ID = 5738022147

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('apexinvest.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT,
            username TEXT,
            balance REAL DEFAULT 1450.00,
            deposited REAL DEFAULT 1600.00,
            withdrawn REAL DEFAULT 300.00
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            type TEXT,
            title TEXT,
            network TEXT,
            ref TEXT,
            rawAmount REAL,
            amount TEXT,
            status TEXT,
            time TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            category TEXT,
            message TEXT,
            status TEXT,
            date TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- HELPER: SEND TELEGRAM NOTIFICATION ---
def send_telegram_alert(text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": ADMIN_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        response = requests.post(url, json=payload)
        print("Telegram Response:", response.text) # Si aad logs-ka uga aragto haddii ay fariintu tagto
    except Exception as e:
        print("Telegram alert error:", e)

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    conn = sqlite3.connect('apexinvest.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return jsonify({
            "id": row[0], "name": row[1], "username": row[2],
            "balance": row[3], "deposited": row[4], "withdrawn": row[5]
        })
    else:
        return jsonify({
            "id": user_id, "name": "Investor", "username": "@ismailessa",
            "balance": 1450.00, "deposited": 1600.00, "withdrawn": 300.00
        })

@app.route('/api/transaction', methods=['POST'])
def handle_transaction():
    data = request.json
    user_id = str(data.get('userId', '5738022147'))
    t_type = data.get('type')
    title = data.get('title')
    network = data.get('network')
    ref = data.get('ref')
    raw_amount = data.get('rawAmount')
    amount = data.get('amount')
    status = data.get('status', 'Pending Review')
    time_str = data.get('time')

    conn = sqlite3.connect('apexinvest.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (user_id, type, title, network, ref, rawAmount, amount, status, time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, t_type, title, network, ref, raw_amount, amount, status, time_str))
    conn.commit()
    tx_id = cursor.lastrowid
    conn.close()

    # Send Telegram Notification to Admin with Approve/Reject buttons
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"app_{tx_id}"},
                {"text": "❌ Reject", "callback_data": f"rej_{tx_id}"}
            ]
        ]
    }
    msg = (f"🚨 *NEW {t_type.upper()} REQUEST*\n\n"
           f"👤 User ID: `{user_id}`\n"
           f"💰 Amount: *{amount}*\n"
           f"🌐 Network: `{network}`\n"
           f"🔗 Ref/TxID: `{ref}`\n"
           f"⚡ Status: *Pending Review*")
    
    send_telegram_alert(msg, keyboard)
    return jsonify({"success": True, "txId": tx_id})

@app.route('/api/ticket', methods=['POST'])
def handle_ticket():
    data = request.json
    user_id = str(data.get('userId', '5738022147'))
    category = data.get('category')
    message = data.get('message')
    date_str = data.get('date')

    conn = sqlite3.connect('apexinvest.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tickets (user_id, category, message, status, date)
        VALUES (?, ?, ?, 'Pending', ?)
    ''', (user_id, category, message, date_str))
    conn.commit()
    ticket_id = cursor.lastrowid
    conn.close()

    # Send Support Ticket Notification to Admin
    msg = (f"🎫 *NEW SUPPORT TICKET #{ticket_id}*\n\n"
           f"👤 User ID: `{user_id}`\n"
           f"📂 Category: *{category}*\n"
           f"💬 Message: _{message}_")
    
    send_telegram_alert(msg)
    return jsonify({"success": True, "ticketId": ticket_id})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
