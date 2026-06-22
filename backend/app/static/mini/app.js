const tg = window.Telegram?.WebApp;

const state = {
  token: null,
  tokenExp: 0,
  authReady: false,
  selectedGameId: null,
    adminWithdrawWalletStatus: new Map(),
  lastEventId: 0,
  pollTimer: null,
  depositDestinations: [],
  cardsPollTimer: null,
  cardsPrevCalledByGame: {},
  cardsLatestSeenEventByGame: {},
  cardsPullBusy: false,
  currentUserId: 0,
  lastWinnerEventId: 0,
  lastWinnerModalKey: "",
  gameSnapshots: new Map(),
  myCardsByGame: new Map(),
  walletTxs: [],
  recentGamesStats: [],
  dashboardTrust: null,
  hotGameId: null,
  userFlags: {
    inGame: false,
    recentWinner: false,
  },
  latestLiveNumberByGame: {},
  globalRefreshTimer: null,
  historyModalCtx: null,
  toastTimer: null,
  adminNotifyTimer: null,
  adminNotifyCurrent: null,
  audioCtx: null,
  soundEnabled: false,
  receiptPreviewUrl: null,
  splashHidden: false,
  gamesCache: [],
  walletCache: {
    balance: null,
    txs: null,
    deposits: null,
    withdraws: null,
    destinations: null,
  },
  admin: {
    enabled: false,
    isSuper: false,
    roles: [],
    selectedGameId: 0,
    gamesById: new Map(),
    liveLinksByGame: new Map(),
    users: {
      selectedTgUserId: 0,
      lastQuery: "",
      reportMode: "none",
      profile: null,
    },
    notify: {
      ready: false,
      lastDepositId: 0,
      lastWithdrawId: 0,
      checking: false,
    },
    create: {
      groupId: null,
      topics: [],
      enforceTopic: false,
      selectedTopicId: null,
    },
  },
};

const MINI_SESSION_STORAGE_KEY = "davarna_mini_session_v1";
const FETCH_RETRY_DELAY_MS = 350;

function _nowSec() {
  return Math.floor(Date.now() / 1000);
}

function clearMiniSession() {
  state.token = null;
  state.tokenExp = 0;
  state.authReady = false;
  state.currentUserId = 0;
  try {
    sessionStorage.removeItem(MINI_SESSION_STORAGE_KEY);
  } catch (_) {}
}

function persistMiniSession() {
  const token = String(state.token || "").trim();
  const tokenExp = Number(state.tokenExp || 0);
  const userId = Number(state.currentUserId || 0);
  if (!token || !Number.isFinite(tokenExp) || tokenExp <= 0) return;
  try {
    sessionStorage.setItem(
      MINI_SESSION_STORAGE_KEY,
      JSON.stringify({
        token,
        tokenExp: Math.trunc(tokenExp),
        userId: Number.isFinite(userId) && userId > 0 ? Math.trunc(userId) : 0,
      })
    );
  } catch (_) {}
}

function restoreMiniSession() {
  try {
    const raw = sessionStorage.getItem(MINI_SESSION_STORAGE_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    const token = String(parsed?.token || "").trim();
    const tokenExp = Number(parsed?.tokenExp || 0);
    const userId = Number(parsed?.userId || 0);
    if (!token || !Number.isFinite(tokenExp) || tokenExp <= _nowSec() + 20) {
      sessionStorage.removeItem(MINI_SESSION_STORAGE_KEY);
      return false;
    }
    state.token = token;
    state.tokenExp = Math.trunc(tokenExp);
    state.currentUserId = Number.isFinite(userId) && userId > 0 ? Math.trunc(userId) : 0;
    state.authReady = true;
    return true;
  } catch (_) {
    return false;
  }
}

const authBadge = document.getElementById("authBadge");
const liveGameMeta = document.getElementById("liveGameMeta");
const headerUserName = document.getElementById("headerUserName");
const headerWalletBalance = document.getElementById("headerWalletBalance");
const headerUserStatus = document.getElementById("headerUserStatus");

const STATUS_LABELS = {
  LOBBY: "در انتظار شروع",
  RUNNING: "در حال اجرا",
  ENDED: "پایان‌یافته",
  CANCELLED: "لغو شده",
  ACTIVE: "فعال",
  PENDING: "در انتظار",
  APPROVED: "تایید شده",
  REJECTED: "رد شده",
};

const DEPOSIT_STATUS_LABELS = {
  AWAITING_RECEIPT: "منتظر رسید",
  PENDING_REVIEW: "در انتظار بررسی ادمین",
  APPROVED: "تایید شده",
  REJECTED: "رد شده",
};

const WITHDRAW_STATUS_LABELS = {
  PENDING: "در انتظار بررسی",
  APPROVED: "تایید شده",
  REJECTED: "رد شده",
  PAID: "پرداخت شده",
  CANCELLED: "لغو شده",
};

const EVENT_KIND_LABELS = {
  GAME_CREATED: "ایجاد بازی",
  GAME_STARTED: "شروع بازی",
  GAME_ENDED: "پایان بازی",
  GAME_CANCELLED: "لغو بازی",
  GAME_LOBBY_CLOSED: "بسته شدن لابی",
  NUMBER_CALLED: "اعلام عدد",
  NUMBER_UNDONE: "حذف آخرین عدد",
  CARDS_PURCHASED: "خرید کارت",
  CARD_BOUGHT: "خرید کارت",
  PRIZE_COL: "برد ستونی(تورنا)",
  PRIZE_ROW: "برد سطری(تمام)",
  CLAIM_SUBMITTED: "ثبت ادعا",
  CLAIM_APPROVED: "تایید ادعا",
  CLAIM_REJECTED: "رد ادعا",
  WINNER_DECLARED: "اعلام برنده",
};

const ACTIVE_GAME_STATUSES = new Set(["LOBBY", "RUNNING"]);
const CARDS_REFRESH_INTERVAL_MS = 2200;
const GLOBAL_REFRESH_INTERVAL_MS = 12000;
const ADMIN_NOTIFY_STORAGE_KEY = "davarna_admin_notify_seen_v1";
const ADMIN_NOTIFY_HIDE_MS = 8500;
const HISTORY_LIST_LIMIT = 15;
const CARD_HISTORY_LIMIT = 10;
const LIVE_EVENTS_LIMIT = 15;

const UI_TEXT = {
  brandTitle: "دبرنا حلیم یگن طیار",
  headerUserLabel: "کاربر",
  headerWalletMiniLabel: "کیف پول",
  gamesTitle: "بازی‌ها",
  refreshGamesBtn: "به‌روزرسانی",
  gamesHint:
    "ورود سریع به بازی‌های فعال، مشاهده آمار زنده و خرید کارت.",
  gamesGuideText:
    "بازی فعال را انتخاب کنید، وارد وضعیت زنده شوید و خرید کارت را انجام دهید.",
  recentStatsTitle: "آمار ۵ بازی اخیر",
  trustPanelTitle: "سیستم اعتماد",
  liveTitle: "وضعیت زنده بازی",
  buyQtyLabel: "تعداد کارت",
  buyCardsBtn: "خرید کارت",
  cardsTitle: "کارت‌های من",
  refreshCardsBtn: "به‌روزرسانی",
  cardsHint:
    "کارت‌های بازی فعال با هایلایت عددهای خوانده‌شده نمایش داده می‌شوند.",
  cardsGuideText:
    "کارت‌های خریداری‌شده، اعداد خوانده‌شده و تاریخچه برد را اینجا ببینید.",
  cardsActiveTitle: "کارت‌های خریداری‌شده بازی‌های فعال",
  cardsHistoryTitle: "تاریخچه خرید کارت (۱۰ مورد آخر)",
  cardsHistoryMeta: "اسکرول‌پذیر",
  cardsWinsTitle: "تایم‌لاین بردها",
  walletTitle: "کیف پول",
  refreshWalletBtn: "به‌روزرسانی",
  walletGuideText:
    "برای واریز یا برداشت، مراحل را به ترتیب انجام دهید و وضعیت درخواست‌ها را پیگیری کنید.",
  walletBalanceLabel: "موجودی فعلی",
  depositFlowTitle: "واریز به کیف پول",
  depositFlowDesc:
    "۱) مبلغ دلخواه تومان وارد کنید. ۲) کارت مقصد را انتخاب کنید. ۳) رسید را آپلود کنید. ۴) ثبت نهایی.",
  depositAmountLabel: "مبلغ واریز (تومان)",
  depositDestinationLabel: "انتخاب کارت معرفی‌شده",
  copyDepositCardBtn: "کپی شماره کارت",
  depositReceiptLabel: "آپلود رسید",
  depositSubmitLabel: "ثبت واریزی",
  submitDepositBtn: "ثبت واریزی",
  withdrawFlowTitle: "برداشت از کیف پول",
  withdrawFlowDesc:
    "۱) مبلغ ۲) اطلاعات مقصد ۳) بازبینی ۴) ثبت نهایی",
  withdrawLabel: "مبلغ برداشت (تومان)",
  withdrawTargetLabel: "اطلاعات مقصد برداشت",
  withdrawFullNameLabel: "نام و نام خانوادگی",
  withdrawCardLabel: "شماره کارت",
  withdrawIbanLabel: "شبا (اختیاری)",
  withdrawAccountLabel: "شماره حساب (اختیاری)",
  withdrawReviewLabel: "بازبینی اطلاعات",
  withdrawSubmitLabel: "ثبت نهایی برداشت",
  submitWithdrawBtn: "ثبت برداشت",
  depositRequestsTitle: "درخواست‌های واریز",
  withdrawRequestsTitle: "درخواست‌های برداشت",
  navGamesText: "بازی",
  navCardsText: "کارت‌های من",
  navWalletText: "کیف پول",
  navAdminText: "مدیریت",
  adminTitle: "پنل مدیریت",
  adminGuideText:
    "ایجاد بازی، مدیریت عملیات و بررسی واریز/برداشت از همین بخش انجام می‌شود.",
  adminCreateTitle: "ایجاد بازی جدید",
  adminCreateHint: "با انتخاب تاپیک و قیمت کارت، بازی جدید بسازید.",
  adminCreateGroupLabel: "شناسه گروه",
  adminCreateTopicLabel: "تاپیک بازی",
  adminCreatePriceLabel: "قیمت کارت (تومان)",
  adminCreateBtn: "ایجاد بازی سفارشی",
  adminGamesTitle: "بازی‌های قابل مدیریت",
  adminActionsTitle: "عملیات بازی",
  adminCallLabel: "عدد برای اعلام",
  adminUndoBtn: "حذف آخرین عدد",
  adminStartBtn: "شروع بازی",
  adminCancelReasonLabel: "علت لغو لابی",
  adminCloseLobbyBtn: "لغو بازی قبل از شروع",
  adminLiveLinkLabel: "لینک پخش زنده",
  adminSetLiveBtn: "ثبت لینک لایو",
  adminClearLiveBtn: "حذف لینک لایو",
  adminDepositsTitle: "واریزهای در انتظار",
  adminWithdrawsTitle: "برداشت‌های مدیریتی",
  adminUsersTitle: "مدیریت کاربران",
  adminUsersSearchLabel: "جستجو (شناسه تلگرام / یوزرنیم / gid / dep / wdr)",
  adminUsersSearchBtn: "جستجو",
  adminUsersRefreshBtn: "بازخوانی کاربر انتخابی",
  superAdminTitle: "مدیریت ادمین‌ها (سوپر ادمین)",
  superAdminUserLabel: "شناسه تلگرام کاربر",
  superAdminRoleLabel: "نقش",
  winnerModalTitle: "تبریک، شما برنده شدید",
  winnerWalletBtn: "مشاهده در کیف پول",
  winnerDismissBtn: "بستن",
};

const ADMIN_CREATE_TOPIC_LABELS = {
  game_low: "🎯 بازی ۱ (مبلغ پایین)",
  game_medium: "🎯 بازی ۲ (مبلغ متوسط)",
  game_high: "🎯 بازی ۳ (مبلغ بالا)",
};

function localizeShell() {
  Object.entries(UI_TEXT).forEach(([id, value]) => {
    const el = getEl(id);
    if (el) el.textContent = value;
  });

  const placeholders = {
    depositAmountInput: "مثلا 500000",
    withdrawAmountInput: "مثلا 300000",
    withdrawFullNameInput: "نام و نام خانوادگی",
    withdrawCardInput: "شماره کارت 16 رقمی",
    withdrawIbanInput: "IRxxxxxxxxxxxxxxxxxxxxxxxx",
    withdrawAccountInput: "شماره حساب (اختیاری)",
    adminCallNumberInput: "عدد بین 1 تا 99",
    adminCancelReasonInput: "علت لغو بازی قبل از شروع",
    adminLiveLinkInput: "https://...",
    adminCreateGroupIdInput: "مثال: -1001234567890",
    adminCreateTopicIdInput: "مثال: 14",
    adminCreateCardPriceInput: "مثال: 100000",
    adminUsersSearchInput: "مثال: 6171256645 یا @username یا gid:12",
    superAdminTgUserInput: "شناسه عددی تلگرام",
  };
  Object.entries(placeholders).forEach(([id, text]) => {
    const el = getEl(id);
    if (el) el.setAttribute("placeholder", text);
  });
}

function getEl(id) {
  return document.getElementById(id);
}

function bind(id, event, handler) {
  const el = getEl(id);
  if (!el) {
    console.warn(`[mini] element not found: #${id}`);
    return false;
  }
  el.addEventListener(event, handler);
  return true;
}

function formatAmount(v) {
  const n = Number(v || 0);
  return n.toLocaleString("fa-IR");
}

function toman(v) {
  return `${formatAmount(v)} تومان`;
}

function setBadge(type, text) {
  if (!authBadge) return;
  authBadge.classList.remove("pending", "success", "error");
  authBadge.classList.add(type);
  authBadge.textContent = text;
  const visible = type === "pending" || type === "error";
  authBadge.classList.toggle("hidden", !visible);
  authBadge.classList.toggle("is-visible", visible);
}

function triggerLightHaptic(kind = "success") {
  try {
    tg?.HapticFeedback?.impactOccurred?.("light");
    tg?.HapticFeedback?.notificationOccurred?.(kind);
  } catch (_) {}
  try {
    if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
      navigator.vibrate(18);
    }
  } catch (_) {}
}


function setSplashStatus(text) {
  const el = getEl("splashStatus");
  if (el) el.textContent = String(text || "در حال آماده‌سازی...");
}

function hideSplash() {
  if (state.splashHidden) return;
  state.splashHidden = true;
  const el = getEl("appSplash");
  if (!el) return;
  el.classList.add("is-hidden");
  setTimeout(() => {
    try { el.remove(); } catch (_) {}
  }, 420);
}

function getAudioContext() {
  if (state.audioCtx) return state.audioCtx;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  state.audioCtx = new Ctx();
  return state.audioCtx;
}

function playTone({ freq = 660, duration = 0.09, type = "sine", gain = 0.035 } = {}) {
  if (!state.soundEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    const osc = ctx.createOscillator();
    const vol = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    vol.gain.setValueAtTime(0.0001, ctx.currentTime);
    vol.gain.exponentialRampToValueAtTime(gain, ctx.currentTime + 0.012);
    vol.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
    osc.connect(vol);
    vol.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration + 0.02);
  } catch (_) {}
}

function playNumberSound() {
  playTone({ freq: 720, duration: 0.075, type: "triangle", gain: 0.028 });
  setTimeout(() => playTone({ freq: 980, duration: 0.06, type: "sine", gain: 0.022 }), 68);
}

function playNumberFeedback() {
  playNumberSound();
  triggerLightHaptic("success");
  try { tg?.HapticFeedback?.impactOccurred?.("medium"); } catch (_) {}
  try { tg?.HapticFeedback?.notificationOccurred?.("success"); } catch (_) {}
  try {
    if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
      navigator.vibrate([35, 25, 45]);
    }
  } catch (_) {}
}

function playNotifySound(type = "success") {
  if (type === "error") {
    playTone({ freq: 230, duration: 0.11, type: "sawtooth", gain: 0.024 });
    setTimeout(() => playTone({ freq: 180, duration: 0.09, type: "sawtooth", gain: 0.018 }), 95);
    return;
  }
  playTone({ freq: 523, duration: 0.08, type: "triangle", gain: 0.026 });
  setTimeout(() => playTone({ freq: 784, duration: 0.1, type: "triangle", gain: 0.024 }), 85);
}

function playWinnerSound() {
  [523, 659, 784, 1046].forEach((freq, idx) => {
    setTimeout(() => playTone({ freq, duration: 0.11, type: "triangle", gain: 0.032 }), idx * 85);
  });
}

function updateSoundButton() {
  const btn = getEl("soundBtn");
  if (!btn) return;
  btn.classList.toggle("is-on", Boolean(state.soundEnabled));
  btn.textContent = state.soundEnabled ? "🔔 صدا" : "🔕 صدا";
  btn.setAttribute("aria-label", state.soundEnabled ? "غیرفعال‌سازی صدای بازی" : "فعال‌سازی صدای بازی");
}

function toggleSound() {
  state.soundEnabled = !state.soundEnabled;
  try { localStorage.setItem("davarna_sound_enabled", state.soundEnabled ? "1" : "0"); } catch (_) {}
  if (state.soundEnabled) {
    getAudioContext();
    playNotifySound("success");
    showToast("صدای بازی فعال شد", "success");
  } else {
    showToast("صدای بازی غیرفعال شد", "pending");
  }
  updateSoundButton();
}

function initSoundPreference() {
  try { state.soundEnabled = localStorage.getItem("davarna_sound_enabled") === "1"; } catch (_) {}
  updateSoundButton();
}

function showToast(message, type = "success") {
  const toast = getEl("miniToast");
  if (!toast) return;
  if (state.toastTimer) {
    clearTimeout(state.toastTimer);
    state.toastTimer = null;
  }
  toast.classList.remove("hidden", "show", "success", "error", "pending");
  toast.classList.add(type);
  toast.textContent = String(message || "");
  requestAnimationFrame(() => toast.classList.add("show"));
  state.toastTimer = setTimeout(() => {
    toast.classList.remove("show");
    state.toastTimer = setTimeout(() => {
      toast.classList.add("hidden");
      state.toastTimer = null;
    }, 220);
  }, 1700);
}

function loadAdminNotifySeen() {
  try {
    const raw = localStorage.getItem(ADMIN_NOTIFY_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    state.admin.notify.lastDepositId = Number(parsed?.deposit || 0);
    state.admin.notify.lastWithdrawId = Number(parsed?.withdraw || 0);
  } catch (_) {}
}

function saveAdminNotifySeen() {
  try {
    localStorage.setItem(
      ADMIN_NOTIFY_STORAGE_KEY,
      JSON.stringify({
        deposit: Number(state.admin.notify.lastDepositId || 0),
        withdraw: Number(state.admin.notify.lastWithdrawId || 0),
      })
    );
  } catch (_) {}
}

function hideAdminNotify() {
  const box = getEl("adminNotify");
  if (!box) return;
  if (state.adminNotifyTimer) {
    clearTimeout(state.adminNotifyTimer);
    state.adminNotifyTimer = null;
  }
  box.classList.add("is-dismissing");
  box.classList.remove("show");
  setTimeout(() => {
    box.classList.add("hidden");
    box.classList.remove("deposit", "withdraw", "is-dismissing");
    box.style.transform = "";
    state.adminNotifyCurrent = null;
  }, 220);
}

function showAdminNotify(item) {
  const box = getEl("adminNotify");
  if (!box || !item) return;
  const kind = String(item.kind || "");
  const title = getEl("adminNotifyTitle");
  const meta = getEl("adminNotifyMeta");
  const label = getEl("adminNotifyKind");

  state.adminNotifyCurrent = item;
  box.classList.remove("hidden", "deposit", "withdraw", "is-dismissing");
  box.classList.add(kind === "withdraw" ? "withdraw" : "deposit");
  box.style.transform = "";

  if (label) label.textContent = kind === "withdraw" ? "برداشت جدید" : "واریزی جدید";
  if (title) title.textContent = item.title || "مورد جدید مدیریتی";
  if (meta) meta.textContent = item.meta || "برای مشاهده جزئیات لمس کنید";

  requestAnimationFrame(() => box.classList.add("show"));
  triggerLightHaptic(kind === "withdraw" ? "warning" : "success");
  playNotifySound(kind === "withdraw" ? "pending" : "success");

  if (state.adminNotifyTimer) clearTimeout(state.adminNotifyTimer);
  state.adminNotifyTimer = setTimeout(hideAdminNotify, ADMIN_NOTIFY_HIDE_MS);
}

async function openAdminNotifyTarget(item) {
  if (!item) return;
  hideAdminNotify();
  switchToView("admin");
  const kind = String(item.kind || "");
  const id = Number(item.id || 0);
  if (kind === "withdraw") {
    await refreshAdminWithdraws();
    openAdminAccordionFor("adminWithdrawsList", id);
  } else {
    await refreshAdminDeposits();
    openAdminAccordionFor("adminDepositsList", id);
  }
}

function openAdminAccordionFor(listId, itemId) {
  const list = getEl(listId);
  if (!list) return;
  const details = list.closest("details");
  if (details) details.open = true;
  const attr = listId === "adminWithdrawsList" ? "data-admin-withdraw-id" : "data-admin-deposit-id";
  const item = itemId ? list.querySelector(`[${attr}="${Number(itemId)}"]`) : null;
  const target = item || list;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  if (item) {
    item.classList.add("admin-notify-highlight");
    setTimeout(() => item.classList.remove("admin-notify-highlight"), 1800);
  }
}

function wireAdminNotify() {
  const box = getEl("adminNotify");
  const body = getEl("adminNotifyBody");
  const close = getEl("adminNotifyClose");
  if (!box || !body) return;
  body.addEventListener("click", () => {
    openAdminNotifyTarget(state.adminNotifyCurrent).catch((e) => setBadge("error", e.message));
  });
  if (close) {
    close.addEventListener("click", (ev) => {
      ev.stopPropagation();
      hideAdminNotify();
    });
  }

  let startX = 0;
  let startY = 0;
  let dragging = false;
  const start = (x, y) => {
    startX = x;
    startY = y;
    dragging = true;
  };
  const move = (x, y) => {
    if (!dragging || box.classList.contains("hidden")) return;
    const dx = x - startX;
    const dy = y - startY;
    if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
    box.style.transform = `translate(${dx}px, ${Math.min(18, Math.max(-18, dy))}px)`;
    if (Math.abs(dx) > 90 || Math.abs(dy) > 70) box.classList.add("is-dismissing");
  };
  const end = (x, y) => {
    if (!dragging) return;
    dragging = false;
    const dx = x - startX;
    const dy = y - startY;
    if (Math.abs(dx) > 90 || Math.abs(dy) > 70) {
      hideAdminNotify();
      return;
    }
    box.classList.remove("is-dismissing");
    box.style.transform = "";
  };

  box.addEventListener("touchstart", (ev) => {
    const t = ev.touches && ev.touches[0];
    if (t) start(t.clientX, t.clientY);
  }, { passive: true });
  box.addEventListener("touchmove", (ev) => {
    const t = ev.touches && ev.touches[0];
    if (t) move(t.clientX, t.clientY);
  }, { passive: true });
  box.addEventListener("touchend", (ev) => {
    const t = ev.changedTouches && ev.changedTouches[0];
    end(t ? t.clientX : startX, t ? t.clientY : startY);
  }, { passive: true });
  box.addEventListener("pointerdown", (ev) => {
    if (ev.pointerType === "mouse" && ev.button !== 0) return;
    start(ev.clientX, ev.clientY);
  });
  box.addEventListener("pointermove", (ev) => move(ev.clientX, ev.clientY));
  box.addEventListener("pointerup", (ev) => end(ev.clientX, ev.clientY));
  box.addEventListener("pointercancel", () => {
    dragging = false;
    box.style.transform = "";
  });
}

function inferDisplayName() {
  const tgUser = tg?.initDataUnsafe?.user;
  const username = String(tgUser?.username || "").trim();
  if (username) return `@${username}`;
  const fn = String(tgUser?.first_name || "").trim();
  const ln = String(tgUser?.last_name || "").trim();
  const full = `${fn} ${ln}`.trim();
  if (full) return full;
  return "کاربر دبرنا حلیم یگن طیار";
}

function updateHeaderWallet(balance) {
  if (headerWalletBalance) headerWalletBalance.textContent = toman(balance || 0);
}

function updateHeaderStatus() {
  if (!headerUserStatus) return;
  const hasRecentWinner = Boolean(state.userFlags?.recentWinner);
  const hasInGame = Boolean(state.userFlags?.inGame);
  headerUserStatus.classList.remove("normal", "ingame", "winner");
  if (hasRecentWinner) {
    headerUserStatus.classList.add("winner");
    headerUserStatus.textContent = "برنده اخیر";
    return;
  }
  if (hasInGame) {
    headerUserStatus.classList.add("ingame");
    headerUserStatus.textContent = "در بازی";
    return;
  }
  headerUserStatus.classList.add("normal");
  headerUserStatus.textContent = "عادی";
}

function safeText(v) {
  return String(v ?? "").replace(/[<>&]/g, (m) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[m]));
}

