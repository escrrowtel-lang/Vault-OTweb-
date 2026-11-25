// Site settings. Yahan koi secret / API key NAHI daalni (ye file browser mein public hoti hai).
window.SITE = {
  BRAND: "Vault OTT",                 // TODO: final brand naam
  TAGLINE: "OTT & digital subscriptions, plan-based",
  BOT_USERNAME: "",                   // TODO: Telegram bot username (bina @ ke)
  SUPPORT_URL: "",                    // TODO: support link, jaise https://t.me/yourhandle
  API_BASE: "",                       // TODO: backend URL jahan /app/catalog chalta hai, jaise https://your-app.up.railway.app
  CATALOG_PATH: "/app/catalog",
  REFRESH_MS: 30000,                  // catalog ko itne ms baad dobara laata hai (server cache 20s hai)
  CURRENCY: "$",
  DEMO_WHEN_NO_API: true              // API_BASE khaali ho to sirf layout dekhne ke liye DEMO data dikhata hai
};
