(() => {
  const key = 'davarna_ui_language';
  const english = document.documentElement.lang === 'en';
  let saved = null;
  try { saved = localStorage.getItem(key); } catch (_) {}
  // Explicit English links work even before a preference has been saved.
  if (!english && saved === 'en') {
    const target = new URL('en.html', location.href);
    target.search = location.search; target.hash = location.hash;
    location.replace(target.href);
    return;
  }
  document.addEventListener('DOMContentLoaded', () => {
    const select = document.getElementById('languageSelect');
    if (!select) return;
    select.value = english ? 'en' : 'fa';
    select.addEventListener('change', () => {
      const language = select.value;
      if (!['fa', 'en'].includes(language) || language === (english ? 'en' : 'fa')) return;
      const message = english
        ? 'Changing language reloads this page. Unsaved entries will be lost. Continue?'
        : 'تغییر زبان صفحه را دوباره بارگذاری می‌کند و اطلاعات واردشدهٔ ذخیره‌نشده از دست می‌رود. ادامه می‌دهید؟';
      if (!window.confirm(message)) { select.value = english ? 'en' : 'fa'; return; }
      try { localStorage.setItem(key, language); } catch (_) {}
      const target = new URL(language === 'en' ? 'en.html' : 'index.html', location.href);
      target.search = location.search; target.hash = location.hash;
      location.assign(target.href);
    });
  });
})();
