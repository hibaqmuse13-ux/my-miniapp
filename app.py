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
# KONFIGURASYON
# ============================================================
BOT_TOKEN = "8679853739:AAEcdk9DWC51lVO1EXvmamgyWSpkp2Vfdk0"
ADMIN_ID = "5738022147"
BONUS_TALKA = 0.05  # 5%
UGU_YAR_KAYDIN = 10
UGU_YAR_MAALGASHI = 10
UGU_BADAN_MAALGASHI = 10000
RATE_DINTA = 20  # 20%
MAALMADO_MAALGASHI = 7

# ============================================================
# DATABASE SQLITE
# ============================================================
def hel_db():
    db = sqlite3.connect('usdtpilot.db')
    db.row_factory = sqlite3.Row
    return db

def bilow_db():
    db = hel_db()
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
            status TEXT DEFAULT 'SUGAYA',
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
            status TEXT DEFAULT 'FIRFIRCOON',
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            maturity_date TIMESTAMP,
            profit REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id TEXT,
            referred_id TEXT,
            bonus REAL,
            status TEXT DEFAULT 'SUGAYA',
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            subject TEXT,
            message TEXT,
            status TEXT DEFAULT 'FURAN',
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

# Bilow database
bilow_db()

# ============================================================
# FALOYAAL CAWIMA
# ============================================================
def dir_telegram(chat_id, text, keyboard=None, parse_mode='HTML'):
    """Dir fariin Telegram ah"""
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
        print(f"Khalad: {e}")
        return None

def hel_istifade(istifade_id):
    """Hel ama abuur istifade cusub"""
    db = hel_db()
    user = db.execute('SELECT * FROM users WHERE telegram_id = ?', (str(istifade_id),)).fetchone()
    db.close()
    
    if not user:
        # Abuur istifade cusub
        kood_talka = secrets.token_hex(4).upper()
        db = hel_db()
        db.execute('''
            INSERT INTO users (telegram_id, username, referral_code, created_at, last_login)
            VALUES (?, ?, ?, ?, ?)
        ''', (str(istifade_id), 'Istifade', kood_talka, datetime.now(), datetime.now()))
        db.commit()
        db.close()
        user = hel_istifade(istifade_id)
    
    return dict(user) if user else None

def samee_xiriir_talka(istifade_id):
    """Samee xiriir tafka ah"""
    return f"https://t.me/USDTPilotBot?start=ref_{istifade_id}"

def abuur_ogeysiin(istifade_id, cinwaan, fariin):
    """Abuur ogeysiin cusub"""
    db = hel_db()
    db.execute('''
        INSERT INTO notifications (user_id, title, message)
        VALUES (?, ?, ?)
    ''', (str(istifade_id), cinwaan, fariin))
    db.commit()
    db.close()

# ============================================================
# ROUTES - XOGTA ISTIFADE
# ============================================================
@app.route('/')
def home():
    """Soo bandhig frontend"""
    return render_template('index.html')

@app.route('/api/auth/verify', methods=['POST'])
def xaqiiji_istifade():
    """Xaqiiji istifade-ka marka uu ku soo biiro"""
    data = request.json
    istifade_id = data.get('user_id')
    magaca = data.get('username', 'Istifade')
    
    if not istifade_id:
        return jsonify({"status": "error", "message": "User ID ma jiro"})
    
    # Hel ama abuur istifade
    user = hel_istifade(istifade_id)
    
    # Cusbooneysii macluumaadka
    db = hel_db()
    db.execute('''
        UPDATE users 
        SET username = ?, last_login = ?
        WHERE telegram_id = ?
    ''', (magaca, datetime.now(), str(istifade_id)))
    db.commit()
    db.close()
    
    # Soo celi xogta
    return jsonify({
        "status": "success",
        "user": user,
        "xiriir_talka": samee_xiriir_talka(istifade_id),
        "message": f"Soo dhawow {magaca}!"
    })

