from datetime import datetime, timedelta
import os
import secrets
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, render_template, request
from pymongo import MongoClient
import requests

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))

# ============================================================
# CONFIGURATION
# ============================================================
BOT_TOKEN = os.getenv(
    'BOT_TOKEN', '8679853739:AAEcdk9DWC51lVO1EXvmamgyWSpkp2Vfdk0'
)
ADMIN_ID = os.getenv('ADMIN_ID', '5738022147')
TOTAL_PROFIT_RATE = 0.20  # 20% Total Return
INVESTMENT_DAYS = 7
TOTAL_HOURS = INVESTMENT_DAYS * 24  # 168 Hours

ALLOWED_PLANS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

# ============================================================
# MONGODB ATLAS DATABASE CONFIGURATION
# ============================================================
MONGO_URI = "mongodb+srv://hibaqmuse13_db_user:xHcBwWQEVi6LxAaX@cluster0.3ur01hf.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)

# Database-ka iyo Collections-ka
db = client['telegram_mini_app']
users_collection = db['users']
transactions_collection = db['transactions']
investments_collection = db['investments']
notifications_collection = db['notifications']


# ============================================================
# AUTOMATIC HOURLY PROFIT SCHEDULER
# ============================================================
def process_hourly_profits():
  active_invs = list(
      investments_collection.find({'status': 'ACTIVE'})
  )

  for inv in active_invs:
    inv_id = inv['_id']
    user_id = inv['user_id']
    hourly_profit = inv['hourly_profit']
    hours_passed = inv.get('hours_passed', 0) + 1

    # Add hourly profit directly to main balance
    users_collection.update_one(
        {'telegram_id': user_id}, {'$inc': {'balance': hourly_profit}}
    )

    if hours_passed >= TOTAL_HOURS:
      investments_collection.update_one(
          {'_id': inv_id},
          {
              '$set': {'hours_passed': hours_passed, 'status': 'COMPLETED'},
              '$inc': {'profit_accumulated': hourly_profit},
          },
      )
      users_collection.update_one(
          {'telegram_id': user_id},
          {'$inc': {'active_deposit': -inv['amount']}},
      )
      create_notification(
          user_id,
          '🎉 Plan Completed',
          f"Your investment of ${inv['amount']} USDT has fully matured!",
      )
    else:
      investments_collection.update_one(
          {'_id': inv_id},
          {
              '$set': {'hours_passed': hours_passed},
              '$inc': {'profit_accumulated': hourly_profit},
          },
      )


scheduler = BackgroundScheduler()
scheduler.add_job(func=process_hourly_profits, trigger='interval', hours=1)
scheduler.start()


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def send_telegram(chat_id, text, keyboard=None):
  url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
  payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
  if keyboard:
    payload['reply_markup'] = keyboard
  try:
    requests.post(url, json=payload, timeout=5)
  except:
    pass


def get_user(user_id):
  user = users_collection.find_one({'telegram_id': str(user_id)})
  if not user:
    ref_code = secrets.token_hex(4).upper()
    new_user = {
        'telegram_id': str(user_id),
        'username': 'User',
        'balance': 0.0,
        'active_deposit': 0.0,
        'referral_code': ref_code,
        'created_at': datetime.now(),
        'last_login': datetime.now(),
    }
    users_collection.insert_one(new_user)
    user = users_collection.find_one({'telegram_id': str(user_id)})

  # MongoDB wuxuu soo celiyaa ObjectId taasoo mararka qaar dhibaato keenta, halkaan ayaan ka hagaajineynaa
  if user and '_id' in user:
    user['_id'] = str(user['_id'])
  return user


def create_notification(user_id, title, message):
  notifications_collection.insert_one({
      'user_id': str(user_id),
      'title': title,
      'message': message,
      'is_read': False,
      'created_at': datetime.now(),
  })


# ============================================================
# API ENDPOINTS
# ============================================================
@app.route('/')
def home():
  return render_template('index.html')


@app.route('/api/auth/verify', methods=['POST'])
def verify_user():
  data = request.json
  user_id = str(data.get('user_id'))
  username = data.get('username', 'User')

  get_user(user_id)
  users_collection.update_one(
      {'telegram_id': user_id},
      {'$set': {'username': username, 'last_login': datetime.now()}},
  )

  return jsonify({'status': 'success', 'user': get_user(user_id)})


