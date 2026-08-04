from datetime import datetime, timedelta
import json
import os
import sqlite3
import threading
import time

from flask import Flask, jsonify, render_template, request
import requests
import telebot
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# ========== CONFIGURATION ==========
BOT_TOKEN = "8626470350:AAFxJ3S5FjEjgBK-ySNAaKAZHvuOGRhLQ3A"
ADMIN_ID = 7076265514
ADMIN_PIN = "1234"

# Official Banner Image
WELCOME_BANNER = "https://images.unsplash.com/photo-1621416894569-0f39ed31d247?w=800&auto=format&fit=crop&q=60"

# Target Deposit Address (TRC20 Example)
TRC20_DEPOSIT_ADDRESS = "TLPVBmQnS6VTV7MwzLzYy7EjUKqsKob7hs"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)


# ========== DATABASE SETUP ==========
def init_db():
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()

  c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0,
        referred_by INTEGER DEFAULT 0,
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

  c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        status TEXT,
        network TEXT,
        txid TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

  c.execute("""CREATE TABLE IF NOT EXISTS investments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        profit REAL,
        status TEXT DEFAULT 'ACTIVE',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP
    )""")

  c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

  c.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        type TEXT,
        read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

  default_settings = {
      "bonus_amount": "1.0",
      "min_deposit": "10",
      "max_deposit": "10000",
      "min_withdraw": "10",
      "max_withdraw": "10000",
      "referral_bonus": "0.5",
      "maintenance_mode": "false",
      "welcome_message": (
          "Welcome to USDTPilotBot! 🚀 Invest & earn profit for 7 days."
      ),
      "currency": "USDT",
  }

  for key, value in default_settings.items():
    c.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )

  conn.commit()
  conn.close()


init_db()


# ========== DATABASE FUNCTIONS ==========
def get_setting(key):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT value FROM settings WHERE key=?", (key,))
  result = c.fetchone()
  conn.close()
  return result[0] if result else None


def add_user(user_id, username, referred_by=0):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT id FROM users WHERE id=?", (user_id,))
  if not c.fetchone():
    c.execute(
        "INSERT INTO users (id, username, referred_by) VALUES (?, ?, ?)",
        (user_id, username, referred_by),
    )
    if referred_by > 0:
      bonus = float(get_setting("referral_bonus") or 0.5)
      update_balance(referred_by, bonus)
      add_notification(
          referred_by, f"🎉 New referral! You earned {bonus} USDT", "SUCCESS"
      )
    conn.commit()
  conn.close()


def get_user(user_id):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT * FROM users WHERE id=?", (user_id,))
  data = c.fetchone()
  conn.close()
  return data


def update_balance(user_id, amount):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id)
  )
  conn.commit()
  conn.close()


def get_active_deposit(user_id):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "SELECT SUM(amount) FROM investments WHERE user_id=? AND status='ACTIVE'",
      (user_id,),
  )
  result = c.fetchone()[0]
  conn.close()
  return result if result is not None else 0.00


def add_request(user_id, req_type, amount, network, txid=""):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "INSERT INTO transactions (user_id, type, amount, status, network, txid)"
      " VALUES (?, ?, ?, ?, ?, ?)",
      (user_id, req_type, amount, "PENDING", network, txid),
  )
  tx_id = c.lastrowid
  conn.commit()
  conn.close()
  add_notification(
      user_id,
      f"📝 {req_type} request of {amount} USDT submitted. Processing...",
      "INFO",
  )
  return tx_id


def get_transaction_history(user_id, limit=10):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      """
    SELECT type, amount, status, network, created_at
    FROM transactions
    WHERE user_id=?
    ORDER BY created_at DESC LIMIT ?
    """,
      (user_id, limit),
  )
  data = c.fetchall()
  conn.close()
  return data


def add_notification(user_id, message, type="INFO"):
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "INSERT INTO notifications (user_id, message, type) VALUES (?, ?, ?)",
      (user_id, message, type),
  )
  conn.commit()
  conn.close()


# ========== TRONGRID TXID VERIFIER ==========
def verify_tron_txid(txid):
  """Verifies TRC20/USDT transaction using TronGrid API"""
  try:
    url = f"https://api.trongrid.io/v1/transactions/{txid}"
    response = requests.get(url, timeout=10)
    data = response.json()

    if data.get("success") and len(data.get("data", [])) > 0:
      tx_data = data["data"][0]
      if tx_data.get("ret", [{}])[0].get("contractRet") == "SUCCESS":
        # Check TRC20 transfer logs
        for log in tx_data.get("trc20TransferInfo", []):
          if log.get("to_address") == TRC20_DEPOSIT_ADDRESS:
            amount = float(log.get("amount_str")) / 1000000  # USDT Sun Decimals
            return True, amount
  except Exception as e:
    print(f"TRON verification error: {e}")
  return False, 0.0


