import os
import sqlite3
from flask import Flask, render_template, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler

app = Flask(__name__)

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
    conn.commit()
    conn.close()

init_db()

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
        user_data = {
            "id": row[0], "name": row[1], "username": row[2],
            "balance": row[3], "deposited": row[4], "withdrawn": row[5]
        }
        return jsonify(user_data)
    else:
        return jsonify({
            "id": user_id, "name": "Investor", "username": "@ismailessa",
            "balance": 1450.00, "deposited": 1600.00, "withdrawn": 300.00
        })

@app.route('/api/transaction', methods=['POST'])
def handle_transaction():
    data = request.json
    user_id = data.get('userId')
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

    # Ogeysiis toos ah oo u diraya Telegram Admin-ka (Adiga)
    try:
        import asyncio
        async def send_alert():
            from telegram import Bot
            bot = Bot(token=BOT_TOKEN)
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"app_{tx_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"rej_{tx_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            msg = (f"🚨 *NEW {t_type.toUpperCase()} REQUEST*\n\n"
                   f"👤 User ID: `{user_id}`\n"
                   f"💰 Amount: *{amount}*\n"
                   f"🌐 Network: `{network}`\n"
                   f"🔗 Ref/TxID: `{ref}`\n"
                   f"⚡ Status: *Pending Review*")
            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode='Markdown', reply_markup=reply_markup)
        
        asyncio.run(send_alert())
    except Exception as e:
        print("Telegram alert error:", e)

    return jsonify({"success": True, "txId": tx_id})

# --- TELEGRAM BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect('apexinvest.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (id, name, username) VALUES (?, ?, ?)',
                   (str(user.id), user.first_name, user.username or 'ismailessa'))
    conn.commit()
    conn.close()

    keyboard = [
        [InlineKeyboardButton("💎 Launch ApexInvest Vault", web_app={"url": "https://<YOUR-RENDER-URL>.onrender.com"})],
        [InlineKeyboardButton("📊 Check Balance", callback_data="check_bal")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🚀 Welcome to *ApexInvest Institutional Vault*, {user.first_name}!\n\nSecure high-yield cryptocurrency investment & automated vault gateway.",
        parse_mode='Markdown', reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "check_bal":
        user_id = str(query.from_user.id)
        conn = sqlite3.connect('apexinvest.db')
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        bal = row[0] if row else 1450.00
        await query.message.reply_text(f"💰 Your Available Vault Balance: *${bal:.2f} USD*", parse_mode='Markdown')

    elif data.startswith("app_") or data.startswith("rej_"):
        parts = data.split('_')
        action = parts[0]
        tx_id = parts[1]

        conn = sqlite3.connect('apexinvest.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, type, rawAmount, amount, status FROM transactions WHERE id = ?', (tx_id,))
        tx = cursor.fetchone()

        if tx and tx[4] == 'Pending Review':
            user_id, t_type, raw_amount, amount, _ = tx
            if action == 'app':
                cursor.execute("UPDATE transactions SET status = 'Completed' WHERE id = ?", (tx_id,))
                if t_type == 'deposit':
                    cursor.execute("UPDATE users SET balance = balance + ?, deposited = deposited + ? WHERE id = ?", (raw_amount, raw_amount, user_id))
                elif t_type == 'withdraw':
                    cursor.execute("UPDATE users SET withdrawn = withdrawn + ? WHERE id = ?", (raw_amount, user_id))
                conn.commit()
                await query.edit_message_text(text=f"✅ Transaction #{tx_id} *APPROVED* successfully!", parse_mode='Markdown')
            else:
                cursor.execute("UPDATE transactions SET status = 'Rejected' WHERE id = ?", (tx_id,))
                if t_type == 'withdraw':
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (raw_amount, user_id))
                conn.commit()
                await query.edit_message_text(text=f"❌ Transaction #{tx_id} *REJECTED*.", parse_mode='Markdown')
        else:
            await query.edit_message_text(text="⚠️ Transaction already processed or not found.")
        conn.close()

if __name__ == '__main__':
    # Flask app wuxuu ka shaqayn karaa background ama Render wuxuu isticmaali karaa Gunicorn
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