@app.route('/api/user/<user_id>', methods=['GET'])
def get_user_data(user_id):
  user = get_user(user_id)

  transactions = list(
      transactions_collection.find({'user_id': str(user_id)})
      .sort('date', -1)
      .limit(20)
  )
  for t in transactions:
    t['_id'] = str(t['_id'])

  investments = list(
      investments_collection.find(
          {'user_id': str(user_id), 'status': 'ACTIVE'}
      )
  )
  for i in investments:
    i['_id'] = str(i['_id'])

  return jsonify({
      'user': user,
      'macaamilo': transactions,
      'maalgashi': investments,
  })


@app.route('/api/deposit/request', methods=['POST'])
def request_deposit():
  data = request.json
  user_id = str(data.get('user_id'))
  username = data.get('username', 'User')
  network = data.get('network', 'TRC20')
  txid = data.get('txid')
  amount = float(data.get('amount', 0))

  if amount < 10:
    return jsonify(
        {'status': 'error', 'message': '⚠️ Minimum deposit is $10 USDT'}
    )
  if not txid:
    return jsonify(
        {'status': 'error', 'message': '⚠️ Please enter a valid TXID / Hash!'}
    )

  tx_doc = {
      'user_id': user_id,
      'type': 'DEPOSIT',
      'amount': amount,
      'status': 'PENDING',
      'txid': txid,
      'network': network,
      'description': f'Deposit via {network}',
      'date': datetime.now(),
  }
  result = transactions_collection.insert_one(tx_doc)
  tx_id = str(result.inserted_id)

  # Inline buttons for Admin
  keyboard = {
      'inline_keyboard': [[
          {'text': '✅ Approve', 'callback_data': f'approve_dep_{tx_id}'},
          {'text': '❌ Reject', 'callback_data': f'reject_dep_{tx_id}'},
      ]]
  }
  admin_msg = (
      f'📥 <b>NEW DEPOSIT REQUEST</b>\n\nUser:'
      f' {username}\nID: <code>{user_id}</code>\nAmount: <b>${amount}'
      f' USDT</b>\nNetwork: {network}\nTXID: <code>{txid}</code>'
  )
  send_telegram(ADMIN_ID, admin_msg, keyboard)

  return jsonify({
      'status': 'success',
      'message': '✅ Deposit request submitted successfully! Pending approval.',
  })


@app.route('/api/invest', methods=['POST'])
def invest():
  data = request.json
  user_id = str(data.get('user_id'))
  amount = int(data.get('amount', 0))

  if amount not in ALLOWED_PLANS:
    return jsonify(
        {'status': 'error', 'message': '⚠️ Invalid Investment Plan!'}
    )

  user = get_user(user_id)
  if not user or user['balance'] < amount:
    return jsonify({
        'status': 'error',
        'message': '⚠️ Insufficient balance! Please deposit first.',
    })

  total_profit = amount * TOTAL_PROFIT_RATE
  hourly_profit = total_profit / TOTAL_HOURS
  maturity_date = datetime.now() + timedelta(days=INVESTMENT_DAYS)

  users_collection.update_one(
      {'telegram_id': user_id},
      {'$inc': {'balance': -amount, 'active_deposit': amount}},
  )

  investments_collection.insert_one({
      'user_id': user_id,
      'amount': amount,
      'total_profit': total_profit,
      'hourly_profit': hourly_profit,
      'profit_accumulated': 0.0,
      'hours_passed': 0,
      'status': 'ACTIVE',
      'start_date': datetime.now(),
      'maturity_date': maturity_date,
  })

  transactions_collection.insert_one({
      'user_id': user_id,
      'type': 'INVESTMENT',
      'amount': -amount,
      'status': 'COMPLETED',
      'description': f'Invested ${amount} USDT',
      'date': datetime.now(),
  })

  create_notification(
      user_id, '🚀 Investment Started', f'Successfully invested ${amount} USDT!'
  )
  return jsonify(
      {'status': 'success', 'message': f'🎉 Successfully invested ${amount} USDT!'}
  )


