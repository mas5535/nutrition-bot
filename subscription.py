# -*- coding: utf-8 -*-
"""سیستم اشتراک، trial و پرداخت"""
import json
import os
from datetime import datetime, timedelta

# ============================================================
# تنظیمات
# ============================================================
TRIAL_HOURS = 2
SUBSCRIPTION_DAYS = 30
SUBSCRIPTION_PRICE = 5000  # به سنت (مثلاً 5000 = 50 دلار)
CURRENCY = "USD"

USERS_DB_FILE = "users.json"


# ============================================================
# مدیریت دیتابیس کاربران
# ============================================================
def load_users():
    if os.path.exists(USERS_DB_FILE):
        try:
            with open(USERS_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_users(users):
    with open(USERS_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def get_user(user_id):
    users = load_users()
    return users.get(str(user_id), None)


def create_or_update_user(user_id, **kwargs):
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "user_id": user_id,
            "trial_used": False,
            "trial_start": None,
            "trial_end": None,
            "subscription_start": None,
            "subscription_end": None,
            "created_at": datetime.now().isoformat(),
        }
    users[uid].update(kwargs)
    save_users(users)
    return users[uid]


# ============================================================
# منطق Trial و اشتراک
# ============================================================
def can_start_trial(user_id):
    """آیا کاربر مجاز به شروع trial است؟"""
    user = get_user(user_id)
    if not user:
        return True
    if user.get("trial_used"):
        return False
    if user.get("subscription_end"):
        end = datetime.fromisoformat(user["subscription_end"])
        if end > datetime.now():
            return False  # اشتراک فعال داره
    return True


def start_trial(user_id):
    """شروع دوره trial"""
    now = datetime.now()
    end = now + timedelta(hours=TRIAL_HOURS)
    create_or_update_user(
        user_id,
        trial_used=True,
        trial_start=now.isoformat(),
        trial_end=end.isoformat(),
    )
    return end


def is_trial_active(user_id):
    """آیا trial کاربر فعال است؟"""
    user = get_user(user_id)
    if not user or not user.get("trial_end"):
        return False
    end = datetime.fromisoformat(user["trial_end"])
    return end > datetime.now()


def is_subscription_active(user_id):
    """آیا اشتراک کاربر فعال است؟"""
    user = get_user(user_id)
    if not user or not user.get("subscription_end"):
        return False
    end = datetime.fromisoformat(user["subscription_end"])
    return end > datetime.now()


def has_access(user_id):
    """آیا کاربر اجازه استفاده از امکانات را دارد؟"""
    return is_trial_active(user_id) or is_subscription_active(user_id)


def get_access_status(user_id):
    """وضعیت دسترسی کاربر"""
    if is_subscription_active(user_id):
        return "subscription"
    if is_trial_active(user_id):
        return "trial"
    if not can_start_trial(user_id):
        return "expired"
    return "new"


def extend_subscription(user_id, days=SUBSCRIPTION_DAYS):
    """تمدید اشتراک پس از پرداخت موفق"""
    now = datetime.now()
    user = get_user(user_id)
    current_end = None
    if user and user.get("subscription_end"):
        end = datetime.fromisoformat(user["subscription_end"])
        if end > now:
            current_end = end
    start = current_end if current_end else now
    new_end = start + timedelta(days=days)
    create_or_update_user(
        user_id,
        subscription_start=now.isoformat(),
        subscription_end=new_end.isoformat(),
    )
    return new_end


def get_subscription_end(user_id):
    user = get_user(user_id)
    if user and user.get("subscription_end"):
        return datetime.fromisoformat(user["subscription_end"])
    return None


# ============================================================
# توابع کمکی برای نمایش
# ============================================================
def format_trial_remaining(user_id):
    user = get_user(user_id)
    if not user or not user.get("trial_end"):
        return None
    end = datetime.fromisoformat(user["trial_end"])
    if end <= datetime.now():
        return None
    delta = end - datetime.now()
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"{hours} ساعت و {minutes} دقیقه"


def format_subscription_remaining(user_id):
    end = get_subscription_end(user_id)
    if not end or end <= datetime.now():
        return None
    delta = end - datetime.now()
    return f"{delta.days} روز"