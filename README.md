# Vault Store – website

Plain static site (HTML + CSS + JS), koi build step nahi. Kisi bhi static host par chalti hai (Netlify, Vercel, GitHub Pages).

## Chalane ke liye
```
python3 -m http.server 8080
```
phir `http://localhost:8080` kholo.

## Setup (`assets/config.js`)
- `BRAND` – final brand naam
- `API_BASE` – backend URL jahan `GET /app/catalog` chalta hai (CORS allow hona chahiye)
- `BOT_USERNAME`, `SUPPORT_URL` – Telegram links

`API_BASE` khaali ho to sirf layout dekhne ke liye DEMO data dikhta hai (banner ke saath). Asli deploy se pehle API_BASE zaroor set karo.

## Rules
- Frontend mein koi API key, token ya secret nahi.
- Reseller API (`/api/v1/*`) site par use nahi hoti.
- Koi asli company ka logo ya domain nahi. Fake reviews, fake stock ya fake urgency nahi.
- `refund-policy`, `terms`, `privacy` pages DRAFT hain, `[TODO]` jagah asli text bharo.

## Design
Safed (plain white) base, alag-alag colours sirf accents mein (category chips, card top-line, buttons).
