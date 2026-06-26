export class CryptoWalletCheckout {
  constructor({ options, theme = "dark", onEvent = null }) {
    this.options = options || {};
    this.theme = theme === "light" ? "light" : "dark";
    this.onEvent = typeof onEvent === "function" ? onEvent : () => {};
  }

  async prepare(network) {
    await this._networkModule(network);
    return true;
  }

  async pay(invoice) {
    const network = String(invoice?.network || "").toUpperCase();
    const module = await this._networkModule(network);
    return module.payCryptoInvoice({
      invoice,
      options: this.options,
      theme: this.theme,
      onEvent: this.onEvent,
    });
  }

  async _networkModule(network) {
    const normalized = String(network || "").toUpperCase();
    if (normalized === "TON") return import("./ton-checkout.js");
    if (normalized === "TRON") return import("./tron-checkout.js");
    throw new Error("شبکه انتخاب‌شده برای پرداخت مستقیم پشتیبانی نمی‌شود.");
  }
}
