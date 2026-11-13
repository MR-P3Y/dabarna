// Display only. The Backend owns every deadline and transition.
export function automationClock(item, nowMs, lastReceivedMs) {
  const labels = {START:'شروع بازی', NEXT_NUMBER:'عدد بعدی', NEXT_GAME:'بازی بعدی'};
  const states = {WAITING:'در انتظار تأیید سرور', WAITING_PLAYERS:'در انتظار آمادگی و حداقل بازیکن',
    MANUAL:'مدیریت دستی', MANUAL_START:'در انتظار شروع توسط مدیر', MANUAL_DRAW:'شماره‌خوان دستی',
    PAUSED:'شماره‌خوان موقتاً متوقف است', NOT_READY:'پیش‌نیازهای بازی آماده نیست',
    MISSING_END_TIME:'زمان پایان بازی قبلی ثبت نشده', AWAITING_CREATION:'در انتظار ساخت بازی'};
  if (!item || !['LOW','MEDIUM','HIGH'].includes(item.level)) return null;
  if (!Number.isFinite(lastReceivedMs) || nowMs-lastReceivedMs>15000) {
    return {label:'اطلاعات تازه در دسترس نیست',seconds:null,progress:0,pending:true};
  }
  if (!labels[item.phase]) return {label:states[item.phase] || 'وضعیت نامشخص',seconds:null,progress:0,pending:false};
  const deadline=Date.parse(item.deadline_utc || '');
  if (!Number.isFinite(deadline)) return {label:'زمان بعدی هنوز ثبت نشده',seconds:null,progress:0,pending:true};
  const seconds=Math.max(0,Math.ceil((deadline-nowMs)/1000));
  return {label:seconds>0 ? 'تا '+labels[item.phase] : 'در انتظار تأیید سرور برای '+labels[item.phase],
    seconds,progress:Math.min(100,Math.max(0,seconds/Math.max(1,Number(item.duration_seconds)||1)*100)),pending:seconds===0};
}
