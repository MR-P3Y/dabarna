# دبرنای طوفان

فارسی · [English](README.md)

**دبرنای طوفان** یک پلتفرم Telegram Mini App و Telegram Bot برای اجرای بازی دبرنای طوفان/بینگو است. این پروژه شامل مدیریت بازی زنده، خرید کارت، کیف پول، واریز کارت بانکی با بررسی رسید، برداشت، عملیات ادمین، اعلان‌ها و پشتیبانی از واریز رمزارزی TON/TRON است.

> نام انگلیسی: **Davarna Toofan**  
> نام‌های داخلی `davarna` / `dabarna` ممکن است برای سازگاری deployment و مسیرهای پروژه باقی بمانند.

---

## فهرست

- [معرفی](#معرفی)
- [قابلیت‌های اصلی](#قابلیتهای-اصلی)
- [معماری](#معماری)
- [تکنولوژی‌ها](#تکنولوژیها)
- [ساختار پروژه](#ساختار-پروژه)
- [جریان‌های پرداخت](#جریانهای-پرداخت)
- [ادمین و سوپرادمین](#ادمین-و-سوپرادمین)
- [اجرای لوکال](#اجرای-لوکال)
- [دیپلوی production](#دیپلوی-production)
- [متغیرهای محیطی](#متغیرهای-محیطی)
- [چک‌لیست عملیاتی](#چکلیست-عملیاتی)
- [نکات امنیتی](#نکات-امنیتی)
- [Roadmap](#roadmap)
- [مجوز](#مجوز)

---

## معرفی

دبرنای طوفان برای اجرای بازی در بستر تلگرام طراحی شده است:

1. کاربر از طریق ربات یا مینی‌اپ وارد می‌شود.
2. بازی‌های فعال را می‌بیند و با موجودی کیف پول کارت می‌خرد.
3. ادمین‌ها وضعیت لابی، شروع بازی، اعلام عدد و امور مالی را مدیریت می‌کنند.
4. سیستم تراکنش‌های کیف پول، واریز، برداشت، جایزه‌ها، اعلان‌ها و audit را ثبت می‌کند.
5. پرداخت رمزارزی با فاکتور، QR، بررسی شبکه و شارژ خودکار کیف پول پشتیبانی می‌شود.

این پروژه برای استفاده تجاری و خصوصی طراحی شده، نه به عنوان قالب عمومی SaaS.

---

## قابلیت‌های اصلی

### Telegram Mini App

- رابط فارسی و موبایل‌محور
- نمایش موجودی کیف پول و تاریخچه تراکنش‌ها
- نمایش بازی‌های فعال و وضعیت زنده بازی
- نمایش کارت‌های خریداری‌شده
- واریز کارت بانکی با آپلود رسید
- ساخت فاکتور رمزارزی TON/TRON
- پرداخت دستی با QR و کپی آدرس
- ثبت اختیاری هش تراکنش رمزارزی
- پنل مدیریت داخل مینی‌اپ
- کنترل سوپرادمین برای روشن/خاموش کردن پرداخت رمزارزی

### Telegram Bot

- شروع و منوی کاربر
- کیف پول، واریز، برداشت، بازی و کارت‌ها
- بررسی عضویت اجباری
- اعلان‌های مالی برای ادمین
- مدیریت بازی توسط ادمین
- مدیریت کاربران
- مدیریت نقش‌ها توسط سوپرادمین
- مدیریت کارت‌های واریز توسط سوپرادمین
- worker اعلان‌ها برای رویدادهای بازی و کاربران

### Backend

- API با FastAPI
- ذخیره‌سازی در MySQL
- Redis برای cache/queue
- دفتر حساب کیف پول
- سرویس خرید کارت و مدیریت بازی
- سرویس‌های واریز، برداشت، تأیید و رد درخواست‌ها
- سرویس‌های فاکتور رمزارز، QR، health، reconciliation و worker
- RBAC ادمین و سوپرادمین
- audit log
- سرو کردن فایل‌های static مینی‌اپ

---

## معماری

```text
کاربر تلگرام
   │
   ├── Telegram Bot
   │      └── Aiogram routers, FSM, notification worker
   │
   └── Telegram Mini App
          └── HTML/CSS/JS frontend
                    │
                    ▼
              FastAPI Backend
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
      MySQL       Redis      Storage
        │                       │
        ▼                       ▼
 Wallet / Game / Finance     Receipts
 Crypto / Admin / Audit
```

### سرویس‌های runtime

```text
davarna-mysql      دیتابیس MySQL 8.0
davarna-redis      Redis 7
davarna-backend    بک‌اند FastAPI + فایل‌های مینی‌اپ + worker رمزارز
davarna-bot        ربات تلگرام
davarna-nginx      reverse proxy اختیاری
certbot            ابزار اختیاری TLS
```

---

## تکنولوژی‌ها

| بخش | تکنولوژی |
|---|---|
| Backend API | FastAPI |
| ORM / DB | SQLAlchemy, Alembic, MySQL 8 |
| Bot | Aiogram 3 |
| Cache / Queue | Redis |
| Mini App | HTML, CSS, Vanilla JavaScript |
| Crypto frontend bundle | esbuild, TON Connect, WalletConnect/TRON tooling |
| Deployment | Docker Compose |
| Runtime | Python 3.13 containers |
| Reverse Proxy | Nginx اختیاری |

---

## ساختار پروژه

```text
.
├── backend/
│   ├── app/
│   │   ├── core/               # تنظیمات، دیتابیس، گارد ادمین، امنیت مینی‌اپ
│   │   ├── models/             # مدل‌های SQLAlchemy
│   │   ├── routers/            # مسیرهای FastAPI
│   │   ├── schemas/            # مدل‌های Pydantic
│   │   ├── services/           # منطق اصلی کسب‌وکار
│   │   ├── scripts/            # seed و اسکریپت‌های نگهداری
│   │   └── static/mini/        # خروجی ساخته‌شده مینی‌اپ
│   ├── frontend/               # bundle پرداخت/اتصال کیف پول
│   ├── alembic/                # migrationهای دیتابیس
│   ├── Dockerfile
│   └── requirements.txt
│
├── davarna-bot/
│   ├── bot/
│   │   ├── routers/            # routerهای ربات
│   │   ├── keyboards/          # کیبوردهای inline
│   │   ├── middlewares/        # middlewareهای user/api/throttling
│   │   ├── services/           # API client، notifier، helperهای تلگرام
│   │   ├── states/             # FSM states
│   │   └── workers/            # worker اعلان‌ها
│   ├── Dockerfile
│   └── requirements.txt
│
├── deploy/                     # فایل‌های Nginx / Certbot
├── storage/                    # فایل‌های runtime، نباید وارد Git شود
└── docker-compose.yml
```

---

## جریان‌های پرداخت

### واریز کارت بانکی

```text
کاربر کارت مقصد را انتخاب می‌کند
→ مبلغ را وارد می‌کند
→ کارت‌به‌کارت را دستی انجام می‌دهد
→ رسید را آپلود می‌کند
→ ادمین رسید را تأیید یا رد می‌کند
→ در صورت تأیید، کیف پول کاربر شارژ می‌شود
```

قابلیت‌های کارت بانکی:

- چند کارت مقصد
- فعال/غیرفعال بودن هر کارت
- افزودن، ویرایش و حذف کارت توسط سوپرادمین
- امکان اضافه شدن دکمه خاموش/روشن کلی واریز کارت بانکی در پنل سوپرادمین مینی‌اپ
- ذخیره snapshot کارت مقصد روی درخواست واریز

### واریز رمزارزی

```text
کاربر شبکه رمزارزی را انتخاب می‌کند
→ بک‌اند با نرخ لحظه‌ای فاکتور می‌سازد
→ کاربر با اتصال کیف پول یا QR / کپی آدرس پرداخت می‌کند
→ worker شبکه را بررسی می‌کند
→ کاربر می‌تواند هش تراکنش را ثبت کند
→ بعد از تأیید شبکه، کیف پول شارژ می‌شود
```

قابلیت‌های رمزارز:

- TON
- TRON / USDT TRC20
- انقضای فاکتور
- راهنمای کارمزد شبکه
- QR fallback
- لینک Explorer
- بررسی دستی توسط ادمین در موارد خاص
- health check و reconciliation
- دکمه روشن/خاموش runtime برای سوپرادمین

---

## ادمین و سوپرادمین

### دسترسی‌های ادمین

- ایجاد و مدیریت بازی
- شروع بازی و اعلام عدد
- حذف آخرین عدد اعلام‌شده
- لغو لابی قبل از شروع بازی
- بررسی واریزهای کارت بانکی
- بررسی برداشت‌ها
- مشاهده تاریخچه مالی و بازی کاربران
- ارسال پیام به کاربران
- ثبت و ارسال لینک لایو

### دسترسی‌های سوپرادمین

- مدیریت نقش ادمین‌ها
- مدیریت کارت‌های واریز
- روشن/خاموش کردن پرداخت رمزارزی از مینی‌اپ
- بررسی سلامت سرویس‌های رمزارزی
- اجرای reconciliation رمزارز
- نگهداری تنظیمات حساس عملیاتی

---

## اجرای لوکال

### ۱. Clone

```bash
git clone <repository-url>
cd dabarna
```

### ۲. ساخت فایل‌های env

برای backend:

```bash
cp .env.example .env
```

برای bot:

```bash
cp davarna-bot/.env.example davarna-bot/.env
```

اگر فایل example هنوز ساخته نشده، از قالب production بدون secret واقعی یک نسخه امن بساز.

### ۳. اجرای سرویس‌ها

```bash
docker compose up -d --build
```

### ۴. بررسی سلامت

```bash
curl http://127.0.0.1:18080/health/db
```

خروجی مورد انتظار:

```json
{"ok": true}
```

### ۵. مشاهده لاگ

```bash
docker compose logs backend --tail=120
docker compose logs bot --tail=120
```

---

## دیپلوی production

### دیپلوی کامل

```bash
cd /opt/davarna

git pull origin main

docker compose --env-file .env.prod up -d --build

curl -sS http://127.0.0.1:18080/health/db
echo

docker compose --env-file .env.prod ps
```

### rebuild فقط backend

زمانی که backend، مینی‌اپ، routerها، serviceها یا config تغییر کرده‌اند:

```bash
cd /opt/davarna

git pull origin main

docker compose --env-file .env.prod up -d --build backend

curl -sS http://127.0.0.1:18080/health/db
echo

docker compose --env-file .env.prod ps
```

### rebuild فقط bot

زمانی که فقط `davarna-bot/` تغییر کرده است:

```bash
cd /opt/davarna

git pull origin main

docker compose --env-file .env.prod up -d --build bot

docker compose --env-file .env.prod logs bot --tail=120
```

### لاگ‌های مهم

```bash
docker compose --env-file .env.prod logs backend --tail=150
docker compose --env-file .env.prod logs bot --tail=150
docker compose --env-file .env.prod logs mysql --tail=80
docker compose --env-file .env.prod logs redis --tail=80
```

---

## متغیرهای محیطی

هیچ‌وقت فایل‌های `.env`، `.env.prod`، توکن ربات، توکن ادمین، کلید API، seed phrase، private key یا رسیدهای کاربران را commit نکن.

### تنظیمات اصلی backend

```env
DATABASE_URL=
REDIS_URL=

ADMIN_AUTH_ENABLED=true
ADMIN_AUTH_HEADER=X-Admin-Token
ADMIN_TOKENS=
SUPER_ADMIN_TOKENS=
ADMIN_TOKEN_MAP=
ADMIN_TOKEN_ROLE_MAP=
ADMIN_TG_USER_IDS=
SUPER_ADMIN_TG_USER_IDS=
RBAC_OWNER_USER_ID=

BOT_SERVICE_TOKEN=
BOT_SERVICE_USER_ID=999

TELEGRAM_BOT_TOKEN=
TELEGRAM_INITDATA_MAX_AGE_SECONDS=86400
TELEGRAM_INITDATA_HEADER=X-Tg-Init-Data

MINI_SESSION_SECRET=
MINI_SESSION_TTL_SEC=900
MINI_INITDATA_REPLAY_TTL_SEC=900
MINI_RATE_LIMIT_EVENTS_PER_SEC=2
MINI_RATE_LIMIT_WRITE_PER_MIN=20

DEFAULT_TG_GROUP_ID=
USER_FORUM_CHAT_ID=
USER_TOPIC_GAME_LOW_ID=
USER_TOPIC_GAME_MEDIUM_ID=
USER_TOPIC_GAME_HIGH_ID=

RECEIPTS_DIR=/app/storage/receipts
CORS_ALLOWED_ORIGINS=
```

### واریز کارت بانکی

در production بهتر است کارت‌ها از DB / پنل سوپرادمین مدیریت شوند. env فقط fallback یا bootstrap باشد.

```env
DEPOSIT_DESTINATION_SALT=davarna-pool-v1
DEPOSIT_DESTINATIONS_JSON=[]

DEPOSIT_CARD_NUMBER=
DEPOSIT_OWNER_NAME=
DEPOSIT_BANK_NAME=
DEPOSIT_IBAN=
DEPOSIT_ACCOUNT_NUMBER=
```

### واریز رمزارزی

```env
CRYPTO_PAYMENTS_ENABLED=false
CRYPTO_AUTO_CONFIRM_ENABLED=true
CRYPTO_CONFIRM_INTERVAL_SEC=45
CRYPTO_INVOICE_EXPIRE_MINUTES=15
CRYPTO_PAYMENT_GRACE_MINUTES=5

CRYPTO_MIN_TOMAN_AMOUNT=50000
CRYPTO_MAX_TOMAN_AMOUNT=50000000
CRYPTO_ADMIN_REVIEW_TOMAN_THRESHOLD=20000000

CRYPTO_DIRECT_WALLET_PAYMENTS_ENABLED=true
CRYPTO_WALLETCONNECT_PROJECT_ID=
CRYPTO_PUBLIC_APP_URL=

CRYPTO_TRON_USDT_ENABLED=true
CRYPTO_TRON_USDT_ADDRESS=
CRYPTO_TRON_USDT_CONTRACT=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
CRYPTO_TRONGRID_BASE_URL=https://api.trongrid.io
TRONGRID_API_KEY=

CRYPTO_TON_ENABLED=true
CRYPTO_TON_ADDRESS=
CRYPTO_TONCENTER_BASE_URL=https://toncenter.com
TONCENTER_API_KEY=
```

### تنظیمات اصلی bot

```env
TELEGRAM_BOT_TOKEN=
API_BASE_URL=http://backend:8000
REDIS_URL=redis://redis:6379/0

BOT_SERVICE_TOKEN=
ADMIN_API_TOKEN=
SUPER_ADMIN_API_TOKEN=

ADMIN_TG_USER_IDS=
SUPER_ADMIN_TG_USER_IDS=

BOT_JOIN_GROUP_ID=
BOT_JOIN_GROUP_INVITE_LINK=

ADMIN_FORUM_CHAT_ID=
ADMIN_TOPIC_GENERAL_ID=
ADMIN_TOPIC_DEPOSIT_ID=
ADMIN_TOPIC_WITHDRAW_ID=
ADMIN_TOPIC_GAMES_ID=
ADMIN_TOPIC_ALERTS_ID=
ADMIN_TOPIC_USERS_ID=

USER_FORUM_CHAT_ID=
USER_TOPIC_ANNOUNCE_ID=
USER_TOPIC_GAME_LOW_ID=
USER_TOPIC_GAME_MEDIUM_ID=
USER_TOPIC_GAME_HIGH_ID=
USER_TOPIC_LIVE_NUMBERS_ID=
USER_TOPIC_RESULTS_ID=
USER_TOPIC_RULES_ID=
USER_TOPIC_CHAT_ID=
```

---

## چک‌لیست عملیاتی

### بعد از هر deploy

```bash
curl -sS http://127.0.0.1:18080/health/db
docker compose --env-file .env.prod ps
docker compose --env-file .env.prod logs backend --tail=80
docker compose --env-file .env.prod logs bot --tail=80
```

### بررسی منبع کارت‌های واریز در DB

```bash
docker compose --env-file .env.prod exec -T backend python - <<'PY'
from app.core.db import SessionLocal
from app.models.settings import AppSetting

with SessionLocal() as db:
    row = db.get(AppSetting, "deposit_destinations")
    if not row:
        print("DB deposit_destinations = NOT SET")
    else:
        items = row.v_json if isinstance(row.v_json, list) else []
        print("DB deposit_destinations_count =", len(items))
        for i, d in enumerate(items, 1):
            card = ''.join(ch for ch in str(d.get("card_number", "")) if ch.isdigit())
            masked = card[:4] + "-" + "*" * max(0, len(card)-8) + "-" + card[-4:] if len(card) >= 8 else "-"
            print(i, d.get("title"), d.get("bank_name"), d.get("account_name"), masked, "active=", d.get("is_active", True))
PY
```

### بررسی fallback کارت‌های env

```bash
docker compose --env-file .env.prod exec -T backend python - <<'PY'
from app.core.config import DEPOSIT_DESTINATIONS, DEPOSIT_CARD_NUMBER

def mask(card):
    s = ''.join(ch for ch in str(card or '') if ch.isdigit())
    if len(s) < 8:
        return "-"
    return s[:4] + "-" + "*" * max(0, len(s)-8) + "-" + s[-4:]

print("env_json_destinations_count =", len(DEPOSIT_DESTINATIONS or []))
for i, d in enumerate(DEPOSIT_DESTINATIONS or [], 1):
    print(i, d.get("bank_name"), d.get("account_name"), mask(d.get("card_number")))

print("single_fallback_card =", mask(DEPOSIT_CARD_NUMBER))
PY
```

---

## نکات امنیتی

- repository را private نگه دار، مگر اینکه عمداً بخواهی public شود.
- `.env` و `.env.prod` را commit نکن.
- توکن ربات، توکن ادمین، API key، private key و seed phrase نباید داخل Git باشد.
- production باید HTTPS داشته باشد.
- `RECEIPTS_DIR` نباید مسیر public static باشد.
- رسیدهای کاربران و تاریخچه کیف پول اطلاعات مالی خصوصی هستند.
- نقش سوپرادمین را محدود نگه دار.
- تغییرات `app_settings` باید audit شود.
- اتصال کیف پول نباید seed phrase یا private key کاربر را ذخیره کند.
- تأیید پرداخت رمزارزی باید سمت سرور انجام شود.
- تأیید واریز کارت بانکی باید قابل پیگیری باشد و فقط از مسیر ledger انجام شود.

---

## تنظیمات پیشنهادی GitHub

### Description

```text
Telegram Mini App and Bot platform for Persian Davarna/Bingo games with wallet, admin controls, bank deposits, and crypto payments.
```

### Topics

```text
telegram-bot
telegram-mini-app
fastapi
aiogram
mysql
redis
docker
crypto-payments
ton
tron
bingo-game
wallet
admin-dashboard
```

### فایل‌های پیشنهادی

```text
README.md
README.fa.md
.env.example
.gitignore
docs/
docs/screenshots/
docs/deployment.md
docs/security.md
```

---

## Roadmap

- [x] ربات تلگرام
- [x] مینی‌اپ تلگرام
- [x] دفتر حساب کیف پول
- [x] خرید کارت
- [x] واریز کارت بانکی با بررسی رسید
- [x] درخواست برداشت
- [x] مدیریت بازی توسط ادمین
- [x] مدیریت نقش‌ها توسط سوپرادمین
- [x] چند کارت مقصد واریز
- [x] فاکتور رمزارزی TON/TRON
- [x] پرداخت رمزارزی با QR fallback
- [x] دکمه روشن/خاموش پرداخت رمزارزی
- [ ] دکمه روشن/خاموش کلی واریز کارت بانکی در پنل سوپرادمین
- [ ] CI برای compile/test
- [ ] گالری اسکرین‌شات
- [ ] مستندات کامل عملیات
- [ ] مستندات backup خودکار

---

## مجوز

این پروژه خصوصی و تجاری است. تمام حقوق محفوظ است، مگر اینکه فایل License جداگانه چیز دیگری مشخص کند.
