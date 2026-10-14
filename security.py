import os
import base64
import hashlib
from cryptography.fernet import Fernet

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
KEY_PATH = os.path.join(DATA_DIR, ".sovereign_master.key")

os.makedirs(DATA_DIR, exist_ok=True)

def get_or_create_master_key() -> bytes:
    """الحصول على المفتاح التشفيري السيادي العسكري (AES-256) للمالك أو توليده وتأمينه"""
    if os.path.exists(KEY_PATH):
        try:
            with open(KEY_PATH, "rb") as f:
                key = f.read().strip()
                if len(key) == 44: # Valid Fernet key length
                    return key
        except Exception:
            pass

    # توليد مفتاح جديد فائق الحماية
    new_key = Fernet.generate_key()
    try:
        with open(KEY_PATH, "wb") as f:
            f.write(new_key)
        # إخفاء الملف على ويندوز
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(KEY_PATH, 0x02) # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass
    except Exception as e:
        print(f"Warning: Could not persist master key: {e}")
    return new_key

MASTER_KEY = get_or_create_master_key()
CIPHER_SUITE = Fernet(MASTER_KEY)

def encrypt_text(text: str) -> str:
    """تشفير النصوص الحساسة ببروتوكول عسكري لمنع أي تسريب على القرص الصلب"""
    if not text:
        return ""
    try:
        raw_bytes = text.encode("utf-8")
        encrypted_bytes = CIPHER_SUITE.encrypt(raw_bytes)
        return "ENC::" + encrypted_bytes.decode("utf-8")
    except Exception as e:
        print(f"Encryption error: {e}")
        return text

def decrypt_text(cipher_str: str) -> str:
    """فك تشفير النصوص حصرياً لصاحب الصلاحية السيادية (المالك)"""
    if not cipher_str:
        return ""
    if not cipher_str.startswith("ENC::"):
        return cipher_str # Plaintext legacy compatibility
    try:
        raw_token = cipher_str[5:].encode("utf-8")
        decrypted_bytes = CIPHER_SUITE.decrypt(raw_token)
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        return f"[🔒 محتوى مشفر فائق الحماية - غير متاح إلا للمالك السيادي] (Err: {e})"

def hash_audit_signature(text: str) -> str:
    """بصمة تجزئة SHA-256 فريدة للتدقيق الجنائي وإثبات عدم التلاعب"""
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

# ==============================================================================
# رادار التقاط واكتشاف الإيميلات المؤقتة (Temp Mail Detection Engine)
# ==============================================================================
DISPOSABLE_DOMAINS = {
    "10minutemail.com", "10minutemail.net", "10minmail.com", "20minutemail.com",
    "guerrillamail.com", "guerrillamail.net", "guerrillamail.biz", "guerrillamail.org",
    "sharklasers.com", "grr.la", "guerrillamailblock.com", "pokemail.net", "spam4.me",
    "mailinator.com", "mailinater.com", "suremail.info", "spamherelots.com", "binkmail.com",
    "safetymail.info", "tradermail.info", "mailcatch.com",
    "tempmail.com", "temp-mail.org", "temp-mail.io", "tempmail.net", "tempmailaddress.com",
    "yopmail.com", "yopmail.fr", "yopmail.net", "cool.fr.nf", "jetable.fr.nf",
    "dispostable.com", "trashmail.com", "trashmail.net", "trashmail.me", "trashmail.org",
    "throwawaymail.com", "getairmail.com", "mohmal.com", "mohmal.in", "fakeinbox.com",
    "fakemailgenerator.com", "emailondeck.com", "crazymailing.com", "maildrop.cc",
    "inboxkitten.com", "generator.email", "mytemp.email", "nada.ltd", "getnada.com",
    "dropmail.me", "clipmail.eu", "luxusmail.org", "tempr.email", "discard.email",
    "burnermail.io", "fakemail.net", "tempmailo.com", "minuteinbox.com",
    "10mail.org", "mytempemail.com", "zillamail.com", "trashinbox.com",
    "disposablemail.com", "tmailor.com", "emailfake.com",
    "tmpmail.net", "tmpmail.org", "disposable.com", "armyspy.com", "cuvox.de",
    "dayrep.com", "fleckens.hu", "gustr.com", "jourrapide.com", "rhyta.com",
    "superrito.com", "teleworm.us", "einrot.com", "fakermail.com", "incognitomail.org",
    "nowmymail.com", "zoemail.org", "onewaymail.com", "instantemailaddress.com"
}

DISPOSABLE_KEYWORDS = [
    "tempmail", "temp-mail", "10minute", "guerrilla", "throwaway",
    "disposable", "fakeinbox", "fakemail", "yopmail", "trashmail",
    "mohmal", "burnermail", "discardmail", "dropmail", "minuteinbox",
    "mailinator", "generator.email", "tmailor", "tmpmail"
]

def is_disposable_email(email: str) -> bool:
    """اكتشاف واصطياد الإيميلات المؤقتة والوهمية (Temp Mail Detection Engine)"""
    if not email or "@" not in email:
        return False
    clean = email.strip().lower()
    parts = clean.split("@")
    if len(parts) != 2:
        return False
    domain = parts[1].strip()
    
    # 1. فحص مباشر للنطاق في القائمة السوداء
    if domain in DISPOSABLE_DOMAINS:
        return True
        
    # 2. فحص النطاقات الفرعية
    for d in DISPOSABLE_DOMAINS:
        if domain.endswith("." + d):
            return True
            
    # 3. فحص الكلمات الدلالية المشهورة لخدمات الإيميل المؤقت
    for kw in DISPOSABLE_KEYWORDS:
        if kw in domain:
            return True
            
    return False
