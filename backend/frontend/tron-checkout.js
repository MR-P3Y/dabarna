import {
  WalletConnectChainID,
  WalletConnectWallet,
} from "@tronweb3/walletconnect-tron";
import { TronWeb } from "tronweb";

let tronWallet = null;


function decimalToUnits(value, decimals) {
  const [wholeRaw, fractionRaw = ""] = String(value || "0").split(".");
  const whole = wholeRaw || "0";
  const fraction = `${fractionRaw}${"0".repeat(decimals)}`.slice(0, decimals);
  return (BigInt(whole) * (10n ** BigInt(decimals)) + BigInt(fraction || "0")).toString();
}


async function injectedTronLink() {
  const tronLink = window.tronLink;
  const tronWeb = window.tronWeb;
  if (!tronLink || !tronWeb) return null;
  try {
    await tronLink.request({ method: "tron_requestAccounts" });
    const address = String(tronWeb.defaultAddress?.base58 || "");
    if (!address) throw new Error("آدرس فعال TronLink دریافت نشد.");
    const fullNodeHost = new URL(String(tronWeb.fullNode?.host || "")).hostname.toLowerCase();
    const mainnetNodes = new Set(["api.trongrid.io", "api.tronstack.io"]);
    if (!mainnetNodes.has(fullNodeHost)) {
      throw new Error("TronLink باید روی TRON Mainnet رسمی باشد. شبکه تست یا نود سفارشی قابل پرداخت نیست.");
    }
    return {
      address,
      tronWeb,
      signTransaction: (transaction) => tronWeb.trx.sign(transaction),
    };
  } catch (error) {
    if (error instanceof Error && error.message.includes("TRON Mainnet")) {
      throw error;
    }
    throw new Error("اتصال TronLink لغو شد یا در دسترس نیست.");
  }
}


async function sendTronUsdt({ adapter, invoice, options, provider }) {
  const fullHost = String(options?.trongrid_base_url || "https://api.trongrid.io");
  const tronWeb = adapter.tronWeb || new TronWeb({ fullHost });
  const contract = String(options?.tron_usdt_contract || "");
  if (!contract) throw new Error("قرارداد USDT شبکه TRON تنظیم نشده است.");
  const amount = decimalToUnits(invoice.amount_crypto, 6);
  const result = await tronWeb.transactionBuilder.triggerSmartContract(
    contract,
    "transfer(address,uint256)",
    { feeLimit: 200000000 },
    [
      { type: "address", value: String(invoice.destination_address) },
      { type: "uint256", value: amount },
    ],
    String(adapter.address),
  );
  if (!result?.result?.result || !result?.transaction) {
    throw new Error("ساخت تراکنش TRC20 در کیف پول ناموفق بود.");
  }
  const signed = await adapter.signTransaction(result.transaction);
  const broadcast = await tronWeb.trx.sendRawTransaction(signed);
  const duplicate = String(broadcast?.code || "").toUpperCase() === "DUP_TRANSACTION_ERROR";
  if (!duplicate && (broadcast?.result === false || broadcast?.code)) {
    throw new Error("ارسال تراکنش TRC20 به شبکه ناموفق بود.");
  }
  const txHash = String(signed?.txID || broadcast?.txid || broadcast?.transaction?.txID || "");
  if (!txHash) throw new Error("هش تراکنش TRC20 دریافت نشد.");
  return {
    provider,
    walletAddress: String(adapter.address),
    txHash,
    traceId: "",
  };
}


export async function payCryptoInvoice({ invoice, options, theme, onEvent }) {
  const injected = await injectedTronLink();
  if (injected) {
    onEvent({
      event: "CONNECTED",
      provider: "TRONLINK",
      walletAddress: injected.address,
    });
    return sendTronUsdt({
      adapter: injected,
      invoice,
      options,
      provider: "TRONLINK",
    });
  }

  const projectId = String(options?.walletconnect_project_id || "").trim();
  if (!projectId) {
    throw new Error("اتصال مستقیم TRON روی سرور فعال نشده است؛ از QR استفاده کنید.");
  }
  if (!tronWallet) {
    tronWallet = new WalletConnectWallet({
      network: WalletConnectChainID.Mainnet,
      options: {
        relayUrl: "wss://relay.walletconnect.com",
        projectId,
        metadata: {
          name: "Davarna",
          description: "Davarna crypto wallet payment",
          url: window.location.origin,
          icons: [`${window.location.origin}/mini/assets/bot-logo.jpg`],
        },
      },
      themeMode: theme,
      themeVariables: {
        "--w3m-z-index": 10000,
      },
    });
  }
  const { address } = await tronWallet.connect();
  if (!address) throw new Error("اتصال کیف پول TRON تکمیل نشد.");
  onEvent({
    event: "CONNECTED",
    provider: "WALLETCONNECT_TRON",
    walletAddress: address,
  });
  return sendTronUsdt({
    adapter: {
      address,
      signTransaction: (transaction) => tronWallet.signTransaction(transaction),
    },
    invoice,
    options,
    provider: "WALLETCONNECT_TRON",
  });
}
