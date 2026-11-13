# تعیین تکلیف PRها — ۱۳ نوامبر ۲۰۲۶

به‌روزرسانی پس از انتشار: PR #52 با تأیید مالک Merge و منتشر شد؛ Release اکنون `a7f3883ca0dcc4f98f0de2f84c0dbbb03088cba6` است. GitHub، #51 را نیز Merge‌شده تشخیص داد. #53 همچنان Draft است و فقط مقصد آن به Release به‌روز شد. PRهای #11، #12، #20، #33، #34، #35، #36 و #38 با دلیل مستند بسته شده‌اند؛ شاخه‌ها حفظ شده‌اند. [رسید انتشار](deployment.md).

جدول زیر مبنای حسابرسی پیش از این اقدامات را حفظ می‌کند: API تمام صفحات PRهای باز را خوانده بود (۱۹ PR، Release آن زمان `98fcce1dd2e127366367b378d47150530bb9b850`). شماره‌های ۲۱ تا ۳۰ در فهرست درخواست‌ها Issue هستند، نه PR. وضعیت‌های «بستن» و «آماده Merge» در این جدول پیشنهاد همان زمان‌اند؛ نتیجه اجرا در بند بالا آمده است.

| PR | وضعیت | وابستگی | ریسک | اقدام پیشنهادی | دلیل |
|---|---|---|---|---|---|
| [#11](https://github.com/MR-P3Y/dabarna/pull/11) | تکراری اثبات‌شده | `main` | کم برای بستن | بستن PR با حفظ شاخه | تمام Head در تاریخچه Release فعلی است؛ نیاز به Merge دوباره ندارد |
| [#12](https://github.com/MR-P3Y/dabarna/pull/12) | تکراری اثبات‌شده | `feature/autopilot-foundation-20261031` | کم برای بستن | بستن PR با حفظ شاخه | تمام Head در تاریخچه Release فعلی است؛ نیاز به Merge دوباره ندارد |
| [#17](https://github.com/MR-P3Y/dabarna/pull/17) | عملیات مالی مستقل | `feature/ui-ux-refresh-tambola-v2-20261106` | بسیار بالا | باز بماند؛ تأیید عملیات مالی لازم | اسکریپت بازپرداخت بازی ۸۴؛ هیچ اجرای واقعی مجاز/انجام‌شده در این مأموریت نیست |
| [#20](https://github.com/MR-P3Y/dabarna/pull/20) | تکراری اثبات‌شده | `feature/ui-ux-refresh-tambola-v2-20261106` | کم برای بستن | بستن PR با حفظ شاخه | تمام Head در تاریخچه Release فعلی است؛ نیاز به Merge دوباره ندارد |
| [#32](https://github.com/MR-P3Y/dabarna/pull/32) | شاخه بازبینی مالی مستقل | `release/combined-forum-mini-candidate-20261107` | بالا، ۳ Migration مستقل | عدم Merge در نسخه غیرمالی | صف بررسی و طرح مالی قدیمی؛ جایگزینی کامل با #49 اثبات نشده |
| [#33](https://github.com/MR-P3Y/dabarna/pull/33) | تکراری اثبات‌شده | `release/combined-forum-mini-candidate-20261107` | کم برای بستن | بستن PR با حفظ شاخه | تمام Head در تاریخچه Release فعلی است؛ نیاز به Merge دوباره ندارد |
| [#34](https://github.com/MR-P3Y/dabarna/pull/34) | نامزد تاریخی منسوخ | `fix/game-forum-notices-rule-routing-20261109` | کم برای بستن | بستن PR با حفظ شواهد و شاخه | رفتار runtime در Release؛ فقط 1 patch مستقل از نوع مستند/اسکریپت ممیزی قدیمی باقی است |
| [#35](https://github.com/MR-P3Y/dabarna/pull/35) | نامزد تاریخی منسوخ | `release/combined-forum-mini-candidate-20261107` | کم برای بستن | بستن PR با حفظ شواهد و شاخه | رفتار runtime در Release؛ فقط 2 patch مستقل از نوع مستند/اسکریپت ممیزی قدیمی باقی است |
| [#36](https://github.com/MR-P3Y/dabarna/pull/36) | نامزد تاریخی منسوخ | `release/combined-forum-mini-candidate-20261107` | کم برای بستن | بستن PR با حفظ شواهد و شاخه | رفتار runtime در Release؛ فقط 3 patch مستقل از نوع مستند/اسکریپت ممیزی قدیمی باقی است |
| [#37](https://github.com/MR-P3Y/dabarna/pull/37) | Head همان Release فعلی | `release/combined-forum-mini-candidate-20261107` | بالا برای Merge تاریخی | حفظ شاخه؛ تصمیم مستقل درباره مقصد قدیمی | PR به combined-forum قدیمی می‌رود؛ بستن یا Merge آن نباید مبنای Release را عوض کند |
| [#38](https://github.com/MR-P3Y/dabarna/pull/38) | نامزد تاریخی منسوخ | `release/combined-forum-mini-candidate-20261107` | کم برای بستن | بستن PR با حفظ شواهد و شاخه | رفتار runtime در Release؛ فقط 2 patch مستقل از نوع مستند/اسکریپت ممیزی قدیمی باقی است |
| [#41](https://github.com/MR-P3Y/dabarna/pull/41) | تعارض GitHub تأییدشده | `feature/superadmin-live-dashboard-v11-20261109` | بسیار بالا؛ UI V1.2 و مالی | عدم Merge؛ انتقال انتخابی مالی در PR جدا | mergeable=false؛ UI قدیمی و زیرساخت مالی درهم‌آمیخته است |
| [#43](https://github.com/MR-P3Y/dabarna/pull/43) | رفتار انتخابی جایگزین‌شده در #50 | `release/superadmin-command-ui-v12-20261110` | بالای Regression V1.3 | عدم Merge کلی؛ ثبت جایگزینی و نگهداری تاریخچه | شماره‌خوان، آمادگی، countdown و متن‌ها در مبنای فعلی یکپارچه‌اند؛ همه commitهای قدیمی عیناً وارد نشده‌اند |
| [#44](https://github.com/MR-P3Y/dabarna/pull/44) | رفتار انتخابی جایگزین‌شده در #50 | `hotfix/auto-draw-worker-start-guard-20261110` | بالای Regression V1.3 | عدم Merge کلی؛ ثبت جایگزینی و نگهداری تاریخچه | شماره‌خوان، آمادگی، countdown و متن‌ها در مبنای فعلی یکپارچه‌اند؛ همه commitهای قدیمی عیناً وارد نشده‌اند |
| [#46](https://github.com/MR-P3Y/dabarna/pull/46) | پیش‌فرض انتشار منسوخ | `release/davarna-v1-candidate-20261109` | بالای عملیاتی | از اسکریپت استفاده نشود؛ برنامه جدید جایگزین | به Image و Compose پیش از #50 مقید است، حتی اگر از نظر Git ادغام‌پذیر باشد |
| [#47](https://github.com/MR-P3Y/dabarna/pull/47) | رفتار انتخابی جایگزین‌شده در #50 | `feature/autopilot-readiness-system-games-20261110` | بالای Regression V1.3 | عدم Merge کلی؛ ثبت جایگزینی و نگهداری تاریخچه | شماره‌خوان، آمادگی، countdown و متن‌ها در مبنای فعلی یکپارچه‌اند؛ همه commitهای قدیمی عیناً وارد نشده‌اند |
| [#48](https://github.com/MR-P3Y/dabarna/pull/48) | رفتار انتخابی جایگزین‌شده در #50 | `feature/autopilot-game-start-countdown-20261110` | بالای Regression V1.3 | عدم Merge کلی؛ ثبت جایگزینی و نگهداری تاریخچه | شماره‌خوان، آمادگی، countdown و متن‌ها در مبنای فعلی یکپارچه‌اند؛ همه commitهای قدیمی عیناً وارد نشده‌اند |
| [#49](https://github.com/MR-P3Y/dabarna/pull/49) | مالی منتخب در شاخه جدید منتقل شد | `feature/superadmin-command-center-v12-20261110` | بالای مالی | مراجعه به PR مالی جدید؛ فعلاً Draft | Base برابر V1.2 است؛ تست MySQL نهایی و رفع تأیید قدیمی/لغو/TON روی مبنای فعلی انجام شد؛ تاریخچه فاکتور همچنان مانع فعال‌سازی است |
| [#51](https://github.com/MR-P3Y/dabarna/pull/51) | آماده Merge با تأیید | `release/davarna-v1-candidate-20261109` | کم | قبل از PR غیرمالی یا همراه آن | فقط تست و رسید انتشار؛ Head در تاریخچه نامزد غیرمالی است |

## تست، Migration و خطر UI

جزئیات آزمون هر Head قدیمی در [حسابرسی قبلی](../integration-20261111/prs.md) محفوظ است؛ این گزارش آن تست‌ها را به‌عنوان اجرای تازه روی شاخه‌های قدیمی معرفی نمی‌کند. آزمون کامل روی شاخه‌های یکپارچه فعلی در report.md و گزارش مالی ثبت شده است. آزمون موفق شاخه جدید مجوز اجرای refund یا migration شاخه قدیمی نیست.

برای هر PR، SHA، merge-base، فایل‌های تغییرکرده، مسیرهای مالی و Migration و commitهای patch-unique در [pr-evidence.json](pr-evidence.json) موجود است. Migrationهای #11/#12/#20 مربوط به تاریخچه‌ای هستند که از قبل در Release وجود دارد؛ اجرای مجدد آن‌ها لازم نیست. دو PR جدید revision دیتابیس اضافه نمی‌کنند.

زنجیره قدیمی #43 → #44 → #47 → #48 حفظ شده و علت عدم Merge زنجیره‌ای همین مبنای قدیمی و UI/مالی نامرتبط است. PR مالی جدید روی PR غیرمالی جدید قرار می‌گیرد؛ ترتیب ادغام در صورت تأیید: #51 (اختیاری جداگانه)، نامزد غیرمالی، سپس تصمیم مستقل درباره مالی. #49 را مستقیماً روی Release Merge نکنید.

## گروه‌بندی

- آماده بازبینی نهایی و Merge با تأیید: #51 و PR نامزد غیرمالی جدید.
- نیازمند اصلاح/تصمیم/تأیید مستقل: #17، #32، #37، #41، #46، #49 و PR مالی جدید (Draft).
- تکراری یا منسوخ: #11، #12، #20، #33 و نامزدهای تاریخی #34، #35، #36، #38. #43، #44، #47، #48 از نظر رفتار موردنظر جایگزین شده‌اند؛ commitهای عملیاتی تاریخی آن‌ها نگه داشته می‌شوند.

بستن PR به‌معنی حذف شاخه، حذف تاریخچه یا Merge کد نیست. نتیجه واقعی تغییر وضعیت‌ها در PRهای GitHub و ضمیمه وضعیت نهایی ثبت می‌شود.

## نتیجه اجرایی ۱۳ نوامبر

[PR #52 غیرمالی](https://github.com/MR-P3Y/dabarna/pull/52) باز شد؛ [PR #53 مالی](https://github.com/MR-P3Y/dabarna/pull/53) روی آن به‌صورت Draft باز شد. هر دو در بازخوانی GitHub mergeable=true بودند؛ این فقط نبود تعارض Git است و تأیید مالی یا انتشار نیست.

پس از بازخوانی Head و تطبیق با شواهد، PRهای **#11، #12، #20، #33، #34، #35، #36، #38 بسته شدند** و دلیل مستند به متن هر PR اضافه شد. هیچ شاخه‌ای حذف و هیچ PRی Merge نشد. PRهای #43/#44/#47/#48 برای نگهداری تفاوت‌های تاریخی باز مانده‌اند ولی Merge کلی آن‌ها توصیه نمی‌شود. #49 به نامزد مالی #53 ارجاع داده شده است. #51 داخل تاریخچه #52 است.

## #34: تفاوت مستقل با Release

- `dev/release/check-v1-readiness-20261109.sh`

## #35: تفاوت مستقل با Release

- `dev/release/davarna-v1-rc-readonly-gate-20261109.sh`
- `dev/release/davarna-v1-release-scope-20261109.md`

## #36: تفاوت مستقل با Release

- `dev/release/v1-rc-preflight-readonly-20261109.sh`
- `dev/release/v1.0.0-rc1-freeze-20261109.md`

## #38: تفاوت مستقل با Release

- `dev/release/v1-freeze-readme-20261109.md`
- `dev/release/v1-readiness-only-20261109.sh`

