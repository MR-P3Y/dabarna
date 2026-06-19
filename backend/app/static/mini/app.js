const tg = window.Telegram?.WebApp;

const state = {
  token: null,
  tokenExp: 0,
  authReady: false,
  selectedGameId: null,
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
    users: {
      selectedTgUserId: 0,
      lastQuery: "",
      reportMode: "none",
      profile: null,
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
  LOBBY: "\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0634\u0631\u0648\u0639",
  RUNNING: "\u062f\u0631 \u062d\u0627\u0644 \u0627\u062c\u0631\u0627",
  ENDED: "\u067e\u0627\u06cc\u0627\u0646\u200c\u06cc\u0627\u0641\u062a\u0647",
  CANCELLED: "\u0644\u063a\u0648 \u0634\u062f\u0647",
  ACTIVE: "\u0641\u0639\u0627\u0644",
  PENDING: "\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631",
  APPROVED: "\u062a\u0627\u06cc\u06cc\u062f \u0634\u062f\u0647",
  REJECTED: "\u0631\u062f \u0634\u062f\u0647",
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
  GAME_CREATED: "\u0627\u06cc\u062c\u0627\u062f \u0628\u0627\u0632\u06cc",
  GAME_STARTED: "\u0634\u0631\u0648\u0639 \u0628\u0627\u0632\u06cc",
  GAME_ENDED: "\u067e\u0627\u06cc\u0627\u0646 \u0628\u0627\u0632\u06cc",
  GAME_CANCELLED: "\u0644\u063a\u0648 \u0628\u0627\u0632\u06cc",
  GAME_LOBBY_CLOSED: "\u0628\u0633\u062a\u0647 \u0634\u062f\u0646 \u0644\u0627\u0628\u06cc",
  NUMBER_CALLED: "\u0627\u0639\u0644\u0627\u0645 \u0639\u062f\u062f",
  NUMBER_UNDONE: "\u062d\u0630\u0641 \u0622\u062e\u0631\u06cc\u0646 \u0639\u062f\u062f",
  CARDS_PURCHASED: "\u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a",
  CARD_BOUGHT: "\u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a",
  PRIZE_COL: "برد ستونی(تورنا)",
  PRIZE_ROW: "برد سطری(تمام)",
  CLAIM_SUBMITTED: "\u062b\u0628\u062a \u0627\u062f\u0639\u0627",
  CLAIM_APPROVED: "\u062a\u0627\u06cc\u06cc\u062f \u0627\u062f\u0639\u0627",
  CLAIM_REJECTED: "\u0631\u062f \u0627\u062f\u0639\u0627",
  WINNER_DECLARED: "\u0627\u0639\u0644\u0627\u0645 \u0628\u0631\u0646\u062f\u0647",
};

const ACTIVE_GAME_STATUSES = new Set(["LOBBY", "RUNNING"]);
const CARDS_REFRESH_INTERVAL_MS = 2200;
const GLOBAL_REFRESH_INTERVAL_MS = 12000;
const HISTORY_LIST_LIMIT = 15;
const CARD_HISTORY_LIMIT = 10;
const LIVE_EVENTS_LIMIT = 15;

const UI_TEXT = {
  brandTitle: "\u062f\u0648\u0631\u0646\u0627\u06cc \u067e\u06cc\u0645\u0648\u0646",
  headerUserLabel: "\u06a9\u0627\u0631\u0628\u0631",
  headerWalletMiniLabel: "\u06a9\u06cc\u0641 \u067e\u0648\u0644",
  gamesTitle: "\u0628\u0627\u0632\u06cc\u200c\u0647\u0627",
  refreshGamesBtn: "\u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc",
  gamesHint:
    "\u0648\u0631\u0648\u062f \u0633\u0631\u06cc\u0639 \u0628\u0647 \u0628\u0627\u0632\u06cc\u200c\u0647\u0627\u06cc \u0641\u0639\u0627\u0644\u060c \u0645\u0634\u0627\u0647\u062f\u0647 \u0622\u0645\u0627\u0631 \u0632\u0646\u062f\u0647 \u0648 \u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a.",
  gamesGuideText:
    "\u0628\u0627\u0632\u06cc \u0641\u0639\u0627\u0644 \u0631\u0627 \u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646\u06cc\u062f\u060c \u0648\u0627\u0631\u062f \u0648\u0636\u0639\u06cc\u062a \u0632\u0646\u062f\u0647 \u0634\u0648\u06cc\u062f \u0648 \u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a \u0631\u0627 \u0627\u0646\u062c\u0627\u0645 \u062f\u0647\u06cc\u062f.",
  recentStatsTitle: "\u0622\u0645\u0627\u0631 \u06f5 \u0628\u0627\u0632\u06cc \u0627\u062e\u06cc\u0631",
  trustPanelTitle: "\u0633\u06cc\u0633\u062a\u0645 \u0627\u0639\u062a\u0645\u0627\u062f",
  liveTitle: "\u0648\u0636\u0639\u06cc\u062a \u0632\u0646\u062f\u0647 \u0628\u0627\u0632\u06cc",
  buyQtyLabel: "\u062a\u0639\u062f\u0627\u062f \u06a9\u0627\u0631\u062a",
  buyCardsBtn: "\u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a",
  cardsTitle: "\u06a9\u0627\u0631\u062a\u200c\u0647\u0627\u06cc \u0645\u0646",
  refreshCardsBtn: "\u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc",
  cardsHint:
    "\u06a9\u0627\u0631\u062a\u200c\u0647\u0627\u06cc \u0628\u0627\u0632\u06cc \u0641\u0639\u0627\u0644 \u0628\u0627 \u0647\u0627\u06cc\u0644\u0627\u06cc\u062a \u0639\u062f\u062f\u0647\u0627\u06cc \u062e\u0648\u0627\u0646\u062f\u0647\u200c\u0634\u062f\u0647 \u0646\u0645\u0627\u06cc\u0634 \u062f\u0627\u062f\u0647 \u0645\u06cc\u200c\u0634\u0648\u0646\u062f.",
  cardsGuideText:
    "\u06a9\u0627\u0631\u062a\u200c\u0647\u0627\u06cc \u062e\u0631\u06cc\u062f\u0627\u0631\u06cc\u200c\u0634\u062f\u0647\u060c \u0627\u0639\u062f\u0627\u062f \u062e\u0648\u0627\u0646\u062f\u0647\u200c\u0634\u062f\u0647 \u0648 \u062a\u0627\u0631\u06cc\u062e\u0686\u0647 \u0628\u0631\u062f \u0631\u0627 \u0627\u06cc\u0646\u062c\u0627 \u0628\u0628\u06cc\u0646\u06cc\u062f.",
  cardsActiveTitle: "\u06a9\u0627\u0631\u062a\u200c\u0647\u0627\u06cc \u062e\u0631\u06cc\u062f\u0627\u0631\u06cc\u200c\u0634\u062f\u0647 \u0628\u0627\u0632\u06cc\u200c\u0647\u0627\u06cc \u0641\u0639\u0627\u0644",
  cardsHistoryTitle: "\u062a\u0627\u0631\u06cc\u062e\u0686\u0647 \u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a (\u06f1\u06f0 \u0645\u0648\u0631\u062f \u0622\u062e\u0631)",
  cardsHistoryMeta: "\u0627\u0633\u06a9\u0631\u0648\u0644\u200c\u067e\u0630\u06cc\u0631",
  cardsWinsTitle: "\u062a\u0627\u06cc\u0645\u200c\u0644\u0627\u06cc\u0646 \u0628\u0631\u062f\u0647\u0627",
  walletTitle: "\u06a9\u06cc\u0641 \u067e\u0648\u0644",
  refreshWalletBtn: "\u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc",
  walletGuideText:
    "\u0628\u0631\u0627\u06cc \u0648\u0627\u0631\u06cc\u0632 \u06cc\u0627 \u0628\u0631\u062f\u0627\u0634\u062a\u060c \u0645\u0631\u0627\u062d\u0644 \u0631\u0627 \u0628\u0647 \u062a\u0631\u062a\u06cc\u0628 \u0627\u0646\u062c\u0627\u0645 \u062f\u0647\u06cc\u062f \u0648 \u0648\u0636\u0639\u06cc\u062a \u062f\u0631\u062e\u0648\u0627\u0633\u062a\u200c\u0647\u0627 \u0631\u0627 \u067e\u06cc\u06af\u06cc\u0631\u06cc \u06a9\u0646\u06cc\u062f.",
  walletBalanceLabel: "\u0645\u0648\u062c\u0648\u062f\u06cc \u0641\u0639\u0644\u06cc",
  depositFlowTitle: "\u0648\u0627\u0631\u06cc\u0632 \u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644",
  depositFlowDesc:
    "\u06f1) \u0645\u0628\u0644\u063a \u062f\u0644\u062e\u0648\u0627\u0647 \u062a\u0648\u0645\u0627\u0646 \u0648\u0627\u0631\u062f \u06a9\u0646\u06cc\u062f. \u06f2) \u06a9\u0627\u0631\u062a \u0645\u0642\u0635\u062f \u0631\u0627 \u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646\u06cc\u062f. \u06f3) \u0631\u0633\u06cc\u062f \u0631\u0627 \u0622\u067e\u0644\u0648\u062f \u06a9\u0646\u06cc\u062f. \u06f4) \u062b\u0628\u062a \u0646\u0647\u0627\u06cc\u06cc.",
  depositAmountLabel: "\u0645\u0628\u0644\u063a \u0648\u0627\u0631\u06cc\u0632 (\u062a\u0648\u0645\u0627\u0646)",
  depositDestinationLabel: "\u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0627\u0631\u062a \u0645\u0639\u0631\u0641\u06cc\u200c\u0634\u062f\u0647",
  copyDepositCardBtn: "\u06a9\u067e\u06cc \u0634\u0645\u0627\u0631\u0647 \u06a9\u0627\u0631\u062a",
  depositReceiptLabel: "\u0622\u067e\u0644\u0648\u062f \u0631\u0633\u06cc\u062f",
  depositSubmitLabel: "\u062b\u0628\u062a \u0648\u0627\u0631\u06cc\u0632\u06cc",
  submitDepositBtn: "\u062b\u0628\u062a \u0648\u0627\u0631\u06cc\u0632\u06cc",
  withdrawFlowTitle: "\u0628\u0631\u062f\u0627\u0634\u062a \u0627\u0632 \u06a9\u06cc\u0641 \u067e\u0648\u0644",
  withdrawFlowDesc:
    "\u06f1) \u0645\u0628\u0644\u063a \u06f2) \u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0645\u0642\u0635\u062f \u06f3) \u0628\u0627\u0632\u0628\u06cc\u0646\u06cc \u06f4) \u062b\u0628\u062a \u0646\u0647\u0627\u06cc\u06cc",
  withdrawLabel: "\u0645\u0628\u0644\u063a \u0628\u0631\u062f\u0627\u0634\u062a (\u062a\u0648\u0645\u0627\u0646)",
  withdrawTargetLabel: "\u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0645\u0642\u0635\u062f \u0628\u0631\u062f\u0627\u0634\u062a",
  withdrawFullNameLabel: "\u0646\u0627\u0645 \u0648 \u0646\u0627\u0645 \u062e\u0627\u0646\u0648\u0627\u062f\u06af\u06cc",
  withdrawCardLabel: "\u0634\u0645\u0627\u0631\u0647 \u06a9\u0627\u0631\u062a",
  withdrawIbanLabel: "\u0634\u0628\u0627 (\u0627\u062e\u062a\u06cc\u0627\u0631\u06cc)",
  withdrawAccountLabel: "\u0634\u0645\u0627\u0631\u0647 \u062d\u0633\u0627\u0628 (\u0627\u062e\u062a\u06cc\u0627\u0631\u06cc)",
  withdrawReviewLabel: "\u0628\u0627\u0632\u0628\u06cc\u0646\u06cc \u0627\u0637\u0644\u0627\u0639\u0627\u062a",
  withdrawSubmitLabel: "\u062b\u0628\u062a \u0646\u0647\u0627\u06cc\u06cc \u0628\u0631\u062f\u0627\u0634\u062a",
  submitWithdrawBtn: "\u062b\u0628\u062a \u0628\u0631\u062f\u0627\u0634\u062a",
  depositRequestsTitle: "\u062f\u0631\u062e\u0648\u0627\u0633\u062a\u200c\u0647\u0627\u06cc \u0648\u0627\u0631\u06cc\u0632",
  withdrawRequestsTitle: "\u062f\u0631\u062e\u0648\u0627\u0633\u062a\u200c\u0647\u0627\u06cc \u0628\u0631\u062f\u0627\u0634\u062a",
  navGamesText: "\u0628\u0627\u0632\u06cc",
  navCardsText: "\u06a9\u0627\u0631\u062a\u200c\u0647\u0627\u06cc \u0645\u0646",
  navWalletText: "\u06a9\u06cc\u0641 \u067e\u0648\u0644",
  navAdminText: "\u0645\u062f\u06cc\u0631\u06cc\u062a",
  adminTitle: "\u067e\u0646\u0644 \u0645\u062f\u06cc\u0631\u06cc\u062a",
  adminGuideText:
    "\u0627\u06cc\u062c\u0627\u062f \u0628\u0627\u0632\u06cc\u060c \u0645\u062f\u06cc\u0631\u06cc\u062a \u0639\u0645\u0644\u06cc\u0627\u062a \u0648 \u0628\u0631\u0631\u0633\u06cc \u0648\u0627\u0631\u06cc\u0632/\u0628\u0631\u062f\u0627\u0634\u062a \u0627\u0632 \u0647\u0645\u06cc\u0646 \u0628\u062e\u0634 \u0627\u0646\u062c\u0627\u0645 \u0645\u06cc\u200c\u0634\u0648\u062f.",
  adminCreateTitle: "\u0627\u06cc\u062c\u0627\u062f \u0628\u0627\u0632\u06cc \u062c\u062f\u06cc\u062f",
  adminCreateHint: "\u0628\u0627 \u0627\u0646\u062a\u062e\u0627\u0628 \u062a\u0627\u067e\u06cc\u06a9 \u0648 \u0642\u06cc\u0645\u062a \u06a9\u0627\u0631\u062a\u060c \u0628\u0627\u0632\u06cc \u062c\u062f\u06cc\u062f \u0628\u0633\u0627\u0632\u06cc\u062f.",
  adminCreateGroupLabel: "\u0634\u0646\u0627\u0633\u0647 \u06af\u0631\u0648\u0647",
  adminCreateTopicLabel: "\u062a\u0627\u067e\u06cc\u06a9 \u0628\u0627\u0632\u06cc",
  adminCreatePriceLabel: "\u0642\u06cc\u0645\u062a \u06a9\u0627\u0631\u062a (\u062a\u0648\u0645\u0627\u0646)",
  adminCreateBtn: "\u0627\u06cc\u062c\u0627\u062f \u0628\u0627\u0632\u06cc \u0633\u0641\u0627\u0631\u0634\u06cc",
  adminGamesTitle: "\u0628\u0627\u0632\u06cc\u200c\u0647\u0627\u06cc \u0642\u0627\u0628\u0644 \u0645\u062f\u06cc\u0631\u06cc\u062a",
  adminActionsTitle: "\u0639\u0645\u0644\u06cc\u0627\u062a \u0628\u0627\u0632\u06cc",
  adminCallLabel: "\u0639\u062f\u062f \u0628\u0631\u0627\u06cc \u0627\u0639\u0644\u0627\u0645",
  adminUndoBtn: "\u062d\u0630\u0641 \u0622\u062e\u0631\u06cc\u0646 \u0639\u062f\u062f",
  adminStartBtn: "\u0634\u0631\u0648\u0639 \u0628\u0627\u0632\u06cc",
  adminCancelReasonLabel: "\u0639\u0644\u062a \u0644\u063a\u0648 \u0644\u0627\u0628\u06cc",
  adminCloseLobbyBtn: "\u0644\u063a\u0648 \u0628\u0627\u0632\u06cc \u0642\u0628\u0644 \u0627\u0632 \u0634\u0631\u0648\u0639",
  adminLiveLinkLabel: "\u0644\u06cc\u0646\u06a9 \u067e\u062e\u0634 \u0632\u0646\u062f\u0647",
  adminSetLiveBtn: "\u062b\u0628\u062a \u0644\u06cc\u0646\u06a9 \u0644\u0627\u06cc\u0648",
  adminClearLiveBtn: "\u062d\u0630\u0641 \u0644\u06cc\u0646\u06a9 \u0644\u0627\u06cc\u0648",
  adminDepositsTitle: "\u0648\u0627\u0631\u06cc\u0632\u0647\u0627\u06cc \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631",
  adminWithdrawsTitle: "\u0628\u0631\u062f\u0627\u0634\u062a\u200c\u0647\u0627\u06cc \u0645\u062f\u06cc\u0631\u06cc\u062a\u06cc",
  adminUsersTitle: "\u0645\u062f\u06cc\u0631\u06cc\u062a \u06a9\u0627\u0631\u0628\u0631\u0627\u0646",
  adminUsersSearchLabel: "\u062c\u0633\u062a\u062c\u0648 (\u0634\u0646\u0627\u0633\u0647 \u062a\u0644\u06af\u0631\u0627\u0645 / \u06cc\u0648\u0632\u0631\u0646\u06cc\u0645 / gid / dep / wdr)",
  adminUsersSearchBtn: "\u062c\u0633\u062a\u062c\u0648",
  adminUsersRefreshBtn: "\u0628\u0627\u0632\u062e\u0648\u0627\u0646\u06cc \u06a9\u0627\u0631\u0628\u0631 \u0627\u0646\u062a\u062e\u0627\u0628\u06cc",
  superAdminTitle: "\u0645\u062f\u06cc\u0631\u06cc\u062a \u0627\u062f\u0645\u06cc\u0646\u200c\u0647\u0627 (\u0633\u0648\u067e\u0631 \u0627\u062f\u0645\u06cc\u0646)",
  superAdminUserLabel: "\u0634\u0646\u0627\u0633\u0647 \u062a\u0644\u06af\u0631\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631",
  superAdminRoleLabel: "\u0646\u0642\u0634",
  winnerModalTitle: "\u062a\u0628\u0631\u06cc\u06a9\u060c \u0634\u0645\u0627 \u0628\u0631\u0646\u062f\u0647 \u0634\u062f\u06cc\u062f",
  winnerWalletBtn: "\u0645\u0634\u0627\u0647\u062f\u0647 \u062f\u0631 \u06a9\u06cc\u0641 \u067e\u0648\u0644",
  winnerDismissBtn: "\u0628\u0633\u062a\u0646",
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

function inferDisplayName() {
  const tgUser = tg?.initDataUnsafe?.user;
  const username = String(tgUser?.username || "").trim();
  if (username) return `@${username}`;
  const fn = String(tgUser?.first_name || "").trim();
  const ln = String(tgUser?.last_name || "").trim();
  const full = `${fn} ${ln}`.trim();
  if (full) return full;
  return "کاربر دورنا";
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
  BUY_CARDS: "\u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a",
  PRIZE_COL: "برد ستونی(تورنا)",
  PRIZE_ROW: "برد سطری(تمام)",
  DEPOSIT_APPROVED: "\u062a\u0627\u06cc\u06cc\u062f \u0648\u0627\u0631\u06cc\u0632",
  WITHDRAW_APPROVED: "\u062a\u0627\u06cc\u06cc\u062f \u0628\u0631\u062f\u0627\u0634\u062a",
  WITHDRAW_REJECTED: "\u0631\u062f \u0628\u0631\u062f\u0627\u0634\u062a",
  GAME_CANCEL_REFUND: "\u0628\u0631\u06af\u0634\u062a \u0648\u062c\u0647 \u0644\u063a\u0648 \u0628\u0627\u0632\u06cc",
  REFUND_GAME_CANCELLED: "\u0628\u0631\u06af\u0634\u062a \u0648\u062c\u0647 \u0644\u063a\u0648 \u0628\u0627\u0632\u06cc",
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
  "Ú©Ø§Ù…Ù„": "برد سطری(تمام)",
  "ØªÙˆØ±Ù†Ø§": "برد ستونی(تورنا)",
  "Ø®Ø·ÛŒ": "خطی",
  "Ù†Ø§Ù…Ø´Ø®Øµ": "نامشخص",
};

function normalizeWinPatternLabel(raw) {
  const val = String(raw || "").trim();
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
      <div class="destination-selected-number" dir="ltr">${safeText(card)}</div>
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
    setHint("depositDestinationHint", `شماره کارت ${prettyCardNumber(rawCard)} کپی شد.`, "success");
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
      hotBanner.classList.remove("hidden");
      hotBanner.textContent = `🔥 بازی داغ: بازی #${hotId} در حال جذب بازیکن است`;
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
      const hot = Number(state.hotGameId || 0) === gid;
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
        ${hot ? '<div class="winner-kind-pill">🔥 بازی داغ است</div>' : ""}
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
  const amountPart = amount > 0 ? ` | \u0645\u0628\u0644\u063a: ${toman(amount)}` : "";
  const gamePart = gid > 0 ? ` \u062f\u0631 \u0628\u0627\u0632\u06cc #${gid}` : "";
  return `\u062a\u0628\u0631\u06cc\u06a9! ${kindLabel}${gamePart}${amountPart}`;
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
  if (kindEl) kindEl.textContent = `نوع برد: ${info.kindLabel}`;
  if (amountEl) amountEl.textContent = info.amount > 0 ? toman(info.amount) : "-";
  if (gameEl) gameEl.textContent = info.gameId > 0 ? `بازی #${info.gameId}` : "";
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  try {
    tg?.HapticFeedback?.notificationOccurred?.("success");
    tg?.HapticFeedback?.impactOccurred?.("medium");
  } catch (_) {}
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
      <strong>\u062a\u0628\u0631\u06cc\u06a9! \u0634\u0645\u0627 \u0628\u0631\u0646\u062f\u0647 \u0627\u06cc\u0646 \u0628\u0627\u0632\u06cc \u0634\u062f\u06cc\u062f</strong>
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
  const nearest = st?.nearest_to_win || {};
  const nearestText = Number(nearest?.percent || 0) > 0
    ? `${nearest.percent}% | ${nearest.missing} عدد مانده`
    : "-";
  root.innerHTML = `
    <div class="live-insight">
      <div class="k">بازیکنان باقی‌مانده</div>
      <div class="v">${safeText(remain)}</div>
    </div>
    <div class="live-insight">
      <div class="k">نزدیک‌ترین کارت به برد</div>
      <div class="v">${safeText(nearestText)}</div>
    </div>
    <div class="live-insight">
      <div class="k">درصد پیشرفت بازی</div>
      <div class="v">${safeText(st?.called_progress_pct || 0)}%</div>
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
    meta.textContent = updated ? `آخرین بروزرسانی: ${updated}` : "لینک لایو توسط مدیریت ثبت شده است.";
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
            <div>${safeText(String(e.created_at || ""))}</div>
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
  const tailNumbers = called.slice(-28);
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
    <div class="live-main">
      <div class="live-top">
        <div>
          <div>وضعیت: <strong>${safeText(statusLabel(st.status || game.status))}</strong></div>
          <div>مجموع جایزه: <strong>${toman(st.prize_pool ?? game.prize_pool)}</strong></div>
          <div class="meta">اعداد اعلام‌شده: ${safeText(st.called_count || called.length)}</div>
        </div>
        <div class="${lastNumberClass}">${safeText(lastNow ?? "-")}</div>
      </div>
      <div class="live-called-grid">${calledGrid}</div>
    </div>
  `;

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
      const winnerText = mine ? '<div class="winner-note">\u062a\u0628\u0631\u06cc\u06a9! \u0627\u06cc\u0646 \u0628\u0631\u062f \u0628\u0631\u0627\u06cc \u0634\u0645\u0627 \u062b\u0628\u062a \u0634\u062f.</div>' : "";
      return `
      <div class="${chipClass}">
        <strong>${safeText(eventKindLabel(e.kind))}</strong>
        <div>${safeText(String(e.created_at || ""))}</div>
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
          try { tg?.HapticFeedback?.impactOccurred?.("light"); } catch (_) {}
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
    state.hotGameId = Number(insights?.hot_game_id || 0) || null;
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
    cardsTitle: "\u06a9\u0627\u0631\u062a\u200c\u0647\u0627\u06cc \u0645\u0646",
    refreshCardsBtn: "\u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc",
    cardsHint:
      "\u06a9\u0627\u0631\u062a\u200c\u0647\u0627\u06cc \u0628\u0627\u0632\u06cc\u200c\u0647\u0627\u06cc \u0641\u0639\u0627\u0644 \u0628\u0647 \u0635\u0648\u0631\u062a \u0632\u0646\u062f\u0647 \u0647\u0627\u06cc\u0644\u0627\u06cc\u062a \u0645\u06cc\u200c\u0634\u0648\u0646\u062f \u0648 \u06f1\u06f0 \u062e\u0631\u06cc\u062f \u0622\u062e\u0631 \u062f\u0631 \u062a\u0627\u0631\u06cc\u062e\u0686\u0647 \u0646\u0645\u0627\u06cc\u0634 \u062f\u0627\u062f\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f.",
    cardsPullHint: "\u0628\u0631\u0627\u06cc \u0646\u0648\u0633\u0627\u0632\u06cc\u060c \u0635\u0641\u062d\u0647 \u0631\u0627 \u06a9\u0645\u06cc \u0628\u0647 \u067e\u0627\u06cc\u06cc\u0646 \u0628\u06a9\u0634\u06cc\u062f.",
    cardsLiveStatus: "\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0628\u0627\u0632\u06cc \u0641\u0639\u0627\u0644",
    cardsActiveTitle: "\u06a9\u0627\u0631\u062a\u200c\u0647\u0627\u06cc \u062e\u0631\u06cc\u062f\u0627\u0631\u06cc\u200c\u0634\u062f\u0647 \u0628\u0627\u0632\u06cc\u200c\u0647\u0627\u06cc \u0641\u0639\u0627\u0644",
    cardsHistoryTitle: "\u062a\u0627\u0631\u06cc\u062e\u0686\u0647 \u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a (\u06f1\u06f0 \u0645\u0648\u0631\u062f \u0622\u062e\u0631)",
    cardsHistoryMeta: "\u0627\u0633\u06a9\u0631\u0648\u0644\u200c\u067e\u0630\u06cc\u0631",
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
  hint.textContent = "\u0628\u0631\u0627\u06cc \u0646\u0648\u0633\u0627\u0632\u06cc\u060c \u0635\u0641\u062d\u0647 \u0631\u0627 \u06a9\u0645\u06cc \u0628\u0647 \u067e\u0627\u06cc\u06cc\u0646 \u0628\u06a9\u0634\u06cc\u062f.";
}

function buildCalledStream(numbers, freshNumbers = [], limit = 42) {
  const list = Array.isArray(numbers) ? numbers : [];
  if (!list.length) return '<div class="empty">\u0647\u0646\u0648\u0632 \u0639\u062f\u062f\u06cc \u0627\u0639\u0644\u0627\u0645 \u0646\u0634\u062f\u0647 \u0627\u0633\u062a.</div>';
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
  if (activeMeta) activeMeta.textContent = "\u062f\u0631 \u062d\u0627\u0644 \u0628\u0627\u0631\u06af\u0630\u0627\u0631\u06cc...";
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
  if (badgeStatus) badgeStatus.textContent = "\u062f\u0631 \u062d\u0627\u0644 \u0647\u0645\u06af\u0627\u0645\u200c\u0633\u0627\u0632\u06cc \u0632\u0646\u062f\u0647";
  if (badgeLast) badgeLast.textContent = "...";
  if (calledStream) calledStream.innerHTML = '<div class="empty">\u062f\u0631 \u062d\u0627\u0644 \u062f\u0631\u06cc\u0627\u0641\u062a \u0627\u0639\u062f\u0627\u062f \u062e\u0648\u0627\u0646\u062f\u0647\u200c\u0634\u062f\u0647...</div>';
}

function renderCardsEmpty() {
  const activeRoot = getEl("cardsActiveList");
  const historyRoot = getEl("cardsHistoryList");
  const activeMeta = getEl("cardsActiveMeta");
  if (activeMeta) activeMeta.textContent = "\u06f0 \u06a9\u0627\u0631\u062a \u0641\u0639\u0627\u0644";
  if (activeRoot) {
    activeRoot.innerHTML = `
      <div class="empty-rich">
        <div>\u0647\u0646\u0648\u0632 \u06a9\u0627\u0631\u062a\u06cc \u062e\u0631\u06cc\u062f\u0627\u0631\u06cc \u0646\u06a9\u0631\u062f\u0647\u200c\u0627\u06cc.</div>
        <button id="goGamesFromCardsBtn" class="small-btn primary" type="button">\u0631\u0641\u062a\u0646 \u0628\u0647 \u0628\u0627\u0632\u06cc\u200c\u0647\u0627</button>
      </div>
    `;
  }
  if (historyRoot) {
    historyRoot.innerHTML = '<div class="empty">\u062a\u0627\u0631\u06cc\u062e\u0686\u0647\u200c\u0627\u06cc \u0628\u0631\u0627\u06cc \u0646\u0645\u0627\u06cc\u0634 \u0648\u062c\u0648\u062f \u0646\u062f\u0627\u0631\u062f.</div>';
  }
  const badgeStatus = getEl("cardsLiveStatus");
  const badgeLast = getEl("cardsLiveLast");
  const calledStream = getEl("cardsCalledStream");
  if (badgeStatus) badgeStatus.textContent = "\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a";
  if (badgeLast) badgeLast.textContent = "-";
  if (calledStream) calledStream.innerHTML = '<div class="empty">\u067e\u0633 \u0627\u0632 \u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a \u062f\u0631 \u0628\u0627\u0632\u06cc \u0641\u0639\u0627\u0644\u060c \u0627\u0639\u062f\u0627\u062f \u0627\u06cc\u0646\u062c\u0627 \u0646\u0645\u0627\u06cc\u0634 \u062f\u0627\u062f\u0647 \u0645\u06cc\u200c\u0634\u0648\u0646\u062f.</div>';
  bindCardsEmptyCta();
}

function renderCardsBadge(activeGames) {
  const badgeStatus = getEl("cardsLiveStatus");
  const badgeLast = getEl("cardsLiveLast");
  const calledStream = getEl("cardsCalledStream");
  if (!badgeStatus || !badgeLast || !calledStream) return;

  if (!activeGames.length) {
    badgeStatus.textContent = "\u0628\u0627\u0632\u06cc \u0641\u0639\u0627\u0644\u06cc \u0628\u0631\u0627\u06cc \u067e\u0627\u06cc\u0634 \u0646\u06cc\u0633\u062a";
    badgeLast.textContent = "-";
    calledStream.innerHTML = '<div class="empty">\u0639\u062f\u062f\u06cc \u0628\u0631\u0627\u06cc \u0646\u0645\u0627\u06cc\u0634 \u0648\u062c\u0648\u062f \u0646\u062f\u0627\u0631\u062f.</div>';
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
    badgeStatus.textContent = `\u0639\u062f\u062f \u062c\u062f\u06cc\u062f \u0631\u0633\u06cc\u062f | \u0628\u0627\u0632\u06cc #${g.gameId}`;
    badgeLast.textContent = String(freshLast);
  } else {
    badgeStatus.textContent = `\u0622\u062e\u0631\u06cc\u0646 \u0639\u062f\u062f \u0628\u0627\u0632\u06cc #${g.gameId}`;
    badgeLast.textContent = String(lastNum ?? "-");
  }

  calledStream.innerHTML = buildCalledStream(g.calledNumbers, g.freshNumbers, 55);
}

function renderCardsActive(activeGames) {
  const root = getEl("cardsActiveList");
  const activeMeta = getEl("cardsActiveMeta");
  if (!root) return;

  if (!activeGames.length) {
    if (activeMeta) activeMeta.textContent = "\u06f0 \u06a9\u0627\u0631\u062a \u0641\u0639\u0627\u0644";
    root.innerHTML = `
      <div class="empty-rich">
        <div>\u0641\u0639\u0644\u0627\u064b \u06a9\u0627\u0631\u062a \u0641\u0639\u0627\u0644\u06cc \u062f\u0631 \u0628\u0627\u0632\u06cc\u200c\u0647\u0627\u06cc \u062c\u0627\u0631\u06cc \u0646\u062f\u0627\u0631\u06cc.</div>
        <button id="goGamesFromCardsBtn" class="small-btn" type="button">\u0645\u0634\u0627\u0647\u062f\u0647 \u0628\u0627\u0632\u06cc\u200c\u0647\u0627\u06cc \u0641\u0639\u0627\u0644</button>
      </div>
    `;
    bindCardsEmptyCta();
    return;
  }

  const totalCards = activeGames.reduce((acc, g) => acc + g.cards.length, 0);
  if (activeMeta) {
    activeMeta.textContent = `${activeGames.length} \u0628\u0627\u0632\u06cc \u0641\u0639\u0627\u0644 | ${totalCards} \u06a9\u0627\u0631\u062a`;
  }

  root.innerHTML = activeGames
    .map((g) => {
      const calledSet = new Set((g.calledNumbers || []).map((x) => Number(x)));
      const freshSet = new Set((g.freshNumbers || []).map((x) => Number(x)));
      const calledTail = (g.calledNumbers || []).slice(-20);
      const calledTailText = calledTail.length ? calledTail.join("\u060c ") : "\u0647\u0646\u0648\u0632 \u0639\u062f\u062f\u06cc \u0627\u0639\u0644\u0627\u0645 \u0646\u0634\u062f\u0647";
      return `
        <div class="active-game-block">
          <div class="active-game-head">
            <h4>\u0628\u0627\u0632\u06cc #${g.gameId}</h4>
            <div class="active-game-meta">
              <span>${safeText(statusLabel(g.status))}</span>
              <span>\u0622\u062e\u0631\u06cc\u0646 \u0639\u062f\u062f: <strong>${safeText(g.lastNumber ?? "-")}</strong></span>
              <button class="small-btn open-from-cards" data-game-id="${g.gameId}" type="button">\u0648\u0631\u0648\u062f</button>
            </div>
          </div>
          <div class="history-meta">\u0627\u0639\u062f\u0627\u062f \u0627\u0639\u0644\u0627\u0645\u200c\u0634\u062f\u0647: ${safeText(calledTailText)}</div>
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
                      <strong>\u06a9\u0627\u0631\u062a #${c.card_id}</strong>
                      <span>${safeText(c.created_at || "")}</span>
                    </div>
                    ${winnerLabel}
                    <div class="card-progress">
                      <span>${calledCount} \u0627\u0632 ${total} \u0639\u062f\u062f \u06a9\u0627\u0631\u062a \u062e\u0648\u0627\u0646\u062f\u0647 \u0634\u062f\u0647</span>
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
    root.innerHTML = '<div class="empty">\u062a\u0627\u0631\u06cc\u062e\u0686\u0647 \u062e\u0631\u06cc\u062f \u06a9\u0627\u0631\u062a \u062e\u0627\u0644\u06cc \u0627\u0633\u062a.</div>';
    return;
  }

  root.innerHTML = list
    .map(
      (c) => `
        <div class="history-item clickable" data-game-id="${Number(c.game_id || 0)}" data-card-id="${Number(c.card_id || 0)}">
          <strong>\u0628\u0627\u0632\u06cc #${c.game_id} | \u06a9\u0627\u0631\u062a #${c.card_id}</strong>
          <div class="history-meta">
            \u0648\u0636\u0639\u06cc\u062a \u0628\u0627\u0632\u06cc: ${safeText(statusLabel(c.game_status))}<br />
            \u0642\u06cc\u0645\u062a \u06a9\u0627\u0631\u062a: ${toman(c.card_price)}<br />
            \u0632\u0645\u0627\u0646 \u062e\u0631\u06cc\u062f: ${safeText(String(c.created_at || "-"))}
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
    <div class="history-modal-head">
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
      const resultText = winnerLabel ? `اعلام برنده: ${winnerLabel}` : "اعلام برنده: هنوز ثبت نشده";
      return `
        <div class="history-modal-card-item">
          <div class="card-pro-head">
            <strong>کارت #${safeText(c.card_id)}</strong>
            <span>${safeText(String(c.created_at || "-"))}</span>
          </div>
          ${winnerLabel ? `<span class="winner-kind-pill">${safeText(winnerLabel)}</span>` : ""}
          <div class="history-modal-result">${safeText(resultText)}</div>
          <div class="mini-card-grid">${buildCardGrid(nums, calledSet, new Set(), winnerCells)}</div>
        </div>
      `;
    })
    .join("");

  bodyEl.innerHTML = `${head}<div class="history-modal-grid">${cardsHtml}</div>`;
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
    setBadge("success", "\u06a9\u0627\u0631\u062a\u200c\u0647\u0627\u06cc \u0645\u0646 \u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc \u0634\u062f");
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
  renderCardsPullHint("\u062f\u0631 \u062d\u0627\u0644 \u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc \u06a9\u0627\u0631\u062a\u200c\u0647\u0627...", "refresh");
  try {
    await refreshCards({ silent: false });
  } finally {
    state.cardsPullBusy = false;
    renderCardsPullHint("\u0628\u0631\u0627\u06cc \u0646\u0648\u0633\u0627\u0632\u06cc\u060c \u0635\u0641\u062d\u0647 \u0631\u0627 \u06a9\u0645\u06cc \u0628\u0647 \u067e\u0627\u06cc\u06cc\u0646 \u0628\u06a9\u0634\u06cc\u062f.", "idle");
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
        renderCardsPullHint("\u0631\u0647\u0627 \u06a9\u0646\u06cc\u062f \u062a\u0627 \u06a9\u0627\u0631\u062a\u200c\u0647\u0627 \u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc \u0634\u0648\u0646\u062f.", "ready");
      } else if (deltaY > 26) {
        renderCardsPullHint("\u0628\u0631\u0627\u06cc \u0646\u0648\u0633\u0627\u0632\u06cc \u0628\u06cc\u0634\u062a\u0631 \u0628\u0647 \u067e\u0627\u06cc\u06cc\u0646 \u0628\u06a9\u0634\u06cc\u062f.", "pull");
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
        renderCardsPullHint("\u0628\u0631\u0627\u06cc \u0646\u0648\u0633\u0627\u0632\u06cc\u060c \u0635\u0641\u062d\u0647 \u0631\u0627 \u06a9\u0645\u06cc \u0628\u0647 \u067e\u0627\u06cc\u06cc\u0646 \u0628\u06a9\u0634\u06cc\u062f.", "idle");
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
    txRoot.innerHTML = '<div class="empty">\u062a\u0631\u0627\u06a9\u0646\u0634\u06cc \u0628\u0631\u0627\u06cc \u0646\u0645\u0627\u06cc\u0634 \u0648\u062c\u0648\u062f \u0646\u062f\u0627\u0631\u062f.</div>';
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
            <span class="meta">${safeText(String(tx.created_at || "-"))}</span>
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
    root.innerHTML = '<div class="empty">\u062f\u0631\u062e\u0648\u0627\u0633\u062a \u0648\u0627\u0631\u06cc\u0632\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647 \u0627\u0633\u062a.</div>';
    return;
  }

  root.innerHTML = items
    .map((d) => `
      <div class="item">
        <h3>\u0648\u0627\u0631\u06cc\u0632\u06cc #${d.id}</h3>
        <p>\u0648\u0636\u0639\u06cc\u062a: ${safeText(depositStatusLabel(d.status))} | \u0645\u0628\u0644\u063a: ${toman(d.amount || 0)}</p>
        <div class="meta">\u06a9\u0627\u0631\u062a \u0645\u0642\u0635\u062f: ${safeText(String(d.destination_title || "-"))}</div>
        <div class="meta">\u0632\u0645\u0627\u0646 \u062b\u0628\u062a: ${safeText(String(d.created_at || "-"))}</div>
      </div>
    `)
    .join("");
}

function drawWithdrawRequests(payload) {
  const root = getEl("withdrawRequestsList");
  if (!root) return;

  const items = Array.isArray(payload?.items) ? payload.items.slice(0, HISTORY_LIST_LIMIT) : [];
  if (!items.length) {
    root.innerHTML = '<div class="empty">\u062f\u0631\u062e\u0648\u0627\u0633\u062a \u0628\u0631\u062f\u0627\u0634\u062a\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647 \u0627\u0633\u062a.</div>';
    return;
  }

  root.innerHTML = items
    .map((w) => `
      <div class="item">
        <h3>\u0628\u0631\u062f\u0627\u0634\u062a #${w.id}</h3>
        <p>\u0648\u0636\u0639\u06cc\u062a: ${safeText(withdrawStatusLabel(w.status))} | \u0645\u0628\u0644\u063a: ${toman(w.amount || 0)}</p>
        <div class="meta">\u0632\u0645\u0627\u0646 \u062b\u0628\u062a: ${safeText(String(w.created_at || "-"))}</div>
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
            زمان: ${safeText(String(w.created_at || "-"))}
          </div>
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
      const label = `${it.title} | ${maskCard(it.card_number)}`;
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
    return;
  }
  meta.textContent = statusText
    ? `بازی #${state.admin.selectedGameId} | ${statusText}`
    : `بازی #${state.admin.selectedGameId}`;
  syncAdminCreateFormFromGame(state.admin.selectedGameId);
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
      <div class="history-item">
        <strong>واریزی #${safeText(d.id)} | ${safeText(depositStatusLabel(d.status))}</strong>
        <div class="history-meta">
          کاربر: ${safeText(d.tg_username || d.tg_user_id || d.user_id)}<br />
          مبلغ: ${safeText(toman(d.amount || 0))}<br />
          مقصد: ${safeText(d.destination_title || "-")}<br />
          زمان: ${safeText(String(d.created_at || "-"))}
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
      const status = String(w.status || "").toUpperCase();
      const actions = [];
      if (status === "PENDING") {
        actions.push(`<button class="small-btn primary admin-wdr-approve-btn" data-id="${safeText(w.id)}" type="button">تایید</button>`);
        actions.push(`<button class="small-btn danger admin-wdr-reject-btn" data-id="${safeText(w.id)}" type="button">رد</button>`);
      }
      if (status === "APPROVED") {
        actions.push(`<button class="small-btn admin-wdr-paid-btn" data-id="${safeText(w.id)}" type="button">ثبت پرداخت</button>`);
      }
      return `
        <div class="history-item">
          <strong>برداشت #${safeText(w.id)} | ${safeText(withdrawStatusLabel(w.status))}</strong>
          <div class="history-meta">
            کاربر: ${safeText(w.tg_username || w.tg_user_id || w.user_id)}<br />
            مبلغ: ${safeText(toman(w.amount || 0))}<br />
            کارت: ${safeText(w.card_number || "-")}<br />
            زمان: ${safeText(String(w.created_at || "-"))}
          </div>
          <div class="admin-item-actions">${actions.join("")}</div>
        </div>
      `;
    })
    .join("");

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
  const gid = requireAdminSelectedGame();
  setHint("adminActionHint", "در حال شروع بازی...");
  await apiFetch(`/mini-api/admin/games/${gid}/start`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_start") },
  });
  setHint("adminActionHint", `بازی #${gid} شروع شد.`, "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
}