function statusLabel(value) {
  const key = String(value || "").toUpperCase();
  return STATUS_LABELS[key] || (value ? String(value) : "-");
}

function depositStatusLabel(value) {
  const key = String(value || "").toUpperCase();
  return DEPOSIT_STATUS_LABELS[key] || statusLabel(value);
}

function withdrawStatusLabel(value) {
  const key = String(value || "").toUpperCase();
  return WITHDRAW_STATUS_LABELS[key] || statusLabel(value);
}

function eventKindLabel(value) {
  const key = String(value || "").toUpperCase();
  return EVENT_KIND_LABELS[key] || String(value || "رویداد");
}

function adminCreateTopicTitle(topic) {
  const key = String(topic?.key || "");
  if (ADMIN_CREATE_TOPIC_LABELS[key]) return ADMIN_CREATE_TOPIC_LABELS[key];
  const fallback = String(topic?.title || "").trim();
  if (fallback) return fallback;
  const topicId = Number(topic?.topic_id || 0);
  return topicId > 0 ? `تاپیک ${topicId}` : "تاپیک بازی";
}

const WALLET_REASON_LABELS = {
  BUY_CARDS: "خرید کارت",
  PRIZE_COL: "برد ستونی(تورنا)",
  PRIZE_ROW: "برد سطری(تمام)",
  DEPOSIT_APPROVED: "تایید واریز",
  WITHDRAW_APPROVED: "تایید برداشت",
  WITHDRAW_REJECTED: "رد برداشت",
  GAME_CANCEL_REFUND: "برگشت وجه لغو بازی",
  REFUND_GAME_CANCELLED: "برگشت وجه لغو بازی",
};

function walletReasonLabel(reason) {
  const key = String(reason || "").toUpperCase();
  if (WALLET_REASON_LABELS[key]) return WALLET_REASON_LABELS[key];
  if (!key) return "-";
  return key.replaceAll("_", " ");
}

const WIN_PATTERN_LABELS = {
  کامل: "برد سطری(تمام)",
  تورنا: "برد ستونی(تورنا)",
  خطی: "خطی",
  نامشخص: "نامشخص",
  ROW: "برد سطری(تمام)",
  COL: "برد ستونی(تورنا)",
  FULL: "برد سطری(تمام)",
};

function repairMojibakeText(raw) {
  const text = String(raw || "");
  const maybeBroken = Array.from(text).some((ch) => {
    const code = ch.charCodeAt(0);
    return code >= 0x00c0 && code <= 0x00ff;
  });
  if (!maybeBroken || typeof TextDecoder === "undefined") return text;
  try {
    const bytes = Uint8Array.from(Array.from(text).map((ch) => ch.charCodeAt(0) & 0xff));
    const repaired = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return repaired || text;
  } catch (_) {
    return text;
  }
}

function normalizeWinPatternLabel(raw) {
  const val = repairMojibakeText(raw).trim();
  if (!val) return "-";
  if (WIN_PATTERN_LABELS[val]) return WIN_PATTERN_LABELS[val];
  const upper = val.toUpperCase();
  if (WIN_PATTERN_LABELS[upper]) return WIN_PATTERN_LABELS[upper];
  return val;
}

function winnerKindLabelByReason(reason) {
  const key = String(reason || "").toUpperCase();
  if (key === "PRIZE_COL") return "برد ستونی(تورنا)";
  if (key === "PRIZE_ROW") return "برد سطری(تمام)";
  return "برد";
}

function winnerKindLabelByFlags({ row = false, col = false } = {}) {
  if (row && col) return "برد ستونی(تورنا) + برد سطری(تمام)";
  if (row) return "برد سطری(تمام)";
  if (col) return "برد ستونی(تورنا)";
  return "";
}


function toEnglishDigits(raw) {
  return String(raw || "")
    .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));
}

function parsePositiveInt(raw) {
  const cleaned = toEnglishDigits(String(raw || "")).replace(/[^\d]/g, "");
  if (!cleaned) return 0;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.trunc(n));
}

function telegramInitData() {
  return String(tg?.initData || "").trim();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
}

function isNetworkFetchError(err) {
  const msg = String(err?.message || err || "").toLowerCase();
  return (
    msg.includes("failed to fetch") ||
    msg.includes("networkerror") ||
    msg.includes("load failed") ||
    msg.includes("network request failed")
  );
}

async function fetchWithRetry(path, options, retries = 1) {
  try {
    return await fetch(path, options);
  } catch (err) {
    if (retries > 0 && isNetworkFetchError(err)) {
      await sleep(FETCH_RETRY_DELAY_MS);
      return fetchWithRetry(path, options, retries - 1);
    }
    throw err;
  }
}

function idem(prefix) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function localizeApiError(detail) {
  const raw = String(detail || "").trim();
  if (!raw) return "خطای نامشخص";
  const low = raw.toLowerCase();
  const exactMap = {
    forbidden: "دسترسی کافی ندارید.",
    "game not found": "بازی موردنظر پیدا نشد.",
    "user not found": "کاربر موردنظر پیدا نشد.",
    "receipt file not found": "فایل رسید پیدا نشد.",
    "deposit_request not found": "درخواست واریز پیدا نشد.",
    "super admin required": "این عملیات فقط برای سوپرادمین مجاز است.",
    "super admin owner required": "این عملیات فقط برای سوپرادمین اصلی مجاز است.",
    "missing authorization": "احراز هویت انجام نشد.",
    "missing telegram init data": "داده احراز هویت تلگرام ارسال نشده است.",
    "invalid live_url": "لینک پخش زنده نامعتبر است.",
    "live_url is required": "لینک پخش زنده الزامی است.",
    "live_url is too long": "طول لینک پخش زنده بیش از حد مجاز است.",
    "cannot revoke your own super admin role": "امکان حذف نقش سوپرادمین از خودتان وجود ندارد.",
    "cannot revoke last super admin": "نقش آخرین سوپرادمین قابل حذف نیست.",
    "super admin owner required": "فقط سوپرادمین اصلی مجاز به این عملیات است.",
    "only game admin can manage this game": "فقط ادمین همان بازی می‌تواند این عملیات را انجام دهد.",
    "invalid bot token": "توکن سرویس ربات نامعتبر است.",
  };
  if (exactMap[low]) return exactMap[low];

  if (low.includes("invalid hash")) {
    return "احراز هویت تلگرام نامعتبر است. مینی‌اپ را فقط از منوی رسمی ربات باز کنید.";
  }
  if (low.includes("json decode error")) {
    return "فرمت داده ارسالی نامعتبر است.";
  }
  if (low.includes("input should be greater than")) {
    return "یکی از مقادیر ارسالی کمتر از حد مجاز است.";
  }
  if (low.includes("field required")) {
    return "برخی فیلدهای ضروری ارسال نشده‌اند.";
  }
  if (low.includes("[object object]")) {
    return "ورودی ارسال‌شده معتبر نیست.";
  }
  if (low === "http 401") {
    return "نشست مینی‌اپ منقضی شده است. مینی‌اپ را از منوی رسمی ربات دوباره باز کنید.";
  }
  if (low === "http 403") {
    return "دسترسی شما برای این عملیات مجاز نیست.";
  }
  if (low.startsWith("http 5")) {
    return "خطای داخلی سرویس رخ داد. چند لحظه بعد دوباره تلاش کنید.";
  }
  if (low.startsWith("http ")) return "خطای ارتباط با سرور رخ داد.";
  return raw;
}

function getVal(id) {
  const el = getEl(id);
  return el ? String(el.value || "").trim() : "";
}

function setVal(id, value) {
  const el = getEl(id);
  if (el) el.value = value;
}

function setHint(id, text, type = "") {
  const el = getEl(id);
  if (!el) return;
  el.textContent = String(text || "");
  el.dataset.type = String(type || "");
}

function setAdminNavVisible(visible) {
  const btn = getEl("adminNavBtn");
  if (!btn) return;
  btn.classList.toggle("hidden", !visible);
  if (!visible) {
    const adminView = getEl("view-admin");
    if (adminView && adminView.classList.contains("active")) {
      switchToView("games");
    }
  }
}

function adminRoleBadgeText() {
  if (!state.admin.enabled) return "دسترسی ادمین فعال نیست.";
  if (state.admin.isSuper) return "سطح دسترسی: سوپر ادمین";
  return "سطح دسترسی: ادمین";
}

function maskCard(cardNumber) {
  const d = String(cardNumber || "").replace(/\D/g, "");
  if (!d) return "-";
  if (d.length <= 8) return d;
  return `${d.slice(0, 4)}-${"*".repeat(Math.max(0, d.length - 8))}-${d.slice(-4)}`;
}

function selectedDepositDestination() {
  const selectedId = getVal("depositDestinationSelect");
  if (!selectedId) return null;
  const items = Array.isArray(state.depositDestinations) ? state.depositDestinations : [];
  return items.find((x) => String(x?.id || "") === selectedId) || null;
}

function normalizedCardNumber(raw) {
  return String(raw || "").replace(/\D/g, "").slice(0, 19);
}

function prettyCardNumber(raw) {
  const digits = normalizedCardNumber(raw);
  if (!digits) return "-";
  return digits.replace(/(\d{4})(?=\d)/g, "$1-");
}

function ltrNumberHtml(value) {
  return `<bdi dir="ltr" class="ltr-number">${safeText(value)}</bdi>`;
}

function ltrIsolateText(value) {
  return `${String.fromCharCode(0x2066)}${String(value || "")}${String.fromCharCode(0x2069)}`;
}

function renderDepositDestinationHint() {
  const selectEl = getEl("depositDestinationSelect");
  const copyBtn = getEl("copyDepositCardBtn");
  const cardBox = getEl("depositDestinationCardBox");
  const selected = selectedDepositDestination();
  if (!selected) {
    setHint("depositDestinationHint", "ابتدا یک کارت مقصد انتخاب کنید.");
    if (selectEl) selectEl.classList.remove("has-selection");
    if (copyBtn) copyBtn.disabled = true;
    if (cardBox) {
      cardBox.classList.add("hidden");
      cardBox.innerHTML = "";
    }
    return;
  }
  const bank = String(selected.bank_name || "-");
  const owner = String(selected.account_name || "-");
  const card = prettyCardNumber(selected.card_number);
  const title = String(selected.title || selected.id || "مقصد");
  setHint("depositDestinationHint", "برای واریز، شماره کارت را کپی کنید و سپس رسید را بارگذاری کنید.");
  if (selectEl) selectEl.classList.add("has-selection");
  if (copyBtn) copyBtn.disabled = false;
  if (cardBox) {
    cardBox.classList.remove("hidden");
    cardBox.innerHTML = `
      <div class="destination-selected-head">کارت انتخاب‌شده</div>
      <div class="destination-selected-title">${safeText(title)}</div>
      <div class="destination-selected-meta">${safeText(bank)} | ${safeText(owner)}</div>
      <div class="destination-selected-number">${ltrNumberHtml(card)}</div>
    `;
  }
}

async function copyTextToClipboard(value) {
  const text = String(value || "");
  if (!text) throw new Error("متنی برای کپی وجود ندارد.");
  if (navigator?.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "readonly");
  ta.style.position = "fixed";
  ta.style.top = "-1000px";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(ta);
  if (!ok) throw new Error("کپی خودکار ممکن نشد.");
}

async function copySelectedDepositCard() {
  const selected = selectedDepositDestination();
  const rawCard = normalizedCardNumber(selected?.card_number || "");
  if (!rawCard) {
    setHint("depositDestinationHint", "کارت مقصد انتخاب نشده است.", "error");
    setBadge("error", "ابتدا کارت مقصد را انتخاب کنید");
    showToast("ابتدا کارت مقصد را انتخاب کنید.", "error");
    return;
  }
  try {
    await copyTextToClipboard(rawCard);
    const hint = getEl("depositDestinationHint");
    if (hint) {
      hint.innerHTML = `شماره کارت ${ltrNumberHtml(prettyCardNumber(rawCard))} کپی شد.`;
      hint.dataset.type = "success";
    }
    setBadge("success", "شماره کارت کپی شد");
    showToast("شماره کارت با موفقیت کپی شد.", "success");
    triggerLightHaptic("success");
  } catch (err) {
    const msg = String(err?.message || "کپی شماره کارت انجام نشد.");
    setHint("depositDestinationHint", msg, "error");
    setBadge("error", msg);
    showToast(msg, "error");
  }
}

function renderWithdrawPreview() {
  const amount = parsePositiveInt(getVal("withdrawAmountInput"));
  const fullName = getVal("withdrawFullNameInput");
  const cardRaw = toEnglishDigits(getVal("withdrawCardInput")).replace(/\D/g, "").slice(0, 16);
  const ibanRaw = toEnglishDigits(getVal("withdrawIbanInput")).replace(/\s+/g, "").toUpperCase();
  const accountRaw = toEnglishDigits(getVal("withdrawAccountInput")).replace(/[^\d]/g, "").slice(0, 20);
  const review = getEl("withdrawReviewCard");
  if (review) {
    review.innerHTML = `
      <div class="withdraw-review-row">
        <span>مبلغ</span>
        <strong>${safeText(amount > 0 ? toman(amount) : "-")}</strong>
      </div>
      <div class="withdraw-review-row">
        <span>نام و نام خانوادگی</span>
        <strong>${safeText(fullName || "-")}</strong>
      </div>
      <div class="withdraw-review-row">
        <span>شماره کارت</span>
        <strong dir="ltr">${safeText(cardRaw ? prettyCardNumber(cardRaw) : "-")}</strong>
      </div>
      <div class="withdraw-review-row">
        <span>شبا</span>
        <strong dir="ltr">${safeText(ibanRaw || "-")}</strong>
      </div>
      <div class="withdraw-review-row">
        <span>شماره حساب</span>
        <strong>${safeText(accountRaw || "-")}</strong>
      </div>
    `;
  }

  const missing = [];
  if (!amount || amount <= 0) missing.push("مبلغ");
  if (!fullName) missing.push("نام");
  if (!cardRaw || cardRaw.length !== 16) missing.push("کارت ۱۶ رقمی");
  if (missing.length) {
    setHint("withdrawPreviewHint", `تکمیل موارد ضروری: ${missing.join("، ")}`);
    return;
  }
  setHint("withdrawPreviewHint", "اطلاعات کامل است. ثبت نهایی را انجام دهید.", "success");
}

async function readFileAsDataUrl(file) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("خواندن فایل رسید انجام نشد."));
    reader.readAsDataURL(file);
  });
}

async function apiFetch(path, { method = "GET", body = null, headers = {} } = {}) {
  const reqHeaders = { ...headers };
  let requestPath = String(path || "");
  const initData = telegramInitData();
  const isExchange = requestPath.startsWith("/mini-api/auth/exchange");

  if (!state.token && !isExchange) {
    throw new Error("نشست کاربری فعال نیست. مینی‌اپ را از منوی رسمی ربات باز کنید.");
  }

  if (state.token) {
    reqHeaders.Authorization = `Bearer ${state.token}`;
  } else if (initData && isExchange) {
    reqHeaders["X-Tg-Init-Data"] = initData;
  } else if (isExchange) {
    throw new Error("داده احراز هویت تلگرام وجود ندارد. مینی‌اپ را از منوی ربات باز کنید.");
  }

  const options = { method, headers: reqHeaders, cache: "no-store" };
  if (body instanceof FormData) {
    options.body = body;
  } else if (body !== null) {
    reqHeaders["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  if (String(method || "GET").toUpperCase() === "GET") {
    requestPath += requestPath.includes("?") ? `&_=${Date.now()}` : `?_=${Date.now()}`;
  }

  let resp;
  try {
    resp = await fetchWithRetry(requestPath, options, 1);
  } catch (err) {
    if (isNetworkFetchError(err)) {
      throw new Error("ارتباط با سرور ناپایدار است. چند لحظه بعد دوباره تلاش کنید.");
    }
    throw err;
  }
  if (!resp.ok) {
    if (resp.status === 401) {
      clearMiniSession();
    }
    let detail = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      if (Array.isArray(data?.detail)) {
        const first = data.detail[0];
        detail = String(first?.msg || "ورودی ارسال‌شده معتبر نیست.");
      } else if (data?.detail) {
        detail = String(data.detail);
      }
    } catch (_) {}
    throw new Error(localizeApiError(detail));
  }
  return await resp.json();
}

async function runManualRefresh(buttonId, taskFn) {
  const btn = getEl(buttonId);
  const originalText = btn ? String(btn.textContent || "به‌روزرسانی") : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "در حال به‌روزرسانی...";
  }
  setBadge("pending", "در حال به‌روزرسانی...");
  try {
    await taskFn();
    setBadge("success", "به‌روزرسانی انجام شد");
  } catch (err) {
    setBadge("error", String(err?.message || "خطا در به‌روزرسانی"));
    throw err;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText || "به‌روزرسانی";
    }
  }
}

async function exchangeSession() {
  const initData = telegramInitData();
  if (!initData) {
    setBadge("error", "initData یافت نشد");
    return;
  }

  setBadge("pending", "در حال احراز هویت...");
  const res = await apiFetch("/mini-api/auth/exchange", {
    method: "POST",
    body: { init_data: initData },
  });
  state.token = res.access_token;
  state.tokenExp = Number(res.expires_at || 0);
  state.authReady = true;
  state.currentUserId = Number(res.user_id || 0);
  persistMiniSession();
  setBadge("success", "متصل شد");
}

function soldCardsCount(game, snap) {
  const fromSnap = Number(snap?.state?.sold_cards_count || 0);
  if (fromSnap > 0) return fromSnap;
  const price = Number(game?.card_price || 0);
  const soldAmount = Number(game?.sold_amount || 0);
  if (price > 0) return Math.max(0, Math.floor(soldAmount / price));
  return 0;
}

function playersCount(game, snap) {
  return Number(snap?.state?.players_count || 0);
}

function drawGames(items) {
  const root = getEl("gamesList");
  const hotBanner = getEl("hotGameBanner");
  if (!root) return;

  if (!items?.length) {
    root.innerHTML = '<div class="empty">بازی فعالی پیدا نشد.</div>';
    if (hotBanner) {
      hotBanner.classList.add("hidden");
      hotBanner.textContent = "";
    }
    return;
  }

  const soldCounts = items.map((g) => soldCardsCount(g, state.gameSnapshots.get(Number(g.id))));
  const maxSold = Math.max(1, ...soldCounts);
  if (hotBanner) {
    const hotId = Number(state.hotGameId || 0);
    if (hotId > 0) {
      hotBanner.classList.add("hidden");
      hotBanner.textContent = "";
    } else {
      hotBanner.classList.add("hidden");
      hotBanner.textContent = "";
    }
  }

  root.innerHTML = items
    .map((g) => {
      const gid = Number(g.id);
      const snap = state.gameSnapshots.get(gid);
      const statusKey = String(g.status || "").toUpperCase();
      const isLobby = statusKey === "LOBBY";
      const isRunning = statusKey === "RUNNING";
      const myCards = Number(state.myCardsByGame.get(gid) || 0);
      const soldCards = soldCardsCount(g, snap);
      const players = playersCount(g, snap);
      const progress = Math.max(0, Math.min(100, Math.round((soldCards / maxSold) * 100)));
      const hot = false;
      const statusClass = isRunning ? "running" : "lobby";
      const runningBanner = isRunning
        ? '<div class="running-banner">🔴 بازی در حال اجراست</div>'
        : "";
      const cta = isLobby && myCards <= 0
        ? `<button class="small-btn primary cta-big open-btn" data-game-id="${gid}">خرید کارت</button>`
        : `<button class="small-btn open-btn" data-game-id="${gid}">مشاهده بازی</button>`;

      return `
      <div class="item game-hero">
        <div class="item-row">
          <h3>بازی #${gid}</h3>
          <span class="game-state ${statusClass}">${safeText(statusLabel(g.status))}</span>
        </div>

        <div class="game-kpis">
          <div class="kpi"><div class="label">کارت فروخته‌شده</div><div class="value">${safeText(soldCards)}</div></div>
          <div class="kpi"><div class="label">بازیکنان فعلی</div><div class="value">${safeText(players)}</div></div>
          <div class="kpi"><div class="label">جایزه</div><div class="value">${safeText(toman(g.prize_pool))}</div></div>
        </div>
        <div class="meta">روند شکل‌گیری جایزه</div>
        <div class="prize-progress"><i style="width:${progress}%"></i></div>
        ${runningBanner}
        <div class="item-row">
          <span class="meta">قیمت هر کارت: ${safeText(toman(g.card_price))}</span>
          ${cta}
        </div>
      </div>
    `;
    })
    .join("");

  root.querySelectorAll(".open-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const gameId = Number(btn.getAttribute("data-game-id") || "0");
    if (!gameId) return;

    const isBuyButton = btn.classList.contains("cta-big");

    if (!isBuyButton) {
      state.selectedGameId = gameId;
      switchToView("cards");
      return;
    }

    openLiveGame(gameId)
      .then(() => {
        setTimeout(() => {
          const liveTitle = getEl("liveTitle");
          const buyForm = getEl("buyActionForm");
          const target = liveTitle || buyForm;

          if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        }, 100);
      })
      .catch((err) => setBadge("error", err.message));
  });
});
}