@app.route('/api/user/<istifade_id>', methods=['GET'])
def hel_xogta_istifade(istifade_id):
    """Soo celi dhammaan xogta istifade-ka"""
    user = hel_istifade(istifade_id)
    if not user:
        return jsonify({"khalad": "Istifade lama helin"}), 404
    
    db = hel_db()
    
    # Macaamilo
    macaamilo = db.execute('''
        SELECT * FROM transactions 
        WHERE user_id = ? 
        ORDER BY date DESC LIMIT 50
    ''', (str(istifade_id),)).fetchall()
    
    # Maalgashi firfircoon
    maalgashi = db.execute('''
        SELECT * FROM investments 
        WHERE user_id = ? AND status = 'FIRFIRCOON'
    ''', (str(istifade_id),)).fetchall()
    
    # Ogeysiis
    ogeysiis = db.execute('''
        SELECT * FROM notifications 
        WHERE user_id = ? AND is_read = 0
        ORDER BY created_at DESC
    ''', (str(istifade_id),)).fetchall()
    
    # Taf
    taf = db.execute('''
        SELECT COUNT(*) as wadarta, SUM(bonus) as dakhli
        FROM referrals 
        WHERE referrer_id = ? AND status = 'DHAMMAYSTIRAY'
    ''', (str(istifade_id),)).fetchone()
    
    db.close()
    
    return jsonify({
        "user": user,
        "macaamilo": [dict(t) for t in macaamilo],
        "maalgashi": [dict(i) for i in maalgashi],
        "ogeysiis": [dict(n) for n in ogeysiis],
        "taf": {
            "wadarta": taf['wadarta'] if taf else 0,
            "dakhli": taf['dakhli'] if taf and taf['dakhli'] else 0
        }
    })

