import os
import jwt
import datetime
import hmac
import hashlib
import json
import threading
import time
import requests
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pymongo import MongoClient
from urllib.parse import parse_qsl
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ==========================================
# 1. DATABASE SETUP
# ==========================================
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/apexinvest')
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client.apexinvest
    users_col = db.users
    txs_col = db.transactions
    client.server_info()
    print("✅ MongoDB Connected")
except Exception as e:
    print("⚠️ MongoDB not connected. Using local memory.")
    db = None
    memory_users = {}
    memory_txs = []

# ==========================================
# 2. RATE LIMITING
# ==========================================
limiter = Limiter(get_remote_address, app=app, default_limits=["100 per 15 minutes"], storage_uri="memory://")

# ==========================================
# 3. HELPERS
# ==========================================
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID', '5738022147')
JWT_SECRET = os.getenv('JWT_SECRET', 'super-secret')

def verify_telegram_data(init_data):
    try:
        parsed_data = dict(parse_qsl(init_data))
        if "hash" not in parsed_data: return False
        hash_val = parsed_data.pop('hash')
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return calculated_hash == hash_val
    except Exception:
        return False

def generate_token(user_id):
    return jwt.encode({'id': user_id, 'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)}, JWT_SECRET, algorithm='HS256')

def auth_middleware(f):
    def wrapper(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token: return jsonify({'error': 'No token'}), 401
        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            request.user_id = data['id']
        except:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ==========================================
# TELEGRAM BOT HELPERS
# ==========================================
def send_tg_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup: payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def answer_callback(callback_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    requests.post(url, json={'callback_query_id': callback_id, 'text': text})

# ==========================================
# 4. ROUTES
# ==========================================
@app.route('/')
def home(): return render_template('index.html')

@app.route('/api/auth/login', methods=['POST'])
def login():
    init_data = request.json.get('initData')
    if init_data == "demo":
        user_id, name, username = "123456789", "Demo", "@demo"
    else:
        if not verify_telegram_data(init_data): return jsonify({'error': 'Invalid data'}), 401
        parsed_data = dict(parse_qsl(init_data))
        tg_user = json.loads(parsed_data['user'])
        user_id, name, username = str(tg_user['id']), tg_user.get('first_name', ''), '@' + tg_user.get('username', 'User')

    if db is not None:
        user = users_col.find_one({'telegramId': user_id})
        if not user:
            users_col.insert_one({'telegramId': user_id, 'name': name, 'username': username, 'balance': 0, 'lockedBalance': 0, 'totalDeposited': 0, 'totalWithdrawn': 0})
            user = users_col.find_one({'telegramId': user_id})
    else:
        if user_id not in memory_users:
            memory_users[user_id] = {'telegramId': user_id, 'name': name, 'username': username, 'balance': 0, 'lockedBalance': 0, 'totalDeposited': 0, 'totalWithdrawn': 0}
        user = memory_users[user_id]

    return jsonify({'token': generate_token(user_id), 'user': user})

@app.route('/api/deposit/request', methods=['POST'])
@limiter.limit("5 per 15 minutes")
@auth_middleware
def deposit_request():
    data = request.json
    txid, amount, network = data.get('txid'), float(data.get('amount')), data.get('network')
    
    if db is not None:
        if txs_col.find_one({'txid': txid}): return jsonify({'error': 'TxID used'}), 400
        tx_id = txs_col.insert_one({'userId': request.user_id, 'txid': txid, 'amount': amount, 'network': network, 'status': 'Pending Review', 'type': 'deposit'}).inserted_id
    else:
        if any(t['txid'] == txid for t in memory_txs): return jsonify({'error': 'TxID used'}), 400
        tx_id = str(len(memory_txs))
        memory_txs.append({'id': tx_id, 'userId': request.user_id, 'txid': txid, 'amount': amount, 'status': 'Pending Review', 'type': 'deposit'})

    msg = f"🚨 *NEW DEPOSIT*\n\n👤 User: `{request.user_id}`\n💰 Amount: *${amount}*\n🌐 Network: {network}\n🔗 TxID: `{txid}`"
    buttons = {'inline_keyboard': [[
        {'text': '✅ Approve', 'callback_data': f'dep_ok_{tx_id}'},
        {'text': '❌ Reject', 'callback_data': f'dep_no_{tx_id}'}
    ]]}
    send_tg_message(ADMIN_ID, msg, buttons)
    
    return jsonify({'success': True, 'message': 'Pending Admin Approval'})

@app.route('/api/withdraw/request', methods=['POST'])
@auth_middleware
def withdraw_request():
    data = request.json
    amount, network, address = float(data.get('amount')), data.get('network'), data.get('address')

    if db is not None:
        user = users_col.find_one({'telegramId': request.user_id})
        if user['balance'] < amount: return jsonify({'error': 'Insufficient balance'}), 400
        users_col.update_one({'telegramId': request.user_id}, {'$inc': {'balance': -amount}})
        tx_id = txs_col.insert_one({'userId': request.user_id, 'amount': amount, 'network': network, 'address': address, 'status': 'Pending Review', 'type': 'withdraw'}).inserted_id
    else:
        user = memory_users[request.user_id]
        if user['balance'] < amount: return jsonify({'error': 'Insufficient'}), 400
        user['balance'] -= amount
        tx_id = str(len(memory_txs))
        memory_txs.append({'id': tx_id, 'userId': request.user_id, 'amount': amount, 'network': network, 'status': 'Pending Review', 'type': 'withdraw'})

    msg = f"🚨 *WITHDRAW REQUEST*\n\n👤 User: `{request.user_id}`\n💰 Amount: *-${amount}*\n🌐 Network: {network}\n🏦 Address: `{address}`"
    buttons = {'inline_keyboard': [[
        {'text': '✅ Approve', 'callback_data': f'wth_ok_{tx_id}'},
        {'text': '❌ Reject', 'callback_data': f'wth_no_{tx_id}'}
    ]]}
    send_tg_message(ADMIN_ID, msg, buttons)
    
    return jsonify({'success': True, 'message': 'Pending Admin Approval', 'new_balance': user['balance'] if db is None else user['balance'] - amount})

# ==========================================
# 5. TELEGRAM CALLBACK LISTENER (Polling)
# ==========================================
def telegram_polling():
    print("🤖 Telegram bot polling started...")
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=5"
            res = requests.get(url).json()
            if res.get('ok') and res['result']:
                for update in res['result']:
                    offset = update['update_id'] + 1
                    
                    # Jawaabta /start
                    if 'message' in update and update['message'].get('text') == '/start':
                        chat_id = update['message']['chat']['id']
                        send_tg_message(chat_id, "👋 Ku soo dhawoow ApexInvest Bot!\n\nFadlan ka fur App-ka hoos si aad u bilowdo.")
                    
                    # Jawaabta Badhanada (Approve/Reject)
                    if 'callback_query' in update:
                        cq = update['callback_query']
                        data = cq['data']
                        cq_id = cq['id']
                        
                        parts = data.split('_')
                        if len(parts) >= 3:
                            action_type = parts[0]
                            status_type = parts[1]
                            tx_id = "_".join(parts[2:])

                            is_ok = (status_type == 'ok')

                            if db is not None:
                                from bson.objectid import ObjectId
                                try: tx = txs_col.find_one({'_id': ObjectId(tx_id)})
                                except: tx = None
                            else:
                                tx = next((t for t in memory_txs if t['id'] == tx_id), None)

                            if not tx or tx['status'] != 'Pending Review':
                                answer_callback(cq_id, "Already processed!")
                                continue

                            if action_type == 'dep' and is_ok:
                                if db is not None:
                                    txs_col.update_one({'_id': tx['_id']}, {'$set': {'status': 'Completed'}})
                                    users_col.update_one({'telegramId': tx['userId']}, {'$inc': {'balance': tx['amount'], 'totalDeposited': tx['amount']}})
                                else:
                                    tx['status'] = 'Completed'
                                    memory_users[tx['userId']]['balance'] += tx['amount']
                                
                                send_tg_message(tx['userId'], f"✅ *Deposit Approved!*\n💰 +${tx['amount']} added to balance.")
                                answer_callback(cq_id, "✅ Deposit Approved")

                            elif action_type == 'dep' and not is_ok:
                                if db is not None: txs_col.update_one({'_id': tx['_id']}, {'$set': {'status': 'Rejected'}})
                                else: tx['status'] = 'Rejected'
                                send_tg_message(tx['userId'], f"❌ *Deposit Rejected*\nYour deposit of ${tx['amount']} was rejected.")
                                answer_callback(cq_id, "❌ Deposit Rejected")

                            elif action_type == 'wth' and is_ok:
                                if db is not None:
                                    txs_col.update_one({'_id': tx['_id']}, {'$set': {'status': 'Completed'}})
                                    users_col.update_one({'telegramId': tx['userId']}, {'$inc': {'totalWithdrawn': tx['amount']}})
                                else:
                                    tx['status'] = 'Completed'
                                    memory_users[tx['userId']]['totalWithdrawn'] = memory_users[tx['userId']].get('totalWithdrawn', 0) + tx['amount']
                                
                                send_tg_message(tx['userId'], f"✅ *Withdrawal Successful!*\n💰 -${tx['amount']} sent.")
                                answer_callback(cq_id, "✅ Withdraw Approved")

                            elif action_type == 'wth' and not is_ok:
                                if db is not None:
                                    txs_col.update_one({'_id': tx['_id']}, {'$set': {'status': 'Rejected'}})
                                    users_col.update_one({'telegramId': tx['userId']}, {'$inc': {'balance': tx['amount']}})
                                else:
                                    tx['status'] = 'Rejected'
                                    memory_users[tx['userId']]['balance'] += tx['amount']

                                send_tg_message(tx['userId'], f"❌ *Withdrawal Rejected*\n${tx['amount']} has been refunded to your balance.")
                                answer_callback(cq_id, "❌ Withdraw Rejected (Refunded)")
                                
                            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup", json={
                                'chat_id': cq['message']['chat']['id'],
                                'message_id': cq['message']['message_id'],
                                'reply_markup': {'inline_keyboard': []}
                            })
        except Exception as e:
            print("Polling Error:", e)
        time.sleep(1)

# Start the polling thread
threading.Thread(target=telegram_polling, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 3000)))