function formatDuration(sec) {
  const s = Number(sec || 0);
  if (s <= 0) return "-";
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function formatFaDateTime(raw) {
  if (!raw) return "-";
  try {
    const d = new Date(String(raw));
    if (Number.isNaN(d.getTime())) return String(raw);
    return d.toLocaleString("fa-IR", {
      calendar: "persian",
      numberingSystem: "arabext",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch (_) {
    return String(raw);
  }
}

function drawRecentStats(items) {
  const root = getEl("recentStatsSlider");
  if (!root) return;
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    root.innerHTML = '<div class="empty">هنوز بازی پایان‌یافته‌ای برای آمار وجود ندارد.</div>';
    return;
  }

  root.innerHTML = list
    .map((g) => {
      const colTotal = Number(g.col_prize_total || 0);
      const rowTotal = Number(g.row_prize_total || 0);
      const colWinners = Number(g.col_winners_count || 0);
      const rowWinners = Number(g.row_winners_count || 0);

      const colWinnerText = colTotal > 0
        ? `تعداد: ${safeText(colWinners || 1)} | مجموع: ${safeText(toman(colTotal))}`
        : "-";
      const rowWinnerText = rowTotal > 0
        ? `تعداد: ${safeText(rowWinners || 1)} | مجموع: ${safeText(toman(rowTotal))}`
        : "-";

      return `
      <div class="stat-card">
        <h4>بازی #${g.game_id}</h4>
        <div class="meta-row">🎫 مبلغ کارت: ${safeText(toman(g.card_price || 0))}</div>
        <div class="meta-row">🎟 کارت فروخته‌شده: ${safeText(g.sold_cards)}</div>
        <div class="meta-row">💳 مجموع فروش کارت: ${safeText(toman(g.sold_amount || 0))}</div>
        <div class="meta-row">🧾 کمیسیون: ${safeText(toman(g.commission_amount || 0))}</div>
        <div class="meta-row">💰 مجموع برنده‌ها: ${safeText(toman(g.prize_pool || 0))}</div>
        <div class="meta-row">🏆 تعداد برنده‌ها: ${safeText(g.winners_count)}</div>
        <div class="meta-row">🔷 نوع برنده ستونی(تورنا): ${colWinnerText}</div>
        <div class="meta-row">🟩 نوع برنده سطری(تمام): ${rowWinnerText}</div>
      </div>
    `
    })
    .join("");
}

function drawTrustStrip(payload) {
  const root = getEl("trustStrip");
  if (!root) return;
  const trust = payload || {};
  const latest = trust.latest_win || null;
  const latestText = latest
    ? `${safeText(latest.user_alias || "کاربر")} | ${safeText(toman(latest.amount || 0))}`
    : "-";

  root.innerHTML = `
    <div class="trust-chip">
      <div class="label">مجموع پرداختی امروز</div>
      <div class="value">${safeText(toman(trust.total_paid_today || 0))}</div>
    </div>
    <div class="trust-chip">
      <div class="label">برندگان امروز</div>
      <div class="value">${safeText(trust.winners_today || 0)} نفر</div>
    </div>
    <div class="trust-chip">
      <div class="label">آخرین برد واقعی</div>
      <div class="value">${latestText}</div>
    </div>
  `;
}

function normalizeIntList(values) {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0))];
}

function extractWinnerUserIds(payload) {
  if (!payload || typeof payload !== "object") return [];
  const out = [];
  const keys = ["winner_user_ids", "row_winner_user_ids", "col_winner_user_ids", "winner_ids"];
  keys.forEach((k) => {
    const vals = payload[k];
    if (Array.isArray(vals)) out.push(...vals);
  });
  if (payload.winner_user_id !== undefined && payload.winner_user_id !== null) out.push(payload.winner_user_id);
  return normalizeIntList(out);
}

function isMyWinnerEvent(event) {
  const myId = Number(state.currentUserId || 0);
  if (!myId || !event) return false;
  const kind = String(event.kind || "").toUpperCase();
  if (!["PRIZE_COL", "PRIZE_ROW", "WINNER_DECLARED"].includes(kind)) return false;
  const winners = extractWinnerUserIds(event.payload || {});
  return winners.includes(myId);
}

function buildWinnerNoticeText(event) {
  const kind = String(event?.kind || "").toUpperCase();
  const gid = Number(event?.game_id || state.selectedGameId || 0);
  const payload = event?.payload || {};
  const amount = resolveWinnerAmount(payload);
  const kindLabel = resolveWinnerKindLabel(kind, payload);
  const amountPart = amount > 0 ? ` | مبلغ: ${toman(amount)}` : "";
  const gamePart = gid > 0 ? ` در بازی #${gid}` : "";
  return `تبریک! ${kindLabel}${gamePart}${amountPart}`;
}

function resolveWinnerAmount(payload) {
  const myId = Number(state.currentUserId || 0);
  if (myId > 0) {
    const users = normalizeIntList(payload?.winner_user_ids || []);
    const amounts = Array.isArray(payload?.amount_by_card)
      ? payload.amount_by_card.map((x) => Number(x || 0))
      : [];
    if (users.length && amounts.length) {
      let mine = 0;
      for (let i = 0; i < users.length && i < amounts.length; i += 1) {
        if (users[i] === myId && Number.isFinite(amounts[i]) && amounts[i] > 0) {
          mine += amounts[i];
        }
      }
      if (mine > 0) return Math.trunc(mine);
    }
  }
  const total = Number(payload?.amount_total || 0);
  if (total > 0) return total;
  const row = Number(payload?.row_payout_total || 0);
  const col = Number(payload?.col_payout_total || 0);
  if (row > 0 && col > 0) return row + col;
  if (row > 0) return row;
  if (col > 0) return col;
  return 0;
}

function resolveWinnerKindLabel(kind, payload) {
  const key = String(kind || "").toUpperCase();
  if (key === "PRIZE_COL" || key === "PRIZE_ROW") return winnerKindLabelByReason(key);
  const myId = Number(state.currentUserId || 0);
  const rowIds = normalizeIntList(payload?.row_winner_user_ids || []);
  const colIds = normalizeIntList(payload?.col_winner_user_ids || []);
  const rowByIds = myId > 0 && rowIds.includes(myId);
  const colByIds = myId > 0 && colIds.includes(myId);
  const rowByAmount = Number(payload?.row_payout_total || 0) > 0;
  const colByAmount = Number(payload?.col_payout_total || 0) > 0;
  const row = rowByIds || (!colByIds && rowByAmount);
  const col = colByIds || (!rowByIds && colByAmount);
  return winnerKindLabelByFlags({ row, col }) || winnerKindLabelByReason(key);
}

function extractWinnerInfo(event) {
  const kind = String(event?.kind || "").toUpperCase();
  const payload = event?.payload || {};
  const gameId = Number(event?.game_id || state.selectedGameId || 0);
  const amount = resolveWinnerAmount(payload);
  const kindLabel = resolveWinnerKindLabel(kind, payload);
  return {
    key: `${kind}:${gameId}:${amount}:${event?.id || 0}`,
    gameId,
    amount,
    kindLabel,
  };
}

