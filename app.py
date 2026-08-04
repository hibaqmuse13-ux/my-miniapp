import os
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Configurations - Bot Token & Admin ID-gaaga Dhabta ah
BOT_TOKEN = os.getenv("BOT_TOKEN", "8679853739:AAEcdk9DWC51lVO1EXvmamgyWSpkp2Vfdk0")
ADMIN_ID = os.getenv("ADMIN_ID", "5738022147")

# Database-ka Kumaankanka Ah (Waxaa loo beddeli karaa SQLite ama Database kale)
users_db = {}
transactions_db = []

def get_user(user_id):
    user_id = str(user_id)
    if user_id not in users_db:
        users_db[user_id] = {
            "balance": 0.0,
            "active_deposit": 0.0,
            "history": []
        }
    return users_db[user_id]

def send_telegram_msg(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending message: {e}")

@app.route('/')
def home():
    return render_template('index.html')

# Qaybta Xogta User-ka ku saabsan
@app.route('/api/user/<user_id>', methods=['GET'])
def get_user_data(user_id):
    user = get_user(user_id)
    return jsonify({
        "balance": user["balance"],
        "active_deposit": user["active_deposit"],
        "history": user["history"]
    })

# Marka uu User-ku Deposit dalbado (Fariinta Admin-ka loo dirayo)
@app.route('/api/deposit/request', methods=['POST'])
def deposit_request():
    data = request.json
    user_id = str(data.get('user_id'))
    username = data.get('username', 'User')
    network = data.get('network')
    txid = data.get('txid')
    amount = float(data.get('amount', 10.0))

    tx_data = {
        "txid": txid,
        "user_id": user_id,
        "username": username,
        "network": network,
        "amount": amount,
        "status": "PENDING"
    }
    transactions_db.append(tx_data)

    # Fariinta loo dirayo Admin ID (5738022147)
    admin_text = (
        f"📥 <b>NEW DEPOSIT REQUEST</b>\n\n"
        f"👤 <b>User:</b> {username} (<code>{user_id}</code>)\n"
        f"💰 <b>Amount:</b> ${amount} USDT\n"
        f"🌐 <b>Network:</b> {network}\n"
        f"🔗 <b>TXID:</b> <code>{txid}</code>\n\n"
        f"<i>Khadka ka hubi TXID-ga kaddibna taabo Approve.</i>"
    )

    # Batoonnada Oggolaanshaha (Inline Keyboard)
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve Deposit", "callback_data": f"approve_{user_id}_{amount}_{txid[:8]}"},
            {"text": "❌ Reject", "callback_data": f"reject_{user_id}"}
        ]]
    }

    send_telegram_msg(ADMIN_ID, admin_text, keyboard)

    return jsonify({"status": "success", "message": "Deposit request sent to Admin for review!"})

# Webhook-ga Telegram Bot-ka (Marka Admin-ku Batoonka Taabo)
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    if "callback_query" in update:
        query = update["callback_query"]
        data = query["data"]
        chat_id = query["message"]["chat"]["id"]
        message_id = query["message"]["message_id"]

        if data.startswith("approve_"):
            parts = data.split("_")
            user_id = parts[1]
            amount = float(parts[2])

            user = get_user(user_id)
            user["balance"] += amount
            user["history"].append({
                "type": "Deposit",
                "amount": f"+${amount} USDT",
                "date": "Just now",
                "status": "SUCCESS"
            })

            # Fariin loo dirayo Admin-ka oo muujinaysa in la oggolaaday
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ <b>DEPOSIT APPROVED</b>\n\nUser ID: <code>{user_id}</code>\nAmount Credited: ${amount} USDT",
                "parse_mode": "HTML"
            })

            # Fariin toos ah oo loo dirayo User-ka
            user_text = f"🎉 <b>Deposit Approved!</b>\n\nAccount-kaaga waxaa kuso biirtay <b>${amount} USDT</b>. Hada waad maalgashan kartaa."
            send_telegram_msg(user_id, user_text)

        elif data.startswith("reject_"):
            parts = data.split("_")
            user_id = parts[1]

            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"❌ <b>DEPOSIT REJECTED</b>\n\nUser ID: <code>{user_id}</code>",
                "parse_mode": "HTML"
            })

            user_text = f"❌ <b>Deposit Rejected!</b>\n\nCodsigii deposit-kaaga waa la diaday. Fadlan la xidhiidh support-ka."
            send_telegram_msg(user_id, user_text)

    return jsonify({"status": "ok"})

# Maalgashiga (Investment)
@app.route('/api/invest', methods=['POST'])
def invest():
    data = request.json
    user_id = str(data.get('user_id'))
    amount = float(data.get('amount'))

    user = get_user(user_id)
    if user["balance"] < amount:
        return jsonify({"status": "error", "message": "Insufficient Balance! Please deposit first."})

    user["balance"] -= amount
    user["active_deposit"] += amount
    user["history"].append({
        "type": "Investment",
        "amount": f"-${amount} USDT",
        "date": "Just now",
        "status": "ACTIVE"
    })

    return jsonify({"status": "success", "message": f"Successfully invested ${amount} USDT!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