@app.route('/api/withdraw/request', methods=['POST'])
def request_withdrawal():
  data = request.json
  user_id = str(data.get('user_id'))
  address = data.get('address')
  amount = float(data.get('amount', 0))

  if amount < 10:
    return jsonify(
        {'status': 'error', 'message': '⚠️ Minimum withdrawal is $10 USDT'}
    )
  if not address:
    return jsonify(
        {'status': 'error', 'message': '⚠️ Please provide a wallet address!'}
    )

  active_inv = investments_collection.find_one(
      {'user_id': user_id, 'status': 'ACTIVE'}
  )

  if active_inv:
    start_time = active_inv['start_date']
    if datetime.now() < start_time + timedelta(days=INVESTMENT_DAYS):
      return jsonify({
          'status': 'error',
          'message': (
              '🔒 Withdrawal locked! Active investment must complete 7 days.'
          ),
      })

  user = get_user(user_id)
  if not user or user['balance'] < amount:
    return jsonify({'status': 'error', 'message': '⚠️ Insufficient balance!'})

  users_collection.update_one(
      {'telegram_id': user_id}, {'$inc': {'balance': -amount}}
  )
  transactions_collection.insert_one({
      'user_id': user_id,
      'type': 'WITHDRAWAL',
      'amount': -amount,
      'status': 'PENDING',
      'description': f'Withdrawal to {address}',
      'date': datetime.now(),
  })

  admin_msg = (
      f'📤 <b>NEW WITHDRAWAL REQUEST</b>\n\nUser ID:'
      f' <code>{user_id}</code>\nAmount: ${amount} USDT\nAddress:'
      f' <code>{address}</code>'
  )
  send_telegram(ADMIN_ID, admin_msg)

  return jsonify({
      'status': 'success',
      'message': '✅ Withdrawal request submitted successfully!',
  })


# ============================================================
# TELEGRAM WEBHOOK (AUTOMATIC BALANCE UPDATE ON APPROVAL)
# ============================================================
@app.route('/webhook', methods=['POST'])
def webhook():
  update = request.json
  if 'callback_query' in update:
    query = update['callback_query']
    data = query['data']
    chat_id = query['message']['chat']['id']
    message_id = query['message']['message_id']

    from bson.objectid import ObjectId

    # Admin Action: Approve Deposit
    if data.startswith('approve_dep_'):
      tx_id = data.split('_')[2]

      try:
        tx = transactions_collection.find_one(
            {'_id': ObjectId(tx_id), 'status': 'PENDING'}
        )
      except:
        tx = None

      if tx:
        user_id = tx['user_id']
        amount = tx['amount']

        # 1. Update Transaction Status
        transactions_collection.update_one(
            {'_id': ObjectId(tx_id)}, {'$set': {'status': 'COMPLETED'}}
        )

        # 2. Add amount AUTOMATICALLY to User Balance
        users_collection.update_one(
            {'telegram_id': user_id}, {'$inc': {'balance': amount}}
        )

        # Notify Admin on Telegram
        requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/editMessageText',
            json={
                'chat_id': chat_id,
                'message_id': message_id,
                'text': (
                    f'✅ <b>DEPOSIT APPROVED</b>\nUser:'
                    f' <code>{user_id}</code>\nAmount: +${amount}'
                    f' USDT\nStatus: Balance Updated!'
                ),
                'parse_mode': 'HTML',
            },
        )

        # Notify User on Telegram
        send_telegram(
            user_id,
            f'🎉 <b>Deposit Approved!</b>\n\nYour deposit of <b>${amount}'
            ' USDT</b> has been credited to your balance successfully.',
        )

    elif data.startswith('reject_dep_'):
      tx_id = data.split('_')[2]
      try:
        transactions_collection.update_one(
            {'_id': ObjectId(tx_id)}, {'$set': {'status': 'REJECTED'}}
        )
      except:
        pass

      requests.post(
          f'https://api.telegram.org/bot{BOT_TOKEN}/editMessageText',
          json={
              'chat_id': chat_id,
              'message_id': message_id,
              'text': '❌ <b>DEPOSIT REJECTED</b>',
              'parse_mode': 'HTML',
          },
      )

  return jsonify({'status': 'ok'})


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000, debug=True)
