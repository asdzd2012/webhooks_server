"""
Facebook Webhooks Server with Web Dashboard
============================================
سيرفر للرد التلقائي على التعليقات والرسائل
مع واجهة ويب لإدارة الصفحات والقوالب
"""

from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session
import requests
import os
import json
import random
import re
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-change-this")

# ============ الإعدادات ============
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_fb_webhook_verify_2024")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "0452218374")

# البيانات (ستُحفظ في ملفات JSON)
DATA_FILE = "data.json"
HISTORY_FILE = "history.json"

data = {
    "pages": [],  # [{"id": "...", "name": "...", "token": "..."}]
    "comment_templates": [],
    "message_templates": [],
    "settings": {
        "auto_reply_comments": True,
        "auto_reply_messages": True,
        "send_private_reply": True
    }
}
history = []
processed_comments = set()

# ============ تحميل وحفظ البيانات ============
def load_data():
    global data, history, processed_comments
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        save_data()
    
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
            processed_comments = set(h.get("comment_id", "") for h in history)
    except:
        history = []

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_history():
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        # Keep last 1000 entries
        json.dump(history[-1000:], f, ensure_ascii=False, indent=2)

PROCESSED_FILE = "processed.json"

def load_processed():
    global processed_comments
    try:
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            processed_comments = set(json.load(f))
    except:
        processed_comments = set()

def save_processed():
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        # Keep last 500 only to prevent file from growing too large
        comments_list = list(processed_comments)[-500:]
        json.dump(comments_list, f)

def add_history(page_name, action, status, details=""):
    history.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "page": page_name,
        "action": action,
        "status": status,
        "details": details,
        "comment_id": details if "comment" in action.lower() else ""
    })
    save_history()

# ============ المصادقة ============
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# ============ Spintax ============
def process_spintax(text):
    pattern = r'\{([^{}]+)\}'
    def replace(match):
        options = match.group(1).split('|')
        return random.choice(options)
    while re.search(pattern, text):
        text = re.sub(pattern, replace, text, count=1)
    return text

# ============ الرد على التعليقات ============
def get_page_token(page_id):
    for page in data.get("pages", []):
        if page["id"] == page_id:
            return page.get("token"), page.get("name", "Unknown")
    return None, None

def reply_to_comment(comment_id, page_id, user_name):
    # Check if already processed FIRST to prevent duplicates
    if comment_id in processed_comments:
        print(f"⏭️ تعليق معالج مسبقاً: {comment_id}")
        return False
    
    # Add to processed IMMEDIATELY to prevent duplicates from webhook retries
    processed_comments.add(comment_id)
    save_processed()  # Save to file immediately
    
    if not data["settings"].get("auto_reply_comments", True):
        return False
    
    token, page_name = get_page_token(page_id)
    if not token:
        add_history("Unknown", "خطأ", "فشل", f"لا يوجد توكن للصفحة {page_id}")
        return False
    
    templates = data.get("comment_templates", [])
    if not templates:
        return False
    
    template = random.choice(templates)
    reply_text = process_spintax(template)
    
    url = f"https://graph.facebook.com/v19.0/{comment_id}/comments"
    try:
        response = requests.post(url, data={
            "message": reply_text,
            "access_token": token
        }, timeout=10)
        
        if response.status_code == 200:
            add_history(page_name, "رد على تعليق", "نجاح", f"الرد على {user_name}: {reply_text[:50]}...")
            return True
        else:
            error_text = response.text[:100]
            print(f"❌ فشل الرد: {error_text}")
            add_history(page_name, "رد على تعليق", "فشل", error_text)
            return False
    except Exception as e:
        print(f"❌ استثناء: {e}")
        add_history(page_name, "رد على تعليق", "خطأ", str(e)[:100])
        return False

