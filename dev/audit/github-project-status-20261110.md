# حسابرسی GitHub دبرنا — ۲۰ آبان ۱۴۰۵ (2026-11-10)

## روش و محدودیت
منابع: وضعیت جاری GitHub REST مخزن MR-P3Y/dabarna، PRهای باز، Issueهای باز، مقایسه شاخه‌ها و خروجی‌های ارائه‌شده از NODE2.
**مبنای اصلی تشخیص:** «کد نوشته شده»، «تست ایزوله پاس شده»، «روی Production فعال است» و «در main ادغام شده» چهار حالت متفاوت‌اند. هیچ Merge، حذف شاخه یا تغییر Production در این حسابرسی انجام نشد.

## شواهد عددی
- شاخه پیش‌فرض: `main`، SHA `4a41e6c016025f3fa8cfc694bc878e1d906a7dd1`.
- تعداد PR باز: **۱۶** و تمامشان **Draft**. Issues باز مستقل از PR: **۹** (#22، #23، #24، #25، #26، #27، #28، #29، #30).
- شاخه `feature/autopilot-readiness-system-games-20261110` نسبت به main **۴۷۲ commit ahead / zero behind** در زمان مقایسه (شامل زنجیره طولانی تغییرات؛ نه لزوماً ۴۷۲ ویژگی مستقل). ۱۶۳ فایل متفاوت.
- شاخه `feature/superadmin-command-center-v12-20261110` نسبت به main ۴۹۳ ahead / zero behind، ۱۷۲ فایل؛ این شاخه با UI-only Release PR #42 یکسان فرض نشود.
- Issue #21 و PR #31 بسته‌اند؛ بسته‌بودن به‌تنهایی وضعیت استقرار آخرین کد را اثبات نمی‌کند.

## تکمیل‌شده با شواهد مستقیم NODE2 (نه الزاماً merged)
| قابلیت | شواهد عملی | محدودیت |
|---|---|---|
| Autopilot LOW | بازی #88 ENDED؛ ۲ بازیکن، ۷ کارت، فروش ۳۵۰۰۰، جایزه ۳۱۵۰۰؛ تراکنش‌های 354/355 تطبیق کامل؛ replay در دیتابیس ایزوله ۳/۳ PASS | یک دور عملی؛ بدون اثبات تست stress |
| Autopilot MEDIUM | بازی #90 ENDED؛ فروش ۶۰۰۰، جایزه ۵۴۰۰؛ تراکنش‌های 364/367 به کاربر ۸، کلیدهای یکتا تطبیق | یک دور |
| Autopilot HIGH | بازی #93 ENDED؛ FULL_CARD v2؛ ۷۶ عدد؛ فروش ۱۴۰۰۰۰، جایزه ۱۲۶۰۰۰ به کاربر ۶، تراکنش 371؛ بدون تورنا مطابق قانون | یک دور |
| پایش ۵ دقیقه‌ای | نصب `/etc/cron.d/davarna-autopilot-monitor`؛ ۹/۹ آزمون، Telegram TEST_DELIVERED، دو ثبت history به وقت UTC 12:28 و 12:30؛ Cron active | خطا/ریکاوری واقعی هنوز تزریق و تست نشده |
| داشبورد countdown / readiness | Backend image `davarna-backend:auto-clock-92471d0132b4` و API/کدهای مرتبط روی شاخه‌های #43/#44؛ استقرار کنترل‌شده گزارش شده | انتشار تمام محتوای شاخه و PR برابر نیست |

## باز ولی دارای پیاده‌سازی یا Candidate
| ردیف | پیگیری | وضعیت قطعی از GitHub | تصمیم پیشنهادی |
|---|---|---|---|
| Autopilot foundation / Rules | PR #11، #12 | Draft؛ کدهای پایه و v2 موجود؛ Production برای سه سطح گردش بازی موفق داشته | انتخاب یک زنجیره canonical انتشار؛ بدون اجرای مجدد migration |
| UI/Forum release | PR #20، #33، #34 و candidateهای #35/#36/#37/#38 | هم‌پوشان و Draft؛ تست‌های ایزوله ذکر شده؛ انتشار نهایی کل ترکیب به طور مستقل اثبات نشده | یکی از candidateها را پس از بررسی deployed-image/patch و QA انتخاب، بقیه را بعداً close با لینک جایگزین؛ هرگز blind-merge |
| Superadmin UI | Issue #22؛ PR #39، #42 | Dashboards v1.1 و V1.2 UI-only در شاخه‌های متفاوت؛ وضعیت live کل تغییرات نیازمند verify | UI-only را از wallet proposal جدا نگه‌دار |
| Crypto address rotation | Issue #30؛ PR #41 (+#32) | نمونه proposal/validation و تاریخچه late-transfer فقط در دیتابیس ایزوله؛ فعال‌سازی آدرس واقعی و پایش old/new invoice کامل نیست | **NO-GO برای Production** تا تست scanner، authorization و reconciliation و مجوز مستقل |
| Telegram routes/rules | Issues #25/#27/#29؛ PR #33/#34 | مطابقت متن‌ها و ACK جزئی و تست‌شده؛ سناریوی واقعی اعلان/تاپیک مجزا و چرخه end-to-end تمام نشده | E2E واقعی امن و تصمیم درباره `USER_TOPIC_GAME_START_ID` |
| Notification UX | Issues #23/#24 | کد اولیه UI و اعلان موجود؛ معیارهای طراحی و تست زنده در Issue هنوز باز | پیاده‌سازی و visual QA مستقل |
| Winner popup | Issue #28 | popup نسخه قدیمی موجود؛ معیارهای جدید طراحی/چندبرنده و تست بصری تکمیل نشده | PR مستقل UI-only |
| Operations cleanup | Issue #26 | برنامه ثبت شده؛ اجرای پاک‌سازی NODE2 و GitHub هنوز انجام نشده | آخرین مرحله، فهرست فقط خواندنی قبل از هر حذف |
| Finance reject reason | Issue #21، PR #31 closed | کد و تست‌های مربوط ثبت شده‌اند؛ بسته بودن PR/Issue برابر تضمین انتشار آخرین نسخه نیست | برابری شناسه فایل/endpoint با Production را بعداً در inventory تأیید کن |

## ریسک‌های فوری
1. **Main از Production عقب است.** ادغام یک‌باره ۴۷۲ commit بدون ساخت ماتریس deployed-vs-source و آزمون مهاجرت/rollback خطرناک است.
2. **شاخه‌های release متعدد و متداخل‌اند** (#35–38). Merge هم‌زمان یا دوتایی زیر-PR و ترکیبی می‌تواند کد تکراری/ناهمساز بسازد.
3. **PR #41 مالی حساس است** و نباید با #42 UI-only یا #44 Production worker ترکیب و کورکورانه منتشر شود.
4. **مدل استقرار image overlay** به معنی یکسان بودن ایمیج نهایی با کل head شاخه نیست؛ آشتی کد production باید با `docker inspect` + patch manifest + git SHA انجام شود.
5. مانیتور هر پنج دقیقه فعال است، اما نیاز به logrotate، سنجش حجم history، و تست ارزیابی قطعی recovery دارد.

## برنامه مرتب‌سازی، بدون اقدام مخرب
1. گزارش فقط خواندنی از NODE2: Compose config chain، SHA/ID imageهای backend/bot، migration head، cron، مصرف دیسک، مسیر backup؛ با ماسک secrets.
2. تهیه `deployed-manifest`: برای هر فایل یا patch مشخص کنیم از کدام SHA و PR ساخته شده؛ سپس release canonical بدون افزودن ویژگی مالی.
3. تعیین یک release candidate مرجع (#37 در صورت تطبیق، یا یک consolidated new RC)، و تعیین تکلیف #35/#36/#38 پس از review و تأیید.
4. لیست جداگانه کارهای Product Issues #23/#24/#28 و Telegram Issues #25/#27/#29؛ آزادسازی هم‌زمان ممنوع.
5. چک مالی/امنیتی #30 در دیتابیس ایزوله؛ عدم انتشار فعال‌سازی آدرس تا مجوز جداگانه.
6. فقط پس از QA و backup، merge/tag/release؛ Issue #26 cleanup آخر کار، **بدون حذف خودکار**.

**محدوده بررسی:** داده‌های GitHub تا تاریخ ساخت سند + شواهد NODE2 در همین گفتگو؛ هیچ تضمین خودکار برای CI یا deployed-state فراتر از شواهد موجود.