function closeWinnerModal() {
  const modal = getEl("winnerModal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function openWinnerModal(event) {
  const modal = getEl("winnerModal");
  if (!modal) return;
  const info = extractWinnerInfo(event);
  if (state.lastWinnerModalKey === info.key) return;
  state.lastWinnerModalKey = info.key;
  const kindEl = getEl("winnerModalKind");
  const amountEl = getEl("winnerModalAmount");
  const gameEl = getEl("winnerModalGame");
  const statusEl = getEl("winnerModalStatus");
  if (kindEl) kindEl.textContent = `نوع برد: ${info.kindLabel}`;
  if (amountEl) amountEl.textContent = info.amount > 0 ? `مبلغ جایزه: ${toman(info.amount)}` : "مبلغ جایزه: در حال محاسبه / بررسی";
  if (gameEl) gameEl.textContent = info.gameId > 0 ? `بازی #${info.gameId}` : "";
  if (statusEl) statusEl.textContent = info.amount > 0 ? "جایزه در کیف پول شما قابل پیگیری است." : "اگر مبلغ نمایش داده نشد، وضعیت را از کیف پول یا مدیر پیگیری کنید.";
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  try {
    tg?.HapticFeedback?.notificationOccurred?.("success");
    tg?.HapticFeedback?.impactOccurred?.("medium");
  } catch (_) {}
  try { if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") navigator.vibrate([45, 35, 65]); } catch (_) {}
  playWinnerSound();
}

function pushWinnerNotice(event) {
  if (!event || !isMyWinnerEvent(event)) return;
  const eventId = Number(event.id || 0);
  if (eventId > 0 && eventId <= Number(state.lastWinnerEventId || 0)) return;
  if (eventId > 0) state.lastWinnerEventId = eventId;
  setBadge("success", buildWinnerNoticeText(event));
  state.userFlags.recentWinner = true;
  updateHeaderStatus();
  openWinnerModal(event);
  try { tg?.HapticFeedback?.notificationOccurred?.("success"); } catch (_) {}
}

function renderWinnerBannerFromState(gameId, st) {
  const host = getEl("liveWinnerBanner");
  if (!host) return;
  const myId = Number(state.currentUserId || 0);
  if (!myId) { host.innerHTML = ""; return; }

  const rowUsers = normalizeIntList(st?.row_winner_user_ids);
  const colUsers = normalizeIntList(st?.col_winner_user_ids);
  const rowMine = rowUsers.includes(myId);
  const colMine = colUsers.includes(myId);

  if (!rowMine && !colMine) { host.innerHTML = ""; return; }

  const notes = [];
  if (colMine) {
    const colAmount = Number(st?.col_payout_total || 0);
    notes.push(colAmount > 0 ? `برد ستونی(تورنا): ${toman(colAmount)}` : "برد ستونی(تورنا) ثبت شد");
  }
  if (rowMine) {
    const rowAmount = Number(st?.row_payout_total || 0);
    notes.push(rowAmount > 0 ? `برد سطری(تمام): ${toman(rowAmount)}` : "برد سطری(تمام) ثبت شد");
  }

  host.innerHTML = `
    <div class="winner-banner">
      <strong>تبریک! شما برنده این بازی شدید</strong>
      <span>${safeText(notes.join(" | "))}</span>
    </div>
  `;
}

function renderGameTimeline(game, st) {
  const root = getEl("gameTimeline");
  if (!root) return;
  const status = String(st?.status || game?.status || "").toUpperCase();
  const calledCount = Number(st?.called_count || (Array.isArray(st?.called_numbers) ? st.called_numbers.length : 0));
  const rowPaid = Number(st?.row_paid || 0) === 1;
  const colPaid = Number(st?.col_paid || 0) === 1;

  let stage = 1;
  if (status === "LOBBY") stage = 1;
  if (status === "RUNNING") stage = calledCount < 35 ? 2 : 3;
  if (rowPaid || colPaid) stage = Math.max(stage, 4);
  if (status === "ENDED") stage = 5;

  const labels = ["لابی", "شروع", "نیمه بازی", "تورنا", "پایان"];
  root.innerHTML = labels
    .map((label, idx) => {
      const n = idx + 1;
      const cls = n < stage ? "timeline-step done" : n === stage ? "timeline-step active" : "timeline-step";
      return `<div class="${cls}">${label}</div>`;
    })
    .join("");
}

function renderLiveInsights(st) {
  const root = getEl("liveInsights");
  if (!root) return;
  const remain = Number(st?.remaining_players_estimate || 0);
  const calledCount = Number(st?.called_count || (Array.isArray(st?.called_numbers) ? st.called_numbers.length : 0));
  const progress = Number(st?.called_progress_pct || 0);
  root.innerHTML = `
    <div class="live-insight">
      <div class="k">بازیکنان باقی‌مانده</div>
      <div class="v">${safeText(remain || "-")}</div>
    </div>
    <div class="live-insight">
      <div class="k">اعداد اعلام‌شده</div>
      <div class="v">${safeText(calledCount)}</div>
    </div>
    <div class="live-insight">
      <div class="k">درصد پیشرفت بازی</div>
      <div class="v">${safeText(progress)}%</div>
    </div>
  `;
}

function normalizeSafeHttpUrl(raw) {
  const text = String(raw || "").trim();
  if (!text) return null;
  if (!/^https?:\/\//i.test(text)) return null;
  return text;
}

function renderLiveLink(st) {
  const section = getEl("liveLinkSection");
  const anchor = getEl("liveLinkAnchor");
  const meta = getEl("liveLinkMeta");
  if (!section || !anchor) return;

  const url = normalizeSafeHttpUrl(st?.live_link_url);
  if (!url) {
    section.classList.add("hidden");
    anchor.removeAttribute("href");
    if (meta) meta.textContent = "";
    return;
  }

  section.classList.remove("hidden");
  anchor.setAttribute("href", url);
  if (meta) {
    const updated = String(st?.live_link_updated_at || "").trim();
    meta.textContent = updated ? `آخرین بروزرسانی: ${formatFaDateTime(updated)}` : "لینک لایو توسط مدیریت ثبت شده است.";
  }
}

function updateBuyActionState({ statusKey, myCardsCount }) {
  const actionForm = getEl("buyActionForm");
  const actionHint = getEl("liveActionHint");
  const buyHint = getEl("buyStatusHint");
  const buyBtn = getEl("buyCardsBtn");

  const canBuy = Boolean(state.selectedGameId) && String(statusKey || "").toUpperCase() === "LOBBY";
  if (actionForm) actionForm.classList.toggle("hidden", !canBuy);
  if (buyBtn) {
    buyBtn.disabled = !canBuy;
    buyBtn.classList.toggle("disabled", !canBuy);
  }

  if (buyHint) {
    if (!canBuy) buyHint.textContent = "";
    else if (Number(myCardsCount || 0) <= 0) buyHint.textContent = "هنوز کارتی نخریدی. الان وارد بازی شو.";
    else buyHint.textContent = "";
  }

  if (actionHint) {
    if (!state.selectedGameId) {
      actionHint.textContent = "برای خرید کارت، ابتدا یکی از بازی‌ها را باز کنید.";
    } else if (!canBuy) {
      actionHint.textContent = "خرید کارت فقط قبل از شروع بازی فعال است.";
    } else {
      actionHint.textContent = "";
    }
  }
}

function renderLiveEvents(events) {
  const evRoot = getEl("liveEvents");
  if (!evRoot) return;
  const list = Array.isArray(events) ? events.slice(-LIVE_EVENTS_LIMIT) : [];
  evRoot.innerHTML = list.length
    ? list
        .map((e) => {
          const mine = isMyWinnerEvent(e);
          const chipClass = mine ? "event-chip winner-event" : "event-chip";
          const winnerText = mine
            ? '<div class="winner-note">تبریک! این برد برای شما ثبت شد.</div>'
            : "";
          return `
          <div class="${chipClass}">
            <strong>${safeText(eventKindLabel(e.kind))}</strong>
            <div>${safeText(formatFaDateTime(e.created_at))}</div>
            ${winnerText}
          </div>`;
        })
        .join("")
    : '<div class="empty">هنوز رویدادی ثبت نشده است.</div>';
  list.forEach((e) => pushWinnerNotice(e));
}

function renderLive(snapshot) {
  const stateBox = getEl("liveState");
  if (!stateBox) return;

  const game = snapshot.game;
  const st = snapshot.state || {};
  state.gameSnapshots.set(Number(game.id), snapshot);

  if (liveGameMeta) {
    liveGameMeta.textContent = `#${game.id} | ${statusLabel(game.status)}`;
  }

  const called = Array.isArray(st.called_numbers) ? st.called_numbers : [];
  const tailNumbers = called.slice(-45);
  const lastNow = st.last_number ?? (called.length ? called[called.length - 1] : null);
  const prevLast = state.latestLiveNumberByGame[Number(game.id)];
  const lastFresh = prevLast !== undefined && prevLast !== null && Number(lastNow) !== Number(prevLast);
  state.latestLiveNumberByGame[Number(game.id)] = lastNow;
  const lastNumberClass = lastFresh ? "last-number-pop fresh" : "last-number-pop";
  const calledGrid = tailNumbers.length
    ? tailNumbers
        .map((n) => {
          const isFresh = Number(lastNow) === Number(n) && lastFresh;
          return `<span class="${isFresh ? "live-called-chip fresh" : "live-called-chip"}">${safeText(n)}</span>`;
        })
        .join("")
    : '<div class="empty">هنوز عددی اعلام نشده است.</div>';

  stateBox.innerHTML = `
    <div id="liveWinnerBanner"></div>
    <div class="live-main live-main-pro">
      <div class="live-top">
        <div>
          <div>وضعیت: <strong>${safeText(statusLabel(st.status || game.status))}</strong></div>
          <div>مجموع جایزه: <strong>${toman(st.prize_pool ?? game.prize_pool)}</strong></div>
          <div class="meta">اعداد اعلام‌شده: ${safeText(st.called_count || called.length)}</div>
        </div>
        <div class="live-last-wrap">
          <div class="live-last-label">آخرین عدد</div>
          <div class="${lastNumberClass}">${safeText(lastNow ?? "-")}</div>
        </div>
      </div>
      <div class="live-called-grid">${calledGrid}</div>
    </div>
  `;

  if (lastFresh && lastNow !== null && lastNow !== undefined) {
    playNumberFeedback();
  }

  renderWinnerBannerFromState(game.id, st);
  renderGameTimeline(game, st);
  renderLiveInsights(st);
  renderLiveLink(st);
  updateBuyActionState({
    statusKey: String(st.status || game.status || "").toUpperCase(),
    myCardsCount: Number(st.my_cards_count || 0),
  });
  renderLiveEvents(snapshot.recent_events || []);
}

async function openLiveGame(gameId) {
  state.selectedGameId = Number(gameId);
  const snapshot = await apiFetch(`/mini-api/games/${gameId}/snapshot?events_limit=${LIVE_EVENTS_LIMIT}`);
  state.lastEventId = Number(snapshot.last_event_id || 0);
  setVal("buyQtyInput", "1");
  renderLive(snapshot);
  setBadge("success", `بازی #${gameId} انتخاب شد`);
  startEventPolling();
}

function appendEvents(events) {
  if (!events?.length) return;
  const evRoot = getEl("liveEvents");
  if (!evRoot) return;

  const html = events
    .map((e) => {
      const mine = isMyWinnerEvent(e);
      const chipClass = mine ? "event-chip winner-event" : "event-chip";
      const winnerText = mine ? '<div class="winner-note">تبریک! این برد برای شما ثبت شد.</div>' : "";
      return `
      <div class="${chipClass}">
        <strong>${safeText(eventKindLabel(e.kind))}</strong>
        <div>${safeText(formatFaDateTime(e.created_at))}</div>
        ${winnerText}
      </div>`;
    })
    .join("");

  evRoot.insertAdjacentHTML("beforeend", html);
  while (evRoot.children.length > LIVE_EVENTS_LIMIT) {
    evRoot.removeChild(evRoot.firstElementChild);
  }
  evRoot.scrollTop = evRoot.scrollHeight;

  events.forEach((e) => pushWinnerNotice(e));
}


function startEventPolling() {
  stopEventPolling();
  if (!state.selectedGameId) return;
  state.pollTimer = setInterval(async () => {
    try {
      const events = await apiFetch(
        `/mini-api/games/${state.selectedGameId}/events?after_id=${state.lastEventId}&limit=${LIVE_EVENTS_LIMIT}`
      );
      if (events?.length) {
        state.lastEventId = Number(events[events.length - 1].id || state.lastEventId);
        const calledEvent = events.find((e) => String(e?.kind || "").toUpperCase() === "NUMBER_CALLED");
        if (calledEvent) {
          playNumberFeedback();
        }
        const snap = await apiFetch(`/mini-api/games/${state.selectedGameId}/snapshot?events_limit=${LIVE_EVENTS_LIMIT}`);
        state.lastEventId = Math.max(Number(state.lastEventId || 0), Number(snap.last_event_id || 0));
        renderLive(snap);
      }
    } catch (_) {}
  }, 1200);
}

function stopEventPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

async function refreshAutoTick() {
  const tasks = [refreshGames(), refreshWallet()];
  if (isCardsViewActive()) {
    tasks.push(refreshCards({ silent: true }));
  }
  if (state.admin.enabled && isAdminViewActive()) {
    tasks.push(refreshAdminPanel({ silent: true }));
  }
  if (state.admin.enabled) {
    tasks.push(checkAdminFinanceNotifications({ silent: false }));
  }
  await Promise.allSettled(tasks);
  if (state.selectedGameId) {
    try {
      const snap = await apiFetch(`/mini-api/games/${state.selectedGameId}/snapshot?events_limit=${LIVE_EVENTS_LIMIT}`);
      state.lastEventId = Math.max(Number(state.lastEventId || 0), Number(snap?.last_event_id || 0));
      renderLive(snap);
    } catch (_) {}
  }
}

function startGlobalRefresh() {
  stopGlobalRefresh();
  state.globalRefreshTimer = setInterval(() => {
    if (!state.authReady) return;
    refreshAutoTick().catch(() => {});
  }, GLOBAL_REFRESH_INTERVAL_MS);
}

function stopGlobalRefresh() {
  if (state.globalRefreshTimer) clearInterval(state.globalRefreshTimer);
  state.globalRefreshTimer = null;
}

async function refreshGames() {
  const [gamesSettled, cardsSettled, insightsSettled] = await Promise.allSettled([
    apiFetch("/mini-api/games?status=LOBBY,RUNNING&limit=30"),
    apiFetch("/mini-api/me/cards?limit=200"),
    apiFetch("/mini-api/dashboard/insights"),
  ]);

  const gamesRes = gamesSettled.status === "fulfilled" ? gamesSettled.value : null;
  const cardsRes = cardsSettled.status === "fulfilled" ? cardsSettled.value : null;
  const insights = insightsSettled.status === "fulfilled" ? insightsSettled.value : null;

  const gameItems = Array.isArray(gamesRes?.items) ? gamesRes.items : (Array.isArray(state.gamesCache) ? state.gamesCache : []);
  const cards = Array.isArray(cardsRes?.items) ? cardsRes.items : null;
  if (Array.isArray(gamesRes?.items)) {
    state.gamesCache = gamesRes.items;
  }

  if (Array.isArray(cards)) {
    state.myCardsByGame = new Map();
    cards.forEach((c) => {
      const gid = Number(c?.game_id || 0);
      if (!gid) return;
      state.myCardsByGame.set(gid, Number(state.myCardsByGame.get(gid) || 0) + 1);
    });
  }

  if (insights) {
    state.hotGameId = null;
    state.userFlags.inGame = Boolean(insights?.in_game);
    state.userFlags.recentWinner = Boolean(insights?.recent_winner);
    state.recentGamesStats = Array.isArray(insights?.recent_games) ? insights.recent_games : [];
    state.dashboardTrust = insights?.trust || null;
  }
  updateHeaderStatus();

  const snapshotResults = await Promise.allSettled(
    gameItems.slice(0, 10).map((g) => apiFetch(`/mini-api/games/${g.id}/snapshot?events_limit=1`))
  );
  snapshotResults.forEach((res) => {
    if (res.status === "fulfilled") {
      const gid = Number(res.value?.game?.id || 0);
      if (gid) state.gameSnapshots.set(gid, res.value);
    }
  });

  drawGames(gameItems);
  drawRecentStats(state.recentGamesStats);
  drawTrustStrip(state.dashboardTrust);
}

function localizeCardsShell() {
  const textMap = {
    cardsTitle: "کارت‌های من",
    refreshCardsBtn: "به‌روزرسانی",
    cardsHint:
      "کارت‌های بازی‌های فعال به صورت زنده هایلایت می‌شوند و ۱۰ خرید آخر در تاریخچه نمایش داده می‌شود.",
    cardsPullHint: "برای نوسازی، صفحه را کمی به پایین بکشید.",
    cardsLiveStatus: "در انتظار بازی فعال",
    cardsActiveTitle: "کارت‌های خریداری‌شده بازی‌های فعال",
    cardsHistoryTitle: "تاریخچه خرید کارت (۱۰ مورد آخر)",
    cardsHistoryMeta: "اسکرول‌پذیر",
  };

  Object.entries(textMap).forEach(([id, value]) => {
    const el = getEl(id);
    if (el) el.textContent = value;
  });
}

function renderCardsPullHint(textValue = "", stateName = "idle") {
  const hint = getEl("cardsPullHint");
  if (!hint) return;
  hint.dataset.state = String(stateName || "idle");
  if (textValue) {
    hint.textContent = textValue;
    return;
  }
  hint.textContent = "برای نوسازی، صفحه را کمی به پایین بکشید.";
}

function buildCalledStream(numbers, freshNumbers = [], limit = 42) {
  const list = Array.isArray(numbers) ? numbers : [];
  if (!list.length) return '<div class="empty">هنوز عددی اعلام نشده است.</div>';
  const freshSet = new Set((freshNumbers || []).map((x) => Number(x)));
  return list
    .slice(-Math.max(1, Number(limit) || 42))
    .map((n) => {
      const klass = freshSet.has(Number(n)) ? "called-chip new" : "called-chip";
      return `<span class="${klass}">${safeText(n)}</span>`;
    })
    .join("");
}

function buildCardGrid(numbers, calledSet, freshSet, winnerSet = new Set()) {
  const list = Array.isArray(numbers) ? numbers : [];
  return list
    .map((n, idx) => {
      const num = Number(n);
      let cls = freshSet.has(num) ? "num-chip called fresh" : calledSet.has(num) ? "num-chip called" : "num-chip";
      if (winnerSet.has(idx)) cls += " win";
      return `<span class="${cls}">${safeText(num)}</span>`;
    })
    .join("");
}

function calcWinnerCellIndices(numbers, calledSet, { row = false, col = false } = {}) {
  const out = new Set();
  const nums = Array.isArray(numbers) ? numbers : [];
  if (nums.length < 20) return out;

  if (row) {
    for (let r = 0; r < 4; r += 1) {
      const start = r * 5;
      const rowNums = nums.slice(start, start + 5);
      if (rowNums.every((n) => calledSet.has(Number(n)))) {
        for (let i = start; i < start + 5; i += 1) out.add(i);
      }
    }
  }

  if (col) {
    for (let c = 0; c < 5; c += 1) {
      const colNums = [nums[c], nums[c + 5], nums[c + 10], nums[c + 15]];
      if (colNums.every((n) => calledSet.has(Number(n)))) {
        out.add(c);
        out.add(c + 5);
        out.add(c + 10);
        out.add(c + 15);
      }
    }
  }
  return out;
}

function bindCardsEmptyCta() {
  const btn = getEl("goGamesFromCardsBtn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    switchToView("games");
  });
}

function renderCardsSkeleton() {
  const activeRoot = getEl("cardsActiveList");
  const historyRoot = getEl("cardsHistoryList");
  const activeMeta = getEl("cardsActiveMeta");
  if (activeMeta) activeMeta.textContent = "در حال بارگذاری...";
  if (activeRoot) {
    activeRoot.innerHTML = `
      <div class="cards-skeleton">
        <div class="skeleton-line lg"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line"></div>
      </div>
      <div class="cards-skeleton">
        <div class="skeleton-line lg"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line"></div>
      </div>
    `;
  }
  if (historyRoot) {
    historyRoot.innerHTML = `
      <div class="cards-skeleton"><div class="skeleton-line"></div><div class="skeleton-line"></div></div>
      <div class="cards-skeleton"><div class="skeleton-line"></div><div class="skeleton-line"></div></div>
      <div class="cards-skeleton"><div class="skeleton-line"></div><div class="skeleton-line"></div></div>
    `;
  }
  const badgeStatus = getEl("cardsLiveStatus");
  const badgeLast = getEl("cardsLiveLast");
  const calledStream = getEl("cardsCalledStream");
  if (badgeStatus) badgeStatus.textContent = "در حال همگام‌سازی زنده";
  if (badgeLast) badgeLast.textContent = "...";
  if (calledStream) calledStream.innerHTML = '<div class="empty">در حال دریافت اعداد خوانده‌شده...</div>';
}

function renderCardsEmpty() {
  const activeRoot = getEl("cardsActiveList");
  const historyRoot = getEl("cardsHistoryList");
  const activeMeta = getEl("cardsActiveMeta");
  if (activeMeta) activeMeta.textContent = "۰ کارت فعال";
  if (activeRoot) {
    activeRoot.innerHTML = `
      <div class="empty-rich">
        <div>هنوز کارتی خریداری نکرده‌ای.</div>
        <button id="goGamesFromCardsBtn" class="small-btn primary" type="button">رفتن به بازی‌ها</button>
      </div>
    `;
  }
  if (historyRoot) {
    historyRoot.innerHTML = '<div class="empty">تاریخچه‌ای برای نمایش وجود ندارد.</div>';
  }
  const badgeStatus = getEl("cardsLiveStatus");
  const badgeLast = getEl("cardsLiveLast");
  const calledStream = getEl("cardsCalledStream");
  if (badgeStatus) badgeStatus.textContent = "در انتظار خرید کارت";
  if (badgeLast) badgeLast.textContent = "-";
  if (calledStream) calledStream.innerHTML = '<div class="empty">پس از خرید کارت در بازی فعال، اعداد اینجا نمایش داده می‌شوند.</div>';
  bindCardsEmptyCta();
}

function renderCardsBadge(activeGames) {
  const badgeStatus = getEl("cardsLiveStatus");
  const badgeLast = getEl("cardsLiveLast");
  const calledStream = getEl("cardsCalledStream");
  if (!badgeStatus || !badgeLast || !calledStream) return;

  if (!activeGames.length) {
    badgeStatus.textContent = "بازی فعالی برای پایش نیست";
    badgeLast.textContent = "-";
    calledStream.innerHTML = '<div class="empty">عددی برای نمایش وجود ندارد.</div>';
    return;
  }

  const sorted = [...activeGames].sort((a, b) => {
    const ea = Number(a.eventMarker || 0);
    const eb = Number(b.eventMarker || 0);
    if (eb !== ea) return eb - ea;
    return Number(b.gameId || 0) - Number(a.gameId || 0);
  });
  const g = sorted[0];
  const lastNum = g.lastNumber ?? (g.calledNumbers.length ? g.calledNumbers[g.calledNumbers.length - 1] : "-");
  const freshLast = g.freshNumbers.length ? g.freshNumbers[g.freshNumbers.length - 1] : null;

  if (freshLast !== null && freshLast !== undefined) {
    badgeStatus.textContent = `عدد جدید رسید | بازی #${g.gameId}`;
    badgeLast.textContent = String(freshLast);
  } else {
    badgeStatus.textContent = `آخرین عدد بازی #${g.gameId}`;
    badgeLast.textContent = String(lastNum ?? "-");
  }

  calledStream.innerHTML = buildCalledStream(g.calledNumbers, g.freshNumbers, 55);
}

function renderCardsActive(activeGames) {
  const root = getEl("cardsActiveList");
  const activeMeta = getEl("cardsActiveMeta");
  if (!root) return;

  if (!activeGames.length) {
    if (activeMeta) activeMeta.textContent = "۰ کارت فعال";
    root.innerHTML = `
      <div class="empty-rich">
        <div>فعلاً کارت فعالی در بازی‌های جاری نداری.</div>
        <button id="goGamesFromCardsBtn" class="small-btn" type="button">مشاهده بازی‌های فعال</button>
      </div>
    `;
    bindCardsEmptyCta();
    return;
  }

  const totalCards = activeGames.reduce((acc, g) => acc + g.cards.length, 0);
  if (activeMeta) {
    activeMeta.textContent = `${activeGames.length} بازی فعال | ${totalCards} کارت`;
  }

  root.innerHTML = activeGames
    .map((g) => {
      const calledSet = new Set((g.calledNumbers || []).map((x) => Number(x)));
      const freshSet = new Set((g.freshNumbers || []).map((x) => Number(x)));
      const calledTail = (g.calledNumbers || []).slice(-20);
      const calledTailText = calledTail.length ? calledTail.join("، ") : "هنوز عددی اعلام نشده";
      return `
        <div class="active-game-block game-emphasis-block active-game-block-ux21">
          <div class="active-game-head">
            <h4>بازی #${g.gameId}</h4>
            <div class="active-game-meta">
              <span>${safeText(statusLabel(g.status))}</span>
              <span>آخرین عدد: <strong>${safeText(g.lastNumber ?? "-")}</strong></span>
              <button class="small-btn open-from-cards" data-game-id="${g.gameId}" type="button">ورود</button>
            </div>
          </div>
          <div class="history-meta">اعداد اعلام‌شده: ${safeText(calledTailText)}</div>
          <div class="cards-active-grid">
            ${g.cards
              .map((c) => {
                const nums = Array.isArray(c.numbers) ? c.numbers : [];
                const calledCount = nums.reduce((acc, n) => acc + (calledSet.has(Number(n)) ? 1 : 0), 0);
                const total = nums.length || 0;
                const percent = total ? Math.round((calledCount / total) * 100) : 0;
                const rowWinner = new Set((g.rowWinnerCardIds || []).map((x) => Number(x)));
                const colWinner = new Set((g.colWinnerCardIds || []).map((x) => Number(x)));
                const isRowWinner = rowWinner.has(Number(c.card_id));
                const isColWinner = colWinner.has(Number(c.card_id));
                const winnerCells = calcWinnerCellIndices(nums, calledSet, {
                  row: isRowWinner,
                  col: isColWinner,
                });
                const winnerLabel = isRowWinner && isColWinner
                  ? '<span class="winner-kind-pill">برنده ستونی(تورنا) + سطری(تمام)</span>'
                  : isRowWinner
                    ? '<span class="winner-kind-pill">برنده سطری(تمام)</span>'
                    : isColWinner
                      ? '<span class="winner-kind-pill">برنده ستونی(تورنا)</span>'
                      : "";
                const cardClass = isRowWinner || isColWinner ? "card-pro winner-focus" : "card-pro";
                return `
                  <div class="${cardClass}">
                    <div class="card-pro-head">
                      <strong>کارت #${c.card_id}</strong>
                      <span>${safeText(formatFaDateTime(c.created_at))}</span>
                    </div>
                    ${winnerLabel}
                    <div class="card-progress">
                      <span>${calledCount} از ${total} عدد کارت خوانده شده</span>
                      <div class="card-progress-bar"><i style="width:${percent}%"></i></div>
                    </div>
                    <div class="mini-card-grid">${buildCardGrid(nums, calledSet, freshSet, winnerCells)}</div>
                  </div>
                `;
              })
              .join("")}
          </div>
        </div>
      `;
    })
    .join("");

  root.querySelectorAll(".open-from-cards").forEach((btn) => {
    btn.addEventListener("click", () => {
      const gid = Number(btn.getAttribute("data-game-id") || "0");
      if (!gid) return;
      switchToView("games");
      openLiveGame(gid).catch((err) => setBadge("error", err.message));
    });
  });
}

function renderCardsHistory(items) {
  const root = getEl("cardsHistoryList");
  if (!root) return;
  const list = Array.isArray(items) ? items.slice(0, CARD_HISTORY_LIMIT) : [];
  if (!list.length) {
    root.innerHTML = '<div class="empty">تاریخچه خرید کارت خالی است.</div>';
    return;
  }

  root.innerHTML = list
    .map(
      (c) => `
        <div class="history-item clickable" data-game-id="${Number(c.game_id || 0)}" data-card-id="${Number(c.card_id || 0)}">
          <strong>بازی #${c.game_id} | کارت #${c.card_id}</strong>
          <div class="history-meta">
            وضعیت بازی: ${safeText(statusLabel(c.game_status))}<br />
            قیمت کارت: ${toman(c.card_price)}<br />
            زمان خرید: ${safeText(formatFaDateTime(c.created_at))}
          </div>
          <div class="history-open-hint">برای مشاهده جزئیات کارت لمس کنید</div>
        </div>
      `
    )
    .join("");

  root.querySelectorAll(".history-item.clickable").forEach((row) => {
    row.addEventListener("click", () => {
      const gameId = Number(row.getAttribute("data-game-id") || "0");
      const cardId = Number(row.getAttribute("data-card-id") || "0");
      if (!gameId) return;
      openHistoryModalForGame(gameId, { cardId, source: "history" }).catch((e) => setBadge("error", e.message));
    });
  });
}

function closeHistoryModal() {
  const modal = getEl("historyModal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

async function openHistoryModalForGame(gameId, { cardId = 0, source = "history" } = {}) {
  const modal = getEl("historyModal");
  const titleEl = getEl("historyModalTitle");
  const metaEl = getEl("historyModalMeta");
  const bodyEl = getEl("historyModalBody");
  if (!modal || !titleEl || !metaEl || !bodyEl) return;

  const gid = Number(gameId || 0);
  if (!gid) return;
  bodyEl.innerHTML = '<div class="empty">در حال بارگذاری جزئیات...</div>';
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");

  try {
    const [snapshot, cardsPayload] = await Promise.all([
      apiFetch(`/mini-api/games/${gid}/snapshot?events_limit=${LIVE_EVENTS_LIMIT}`),
      apiFetch(`/mini-api/me/cards?game_id=${gid}&limit=200`),
    ]);

    const cards = Array.isArray(cardsPayload?.items) ? cardsPayload.items : [];
    const targetCards = Number(cardId || 0) > 0
      ? cards.filter((c) => Number(c?.card_id || 0) === Number(cardId))
      : cards;
    const shownCards = targetCards.slice(0, HISTORY_LIST_LIMIT);

    const st = snapshot?.state || {};
    const calledNumbers = Array.isArray(st.called_numbers)
      ? st.called_numbers.map((x) => Number(x)).filter((x) => Number.isFinite(x))
      : [];
    const calledSet = new Set(calledNumbers);
    const rowWinnerSet = new Set((st.row_winner_card_ids || []).map((x) => Number(x)));
    const colWinnerSet = new Set((st.col_winner_card_ids || []).map((x) => Number(x)));

    titleEl.textContent = source === "wins" ? `جزئیات برد بازی #${gid}` : `جزئیات کارت‌های بازی #${gid}`;
    metaEl.textContent = `وضعیت: ${statusLabel(st.status || snapshot?.game?.status)} | اعداد اعلام‌شده: ${calledNumbers.length}`;

    if (!shownCards.length) {
      bodyEl.innerHTML = '<div class="empty">کارتی برای نمایش در این بازی پیدا نشد.</div>';
      return;
    }

    const head = `
      <div class="history-modal-head history-modal-head-ux21">
        آخرین عدد: <strong>${safeText(st.last_number ?? "-")}</strong> |
        مجموع جایزه: <strong>${safeText(toman((st.prize_pool ?? snapshot?.game?.prize_pool ?? 0)))}</strong>
      </div>
    `;

    const cardsHtml = shownCards
      .map((c) => {
        const nums = Array.isArray(c?.numbers) ? c.numbers : [];
        const isRowWinner = rowWinnerSet.has(Number(c.card_id || 0));
        const isColWinner = colWinnerSet.has(Number(c.card_id || 0));
        const winnerCells = calcWinnerCellIndices(nums, calledSet, { row: isRowWinner, col: isColWinner });
        const winnerLabel = winnerKindLabelByFlags({ row: isRowWinner, col: isColWinner });
        const resultText = winnerLabel ? `برنده: ${winnerLabel}` : "هنوز برنده ثبت نشده";
        return `
          <div class="history-modal-card-item history-modal-card-item-ux21">
            <div class="card-pro-head">
              <span class="card-id-stack"><strong>کارت #${safeText(c.card_id)}</strong><em>بازی #${gid}</em></span>
              <span class="card-game-badge">بازی #${gid}</span>
              <span>${safeText(formatFaDateTime(c.created_at))}</span>
            </div>
            ${winnerLabel ? `<span class="winner-kind-pill">${safeText(winnerLabel)}</span>` : ""}
            <div class="history-modal-result history-modal-result-ux21">${safeText(resultText)}</div>
            <div class="mini-card-grid">${buildCardGrid(nums, calledSet, new Set(), winnerCells)}</div>
          </div>
        `;
      })
      .join("");

    bodyEl.innerHTML = `${head}<div class="history-modal-grid history-modal-grid-ux21">${cardsHtml}</div>`;
  } catch (err) {
    const msg = localizeApiError(err?.message || err || "خطای بارگذاری جزئیات");
    titleEl.textContent = source === "wins" ? `جزئیات برد بازی #${gid}` : `جزئیات کارت‌های بازی #${gid}`;
    metaEl.textContent = "بارگذاری ناموفق";
    bodyEl.innerHTML = `<div class="empty">جزئیات کارت‌ها بارگذاری نشد. ${safeText(msg)}</div>`;
    setBadge("error", msg);
  }
}
function groupCardsByGame(items) {
  const out = new Map();
  for (const item of items || []) {
    const gid = Number(item?.game_id || 0);
    if (!gid) continue;
    if (!out.has(gid)) out.set(gid, []);
    out.get(gid).push(item);
  }
  return out;
}

async function refreshCards({ silent = false } = {}) {
  if (!silent) {
    renderCardsSkeleton();
  }

  const payload = await apiFetch("/mini-api/me/cards?limit=100");
  const allCards = Array.isArray(payload?.items) ? payload.items : [];

  if (!allCards.length) {
    renderCardsEmpty();
    return;
  }

  const historyItems = allCards.slice(0, CARD_HISTORY_LIMIT);
  const activeCards = allCards.filter((c) => ACTIVE_GAME_STATUSES.has(String(c?.game_status || "").toUpperCase()));
  const byGame = groupCardsByGame(activeCards);
  const gameIds = [...byGame.keys()].sort((a, b) => b - a);

  const snapshotResults = await Promise.allSettled(
    gameIds.map((gid) => apiFetch(`/mini-api/games/${gid}/snapshot?events_limit=1`))
  );

  const snapshots = new Map();
  snapshotResults.forEach((res, idx) => {
    if (res.status === "fulfilled") {
      snapshots.set(gameIds[idx], res.value);
    }
  });

  const activeGames = gameIds.map((gid) => {
    const cards = byGame.get(gid) || [];
    const snap = snapshots.get(gid) || null;
    const calledNumbers = Array.isArray(snap?.state?.called_numbers)
      ? snap.state.called_numbers.map((x) => Number(x)).filter((x) => Number.isFinite(x))
      : [];
    const prevNumbers = Array.isArray(state.cardsPrevCalledByGame[gid]) ? state.cardsPrevCalledByGame[gid] : [];
    const prevSet = new Set(prevNumbers.map((x) => Number(x)));
    const freshNumbers = calledNumbers.filter((n) => !prevSet.has(Number(n)));

    state.cardsPrevCalledByGame[gid] = calledNumbers;
    state.cardsLatestSeenEventByGame[gid] = Number(snap?.last_event_id || 0);

    return {
      gameId: gid,
      status: String(snap?.game?.status || cards[0]?.game_status || "LOBBY"),
      eventMarker: Number(snap?.last_event_id || 0),
      calledNumbers,
      freshNumbers,
      lastNumber: snap?.state?.last_number ?? (calledNumbers.length ? calledNumbers[calledNumbers.length - 1] : null),
      rowWinnerCardIds: Array.isArray(snap?.state?.row_winner_card_ids) ? snap.state.row_winner_card_ids.map((x) => Number(x)) : [],
      colWinnerCardIds: Array.isArray(snap?.state?.col_winner_card_ids) ? snap.state.col_winner_card_ids.map((x) => Number(x)) : [],
      cards,
    };
  });

  state.userFlags.inGame = activeGames.length > 0;
  updateHeaderStatus();

  renderCardsBadge(activeGames);
  renderCardsActive(activeGames);
  renderCardsHistory(historyItems);
  drawWinTimeline();

  if (!silent) {
    setBadge("success", "کارت‌های من به‌روزرسانی شد");
  }
}

function startCardsPolling() {
  stopCardsPolling();
  state.cardsPollTimer = setInterval(() => {
    if (!isCardsViewActive()) return;
    refreshCards({ silent: true }).catch(() => {});
  }, CARDS_REFRESH_INTERVAL_MS);
}

function stopCardsPolling() {
  if (state.cardsPollTimer) clearInterval(state.cardsPollTimer);
  state.cardsPollTimer = null;
}

async function refreshCardsFromPull() {
  if (state.cardsPullBusy) return;
  state.cardsPullBusy = true;
  renderCardsPullHint("در حال به‌روزرسانی کارت‌ها...", "refresh");
  try {
    await refreshCards({ silent: false });
  } finally {
    state.cardsPullBusy = false;
    renderCardsPullHint("برای نوسازی، صفحه را کمی به پایین بکشید.", "idle");
  }
}

function wireCardsPullToRefresh() {
  const panel = getEl("cardsPanel");
  if (!panel) return;

  let tracking = false;
  let startY = 0;
  let deltaY = 0;

  panel.addEventListener(
    "touchstart",
    (e) => {
      if (!isCardsViewActive()) return;
      const top = Number(window.scrollY || document.documentElement.scrollTop || 0);
      if (top > 2) return;
      tracking = true;
      startY = Number(e.touches?.[0]?.clientY || 0);
      deltaY = 0;
    },
    { passive: true }
  );

  panel.addEventListener(
    "touchmove",
    (e) => {
      if (!tracking) return;
      const y = Number(e.touches?.[0]?.clientY || 0);
      deltaY = y - startY;
      if (deltaY > 84) {
        renderCardsPullHint("رها کنید تا کارت‌ها به‌روزرسانی شوند.", "ready");
      } else if (deltaY > 26) {
        renderCardsPullHint("برای نوسازی بیشتر به پایین بکشید.", "pull");
      }
    },
    { passive: true }
  );

  panel.addEventListener(
    "touchend",
    () => {
      if (!tracking) return;
      tracking = false;
      if (deltaY > 84) {
        refreshCardsFromPull().catch((e) => setBadge("error", e.message));
      } else {
        renderCardsPullHint("برای نوسازی، صفحه را کمی به پایین بکشید.", "idle");
      }
      deltaY = 0;
    },
    { passive: true }
  );
}


function drawWallet(balancePayload, txPayload) {
  const balEl = getEl("walletBalance");
  const balance = Number(balancePayload?.balance || 0);
  if (balEl) balEl.textContent = toman(balance);

  const txRoot = getEl("walletTxs");
  if (!txRoot) return;

  const txItems = Array.isArray(txPayload)
    ? txPayload
    : Array.isArray(txPayload?.items)
      ? txPayload.items
      : [];
  state.walletTxs = txItems;
  const nowMs = Date.now();
  const hasRecentPrize = txItems.some((tx) => {
    const reason = String(tx?.reason || "").toUpperCase();
    if (!(reason === "PRIZE_COL" || reason === "PRIZE_ROW")) return false;
    const created = Date.parse(String(tx?.created_at || ""));
    if (!Number.isFinite(created)) return true;
    return nowMs - created <= 24 * 60 * 60 * 1000;
  });
  if (hasRecentPrize) {
    state.userFlags.recentWinner = true;
  }
  updateHeaderStatus();

  if (!txItems.length) {
    txRoot.innerHTML = '<div class="empty">تراکنشی برای نمایش وجود ندارد.</div>';
    return;
  }

  txRoot.innerHTML = txItems
    .slice(0, HISTORY_LIST_LIMIT)
    .map((tx) => {
      const direction = String(tx.direction || "").toUpperCase();
      const credit = direction === "CREDIT";
      const klass = credit ? "tx-chip credit" : "tx-chip debit";
      const sign = credit ? "+" : "-";
      const reason = walletReasonLabel(tx.reason);
      return `
        <div class="${klass}">
          <div>
            <strong>${safeText(reason)}</strong><br />
            <span class="meta">${safeText(formatFaDateTime(tx.created_at))}</span>
          </div>
          <div><strong>${sign}${toman(tx.amount || 0)}</strong></div>
        </div>
      `;
    })
    .join("");
}

function drawDepositRequests(payload) {
  const root = getEl("depositRequestsList");
  if (!root) return;

  const items = Array.isArray(payload?.items) ? payload.items.slice(0, HISTORY_LIST_LIMIT) : [];
  if (!items.length) {
    root.innerHTML = '<div class="empty">درخواست واریزی ثبت نشده است.</div>';
    return;
  }

  root.innerHTML = items
    .map((d) => `
      <div class="item">
        <h3>واریزی #${d.id}</h3>
        <p>وضعیت: ${safeText(depositStatusLabel(d.status))} | مبلغ: ${toman(d.amount || 0)}</p>
        <div class="meta">کارت مقصد: ${safeText(String(d.destination_title || "-"))}</div>
        <div class="meta">زمان ثبت: ${safeText(formatFaDateTime(d.created_at))}</div>
      </div>
    `)
    .join("");
}

function drawWithdrawRequests(payload) {
  const root = getEl("withdrawRequestsList");
  if (!root) return;

  const items = Array.isArray(payload?.items) ? payload.items.slice(0, HISTORY_LIST_LIMIT) : [];
  if (!items.length) {
    root.innerHTML = '<div class="empty">درخواست برداشتی ثبت نشده است.</div>';
    return;
  }

  root.innerHTML = items
    .map((w) => `
      <div class="item">
        <h3>برداشت #${w.id}</h3>
        <p>وضعیت: ${safeText(withdrawStatusLabel(w.status))} | مبلغ: ${toman(w.amount || 0)}</p>
        <div class="meta">زمان ثبت: ${safeText(formatFaDateTime(w.created_at))}</div>
      </div>
    `)
    .join("");
}

function drawWinTimeline() {
  const root = getEl("cardsWinsTimeline");
  const filterEl = getEl("winsGameFilter");
  if (!root || !filterEl) return;

  const wins = (state.walletTxs || []).filter((tx) => {
    const r = String(tx?.reason || "").toUpperCase();
    return r === "PRIZE_ROW" || r === "PRIZE_COL";
  });

  const gameIds = [...new Set(wins.map((w) => Number(w?.ref_id || 0)).filter((x) => x > 0))].sort((a, b) => b - a);
  const prev = String(filterEl.value || "all");
  filterEl.innerHTML = `<option value="all">همه بازی‌ها</option>${gameIds
    .map((gid) => `<option value="${gid}">بازی #${gid}</option>`)
    .join("")}`;
  if (prev && (prev === "all" || gameIds.includes(Number(prev)))) {
    filterEl.value = prev;
  }
  const selected = String(filterEl.value || "all");

  const filtered = wins
    .filter((w) => (selected === "all" ? true : Number(w?.ref_id || 0) === Number(selected)))
    .slice(0, HISTORY_LIST_LIMIT);

  if (!filtered.length) {
    root.innerHTML = '<div class="empty">بردی برای نمایش وجود ندارد.</div>';
    return;
  }

  root.innerHTML = filtered
    .map((w) => {
      const kind = winnerKindLabelByReason(String(w.reason || ""));
      const gid = Number(w.ref_id || 0);
      return `
        <div class="history-item clickable" data-game-id="${gid}" data-tx-id="${Number(w.id || 0)}">
          <strong>${safeText(kind)} | ${safeText(toman(w.amount || 0))}</strong>
          <div class="history-meta">
            بازی: ${gid > 0 ? `#${gid}` : "-"}<br />
            زمان: ${safeText(formatFaDateTime(w.created_at))}
          </div>
          <div id="adminWdrWalletStatus${safeText(w.id)}" class="withdraw-wallet-status">وضعیت کیف پول هنوز بروزرسانی نشده است.</div>
          <div class="history-open-hint">برای مشاهده جزئیات برد لمس کنید</div>
        </div>
      `;
    })
    .join("");

  root.querySelectorAll(".history-item.clickable").forEach((row) => {
    row.addEventListener("click", () => {
      const gameId = Number(row.getAttribute("data-game-id") || "0");
      if (!gameId) return;
      openHistoryModalForGame(gameId, { source: "wins" }).catch((e) => setBadge("error", e.message));
    });
  });
}

async function refreshWallet() {
  const [balanceSettled, txsSettled, depositsSettled, withdrawsSettled, destinationsSettled] = await Promise.allSettled([
    apiFetch("/mini-api/me/wallet"),
    apiFetch(`/mini-api/me/wallet/txs?limit=${HISTORY_LIST_LIMIT}`),
    apiFetch(`/mini-api/me/deposits?limit=${HISTORY_LIST_LIMIT}`),
    apiFetch(`/mini-api/me/withdraws?limit=${HISTORY_LIST_LIMIT}`),
    apiFetch("/mini-api/deposit-destinations"),
  ]);

  const balance = balanceSettled.status === "fulfilled" ? balanceSettled.value : state.walletCache.balance;
  const txs = txsSettled.status === "fulfilled" ? txsSettled.value : state.walletCache.txs;
  const deposits = depositsSettled.status === "fulfilled" ? depositsSettled.value : state.walletCache.deposits;
  const withdraws = withdrawsSettled.status === "fulfilled" ? withdrawsSettled.value : state.walletCache.withdraws;
  const destinations = destinationsSettled.status === "fulfilled" ? destinationsSettled.value : state.walletCache.destinations;

  if (balanceSettled.status === "fulfilled") state.walletCache.balance = balanceSettled.value;
  if (txsSettled.status === "fulfilled") state.walletCache.txs = txsSettled.value;
  if (depositsSettled.status === "fulfilled") state.walletCache.deposits = depositsSettled.value;
  if (withdrawsSettled.status === "fulfilled") state.walletCache.withdraws = withdrawsSettled.value;
  if (destinationsSettled.status === "fulfilled") state.walletCache.destinations = destinationsSettled.value;

  if (balance || txs) {
    drawWallet(balance || { balance: 0 }, txs || []);
    updateHeaderWallet(Number(balance?.balance || 0));
  }
  if (deposits) drawDepositRequests(deposits);
  if (withdraws) drawWithdrawRequests(withdraws);
  if (destinations) drawDepositDestinations(destinations);
  drawWinTimeline();
}

function drawDepositDestinations(payload) {
  const el = getEl("depositDestinationSelect");
  const copyBtn = getEl("copyDepositCardBtn");
  if (!el) return;

  const items = Array.isArray(payload?.items) ? payload.items : [];
  state.depositDestinations = items;
  const prev = getVal("depositDestinationSelect");

  if (!items.length) {
    el.innerHTML = '<option value="">کارت مقصدی موجود نیست</option>';
    el.classList.remove("has-selection");
    if (copyBtn) copyBtn.disabled = true;
    setHint("depositDestinationHint", "هیچ کارت مقصد فعالی در سیستم تعریف نشده است.");
    return;
  }

  el.innerHTML = items
    .map((it) => {
      const label = `${it.title} | ${ltrIsolateText(maskCard(it.card_number))}`;
      return `<option value="${safeText(it.id)}">${safeText(label)}</option>`;
    })
    .join("");

  if (prev && items.some((it) => String(it.id) === prev)) {
    el.value = prev;
  } else {
    el.value = String(items[0].id || "");
  }
  if (copyBtn) copyBtn.disabled = false;
  renderDepositDestinationHint();
}

async function buySelectedGame() {
  if (!state.selectedGameId) {
    throw new Error("ابتدا یک بازی را انتخاب کنید.");
  }
  const qty = Number(getVal("buyQtyInput") || "1");
  if (!qty || qty < 1 || qty > 50) {
    throw new Error("تعداد کارت نامعتبر است.");
  }

  const res = await apiFetch(`/mini-api/games/${state.selectedGameId}/buy`, {
    method: "POST",
    body: { qty, idempotency_key: idem("buy") },
  });
  setBadge("success", `خرید موفق بود. شماره خرید: ${res.purchase_id}`);
  await Promise.allSettled([refreshWallet(), refreshCards(), openLiveGame(state.selectedGameId)]);
}

async function submitDepositWithReceipt() {
  const amount = parsePositiveInt(getVal("depositAmountInput"));
  const destination_id = getVal("depositDestinationSelect") || null;
  const fileInput = getEl("depositReceiptFileInput");
  const file = fileInput?.files?.[0];

  if (!amount || amount <= 0) throw new Error("مبلغ واریز نامعتبر است.");
  if (!destination_id) throw new Error("کارت مقصد را انتخاب کنید.");
  if (!file) throw new Error("فایل رسید را انتخاب کنید.");

  setHint("depositSubmitHint", "در حال ثبت واریز و آپلود رسید...");
  setBadge("pending", "در حال ثبت واریز...");

  const created = await apiFetch("/mini-api/deposits", {
    method: "POST",
    body: { amount, destination_id },
  });
  const depositId = Number(created?.id || 0);
  if (!depositId || depositId <= 0) {
    throw new Error("درخواست واریز به‌درستی ایجاد نشد.");
  }

  try {
    const data_base64 = await readFileAsDataUrl(file);
    await apiFetch(`/mini-api/deposits/${depositId}/receipt`, {
      method: "POST",
      body: {
        filename: String(file.name || "receipt.jpg"),
        content_type: String(file.type || "application/octet-stream"),
        data_base64,
      },
    });
  } catch (err) {
    setHint("depositSubmitHint", `واریزی #${depositId} ثبت شد اما آپلود رسید ناموفق بود. دوباره تلاش کنید.`, "error");
    throw err;
  }

  if (fileInput) fileInput.value = "";
  setVal("depositAmountInput", "");
  setHint("depositSubmitHint", `واریزی #${depositId} با موفقیت ثبت شد و در صف بررسی ادمین قرار گرفت.`, "success");
  setBadge("success", `واریزی #${depositId} ثبت شد`);
  await refreshWallet();
}

async function createWithdraw() {
  const amount = parsePositiveInt(getVal("withdrawAmountInput"));
  const full_name = getVal("withdrawFullNameInput");
  const ibanRaw = toEnglishDigits(getVal("withdrawIbanInput")).replace(/\s+/g, "").toUpperCase();
  const iban = ibanRaw || null;
  const card_number = toEnglishDigits(getVal("withdrawCardInput")).replace(/\D/g, "").slice(0, 16);
  const account_number_raw = toEnglishDigits(getVal("withdrawAccountInput")).replace(/[^\d]/g, "").slice(0, 20);
  const account_number = account_number_raw || null;

  if (!amount || amount <= 0) throw new Error("مبلغ برداشت نامعتبر است.");
  if (!full_name) throw new Error("نام و نام خانوادگی الزامی است.");
  if (!card_number) throw new Error("شماره کارت الزامی است.");

  setHint("withdrawSubmitHint", "در حال ثبت...");
  setBadge("pending", "در حال ثبت برداشت...");

  const res = await apiFetch("/mini-api/withdraws", {
    method: "POST",
    body: {
      amount,
      full_name,
      iban,
      card_number,
      account_number,
      idempotency_key: idem("withdraw"),
    },
  });

  setVal("withdrawAmountInput", "");
  setVal("withdrawFullNameInput", "");
  setVal("withdrawIbanInput", "");
  setVal("withdrawCardInput", "");
  setVal("withdrawAccountInput", "");
  renderWithdrawPreview();

  setHint("withdrawSubmitHint", `درخواست برداشت #${res.id} ثبت شد.`, "success");
  setBadge("success", `درخواست برداشت #${res.id} ثبت شد`);
  await refreshWallet();
}

function selectedAdminGameId() {
  return Number(state.admin?.selectedGameId || 0);
}

function getAdminGameById(gameId) {
  const gid = Number(gameId || 0);
  if (!gid) return null;
  const mp = state.admin?.gamesById;
  if (!mp || typeof mp.get !== "function") return null;
  return mp.get(gid) || null;
}


function adminLiveLinkForGame(gameId) {
  const gid = Number(gameId || state.admin?.selectedGameId || 0);
  if (!gid) return "";
  const g = getAdminGameById(gid);
  return String(
    g?.live_link_url ||
      g?.live_url ||
      g?.live_link ||
      state.admin?.liveLinksByGame?.get(gid) ||
      ""
  ).trim();
}

function updateAdminCreateGroupVisibility() {
  const isSuper = Boolean(state.admin?.isSuper);
  const input = getEl("adminCreateGroupIdInput");
  const hint = getEl("adminCreateGroupHint");
  const label = getEl("adminCreateGroupLabel");

  const targets = new Set();
  [input, hint, label].forEach((el) => {
    if (!el) return;
    targets.add(el.closest(".form-field") || el.closest(".field") || el.parentElement || el);
  });

  targets.forEach((el) => {
    if (!el) return;
    el.classList.toggle("hidden", !isSuper);
    el.classList.toggle("admin-super-only-field", true);
  });

  if (input) {
    input.readOnly = !isSuper;
    input.disabled = !isSuper;
  }
}

function resetAdminCreateState() {
  state.admin.create = {
    groupId: null,
    topics: [],
    enforceTopic: false,
    selectedTopicId: null,
  };
}

function setAdminCreateTopic(topicId, { silent = false } = {}) {
  const create = state.admin?.create || {};
  const normalized = Number(topicId || 0);
  create.selectedTopicId = normalized > 0 ? Math.trunc(normalized) : null;
  state.admin.create = create;
  setVal("adminCreateTopicIdInput", create.selectedTopicId == null ? "" : String(create.selectedTopicId));

  const root = getEl("adminCreateTopics");
  if (root) {
    root.querySelectorAll(".topic-chip").forEach((btn) => {
      const tid = Number(btn.getAttribute("data-topic-id") || "0");
      btn.classList.toggle("active", create.selectedTopicId != null && tid === create.selectedTopicId);
    });
  }

  if (!silent && create.selectedTopicId != null) {
    const selected = Array.isArray(create.topics)
      ? create.topics.find((it) => Number(it?.topic_id || 0) === Number(create.selectedTopicId))
      : null;
    if (selected) {
      setHint("adminCreateHintMsg", `تاپیک ${adminCreateTopicTitle(selected)} انتخاب شد.`, "success");
    }
  }
}

function renderAdminCreateTopics() {
  const root = getEl("adminCreateTopics");
  if (!root) return;

  const topics = Array.isArray(state.admin?.create?.topics) ? state.admin.create.topics : [];
  if (!topics.length) {
    root.innerHTML = '<div class="empty">تاپیک‌های بازی در تنظیمات ربات تعریف نشده‌اند.</div>';
    setAdminCreateTopic(null, { silent: true });
    return;
  }

  root.innerHTML = topics
    .map((it) => {
      const tid = Number(it?.topic_id || 0);
      const title = safeText(adminCreateTopicTitle(it));
      return `<button class="price-chip topic-chip" type="button" data-topic-id="${tid}">${title}</button>`;
    })
    .join("");

  root.querySelectorAll(".topic-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tid = Number(btn.getAttribute("data-topic-id") || "0");
      if (!tid) return;
      setAdminCreateTopic(tid);
    });
  });

  const hasCurrent = topics.some((it) => Number(it?.topic_id || 0) === Number(state.admin.create.selectedTopicId || 0));
  if (state.admin.create.selectedTopicId == null || !hasCurrent) {
    setAdminCreateTopic(Number(topics[0]?.topic_id || 0), { silent: true });
  } else {
    setAdminCreateTopic(state.admin.create.selectedTopicId, { silent: true });
  }
}