def send_private_reply(comment_id, page_id, user_name):
    if not data["settings"].get("send_private_reply", True):
        return False
    
    token, page_name = get_page_token(page_id)
    if not token:
        print(f"⚠️ رسالة خاصة: لا يوجد توكن للصفحة {page_id}")
        return False
    
    templates = data.get("message_templates", [])
    if not templates:
        print("⚠️ رسالة خاصة: لا يوجد قوالب رسائل")
        return False
    
    template = random.choice(templates)
    message_text = process_spintax(template)
    
    url = f"https://graph.facebook.com/v19.0/{comment_id}/private_replies"
    try:
        response = requests.post(url, data={
            "message": message_text,
            "access_token": token
        }, timeout=10)
        
        if response.status_code == 200:
            add_history(page_name, "رسالة خاصة", "نجاح", f"رسالة لـ {user_name}")
            return True
        else:
            error_text = response.text[:100]
            print(f"❌ فشل الرسالة الخاصة: {error_text}")
            add_history(page_name, "رسالة خاصة", "فشل", error_text)
            return False
    except Exception as e:
        print(f"❌ استثناء رسالة خاصة: {e}")
        return False

def reply_to_message(sender_id, page_id):
    if not data["settings"].get("auto_reply_messages", True):
        return False
    
    token, page_name = get_page_token(page_id)
    if not token:
        return False
    
    templates = data.get("message_templates", [])
    if not templates:
        return False
    
    template = random.choice(templates)
    message_text = process_spintax(template)
    
    url = f"https://graph.facebook.com/v19.0/{page_id}/messages"
    try:
        response = requests.post(url, json={
            "recipient": {"id": sender_id},
            "message": {"text": message_text},
            "access_token": token
        }, timeout=10)
        
        if response.status_code == 200:
            add_history(page_name, "رد على رسالة", "نجاح", "")
            return True
        else:
            add_history(page_name, "رد على رسالة", "فشل", response.text[:100])
            return False
    except Exception as e:
        add_history(page_name, "رد على رسالة", "خطأ", str(e)[:100])
        return False

