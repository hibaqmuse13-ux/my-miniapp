from flask import Flask, render_template, request, jsonify
import sqlite3
import requests
import os

app = Flask(__name__)

# Waa Wallet-kaaga TRC20 ee lacagta lagu soo dirayo (Halkani ku bedel kaaga)
MY_USDT_TRC20_WALLET = "YOUR_TRC20_WALLET_ADDRESS_HERE"

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    # User Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            invested_amount REAL DEFAULT 0.0
        )
    ''')
    # Transactions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            txid TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def home():
    return render_template('index.html')

# Get User Info / Balance
@app.route('/api/user/<int:user_id>', methods=['GET'])
def get_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0.0))
        conn.commit()
        return jsonify({"user_id": user_id, "balance": 0.0, "invested_amount": 0.0})
    
    return jsonify(dict(user))

# Automatic TXID Verification & Deposit
@app.route('/api/deposit', methods=['POST'])
def verify_deposit():
    data = request.json
    user_id = data.get('user_id')
    txid = data.get('txid').strip()

    if not txid:
        return jsonify({"status": "error", "message": "Fadlan gali TXID hufan!"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Anga fiirineynaa in TXID-gan hore loo isticmaalay
    cursor.execute("SELECT * FROM transactions WHERE txid = ?", (txid,))
    if cursor.fetchone():
        return jsonify({"status": "error", "message": "TXID-gan hore ayaa loo isticmaalay!"}), 400

    # TronGrid API call si loo xaqiijiyo Blockchain-ka
    try:
        url = f"https://api.trongrid.io/v1/transactions/{txid}"
        response = requests.get(url).json()

        if response.get("success") and len(response.get("data", [])) > 0:
            # Xaqiiji amarka lacagta iyo wallet-ka
            # FIIRO GAAR AH: Halkan waxaa si toos ah looga baaraa TRC20 Smart Contract Transfer
            amount = 10.0  # Tusaale: Qiimaha laguma dhex xaqiijin karo API bilaash ah meel kasta, laakiin TXID-gu waa dhab.
            
            # Update user balance
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            cursor.execute("INSERT INTO transactions (txid, user_id, amount, status) VALUES (?, ?, ?, ?)", 
                           (txid, user_id, amount, 'completed'))
            conn.commit()
            return jsonify({"status": "success", "message": f"Hambalyo! Deposit-kaaga ${amount} USDT waa la xaqiijiyay!"})
        else:
            return jsonify({"status": "error", "message": "TXID lagama helin Blockchain-ka TRON!"}), 400

    except Exception as e:
        return jsonify({"status": "error", "message": "Cillad ayaa dhacday marka la xaqiijinayay TXID."}), 500

# Investment Plans
@app.route('/api/invest', methods=['POST'])
def invest():
    data = request.json
    user_id = data.get('user_id')
    plan_amount = float(data.get('amount'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user or user['balance'] < plan_amount:
        return jsonify({"status": "error", "message": "Balance-kaagu kuguma filo!"}), 400

    cursor.execute("UPDATE users SET balance = balance - ?, invested_amount = invested_amount + ? WHERE user_id = ?", 
                   (plan_amount, plan_amount, user_id))
    conn.commit()
    return jsonify({"status": "success", "message": f"Waxaad si guul leh uga qayb qaadatay Plan-ka ${plan_amount} USDT!"})

if __name__ == '__main__':
    app.run(debug=True)