async function refreshAdminCreateOptions() {
  if (!state.admin.enabled) return;

  const out = await apiFetch("/mini-api/admin/games/create-options");
  const groupId = parseIntegerStrict(out?.group_id);
  const topics = Array.isArray(out?.topics) ? out.topics : [];
  const enforceTopic = Boolean(out?.enforce_topic);

  state.admin.create.groupId = groupId;
  state.admin.create.topics = topics;
  state.admin.create.enforceTopic = enforceTopic;

  const groupInput = getEl("adminCreateGroupIdInput");
  if (groupId != null) {
    setVal("adminCreateGroupIdInput", String(groupId));
    if (groupInput) groupInput.setAttribute("readonly", "readonly");
  } else {
    if (!getVal("adminCreateGroupIdInput")) {
      setVal("adminCreateGroupIdInput", "");
    }
    if (groupInput) groupInput.removeAttribute("readonly");
  }

  const groupHint = getEl("adminCreateGroupHint");
  if (groupHint) {
    groupHint.textContent =
      groupId != null
        ? `گروه مقصد از تنظیمات ربات دریافت شد: ${groupId}`
        : "گروه مقصد در تنظیمات بک‌اند ثبت نشده است.";
  }

  renderAdminCreateTopics();
  updateAdminCreateGroupVisibility();
}

function syncAdminCreateFormFromGame(gameId) {
  const g = getAdminGameById(gameId);
  if (!g) return;
  setVal("adminCreateGroupIdInput", String(g.tg_group_id || ""));
  setAdminCreateTopic(g.tg_topic_id == null ? null : Number(g.tg_topic_id), { silent: true });
  setVal("adminCreateCardPriceInput", String(g.card_price || ""));
}

function setAdminSelectedGame(gameId, statusText = "") {
  state.admin.selectedGameId = Number(gameId || 0);
  const meta = getEl("adminSelectedGameMeta");
  if (!meta) return;
  if (!state.admin.selectedGameId) {
    meta.textContent = "هیچ بازی انتخاب نشده";
    updateAdminActionButtons();
    return;
  }
  meta.textContent = statusText
    ? `بازی #${state.admin.selectedGameId} | ${statusText}`
    : `بازی #${state.admin.selectedGameId}`;
  syncAdminCreateFormFromGame(state.admin.selectedGameId);
  updateAdminActionButtons();
}

function updateAdminActionButtons() {
  const gid = Number(state.admin?.selectedGameId || 0);
  const g = gid ? getAdminGameById(gid) : null;
  const status = String(g?.status || "").toUpperCase();

  const setBtn = (id, enabled, title) => {
    const btn = getEl(id);
    if (!btn) return;
    btn.disabled = !enabled;
    btn.classList.toggle("is-disabled", !enabled);
    if (title) btn.setAttribute("title", title);
    else btn.removeAttribute("title");
  };

  const hasGame = gid > 0;
  const isLobby = status === "LOBBY";
  const isRunning = status === "RUNNING";

  const hasLiveLink = Boolean(adminLiveLinkForGame(gid));

  setBtn("adminStartBtn", hasGame && isLobby, hasGame ? "شروع فقط برای بازی در لابی فعال است." : "ابتدا بازی را انتخاب کنید.");
  setBtn("adminCloseLobbyBtn", hasGame && isLobby, hasGame ? "لغو فقط پیش از شروع بازی مجاز است." : "ابتدا بازی را انتخاب کنید.");
  setBtn("adminCallBtn", hasGame && isRunning, hasGame ? "اعلام عدد فقط برای بازی در حال اجرا مجاز است." : "ابتدا بازی را انتخاب کنید.");
  setBtn("adminUndoBtn", hasGame && isRunning, hasGame ? "حذف آخرین عدد فقط برای بازی در حال اجرا مجاز است." : "ابتدا بازی را انتخاب کنید.");
  setBtn("adminSendLiveBtn", hasGame && hasLiveLink, hasLiveLink ? "ارسال لینک لایو به خریداران کارت همین بازی." : "ابتدا لینک لایو را ثبت کنید.");
  setBtn("adminClearLiveBtn", hasGame && hasLiveLink, hasLiveLink ? "حذف لینک لایو ثبت‌شده برای این بازی." : "لینک لایو ثبت نشده است.");
}

function requireAdminGameStatus(allowedStatuses, actionLabel) {
  const gid = requireAdminSelectedGame();
  const g = getAdminGameById(gid);
  const status = String(g?.status || "").toUpperCase();
  const allowed = new Set((allowedStatuses || []).map((x) => String(x).toUpperCase()));
  if (allowed.size && !allowed.has(status)) {
    const current = status ? statusLabel(status) : "نامشخص";
    throw new Error(`${actionLabel} برای وضعیت فعلی بازی مجاز نیست. وضعیت فعلی: ${current}`);
  }
  return { gid, game: g, status };
}


async function refreshAdminBootstrap() {
  try {
    const me = await apiFetch("/mini-api/admin/me");
    state.admin.enabled = Boolean(me?.is_admin);
    state.admin.isSuper = Boolean(me?.is_super_admin);
    state.admin.roles = Array.isArray(me?.roles) ? me.roles : [];
    setAdminNavVisible(state.admin.enabled);
    const roleEl = getEl("adminRoleText");
    if (roleEl) roleEl.textContent = adminRoleBadgeText();
    const superSection = getEl("superAdminSection");
    if (superSection) superSection.classList.toggle("hidden", !state.admin.isSuper);
    updateAdminCreateGroupVisibility();
    if (state.admin.enabled) {
      await Promise.allSettled([refreshAdminCreateOptions(), refreshAdminPanel()]);
    }
  } catch (err) {
    state.admin.enabled = false;
    state.admin.isSuper = false;
    state.admin.roles = [];
    state.admin.selectedGameId = 0;
    state.admin.gamesById = new Map();
    state.admin.users.selectedTgUserId = 0;
    state.admin.users.lastQuery = "";
    state.admin.users.reportMode = "none";
    state.admin.users.profile = null;
    resetAdminCreateState();
    renderAdminCreateTopics();
    setHint("adminCreateHintMsg", "");
    const roleEl = getEl("adminRoleText");
    if (roleEl) roleEl.textContent = "دسترسی ادمین فعال نیست.";
    setAdminNavVisible(false);
    console.warn("[mini] admin bootstrap failed", err);
  }
}

function renderAdminGames(payload) {
  const root = getEl("adminGamesList");
  if (!root) return;
  const items = Array.isArray(payload?.items) ? payload.items : [];
  state.admin.gamesById = new Map(items.map((g) => [Number(g?.id || 0), g]).filter(([gid]) => gid > 0));
  if (!items.length) {
    root.innerHTML = '<div class="empty">بازی قابل مدیریت پیدا نشد.</div>';
    setAdminSelectedGame(0);
    return;
  }

  root.innerHTML = items
    .map((g) => {
      const gid = Number(g?.id || 0);
      const status = safeText(statusLabel(g?.status));
      const canManage = Boolean(g?.can_manage);
      return `
        <div class="history-item">
          <strong>بازی #${gid} | ${status}</strong>
          <div class="history-meta">
            قیمت کارت: ${safeText(toman(g?.card_price || 0))}<br />
            جایزه: ${safeText(toman(g?.prize_pool || 0))}<br />
            گروه: ${safeText(String(g?.tg_group_id || "-"))}<br />
            تاپیک: ${safeText(g?.tg_topic_id == null ? "-" : String(g?.tg_topic_id))}<br />
            وضعیت لایو: ${g?.live_link_url ? "ثبت شده" : "ثبت نشده"}
          </div>
          <div class="admin-item-actions">
            <button class="small-btn admin-select-game-btn" data-game-id="${gid}" data-status="${status}" type="button">انتخاب</button>
            <button class="small-btn admin-open-game-btn" data-game-id="${gid}" type="button">نمایش زنده</button>
            ${canManage ? "" : '<span class="meta">بدون دسترسی مدیریت این بازی</span>'}
          </div>
        </div>
      `;
    })
    .join("");

  root.querySelectorAll(".admin-select-game-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const gid = Number(btn.getAttribute("data-game-id") || "0");
      const status = String(btn.getAttribute("data-status") || "");
      if (!gid) return;
      setAdminSelectedGame(gid, status);
      setHint("adminActionHint", `بازی #${gid} انتخاب شد.`, "success");
    });
  });

  root.querySelectorAll(".admin-open-game-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const gid = Number(btn.getAttribute("data-game-id") || "0");
      if (!gid) return;
      setAdminSelectedGame(gid);
      switchToView("games");
      openLiveGame(gid).catch((e) => setBadge("error", e.message));
    });
  });

  if (!selectedAdminGameId()) {
    const first = Number(items[0]?.id || 0);
    if (first) setAdminSelectedGame(first, statusLabel(items[0]?.status));
  }
}

