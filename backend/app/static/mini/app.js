Warning: truncated output (original token count: 83389)
Total output lines: 8264

const tg = window.Telegram?.WebApp;

const state = {
  token: null,
  tokenExp: 0,
  authReady: false,
  selectedGameId: null,
    adminWithdrawWalletStatus: new Map(),
  lastEventId: 0,
  liveEventCursorByGame: {},
  pollTimer: null,
  miniSocket: null,
  miniSocketReconnectTimer: null,
  miniSocketManualClose: false,
  miniSocketConnected: false,
  miniSocketLiveGameId: 0,
  miniSocketCryptoInvoiceId: 0,
  miniSocketFinanceKey: "",
  tokenRefreshPromise: null,
  depositDestinations: [],
  cryptoOptions: null,
  cryptoCurrentInvoice: null,
  cryptoQrObjectUrl: "",
  cryptoQrInvoiceId: 0,
  cryptoCountdownTimer: null,
  cryptoServerOffsetMs: 0,
  cryptoInvoiceViewOpen: false,
  cryptoExpiryRefreshId: 0,
  cryptoWalletCheckout: null,
  cryptoPaymentBusy: false,
  cryptoRefreshBusy: false,
  cryptoManualPaymentOpen: false,
  cryptoTxDetailsOpen: false,
  cryptoInvoiceHintText: "",
  cryptoInvoiceHintType: "",
  cryptoTxHashDraft: "",
  notifications: [],
  notificationReadIds: new Set(),
  notificationsOpen: false,
  latestLiveBarGameId: 0,
  liveBarExpanded: false,
  cardsPollTimer: null,
  cardsPrevCalledByGame: {},
  cardsLatestSeenEventByGame: {},
  cardsPullBusy: false,
  currentUserId: 0,
  lastWinnerEventId: 0,
  lastWinnerModalKey: "",
  userWinnerNoticeSeen: new Set(),
  userWinnerSeenStorageKey: "",
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
  depositReceiptObjectUrl: null,
  splashHidden: false,
  gamesCache: [],
  walletCache: {
    balance: null,
    txs: null,
    deposits: null,
    withdraws: null,
    destinations: null,
    cryptoOptions: null,
    cryptoDeposits: null,
  },
  admin: {
    enabled: false,
    isSuper: false,
    roles: [],
    cryptoSettings: null,
    bankDepositSettings: null,
    selectedGameId: 0,
    gamesById: new Map(),
    liveLinksByGame: new Map(),
    autoDrawByGame: new Map(),
    depositsById: new Map(),
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
const TOKEN_REFRESH_BEFORE_SEC = 180;
const MINI_SOCKET_RECONNECT_MS = 2500;

function _nowSec() {
  return Math.floor(Date.now() / 1000);
}

function clearMiniSession() {
  stopMiniSocket();
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

const CRYPTO_STATUS_LABELS = {
  WAITING_PAYMENT: "در انتظار پرداخت",
  CONFIRMING: "در حال تایید شبکه",
  CREDITED: "تایید و شارژ شده",
  EXPIRED: "منقضی شده",
  NEEDS_REVIEW: "نیازمند بررسی ادمین",
  REJECTED: "رد شده",
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

const ADMIN_ROLE_LABELS = {
  GAME_OPERATOR: "اپراتور بازی",
  FINANCE_ADMIN: "ادمین مالی",
  ADMIN: "ادمین",
  SUPER_ADMIN: "سوپرادمین",
};

const ADMIN_AUDIT_ACTION_LABELS = {
  "game.create": "ایجاد بازی",
  "game.start": "شروع بازی",
  "game.call": "اعلام عدد",
  "user.restrict": "محدود کردن کاربر",
  "user.unrestrict": "رفع محدودیت کاربر",
  "user.wallet_adjust": "اصلاح کیف پول",
  "settings.update": "تغییر تنظیمات",
  "admin.grant": "اعطای نقش",
  "admin.revoke": "حذف نقش",
  "deposit.approve": "تایید واریز",
  "deposit.reject": "رد واریز",
  "crypto.deposit.approve": "تایید واریز کریپتو",
  "crypto.deposit.reject": "رد واریز کریپتو",
  "crypto.wallet.connected": "اتصال کیف پول کریپتو",
  "crypto.payment.requested": "درخواست پرداخت کریپتو",
  "risk.buy.insufficient_balance": "تلاش خرید با موجودی ناکافی",
};

const ACTIVE_GAME_STATUSES = new Set(["LOBBY", "RUNNING"]);
const CARDS_REFRESH_INTERVAL_MS = 2200;
const GLOBAL_REFRESH_INTERVAL_MS = 12000;
const ADMIN_NOTIFY_STORAGE_KEY = "davarna_admin_notify_seen_v1";
const NOTIFICATION_READ_STORAGE_KEY = "davarna_notification_read_v1";
const ADMIN_NOTIFY_HIDE_MS = 8500;
const HISTORY_LIST_LIMIT = 15;
const CARD_HISTORY_LIMIT = 10;
const LIVE_EVENTS_LIMIT = 15;

const UI_TEXT = {
  brandTitle: "دبرنای طوفان",
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
    adminCallNumberInput: "عدد بین 1 تا 90",
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
  await openNotificationRoute(item);
}

function scrollAndHighlight(target) {
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("admin-notify-highlight");
  setTimeout(() => target.classList.remove("admin-notify-highlight"), 1800);
}

function cssAttrValue(value) {
  const raw = String(value ?? "");
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(raw);
  return raw.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function openAdminSectionForList(listId) {
  const list = getEl(listId);
  if (!list) return;
  const details = list.closest("details");
  if (details) details.open = true;
  return list;
}

function adminListAttrFor(listId) {
  const map = {
    adminDepositsList: "data-admin-deposit-id",
    adminWithdrawsList: "data-admin-withdraw-id",
    adminCryptoDepositsList: "data-admin-crypto-id",
    adminAuditLogsList: "data-admin-audit-id",
  };
  return map[listId] || "";
}

function openAdminAccordionFor(listId, itemId, attrName = "") {
  const list = openAdminSectionForList(listId);
  if (!list) return;
  const attr = attrName || adminListAttrFor(listId);
  const item = itemId ? list.querySelector(`[${attr}="${Number(itemId)}"]`) : null;
  const target = item || list;
  scrollAndHighlight(target);
}

async function openAdminRoute(route) {
  if (!state.admin.enabled) {
    switchToView("wallet");
    showToast("این اعلان مدیریتی است و با نقش فعلی قابل مشاهده نیست.", "error");
    return;
  }

  switchToView("admin");
  const section = String(route.section || "").toLowerCase();
  const targetType = String(route.targetType || "").toLowerCase();
  const id = Number(route.targetId || 0);

  if (section === "deposits" || targetType === "deposit_request") {
    await refreshAdminDeposits();
    openAdminAccordionFor("adminDepositsList", id);
    if (route.action === "open_receipt" && id) {
      await openAdminDepositReceipt(id);
    }
    return;
  }

  if (section === "withdraws" || targetType === "withdraw_request") {
    await refreshAdminWithdraws();
    openAdminAccordionFor("adminWithdrawsList", id);
    return;
  }

  if (section === "crypto" || section === "crypto_deposits" || targetType === "crypto_deposit_request") {
    await refreshAdminCryptoDeposits();
    openAdminAccordionFor("adminCryptoDepositsList", id);
    return;
  }

  if (section === "risk" || targetType === "risk_alert") {
    await refreshAdminRiskAlerts();
    const list = openAdminSectionForList("adminRiskAlertsList");
    const riskType = cssAttrValue(route.meta?.target_type || "");
    const riskId = Number(route.meta?.target_id || id || 0);
    const target = list?.querySelector(`[data-risk-target-type="${riskType}"][data-risk-target-id="${riskId}"]`) || list;
    scrollAndHighlight(target);
    return;
  }

  if (section === "audit" || targetType === "admin_audit_log") {
    await refreshAdminAuditLogs();
    openAdminAccordionFor("adminAuditLogsList", id);
    return;
  }

  if (section === "users" || targetType === "user") {
    openAdminSectionForList("adminUsersProfileBox");
    const tgId = Number(route.meta?.tg_user_id || route.targetId || 0);
    if (tgId) {
      await adminUsersOpenProfile(tgId, { silent: false });
      scrollAndHighlight(getEl("adminUsersProfileBox"));
    }
    return;
  }

  if (section === "games" || targetType === "game") {
    if (id) {
      setAdminSelectedGame(id);
      switchToView("games");
      await openLiveGame(id);
      return;
    }
  }

  await refreshAdminPanel();
  scrollAndHighlight(getEl("adminOpsDashboard"));
}

async function openNotificationRoute(item) {
  const route = notificationRoute(item || {});
  const view = String(route.view || "").toLowerCase();
  const section = String(route.section || "").toLowerCase();
  const targetType = String(route.targetType || "").toLowerCase();
  const id = Number(route.targetId || 0);

  if (view === "admin") {
    await openAdminRoute(route);
    return;
  }

  if (view === "games" || section === "live" || route.action === "open_live_game") {
    switchToView("games");
    if (id) await openLiveGame(id);
    return;
  }

  if (view === "cards" || section === "wins" || route.action === "open_winning_card") {
    switchToView("cards");
    await refreshCards({ silent: true });
    const gameId = id || Number(route.meta?.game_id || 0);
    const cardId = Number(route.meta?.card_id || 0);
    if (gameId) {
      await openHistoryModalForGame(gameId, { cardId, source: "notification" });
    }
    return;
  }

  switchToView("wallet");
  await refreshWallet();
  if (route.action === "open_receipt" && route.receiptKind && route.receiptId) {
    await openReceiptModal(route.receiptKind, route.receiptId);
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
  return "کاربر دبرنای طوفان";
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

function cryptoStatusLabel(value) {
  const key = String(value || "").toUpperCase();
  return CRYPTO_STATUS_LABELS[key] || statusLabel(value);
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
  DEPOSIT_CRYPTO: "واریز تاییدشده رمزارز",
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

function loadNotificationReadIds() {
  try {
    const raw = localStorage.getItem(NOTIFICATION_READ_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    state.notificationReadIds = new Set(Array.isArray(parsed) ? parsed.map((x) => String(x)) : []);
  } catch (_) {
    state.notificationReadIds = new Set();
  }
}

function saveNotificationReadIds() {
  try {
    localStorage.setItem(
      NOTIFICATION_READ_STORAGE_KEY,
      JSON.stringify([...state.notificationReadIds].slice(-300))
    );
  } catch (_) {}
}

function notificationSeverityLabel(severity) {
  const key = String(severity || "").toLowerCase();
  if (key === "success") return "موفق";
  if (key === "danger" || key === "error") return "نیازمند توجه";
  if (key === "pending") return "در انتظار";
  return "اطلاع";
}

function notificationRoute(item) {
  const route = item?.route && typeof item.route === "object" ? item.route : {};
  const meta = route.meta && typeof route.meta === "object" ? route.meta : {};
  return {
    view: String(route.view || item?.target_view || "wallet").trim() || "wallet",
    section: String(route.section || item?.target_section || "").trim(),
    targetType: String(route.target_type || item?.target_type || "").trim(),
    targetId: Number(route.target_id ?? item?.target_id ?? 0) || 0,
    action: String(route.action || item?.action || "").trim(),
    meta,
    receiptKind: String(item?.receipt_kind || ""),
    receiptId: Number(item?.receipt_id || 0),
  };
}

function updateNotificationBadge() {
  const badge = getEl("notificationsBadge");
  const count = (state.notifications || []).filter((item) => !state.notificationReadIds.has(String(item?.id || ""))).length;
  if (badge) {
    badge.textContent = toFaDigits(count);
    badge.classList.toggle("hidden", count <= 0);
  }
  const meta = getEl("notificationCenterMeta");
  if (meta) {
    meta.textContent = count > 0
      ? `${toFaDigits(count)} اعلان خوانده‌نشده`
      : "همه اعلان‌ها خوانده شده‌اند";
  }
}

function renderNotificationCenter() {
  const root = getEl("notificationList");
  if (!root) return;
  const items = Array.isArray(state.notifications) ? state.notifications : [];
  if (!items.length) {
    root.innerHTML = '<div class="empty">اعلان جدیدی وجود ندارد.</div>';
    updateNotificationBadge();
    return;
  }
  root.innerHTML = items
    .map((item, idx) => {
      const id = String(item?.id || "");
      const read = state.notificationReadIds.has(id);
      const severity = String(item?.severity || "info").toLowerCase();
      const receiptKind = String(item?.receipt_kind || "");
      const receiptId = Number(item?.receipt_id || 0);
      const receiptBtn = receiptKind && receiptId
        ? `<button class="small-btn notification-receipt-btn" data-kind="${safeText(receiptKind)}" data-id="${safeText(receiptId)}" type="button">رسید</button>`
        : "";
      return `
        <div class="notification-item ${read ? "is-read" : "is-unread"}" data-id="${safeText(id)}" data-index="${safeText(String(idx))}">
          <div class="notification-item-main">
            <span class="notification-status ${safeText(severity)}">${safeText(read ? "خوانده شد" : "در انتظار")}</span>
            <strong>${safeText(item?.title || "اعلان")}</strong>
            <p>${safeText(item?.body || "")}</p>
            <small>${safeText(formatFaDateTime(item?.created_at))} | ${safeText(notificationSeverityLabel(severity))}</small>
          </div>
          <div class="notification-item-actions">
            ${receiptBtn}
            <button class="small-btn notification-open-btn" type="button">مشاهده</button>
          </div>
        </div>
      `;
    })
    .join("");

  root.querySelectorAll(".notification-item").forEach((row) => {
    const markRead = () => {
      const id = String(row.getAttribute("data-id") || "");
      if (id) state.notificationReadIds.add(id);
      saveNotificationReadIds();
      updateNotificationBadge();
      row.classList.remove("is-unread");
      row.classList.add("is-read");
    };
    row.querySelector(".notification-open-btn")?.addEventListener("click", () => {
      markRead();
      closeNotificationCenter();
      const idx = Number(row.getAttribute("data-index") || "-1");
      const item = Array.isArray(state.notifications) ? state.notifications[idx] : null;
      openNotificationRoute(item).catch((e) => showToast(localizeApiError(e?.message || e), "error"));
    });
    row.querySelector(".notification-receipt-btn")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      markRead();
      const btn = ev.currentTarget;
      openReceiptModal(String(btn.getAttribute("data-kind") || ""), Number(btn.getAttribute("data-id") || 0))
        .catch((e) => showToast(localizeApiError(e?.message || e), "error"));
    });
  });
  updateNotificationBadge();
}

async function refreshNotifications({ silent = true } = {}) {
  try {
    const out = await apiFetch("/mini-api/me/notifications?limit=50");
    state.notifications = Array.isArray(out?.items) ? out.items : [];
    renderNotificationCenter();
  } catch (error) {
    if (!silent) showToast(localizeApiError(error?.message || error), "error");
  }
}

function openNotificationCenter() {
  state.notificationsOpen = true;
  const modal = getEl("notificationCenter");
  if (!modal) return;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  renderNotificationCenter();
  refreshNotifications({ silent: false }).catch(() => {});
}

function closeNotificationCenter() {
  state.notificationsOpen = false;
  const modal = getEl("notificationCenter");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function markAllNotificationsRead() {
  (state.notifications || []).forEach((item) => {
    const id = String(item?.id || "");
    if (id) state.notificationReadIds.add(id);
  });
  saveNotificationReadIds();
  renderNotificationCenter();
}

function receiptStatusLabel(kind, status) {
  const k = String(kind || "").toLowerCase();
  if (k === "bank_deposit") return depositStatusLabel(status);
  if (k === "withdraw") return withdrawStatusLabel(status);
  if (k === "crypto_deposit") return cryptoStatusLabel(status);
  return statusLabel(status);
}

function receiptAmountText(receipt) {
  const sign = String(receipt?.direction || "").toUpperCase() === "DEBIT" ? "-" : "+";
  return `${sign}${toman(receipt?.amount || 0)}`;
}

function renderReceiptModal(receipt) {
  const body = getEl("receiptModalBody");
  const title = getEl("receiptModalTitle");
  if (!body) return;
  if (title) title.textContent = String(receipt?.title || "رسید تراکنش");
  const items = Array.isArray(receipt?.items) ? receipt.items : [];
  body.innerHTML = `
    <div class="receipt-hero">
      <div class="receipt-seal">✓</div>
      <div>
        <strong>${safeText(receipt?.title || "رسید تراکنش")}</strong>
        <span>${safeText(receiptStatusLabel(receipt?.kind, receipt?.status))}</span>
      </div>
    </div>
    <div class="receipt-grid">
      <div><span>مبلغ</span><strong>${safeText(receiptAmountText(receipt))}</strong></div>
      <div><span>کد پیگیری</span><strong dir="ltr">${safeText(receipt?.tracking_code || "-")}</strong></div>
      <div><span>تاریخ ثبت</span><strong>${safeText(formatFaDateTime(receipt?.created_at))}</strong></div>
      <div><span>تاریخ نهایی</span><strong>${safeText(formatFaDateTime(receipt?.completed_at))}</strong></div>
    </div>
    <div class="receipt-detail-list">
      ${items.map((item) => `
        <div class="receipt-detail-row">
          <span>${safeText(item?.label || "-")}</span>
          <strong dir="auto">${safeText(item?.value || "-")}</strong>
        </div>
      `).join("")}
    </div>
    <div class="receipt-actions">
      ${receipt?.explorer_url ? `<a class="small-btn primary" href="${safeText(receipt.explorer_url)}" target="_blank" rel="noopener noreferrer">مشاهده در Explorer</a>` : ""}
      <button id="receiptCopyBtn" class="small-btn" type="button">کپی رسید</button>
    </div>
  `;
  getEl("receiptCopyBtn")?.addEventListener("click", () => {
    const text = [
      receipt?.title || "رسید تراکنش",
      `وضعیت: ${receiptStatusLabel(receipt?.kind, receipt?.status)}`,
     …63389 tokens truncated… نیست.</div>';

  const modal = ensureAdminWinnerModal();
  const body = getEl("adminWinnerModalBody");
  if (body) {
    body.innerHTML = `
      <div class="admin-winner-summary">
        <div><span>نوع برد</span><strong>${safeText(kindLabel || kind)}</strong></div>
        <div><span>بازی</span><strong>#${safeText(gameId || "-")}</strong></div>
        <div><span>عدد اعلامی</span><strong>${safeText(callNumber || "-")}</strong></div>
        <div><span>مبلغ کل</span><strong>${safeText(total ? toman(total) : "-")}</strong></div>
      </div>
      <div class="admin-winner-list">${winnerRows}</div>
      <div id="adminWinnerCardPanel" class="admin-winner-card-panel hidden"></div>`;
  }

  modal.dataset.gameId = String(gameId || "");
  modal.dataset.cardId = String(firstWinnerCardId || "");
  hideAdminWinnerCardPanel();
  const winnerCopyLines = winnerUsers.length
    ? winnerUsers.map((user, idx) => {
        const parts = [
          `بازیکن ${idx + 1}: ${adminWinnerUserLabel(user)}`,
          `شناسه کاربر: ${Number(user?.userId || 0) || "-"}`,
          Number(user?.tgUserId || 0) ? `شناسه تلگرام: ${Number(user.tgUserId)}` : "",
          `کارت: ${Number(user?.cardId || 0) || "-"}`,
          Number(user?.amount || 0) ? `سهم: ${toman(Number(user.amount))}` : "",
        ].filter(Boolean);
        return parts.join(" | ");
      })
    : ["بازیکن: -"];
  modal.dataset.copyText = [
    `نوع برد: ${kindLabel || kind}`,
    `بازی: #${gameId || "-"}`,
    `عدد اعلامی: ${callNumber || "-"}`,
    `مبلغ کل: ${total ? toman(total) : "-"}`,
    ...winnerCopyLines,
  ].join("\n");

  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function pushAdminWinnerNotice(event) {
  showAdminWinnerPopup(event);
}
// ADMIN_WINNER_POPUP_V6_3_END

function adminAutoDrawState(gameId) {
  const gid = Number(gameId || state.admin?.selectedGameId || 0);
  return gid ? state.admin?.autoDrawByGame?.get(gid) || null : null;
}

function renderAdminAutoDraw() {
  const gid = Number(state.admin?.selectedGameId || 0);
  const data = adminAutoDrawState(gid) || {};
  const status = String(data.status || "STOPPED").toUpperCase();
  const labels = { RUNNING: "در حال اجرا", PAUSED: "متوقف موقت", STOPPED: "متوقف" };
  const statusEl = getEl("adminAutoDrawStatus");
  const remainingEl = getEl("adminAutoDrawRemaining");
  const countdownEl = getEl("adminAutoDrawCountdown");
  const intervalEl = getEl("adminAutoDrawInterval");
  if (statusEl) statusEl.textContent = labels[status] || status;
  if (remainingEl) remainingEl.textContent = Number.isFinite(Number(data.remaining_count)) ? String(Number(data.remaining_count)) : "-";
  if (intervalEl && data.interval_seconds && document.activeElement !== intervalEl) {
    intervalEl.value = String(data.interval_seconds);
  }
  if (countdownEl) {
    if (status !== "RUNNING" || !data.next_draw_at) {
      countdownEl.textContent = "--:--";
    } else {
      const remainingMs = Math.max(0, new Date(data.next_draw_at).getTime() - Date.now());
      const seconds = Math.ceil(remainingMs / 1000);
      countdownEl.textContent = `00:${String(seconds).padStart(2, "0")}`;
    }
  }
  updateAdminActionButtons();
}

async function refreshAdminAutoDraw(gameId) {
  const gid = Number(gameId || state.admin?.selectedGameId || 0);
  if (!state.admin.enabled || !gid) return;
  const data = await apiFetch(`/mini-api/admin/games/${gid}/auto-draw`);
  state.admin.autoDrawByGame.set(gid, data || {});
  if (Number(state.admin?.selectedGameId || 0) === gid) renderAdminAutoDraw();
}

async function adminAutoDrawAction(action) {
  const { gid } = requireAdminGameStatus(["RUNNING"], "کنترل شماره‌خوان خودکار");
  const body = action === "start"
    ? { interval_seconds: Number(getVal("adminAutoDrawInterval") || 10) }
    : undefined;
  const actionText = { start: "شروع", pause: "توقف موقت", resume: "ادامه", stop: "پایان" }[action] || action;
  setAdminLocalHint("adminAutoDrawHint", `در حال ${actionText} شماره‌خوان...`);
  const out = await apiFetch(`/mini-api/admin/games/${gid}/auto-draw/${action}`, {
    method: "POST",
    ...(body ? { body } : {}),
  });
  state.admin.autoDrawByGame.set(gid, out?.auto_draw || {});
  renderAdminAutoDraw();
  setAdminLocalHint("adminAutoDrawHint", `${actionText} شماره‌خوان با موفقیت انجام شد.`, "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
}

async function adminCallNumber() {
  const { gid } = requireAdminGameStatus(["RUNNING"], "اعلام عدد");
  normalizeAdminCallNumberInput();

  const rawNumber = String(getVal("adminCallNumberInput") || "").trim();
  const number = Number(rawNumber || "0");

  if (!Number.isInteger(number) || number < 1 || number > 90) {
    focusAdminCallNumberInput();
    throw new Error("عدد اعلام باید بین 1 تا 90 باشد.");
  }

  if (getAdminCalledNumbersForSelectedGame(gid).includes(number)) {
    focusAdminCallNumberInput();
    throw new Error(`عدد ${number} قبلاً اعلام شده است.`);
  }

  setAdminLocalHint("adminCallActionHint", "در حال ثبت عدد...");
  if (!liveEventCursorKnown(gid)) {
    try {
      const currentSnap = await apiFetch(`/mini-api/games/${gid}/snapshot?events_limit=1`);
      markLiveEventCursor(gid, Number(currentSnap?.last_event_id || 0));
    } catch (_) {}
  }
  const previousCursor = getLiveEventCursor(gid);
  await apiFetch(`/mini-api/admin/games/${gid}/call`, {
    method: "POST",
    body: { number, idempotency_key: idem("mini_admin_call") },
  });

  addAdminCalledNumberLocal(gid, number);
  setVal("adminCallNumberInput", "");
  focusAdminCallNumberInput();
  renderAdminCallQuickPanel({ fresh: true });
  setAdminLocalHint("adminCallActionHint", `عدد ${number} برای بازی #${gid} ثبت شد.`, "success");
  await Promise.allSettled([
    refreshAdminGames(),
    openLiveGame(gid, { notifyFresh: true, notifyAfterId: previousCursor }),
    refreshCards({ silent: true }),
  ]);
}


async function adminUndoCall() {
  const { gid } = requireAdminGameStatus(["RUNNING"], "حذف آخرین عدد");
  const now = Date.now();
  if (!adminUndoConfirmUntil || adminUndoConfirmUntil < now) {
    adminUndoConfirmUntil = now + 5000;
    setAdminLocalHint("adminCallActionHint", "برای تایید حذف آخرین عدد، دوباره روی حذف بزن.", "pending");
    return;
  }
  adminUndoConfirmUntil = 0;
  setAdminLocalHint("adminCallActionHint", "در حال حذف آخرین عدد...");
  await apiFetch(`/mini-api/admin/games/${gid}/undo-last-call`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_undo") },
  });
  setAdminLocalHint("adminCallActionHint", "آخرین عدد بازی با موفقیت حذف شد.", "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid), refreshCards({ silent: true })]);
  popAdminCalledNumberLocal(gid);
  renderAdminCallQuickPanel();
}

async function adminCloseLobby() {
  const { gid } = requireAdminGameStatus(["LOBBY"], "لغو لابی");
  const reason = getVal("adminCancelReasonInput");
  if (!reason || reason.length < 3) throw new Error("علت لغو باید حداقل 3 کاراکتر باشد.");
  setAdminLocalHint("adminCloseLobbyHint", "در حال لغو بازی لابی...");
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
  setAdminLocalHint("adminCloseLobbyHint", hint, "success");
  await Promise.allSettled([refreshAdminGames(), refreshWallet(), refreshCards({ silent: true }), refreshAdminDeposits(), refreshAdminCryptoDeposits(), refreshAdminWithdraws()]);
}

async function adminSetLiveLink() {
  const gid = requireAdminSelectedGame();
  const url = getVal("adminLiveLinkInput");
  if (!url) throw new Error("لینک لایو را وارد کنید.");
  setAdminLocalHint("adminLiveActionHint", "در حال ثبت لینک لایو...");
  await apiFetch(`/mini-api/admin/games/${gid}/live-link`, {
    method: "PUT",
    body: { url },
  });
  state.admin.liveLinksByGame?.set(gid, String(url || "").trim());
  setAdminLocalHint("adminLiveActionHint", "لینک لایو بازی با موفقیت ثبت شد. اکنون می‌توانید آن را برای خریداران کارت ارسال کنید.", "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
  setAdminSelectedGame(gid, statusLabel(getAdminGameById(gid)?.status || ""));
  updateAdminActionButtons();
}
async function adminSendLiveLink() {
  const gid = requireAdminSelectedGame();
  const g = getAdminGameById(gid);
  const liveUrl = adminLiveLinkForGame(gid);
  if (!liveUrl) throw new Error("ابتدا لینک لایو را ثبت کنید.");
  setAdminLocalHint("adminLiveActionHint", "در حال ارسال لینک لایو به خریداران کارت...");
  const res = await apiFetch(`/mini-api/admin/games/${gid}/live-link/send`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_live_send") },
  });
  const participants = Number(res?.participants_count || 0);
  const okCount = Number(res?.notified_ok || 0);
  const failCount = Number(res?.notify_failed || 0);
  const noTgCount = Number(res?.no_tg_count || 0);
  const msg = `لینک لایو بازی #${gid} ارسال شد. خریداران: ${participants} | موفق: ${okCount} | ناموفق: ${failCount} | بدون شناسه: ${noTgCount}`;
  setAdminLocalHint("adminLiveActionHint", msg, okCount > 0 ? "success" : "error");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
}


async function adminClearLiveLink() {
  const gid = requireAdminSelectedGame();
  setAdminLocalHint("adminLiveActionHint", "در حال حذف لینک لایو...");
  await apiFetch(`/mini-api/admin/games/${gid}/live-link`, { method: "DELETE" });
  state.admin.liveLinksByGame?.delete(gid);
  setAdminLocalHint("adminLiveActionHint", "لینک لایو حذف شد.", "success");
  updateAdminActionButtons();
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
}

async function adminApproveDeposit(depositId, options = {}) {
  await apiFetch(`/mini-api/admin/deposits/${Number(depositId)}/approve`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_dep_approve") },
  });
  setAdminLocalHint("adminActionHint", `واریزی #${depositId} تایید شد.`, "success");
  if (options.closeReceipt) closeDepositReceiptModal();
  await Promise.allSettled([refreshAdminDeposits(), refreshWallet()]);
}

async function adminRejectDeposit(depositId, options = {}) {
  await apiFetch(`/mini-api/admin/deposits/${Number(depositId)}/reject`, { method: "POST" });
  setAdminLocalHint("adminActionHint", `واریزی #${depositId} رد شد.`, "success");
  if (options.closeReceipt) closeDepositReceiptModal();
  await refreshAdminDeposits();
}


async function adminRefreshWithdrawWallet(withdrawId) {
  const id = Number(withdrawId || 0);
  if (!id) throw new Error("شناسه برداشت نامعتبر است.");
  setAdminLocalHint("adminActionHint", "در حال بروزرسانی کیف پول...");
  const info = await apiFetch(`/mini-api/admin/withdraws/${id}/wallet-status`);
  setWithdrawWalletStatus(id, info);
  setAdminLocalHint(
    "adminActionHint",
    info?.can_approve ? "کیف پول بروزرسانی شد؛ تایید مجاز است." : "موجودی قابل تایید کافی نیست.",
    info?.can_approve ? "success" : "error"
  );
  return info;
}


async function adminApproveWithdraw(withdrawId) {
  const info = await adminRefreshWithdrawWallet(withdrawId);
  if (!info?.can_approve) throw new Error("موجودی قابل تایید برای این برداشت کافی نیست. درخواست را رد یا دوباره بررسی کنید.");
  await apiFetch(`/mini-api/admin/withdraws/${Number(withdrawId)}/approve`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_wdr_approve") },
  });
  setAdminLocalHint("adminActionHint", `برداشت #${withdrawId} تایید شد.`, "success");
  await Promise.allSettled([refreshAdminWithdraws(), refreshWallet()]);
}

async function adminRejectWithdraw(withdrawId) {
  await apiFetch(`/mini-api/admin/withdraws/${Number(withdrawId)}/reject`, {
    method: "POST",
    body: { reason: "رد توسط ادمین" },
  });
  setAdminLocalHint("adminActionHint", `برداشت #${withdrawId} رد شد.`, "success");
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

  try {
    await adminSaveWithdrawProof(id, proofText, file);
    const tracking = proofText || `image_receipt_${Date.now()}`;
    await apiFetch(`/mini-api/admin/withdraws/${id}/paid`, {
      method: "POST",
      body: { paid_tracking: tracking.slice(0, 128) },
    });

    setWithdrawProofHint("فیش پرداخت ثبت شد و برداشت پرداخت‌شده شد.", "success");
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
  setHint("superAdminHint", `نقش ${adminRoleLabel(role)} برای ${tgUserId} ثبت شد.`, "success");
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
  setHint("superAdminHint", `نقش ${adminRoleLabel(role)} از ${tgUserId} حذف شد.`, "success");
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


function configureDepositReceiptPicker() {
  const input = getEl("depositReceiptFileInput");
  const hint = getEl("depositReceiptPickerHint");
  const pickerLabel = document.querySelector(".receipt-picker-btn span");
  if (!input) return;

  const ua = String(navigator.userAgent || "").toLowerCase();
  const isMobileLike = /android|iphone|ipad|ipod|mobile/.test(ua) || Boolean(tg?.platform && String(tg.platform).toLowerCase() !== "tdesktop");

  if (isMobileLike) {
    input.setAttribute("accept", "image/*");
    // Do not set "capture": capture usually opens the camera. For receipt screenshots we want the gallery/file picker.
    if (hint) hint.textContent = "اسکرین‌شات رسید را از گالری انتخاب کن. عکس واضح و خوانا باشد.";
    if (pickerLabel) pickerLabel.textContent = "انتخاب عکس رسید از گالری";
  } else {
    input.setAttribute("accept", "image/*,.pdf");
    if (hint) hint.textContent = "در لپ‌تاپ، عکس رسید یا PDF پرداخت را انتخاب کن.";
    if (pickerLabel) pickerLabel.textContent = "انتخاب رسید از فایل";
  }
}

function wireWalletUxHelpers() {
  configureDepositReceiptPicker();
  document.querySelectorAll(".deposit-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      setDepositMode(btn.getAttribute("data-deposit-mode") || "bank");
      triggerLightHaptic("success");
    });
  });

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

  document.querySelectorAll(".crypto-amount-preset").forEach((btn) => {
    btn.addEventListener("click", () => {
      const amount = Number(btn.getAttribute("data-amount") || "0");
      if (!amount) return;
      setVal("cryptoAmountInput", String(amount));
      document.querySelectorAll(".crypto-amount-preset").forEach((b) => b.classList.remove("is-selected"));
      btn.classList.add("is-selected");
      setHint("cryptoSubmitHint", `مبلغ شارژ روی ${toman(amount)} تنظیم شد.`, "success");
      triggerLightHaptic("success");
    });
  });

  document.querySelectorAll(".crypto-network-option").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      selectCryptoNetwork(button.getAttribute("data-network") || "");
    });
  });

  getEl("cryptoAmountInput")?.addEventListener("input", () => {
    const current = parsePositiveInt(getVal("cryptoAmountInput"));
    document.querySelectorAll(".crypto-amount-preset").forEach((button) => {
      button.classList.toggle(
        "is-selected",
        Number(button.getAttribute("data-amount") || 0) === current
      );
    });
  });

  getEl("resumeCryptoInvoiceBtn")?.addEventListener("click", () => {
    const id = Number(state.cryptoCurrentInvoice?.id || 0);
    if (!id) return;
    refreshCryptoInvoice(id, { open: true }).catch((e) => setLocalError("cryptoSubmitHint", e));
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
        box.innerHTML = `<strong>رسید انتخاب شد</strong><div>${name} — ${safeText(sizeKb)} KB</div><img src="${state.receiptPreviewUrl}" alt="پیش‌نمایش رسید" /><small>اگر مبلغ، تاریخ یا شماره پیگیری خوانا نیست، عکس واضح‌تری انتخاب کن.</small>`;
      } else {
        box.innerHTML = `<strong>فایل رسید انتخاب شد</strong><div>${name} — ${safeText(sizeKb)} KB</div><small>اگر فایل PDF است، مطمئن شو مبلغ و شماره پیگیری داخل آن مشخص است.</small>`;
      }
      setHint("depositSubmitHint", "رسید انتخاب شد. ثبت واریزی را بزن. اگر رسید پیوست نشد، ادمین با موجودی همراه‌بانک بررسی می‌کند.", "success");
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
  loadNotificationReadIds();
  updateNotificationBadge();
  updateBuyActionState({ statusKey: "", myCardsCount: 0 });
  renderLiveLink({});
  const copyBtn = getEl("copyDepositCardBtn");
  if (copyBtn) copyBtn.disabled = true;

  bind("soundBtn", "click", toggleSound);
  bind("notificationsBtn", "click", openNotificationCenter);
  bind("notificationCloseBtn", "click", closeNotificationCenter);
  bind("notificationMarkAllBtn", "click", markAllNotificationsRead);
  bind("notificationRefreshBtn", "click", () => refreshNotifications({ silent: false }).catch((e) => showToast(localizeApiError(e?.message || e), "error")));
  bind("refreshGamesBtn", "click", () => runManualRefresh("refreshGamesBtn", () => refreshGames()).catch(() => {}));
  bind("refreshCardsBtn", "click", () => runManualRefresh("refreshCardsBtn", () => refreshCards({ silent: false })).catch(() => {}));
  bind("refreshWalletBtn", "click", () => runManualRefresh("refreshWalletBtn", () => refreshWallet()).catch(() => {}));
  bind("buyCardsBtn", "click", () => buySelectedGame().catch((e) => setLocalError("buyStatusHint", e)));
  bind("submitDepositBtn", "click", () => submitDepositWithReceipt().catch((e) => setLocalError("depositSubmitHint", e)));
  bind("createCryptoInvoiceBtn", "click", () => createCryptoInvoice().catch((e) => setLocalError("cryptoSubmitHint", e)));
  bind("depositDestinationSelect", "change", renderDepositDestinationHint);
  bind("copyDepositCardBtn", "click", () => copySelectedDepositCard().catch((e) => setLocalError("depositDestinationHint", e)));
  bind("submitWithdrawBtn", "click", () => createWithdraw().catch((e) => setLocalError("withdrawSubmitHint", e)));
  bind("refreshAdminBtn", "click", () => runManualRefresh("refreshAdminBtn", () => refreshAdminPanel()).catch(() => {}));
  bind("adminOpsRefreshBtn", "click", () => runManualRefresh("adminOpsRefreshBtn", () => refreshAdminPanel()).catch(() => {}));
  bind("adminUsersSearchBtn", "click", () => adminUsersSearch().catch((e) => setLocalError("adminUsersHint", e)));
  bind("adminUsersRefreshBtn", "click", () => adminUsersRefreshSelected().catch((e) => setLocalError("adminUsersHint", e)));
  bind("adminUsersSearchInput", "keydown", (ev) => {
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    adminUsersSearch().catch((e) => setLocalError("adminUsersHint", e));
  });
  bind("adminCreateBtn", "click", () =>
    adminCreateGame().catch((e) => {
      setHint("adminCreateHintMsg", String(e.message || ""), "error");
    })
  );
  bind("adminCallBtn", "click", () => adminCallNumber().catch((e) => setAdminLocalError("adminCallActionHint", e)));
  bind("adminUndoBtn", "click", () => adminUndoCall().catch((e) => setAdminLocalError("adminCallActionHint", e)));
  bind("adminAutoDrawStartBtn", "click", () => adminAutoDrawAction("start").catch((e) => setAdminLocalError("adminAutoDrawHint", e)));
  bind("adminAutoDrawPauseBtn", "click", () => adminAutoDrawAction("pause").catch((e) => setAdminLocalError("adminAutoDrawHint", e)));
  bind("adminAutoDrawResumeBtn", "click", () => adminAutoDrawAction("resume").catch((e) => setAdminLocalError("adminAutoDrawHint", e)));
  bind("adminAutoDrawStopBtn", "click", () => adminAutoDrawAction("stop").catch((e) => setAdminLocalError("adminAutoDrawHint", e)));
  const adminCallInput = getEl("adminCallNumberInput");
  if (adminCallInput && !adminCallInput.dataset.phase1UxBound) {
    adminCallInput.dataset.phase1UxBound = "1";
    adminCallInput.addEventListener("input", normalizeAdminCallNumberInput);
    adminCallInput.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      adminCallNumber().catch((e) => setAdminLocalError("adminCallActionHint", e));
    });
  }
  bindAdminCallKeypad();
  renderAdminCallQuickPanel();
  bind("adminStartBtn", "click", () => adminStartGame().catch((e) => setAdminLocalError("adminCallActionHint", e)));
  bind("adminCloseLobbyBtn", "click", () => adminCloseLobby().catch((e) => setAdminLocalError("adminCloseLobbyHint", e)));
  bind("adminSetLiveBtn", "click", () => adminSetLiveLink().catch((e) => setAdminLocalError("adminLiveActionHint", e)));
  bind("adminSendLiveBtn", "click", () => adminSendLiveLink().catch((e) => setAdminLocalError("adminLiveActionHint", e)));
  bind("adminClearLiveBtn", "click", () => adminClearLiveLink().catch((e) => setAdminLocalError("adminLiveActionHint", e)));
  bind("superAdminGrantBtn", "click", () => superAdminGrant().catch((e) => setLocalError("superAdminHint", e)));
  bind("superAdminRevokeBtn", "click", () => superAdminRevoke().catch((e) => setLocalError("superAdminHint", e)));
  bind("superCryptoToggleBtn", "click", () => toggleSuperCryptoSettings().catch((e) => setLocalError("superCryptoHint", e)));
  bind("superBankDepositToggleBtn", "click", () => toggleSuperBankDepositSettings().catch((e) => setLocalError("superBankDepositHint", e)));
  bind("superCryptoHealthBtn", "click", () => checkSuperCryptoHealth().catch((e) => setLocalError("superCryptoHint", e)));
  bind("superCryptoReconcileBtn", "click", () => checkSuperCryptoReconciliation().catch((e) => setLocalError("superCryptoHint", e)));
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
  bind("depositReceiptCloseBtn", "click", closeDepositReceiptModal);
  bind("receiptModalCloseBtn", "click", closeReceiptModal);
  const depositReceiptModal = getEl("depositReceiptModal");
  if (depositReceiptModal) {
    depositReceiptModal.addEventListener("click", (e) => {
      if (e.target === depositReceiptModal) closeDepositReceiptModal();
    });
  }
  const receiptModal = getEl("receiptModal");
  if (receiptModal) {
    receiptModal.addEventListener("click", (e) => {
      if (e.target === receiptModal) closeReceiptModal();
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

  startMiniSocket();
  setSplashStatus("در حال دریافت بازی‌ها و کیف پول...");
  loadAdminNotifySeen();
  await refreshAdminBootstrap();
  await Promise.allSettled([refreshGames(), refreshCards({ silent: false }), refreshWallet()]);
  if (state.admin.enabled) {
    checkAdminFinanceNotifications({ silent: false }).catch(() => {});
  }
  startGlobalRefresh();
  setInterval(() => renderAdminAutoDraw(), 1000);

  const current = document.querySelector(".nav-btn.active")?.getAttribute("data-view") || "games";
  switchToView(current);
  setSplashStatus("آماده بازی هستید");
  setTimeout(hideSplash, 260);
}


window.addEventListener("beforeunload", () => {
  stopCryptoCountdown();
  clearCryptoQrObjectUrl();
  stopMiniSocket();
  stopEventPolling();
  stopCardsPolling();
  stopGlobalRefresh();
});
boot().catch((err) => {
  setBadge("error", String(err.message || "خطای داخلی"));
  setSplashStatus("خطا در آماده‌سازی. لطفاً دوباره تلاش کنید.");
  setTimeout(hideSplash, 900);
});


try {
  startWalletLiveRefresh();
} catch (err) {
  console.warn("startWalletLiveRefresh failed:", err);
}
