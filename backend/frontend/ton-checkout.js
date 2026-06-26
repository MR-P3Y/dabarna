import { Address, beginCell } from "@ton/core";
import { TonConnectUI, THEME } from "@tonconnect/ui";

let tonUi = null;


function decimalToUnits(value, decimals) {
  const [wholeRaw, fractionRaw = ""] = String(value || "0").split(".");
  const whole = wholeRaw || "0";
  const fraction = `${fractionRaw}${"0".repeat(decimals)}`.slice(0, decimals);
  return (BigInt(whole) * (10n ** BigInt(decimals)) + BigInt(fraction || "0")).toString();
}


function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}


function tonCommentPayload(text) {
  if (!String(text || "").trim()) return undefined;
  const cell = beginCell()
    .storeUint(0, 32)
    .storeStringTail(String(text).trim())
    .endCell();
  return bytesToBase64(cell.toBoc());
}


function timeoutPromise(ms, message) {
  return new Promise((_, reject) => {
    window.setTimeout(() => reject(new Error(message)), ms);
  });
}


export async function payCryptoInvoice({ invoice, options, theme, onEvent }) {
  const manifestUrl = String(options?.ton_manifest_url || "").trim();
  if (!manifestUrl) throw new Error("تنظیمات اتصال کیف پول TON کامل نیست.");
  if (!tonUi) {
    tonUi = new TonConnectUI({ manifestUrl });
    tonUi.uiOptions = {
      uiPreferences: {
        theme: theme === "light" ? THEME.LIGHT : THEME.DARK,
      },
    };
    await tonUi.connectionRestored;
  }

  if (!tonUi.connected) {
    const connected = new Promise((resolve) => {
      const unsubscribe = tonUi.onStatusChange((wallet) => {
        if (!wallet?.account?.address) return;
        unsubscribe();
        resolve(wallet);
      });
    });
    await tonUi.openModal();
    await Promise.race([
      connected,
      timeoutPromise(120000, "مهلت اتصال کیف پول TON تمام شد."),
    ]);
  }

  const walletAddress = String(tonUi.account?.address || "");
  if (!walletAddress) throw new Error("اتصال کیف پول TON تکمیل نشد.");
  onEvent({
    event: "CONNECTED",
    provider: "TON_CONNECT",
    walletAddress,
  });

  const amount = decimalToUnits(invoice.amount_crypto, 9);
  const destination = Address.parse(String(invoice.destination_address)).toString({
    bounceable: false,
    urlSafe: true,
  });
  const result = await tonUi.sendTransaction({
    validUntil: Math.floor(Date.now() / 1000) + 600,
    network: "-239",
    from: walletAddress,
    messages: [
      {
        address: destination,
        amount,
        payload: tonCommentPayload(invoice.memo),
      },
    ],
  });
  return {
    provider: "TON_CONNECT",
    walletAddress,
    txHash: null,
    traceId: String(result?.traceId || ""),
  };
}