async function refreshAdminGames() {
  if (!state.admin.enabled) return;
  const groupId = parseIntegerStrict(state.admin?.create?.groupId);
  const qs = groupId != null ? `&tg_group_id=${encodeURIComponent(String(groupId))}` : "";
  const out = await apiFetch(`/mini-api/admin/games?status=LOBBY,RUNNING&limit=40${qs}`);
  renderAdminGames(out);
  updateAdminActionButtons();
}

function renderAdminDeposits(payload) {
  const root = getEl("adminDepositsList");
  if (!root) return;
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) {
    root.innerHTML = '<div class="empty">واریز در انتظار بررسی وجود ندارد.</div>';
    return;
  }

  root.innerHTML = items
    .map((d) => `
      <div class="history-item" data-admin-deposit-id="${safeText(d.id)}">
        <strong>واریزی #${safeText(d.id)} | ${safeText(depositStatusLabel(d.status))}</strong>
        <div class="history-meta">
          کاربر: ${safeText(d.tg_username || d.tg_user_id || d.user_id)}<br />
          مبلغ: ${safeText(toman(d.amount || 0))}<br />
          مقصد: ${safeText(d.destination_title || "-")}<br />
          زمان: ${safeText(formatFaDateTime(d.created_at))}
        </div>
        <div class="admin-item-actions">
          <button class="small-btn primary admin-dep-approve-btn" data-id="${safeText(d.id)}" type="button">تایید</button>
          <button class="small-btn danger admin-dep-reject-btn" data-id="${safeText(d.id)}" type="button">رد</button>
          ${d.receipt_uploaded ? `<a class="small-btn" href="${safeText(d.receipt_url || "#")}" target="_blank" rel="noopener noreferrer">رسید</a>` : ""}
        </div>
      </div>
    `)
    .join("");

  root.querySelectorAll(".admin-dep-approve-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-id") || "0");
      if (!id) return;
      adminApproveDeposit(id).catch((e) => setBadge("error", e.message));
    });
  });
  root.querySelectorAll(".admin-dep-reject-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-id") || "0");
      if (!id) return;
      adminRejectDeposit(id).catch((e) => setBadge("error", e.message));
    });
  });
}

async function refreshAdminDeposits() {
  if (!state.admin.enabled) return;
  const out = await apiFetch("/mini-api/admin/deposits?status=PENDING_REVIEW&limit=40");
  renderAdminDeposits(out);
}


function renderWithdrawWalletStatusLine(info, withdrawAmount = 0) {
  if (!info) return "وضعیت کیف پول هنوز بروزرسانی نشده است.";
  const balance = Number(info.wallet_balance || 0);
  const pendingOther = Number(info.pending_other || 0);
  const available = Number(info.available_for_this || 0);
  const req = Number(info.request_amount || withdrawAmount || 0);
  const ok = Boolean(info.can_approve);
  return `کیف پول: ${toman(balance)} | برداشت‌های دیگر در انتظار: ${toman(pendingOther)} | قابل تایید برای این برداشت: ${toman(available)} | مبلغ درخواست: ${toman(req)} | ${ok ? "مجاز برای تایید" : "نیازمند رد/بررسی"}`;
}


function renderWithdrawWalletStatusHtml(info) {
  if (!info) {
    return '<div class="withdraw-wallet-grid muted">برای دیدن موجودی، دکمه بروزرسانی کیف پول را بزنید.</div>';
  }
  const balance = Number(info.wallet_balance || 0);
  const pendingOther = Number(info.pending_other || 0);
  const available = Number(info.available_for_this || 0);
  const req = Number(info.request_amount || 0);
  const ok = Boolean(info.can_approve);
  return `
    <div class="withdraw-wallet-grid ${ok ? "ok" : "bad"}">
      <div><span>موجودی کیف پول</span><b>${safeText(toman(balance))}</b></div>
      <div><span>مبلغ این برداشت</span><b>${safeText(toman(req))}</b></div>
      <div><span>برداشت‌های دیگر در انتظار</span><b>${safeText(toman(pendingOther))}</b></div>
      <div><span>قابل تایید برای این برداشت</span><b>${safeText(toman(available))}</b></div>
      <div class="wide"><span>نتیجه</span><b>${ok ? "موجودی کافی است؛ تایید مجاز است" : "موجودی کافی نیست؛ رد یا بررسی کن"}</b></div>
    </div>
  `;
}

function setWithdrawWalletStatus(withdrawId, info) {
  const id = Number(withdrawId || 0);
  if (!id) return;
  state.adminWithdrawWalletStatus?.set(id, info);
  const el = getEl(`adminWdrWalletStatus${id}`);
  if (el) {
    el.innerHTML = renderWithdrawWalletStatusHtml(info);
    el.classList.toggle("ok", Boolean(info?.can_approve));
    el.classList.toggle("bad", !info?.can_approve);
  }
  const approveBtn = document.querySelector(`.admin-wdr-approve-btn[data-id="${id}"]`);
  if (approveBtn && info) {
    approveBtn.classList.toggle("needs-refresh", false);
    approveBtn.disabled = !Boolean(info.can_approve);
    approveBtn.title = info.can_approve
      ? "آخرین وضعیت کیف پول تایید شد؛ می‌توانید برداشت را تایید کنید."
      : "موجودی قابل تایید کافی نیست؛ قبل از اقدام بررسی کنید.";
  }
}


function renderAdminWithdraws(payload) {
  const root = getEl("adminWithdrawsList");
  if (!root) return;
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) {
    root.innerHTML = '<div class="empty">برداشتی برای مدیریت وجود ندارد.</div>';
    return;
  }

  root.innerHTML = items
    .map((w) => {
      const id = Number(w.id || 0);
      const status = String(w.status || "").toUpperCase();
      const walletInfo = state.adminWithdrawWalletStatus?.get(id) || null;
      const canApproveFromWallet = Boolean(walletInfo?.can_approve);
      const userLabel = w.tg_username
        ? `@${safeText(String(w.tg_username).replace(/^@+/, ""))}`
        : safeText(w.tg_user_id || w.user_id || "-");
      const fullName = String(w.full_name || w.name || w.account_name || "").trim();

      const actions = [];
      if (status === "PENDING") {
        actions.push(`<button class="small-btn admin-wdr-wallet-refresh-btn" data-id="${safeText(id)}" type="button">بروزرسانی کیف پول</button>`);
        actions.push(`<button class="small-btn primary admin-wdr-approve-btn ${canApproveFromWallet ? "" : "needs-refresh"}" data-id="${safeText(id)}" type="button" ${canApproveFromWallet ? "" : "disabled"} title="${canApproveFromWallet ? "آخرین وضعیت کیف پول تایید شد؛ می‌توانید برداشت را تایید کنید." : "ابتدا بروزرسانی کیف پول را بزنید."}">تایید</button>`);
        actions.push(`<button class="small-btn danger admin-wdr-reject-btn" data-id="${safeText(id)}" type="button">رد</button>`);
      }
      if (status === "APPROVED") {
        actions.push(`<button class="small-btn primary admin-wdr-paid-btn" data-id="${safeText(id)}" type="button">ثبت فیش پرداخت</button>`);
      }

      return `
        <div class="history-item admin-withdraw-item" data-admin-withdraw-id="${safeText(id)}">
          <strong>برداشت #${safeText(id)} | ${safeText(withdrawStatusLabel(w.status))}</strong>
          <div class="history-meta">
            کاربر: ${userLabel}<br />
            نام: ${safeText(fullName || "-")}<br />
            شناسه داخلی: ${safeText(w.user_id || "-")}<br />
            مبلغ: ${safeText(toman(w.amount || 0))}<br />
            کارت: ${safeText(w.card_number || "-")}<br />
            شبا: ${safeText(w.iban || "-")}<br />
            حساب: ${safeText(w.account_number || "-")}<br />
            پیگیری پرداخت: ${safeText(w.paid_tracking || "-")}<br />
            زمان: ${safeText(formatFaDateTime(w.created_at))}
          </div>
          <div id="adminWdrWalletStatus${safeText(id)}" class="withdraw-wallet-status">
            ${renderWithdrawWalletStatusHtml(walletInfo)}
          </div>
          <div class="admin-item-actions">${actions.join("")}</div>
        </div>
      `;
    })
    .join("");

  root.querySelectorAll(".admin-wdr-wallet-refresh-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-id") || "0");
      if (!id) return;
      adminRefreshWithdrawWallet(id).catch((e) => setBadge("error", e.message));
    });
  });

  root.querySelectorAll(".admin-wdr-approve-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-id") || "0");
      if (!id) return;
      adminApproveWithdraw(id).catch((e) => setBadge("error", e.message));
    });
  });

  root.querySelectorAll(".admin-wdr-reject-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-id") || "0");
      if (!id) return;
      adminRejectWithdraw(id).catch((e) => setBadge("error", e.message));
    });
  });

  root.querySelectorAll(".admin-wdr-paid-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-id") || "0");
      if (!id) return;
      adminPaidWithdraw(id).catch((e) => setBadge("error", e.message));
    });
  });
}

async function refreshAdminWithdraws() {
  if (!state.admin.enabled) return;
  const out = await apiFetch("/mini-api/admin/withdraws?status=PENDING,APPROVED&limit=40");
  renderAdminWithdraws(out);
}

function latestAdminItem(items) {
  const arr = Array.isArray(items) ? items : [];
  let best = null;
  arr.forEach((it) => {
    const id = Number(it?.id || 0);
    if (!id) return;
    if (!best || id > Number(best.id || 0)) best = it;
  });
  return best;
}

async function checkAdminFinanceNotifications(options = {}) {
  if (!state.admin.enabled || state.admin.notify.checking) return;
  state.admin.notify.checking = true;
  const silent = Boolean(options.silent);
  try {
    const [depSettled, wdrSettled] = await Promise.allSettled([
      apiFetch("/mini-api/admin/deposits?status=PENDING_REVIEW&limit=5"),
      apiFetch("/mini-api/admin/withdraws?status=PENDING&limit=5"),
    ]);

    const depItems = depSettled.status === "fulfilled" && Array.isArray(depSettled.value?.items)
      ? depSettled.value.items
      : [];
    const wdrItems = wdrSettled.status === "fulfilled" && Array.isArray(wdrSettled.value?.items)
      ? wdrSettled.value.items
      : [];

    const latestDep = latestAdminItem(depItems);
    const latestWdr = latestAdminItem(wdrItems);
    const latestDepId = Number(latestDep?.id || 0);
    const latestWdrId = Number(latestWdr?.id || 0);

    const notices = [];
    if (latestDepId > Number(state.admin.notify.lastDepositId || 0)) {
      notices.push({
        kind: "deposit",
        id: latestDepId,
        title: `واریزی #${latestDepId} | ${toman(latestDep?.amount || 0)}`,
        meta: `کاربر: ${latestDep?.tg_username || latestDep?.tg_user_id || latestDep?.user_id || "-"} | لمس برای بررسی`,
      });
      state.admin.notify.lastDepositId = latestDepId;
    }
    if (latestWdrId > Number(state.admin.notify.lastWithdrawId || 0)) {
      notices.push({
        kind: "withdraw",
        id: latestWdrId,
        title: `برداشت #${latestWdrId} | ${toman(latestWdr?.amount || 0)}`,
        meta: `نیاز به بررسی کیف پول | لمس برای مشاهده`,
      });
      state.admin.notify.lastWithdrawId = latestWdrId;
    }

    if (latestDepId || latestWdrId) {
      saveAdminNotifySeen();
    }
    if (!silent && notices.length) {
      showAdminNotify(notices[notices.length - 1]);
    }
  } catch (_) {
    // Admin notifications are a UX layer; never break the mini-app.
  } finally {
    state.admin.notify.ready = true;
    state.admin.notify.checking = false;
  }
}

function parseAdminUsersSearchParams(raw) {
  const txt = toEnglishDigits(String(raw || "").trim());
  if (!txt) throw new Error("عبارت جستجو را وارد کنید.");
  const low = txt.toLowerCase();
  const p = new URLSearchParams();
  if (low.startsWith("gid:") || low.startsWith("game:") || low.startsWith("game_id:")) {
    p.set("game_id", String(parseIntegerStrict(txt.split(":").slice(1).join(":")) || 0));
  } else if (low.startsWith("dep:") || low.startsWith("deposit:") || low.startsWith("deposit_id:")) {
    p.set("deposit_id", String(parseIntegerStrict(txt.split(":").slice(1).join(":")) || 0));
  } else if (low.startsWith("wdr:") || low.startsWith("withdraw:") || low.startsWith("withdraw_id:")) {
    p.set("withdraw_id", String(parseIntegerStrict(txt.split(":").slice(1).join(":")) || 0));
  } else if (txt.startsWith("@")) {
    p.set("username", txt.slice(1));
  } else if (/^\d+$/.test(txt)) {
    p.set("tg_user_id", txt);
  } else {
    p.set("username", txt);
  }
  p.set("limit", "15");
  return p;
}

function adminUsersSelectedId() {
  return Number(state.admin?.users?.selectedTgUserId || 0);
}

function adminUsersEntryTypeLabel(entryType) {
  const key = String(entryType || "").trim().toLowerCase();
  if (key === "wallet_tx") return "تراکنش کیف پول";
  if (key === "deposit_request") return "درخواست واریز";
  if (key === "withdraw_request") return "درخواست برداشت";
  return key || "-";
}

function adminUsersMembershipLabel(membership) {
  const status = String(membership?.status || "").toUpperCase();
  if (status === "MEMBER") return "عضو گروه";
  if (status === "RESTRICTED") return "عضو محدودشده";
  if (status === "NOT_MEMBER") return "خارج از گروه";
  return "نامشخص";
}

function adminUsersMembershipClass(membership) {
  const status = String(membership?.status || "").toUpperCase();
  if (status === "MEMBER" || status === "RESTRICTED") return "is-ok";
  if (status === "NOT_MEMBER") return "is-danger";
  return "is-muted";
}

function adminUsersRolePills(roles) {
  const list = Array.isArray(roles) ? roles : [];
  if (!list.length) return '<span class="admin-mini-pill">USER</span>';
  return list
    .map((r) => `<span class="admin-mini-pill">${safeText(String(r || "USER"))}</span>`)
    .join("");
}

function renderAdminUsersSearchResults(payload) {
  const root = getEl("adminUsersSearchResults");
  if (!root) return;
  const items = Array.isArray(payload?.items) ? payload.items : [];
  const selected = adminUsersSelectedId();
  if (!items.length) {
    root.innerHTML = '<div class="empty">کاربری یافت نشد.</div>';
    return;
  }
  root.innerHTML = items
    .map((u) => {
      const tgid = Number(u?.tg_user_id || 0);
      const display = safeText(u?.display_name || u?.username || `کاربر ${tgid}`);
      const username = u?.username ? `@${safeText(u.username)}` : "-";
      const matchedBy = Array.isArray(u?.matched_by) ? u.matched_by : [];
      const matchedPills = matchedBy.length
        ? matchedBy.map((m) => `<span class="admin-mini-pill is-soft">${safeText(String(m || "-"))}</span>`).join("")
        : '<span class="admin-mini-pill is-soft">بدون منبع</span>';
      const rolePills = adminUsersRolePills(u?.roles);
      const selectedClass = selected > 0 && selected === tgid ? "is-selected" : "";
      return `
        <div class="history-item clickable admin-user-search-item ${selectedClass}" data-tg-id="${tgid}">
          <strong>${display}</strong>
          <div class="history-meta">
            TG ID: ${safeText(String(tgid))}<br />
            یوزرنیم: ${username}
          </div>
          <div class="admin-inline-chips">${rolePills}${matchedPills}</div>
          <div class="admin-item-actions">
            <button class="small-btn primary admin-user-open-btn" data-tg-id="${tgid}" type="button">باز کردن پروفایل</button>
          </div>
        </div>
      `;
    })
    .join("");
  root.querySelectorAll(".admin-user-search-item").forEach((item) => {
    item.addEventListener("click", () => {
      const tgid = Number(item.getAttribute("data-tg-id") || "0");
      if (!tgid) return;
      adminUsersOpenProfile(tgid).catch((e) => setBadge("error", e.message));
    });
  });
  root.querySelectorAll(".admin-user-open-btn").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const tgid = Number(btn.getAttribute("data-tg-id") || "0");
      if (!tgid) return;
      adminUsersOpenProfile(tgid).catch((e) => setBadge("error", e.message));
    });
  });
}

function renderAdminUsersProfile(payload) {
  const root = getEl("adminUsersProfileBox");
  if (!root) return;
  const user = payload?.user || {};
  const stats = payload?.stats || {};
  const wallet = payload?.wallet || {};
  const restriction = payload?.restriction || {};
  const membership = payload?.membership || {};
  const roles = Array.isArray(payload?.roles) ? payload.roles : [];
  const tgid = Number(user?.tg_user_id || 0);
  const rolePills = adminUsersRolePills(roles);
  const isRestricted = Boolean(restriction?.active);
  const reportMode = String(state.admin?.users?.reportMode || "none");
  const membershipLabel = adminUsersMembershipLabel(membership);
  const membershipClass = adminUsersMembershipClass(membership);
  const restrictionText = isRestricted ? "محدود" : "آزاد";
  const restrictionClass = isRestricted ? "is-danger" : "is-ok";
  const walletBalance = Number(wallet?.balance || 0);
  const cardsPurchased = Number(stats?.cards_purchased || 0);
  const gamesParticipated = Number(stats?.games_participated || 0);
  const totalBuyAmount = Number(stats?.total_buy_amount || 0);
  const winsTotalAmount = Number(stats?.wins_total_amount || 0);
  const winsTotalCount = Number(stats?.wins_total_count || 0);
  const pendingWithdrawCount = Number(stats?.pending_withdraw_count || 0);
  const lastActivityAt = formatFaDateTime(stats?.last_activity_at || user?.created_at);
  const lastWinAt = formatFaDateTime(stats?.last_win_at);
  root.innerHTML = `
    <div class="history-item admin-user-profile-card">
      <div class="admin-user-profile-head">
        <div>
          <strong>${safeText(user?.display_name || user?.username || `کاربر ${tgid}`)}</strong>
          <div class="history-meta">
            TG ID: ${safeText(String(tgid))} | یوزرنیم: ${safeText(user?.username ? `@${user.username}` : "-")}
          </div>
        </div>
        <div class="admin-inline-chips">${rolePills}</div>
      </div>
      <div class="history-meta">
        <span class="admin-status-pill ${membershipClass}">عضویت گروه: ${safeText(membershipLabel)}</span>
        <span class="admin-status-pill ${restrictionClass}">وضعیت محدودیت: ${safeText(restrictionText)}</span>
      </div>
      <div class="admin-user-kpi-grid">
        <div class="admin-user-kpi"><div class="k">موجودی</div><div class="v">${safeText(toman(walletBalance))}</div></div>
        <div class="admin-user-kpi"><div class="k">کارت خریده</div><div class="v">${safeText(String(cardsPurchased))}</div></div>
        <div class="admin-user-kpi"><div class="k">بازی شرکت‌کرده</div><div class="v">${safeText(String(gamesParticipated))}</div></div>
        <div class="admin-user-kpi"><div class="k">جمع خرید</div><div class="v">${safeText(toman(totalBuyAmount))}</div></div>
        <div class="admin-user-kpi"><div class="k">تعداد برد</div><div class="v">${safeText(String(winsTotalCount))}</div></div>
        <div class="admin-user-kpi"><div class="k">جمع برد</div><div class="v">${safeText(toman(winsTotalAmount))}</div></div>
        <div class="admin-user-kpi"><div class="k">برداشت در انتظار</div><div class="v">${safeText(String(pendingWithdrawCount))}</div></div>
        <div class="admin-user-kpi"><div class="k">آخرین فعالیت</div><div class="v">${safeText(lastActivityAt)}</div></div>
      </div>
      <div class="history-meta mt-12">
        آخرین برد: ${safeText(lastWinAt)}
      </div>
      <div class="admin-action-block mt-12">
        <div class="admin-action-block-title">گزارش‌های کاربر</div>
        <div class="admin-item-actions">
          <button class="small-btn admin-user-fin-btn ${reportMode === "financial" ? "is-active" : ""}" data-tg-id="${tgid}" type="button">تاریخچه مالی</button>
          <button class="small-btn admin-user-games-btn ${reportMode === "games" ? "is-active" : ""}" data-tg-id="${tgid}" type="button">تاریخچه بازی</button>
          <button class="small-btn admin-user-report-clear-btn" type="button">پاکسازی گزارش</button>
        </div>
      </div>
      <div class="admin-action-block mt-12">
        <div class="admin-action-block-title">عملیات کنترلی</div>
        <div class="admin-item-actions">
          <button class="small-btn danger admin-user-restrict-btn" data-tg-id="${tgid}" type="button">محدودسازی</button>
          <button class="small-btn admin-user-unrestrict-btn" data-tg-id="${tgid}" type="button">رفع محدودیت</button>
          <button class="small-btn admin-user-adjust-btn" data-tg-id="${tgid}" type="button">اصلاح کیف پول</button>
        </div>
      </div>
      <div class="admin-action-block mt-12">
        <div class="admin-action-block-title">ارتباط با کاربر</div>
        <div class="admin-item-actions">
          <button class="small-btn admin-user-template-btn" data-tg-id="${tgid}" type="button">پیام آماده</button>
          <button class="small-btn primary admin-user-notify-btn" data-tg-id="${tgid}" type="button">پیام دستی</button>
        </div>
      </div>
      <div id="adminUsersReportArea" class="admin-users-report mt-12">
        <div class="empty">یک گزارش را انتخاب کنید.</div>
      </div>
    </div>
  `;
  root.querySelectorAll(".admin-user-fin-btn").forEach((btn) => btn.addEventListener("click", () => adminUsersShowFinancial(Number(btn.getAttribute("data-tg-id") || "0")).catch((e) => setBadge("error", e.message))));
  root.querySelectorAll(".admin-user-games-btn").forEach((btn) => btn.addEventListener("click", () => adminUsersShowGames(Number(btn.getAttribute("data-tg-id") || "0")).catch((e) => setBadge("error", e.message))));
  root.querySelectorAll(".admin-user-report-clear-btn").forEach((btn) => btn.addEventListener("click", () => {
    state.admin.users.reportMode = "none";
    renderAdminUsersReport(null);
    adminUsersRefreshReportModeUi();
  }));
  root.querySelectorAll(".admin-user-restrict-btn").forEach((btn) => btn.addEventListener("click", () => adminUsersRestrict(Number(btn.getAttribute("data-tg-id") || "0")).catch((e) => setBadge("error", e.message))));
  root.querySelectorAll(".admin-user-unrestrict-btn").forEach((btn) => btn.addEventListener("click", () => adminUsersUnrestrict(Number(btn.getAttribute("data-tg-id") || "0")).catch((e) => setBadge("error", e.message))));
  root.querySelectorAll(".admin-user-adjust-btn").forEach((btn) => btn.addEventListener("click", () => adminUsersAdjustWallet(Number(btn.getAttribute("data-tg-id") || "0")).catch((e) => setBadge("error", e.message))));
  root.querySelectorAll(".admin-user-template-btn").forEach((btn) => btn.addEventListener("click", () => adminUsersSendTemplate(Number(btn.getAttribute("data-tg-id") || "0")).catch((e) => setBadge("error", e.message))));
  root.querySelectorAll(".admin-user-notify-btn").forEach((btn) => btn.addEventListener("click", () => adminUsersNotifyManual(Number(btn.getAttribute("data-tg-id") || "0")).catch((e) => setBadge("error", e.message))));
}

