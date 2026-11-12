// Presentation only: never authorizes a win, transfers money or starts a game.
const integerValue = value => typeof value === "number" ? value :
  typeof value === "string" && /^\d+$/.test(value.trim()) ? Number(value.trim()) : NaN;
const positiveId = value => Number.isSafeInteger(integerValue(value)) && integerValue(value) > 0;
const amountValue = value => Number.isSafeInteger(integerValue(value)) && integerValue(value) >= 0 ? integerValue(value) : null;

export function prizeRows(payload = {}) {
  const users = payload.winner_user_ids;
  const cards = payload.winner_card_ids;
  const amounts = payload.amounts_by_card;
  // Preserve repeated user IDs: one user may win on several distinct cards.
  let rows = [];
  if (Array.isArray(users) && Array.isArray(cards) && Array.isArray(amounts) &&
      users.length && users.length === cards.length && users.length === amounts.length) {
    rows = users.map((id, i) => ({ userId: integerValue(id), cardId: integerValue(cards[i]), amount: amountValue(amounts[i]) }));
  } else if (Array.isArray(payload.winner_users) && payload.winner_users.length) {
    rows = payload.winner_users.map(user => ({ userId: integerValue(user.user_id), cardId: integerValue(user.card_id), amount: amountValue(user.amount) }));
  }
  if (!rows.length || rows.some(row => !positiveId(row.userId) || !positiveId(row.cardId) || row.amount === null) ||
      new Set(rows.map(row => row.cardId)).size !== rows.length) return [];
  const total = rows.reduce((sum, row) => sum + row.amount, 0);
  if (!Number.isSafeInteger(total)) return [];
  if (payload.amount_total !== undefined && amountValue(payload.amount_total) !== total) return [];
  const rich = Array.isArray(payload.winner_users) ? payload.winner_users : [];
  if (rich.length && (rich.length !== rows.length || rows.some(row => {
    const matches = rich.filter(user => Number(user.card_id) === row.cardId);
    return matches.length !== 1 || Number(matches[0].user_id) !== row.userId || amountValue(matches[0].amount) !== row.amount;
  }))) return [];
  return rows.map(row => {
    const detail = rich.find(user => Number(user.card_id) === row.cardId) || {};
    return { ...row, displayName: String(detail.display_name || detail.first_name || ""),
      username: String(detail.username || ""), tgUserId: positiveId(detail.tg_user_id) ? Number(detail.tg_user_id) : 0 };
  });
}

export function personalPrize(payload, userId) {
  const rows = prizeRows(payload);
  const mine = rows.filter(row => row.userId === Number(userId));
  return mine.length ? mine.reduce((sum, row) => sum + row.amount, 0) : null;
}

export function ruleLabel(rule, layout) {
  const key = String(rule || "").toUpperCase();
  if (key === "LINE" && integerValue(layout) === 2) return "خطی · ۱۵ عدد · ۳×۹";
  if (key === "FULL_CARD" && integerValue(layout) === 2) return "پرکردنی · ۱۵ عدد · بدون تورنا";
  if (key === "LEGACY" && integerValue(layout) === 1) return "قدیمی · ۲۰ عدد · ۴×۵";
  return "اطلاعات قانون بازی ناسازگار است";
}

export function prizeLabel(kind, payload = {}) {
  const key = String(payload.game_rule || "").toUpperCase();
  if (ruleLabel(key, payload.card_layout_version).includes("ناسازگار")) return "قانون برد قابل تأیید نیست";
  if (kind === "PRIZE_COL") return key === "FULL_CARD" ? "رویداد جایزه با قانون بازی ناسازگار است" : key === "LINE" ? "تورنا · ۳ عدد یک ردیف" : "تورنا · ستون ۴عددی";
  if (kind === "PRIZE_ROW") return key === "FULL_CARD" ? "پرکردنی · تمام ۱۵ عدد" : key === "LINE" ? "خطی · ۵ عدد یک ردیف" : "تمام · ردیف ۵عددی";
  return "نتیجه ثبت‌شده بازی";
}

export function notificationCategory(item) {
  const kind = String(item?.kind || "").toLowerCase();
  if (kind === "game") return "game";
  if (kind === "win") return "win";
  if (["deposit", "withdraw", "crypto", "admin_message"].includes(kind)) return "payment";
  return "system";
}

export function inboxItems(items, games) {
  const gameItems = (Array.isArray(games) ? games : []).filter(game => positiveId(game.id)).map(game => ({
    id: `game:${game.id}:${game.status}`, kind: "game", severity: "info", game,
    title: `بازی #${game.id}`, body: ruleLabel(game.game_rule, game.card_layout_version),
    created_at: game.ended_at || game.started_at || game.created_at,
    route: { view: "games", target_type: "game", target_id: game.id, action: "open_game" },
  }));
  const unique = new Map();
  for (const item of [...(Array.isArray(items) ? items : []), ...gameItems]) {
    if (item?.id !== undefined && String(item.id)) unique.set(String(item.id), item);
  }
  return [...unique.values()].sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0));
}

export function filterInbox(items, filter, readIds) {
  return items.filter(item => filter === "all" || (filter === "unread" ? !readIds.has(String(item.id)) : notificationCategory(item) === filter));
}

// One focus owner, including nested receipt/card dialogs; restore the invoking control.
const dialogs = [];
let pageOverflow = "";
export function openDialog(element, onClose) {
  if (!element || dialogs.some(item => item.element === element)) return;
  const dialog = element.querySelector('[role="dialog"]') || element.firstElementChild;
  const previous = document.activeElement;
  const previousRowId = previous?.closest?.(".notification-item")?.dataset.id;
  const previousAction = previous?.dataset?.inboxAction;
  const keydown = event => {
    if (dialogs.at(-1)?.element !== element) return;
    if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); onClose(); return; }
    if (event.key !== "Tab") return;
    const nodes = [...dialog.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]')].filter(node => node.getClientRects().length);
    const first = nodes[0] || dialog, last = nodes.at(-1) || dialog;
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
  };
  if (!dialogs.length) pageOverflow = document.body.style.overflow;
  dialogs.push({ element, previous, previousRowId, previousAction, keydown });
  element.classList.add("open"); element.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  dialog.setAttribute("tabindex", "-1");
  document.addEventListener("keydown", keydown, true);
  (dialog.querySelector('button:not(:disabled)') || dialog).focus();
}

export function closeDialog(element) {
  if (!element) return;
  element.classList.remove("open"); element.setAttribute("aria-hidden", "true");
  const index = dialogs.findIndex(item => item.element === element);
  if (index < 0) return;
  const [entry] = dialogs.splice(index, 1);
  document.removeEventListener("keydown", entry.keydown, true);
  if (!dialogs.length) document.body.style.overflow = pageOverflow;
  const target = dialogs.at(-1)?.element;
  const replacement = entry.previousRowId && [...document.querySelectorAll(".notification-item")].find(row => row.dataset.id === entry.previousRowId)?.querySelector(`[data-inbox-action="${entry.previousAction}"]`);
  const previous = entry.previous?.isConnected ? entry.previous : replacement;
  if (previous?.isConnected && (!target || target.contains(previous))) previous.focus();
  else target?.querySelector('button:not(:disabled)')?.focus();
}