# ========== BACKGROUND WORKER (7-DAY INVESTMENTS) ==========
def check_investments():
  while True:
    try:
      conn = sqlite3.connect("bot.db")
      c = conn.cursor()

      # Hourly Profit Calculation (7 Days = 168 Hours)
      c.execute(
          "SELECT id, user_id, amount, profit FROM investments WHERE"
          " status='ACTIVE'"
      )
      active_investments = c.fetchall()

      for inv in active_investments:
        inv_id, user_id, amount, total_profit = inv
        hourly_profit = total_profit / (7 * 24)
        update_balance(user_id, hourly_profit)

      # Expired Investments (7 days)
      c.execute("""
                SELECT id, user_id, amount FROM investments 
                WHERE status='ACTIVE' AND datetime(created_at, '+7 days') <= datetime('now')
            """)
      expired_investments = c.fetchall()

      for inv in expired_investments:
        inv_id, user_id, amount = inv
        c.execute(
            "UPDATE investments SET status='COMPLETED' WHERE id=?", (inv_id,)
        )
        conn.commit()

        # Return Initial Capital
        update_balance(user_id, amount)

        completion_msg = f"""🎉 **Investment Cycle Completed!**

Dear Investor,
Your 7-day investment cycle for **${amount:.2f} USDT** has successfully finished! 

💰 Your initial capital and profits are now fully credited to your main balance.
🔓 **Status:** Capital and Withdrawal locked expired. You can withdraw anytime!"""

        try:
          bot.send_message(user_id, completion_msg, parse_mode="Markdown")
        except Exception as e:
          print(f"Error sending message: {e}")

        add_notification(
            user_id,
            f"🎉 Investment completed for ${amount}! 7-day cycle finished and"
            " funds unlocked.",
            "SUCCESS",
        )

      conn.close()
    except Exception as e:
      print(f"Error in background worker: {e}")
    time.sleep(3600)


# ========== TELEGRAM BOT HANDLERS ==========
def get_main_reply_keyboard():
  markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
  markup.add(
      KeyboardButton("👤 My Profile"),
      KeyboardButton("💳 Deposit"),
      KeyboardButton("💎 Investment"),
      KeyboardButton("💸 Withdraw"),
      KeyboardButton("📜 History"),
      KeyboardButton("🎁 Referral"),
      KeyboardButton("📜 Terms"),
      KeyboardButton("🛠️ Support"),
      KeyboardButton("🔙 Back"),
  )
  return markup


@bot.message_handler(commands=["start"])
def start(message):
  user_id = message.from_user.id
  username = message.from_user.first_name or "User"

  referred_by = 0
  if message.text and " " in message.text:
    try:
      referred_by = int(message.text.split()[1])
      if referred_by == user_id:
        referred_by = 0
    except:
      pass

  add_user(user_id, username, referred_by)
  send_profile_card(message.chat.id, user_id, username, send_welcome_photo=True)


def send_profile_card(chat_id, user_id, name, send_welcome_photo=False):
  user = get_user(user_id)
  balance = user[2] if user else 0.00
  active_deposit = get_active_deposit(user_id)
  status = "Active 🟢" if (balance > 0 or active_deposit > 0) else "No Deposit"
  current_time = datetime.now().strftime("%I:%M %p")

  text = f"""👤 **PROFILE & DASHBOARD**

🆔 ID: `{user_id}`
👤 Name: {name}
💰 Balance: `${balance:.2f} USDT`
📊 Active Deposit: `${active_deposit:.2f} USDT`
📈 Hourly Profit: Active (Updates Every Hour) ⏳
⏳ Status: {status}
🔓 Withdrawal Lock: 7 Days Policy Enforced 🛡️ ({current_time})"""

  if send_welcome_photo:
    bot.send_photo(
        chat_id,
        WELCOME_BANNER,
        caption=(
            "🚀 **Welcome to USDTPilotBot!**\n\nInvest & earn profits for 7"
            " days with hourly updates."
        ),
        parse_mode="Markdown",
    )

  bot.send_message(
      chat_id,
      text,
      parse_mode="Markdown",
      reply_markup=get_main_reply_keyboard(),
  )