# ============ HTML Templates ============
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تحكم Webhooks</title>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Cairo', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            color: #fff;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        
        /* Header */
        .header {
            background: rgba(0,0,0,0.3);
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 { color: #00e5ff; font-size: 1.8em; }
        .header .status {
            background: #00c853;
            padding: 8px 20px;
            border-radius: 20px;
            font-weight: bold;
        }
        .logout-btn {
            background: #ff5252;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
        }
        
        /* Stats */
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: rgba(255,255,255,0.1);
            padding: 20px;
            border-radius: 12px;
            text-align: center;
        }
        .stat-card h3 { font-size: 2em; color: #00e5ff; }
        .stat-card p { color: #aaa; }
        
        /* Grid */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
        }
        
        /* Cards */
        .card {
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .card-title { color: #00e5ff; font-size: 1.2em; }
        
        /* Forms */
        input, textarea, select {
            width: 100%;
            padding: 12px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 8px;
            background: rgba(0,0,0,0.3);
            color: #fff;
            margin-bottom: 10px;
            font-family: inherit;
        }
        textarea { min-height: 100px; resize: vertical; }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.3s;
        }
        .btn-primary { background: linear-gradient(45deg, #00e5ff, #00b8d4); color: #000; }
        .btn-danger { background: #ff5252; color: #fff; }
        .btn-success { background: #00c853; color: #fff; }
        .btn:hover { transform: translateY(-2px); opacity: 0.9; }
        
        /* List */
        .list-item {
            background: rgba(0,0,0,0.2);
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .list-item:hover { background: rgba(0,0,0,0.3); }
        
        /* Table */
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: right; border-bottom: 1px solid rgba(255,255,255,0.1); }
        th { color: #00e5ff; }
        .status-success { color: #00c853; }
        .status-error { color: #ff5252; }
        
        /* Toggle */
        .toggle-container { display: flex; align-items: center; gap: 10px; margin: 10px 0; }
        .toggle {
            width: 50px; height: 26px;
            background: #555;
            border-radius: 13px;
            position: relative;
            cursor: pointer;
            transition: 0.3s;
        }
        .toggle.active { background: #00c853; }
        .toggle::after {
            content: '';
            position: absolute;
            width: 22px; height: 22px;
            background: #fff;
            border-radius: 50%;
            top: 2px; left: 2px;
            transition: 0.3s;
        }
        .toggle.active::after { left: 26px; }
        
        /* Responsive */
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .header { flex-direction: column; gap: 15px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>🚀 لوحة تحكم Webhooks</h1>
            <div class="status">🟢 السيرفر يعمل</div>
            <a href="/logout" class="logout-btn">تسجيل الخروج</a>
        </div>
        
        <!-- Stats -->
        <div class="stats">
            <div class="stat-card">
                <h3 id="pages-count">{{ pages_count }}</h3>
                <p>الصفحات</p>
            </div>
            <div class="stat-card">
                <h3 id="replies-count">{{ replies_count }}</h3>
                <p>الردود اليوم</p>
            </div>
            <div class="stat-card">
                <h3 id="templates-count">{{ templates_count }}</h3>
                <p>القوالب</p>
            </div>
        </div>
        
        <div class="grid">
            <!-- Pages -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">📄 الصفحات</span>
                    <button class="btn btn-danger" onclick="deleteAllPages()" style="font-size: 0.8em;">🗑️ حذف الكل</button>
                </div>
                
                <!-- Fetch Pages Section -->
                <div style="margin-bottom: 15px; padding: 15px; background: rgba(0,0,0,0.2); border-radius: 10px;">
                    <p style="color: #00e5ff; margin-bottom: 10px;">🔄 جلب الصفحات تلقائياً</p>
                    <input type="text" id="user-token" placeholder="أدخل Access Token للحساب">
                    <button class="btn btn-primary" onclick="fetchPages()" id="fetch-btn">📥 جلب الصفحات</button>
                </div>
                
                <!-- Fetched Pages (hidden initially) -->
                <div id="fetched-pages-container" style="display: none; margin-bottom: 15px; padding: 15px; background: rgba(0,100,0,0.2); border-radius: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <span style="color: #00c853;">📋 الصفحات المتاحة:</span>
                        <button class="btn btn-success" onclick="addSelectedPages()">➕ إضافة المحددة</button>
                    </div>
                    <div style="margin-bottom: 10px;">
                        <label style="cursor: pointer;">
                            <input type="checkbox" id="select-all-fetched" onchange="toggleAllFetched()"> 
                            تحديد الكل
                        </label>
                    </div>
                    <div id="fetched-pages-list" style="max-height: 200px; overflow-y: auto;"></div>
                </div>
                
                <!-- Current Pages List -->
                <p style="color: #aaa; margin-bottom: 10px;">الصفحات المضافة ({{ pages|length }}):</p>
                <div id="pages-list" style="max-height: 300px; overflow-y: auto;">
                    {% for page in pages %}
                    <div class="list-item">
                        <span>{{ page.name }}</span>
                        <button class="btn btn-danger" onclick="deletePage('{{ page.id }}')" style="padding: 5px 10px;">🗑️</button>
                    </div>
                    {% endfor %}
                </div>
                
                <!-- Subscribe All Button -->
                {% if pages %}
                <div style="margin-top: 15px; padding: 15px; background: rgba(0,150,0,0.2); border-radius: 10px;">
                    <button class="btn btn-success" onclick="subscribeAllPages()" style="width: 100%;">
                        🔔 تفعيل Webhooks لكل الصفحات
                    </button>
                    <p style="color: #aaa; font-size: 0.85em; margin-top: 8px; text-align: center;">
                        اضغط هنا بعد إضافة الصفحات لتفعيل الإشعارات
                    </p>
                </div>
                {% endif %}
            </div>
            
            <!-- Comment Templates -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">💬 قوالب التعليقات</span>
                </div>
                <form id="add-comment-template-form">
                    <textarea id="comment-template" placeholder="اكتب قالب الرد هنا... يمكنك استخدام {خيار1|خيار2}"></textarea>
                    <button type="submit" class="btn btn-primary">➕ إضافة قالب</button>
                </form>
                <div id="comment-templates-list" style="margin-top: 15px; max-height: 200px; overflow-y: auto;">
                    {% for template in comment_templates %}
                    <div class="list-item">
                        <span>{{ template[:50] }}...</span>
                        <button class="btn btn-danger" onclick="deleteCommentTemplate({{ loop.index0 }})">🗑️</button>
                    </div>
                    {% endfor %}
                </div>
            </div>
            
            <!-- Message Templates -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">📨 قوالب الرسائل</span>
                </div>
                <form id="add-message-template-form">
                    <textarea id="message-template" placeholder="اكتب قالب الرسالة هنا..."></textarea>
                    <button type="submit" class="btn btn-primary">➕ إضافة قالب</button>
                </form>
                <div id="message-templates-list" style="margin-top: 15px; max-height: 200px; overflow-y: auto;">
                    {% for template in message_templates %}
                    <div class="list-item">
                        <span>{{ template[:50] }}...</span>
                        <button class="btn btn-danger" onclick="deleteMessageTemplate({{ loop.index0 }})">🗑️</button>
                    </div>
                    {% endfor %}
                </div>
            </div>
            
            <!-- Settings -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">⚙️ الإعدادات</span>
                </div>
                <div class="toggle-container">
                    <div class="toggle {{ 'active' if settings.auto_reply_comments else '' }}" 
                         onclick="toggleSetting('auto_reply_comments', this)"></div>
                    <span>الرد على التعليقات تلقائياً</span>
                </div>
                <div class="toggle-container">
                    <div class="toggle {{ 'active' if settings.auto_reply_messages else '' }}" 
                         onclick="toggleSetting('auto_reply_messages', this)"></div>
                    <span>الرد على الرسائل تلقائياً</span>
                </div>
                <div class="toggle-container">
                    <div class="toggle {{ 'active' if settings.send_private_reply else '' }}" 
                         onclick="toggleSetting('send_private_reply', this)"></div>
                    <span>إرسال رسالة خاصة مع الرد</span>
                </div>
                
                <div style="margin-top: 20px; padding: 15px; background: rgba(0,0,0,0.2); border-radius: 8px;">
                    <p style="color: #aaa; margin-bottom: 10px;">🔗 Webhook URL:</p>
                    <code style="color: #00e5ff; word-break: break-all;">{{ webhook_url }}</code>
                </div>
            </div>
            
            <!-- History -->
            <div class="card" style="grid-column: span 2;">
                <div class="card-header">
                    <span class="card-title">📜 سجل الردود</span>
                    <button class="btn btn-danger" onclick="clearHistory()">🗑️ مسح السجل</button>
                </div>
                <div style="max-height: 400px; overflow-y: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>الوقت</th>
                                <th>الصفحة</th>
                                <th>الإجراء</th>
                                <th>الحالة</th>
                            </tr>
                        </thead>
                        <tbody id="history-table">
                            {% for item in history[-50:]|reverse %}
                            <tr>
                                <td>{{ item.time }}</td>
                                <td>{{ item.page }}</td>
                                <td>{{ item.action }}</td>
                                <td class="{{ 'status-success' if item.status == 'نجاح' else 'status-error' }}">
                                    {{ item.status }}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
        </div>
    </div>
    
    <script>
        // Global variable to store fetched pages
        let fetchedPages = [];
        
        // Fetch Pages from Token
        async function fetchPages() {
            const token = document.getElementById('user-token').value;
            if (!token) {
                alert('يرجى إدخال Access Token');
                return;
            }
            
            const btn = document.getElementById('fetch-btn');
            btn.textContent = '⏳ جاري الجلب...';
            btn.disabled = true;
            
            try {
                const response = await fetch('/api/fetch-pages', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({token: token})
                });
                const result = await response.json();
                
                if (result.success) {
                    fetchedPages = result.pages;
                    displayFetchedPages(result.pages);
                } else {
                    alert('خطأ: ' + (result.error || 'فشل جلب الصفحات'));
                }
            } catch (e) {
                alert('خطأ في الاتصال');
            }
            
            btn.textContent = '📥 جلب الصفحات';
            btn.disabled = false;
        }
        
        // Display fetched pages with checkboxes
        function displayFetchedPages(pages) {
            const container = document.getElementById('fetched-pages-container');
            const list = document.getElementById('fetched-pages-list');
            
            if (pages.length === 0) {
                list.innerHTML = '<p style="color: #aaa;">لم يتم العثور على صفحات</p>';
            } else {
                list.innerHTML = pages.map((p, i) => `
                    <div class="list-item">
                        <label style="cursor: pointer; flex: 1;">
                            <input type="checkbox" class="page-checkbox" data-index="${i}" checked>
                            ${p.name}
                        </label>
                    </div>
                `).join('');
            }
            
            container.style.display = 'block';
        }
        
        // Toggle all checkboxes
        function toggleAllFetched() {
            const checked = document.getElementById('select-all-fetched').checked;
            document.querySelectorAll('.page-checkbox').forEach(cb => cb.checked = checked);
        }
        
        // Add selected pages
        async function addSelectedPages() {
            const selected = [];
            document.querySelectorAll('.page-checkbox:checked').forEach(cb => {
                const index = parseInt(cb.dataset.index);
                selected.push(fetchedPages[index]);
            });
            
            if (selected.length === 0) {
                alert('يرجى تحديد صفحة واحدة على الأقل');
                return;
            }
            
            const response = await fetch('/api/pages/bulk', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({pages: selected})
            });
            const result = await response.json();
            
            alert(`تمت إضافة ${result.added} صفحة جديدة`);
            location.reload();
        }
        
        // Subscribe all pages to webhooks
        async function subscribeAllPages() {
            if (!confirm('هل تريد تفعيل Webhooks لكل الصفحات المضافة؟')) {
                return;
            }
            
            try {
                const response = await fetch('/api/pages/subscribe-all', {method: 'POST'});
                const result = await response.json();
                
                if (result.success) {
                    let message = `تم تفعيل ${result.subscribed} من ${result.total} صفحة\n\n`;
                    result.results.forEach(r => {
                        message += r.success ? `✅ ${r.page}\n` : `❌ ${r.page}: ${r.error}\n`;
                    });
                    alert(message);
                    location.reload();
                } else {
                    alert('حدث خطأ أثناء التفعيل');
                }
            } catch (e) {
                alert('خطأ في الاتصال');
            }
        }
        
        // Delete Page
        async function deletePage(id) {
            if (confirm('هل أنت متأكد من حذف هذه الصفحة؟')) {
                await fetch('/api/pages/' + id, {method: 'DELETE'});
                location.reload();
            }
        }
        
        // Delete All Pages
        async function deleteAllPages() {
            if (confirm('هل أنت متأكد من حذف جميع الصفحات؟')) {
                const pages = {{ pages | tojson }};
                for (const p of pages) {
                    await fetch('/api/pages/' + p.id, {method: 'DELETE'});
                }
                location.reload();
            }
        }
        
        // Add Comment Template
        document.getElementById('add-comment-template-form').onsubmit = async (e) => {
            e.preventDefault();
            await fetch('/api/templates/comment', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({template: document.getElementById('comment-template').value})
            });
            location.reload();
        };
        
        // Add Message Template
        document.getElementById('add-message-template-form').onsubmit = async (e) => {
            e.preventDefault();
            await fetch('/api/templates/message', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({template: document.getElementById('message-template').value})
            });
            location.reload();
        };
        
        // Delete Templates
        async function deleteCommentTemplate(index) {
            await fetch('/api/templates/comment/' + index, {method: 'DELETE'});
            location.reload();
        }
        
        async function deleteMessageTemplate(index) {
            await fetch('/api/templates/message/' + index, {method: 'DELETE'});
            location.reload();
        }
        
        // Toggle Setting
        async function toggleSetting(setting, el) {
            el.classList.toggle('active');
            await fetch('/api/settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({setting: setting, value: el.classList.contains('active')})
            });
        }
        
        // Clear History
        async function clearHistory() {
            if (confirm('هل أنت متأكد من مسح السجل؟')) {
                await fetch('/api/history', {method: 'DELETE'});
                location.reload();
            }
        }
        
        // Auto-refresh disabled to prevent losing data while working
        // setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
'''

LOGIN_HTML = '''
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تسجيل الدخول</title>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Cairo', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            color: #fff;
        }
        .login-box {
            background: rgba(255,255,255,0.05);
            padding: 40px;
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            width: 100%;
            max-width: 400px;
            text-align: center;
        }
        h1 { color: #00e5ff; margin-bottom: 30px; font-size: 1.8em; }
        input {
            width: 100%;
            padding: 15px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 10px;
            background: rgba(0,0,0,0.3);
            color: #fff;
            margin-bottom: 15px;
            font-size: 1em;
        }
        button {
            width: 100%;
            padding: 15px;
            background: linear-gradient(45deg, #00e5ff, #00b8d4);
            border: none;
            border-radius: 10px;
            color: #000;
            font-weight: bold;
            font-size: 1.1em;
            cursor: pointer;
            transition: 0.3s;
        }
        button:hover { transform: translateY(-2px); }
        .error { color: #ff5252; margin-bottom: 15px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>🔒 تسجيل الدخول</h1>
        {% if error %}
        <p class="error">{{ error }}</p>
        {% endif %}
        <form method="POST">
            <input type="password" name="password" placeholder="كلمة المرور" required>
            <button type="submit">دخول</button>
        </form>
    </div>
</body>
</html>
'''

# ============ Routes ============
@app.route("/")
@login_required
def dashboard():
    today = datetime.now().strftime("%Y-%m-%d")
    replies_today = len([h for h in history if h.get("time", "").startswith(today) and h.get("status") == "نجاح"])
    
    return render_template_string(DASHBOARD_HTML,
        pages=data.get("pages", []),
        comment_templates=data.get("comment_templates", []),
        message_templates=data.get("message_templates", []),
        settings=data.get("settings", {}),
        history=history,
        pages_count=len(data.get("pages", [])),
        replies_count=replies_today,
        templates_count=len(data.get("comment_templates", [])) + len(data.get("message_templates", [])),
        webhook_url=request.host_url + "webhook"
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            error = "كلمة المرور غير صحيحة"
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ============ API Routes ============
@app.route("/api/pages", methods=["POST"])
@login_required
def add_page():
    page_data = request.json
    data.setdefault("pages", []).append(page_data)
    save_data()
    return jsonify({"success": True})

@app.route("/api/fetch-pages", methods=["POST"])
@login_required
def fetch_pages():
    """Fetch all pages from a user access token"""
    user_token = request.json.get("token")
    if not user_token:
        return jsonify({"success": False, "error": "Token required"}), 400
    
    try:
        # Get all pages for this user
        url = f"https://graph.facebook.com/v19.0/me/accounts?fields=id,name,access_token&limit=100&access_token={user_token}"
        response = requests.get(url, timeout=15)
        
        if response.status_code != 200:
            return jsonify({"success": False, "error": response.text}), 400
        
        pages_data = response.json().get("data", [])
        
        # Format pages
        pages = []
        for p in pages_data:
            pages.append({
                "id": p["id"],
                "name": p["name"],
                "token": p["access_token"]
            })
        
        return jsonify({"success": True, "pages": pages})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/pages/bulk", methods=["POST"])
@login_required
def add_pages_bulk():
    """Add multiple pages at once"""
    pages_to_add = request.json.get("pages", [])
    existing_ids = {p["id"] for p in data.get("pages", [])}
    
    added = 0
    for page in pages_to_add:
        if page["id"] not in existing_ids:
            data.setdefault("pages", []).append(page)
            added += 1
    
    save_data()
    return jsonify({"success": True, "added": added})

@app.route("/api/pages/subscribe-all", methods=["POST"])
@login_required
def subscribe_all_pages():
    """Subscribe all pages to webhooks at once"""
    results = []
    pages = data.get("pages", [])
    
    for page in pages:
        page_id = page.get("id")
        page_token = page.get("token")
        page_name = page.get("name", "Unknown")
        
        if not page_id or not page_token:
            results.append({"page": page_name, "success": False, "error": "Missing ID or token"})
            continue
        
        try:
            url = f"https://graph.facebook.com/v19.0/{page_id}/subscribed_apps"
            response = requests.post(url, data={
                "subscribed_fields": "feed,messages",
                "access_token": page_token
            }, timeout=10)
            
            if response.status_code == 200:
                results.append({"page": page_name, "success": True})
                add_history(page_name, "اشتراك Webhook", "نجاح", "")
            else:
                error_msg = response.json().get("error", {}).get("message", "Unknown error")
                results.append({"page": page_name, "success": False, "error": error_msg[:50]})
                add_history(page_name, "اشتراك Webhook", "فشل", error_msg[:50])
        except Exception as e:
            results.append({"page": page_name, "success": False, "error": str(e)[:50]})
    
    success_count = len([r for r in results if r["success"]])
    return jsonify({
        "success": True,
        "total": len(pages),
        "subscribed": success_count,
        "results": results
    })

@app.route("/api/pages/<page_id>", methods=["DELETE"])
@login_required
def delete_page(page_id):
    data["pages"] = [p for p in data.get("pages", []) if p["id"] != page_id]
    save_data()
    return jsonify({"success": True})

@app.route("/api/templates/comment", methods=["POST"])
@login_required
def add_comment_template():
    template = request.json.get("template")
    if template:
        data.setdefault("comment_templates", []).append(template)
        save_data()
    return jsonify({"success": True})

@app.route("/api/templates/comment/<int:index>", methods=["DELETE"])
@login_required
def delete_comment_template(index):
    if 0 <= index < len(data.get("comment_templates", [])):
        data["comment_templates"].pop(index)
        save_data()
    return jsonify({"success": True})

@app.route("/api/templates/message", methods=["POST"])
@login_required
def add_message_template():
    template = request.json.get("template")
    if template:
        data.setdefault("message_templates", []).append(template)
        save_data()
    return jsonify({"success": True})

@app.route("/api/templates/message/<int:index>", methods=["DELETE"])
@login_required
def delete_message_template(index):
    if 0 <= index < len(data.get("message_templates", [])):
        data["message_templates"].pop(index)
        save_data()
    return jsonify({"success": True})

@app.route("/api/settings", methods=["POST"])
@login_required
def update_setting():
    setting = request.json.get("setting")
    value = request.json.get("value")
    data.setdefault("settings", {})[setting] = value
    save_data()
    return jsonify({"success": True})

@app.route("/api/history", methods=["DELETE"])
@login_required
def clear_history():
    global history
    history = []
    save_history()
    return jsonify({"success": True})

# ============ Webhook ============
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook verified!")
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def webhook_handler():
    webhook_data = request.get_json()
    print(f"📩 Webhook: {json.dumps(webhook_data, indent=2)}")
    
    if webhook_data.get("object") == "page":
        for entry in webhook_data.get("entry", []):
            page_id = entry.get("id")
            
            for change in entry.get("changes", []):
                if change.get("field") == "feed":
                    value = change.get("value", {})
                    if value.get("item") == "comment" and value.get("verb") == "add":
                        comment_id = value.get("comment_id")
                        user_name = value.get("from", {}).get("name", "Unknown")
                        
                        print(f"💬 New comment from {user_name}")
                        reply_to_comment(comment_id, page_id, user_name)
                        send_private_reply(comment_id, page_id, user_name)
            
            for messaging in entry.get("messaging", []):
                sender_id = messaging.get("sender", {}).get("id")
                message = messaging.get("message", {})
                
                if message and sender_id != page_id:
                    reply_to_message(sender_id, page_id)
    
    return "OK", 200

# ============ Run ============
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 Facebook Webhooks Server with Dashboard")
    print("=" * 50)
    
    load_data()
    load_processed()  # Load processed comments to prevent duplicates
    
    port = int(os.getenv("PORT", 5000))
    print(f"🌐 Server running on port {port}")
    print(f"📊 Dashboard: http://localhost:{port}")
    
    app.run(host="0.0.0.0", port=port, debug=False)
