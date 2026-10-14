import os
import sqlite3
import datetime
import secrets
import csv
import io
import json
import security

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "app.db")

os.makedirs(DATA_DIR, exist_ok=True)

def get_db():
    """الحصول على اتصال بقاعدة البيانات مهيأ بأعلى معايير الأداء والـ Concurrency"""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    """تهيئة قاعدة البيانات وإنشاء الجداول والفهارس المؤسسية والخزنة المشفرة"""
    conn = get_db()
    c = conn.cursor()
    
    # 1. جدول المستخدمين (Users & Quotas)
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        name TEXT,
        avatar TEXT,
        provider TEXT DEFAULT 'google',
        role TEXT DEFAULT 'user', -- 'owner' أو 'user'
        tier TEXT DEFAULT 'free', -- 'free', 'silver', 'gold', 'platinum', 'lifetime_vip'
        words_quota INTEGER DEFAULT 300,
        words_used INTEGER DEFAULT 0,
        is_lifetime INTEGER DEFAULT 0, -- 1 = اشتراك مجاني مدى الحياة
        is_active INTEGER DEFAULT 1,
        quota_exhausted_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    try:
        c.execute("ALTER TABLE users ADD COLUMN quota_exhausted_at TIMESTAMP")
    except Exception:
        pass

    # تحديث سقف الحسابات المجانية القائمة إلى 300 كلمة
    c.execute("""
    UPDATE users SET words_quota = 300 
    WHERE role != 'owner' AND is_lifetime = 0 AND tier = 'free' AND words_quota > 300
    """)
    conn.commit()

    # 2. جدول توثيق الجلسات والرموز المشفرة (Security Tokens & Sessions)
    c.execute("""
    CREATE TABLE IF NOT EXISTS auth_tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 3. جدول الكوبونات الآلية (Coupons & Promo Codes)
    c.execute("""
    CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        coupon_type TEXT NOT NULL, -- 'bonus_words', 'lifetime_vip', 'discount_percent'
        value INTEGER NOT NULL,
        max_uses INTEGER DEFAULT 100,
        used_count INTEGER DEFAULT 0,
        expires_at TIMESTAMP,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 4. جدول استرداد الكوبونات (Coupon Redemptions)
    c.execute("""
    CREATE TABLE IF NOT EXISTS coupon_redemptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coupon_id INTEGER,
        user_id INTEGER,
        redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(coupon_id) REFERENCES coupons(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 5. جدول الجلسات والأبحاث (Sessions)
    c.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        title TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 6. جدول سجل العمليات والتحويلات المشفرة (Audit Log & Transformations)
    c.execute("""
    CREATE TABLE IF NOT EXISTS transformations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        session_id TEXT,
        persona TEXT,
        mode TEXT,
        input_words INTEGER,
        output_words INTEGER,
        input_snippet TEXT,
        output_snippet TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 7. جدول طلبات الدفع والاشتراكات (Payments & Invoices)
    c.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan_name TEXT,
        amount_egp INTEGER,
        payment_method TEXT,
        receipt_ref TEXT,
        status TEXT DEFAULT 'approved',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 8. الخزنة المشفرة لجميع جلسات وفحوصات وتحويلات وتسجيلات العملاء (Encrypted Customer Vault)
    c.execute("""
    CREATE TABLE IF NOT EXISTS customer_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        event_type TEXT NOT NULL, -- 'registration', 'login', 'transformation', 'forensic_check'
        session_id TEXT,
        details_encrypted TEXT NOT NULL,
        integrity_hash TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # فهارس الأداء العالي لمنع أي بطء في قواعد البيانات الكبيرة
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(lower(email));")
    c.execute("CREATE INDEX IF NOT EXISTS idx_trans_user ON transformations(user_id, created_at);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_coupons_code ON coupons(code);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_auth_token ON auth_tokens(token);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_event_type ON customer_audit_events(event_type, created_at);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_id ON customer_audit_events(user_id, created_at);")

    conn.commit()
    conn.close()

# تهيئة تلقائية فور استدعاء الملف
init_db()

# ==============================================================================
# إدارة المستخدمين والرموز الأمنية (Auth & Session Tokens)
# ==============================================================================
def get_or_create_user(email: str, name: str = None, avatar: str = None, provider: str = "google", owner_email: str = None):
    conn = get_db()
    c = conn.cursor()
    
    email_clean = email.strip().lower()
    is_owner = False
    if owner_email and email_clean == owner_email.strip().lower():
        is_owner = True
        
    if not is_owner and security.is_disposable_email(email_clean):
        conn.close()
        raise ValueError("temp_mail_detected")
        
    c.execute("SELECT * FROM users WHERE lower(email) = ?", (email_clean,))
    row = c.fetchone()
    
    if row:
        user_id = row["id"]
        if is_owner and (row["role"] != "owner" or row["is_lifetime"] != 1):
            c.execute("""
            UPDATE users SET role = 'owner', is_lifetime = 1, tier = 'lifetime_vip', last_login = CURRENT_TIMESTAMP 
            WHERE id = ?
            """, (user_id,))
        else:
            c.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        conn.commit()
    else:
        role = "owner" if is_owner else "user"
        tier = "lifetime_vip" if is_owner else "free"
        quota = 999999999 if is_owner else 300
        is_life = 1 if is_owner else 0
        
        c.execute("""
        INSERT INTO users (email, name, avatar, provider, role, tier, words_quota, is_lifetime)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (email_clean, name or email_clean.split("@")[0], avatar or "", provider, role, tier, quota, is_life))
        user_id = c.lastrowid
        conn.commit()
        
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_data = dict(c.fetchone())
    conn.close()
    return user_data

def get_user_by_id(user_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_email(email: str):
    if not email:
        return None
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE lower(email) = ?", (email.strip().lower(),))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def create_auth_token(user_id: int, days_valid: int = 30) -> str:
    """إنشاء رمز أمني مشفر للمستخدم لمنع تزييف الحسابات"""
    conn = get_db()
    c = conn.cursor()
    token = secrets.token_hex(32)
    expires = datetime.datetime.now() + datetime.timedelta(days=days_valid)
    c.execute("""
    INSERT INTO auth_tokens (token, user_id, expires_at)
    VALUES (?, ?, ?)
    """, (token, user_id, expires.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return token

def get_user_by_token(token: str):
    """التحقق من صحة الرمز الأمني واسترجاع حساب المستخدم"""
    if not token:
        return None
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    SELECT u.* FROM users u
    JOIN auth_tokens t ON u.id = t.user_id
    WHERE t.token = ? AND datetime(t.expires_at) > datetime('now')
    """, (token.strip(),))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

# ==============================================================================
# دوال استهلاك الكلمات والتحقق من الباقة (Quota & Usage)
# ==============================================================================
def check_user_quota(user_id: int, incoming_words: int) -> dict:
    user = get_user_by_id(user_id)
    if not user:
        return {"allowed": False, "reason": "user_not_found", "message": "المستخدم غير مسجل بالنظام."}
    if not user["is_active"]:
        return {"allowed": False, "reason": "user_suspended", "message": "عفواً، هذا الحساب معلق مؤقتاً من قِبل إدارة المنظومة."}
    if user["role"] == "owner" or user["is_lifetime"]:
        return {"allowed": True, "remaining_words": "unlimited", "is_lifetime": True}

    remaining = user["words_quota"] - user["words_used"]
    is_free_trial = (user.get("tier") == "free" and not user.get("is_lifetime"))

    # 1. إذا استنفد المستخدم رصيده التجريبي بالكامل (300 كلمة)
    if remaining <= 0 or user["words_used"] >= user["words_quota"]:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not user.get("quota_exhausted_at"):
            conn = get_db()
            conn.execute("UPDATE users SET quota_exhausted_at = ? WHERE id = ?", (now_str, user_id))
            conn.commit()
            conn.close()

        if is_free_trial:
            return {
                "allowed": False,
                "reason": "free_trial_exhausted",
                "must_subscribe": True,
                "message": "عفواً، لقد استنفدت رصيدك التجريبي المجاني (300 كلمة). لإكمال صياغة بحوثك وأطروحاتك، يجب تفعيل الاشتراك في إحدى الخطط الأكاديمية.",
                "words_quota": user["words_quota"],
                "words_used": user["words_used"],
                "remaining_words": 0,
                "incoming_words": incoming_words
            }
        else:
            return {
                "allowed": False,
                "reason": "quota_exhausted",
                "must_subscribe": True,
                "message": f"عفواً، لقد استنفدت رصيد باقتك الحالية ({user['words_quota']:,} كلمة). يرجى الترقية أو تجديد الباقة لإكمال الصياغة.",
                "words_quota": user["words_quota"],
                "words_used": user["words_used"],
                "remaining_words": 0,
                "incoming_words": incoming_words
            }

    # 2. إذا كانت الكلمات المطلوبة أكبر من الرصيد المتبقي
    if incoming_words > remaining:
        if is_free_trial:
            return {
                "allowed": False,
                "reason": "insufficient_trial_quota",
                "must_subscribe": True,
                "message": f"عفواً، رصيدك التجريبي المتبقي ({remaining} كلمة) لا يكفي لصياغة النص المطلوب ({incoming_words} كلمة). يرجى الاشتراك في إحدى الباقات لرفع الرصيد أو تقليص النص.",
                "words_quota": user["words_quota"],
                "words_used": user["words_used"],
                "remaining_words": remaining,
                "incoming_words": incoming_words
            }
        else:
            return {
                "allowed": False,
                "reason": "insufficient_quota",
                "must_subscribe": True,
                "message": f"عفواً، رصيدك المتبقي ({remaining:,} كلمة) لا يكفي لصياغة النص المطلوب ({incoming_words:,} كلمة). يرجى شحن الرصيد.",
                "words_quota": user["words_quota"],
                "words_used": user["words_used"],
                "remaining_words": remaining,
                "incoming_words": incoming_words
            }

    return {
        "allowed": True,
        "words_quota": user["words_quota"],
        "words_used": user["words_used"],
        "remaining_words": remaining - incoming_words,
        "is_lifetime": False,
        "is_free_trial": is_free_trial,
        "trial_remaining": remaining - incoming_words if is_free_trial else None
    }

def log_customer_event(user_id: int, event_type: str, details: dict, session_id: str = None) -> int:
    """تسجيل نشاط العميل (تسجيل، فحص، تحويل) مشفراً تشفيراً عسكرياً كاملاً"""
    conn = get_db()
    c = conn.cursor()
    details_json = json.dumps(details, ensure_ascii=False)
    encrypted_payload = security.encrypt_text(details_json)
    integrity = security.hash_audit_signature(details_json)
    
    c.execute("""
    INSERT INTO customer_audit_events (user_id, event_type, session_id, details_encrypted, integrity_hash)
    VALUES (?, ?, ?, ?, ?)
    """, (user_id, event_type, session_id or secrets.token_hex(8), encrypted_payload, integrity))
    
    conn.commit()
    event_id = c.lastrowid
    conn.close()
    return event_id

def record_usage(user_id: int, input_words: int, output_words: int, persona: str, mode: str, input_snip: str, output_snip: str, session_id: str = None):
    conn = get_db()
    c = conn.cursor()
    
    user = get_user_by_id(user_id)
    if not user:
        conn.close()
        return None
        
    words_consumed = input_words  # يتم خصم عدد كلمات النص المدخل من الرصيد
    
    if user["role"] != "owner" and not user["is_lifetime"]:
        new_used = user["words_used"] + words_consumed
        if new_used >= user["words_quota"]:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""
            UPDATE users SET words_used = ?, quota_exhausted_at = ? WHERE id = ?
            """, (new_used, now_str, user_id))
        else:
            c.execute("""
            UPDATE users SET words_used = ? WHERE id = ?
            """, (new_used, user_id))
        
    # تشفير البيانات عسكرياً قبل كتابتها على القرص الصلب (Zero Plaintext at Rest)
    enc_input = security.encrypt_text(input_snip)
    enc_output = security.encrypt_text(output_snip)
    sess_id = session_id or secrets.token_hex(8)

    c.execute("""
    INSERT INTO transformations (user_id, session_id, persona, mode, input_words, output_words, input_snippet, output_snippet)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, sess_id, persona, mode, input_words, output_words, enc_input, enc_output))
    
    conn.commit()
    conn.close()

    # تسجيل في الخزنة الأمنية كحدث تحويل أسلوب فكري مشفر
    log_customer_event(
        user_id=user_id,
        event_type="transformation",
        details={
            "persona": persona,
            "mode": mode,
            "input_words": input_words,
            "output_words": output_words,
            "input_text": input_snip,
            "output_text": output_snip
        },
        session_id=sess_id
    )

    return get_user_by_id(user_id)

def get_user_history(user_id: int, limit: int = 25):
    """جلب سجل العمليات السابقة الخاصة بالباحث فقط مع فك تشفيرها له بحكم ملكيته لحسابه"""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    SELECT id, persona, mode, input_words, output_words, input_snippet, output_snippet, created_at
    FROM transformations
    WHERE user_id = ?
    ORDER BY created_at DESC LIMIT ?
    """, (user_id, limit))
    rows = []
    for r in c.fetchall():
        d = dict(r)
        d["input_snippet"] = security.decrypt_text(d.get("input_snippet", ""))
        d["output_snippet"] = security.decrypt_text(d.get("output_snippet", ""))
        rows.append(d)
    conn.close()
    return rows

# ==============================================================================
# صلاحيات المالك: شحن الرصيد ومنح اشتراك مدى الحياة (Owner Actions)
# ==============================================================================
def grant_lifetime_vip(user_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    UPDATE users SET is_lifetime = 1, tier = 'lifetime_vip', words_quota = 999999999 WHERE id = ?
    """, (user_id,))
    conn.commit()
    conn.close()
    return get_user_by_id(user_id)

def add_user_words(user_id: int, words_to_add: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    UPDATE users SET words_quota = words_quota + ? WHERE id = ?
    """, (words_to_add, user_id))
    conn.commit()
    conn.close()
    return get_user_by_id(user_id)

def toggle_user_active(user_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return get_user_by_id(user_id)

# ==============================================================================
# مولد ومحرك الكوبونات الآلية (Coupon Engine)
# ==============================================================================
def create_coupon(code: str = None, coupon_type: str = "bonus_words", value: int = 50000, max_uses: int = 50, days_valid: int = 30):
    conn = get_db()
    c = conn.cursor()
    
    if not code:
        code = "ACADEMIC-" + secrets.token_hex(3).upper()
    else:
        code = code.strip().upper()
        
    expires_at = datetime.datetime.now() + datetime.timedelta(days=days_valid)
    
    try:
        c.execute("""
        INSERT INTO coupons (code, coupon_type, value, max_uses, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """, (code, coupon_type, value, max_uses, expires_at.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        coupon_id = c.lastrowid
        c.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
        res = dict(c.fetchone())
        conn.close()
        return res
    except sqlite3.IntegrityError:
        c.execute("SELECT * FROM coupons WHERE code = ?", (code,))
        res = dict(c.fetchone())
        conn.close()
        return res

def redeem_coupon(user_id: int, code: str) -> dict:
    conn = get_db()
    c = conn.cursor()
    
    code_clean = code.strip().upper()
    c.execute("SELECT * FROM coupons WHERE code = ? AND is_active = 1", (code_clean,))
    coupon = c.fetchone()
    
    if not coupon:
        conn.close()
        return {"success": False, "message": "كود الخصم غير صحيح أو غير مفعّل!"}
        
    if coupon["used_count"] >= coupon["max_uses"]:
        conn.close()
        return {"success": False, "message": "عفواً، لقد اكتمل الحد الأقصى لاستخدام هذا الكوبون!"}
        
    c.execute("SELECT * FROM coupon_redemptions WHERE coupon_id = ? AND user_id = ?", (coupon["id"], user_id))
    if c.fetchone():
        conn.close()
        return {"success": False, "message": "لقد قمت باستخدام هذا الكوبون بالفعل سابقاً!"}
        
    ctype = coupon["coupon_type"]
    val = coupon["value"]
    
    if ctype == "lifetime_vip":
        c.execute("UPDATE users SET is_lifetime = 1, tier = 'lifetime_vip', words_quota = 999999999 WHERE id = ?", (user_id,))
        reward_msg = "تهانينا! تم تفعيل اشتراك VIP مجاني مدى الحياة بحسابك!"
    elif ctype == "bonus_words":
        c.execute("UPDATE users SET words_quota = words_quota + ? WHERE id = ?", (val, user_id))
        reward_msg = f"تمت إضافة {val:,} كلمة جديدة إلى رصيدك بنجاح!"
    else:
        reward_msg = f"تم تفعيل خصم بقيمة {val}% على باقاتك القادمة!"
        
    c.execute("INSERT INTO coupon_redemptions (coupon_id, user_id) VALUES (?, ?)", (coupon["id"], user_id))
    c.execute("UPDATE coupons SET used_count = used_count + 1 WHERE id = ?", (coupon["id"],))
    
    conn.commit()
    conn.close()
    return {"success": True, "message": reward_msg, "updated_user": get_user_by_id(user_id)}

def create_payment_request(user_id: int, plan_name: str, amount_egp: int, payment_method: str, receipt_ref: str):
    """تسجيل طلب اشتراك جديد وشحن الرصيد المخصص للباقة مباشرة"""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    INSERT INTO payments (user_id, plan_name, amount_egp, payment_method, receipt_ref, status)
    VALUES (?, ?, ?, ?, ?, 'approved')
    """, (user_id, plan_name, amount_egp, payment_method, receipt_ref))
    payment_id = c.lastrowid
    
    PLAN_WORDS = {
        "باقة الباحث المستجد": 50000,
        "باقة الماجستير المحكمة": 150000,
        "باقة الدكتوراه الأكاديمية": 400000,
        "باقة الأستاذية غير المحدودة": 999999999
    }
    PLAN_TIERS = {
        "باقة الباحث المستجد": "silver",
        "باقة الماجستير المحكمة": "gold",
        "باقة الدكتوراه الأكاديمية": "platinum",
        "باقة الأستاذية غير المحدودة": "lifetime_vip"
    }
    words_to_add = PLAN_WORDS.get(plan_name, 50000)
    tier = PLAN_TIERS.get(plan_name, "silver")
    is_vip = 1 if tier == "lifetime_vip" else 0
    
    c.execute("""
    UPDATE users 
    SET words_quota = words_quota + ?, tier = ?, is_lifetime = CASE WHEN ? = 1 THEN 1 ELSE is_lifetime END,
        quota_exhausted_at = NULL
    WHERE id = ?
    """, (words_to_add, tier, is_vip, user_id))
    
    conn.commit()
    conn.close()
    
    log_customer_event(
        user_id=user_id,
        event_type="subscription_activated",
        details={
            "plan_name": plan_name,
            "amount_egp": amount_egp,
            "payment_method": payment_method,
            "receipt_ref": receipt_ref,
            "words_added": words_to_add,
            "payment_id": payment_id
        }
    )
    return get_user_by_id(user_id)

# ==============================================================================
# إحصاءات وتصدير بيانات لوحة تحكم المالك (Owner Analytics & CSV Exporters)
# ==============================================================================
def get_owner_stats():
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) as total_users FROM users")
    total_users = c.fetchone()["total_users"]
    
    c.execute("SELECT COUNT(*) as vip_users FROM users WHERE is_lifetime = 1")
    vip_users = c.fetchone()["vip_users"]
    
    c.execute("SELECT SUM(words_used) as total_words_consumed FROM users")
    words_consumed = c.fetchone()["total_words_consumed"] or 0
    
    c.execute("SELECT COUNT(*) as total_transformations FROM transformations")
    total_trans = c.fetchone()["total_transformations"]
    
    c.execute("SELECT COUNT(*) as active_coupons FROM coupons WHERE is_active = 1")
    active_coupons = c.fetchone()["active_coupons"]

    c.execute("SELECT COUNT(*) as temp_mail_blocked FROM customer_audit_events WHERE event_type = 'temp_mail_blocked'")
    temp_mail_count = c.fetchone()["temp_mail_blocked"]
    
    conn.close()
    return {
        "total_users": total_users,
        "vip_users": vip_users,
        "total_words_consumed": words_consumed,
        "total_transformations": total_trans,
        "active_coupons": active_coupons,
        "temp_mail_blocked": temp_mail_count
    }

def get_all_users(limit: int = 200):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_all_coupons():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM coupons ORDER BY created_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_audit_logs(limit: int = 100):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    SELECT t.*, u.email, u.name 
    FROM transformations t
    LEFT JOIN users u ON t.user_id = u.id
    ORDER BY t.created_at DESC LIMIT ?
    """, (limit,))
    rows = []
    for r in c.fetchall():
        d = dict(r)
        d["input_snippet"] = security.decrypt_text(d.get("input_snippet", ""))
        d["output_snippet"] = security.decrypt_text(d.get("output_snippet", ""))
        d["is_encrypted"] = True
        rows.append(d)
    conn.close()
    return rows

def get_customer_vault_records(owner_user_id: int, event_filter: str = None, limit: int = 150) -> list:
    """استرجاع سجلات وجلسات العملاء المشفرة مفكوكة الشفرة حصرياً للمالك السيادي"""
    owner = get_user_by_id(owner_user_id)
    if not owner or owner["role"] != "owner":
        raise PermissionError("Access Denied: Only Sovereign Owner can inspect customer vault records.")

    conn = get_db()
    c = conn.cursor()
    
    if event_filter and event_filter != "all":
        c.execute("""
        SELECT e.id, e.user_id, e.event_type, e.session_id, e.details_encrypted, e.integrity_hash, e.created_at,
               u.email, u.name, u.role, u.tier, u.words_used, u.words_quota
        FROM customer_audit_events e
        LEFT JOIN users u ON e.user_id = u.id
        WHERE e.event_type = ?
        ORDER BY e.created_at DESC LIMIT ?
        """, (event_filter, limit))
    else:
        c.execute("""
        SELECT e.id, e.user_id, e.event_type, e.session_id, e.details_encrypted, e.integrity_hash, e.created_at,
               u.email, u.name, u.role, u.tier, u.words_used, u.words_quota
        FROM customer_audit_events e
        LEFT JOIN users u ON e.user_id = u.id
        ORDER BY e.created_at DESC LIMIT ?
        """, (limit,))

    records = []
    for row in c.fetchall():
        r = dict(row)
        raw_cipher = r.pop("details_encrypted", "")
        decrypted_str = security.decrypt_text(raw_cipher)
        try:
            details = json.loads(decrypted_str) if decrypted_str else {}
        except Exception:
            details = {"raw": decrypted_str}
        r["details"] = details
        r["is_encrypted_at_rest"] = True
        r["encryption_algorithm"] = "AES-256-Fernet-Military"
        records.append(r)

    conn.close()
    return records

def export_users_csv() -> str:
    """تصدير قائمة المستخدمين بتقرير CSV محاسبي للمالك"""
    users = get_all_users(1000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Email", "Name", "Role", "Tier", "Words Quota", "Words Used", "Is Lifetime", "Is Active", "Registered At", "Last Login"])
    for u in users:
        writer.writerow([
            u["id"], u["email"], u["name"], u["role"], u["tier"],
            u["words_quota"], u["words_used"], u["is_lifetime"],
            u["is_active"], u["created_at"], u["last_login"]
        ])
    return output.getvalue()
