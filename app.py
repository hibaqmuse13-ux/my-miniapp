import os
import sqlite3
from flask import Flask, render_template, request, jsonify
import requests
import threading
import time

app = Flask(__name__)

# Xogtaaga saxda ah ee Bot-ka iyo Admin-ka
BOT_TOKEN = "8917773815:AAHoyZ0_U6Q5YHy5M9t0wutYqi1JlQZoVgw"
ADMIN_CHAT_ID = 5738022147

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('apexinvest.db', check_same_thread=False)
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
            date TEXT,
            reply TEXT
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
        print("Telegram Response:", response.text)
        return response.json()
    except Exception as e:
        print("Telegram alert error:", e)
        return None

def answer_callback_query(callback_query_id, text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        requests.post(url, json={"callback_query_id": callback_query_id, "text": text})
    except Exception as e:
        print("Answer callback error:", e)

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
        INSERT INTO tickets (user_id, category, message, status, date, reply)
        VALUES (?, ?, ?, 'Pending', ?, NULL)
    ''', (user_id, category, message, date_str))
    conn.commit()
    ticket_id = cursor.lastrowid
    conn.close()

    # Send Support Ticket Notification to Admin with Reply Button
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "💬 Reply to User", "callback_data": f"reply_tkt_{ticket_id}"}
            ]
        ]
    }
    msg = (f"🎫 *NEW SUPPORT TICKET #{ticket_id}*\n\n"
           f"👤 User ID: `{user_id}`\n"
           f"📂 Category: *{category}*\n"
           f"💬 Message: _{message}_")
    
    send_telegram_alert(msg, keyboard)
    return jsonify({"success": True, "ticketId": ticket_id})


# --- TELEGRAM BOT BACKGROUND POLLING (Si uu Admin-ku si toos ah ugu shaqeeyo badhamada) ---
def process_telegram_updates():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok") and data.get("result"):
                    for update in data["result"]:
                        last_update_id = update["update_id"]
                        
                        # Handle Inline Button Clicks (Approve, Reject, Reply)
                        if "callback_query" in update:
                            cq = update["callback_query"]
                            cq_id = cq["id"]
                            data_str = cq["data"]
                            chat_id = cq["message"]["chat"]["id"]
                            
                            conn = sqlite3.connect('apexinvest.db')
                            cursor = conn.cursor()

                            if data_str.startswith("app_") or data_str.startswith("rej_"):
                                tx_id = data_str.split("_")[1]
                                is_approve = data_str.startswith("app_")
                                new_status = "Completed" if is_approve else "Rejected"

                                cursor.execute("SELECT user_id, type, amount, rawAmount FROM transactions WHERE id = ?", (tx_id,))
                                tx = cursor.fetchone()
                                if tx:
                                    u_id, t_type, amount_str, raw_amt = tx
                                    cursor.execute("UPDATE transactions SET status = ? WHERE id = ?", (new_status, tx_id))
                                    
                                    if is_approve and t_type == "deposit":
                                        cursor.execute("UPDATE users SET balance = balance + ?, deposited = deposited + ? WHERE id = ?", (raw_amt, raw_amt, u_id))
                                    elif not is_approve and t_type == "withdraw":
                                        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (raw_amt, u_id))
                                    
                                    conn.commit()
                                    answer_callback_query(cq_id, f"Transaction {new_status}!")
                                    send_telegram_alert(f"✅ *TRANSACTION #{tx_id}* waxaa loo bedelay: *{new_status}*")
                                else:
                                    answer_callback_query(cq_id, "Transaction not found!")

                            elif data_str.startswith("reply_tkt_"):
                                tkt_id = data_str.split("_")[2]
                                answer_callback_query(cq_id, f"Fadlan qor jawaabta Ticket #{tkt_id} adigoo isticmaalaya reply fariintan.")
                                # Halkan waxaan ku kaydin karnaa state-ka in admin uu ku jiro replying
                                send_telegram_alert(f"✍️ Fadlan ku qor fariintaada jawaabta ah ee ku socota Ticket #{tkt_id} adigoo **Reply** ku samaynaya fariintan ama soo dir fariin cusub.")

                            conn.close()

                        # Handle Admin Text Reply in Telegram Chat
                        elif "message" in update and "reply_to_message" in update["message"]:
                            msg = update["message"]
                            if msg["from"]["id"] == ADMIN_CHAT_ID:
                                replied_text = msg["reply_to_message"].get("text", "")
                                answer_text = msg.text
                                
                                # Ka dhex raadi Ticket ID ama User ID fariintii la reply-gareeyay
                                if "SUPPORT TICKET #" in replied_text:
                                    try:
                                        # Soo saar ticket id
                                        import re
                                        tkt_match = re.search(r"SUPPORT TICKET #(\d+)", replied_text)
                                        if tkt_match:
                                            tkt_id = tkt_match.group(1)
                                            conn = sqlite3.connect('apexinvest.db')
                                            cursor = conn.cursor()
                                            cursor.execute("UPDATE tickets SET status = 'Resolved', reply = ? WHERE id = ?", (answer_text, tkt_id))
                                            conn.commit()
                                            
                                            # Hel user_id si loogu diro ogeysiis
                                            cursor.execute("SELECT user_id FROM tickets WHERE id = ?", (tkt_id,))
                                            t_row = cursor.fetchone()
                                            conn.close()
                                            
                                            send_telegram_alert(f"✨ Jawaabtiile waxaa loo diray si guul leh oo loo diiwaangeliyay Ticket #{tkt_id}!")
                                    except Exception as e:
                                        print("Error processing admin reply:", e)

        except Exception as e:
            print("Polling error:", e)
            time.sleep(5)

# Bilow Telegram Polling Thread si uusan u xidhin Flask server-ka
threading.Thread(target=process_telegram_updates, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