# ============================================================
# ROUTES - KAYDIN (DEPOSIT)
# ============================================================
@app.route('/api/deposit/request', methods=['POST'])
def codso_kaydin():
    """Istifade wuxuu codsadaa kaydin"""
    data = request.json
    istifade_id = str(data.get('user_id'))
    magaca = data.get('username', 'Istifade')
    network = data.get('network', 'TRC20')
    txid = data.get('txid')
    qadar = float(data.get('amount', 0))
    
    if qadar < UGU_YAR_KAYDIN:
        return jsonify({"status": "error", "message": f"Ugu yar kaydintu waa ${UGU_YAR_KAYDIN} USDT"})
    
    if not txid:
        return jsonify({"status": "error", "message": "TXID ayaa loo baahan yahay"})
    
    # Kaydi macaamilka
    db = hel_db()
    db.execute('''
        INSERT INTO transactions (user_id, type, amount, status, txid, network, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (istifade_id, 'KAYDIN', qadar, 'SUGAYA', txid, network, f'Kaydin via {network}'))
    db.commit()
    db.close()
    
    # Ogeysii Admin-ka
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Ogolow", "callback_data": f"approve_deposit_{istifade_id}_{qadar}"},
                {"text": "❌ Diid", "callback_data": f"reject_deposit_{istifade_id}"}
            ]
        ]
    }
    
    farriin_admin = f"""
📥 <b>CODSI KAYDIN CUSUB</b>

👤 <b>Istifade:</b> {magaca}
🆔 <b>ID:</b> <code>{istifade_id}</code>
💰 <b>Qadar:</b> ${qadar:,.2f} USDT
🌐 <b>Shabakad:</b> {network}
🔗 <b>TXID:</b> <code>{txid}</code>
🕐 <b>Waqti:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    
    dir_telegram(ADMIN_ID, farriin_admin, keyboard)
    
    # Ogeysii istifade-ka
    abuur_ogeysiin(
        istifade_id,
        "📥 Kaydin La Soo Diray",
        f"Kaydintaada ${qadar:,.2f} USDT waa la soo diray. Admin baa xaqiijin doona."
    )
    
    return jsonify({
        "status": "success",
        "message": "Codsiga kaydinta ayaa la soo diray admin-ka!"
    })

# ============================================================
# ROUTES - MAALGASHI (INVEST)
# ============================================================
@app.route('/api/invest', methods=['POST'])
def maalgashi():
    """Istifade wuxuu maalgaliyaa"""
    data = request.json
    istifade_id = str(data.get('user_id'))
    qadar = float(data.get('amount', 0))
    
    if qadar < UGU_YAR_MAALGASHI:
        return jsonify({"status": "error", "message": f"Ugu yar maalgashigu waa ${UGU_YAR_MAALGASHI}"})
    
    if qadar > UGU_BADAN_MAALGASHI:
        return jsonify({"status": "error", "message": f"Ugu badan maalgashigu waa ${UGU_BADAN_MAALGASHI}"})
    
    user = hel_istifade(istifade_id)
    if not user or user['balance'] < qadar:
        return jsonify({"status": "error", "message": "Dheeli ma hayso! Fadlan kaydi marka hore."})
    
    # Bilow maalgashiga
    db = hel_db()
    soo_celin = qadar * (1 + RATE_DINTA / 100)
    taariikh_dhamaad = datetime.now() + timedelta(days=MAALMADO_MAALGASHI)
    
    db.execute('''
        INSERT INTO investments (user_id, amount, expected_return, maturity_date)
        VALUES (?, ?, ?, ?)
    ''', (istifade_id, qadar, soo_celin, taariikh_dhamaad))
    
    # Cusbooneysii dheelitirka
    db.execute('''
        UPDATE users 
        SET balance = balance - ?, active_deposit = active_deposit + ?
        WHERE telegram_id = ?
    ''', (qadar, qadar, istifade_id))
    
    # Diiwaan geli macaamilka
    db.execute('''
        INSERT INTO transactions (user_id, type, amount, status, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (istifade_id, 'MAALGASHI', -qadar, 'DHAMMAYSTIRAY', f'Maalgashi ${qadar} USDT'))
    
    db.commit()
    db.close()
    
    # Ogeysii istifade-ka
    abuur_ogeysiin(
        istifade_id,
        "💰 Maalgashi Waa Bilaabmay",
        f"Maalgashigaaga ${qadar:,.2f} USDT waa bilaabmay. Soo celin la filayo: ${soo_celin:,.2f} USDT"
    )
    
    return jsonify({
        "status": "success",
        "message": f"Maalgashiga ${qadar:,.2f} USDT waa bilaabmay!",
        "soo_celin": soo_celin,
        "taariikh_dhamaad": taariikh_dhamaad.strftime('%Y-%m-%d')
    })

# ============================================================
# ROUTES - BIXITAAN (WITHDRAW)
# ============================================================
@app.route('/api/withdraw/request', methods=['POST'])
def codso_bixitaan():
    """Istifade wuxuu codsadaa bixitaan"""
    data = request.json
    istifade_id = str(data.get('user_id'))
    cinwaan = data.get('address')
    qadar = float(data.get('amount', 0))
    network = data.get('network', 'TRC20')
    
    if qadar < 10:
        return jsonify({"status": "error", "message": "Ugu yar bixitaanku waa $10 USDT"})
    
    user = hel_istifade(istifade_id)
    if not user or user['balance'] < qadar:
        return jsonify({"status": "error", "message": "Dheeli ma hayso!"})
    
    # Kaydi macaamilka
    db = hel_db()
    db.execute('''
        INSERT INTO transactions (user_id, type, amount, status, description, network)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (istifade_id, 'BIXITAAN', -qadar, 'SUGAYA', f'Bixitaan loo dirayo {network}', network))
    
    # Ku dar liiska cad haddii aysan jirin
    db.execute('''
        INSERT OR IGNORE INTO withdrawal_whitelist (user_id, address, network)
        VALUES (?, ?, ?)
    ''', (istifade_id, cinwaan, network))
    
    db.commit()
    db.close()
    
    # Ogeysii Admin-ka
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Ogolow", "callback_data": f"approve_withdraw_{istifade_id}_{qadar}"},
                {"text": "❌ Diid", "callback_data": f"reject_withdraw_{istifade_id}"}
            ]
        ]
    }
    
    farriin_admin = f"""
📤 <b>CODSI BIXITAAN CUSUB</b>

👤 <b>Istifade:</b> {user['username']}
🆔 <b>ID:</b> <code>{istifade_id}</code>
💰 <b>Qadar:</b> ${qadar:,.2f} USDT
🌐 <b>Shabakad:</b> {network}
🏦 <b>Cinwaan:</b> <code>{cinwaan}</code>
💳 <b>Dheelitir:</b> ${user['balance']:,.2f} USDT
    """
    
    dir_telegram(ADMIN_ID, farriin_admin, keyboard)
    
    abuur_ogeysiin(
        istifade_id,
        "📤 Bixitaan La Soo Diray",
        f"Bixitaankaaga ${qadar:,.2f} USDT waa la soo diray. Admin baa xaqiijin doona."
    )
    
    return jsonify({
        "status": "success",
        "message": "Codsiga bixitaanka ayaa loo diray admin-ka!"
    })

# ============================================================
# ROUTES - TAF (REFERRAL)
# ============================================================
@app.route('/api/referral/stats', methods=['GET'])
def tirakoob_taf():
    """Soo celi tirakoobka tafka"""
    istifade_id = request.args.get('user_id')
    
    db = hel_db()
    
    taf = db.execute('''
        SELECT r.*, u.username as magaca_taf 
        FROM referrals r
        JOIN users u ON r.referred_id = u.telegram_id
        WHERE r.referrer_id = ?
        ORDER BY r.date DESC
    ''', (str(istifade_id),)).fetchall()
    
    tirakoob = db.execute('''
        SELECT 
            COUNT(*) as wadarta,
            SUM(CASE WHEN status = 'DHAMMAYSTIRAY' THEN 1 ELSE 0 END) as dhammaystiray,
            SUM(CASE WHEN status = 'SUGAYA' THEN 1 ELSE 0 END) as sugaya,
            SUM(bonus) as wadarta_guno
        FROM referrals
        WHERE referrer_id = ?
    ''', (str(istifade_id),)).fetchone()
    
    db.close()
    
    return jsonify({
        "taf": [dict(r) for r in taf],
        "tirakoob": dict(tirakoob) if tirakoob else {
            "wadarta": 0,
            "dhammaystiray": 0,
            "sugaya": 0,
            "wadarta_guno": 0
        }
    })

# ============================================================
# ROUTES - TAAKO (SUPPORT)
# ============================================================
@app.route('/api/support/create', methods=['POST'])
def abuur_tikidh():
    """Istifade wuxuu abuuraa tikidh cawima"""
    data = request.json
    istifade_id = str(data.get('user_id'))
    mawduuc = data.get('subject')
    fariin = data.get('message')
    
    if not mawduuc or not fariin:
        return jsonify({"status": "error", "message": "Mawduuc iyo fariin ayaa loo baahan yahay"})
    
    db = hel_db()
    db.execute('''
        INSERT INTO support_tickets (user_id, subject, message, status)
        VALUES (?, ?, ?, ?)
    ''', (istifade_id, mawduuc, fariin, 'FURAN'))
    db.commit()
    db.close()
    
    # Ogeysii Admin-ka
    farriin_admin = f"""
🎫 <b>TIKIDH CAWIMA CUSUB</b>

👤 <b>Istifade ID:</b> <code>{istifade_id}</code>
📋 <b>Mawduuc:</b> {mawduuc}
📝 <b>Fariin:</b> {fariin}
    """
    
    dir_telegram(ADMIN_ID, farriin_admin)
    
    return jsonify({
        "status": "success",
        "message": "Tikidhka cawima ayaa la abuuray!"
    })

@app.route('/api/support/tickets', methods=['GET'])
def hel_tikidhyada():
    """Soo celi tikidhyada istifade-ka"""
    istifade_id = request.args.get('user_id')
    
    db = hel_db()
    tikidhyo = db.execute('''
        SELECT * FROM support_tickets 
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (str(istifade_id),)).fetchall()
    db.close()
    
    return jsonify({
        "tikidhyo": [dict(t) for t in tikidhyo]
    })

# ============================================================
# ROUTES - OGEYSIIS (NOTIFICATIONS)
# ============================================================
@app.route('/api/notifications/mark-read', methods=['POST'])
def calaamadee_la_akhriyay():
    """Calaamadee ogeysiisyada in la akhriyay"""
    data = request.json
    istifade_id = str(data.get('user_id'))
    
    db = hel_db()
    db.execute('''
        UPDATE notifications 
        SET is_read = 1 
        WHERE user_id = ?
    ''', (istifade_id,))
    db.commit()
    db.close()
    
    return jsonify({"status": "success"})

# ============================================================
# ROUTES - XISAABIYE (CALCULATOR)
# ============================================================
@app.route('/api/calculator', methods=['POST'])
def xisaabi_soo_celin():
    """Xisaabi soo celinta maalgashiga"""
    data = request.json
    qadar = float(data.get('amount', 0))
    maalmood = int(data.get('days', MAALMADO_MAALGASHI))
    
    heerka_maalinlaha = RATE_DINTA / maalmood
    wadarta_soo_celin = qadar * (1 + heerka_maalinlaha / 100 * maalmood)
    
    return jsonify({
        "qadar": qadar,
        "maalmood": maalmood,
        "wadarta_soo_celin": round(wadarta_soo_celin, 2),
        "faaiido": round(wadarta_soo_celin - qadar, 2)
    })

# ============================================================
# TELEGRAM WEBHOOK - SI DHAB AH
# ============================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram Bot webhook - Admin waxqabadyada"""
    update = request.json
    
    if "callback_query" in update:
        query = update["callback_query"]
        data = query["data"]
        chat_id = query["message"]["chat"]["id"]
        message_id = query["message"]["message_id"]
        
        # =========================================================
        # KAYDIN OGOLOW
        # =========================================================
        if data.startswith("approve_deposit_"):
            qaybo = data.split("_")
            istifade_id = qaybo[2]
            qadar = float(qaybo[3])
            
            db = hel_db()
            
            # Cusbooneysii macaamilka
            db.execute('''
                UPDATE transactions 
                SET status = 'DHAMMAYSTIRAY' 
                WHERE user_id = ? AND type = 'KAYDIN' AND status = 'SUGAYA'
                ORDER BY date DESC LIMIT 1
            ''', (istifade_id,))
            
            # Cusbooneysii dheelitirka
            db.execute('''
                UPDATE users 
                SET balance = balance + ? 
                WHERE telegram_id = ?
            ''', (qadar, istifade_id))
            
            db.commit()
            db.close()
            
            # Cusbooneysii farriinta admin-ka
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ <b>KAYDIN LAA OGGOLAADAY</b>\n\nIstifade: <code>{istifade_id}</code>\nQadar: +${qadar:,.2f} USDT",
                "parse_mode": "HTML"
            })
            
            # Ogeysii istifade-ka
            user = hel_istifade(istifade_id)
            farriin = f"""
🎉 <b>Kaydinta waa la oggolaaday!</b>

Kaydintaada <b>${qadar:,.2f} USDT</b> waa la xaqiijiyay.

💰 <b>Dheelitirka Cusub:</b> ${user['balance']:,.2f} USDT

Hada waad bilaabi kartaa maalgashiga!
            """
            dir_telegram(istifade_id, farriin)
            
            abuur_ogeysiin(
                istifade_id,
                "✅ Kaydin La Oggolaaday",
                f"Kaydintaada ${qadar:,.2f} USDT waa la oggolaaday!"
            )
            
            # Hubi tafka
            if user and user.get('referred_by'):
                tifaftire = hel_istifade(user['referred_by'])
                if tifaftire:
                    guno = qadar * BONUS_TALKA
                    db = hel_db()
                    db.execute('''
                        UPDATE users 
                        SET balance = balance + ? 
                        WHERE telegram_id = ?
                    ''', (guno, tifaftire['telegram_id']))
                    
                    db.execute('''
                        INSERT INTO referrals (referrer_id, referred_id, bonus, status)
                        VALUES (?, ?, ?, ?)
                    ''', (tifaftire['telegram_id'], istifade_id, guno, 'DHAMMAYSTIRAY'))
                    db.commit()
                    db.close()
                    
                    dir_telegram(
                        tifaftire['telegram_id'],
                        f"🎁 <b>Guno Taf!</b>\n\nWaxaad kasbatay <b>${guno:,.2f} USDT</b> kaydinta {user['username']}!"
                    )
        
        # =========================================================
        # KAYDIN DIID
        # =========================================================
        elif data.startswith("reject_deposit_"):
            istifade_id = data.split("_")[2]
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"❌ <b>KAYDIN LAA DIYAY</b>\n\nIstifade: <code>{istifade_id}</code>",
                "parse_mode": "HTML"
            })
            
            farriin = """
❌ <b>Kaydinta waa la diiday</b>

Codsiga kaydintaaga lama oggolaan.

📌 Sababaha suurtagalka ah:
• TXID aan sax ahayn
• Qadar khaldan
• Shabakad aan ku habooneyn

Fadlan soo gudbi codsi cusub.
            """
            dir_telegram(istifade_id, farriin)
        
        # =========================================================
        # BIXITAAN OGOLOW
        # =========================================================
        elif data.startswith("approve_withdraw_"):
            qaybo = data.split("_")
            istifade_id = qaybo[2]
            qadar = float(qaybo[3])
            
            db = hel_db()
            
            # Cusbooneysii macaamilka
            db.execute('''
                UPDATE transactions 
                SET status = 'DHAMMAYSTIRAY' 
                WHERE user_id = ? AND type = 'BIXITAAN' AND status = 'SUGAYA'
                ORDER BY date DESC LIMIT 1
            ''', (istifade_id,))
            
            # Ka jar dheelitirka
            db.execute('''
                UPDATE users 
                SET balance = balance - ? 
                WHERE telegram_id = ?
            ''', (qadar, istifade_id))
            
            db.commit()
            db.close()
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ <b>BIXITAAN LAA OGGOLAADAY</b>\n\nIstifade: <code>{istifade_id}</code>\nQadar: -${qadar:,.2f} USDT",
                "parse_mode": "HTML"
            })
            
            user = hel_istifade(istifade_id)
            farriin = f"""
✅ <b>Bixitaanka waa la oggolaaday!</b>

Bixitaankaaga <b>${qadar:,.2f} USDT</b> waa la farsameeyay.

💰 <b>Dheelitirka Cusub:</b> ${user['balance']:,.2f} USDT
            """
            dir_telegram(istifade_id, farriin)
            
            abuur_ogeysiin(
                istifade_id,
                "✅ Bixitaan La Oggolaaday",
                f"Bixitaankaaga ${qadar:,.2f} USDT waa la oggolaaday!"
            )
        
        # =========================================================
        # BIXITAAN DIID
        # =========================================================
        elif data.startswith("reject_withdraw_"):
            istifade_id = data.split("_")[2]
            
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"❌ <b>BIXITAAN LAA DIYAY</b>\n\nIstifade: <code>{istifade_id}</code>",
                "parse_mode": "HTML"
            })
            
            farriin = """
❌ <b>Bixitaanka waa la diiday</b>

Codsiga bixitaankaaga lama oggolaan.

📌 Sababaha suurtagalka ah:
• Cinwaan aan sax ahayn
• Dheelitir ku filan ma jiro
            """
            dir_telegram(istifade_id, farriin)
    
    return jsonify({"status": "ok"})

# ============================================================
# BILOW SERVER
# ============================================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
