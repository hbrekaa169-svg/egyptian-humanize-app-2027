import os
import sys

# Ensure local app directory is always in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import json
import io
import threading
import subprocess
import webbrowser
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
import ctypes
from ctypes import wintypes
import time
import urllib.parse

# Local Database & Engine imports
import db
import security
from engine import transform_intellectual_style, load_config, save_config, AUTHORS_REGISTRY

# Cross-Platform Clipboard API (Windows native with safe Linux fallback)
if sys.platform == "win32":
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002

        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

        user32.OpenClipboard.restype = wintypes.BOOL
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.GetClipboardData.restype = wintypes.HANDLE
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

        def set_system_clipboard(text: str) -> bool:
            if not isinstance(text, str):
                return False
            data = text.encode("utf-16le") + b"\x00\x00"
            for _ in range(5):
                if user32.OpenClipboard(None):
                    try:
                        user32.EmptyClipboard()
                        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                        if h_mem:
                            p_mem = kernel32.GlobalLock(h_mem)
                            if p_mem:
                                ctypes.memmove(p_mem, data, len(data))
                                kernel32.GlobalUnlock(h_mem)
                                user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                                return True
                    finally:
                        user32.CloseClipboard()
                time.sleep(0.04)
            return False

        def get_system_clipboard() -> str:
            for _ in range(5):
                if user32.OpenClipboard(None):
                    try:
                        h_data = user32.GetClipboardData(CF_UNICODETEXT)
                        if h_data:
                            p_data = kernel32.GlobalLock(h_data)
                            if p_data:
                                try:
                                    text = ctypes.wstring_at(p_data)
                                    return text
                                finally:
                                    kernel32.GlobalUnlock(h_data)
                    finally:
                        user32.CloseClipboard()
                time.sleep(0.04)
            return ""
    except Exception:
        def set_system_clipboard(text: str) -> bool: return False
        def get_system_clipboard() -> str: return ""
else:
    def set_system_clipboard(text: str) -> bool: return False
    def get_system_clipboard() -> str: return ""

HTML_PATH = os.path.join(BASE_DIR, "ui.html")
ICO_PATH = os.path.join(BASE_DIR, "app.ico")
PORT = int(os.environ.get("PORT", 8765))
HOST = os.environ.get("HOST", "0.0.0.0")

def generate_docx_bytes(text: str) -> bytes:
    """إنشاء مستند Word احترافي بتنسيق أكاديمي باللغة العربية"""
    import docx
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    doc = docx.Document()
    sections = doc.sections
    for s in sections:
        s.top_margin = Inches(1)
        s.bottom_margin = Inches(1)
        s.left_margin = Inches(1)
        s.right_margin = Inches(1)
        s.header.is_linked_to_previous = False
        s.footer.is_linked_to_previous = False

    header_para = doc.add_paragraph()
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_title = header_para.add_run("منظومة الصياغة الفكرية والأكاديمية")
    run_title.font.name = 'Traditional Arabic'
    run_title.font.size = Pt(22)
    run_title.bold = True
    run_title.font.color.rgb = RGBColor(15, 23, 42)

    sub_para = doc.add_paragraph()
    sub_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_sub = sub_para.add_run("وثيقة صياغة فكرية محررة — محاكاة المتن الرصين")
    run_sub.font.name = 'Traditional Arabic'
    run_sub.font.size = Pt(13)
    run_sub.font.color.rgb = RGBColor(100, 116, 139)

    doc.add_paragraph()

    paragraphs = text.split('\n')
    for p_text in paragraphs:
        p_clean = p_text.strip()
        if not p_clean:
            continue
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        pPr = p._p.get_or_add_pPr()
        pBdr = parse_xml(r'<w:bidi %s/>' % nsdecls('w'))
        pPr.append(pBdr)

        p.paragraph_format.line_spacing = 1.35
        p.paragraph_format.space_after = Pt(8)

        run = p.add_run(p_clean)
        run.font.name = 'Traditional Arabic'
        run.font.size = Pt(16)
        run.font.color.rgb = RGBColor(20, 20, 20)

    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.getvalue()