function renderAdminUsersReport(payload = null) {
  const area = getEl("adminUsersReportArea");
  if (!area) return;
  if (!payload) {
    area.innerHTML = '<div class="empty">یک گزارش را انتخاب کنید.</div>';
    return;
  }
  const title = safeText(String(payload?.title || "گزارش"));
  const meta = safeText(String(payload?.meta || ""));
  const bodyHtml = String(payload?.bodyHtml || "");
  area.innerHTML = `
    <div class="admin-report-wrap">
      <div class="admin-report-head">
        <strong>${title}</strong>
        ${meta ? `<span class="meta">${meta}</span>` : ""}
      </div>
      <div class="admin-report-list">${bodyHtml || '<div class="empty">رکوردی وجود ندارد.</div>'}</div>
    </div>
  `;
}

function adminUsersRefreshReportModeUi() {
  const mode = String(state.admin?.users?.reportMode || "none");
  const root = getEl("adminUsersProfileBox");
  if (!root) return;
  root.querySelectorAll(".admin-user-fin-btn").forEach((btn) => {
    btn.classList.toggle("is-active", mode === "financial");
  });
  root.querySelectorAll(".admin-user-games-btn").forEach((btn) => {
    btn.classList.toggle("is-active", mode === "games");
  });
}

async function adminUsersOpenProfile(tgUserId, options = {}) {
  const silent = Boolean(options?.silent);
  const tgid = Number(tgUserId || 0);
  if (!tgid) throw new Error("شناسه کاربر نامعتبر است.");
  const previous = adminUsersSelectedId();
  if (previous !== tgid) {
    state.admin.users.reportMode = "none";
  }
  const profileRoot = getEl("adminUsersProfileBox");
  if (profileRoot && !silent) {
    profileRoot.innerHTML = `
      <div class="cards-skeleton">
        <div class="skeleton-line lg"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line"></div>
      </div>
    `;
  }
  if (!silent) {
    setHint("adminUsersHint", `در حال بارگذاری پروفایل کاربر ${tgid}...`);
  }
  const out = await apiFetch(`/mini-api/admin/users/${tgid}/profile`);
  state.admin.users.selectedTgUserId = tgid;
  state.admin.users.profile = out;
  renderAdminUsersProfile(out);
  adminUsersRefreshReportModeUi();
  const listRoot = getEl("adminUsersSearchResults");
  if (listRoot) {
    listRoot.querySelectorAll(".admin-user-search-item").forEach((el) => {
      const rowId = Number(el.getAttribute("data-tg-id") || "0");
      el.classList.toggle("is-selected", rowId === tgid);
    });
  }
  if (state.admin.users.reportMode === "financial") {
    await adminUsersShowFinancial(tgid, { silent });
  } else if (state.admin.users.reportMode === "games") {
    await adminUsersShowGames(tgid, { silent });
  }
  if (!silent) {
    setHint("adminUsersHint", `پروفایل کاربر ${tgid} بارگذاری شد.`, "success");
  }
}

async function adminUsersSearch() {
  const query = getVal("adminUsersSearchInput");
  setHint("adminUsersHint", "در حال جستجو...");
  const root = getEl("adminUsersSearchResults");
  if (root) {
    root.innerHTML = `
      <div class="cards-skeleton">
        <div class="skeleton-line"></div>
        <div class="skeleton-line"></div>
      </div>
    `;
  }
  const params = parseAdminUsersSearchParams(query);
  const out = await apiFetch(`/mini-api/admin/users/search?${params.toString()}`);
  state.admin.users.lastQuery = String(query || "").trim();
  renderAdminUsersSearchResults(out);
  const count = Number(out?.total || (Array.isArray(out?.items) ? out.items.length : 0));
  setHint("adminUsersHint", `نتیجه جستجو: ${count} مورد`, "success");
}

async function adminUsersRefreshSelected() {
  const tgid = adminUsersSelectedId();
  if (!tgid) throw new Error("ابتدا یک کاربر را از نتایج انتخاب کنید.");
  await adminUsersOpenProfile(tgid);
}

async function adminUsersShowFinancial(tgUserId, options = {}) {
  const silent = Boolean(options?.silent);
  const tgid = Number(tgUserId || 0);
  state.admin.users.reportMode = "financial";
  adminUsersRefreshReportModeUi();
  if (!silent) {
    renderAdminUsersReport({
      title: "تاریخچه مالی",
      meta: "در حال بارگذاری...",
      bodyHtml: `
        <div class="cards-skeleton">
          <div class="skeleton-line"></div>
          <div class="skeleton-line"></div>
          <div class="skeleton-line"></div>
        </div>
      `,
    });
  }
  const out = await apiFetch(`/mini-api/admin/users/${tgid}/financial-history?limit=20`);
  const timeline = Array.isArray(out?.timeline) ? out.timeline : [];
  if (!timeline.length) {
    renderAdminUsersReport({
      title: "تاریخچه مالی",
      meta: "۰ رکورد",
      bodyHtml: '<div class="empty">تاریخچه مالی ثبت نشده است.</div>',
    });
    return;
  }
  const html = timeline.slice(0, 12).map((it) => {
    const created = safeText(formatFaDateTime(it?.created_at));
    const typ = safeText(adminUsersEntryTypeLabel(it?.entry_type));
    const p = it?.payload || {};
    const amount = Number(p?.amount || 0);
    const amountText = Number.isFinite(amount) && amount !== 0 ? safeText(toman(Math.abs(amount))) : "-";
    const sign = amount > 0 ? "+" : amount < 0 ? "-" : "";
    const statusText =
      String(it?.entry_type || "").toLowerCase() === "deposit_request"
        ? depositStatusLabel(p?.status)
        : String(it?.entry_type || "").toLowerCase() === "withdraw_request"
          ? withdrawStatusLabel(p?.status)
          : safeText(String(p?.reason_label || p?.reason || "-"));
    return `
      <div class="history-item">
        <strong>${typ}</strong>
        <div class="history-meta">
          زمان: ${created}<br/>
          وضعیت/علت: ${safeText(statusText)}<br/>
          مبلغ: ${safeText(sign)}${amountText}
        </div>
      </div>
    `;
  }).join("");
  renderAdminUsersReport({
    title: "تاریخچه مالی",
    meta: `${timeline.length} رکورد اخیر`,
    bodyHtml: html,
  });
}

async function adminUsersShowGames(tgUserId, options = {}) {
  const silent = Boolean(options?.silent);
  const tgid = Number(tgUserId || 0);
  state.admin.users.reportMode = "games";
  adminUsersRefreshReportModeUi();
  if (!silent) {
    renderAdminUsersReport({
      title: "تاریخچه بازی",
      meta: "در حال بارگذاری...",
      bodyHtml: `
        <div class="cards-skeleton">
          <div class="skeleton-line"></div>
          <div class="skeleton-line"></div>
        </div>
      `,
    });
  }
  const out = await apiFetch(`/mini-api/admin/users/${tgid}/games-history?limit=20`);
  const items = Array.isArray(out?.items) ? out.items : [];
  const summary = out?.summary || {};
  if (!items.length) {
    renderAdminUsersReport({
      title: "تاریخچه بازی",
      meta: "۰ رکورد",
      bodyHtml: '<div class="empty">تاریخچه بازی ثبت نشده است.</div>',
    });
    return;
  }
  const html = items.slice(0, 12).map((g) => {
    const win = Number(g?.win?.wins_total_amount || 0);
    const winCol = Number(g?.win?.wins_col_amount || 0);
    const winRow = Number(g?.win?.wins_row_amount || 0);
    const winColCount = Number(g?.win?.wins_col_count || 0);
    const winRowCount = Number(g?.win?.wins_row_count || 0);
    return `
      <div class="history-item">
        <strong>بازی #${safeText(String(g?.game_id || 0))}</strong>
        <div class="history-meta">
          وضعیت: ${safeText(statusLabel(g?.game_status || ""))}<br/>
          کارت: ${safeText(String(g?.cards_qty || 0))} | هزینه: ${safeText(toman(g?.total_spent || 0))}<br/>
          برد ستونی(تورنا): ${safeText(String(winColCount))} | ${safeText(toman(winCol))}<br/>
          برد سطری(تمام): ${safeText(String(winRowCount))} | ${safeText(toman(winRow))}<br/>
          مجموع برد: ${safeText(toman(win))}<br/>
          آخرین خرید: ${safeText(formatFaDateTime(g?.last_buy_at))}
        </div>
      </div>
    `;
  }).join("");
  renderAdminUsersReport({
    title: "تاریخچه بازی",
    meta: `بازی‌ها: ${safeText(String(summary?.games_participated || items.length))} | مجموع برد: ${safeText(toman(summary?.total_win_amount || 0))}`,
    bodyHtml: html,
  });
}

async function adminUsersRestrict(tgUserId) {
  const tgid = Number(tgUserId || 0);
  const reason = String(prompt("علت محدودسازی را وارد کنید:", "نقض قوانین") || "").trim();
  if (reason.length < 3) throw new Error("علت محدودسازی نامعتبر است.");
  const minutesRaw = String(prompt("مدت محدودسازی به دقیقه (اختیاری):", "") || "").trim();
  const actionsRaw = String(prompt("اکشن‌های محدود (BUY,DEPOSIT,WITHDRAW,ACTIVE_GAMES):", "BUY,DEPOSIT,WITHDRAW,ACTIVE_GAMES") || "").trim();
  const body = { reason };
  const minutes = parseIntegerStrict(minutesRaw);
  if (minutes != null && minutes > 0) body.minutes = Number(minutes);
  if (actionsRaw) {
    body.actions = actionsRaw.split(",").map((x) => String(x || "").trim().toUpperCase()).filter(Boolean);
  }
  await apiFetch(`/mini-api/admin/users/${tgid}/restrict`, { method: "POST", body });
  setBadge("success", `کاربر ${tgid} محدود شد`);
  await adminUsersOpenProfile(tgid);
}

async function adminUsersUnrestrict(tgUserId) {
  const tgid = Number(tgUserId || 0);
  const reason = String(prompt("علت رفع محدودیت (اختیاری):", "رفع محدودیت توسط ادمین") || "").trim();
  await apiFetch(`/mini-api/admin/users/${tgid}/unrestrict`, { method: "POST", body: { reason: reason || null } });
  setBadge("success", `محدودیت کاربر ${tgid} رفع شد`);
  await adminUsersOpenProfile(tgid);
}

async function adminUsersAdjustWallet(tgUserId) {
  const tgid = Number(tgUserId || 0);
  const amountRaw = String(prompt("مبلغ اصلاح (+50000 یا -20000):", "") || "").trim();
  const amount = Number(toEnglishDigits(amountRaw).replace(/,/g, ""));
  if (!Number.isFinite(amount) || amount === 0) throw new Error("مبلغ اصلاح نامعتبر است.");
  const reason = String(prompt("علت اصلاح کیف پول:", "اصلاح کیف پول توسط ادمین") || "").trim();
  if (reason.length < 3) throw new Error("علت اصلاح کیف پول نامعتبر است.");
  await apiFetch(`/mini-api/admin/users/${tgid}/wallet-adjust`, {
    method: "POST",
    body: { amount: Math.trunc(amount), reason, notify_user: true },
  });
  setBadge("success", `کیف پول کاربر ${tgid} اصلاح شد`);
  await adminUsersOpenProfile(tgid);
}

async function adminUsersNotifyManual(tgUserId) {
  const tgid = Number(tgUserId || 0);
  const text = String(prompt("متن پیام خصوصی به کاربر:", "") || "").trim();
  if (text.length < 2) throw new Error("متن پیام نامعتبر است.");
  await apiFetch(`/mini-api/admin/users/${tgid}/notify`, {
    method: "POST",
    body: { text, parse_mode: "HTML", disable_notification: false },
  });
  setBadge("success", `پیام خصوصی برای ${tgid} ارسال شد`);
}

async function adminUsersSendTemplate(tgUserId) {
  const tgid = Number(tgUserId || 0);
  const pick = String(
    prompt(
      "نوع پیام آماده را وارد کنید:\n1) deposit_reject\n2) withdraw_reject\n3) wallet_adjust\n4) restriction\n5) generic",
      "generic"
    ) || ""
  ).trim().toLowerCase();
  const map = { "1": "deposit_reject", "2": "withdraw_reject", "3": "wallet_adjust", "4": "restriction", "5": "generic" };
  const kind = map[pick] || pick || "generic";
  const reason = String(prompt("توضیح پیام (اختیاری):", "") || "").trim();
  let amount = null;
  if (kind === "wallet_adjust") {
    const amountRaw = String(prompt("مبلغ برای پیام آماده (اختیاری):", "") || "").trim();
    const n = Number(toEnglishDigits(amountRaw).replace(/,/g, ""));
    if (Number.isFinite(n) && n !== 0) amount = Math.trunc(n);
  }
  const composed = await apiFetch(`/mini-api/admin/users/${tgid}/compose-message`, {
    method: "POST",
    body: { kind, reason: reason || null, amount },
  });
  const text = String(composed?.text || "").trim();
  if (!text) throw new Error("پیام آماده تولید نشد.");
  await apiFetch(`/mini-api/admin/users/${tgid}/notify`, {
    method: "POST",
    body: { text, parse_mode: "HTML", disable_notification: false },
  });
  setBadge("success", `پیام آماده برای ${tgid} ارسال شد`);
}

async function refreshAdminUsersPanel(options = {}) {
  const silent = Boolean(options?.silent);
  if (!state.admin.enabled) return;
  const selected = adminUsersSelectedId();
  if (selected > 0) {
    if (!silent) {
      await adminUsersOpenProfile(selected, { silent: false });
    }
    return;
  }
  const lastQ = String(state.admin?.users?.lastQuery || "").trim();
  if (lastQ) {
    try {
      const params = parseAdminUsersSearchParams(lastQ);
      const out = await apiFetch(`/mini-api/admin/users/search?${params.toString()}`);
      renderAdminUsersSearchResults(out);
    } catch (_) {}
  }
}

function renderSuperAdminList(payload) {
  const root = getEl("superAdminList");
  if (!root) return;
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) {
    root.innerHTML = '<div class="empty">ادمینی تعریف نشده است.</div>';
    return;
  }
  root.innerHTML = items
    .map((a) => `
      <div class="history-item">
        <strong>${safeText(a.first_name || a.username || a.tg_user_id || a.user_id)}</strong>
        <div class="history-meta">
          tg_user_id: ${safeText(a.tg_user_id)}<br />
          نقش‌ها: ${safeText((a.roles || []).join(" | "))}
        </div>
      </div>
    `)
    .join("");
}

async function refreshSuperAdminList() {
  if (!state.admin.enabled || !state.admin.isSuper) return;
  const out = await apiFetch("/mini-api/admin/super/admins");
  renderSuperAdminList(out);
}

async function refreshAdminPanel(options = {}) {
  const silent = Boolean(options?.silent);
  if (!state.admin.enabled) return;
  await Promise.allSettled([
    refreshAdminCreateOptions(),
    refreshAdminGames(),
    refreshAdminDeposits(),
    refreshAdminWithdraws(),
    refreshAdminUsersPanel({ silent }),
    refreshSuperAdminList(),
  ]);
}

function requireAdminSelectedGame() {
  const gid = selectedAdminGameId();
  if (!gid) throw new Error("ابتدا یک بازی از لیست مدیریت انتخاب کنید.");
  return gid;
}

function parseIntegerStrict(raw) {
  const s = toEnglishDigits(String(raw || "")).trim();
  if (!s) return null;
  if (!/^-?\d+$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}

async function adminCreateGame() {
  let groupId = parseIntegerStrict(getVal("adminCreateGroupIdInput"));
  if (groupId == null) {
    groupId = parseIntegerStrict(state.admin?.create?.groupId);
  }

  let topicId = parseIntegerStrict(getVal("adminCreateTopicIdInput"));
  if (topicId == null) {
    topicId = parseIntegerStrict(state.admin?.create?.selectedTopicId);
  }

  let cardPrice = parsePositiveInt(getVal("adminCreateCardPriceInput"));

  if (state.admin?.create?.enforceTopic && topicId == null) {
    throw new Error("ابتدا یکی از تاپیک‌های بازی را انتخاب کنید.");
  }
  if (groupId == null) throw new Error("شناسه گروه در تنظیمات مشخص نیست.");
  if (groupId === 0) throw new Error("شناسه گروه نامعتبر است.");
  if (topicId != null && topicId <= 0) throw new Error("شناسه تاپیک نامعتبر است.");
  if (!cardPrice || cardPrice <= 0) throw new Error("قیمت کارت باید بیشتر از صفر باشد.");

  setAdminCreateTopic(topicId, { silent: true });
  setHint("adminCreateHintMsg", "در حال ایجاد بازی جدید...");
  const body = {
    tg_group_id: Number(groupId),
    tg_topic_id: topicId == null ? null : Number(topicId),
    card_price: Number(cardPrice),
    source_game_id: null,
    idempotency_key: idem("mini_admin_create_game"),
  };
  const res = await apiFetch("/mini-api/admin/games/create", { method: "POST", body });
  const newGameId = Number(res?.game?.id || 0);
  const reused = Boolean(res?.reused_active);
  const activePrice = Number(res?.game?.card_price || 0);
  const requestedPrice = Number(res?.requested_card_price || cardPrice || 0);
  if (reused) {
    const reuseMsg =
      activePrice > 0 && requestedPrice > 0 && activePrice !== requestedPrice
        ? `برای این تاپیک، بازی فعال موجود بود (#${newGameId}) و قیمت کارت فعلی ${toman(activePrice)} است.`
        : `برای این تاپیک، بازی فعال موجود بود و همان بازی #${newGameId} انتخاب شد.`;
    setHint("adminCreateHintMsg", reuseMsg, "success");
    setBadge("success", newGameId ? `بازی فعال #${newGameId} موجود بود` : "بازی فعال موجود بود");
  } else {
    setHint("adminCreateHintMsg", newGameId ? `بازی #${newGameId} با موفقیت ایجاد شد.` : "بازی جدید ایجاد شد.", "success");
    setBadge("success", newGameId ? `بازی #${newGameId} ایجاد شد` : "بازی جدید ایجاد شد");
  }

  await Promise.allSettled([refreshAdminGames(), refreshGames(), refreshAdminCreateOptions()]);
  if (newGameId) {
    const g = getAdminGameById(newGameId);
    setAdminSelectedGame(newGameId, statusLabel(g?.status || "LOBBY"));
  }
}

async function adminStartGame() {
  const { gid } = requireAdminGameStatus(["LOBBY"], "شروع بازی");
  setHint("adminActionHint", "در حال شروع بازی...");
  await apiFetch(`/mini-api/admin/games/${gid}/start`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_start") },
  });
  setHint("adminActionHint", `بازی #${gid} شروع شد.`, "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
}

async function adminCallNumber() {
  const { gid } = requireAdminGameStatus(["RUNNING"], "اعلام عدد");
  const number = Number(getVal("adminCallNumberInput") || "0");
  if (!number || number < 1 || number > 99) throw new Error("عدد اعلام باید بین 1 تا 99 باشد.");
  setHint("adminActionHint", "در حال ثبت عدد...");
  await apiFetch(`/mini-api/admin/games/${gid}/call`, {
    method: "POST",
    body: { number, idempotency_key: idem("mini_admin_call") },
  });
  setVal("adminCallNumberInput", "");
  setHint("adminActionHint", `عدد ${number} برای بازی #${gid} ثبت شد.`, "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid), refreshCards({ silent: true })]);
}

async function adminUndoCall() {
  const { gid } = requireAdminGameStatus(["RUNNING"], "حذف آخرین عدد");
  setHint("adminActionHint", "در حال Undo آخرین عدد...");
  await apiFetch(`/mini-api/admin/games/${gid}/undo-last-call`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_undo") },
  });
  setHint("adminActionHint", "آخرین عدد بازی با موفقیت Undo شد.", "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid), refreshCards({ silent: true })]);
}

async function adminCloseLobby() {
  const { gid } = requireAdminGameStatus(["LOBBY"], "لغو لابی");
  const reason = getVal("adminCancelReasonInput");
  if (!reason || reason.length < 3) throw new Error("علت لغو باید حداقل 3 کاراکتر باشد.");
  setHint("adminActionHint", "در حال لغو بازی لابی...");
  const res = await apiFetch(`/mini-api/admin/games/${gid}/close-lobby`, {
    method: "POST",
    body: { cancel_reason: reason, idempotency_key: idem("mini_admin_close_lobby") },
  });
  setVal("adminCancelReasonInput", "");
  const st = res?.refund_notify || {};
  const usersCount = Number(st.refund_users_count || 0);
  const refundTotal = Number(st.refund_total || 0);
  const okCount = Number(st.notified_ok || 0);
  const failCount = Number(st.notify_failed || 0);
  const noTgCount = Number(st.no_tg_count || 0);
  let hint = "بازی لابی با موفقیت لغو شد.";
  if (usersCount > 0) {
    hint = `بازی لابی لغو شد. بازگشت وجه: ${usersCount} کاربر (${toman(refundTotal)}). پیام خصوصی: موفق ${okCount} | ناموفق ${failCount} | بدون شناسه ${noTgCount}.`;
  }
  setHint("adminActionHint", hint, "success");
  await Promise.allSettled([refreshAdminGames(), refreshWallet(), refreshCards({ silent: true }), refreshAdminDeposits(), refreshAdminWithdraws()]);
}

async function adminSetLiveLink() {
  const gid = requireAdminSelectedGame();
  const url = getVal("adminLiveLinkInput");
  if (!url) throw new Error("لینک لایو را وارد کنید.");
  setHint("adminActionHint", "در حال ثبت لینک لایو...");
  await apiFetch(`/mini-api/admin/games/${gid}/live-link`, {
    method: "PUT",
    body: { url },
  });
  state.admin.liveLinksByGame?.set(gid, String(url || "").trim());
  setHint("adminActionHint", "لینک لایو بازی با موفقیت ثبت شد. اکنون می‌توانید آن را برای خریداران کارت ارسال کنید.", "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
  setAdminSelectedGame(gid, statusLabel(getAdminGameById(gid)?.status || ""));
  updateAdminActionButtons();
}
async function adminSendLiveLink() {
  const gid = requireAdminSelectedGame();
  const g = getAdminGameById(gid);
  const liveUrl = adminLiveLinkForGame(gid);
  if (!liveUrl) throw new Error("ابتدا لینک لایو را ثبت کنید.");
  setHint("adminActionHint", "در حال ارسال لینک لایو به خریداران کارت...");
  const res = await apiFetch(`/mini-api/admin/games/${gid}/live-link/send`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_live_send") },
  });
  const participants = Number(res?.participants_count || 0);
  const okCount = Number(res?.notified_ok || 0);
  const failCount = Number(res?.notify_failed || 0);
  const noTgCount = Number(res?.no_tg_count || 0);
  const msg = `لینک لایو بازی #${gid} ارسال شد. خریداران: ${participants} | موفق: ${okCount} | ناموفق: ${failCount} | بدون شناسه: ${noTgCount}`;
  setHint("adminActionHint", msg, okCount > 0 ? "success" : "error");
  setBadge(okCount > 0 ? "success" : "error", okCount > 0 ? "لینک لایو ارسال شد" : "ارسال لینک لایو ناموفق بود");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
}


async function adminClearLiveLink() {
  const gid = requireAdminSelectedGame();
  setHint("adminActionHint", "در حال حذف لینک لایو...");
  await apiFetch(`/mini-api/admin/games/${gid}/live-link`, { method: "DELETE" });
  state.admin.liveLinksByGame?.delete(gid);
  setHint("adminActionHint", "لینک لایو حذف شد.", "success");
  updateAdminActionButtons();
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
}

async function adminApproveDeposit(depositId) {
  await apiFetch(`/mini-api/admin/deposits/${Number(depositId)}/approve`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_dep_approve") },
  });
  setBadge("success", `واریزی #${depositId} تایید شد`);
  await Promise.allSettled([refreshAdminDeposits(), refreshWallet()]);
}

async function adminRejectDeposit(depositId) {
  await apiFetch(`/mini-api/admin/deposits/${Number(depositId)}/reject`, { method: "POST" });
  setBadge("success", `واریزی #${depositId} رد شد`);
  await refreshAdminDeposits();
}


async function adminRefreshWithdrawWallet(withdrawId) {
  const id = Number(withdrawId || 0);
  if (!id) throw new Error("شناسه برداشت نامعتبر است.");
  setBadge("loading", "در حال بروزرسانی کیف پول...");
  const info = await apiFetch(`/mini-api/admin/withdraws/${id}/wallet-status`);
  setWithdrawWalletStatus(id, info);
  setBadge(info?.can_approve ? "success" : "error", info?.can_approve ? "کیف پول بروزرسانی شد؛ تایید مجاز است" : "موجودی قابل تایید کافی نیست");
  return info;
}


async function adminApproveWithdraw(withdrawId) {
  const info = await adminRefreshWithdrawWallet(withdrawId);
  if (!info?.can_approve) throw new Error("موجودی قابل تایید برای این برداشت کافی نیست. درخواست را رد یا دوباره بررسی کنید.");
  await apiFetch(`/mini-api/admin/withdraws/${Number(withdrawId)}/approve`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_wdr_approve") },
  });
  setBadge("success", `برداشت #${withdrawId} تایید شد`);
  await Promise.allSettled([refreshAdminWithdraws(), refreshWallet()]);
}