async function adminCallNumber() {
  const gid = requireAdminSelectedGame();
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
  const gid = requireAdminSelectedGame();
  setHint("adminActionHint", "در حال Undo آخرین عدد...");
  await apiFetch(`/mini-api/admin/games/${gid}/undo-last-call`, {
    method: "POST",
    body: { idempotency_key: idem("mini_admin_undo") },
  });
  setHint("adminActionHint", "آخرین عدد بازی با موفقیت Undo شد.", "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid), refreshCards({ silent: true })]);
}

async function adminCloseLobby() {
  const gid = requireAdminSelectedGame();
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
  setHint("adminActionHint", "لینک لایو بازی با موفقیت ثبت شد.", "success");
  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);
}

async function adminClearLiveLink() {
  const gid = requireAdminSelectedGame();
  setHint("adminActionHint", "در حال حذف لینک لایو...");
  await apiFetch(`/mini-api/admin/games/${gid}/live-link`, { method: "DELETE" });
  setHint("adminActionHint", "لینک لایو حذف شد.", "success");
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

async function adminApproveWithdraw(withdrawId) {
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

async function adminPaidWithdraw(withdrawId) {
  const tracking = `mini_paid_${Date.now()}`;
  await apiFetch(`/mini-api/admin/withdraws/${Number(withdrawId)}/paid`, {
    method: "POST",
    body: { paid_tracking: tracking },
  });
  setBadge("success", `برداشت #${withdrawId} پرداخت‌شده ثبت شد`);
  await refreshAdminWithdraws();
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

  localizeShell();
  localizeCardsShell();
  if (headerUserName) headerUserName.textContent = inferDisplayName();
  updateHeaderStatus();
  wireNavigation();
  wireTheme();
  wireWalletDynamic();
  wireAdminCreateUi();
  wireAdminAccordion();
  wireCardsPullToRefresh();
  updateBuyActionState({ statusKey: "", myCardsCount: 0 });
  renderLiveLink({});
  const copyBtn = getEl("copyDepositCardBtn");
  if (copyBtn) copyBtn.disabled = true;

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
    setBadge("error", String(err.message || "\u062e\u0637\u0627\u06cc \u0627\u062d\u0631\u0627\u0632 \u0647\u0648\u06cc\u062a"));
  }

  if (!authOk) return;

  await refreshAdminBootstrap();
  await Promise.allSettled([refreshGames(), refreshCards({ silent: false }), refreshWallet()]);
  startGlobalRefresh();

  const current = document.querySelector(".nav-btn.active")?.getAttribute("data-view") || "games";
  switchToView(current);
}


window.addEventListener("beforeunload", () => {
  stopEventPolling();
  stopCardsPolling();
  stopGlobalRefresh();
});
boot().catch((err) => setBadge("error", String(err.message || "خطای داخلی")));

