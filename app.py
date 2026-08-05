from flask import Flask, render_template, request, jsonify
import sqlite3
import requests

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = "8679853739:AAEcdk9DWC51lVO1EXvmamgyWSpkp2Vfdk0"
ADMIN_CHAT_ID = "5738022147"

DATABASE = "database.db"

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            type TEXT,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/deposit', methods=['POST'])
def deposit():
    data = request.json
    user_id = data.get('user_id')
    amount = data.get('amount')

    if not user_id or not amount:
       return jsonify({"status": "error", "message": "Xogta waa dhimantahay"}), 400

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO transactions (user_id, amount, type, status) VALUES (?, ?, 'deposit', 'pending')", (user_id, amount))
    conn.commit()
    conn.close()

    message = (
        f"📥 **Codsi Deposit Cusub ah!**\n\n"
        f"👤 User ID: `{user_id}`\n"
        f"💰 Lacagta: `${amount}`\n\n"
        f"Si aad u oggolaato, soo qor amarkan:\n"
        f"`/approve {user_id} {amount}`\n\n"
        f"Si aad u diiddo, soo qor:\n"
        f"`/reject {user_id} {amount}`"
    )
    
    send_telegram_message(ADMIN_CHAT_ID, message)
    return jsonify({"status": "success", "message": "Codsigii waa la diray"})

# Endpoint-kan waxaa isticmaalaya Admin Panel-ka si uu u soo bandhigo codsiyada pending-ka ah
@app.route('/admin/requests', methods=['GET'])
def get_admin_requests():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, amount, type, status FROM transactions WHERE status = 'pending'")
    rows = cursor.fetchall()
    conn.close()

    requests_list = []
    for row in rows:
        requests_list.append({
            "id": row[0],
            "user_id": row[1],
            "amount": row[2],
            "type": row[3],
            "status": row[4]
        })
    return jsonify(requests_list)

# Endpoint-kan wuxuu fuliyaa oggolaanshaha ama diidmada ee ka imanaysa Admin Panel-ka
@app.route('/admin/action', methods=['POST'])
def admin_action():
    data = request.json
    tx_id = data.get('id')
    action = data.get('action') # 'approve' ama 'reject'

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, amount, type FROM transactions WHERE id = ?", (tx_id,))
    tx = cursor.fetchone()

    if not tx:
        conn.close()
        return jsonify({"status": "error", "message": "Codsigan lama helin"}), 404

    user_id, amount, tx_type = tx

    if action == 'approve':
        cursor.execute("UPDATE transactions SET status = 'approved' WHERE id = ?", (tx_id,))
        cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (user_id,))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

        send_telegram_message(user_id, f"🎉 Warka Wanaagsan! Dalabkaaga oo ah ${amount} waa la xaqiijiyay.")
        return jsonify({"status": "success", "message": "Waa la oggolaaday"})
    
    elif action == 'reject':
        cursor.execute("UPDATE transactions SET status = 'rejected' WHERE id = ?", (tx_id,))
        conn.commit()
        conn.close()

        send_telegram_message(user_id, f"❌ Waan ka xunnahay, dalabkaaga oo ah ${amount} waa la diiday.")
        return jsonify({"status": "success", "message": "Waa la diiday"})

    conn.close()
    return jsonify({"status": "error", "message": "Action khaldan"}), 400

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.json
    
    if "message" in data:
        message = data["message"]
        chat_id = str(message.get("chat", {}).get("id"))
        text = message.get("text", "")

        if chat_id == ADMIN_CHAT_ID:
            if text.startswith("/approve"):
                parts = text.split()
                if len(parts) == 3:
                    target_user_id = parts[1]
                    amount = float(parts[2])

                    conn = sqlite3.connect(DATABASE)
                    cursor = conn.cursor()
                    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (target_user_id,))
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_user_id))
                    cursor.commit()
                    conn.close()

                    send_telegram_message(ADMIN_CHAT_ID, f"✅ Si guul leh ayaa loogu oggolaaday ${amount} user-ka {target_user_id}.")
                    send_telegram_message(target_user_id, f"🎉 Warka Wanaagsan! Deposit-kaaga oo ah ${amount} waa la xaqiijiyay oo waa lagu daray xisaabtaada.")
                else:
                    send_telegram_message(ADMIN_CHAT_ID, "⚠️ Qaabka aad u qortay waa qalad. Isticmaal: `/approve <user_id> <amount>`")

            elif text.startswith("/reject"):
                parts = text.split()
                if len(parts) == 3:
                    target_user_id = parts[1]
                    send_telegram_message(ADMIN_CHAT_ID, f"❌ Waa la diiday codsigii user-ka {target_user_id}.")
                    send_telegram_message(target_user_id, "❌ Waan ka xunnahay, codsigii deposit-ka ahaa waa la diiday.")
                else:
                    send_telegram_message(ADMIN_CHAT_ID, "⚠️ Qaabka aad u qortay waa qalad. Isticmaal: `/reject <user_id> <amount>`")

    return "OK", 200

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

if __name__ == '__main__':
    app.run(debug=True)