@bot.message_handler(
    func=lambda msg: msg.text
    in [
        "👤 My Profile",
        "💳 Deposit",
        "💎 Investment",
        "💸 Withdraw",
        "📜 History",
        "🎁 Referral",
        "📜 Terms",
        "🛠️ Support",
        "🔙 Back",
    ]
)
def handle_reply_menu(message):
  user_id = message.from_user.id
  name = message.from_user.first_name or "User"
  text = message.text

  if text == "👤 My Profile" or text == "🔙 Back":
    send_profile_card(message.chat.id, user_id, name)
  elif text == "💳 Deposit":
    bot.send_message(
        message.chat.id,
        f"💳 **Deposit Address (TRC20):**\n`{TRC20_DEPOSIT_ADDRESS}`\n\nSend"
        " USDT and use Mini App to submit TXID for auto-approval!",
        parse_mode="Markdown",
    )
  elif text == "💎 Investment":
    bot.send_message(
        message.chat.id,
        "💎 **7-Day Investment Plan**\n\nEarn 20% total profit in 7 days with"
        " hourly payouts! Open Mini App to invest instantly.",
        parse_mode="Markdown",
    )
  elif text == "💸 Withdraw":
    bot.send_message(
        message.chat.id,
        "💸 **Withdraw Funds**\n\nCommand format: `/withdraw 50`\nNote:"
        " Withdrawals are locked for 7 days during active investment.",
        parse_mode="Markdown",
    )
  elif text == "📜 History":
    bot.send_message(
        message.chat.id,
        "📜 Check Mini App Dashboard for live transaction history!",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["withdraw"])
def withdraw_command(message):
  user_id = message.from_user.id
  try:
    amount = float(message.text.split()[1])
    if amount <= 0:
      raise ValueError
  except:
    bot.reply_to(
        message, "❌ Invalid Format! Use: `/withdraw 50`", parse_mode="Markdown"
    )
    return

  user = get_user(user_id)
  if not user or (user[2] or 0) < amount:
    bot.reply_to(
        message, "❌ Insufficient Balance!", parse_mode="Markdown"
    )
    return

  add_request(user_id, "WITHDRAW", amount, "USDT")
  bot.reply_to(
      message,
      f"✅ Withdrawal request of `${amount:.2f} USDT` submitted!",
      parse_mode="Markdown",
  )


# ========== FLASK ROUTES (WEBAPP BACKEND & FRONTEND) ==========
@app.route("/")
def index():
  return render_template("index.html")


@app.route("/api/user/<int:user_id>")
def api_get_user(user_id):
  user = get_user(user_id)
  if not user:
    add_user(user_id, "Telegram User")
    user = get_user(user_id)

  balance = user[2] if user else 0.0
  active_deposit = get_active_deposit(user_id)
  return jsonify({
      "user_id": user_id,
      "balance": balance,
      "active_deposit": active_deposit,
  })


@app.route("/api/deposit/verify", methods=["POST"])
def api_verify_deposit():
  data = request.json or {}
  user_id = data.get("user_id")
  txid = data.get("txid", "").strip()

  if not txid or not user_id:
    return jsonify({"success": False, "message": "Invalid TXID or User ID."})

  # Check duplicates
  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute("SELECT id FROM transactions WHERE txid=?", (txid,))
  if c.fetchone():
    conn.close()
    return jsonify(
        {"success": False, "message": "This TXID has already been submitted."}
    )
  conn.close()

  # Verify on TRON Blockchain
  valid, amount = verify_tron_txid(txid)

  if valid and amount > 0:
    update_balance(user_id, amount)
    add_request(user_id, "DEPOSIT", amount, "TRC20", txid=txid)
    return jsonify({
        "success": True,
        "message": f"Successfully verified! Added ${amount:.2f} USDT.",
    })
  else:
    # Save as pending for manual admin check
    add_request(user_id, "DEPOSIT", 0, "TRC20", txid=txid)
    return jsonify({
        "success": False,
        "message": "Auto-verification failed or tx pending. Sent to Admin.",
    })


@app.route("/api/invest", methods=["POST"])
def api_invest():
  data = request.json or {}
  user_id = data.get("user_id")
  amount = float(data.get("amount", 0))

  user = get_user(user_id)
  if not user or user[2] < amount:
    return jsonify({"success": False, "message": "Insufficient balance!"})

  profit = amount * 0.20 * 7  # 20% Total profit

  conn = sqlite3.connect("bot.db")
  c = conn.cursor()
  c.execute(
      "UPDATE users SET balance = balance - ? WHERE id=?", (amount, user_id)
  )
  c.execute(
      "INSERT INTO investments (user_id, amount, profit, status) VALUES (?,"
      " ?, ?, 'ACTIVE')",
      (user_id, amount, profit),
  )
  conn.commit()
  conn.close()

  return jsonify(
      {"success": True, "message": f"Successfully invested ${amount:.2f} USDT!"}
  )


# ========== START APPLICATION ==========
if __name__ == "__main__":
  inv_thread = threading.Thread(target=check_investments, daemon=True)
  inv_thread.start()

  bot_thread = threading.Thread(target=bot.infinity_polling, daemon=True)
  bot_thread.start()

  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port)
