// Site settings. Yahan koi secret / API key NAHI daalni (ye file browser mein public hoti hai).
window.SITE = {
  BRAND: "Vault Store",                 // final brand naam
  TAGLINE: "OTT & digital subscriptions, plan-based",
  BOT_USERNAME: "",                   // TODO: Telegram bot username (bina @ ke)
  SUPPORT_URL: "",                    // TODO: support link, jaise https://t.me/yourhandle
  API_BASE: "",                       // khaali = same domain/IP (nginx /app/ ko backend par proxy karta hai). Alag server ho to poora URL
  CATALOG_PATH: "/app/catalog",
  REFRESH_MS: 30000,                  // catalog ko itne ms baad dobara laata hai (server cache 20s hai)
  CURRENCY: "$",
  DEMO_ON_ERROR: true                 // catalog na mile to DEMO data dikhata hai (banner ke saath). Live jaane par false kar do
};
