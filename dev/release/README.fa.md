# انتشار کنترل‌شده پنج موج UI/UX دبرنای طوفان

## وضعیت انتشار

شاخه توسعه: \`feature/ui-ux-refresh-tambola-v2-20261106\`  
نسخه پایه‌ای که UI/UX روی آن ساخته شد: \`937ef711a9db45d85099e066733ceede72848cf1\`

- پنج موج آزمایش اختصاصی JavaScript و Python روی NODE2 موفق بوده‌اند.
- تغییرات مشاهده‌شده نسبت به پایه شامل Mini App، قرارداد خواندنی کیف پول، برچسب جوایز ربات، و تست‌هاست.
- از مقایسه GitHub، فایلی در \`backend/alembic/\` یا Dockerfile تغییر نکرده است؛ اما **وضعیت واقعی Migration و ایمیج فعال Production باید جداگانه از NODE2 خوانده شود**.
- Staging روی NODE2 به دلیل RAM قابل‌استفاده ~۱۵۲۹ MiB و Swap بالا رد شده بود. **ساخت ایمیج روی همین میزبان هم بدون کنترل منابع خطر دارد.**

## ترتیب الزامی (بدون عبور از مراحل)

۱. **شناسایی Production — فقط خواندنی:** اجرای \`bash dev/release/inventory.sh\`. بررسی مسیر کاری واقعی Compose، فایل پیکربندی آن، ایمیج‌های در حال اجرا و سلامت چهار کانتینر. این کار هیچ سرویسی را تغییر نمی‌دهد.

۲. **قفل نسخه و بررسی منابع:** اطمینان از اینکه نسخه فعال از پایه \`937ef...\` یا نسخه سازگار آن است؛ اگر نسخه فعال جدیدتر و متفاوت باشد، از انتشار مستقیم این شاخه جلوگیری شود. بررسی RAM و دیسک پیش از Build.

۳. **بکاپ قابل تأیید قبل از هر تغییر:** تهیه Dump سازگار MySQL (با \`--single-transaction\`، بدون نگهداری رمز در لاگ)، ذخیره فایل‌های رسید و تنظیمات فعلی در پوشه root-only، ثبت SHA256 و حجم فایل‌ها، و حفظ شناسه ایمیج‌های فعال. تست صحت آرشیو و Dump بدون بازیابی روی دیتابیس اصلی. **هرگز از فایل‌های .env تولیدی برای Staging استفاده نشود.**

۴. **آماده‌سازی بازگشت:** از هر دو ایمیج در حال اجرای Backend/Bot، تگ rollback منحصر‌به‌فرد بسازید و پیش از جایگزینی، وجود آن‌ها را بررسی کنید. مسیر Compose واقعی Production باید مشخص باشد، نه checkout شاخه آزمایشی.

۵. **ساخت/انتقال ایمیج با حداقل فشار:** Build مرحله‌ای و با کنترل منابع؛ برای CPU/RAM محدود NODE2، در صورت ریسک OOM ساخت خارج از سرور و انتقال ایمیج ترجیح دارد. هیچ تغییر خودکار MySQL یا فعال‌شدن ناخواسته Autopilot پذیرفته نیست.

۶. **استقرار مرحله‌ای:** ابتدا Backend، سپس بررسی سلامت DB/Redis/API/مینی‌اپ و فقط پس از موفقیت، Bot. اجرای هر دو سرویس باید با همان Compose project اصلی و بدون \`down\`/پاک‌سازی volume انجام شود.

۷. **Smoke test و مشاهده:** سلامت API، بازی‌های فعال، بررسی خطاهای لاگ، مسیرهای نمایشی، ربات و اعلان‌ها. تراکنش/خرید آزمایشی با حساب واقعی بدون هماهنگی و تضمین برگشت انجام نشود.

۸. **بازگشت سریع در صورت خطا:** ایمیج‌های قبل را با Compose واقعی بازگردانید. **به طور معمول دیتابیس اصلی را به زمان قبل برنگردانید**؛ بازگردانی دیتابیس پس از پذیرش تراکنش‌های واقعی می‌تواند تراکنش یا موجودی کاربران را از بین ببرد. بکاپ DB فقط برای بازیابی فاجعه با برنامه مستقل است.

## ممنوعیت‌های این انتشار

- عدم اجرای \`docker compose down -v\` یا \`docker system prune\` روی NODE2.
- عدم کپی Production DB/توکن اصلی به نمونه آزمایشی.
- عدم پاک‌کردن کانتینرهای قدیمی \`davarna-withdraw-mig-mysql\`، \`davarna-pr4-redis\` یا \`node\` قبل از بررسی وابستگی‌ها.
- عدم تغییر flagهای Runtime شماره‌خوان، Autopilot یا پرداخت در جریان این انتشار.
- عدم ری‌استارت یا Upgrade سیستم‌عامل در همان بازه انتشار.
- عدم تغییر خودکار پیام‌های پین‌شده گروه با تغییر markerهای Bot.

## مرحله بکاپ بعد از خروجی موفق Inventory

اکنون `dev/release/backup-production.sh` نیز در همین شاخه آماده است. اسکریپت قبل از شروع **ایمیج‌های پایه، سلامت چهار کانتینر، مسیر واقعی Volumeهای Storage، فایل‌های Compose و ظرفیت دیسک** را کنترل می‌کند؛ سپس به‌صورت متوالی موارد زیر را در پوشه‌ای با مجوز فقط root ذخیره می‌کند:

- Dump منطقی پایگاه داده با `mysqldump --single-transaction --skip-lock-tables` و بررسی سلامت `gzip`.
- فایل‌های رسید Backend و Storage ربات، همراه با اعتبارسنجی آرشیو `tar.gz`.
- همه فایل‌های Compose شناسایی‌شده از Label کانتینرها، نسخه خصوصی فایل‌های محیطی شناخته‌شده و فایل بسیار حساس `configs/runtime-private.json` حاوی تنظیمات مؤثر کانتینرها. **این فایل ممکن است توکن و رمز داشته باشد؛ هرگز محتوایش را در چت، GitHub یا لاگ منتشر نکنید.**
- آرشیو کامل ایمیج‌های در حال اجرای Backend/Bot برای Rollback.
- فایل `SHA256SUMS` برای بررسی یکپارچگی همه فایل‌ها.

**فرمان مرحله بکاپ (بعد از موفقیت Inventory):**

```bash
cd /opt/davarna-v2
git pull --ff-only origin feature/ui-ux-refresh-tambola-v2-20261106
bash -n dev/release/backup-production.sh
bash dev/release/backup-production.sh
```

در پایان باید `===== BACKUP VERIFIED =====` دیده شود. این فرایند سرویس را ری‌استارت نمی‌کند و اطلاعات جدید را به دیتابیس نمی‌نویسد، اما خواندن دیتابیس، آرشیو ایمیج‌ها و Storage مصرف I/O و CPU دارد؛ در ساعات خلوت اجرا شود. اگر مانع یا شکست رخ دهد، انتشار متوقف است و اسکریپت آرشیو ناقص ساخته‌شده توسط خود را حذف می‌کند. هیچ دستور `docker compose up` یا Migration در این مرحله وجود ندارد.

## گام بعد از بکاپ — ایمیج نامزد انتشار بدون دست‌زدن به Production

بکاپ `release-20261106T164544Z.TV2FyH` از نظر `gzip/tar/SHA256` در NODE2 بررسی شد. بازیابی عملی دیتابیس هنوز در محیط مستقل آزمایش نشده است.

برای جلوگیری از Build سنگین `npm ci` و `pip install` با RAM محدود NODE2، دو Dockerfile کوچک فقط **فایل‌های تغییرکرده این پنج موج** را روی همان ایمیج‌های ثابت `v2-937ef711a9db` قرار می‌دهند. هیچ فایل `.env` وارد Build Context نمی‌شود؛ شبکه Build و تست نیز `none` است.

```bash
(
  set -Eeuo pipefail
  cd /opt/davarna-v2
  git pull --ff-only origin feature/ui-ux-refresh-tambola-v2-20261106
  bash -n dev/release/build-candidates.sh
  DAVARNA_RELEASE_BACKUP=/root/davarna-v2-release-backups/release-20261106T164544Z.TV2FyH \
    bash dev/release/build-candidates.sh
)
```

اسکریپت ابتدا checksum بکاپ و تطابق ایمیج‌های در حال اجرا را کنترل می‌کند، سپس:

- از تصاویر فعلی تگ‌های `rollback-20261106-937ef711` می‌سازد (کانتینرها را تغییر نمی‌دهد).
- از `git archive` تنها ۶ فایل تغییرکرده Backend و ۷ فایل تغییرکرده Bot را به پوشه موقت Build می‌برد؛ هیچ secret، کل ریپو یا storage وارد Context نمی‌شود.
- ایمیج Backend و Bot را **جداگانه و بدون شبکه** می‌سازد، سپس `compileall` آن‌ها را در کانتینرهای موقت بدون شبکه اجرا می‌کند.
- مشخصات نامزد را در `/root/davarna-v2-release-backups/candidate-ux5-<commit>.txt` با دسترسی root-only ذخیره می‌کند.
- چنانچه RAM آزاد پیش از Build کمتر از ۱۲۸۰ MiB باشد، اقدام را متوقف می‌کند. این آستانه تضمین عدم فشار نیست؛ مصرف منابع حین عملیات باید بررسی شود.

**شرط مهم:** `CANDIDATE IMAGES VERIFIED` فقط یعنی ایمیج‌ها ساخته شده‌اند و Syntax پایتون سالم است؛ به معنای انتشار موفق یا آماده‌شدن تمام سناریوهای واقعی نیست.

**هنوز نباید** `docker compose up` اجرا شود. از آنجا که کانتینرهای Backend و Bot به Compose overrideهای متفاوتی متصل‌اند (از جمله فایل خصوصی `/root/davarna-v2-release-backups/tambola-v2-manual.compose.yml` برای Backend)، دستور بازآفرینی باید بعد از بررسی تنظیمات دقیق نسخه‌های نامزد آماده شود. این فایل خصوصی یا اطلاعات `runtime-private.json` را در چت منتشر نکنید.

## گام ایمن قبل از جابه‌جایی کانتینرها — تطبیق واقعی Compose

ایمیج‌های نامزد زیر روی NODE2 با پیام `CANDIDATE IMAGES VERIFIED` ساخته شدند:

- Backend: `davarna-backend:ux5-f3c649e22593`
- Bot: `davarna-bot:ux5-f3c649e22593`
- Rollback Backend: `davarna-backend:rollback-20261106-937ef711`
- Rollback Bot: `davarna-bot:rollback-20261106-937ef711`

کانتینرهای فعلی با زنجیره Compose متفاوت ساخته شده‌اند:

- Backend: `/opt/davarna/docker-compose.yml` + `/opt/davarna-v2/deploy/tambola-v2-inactive.compose.yml` + `/root/davarna-v2-release-backups/tambola-v2-manual.compose.yml`
- Bot: همان دو فایل اول، **بدون** فایل دستی اضافی Backend.

**احتیاط:** از `docker compose up` عمومی یا یک زنجیره یکسان برای هر دو سرویس استفاده نشود.

`dev/release/ux5-candidate.compose.yml` فقط نام ایمیج‌ها را تنظیم می‌کند. `dev/release/predeploy-audit.sh` برای هر سرویس همان زنجیره Compose اولیه را به همراه این لایه تصویری رندر می‌کند و *بدون اجرا* با کانتینر فعال مقایسه می‌کند:

- تغییر ناخواسته متغیرهای محیطی یا Flagها (بدون افشای مقادیر رمزها)
- تغییر پورت‌های منتشرشده یا Bind Mountها
- تغییر Restart Policy یا تنظیمات امنیتی
- عدم تطابق ایمیج نامزد با Build تأییدشده

```bash
cd /opt/davarna-v2
git pull --ff-only origin feature/ui-ux-refresh-tambola-v2-20261106
bash -n dev/release/predeploy-audit.sh
bash dev/release/predeploy-audit.sh
```

**فقط** خروجی `PREDEPLOY CONFIG MATCH: IMAGE-ONLY CHANGE` مجوز رفتن به مرحله ساخت دستور انتشار است؛ این خروجی خودش هیچ سرویس اصلی را تغییر نمی‌دهد. در صورت `NO-GO` باید علت بررسی شود و هیچ‌یک از guardها را حذف نکنیم. رندر Compose در فضای موقت root-only انجام می‌شود؛ فایل JSON موقت شامل مقادیر حساس است و به‌صورت خودکار حذف خواهد شد.

## اولین فرمان مجاز

\`\`\`bash
cd /opt/davarna-v2
git pull --ff-only origin feature/ui-ux-refresh-tambola-v2-20261106
bash dev/release/inventory.sh
\`\`\`

پس از مشاهده خروجی Inventory، دستور بکاپ و استقرار باید برای **مسیر و تصویر واقعی Production** تنظیم شود؛ نه بر پایه حدس.