async function adminRejectWithdraw(withdrawId) {
  await apiFetch(`/mini-api/admin/withdraws/${Number(withdrawId)}/reject`, {
    method: "POST",
    body: { reason: "رد توسط ادمین" },
  });
  setBadge("success", `برداشت #${withdrawId} رد شد`);
  await refreshAdminWithdraws();
}



let withdrawProofModalWithdrawId = 0;
let withdrawProofSelectedFile = null;
let withdrawProofModalBound = false;

function withdrawProofAllowedImage(file) {
  if (!file) return true;
  const type = String(file.type || "").toLowerCase();
  const name = String(file.name || "").toLowerCase();
  const okType = type.startsWith("image/");
  const okExt = [".jpg", ".jpeg", ".png", ".webp"].some((ext) => name.endsWith(ext));
  if (!okType && !okExt) {
    throw new Error("فرمت تصویر فیش مجاز نیست. فقط JPG، PNG یا WEBP قابل قبول است.");
  }
  const maxBytes = 3 * 1024 * 1024;
  if (Number(file.size || 0) > maxBytes) {
    throw new Error("حجم تصویر فیش نباید بیشتر از ۳ مگابایت باشد.");
  }
  return true;
}

function closeWithdrawProofModal() {
  const modal = getEl("withdrawProofModal");
  if (modal) {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
  }
  withdrawProofModalWithdrawId = 0;
  withdrawProofSelectedFile = null;
}

function setWithdrawProofHint(text, kind = "") {
  const el = getEl("withdrawProofHint");
  if (!el) return;
  el.textContent = String(text || "");
  el.classList.remove("success", "error", "pending");
  if (kind) el.classList.add(kind);
}

async function renderWithdrawProofPreview(file) {
  const preview = getEl("withdrawProofPreview");
  const nameEl = getEl("withdrawProofFileName");
  if (!preview) return;

  if (!file) {
    preview.classList.add("hidden");
    preview.innerHTML = "";
    if (nameEl) nameEl.textContent = "هیچ فایلی انتخاب نشده";
    return;
  }

  withdrawProofAllowedImage(file);
  if (nameEl) nameEl.textContent = `${file.name || "تصویر فیش"} - ${Math.ceil(Number(file.size || 0) / 1024)}KB`;

  const dataUrl = await readFileAsDataUrl(file);
  preview.innerHTML = `
    <div class="withdraw-proof-preview-card">
      <span>پیش‌نمایش فیش انتخاب‌شده</span>
      <img src="${dataUrl}" alt="پیش‌نمایش فیش پرداخت" />
    </div>
  `;
  preview.classList.remove("hidden");
  try {
    const modalCard = document.querySelector("#withdrawProofModal .withdraw-proof-modal-card");
    if (modalCard) {
      modalCard.scrollLeft = 0;
    }
    document.body.scrollLeft = 0;
    document.documentElement.scrollLeft = 0;
  } catch (_) {}
}

function bindWithdrawProofModalOnce() {
  if (withdrawProofModalBound) return;
  withdrawProofModalBound = true;

  const closeBtn = getEl("withdrawProofCloseBtn");
  const cancelBtn = getEl("withdrawProofCancelBtn");
  const submitBtn = getEl("withdrawProofSubmitBtn");
  const fileInput = getEl("withdrawProofFileInput");
  const modal = getEl("withdrawProofModal");

  if (closeBtn) closeBtn.addEventListener("click", closeWithdrawProofModal);
  if (cancelBtn) cancelBtn.addEventListener("click", closeWithdrawProofModal);

  if (modal) {
    modal.addEventListener("click", (ev) => {
      if (ev.target === modal) closeWithdrawProofModal();
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
      try {
        withdrawProofSelectedFile = file;
        await renderWithdrawProofPreview(file);
        setWithdrawProofHint(file ? "تصویر فیش آماده ارسال است." : "", file ? "success" : "");
      } catch (e) {
        withdrawProofSelectedFile = null;
        fileInput.value = "";
        await renderWithdrawProofPreview(null);
        setWithdrawProofHint(e.message || "فایل فیش نامعتبر است.", "error");
      }
    });
  }

  if (submitBtn) {
    submitBtn.addEventListener("click", () => submitWithdrawProofModal().catch((e) => {
      setWithdrawProofHint(e.message || "ثبت فیش پرداخت ناموفق بود.", "error");
      setBadge("error", e.message || "ثبت فیش پرداخت ناموفق بود.");
    }));
  }
}

function openWithdrawProofModal(withdrawId) {
  const id = Number(withdrawId || 0);
  if (!id) throw new Error("شناسه برداشت نامعتبر است.");

  bindWithdrawProofModalOnce();
  withdrawProofModalWithdrawId = id;
  withdrawProofSelectedFile = null;

  const modal = getEl("withdrawProofModal");
  const textInput = getEl("withdrawProofTextInput");
  const fileInput = getEl("withdrawProofFileInput");
  const submitBtn = getEl("withdrawProofSubmitBtn");
  const meta = getEl("withdrawProofModalMeta");

  if (textInput) textInput.value = "";
  if (fileInput) fileInput.value = "";
  if (submitBtn) {
    submitBtn.disabled = false;
    submitBtn.textContent = "ثبت نهایی پرداخت";
  }
  if (meta) {
    meta.textContent = `برداشت #${id} تایید شده و مبلغ از کیف پول کسر شده است. فیش پرداخت را به صورت متن یا تصویر ثبت کنید.`;
  }
  renderWithdrawProofPreview(null);
  setWithdrawProofHint("حداقل یکی از این دو مورد را وارد کنید: متن فیش یا تصویر فیش.", "pending");

  if (!modal) throw new Error("پنجره ثبت فیش در صفحه پیدا نشد.");
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  setTimeout(() => {
    try { textInput?.focus(); } catch (_) {}
  }, 50);
}

async function adminSaveWithdrawProof(withdrawId, proofText, file) {
  const body = { proof_text: String(proofText || "").trim() };
  if (file) {
    withdrawProofAllowedImage(file);
    body.filename = String(file.name || "withdraw-proof.jpg");
    body.content_type = String(file.type || "image/jpeg");
    body.data_base64 = await readFileAsDataUrl(file);
  }
  return apiFetch(`/mini-api/admin/withdraws/${Number(withdrawId)}/proof`, {
    method: "POST",
    body,
  });
}

async function submitWithdrawProofModal() {
  const id = Number(withdrawProofModalWithdrawId || 0);
  if (!id) throw new Error("شناسه برداشت نامعتبر است.");

  const textInput = getEl("withdrawProofTextInput");
  const submitBtn = getEl("withdrawProofSubmitBtn");
  const proofText = String(textInput?.value || "").trim();
  const file = withdrawProofSelectedFile || null;

  if (!proofText && !file) {
    throw new Error("برای ثبت پرداخت، متن فیش/کد پیگیری یا تصویر فیش الزامی است.");
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "در حال ثبت...";
  }
  setWithdrawProofHint("در حال ثبت فیش پرداخت و نهایی‌سازی برداشت...", "pending");
  setBadge("loading", "در حال ثبت فیش برداشت...");

  try {
    await adminSaveWithdrawProof(id, proofText, file);
    const tracking = proofText || `image_receipt_${Date.now()}`;
    await apiFetch(`/mini-api/admin/withdraws/${id}/paid`, {
      method: "POST",
      body: { paid_tracking: tracking.slice(0, 128) },
    });

    setWithdrawProofHint("فیش پرداخت ثبت شد و برداشت پرداخت‌شده شد.", "success");
    setBadge("success", `برداشت #${id} پرداخت‌شده ثبت شد`);
    closeWithdrawProofModal();
    await refreshAdminWithdraws();
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "ثبت نهایی پرداخت";
    }
  }
}

async function adminPaidWithdraw(withdrawId) {
  openWithdrawProofModal(withdrawId);
}

async function superAdminGrant() {
  const tgUserId = Number(getVal("superAdminTgUserInput") || "0");
  const role = String(getVal("superAdminRoleSelect") || "ADMIN").toUpperCase();
  if (!tgUserId) throw new Error("شناسه تلگرام معتبر وارد کنید.");
  await apiFetch("/mini-api/admin/super/admins/grant", {
    method: "POST",
    body: { tg_user_id: tgUserId, role },
  });
  setHint("superAdminHint", `نقش ${role} برای ${tgUserId} ثبت شد.`, "success");
  await refreshSuperAdminList();
}

async function superAdminRevoke() {
  const tgUserId = Number(getVal("superAdminTgUserInput") || "0");
  const role = String(getVal("superAdminRoleSelect") || "ADMIN").toUpperCase();
  if (!tgUserId) throw new Error("شناسه تلگرام معتبر وارد کنید.");
  await apiFetch("/mini-api/admin/super/admins/revoke", {
    method: "POST",
    body: { tg_user_id: tgUserId, role },
  });
  setHint("superAdminHint", `نقش ${role} از ${tgUserId} حذف شد.`, "success");
  await refreshSuperAdminList();
}

function isCardsViewActive() {
  const v = getEl("view-cards");
  return Boolean(v && v.classList.contains("active"));
}

function isAdminViewActive() {
  const v = getEl("view-admin");
  return Boolean(v && v.classList.contains("active"));
}

function switchToView(target) {
  const views = {
    games: getEl("view-games"),
    cards: getEl("view-cards"),
    wallet: getEl("view-wallet"),
    admin: getEl("view-admin"),
  };

  const desired = Object.prototype.hasOwnProperty.call(views, target) ? target : "games";
  const normalized = desired === "admin" && !state.admin.enabled ? "games" : desired;

  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-view") === normalized);
  });

  Object.entries(views).forEach(([k, el]) => {
    if (el) el.classList.toggle("active", k === normalized);
  });

  if (normalized === "cards") {
    startCardsPolling();
    refreshCards({ silent: true }).catch(() => {});
  } else {
    stopCardsPolling();
  }

  if (normalized === "admin" && state.admin.enabled) {
    refreshAdminPanel().catch((e) => setBadge("error", e.message));
  }
}

function wireNavigation() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-view") || "games";
      switchToView(target);
    });
  });
}

function applyTheme(theme) {
  const normalized = String(theme || "").toLowerCase() === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", normalized);
  localStorage.setItem("davarna_theme", normalized);

  const btn = getEl("themeBtn");
  if (btn) {
    const next = normalized === "dark" ? "روشن" : "تیره";
    const currentLabel = normalized === "dark" ? "تیره" : "روشن";
    btn.textContent = `◐ حالت ${currentLabel}`;
    btn.setAttribute("title", `تغییر به حالت ${next}`);
    btn.setAttribute("aria-label", `تغییر به حالت ${next}`);
  }
}

function wireTheme() {
  const btn = getEl("themeBtn");
  const saved = localStorage.getItem("davarna_theme");
  const tgTheme = tg?.colorScheme === "light" ? "light" : "dark";
  applyTheme(saved || tgTheme || "dark");
  if (!btn) return;

  btn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    applyTheme(current === "dark" ? "light" : "dark");
  });
}

function wireWalletDynamic() {
  bind("withdrawAmountInput", "input", renderWithdrawPreview);
  bind("withdrawFullNameInput", "input", renderWithdrawPreview);

  bind("withdrawCardInput", "input", () => {
    const sanitized = toEnglishDigits(getVal("withdrawCardInput")).replace(/\D/g, "").slice(0, 16);
    setVal("withdrawCardInput", sanitized);
    renderWithdrawPreview();
  });

  bind("withdrawIbanInput", "input", () => {
    const sanitized = toEnglishDigits(getVal("withdrawIbanInput")).replace(/\s+/g, "").toUpperCase().slice(0, 26);
    setVal("withdrawIbanInput", sanitized);
    renderWithdrawPreview();
  });

  bind("withdrawAccountInput", "input", () => {
    const sanitized = toEnglishDigits(getVal("withdrawAccountInput")).replace(/[^\d]/g, "").slice(0, 20);
    setVal("withdrawAccountInput", sanitized);
    renderWithdrawPreview();
  });

  renderWithdrawPreview();
}


function wireWalletUxHelpers() {
  document.querySelectorAll(".wallet-jump-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-target") === "withdraw" ? ".withdraw-flow" : ".deposit-flow";
      const el = document.querySelector(target);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      triggerLightHaptic("success");
    });
  });

  document.querySelectorAll(".amount-preset").forEach((btn) => {
    btn.addEventListener("click", () => {
      const amount = Number(btn.getAttribute("data-amount") || "0");
      if (!amount) return;
      setVal("depositAmountInput", String(amount));
      document.querySelectorAll(".amount-preset").forEach((b) => b.classList.remove("is-selected"));
      btn.classList.add("is-selected");
      setHint("depositSubmitHint", `مبلغ شارژ روی ${toman(amount)} تنظیم شد.`, "success");
      triggerLightHaptic("success");
    });
  });

  const receiptInput = getEl("depositReceiptFileInput");
  if (receiptInput) {
    receiptInput.addEventListener("change", () => {
      const box = getEl("receiptPreview");
      if (!box) return;
      const file = receiptInput.files && receiptInput.files[0];
      if (state.receiptPreviewUrl) {
        try { URL.revokeObjectURL(state.receiptPreviewUrl); } catch (_) {}
        state.receiptPreviewUrl = null;
      }
      if (!file) {
        box.classList.add("hidden");
        box.innerHTML = "";
        return;
      }
      const name = safeText(file.name || "رسید انتخاب‌شده");
      const sizeKb = Math.max(1, Math.round(Number(file.size || 0) / 1024));
      if (String(file.type || "").startsWith("image/")) {
        state.receiptPreviewUrl = URL.createObjectURL(file);
        box.innerHTML = `<strong>پیش‌نمایش رسید:</strong><div>${name} — ${safeText(sizeKb)} KB</div><img src="${state.receiptPreviewUrl}" alt="پیش‌نمایش رسید" />`;
      } else {
        box.innerHTML = `<strong>فایل رسید انتخاب شد:</strong><div>${name} — ${safeText(sizeKb)} KB</div>`;
      }
      box.classList.remove("hidden");
      triggerLightHaptic("success");
    });
  }
}

function wireAdminCreateUi() {
  const row = getEl("adminPricePresetRow");
  if (row) {
    row.querySelectorAll(".price-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const price = parsePositiveInt(btn.getAttribute("data-price") || "");
        if (!price) return;
        setVal("adminCreateCardPriceInput", String(price));
        setHint("adminCreateHintMsg", `قیمت کارت روی ${toman(price)} تنظیم شد.`, "success");
      });
    });
  }

  renderAdminCreateTopics();
}

function wireAdminAccordion() {
  const items = Array.from(document.querySelectorAll("#view-admin .accordion-item"));
  if (!items.length) return;
  items.forEach((item) => {
    item.addEventListener("toggle", () => {
      if (!item.open) return;
      items.forEach((other) => {
        if (other !== item) other.open = false;
      });
    });
  });
}

async function boot() {
  if (tg) {
    tg.ready();
    tg.expand();
  }

  setSplashStatus("در حال بارگذاری رابط بازی...");
  localizeShell();
  localizeCardsShell();
  if (headerUserName) headerUserName.textContent = inferDisplayName();
  updateHeaderStatus();
  wireNavigation();
  wireTheme();
  wireWalletDynamic();
  wireWalletUxHelpers();
  initSoundPreference();
  wireAdminCreateUi();
  wireAdminAccordion();
  wireAdminNotify();
  wireCardsPullToRefresh();
  updateBuyActionState({ statusKey: "", myCardsCount: 0 });
  renderLiveLink({});
  const copyBtn = getEl("copyDepositCardBtn");
  if (copyBtn) copyBtn.disabled = true;

  bind("soundBtn", "click", toggleSound);
  bind("refreshGamesBtn", "click", () => runManualRefresh("refreshGamesBtn", () => refreshGames()).catch(() => {}));
  bind("refreshCardsBtn", "click", () => runManualRefresh("refreshCardsBtn", () => refreshCards({ silent: false })).catch(() => {}));
  bind("refreshWalletBtn", "click", () => runManualRefresh("refreshWalletBtn", () => refreshWallet()).catch(() => {}));
  bind("buyCardsBtn", "click", () => buySelectedGame().catch((e) => setBadge("error", e.message)));
  bind("submitDepositBtn", "click", () => submitDepositWithReceipt().catch((e) => setBadge("error", e.message)));
  bind("depositDestinationSelect", "change", renderDepositDestinationHint);
  bind("copyDepositCardBtn", "click", () => copySelectedDepositCard().catch((e) => setBadge("error", e.message)));
  bind("submitWithdrawBtn", "click", () => createWithdraw().catch((e) => setBadge("error", e.message)));
  bind("refreshAdminBtn", "click", () => runManualRefresh("refreshAdminBtn", () => refreshAdminPanel()).catch(() => {}));
  bind("adminUsersSearchBtn", "click", () => adminUsersSearch().catch((e) => setBadge("error", e.message)));
  bind("adminUsersRefreshBtn", "click", () => adminUsersRefreshSelected().catch((e) => setBadge("error", e.message)));
  bind("adminUsersSearchInput", "keydown", (ev) => {
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    adminUsersSearch().catch((e) => setBadge("error", e.message));
  });
  bind("adminCreateBtn", "click", () =>
    adminCreateGame().catch((e) => {
      setHint("adminCreateHintMsg", String(e.message || ""), "error");
      setBadge("error", e.message);
    })
  );
  bind("adminCallBtn", "click", () => adminCallNumber().catch((e) => setBadge("error", e.message)));
  bind("adminUndoBtn", "click", () => adminUndoCall().catch((e) => setBadge("error", e.message)));
  bind("adminStartBtn", "click", () => adminStartGame().catch((e) => setBadge("error", e.message)));
  bind("adminCloseLobbyBtn", "click", () => adminCloseLobby().catch((e) => setBadge("error", e.message)));
  bind("adminSetLiveBtn", "click", () => adminSetLiveLink().catch((e) => setBadge("error", e.message)));
  bind("adminSendLiveBtn", "click", () => adminSendLiveLink().catch((e) => setBadge("error", e.message)));
  bind("adminClearLiveBtn", "click", () => adminClearLiveLink().catch((e) => setBadge("error", e.message)));
  bind("superAdminGrantBtn", "click", () => superAdminGrant().catch((e) => setBadge("error", e.message)));
  bind("superAdminRevokeBtn", "click", () => superAdminRevoke().catch((e) => setBadge("error", e.message)));
  bind("winsGameFilter", "change", drawWinTimeline);
  bind("winnerCloseBtn", "click", closeWinnerModal);
  bind("winnerDismissBtn", "click", closeWinnerModal);
  bind("winnerWalletBtn", "click", () => {
    closeWinnerModal();
    switchToView("wallet");
  });
  bind("historyCloseBtn", "click", closeHistoryModal);
  const winnerModal = getEl("winnerModal");
  if (winnerModal) {
    winnerModal.addEventListener("click", (e) => {
      if (e.target === winnerModal) closeWinnerModal();
    });
  }
  const historyModal = getEl("historyModal");
  if (historyModal) {
    historyModal.addEventListener("click", (e) => {
      if (e.target === historyModal) closeHistoryModal();
    });
  }

  let authOk = false;
  try {
    setSplashStatus("در حال اتصال امن به حساب شما...");
    if (restoreMiniSession()) {
      authOk = true;
      setBadge("success", "متصل شد");
    } else {
      await exchangeSession();
      authOk = true;
    }
  } catch (err) {
    clearMiniSession();
    state.authReady = false;
    setBadge("error", String(err.message || "خطای احراز هویت"));
  }

  if (!authOk) return;

  setSplashStatus("در حال دریافت بازی‌ها و کیف پول...");
  loadAdminNotifySeen();
  await refreshAdminBootstrap();
  await Promise.allSettled([refreshGames(), refreshCards({ silent: false }), refreshWallet()]);
  if (state.admin.enabled) {
    checkAdminFinanceNotifications({ silent: false }).catch(() => {});
  }
  startGlobalRefresh();

  const current = document.querySelector(".nav-btn.active")?.getAttribute("data-view") || "games";
  switchToView(current);
  setSplashStatus("آماده بازی هستید");
  setTimeout(hideSplash, 260);
}


window.addEventListener("beforeunload", () => {
  stopEventPolling();
  stopCardsPolling();
  stopGlobalRefresh();
});
boot().catch((err) => {
  setBadge("error", String(err.message || "خطای داخلی"));
  setSplashStatus("خطا در آماده‌سازی. لطفاً دوباره تلاش کنید.");
  setTimeout(hideSplash, 900);
});