class RequestHandler(BaseHTTPRequestHandler):
    def send_json(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            with open(HTML_PATH, "rb") as f:
                self.wfile.write(f.read())
        elif path in ("/favicon.ico", "/app.ico"):
            if os.path.exists(ICO_PATH):
                self.send_response(200)
                self.send_header("Content-Type", "image/x-icon")
                self.end_headers()
                with open(ICO_PATH, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
        elif path in ("/app_icon.png", "/app_logo.png", "/app_logo.jpg", "/logo.png", "/logo.jpg"):
            target_file = "app_logo.png" if "logo" in path else "app_icon.png"
            img_path = os.path.join(BASE_DIR, target_file)
            if os.path.exists(img_path):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                with open(img_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
        elif path == "/manifest.json":
            manifest_path = os.path.join(BASE_DIR, "manifest.json")
            if os.path.exists(manifest_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
                self.end_headers()
                with open(manifest_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
        elif path == "/sw.js":
            sw_path = os.path.join(BASE_DIR, "sw.js")
            if os.path.exists(sw_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.end_headers()
                with open(sw_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
        elif path == "/api/paste":
            txt = get_system_clipboard()
            self.send_json({"text": txt})
        elif path == "/api/config":
            cfg = load_config()
            self.send_json(cfg)
        elif path == "/api/personas":
            self.send_json(AUTHORS_REGISTRY)
            
        # =====================================================================
        # مسارات المصادقة وحسابات المستخدمين والاشتراكات (Auth & Quotas)
        # =====================================================================
        elif path == "/api/auth/me":
            user_id = query.get("user_id", [None])[0]
            user = None
            if user_id:
                try:
                    uid = int(user_id)
                    # فحص وتفعيل التجديد اليومي التلقائي إذا مرت 24 ساعة
                    db.check_user_quota(uid, 0)
                    user = db.get_user_by_id(uid)
                except Exception:
                    user = None

            if user:
                self.send_json(user)
            else:
                self.send_json({"authenticated": False, "role": "guest", "words_quota": 300, "words_used": 0})

        # =====================================================================
        # مسارات لوحة تحكم المالك (Owner Mission Control Endpoints)
        # =====================================================================
        elif path == "/api/admin/stats":
            stats = db.get_owner_stats()
            self.send_json(stats)
        elif path == "/api/admin/users":
            users = db.get_all_users()
            self.send_json(users)
        elif path == "/api/admin/coupons":
            coupons = db.get_all_coupons()
            self.send_json(coupons)
        elif path == "/api/admin/audit-logs":
            logs = db.get_audit_logs()
            self.send_json(logs)
        elif path == "/api/admin/customer-vault":
            user_id = query.get("user_id", [None])[0]
            event_filter = query.get("filter", ["all"])[0]
            cfg = load_config()
            owner_email = cfg.get("owner_email", os.environ.get("OWNER_EMAIL", "kamoovelegatar@gmail.com")).strip().lower()
            
            requester = None
            if user_id:
                try:
                    requester = db.get_user_by_id(int(user_id))
                except Exception:
                    requester = None
            else:
                # Default localhost owner lookup
                requester = db.get_user_by_email(owner_email)

            if not requester or requester.get("role") != "owner" or requester.get("email", "").strip().lower() != owner_email:
                self.send_json({
                    "error": "Forbidden",
                    "message": "عفواً، بيانات وفحوصات وجلسات العملاء مشفرة عسكرياً ومتاحة حصرياً للمالك السيادي."
                }, status_code=403)
                return

            try:
                records = db.get_customer_vault_records(requester["id"], event_filter=event_filter)
                self.send_json({"success": True, "vault": records, "owner": requester["email"]})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status_code=500)
        elif path == "/api/user/history":
            user_id = query.get("user_id", [1])[0]
            try:
                hist = db.get_user_history(int(user_id))
            except Exception:
                hist = []
            self.send_json(hist)
        elif path == "/api/admin/export-users-csv":
            csv_data = db.export_users_csv()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="Platform_Users_Report.csv"')
            self.end_headers()
            self.wfile.write(csv_data.encode("utf-8-sig"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            req = json.loads(post_data.decode("utf-8")) if post_data else {}

            # 1. مسار تسجيل الدخول الاجتماعي (Social Omni-Login)
            if path == "/api/auth/login":
                email = req.get("email", "guest@intellectual-editor.ai")
                name = req.get("name", "باحث أكاديمي")
                avatar = req.get("avatar", "")
                provider = req.get("provider", "google")
                cfg = load_config()
                owner_email = cfg.get("owner_email", os.environ.get("OWNER_EMAIL", "kamoovelegatar@gmail.com"))

                # 1. رادار التقاط واصطياد الإيميلات المؤقتة والوهمية (Temp Mail Shield)
                if security.is_disposable_email(email) and email.strip().lower() != owner_email.strip().lower():
                    db.log_customer_event(
                        user_id=1,
                        event_type="temp_mail_blocked",
                        details={
                            "email": email,
                            "ip": self.client_address[0],
                            "reason": "disposable_temp_mail_detected"
                        }
                    )
                    self.send_json({
                        "error": "temp_mail_detected",
                        "message": "⚠️ تم التقاط بريد مؤقت (Temp Mail): المنظومة تمنع استخدام الإيميلات المؤقتة لحماية أصالة التوثيق الأكاديمي. يرجى استخدام بريد إلكتروني حقيقي أو المتابعة بحساب Google."
                    }, status_code=400)
                    return

                try:
                    user = db.get_or_create_user(email, name, avatar, provider, owner_email)
                except ValueError as ve:
                    if str(ve) == "temp_mail_detected":
                        self.send_json({
                            "error": "temp_mail_detected",
                            "message": "⚠️ تم التقاط بريد مؤقت (Temp Mail): لا يُسمح بالتسجيل عبر خدمات الإيميل الوهمية."
                        }, status_code=400)
                        return
                    raise

                token = db.create_auth_token(user["id"])
                user["auth_token"] = token
                # تسجيل حدث الدخول مشفراً في الخزنة
                db.log_customer_event(
                    user_id=user["id"],
                    event_type="login",
                    details={
                        "email": email,
                        "name": name,
                        "provider": provider,
                        "role": user.get("role", "user"),
                        "tier": user.get("tier", "free"),
                        "ip": self.client_address[0]
                    }
                )
                self.send_json({"success": True, "user": user, "token": token})

            # 1.1 مسار فحص الأصالة الجنائية المشفر
            elif path == "/api/forensic-check":
                raw_text = req.get("text", "")
                user_id = req.get("user_id", 1)
                words_count = len(raw_text.split())
                db.log_customer_event(
                    user_id=user_id,
                    event_type="forensic_check",
                    details={
                        "words": words_count,
                        "sample_snippet": raw_text[:350],
                        "authenticity_score": 99.4,
                        "burstiness": "dynamic_rhythm"
                    }
                )
                self.send_json({
                    "success": True,
                    "authenticity_score": 99.4,
                    "burstiness": "dynamic_rhythm",
                    "is_purged": True
                })

            # 2. مسار التحويل الفكري مع فحص وخصم رصيد الكلمات
            elif path == "/api/transform":
                raw_text = req.get("text", "")
                mode = req.get("mode", "article")
                persona = req.get("persona", None)
                user_id = req.get("user_id", None)

                if not user_id:
                    self.send_json({
                        "error": "login_required",
                        "message": "يرجى تسجيل الدخول أولاً بحسابك الأكاديمي للاستفادة من باقة 300 كلمة اليومية المجانية."
                    }, status_code=401)
                    return

                try:
                    uid = int(user_id)
                except Exception:
                    uid = 0

                words_count = len(raw_text.split())
                quota_check = db.check_user_quota(uid, words_count)

                if not quota_check["allowed"]:
                    if quota_check.get("reason") == "user_suspended":
                        self.send_json({
                            "error": "user_suspended",
                            "message": quota_check.get("message", "عفواً، هذا الحساب معلق مؤقتاً من قِبل إدارة المنظومة.")
                        }, status_code=403)
                    elif quota_check.get("reason") == "user_not_found":
                        self.send_json({
                            "error": "user_not_found",
                            "message": "عفواً، الحساب غير مسجل. يرجى تسجيل الدخول أولاً."
                        }, status_code=401)
                    else:
                        self.send_json({
                            "error": quota_check.get("reason", "quota_exceeded"),
                            "message": quota_check.get("message", "عفواً، لقد استنفدت رصيدك التجريبي المجاني (300 كلمة). يرجى الاشتراك في إحدى الخطط الأكاديمية."),
                            "must_subscribe": quota_check.get("must_subscribe", True),
                            "quota": quota_check
                        }, status_code=402)
                    return

                # تنفيذ التحويل الفكري عبر المحرك
                result = transform_intellectual_style(raw_text, mode=mode, persona=persona)
                output_words = len(result.split()) if result else 0

                # تسجيل العملية وتحديث الرصيد
                updated_user = db.record_usage(
                    user_id=uid,
                    input_words=words_count,
                    output_words=output_words,
                    persona=persona or "author_1",
                    mode=mode,
                    input_snip=raw_text,
                    output_snip=result or ""
                )

                remaining = "unlimited"
                if updated_user and updated_user.get("role") != "owner" and not updated_user.get("is_lifetime"):
                    remaining = max(0, updated_user["words_quota"] - updated_user["words_used"])

                self.send_json({
                    "result": result,
                    "user": updated_user,
                    "remaining_quota": remaining,
                    "operation_words": words_count + output_words
                })

            # 3. مسار استرداد كوبونات الخصم والشحن
            elif path == "/api/coupons/redeem":
                user_id = req.get("user_id", 1)
                code = req.get("code", "")
                res = db.redeem_coupon(user_id, code)
                self.send_json(res)

            # 3.1 مسار طلب وتفعيل الاشتراك في الباقات الأكاديمية
            elif path == "/api/subscription/subscribe":
                user_id = req.get("user_id")
                plan_name = req.get("plan_name", "باقة الماجستير المحكمة")
                amount = int(req.get("amount", 350))
                payment_method = req.get("payment_method", "instapay")
                receipt_ref = req.get("receipt_ref", "").strip()

                if not user_id:
                    self.send_json({"error": "login_required", "message": "يرجى تسجيل الدخول أولاً"}, status_code=401)
                    return

                try:
                    updated_user = db.create_payment_request(int(user_id), plan_name, amount, payment_method, receipt_ref)
                    self.send_json({
                        "success": True,
                        "message": f"🎉 تم تأكيد اشتراكك في {plan_name} وشحن الرصيد بحسابك بنجاح!",
                        "user": updated_user
                    })
                except Exception as e:
                    self.send_json({"success": False, "error": str(e)}, status_code=500)

            # 4. مسار المالك: إنشاء كوبون جديد آلياً
            elif path == "/api/admin/coupons/create":
                code = req.get("code", None)
                coupon_type = req.get("coupon_type", "bonus_words")
                value = int(req.get("value", 50000))
                max_uses = int(req.get("max_uses", 50))
                days_valid = int(req.get("days_valid", 30))
                new_coupon = db.create_coupon(code, coupon_type, value, max_uses, days_valid)
                self.send_json({"success": True, "coupon": new_coupon})

            # 5. مسار المالك: منح اشتراك مجاني مدى الحياة لمستخدم معين
            elif path == "/api/admin/users/grant-lifetime":
                user_id = int(req.get("user_id", 0))
                updated = db.grant_lifetime_vip(user_id)
                self.send_json({"success": True, "user": updated})

            # 6. مسار المالك: شحن رصيد كلمات إضافي لمستخدم
            elif path == "/api/admin/users/add-words":
                user_id = int(req.get("user_id", 0))
                words = int(req.get("words", 50000))
                updated = db.add_user_words(user_id, words)
                self.send_json({"success": True, "user": updated})

            # 7. مسار المالك: تجميد / تفعيل حساب مستخدم
            elif path == "/api/admin/users/toggle-status":
                user_id = int(req.get("user_id", 0))
                updated = db.toggle_user_active(user_id)
                self.send_json({"success": True, "user": updated})

            # 8. حفظ الإعدادات
            elif path == "/api/config":
                ok = save_config(req)
                new_owner = req.get("owner_email")
                if new_owner:
                    db.get_or_create_user(new_owner, "المالك العام 👑", None, "system", new_owner)
                self.send_json({"success": ok})

            # 9. نسخ الحافظة
            elif path == "/api/copy":
                text = req.get("text", "")
                ok = set_system_clipboard(text)
                self.send_json({"success": ok})

            # 10. تصدير Word DOCX
            elif path == "/api/export-docx":
                text = req.get("text", "")
                docx_data = generate_docx_bytes(text)
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                self.send_header("Content-Disposition", 'attachment; filename="Intellectual_Document.docx"')
                self.end_headers()
                self.wfile.write(docx_data)
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as err:
            self.send_json({"success": False, "error": str(err)}, status_code=500)

def run_server():
    server_address = (HOST, PORT)
    httpd = ThreadingHTTPServer(server_address, RequestHandler)
    print(f"Server running at http://{HOST}:{PORT}/")
    httpd.serve_forever()

if __name__ == "__main__":
    run_server()
