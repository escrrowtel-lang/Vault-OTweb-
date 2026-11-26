# Vault Store

Apna standalone OTT/digital subscription store: website + wallet + inventory + admin panel. Telegram ki zaroorat nahi.
Sirf Python 3 chahiye (koi pip package nahi), database SQLite.

## Kya kya hai
- **Customer:** signup/login, catalog, plan kharidna (wallet se), orders + delivery, wallet top-up, referral
- **Inventory:** auto delivery (admin account details upload karta hai, har item sirf ek baar bikta hai), manual delivery, pre-order (stock aate hi auto deliver)
- **Payments (wallet top-up):** UPI (UTR, admin approve), Binance ID (admin approve), USDT BEP20 (blockchain se auto-verify, unique amount + ek hash sirf ek baar)
- **Admin panel (`/admin.html`):** deposits approve/reject, orders deliver/refund, category/product/plan/inventory, users, coupons, settings
- **Password reset:** admin panel se user ko reset link do (Users > Reset link), ya SMTP set ho to "Password bhool gaye?" se email jaata hai
- **Activity log:** admin ke saare important actions (Activity tab), **roz auto backup** (`/var/backups/vault-store`, 14 din)
- **Nahi bana (baad mein):** Binance Pay checkout, UPI auto-mail verification, email verify, HTTPS (domain chahiye)

## Local par chalao
```
python3 server/manage.py create-admin you@example.com
python3 server/manage.py seed-demo          # sirf layout dekhne ke liye DEMO data
python3 server/app.py                       # http://127.0.0.1:8000
python3 -m unittest discover -s tests       # tests
```

## VPS par (Ubuntu/Debian)
Pehli baar:
```
git clone https://github.com/escrrowtel-lang/Vault-OTweb-.git
cd Vault-OTweb-
sudo bash deploy/install.sh
sudo bash deploy/admin.sh create-admin aapka@email.com
```
Update / restart:
```
cd ~/Vault-OTweb- && sudo bash deploy/update.sh
sudo systemctl restart vault-store      # sirf server restart
sudo journalctl -u vault-store -n 50 --no-pager   # log
```
Data `/var/lib/vault-store` mein hai (backup yahin se lo).

## Email (optional, password reset ke liye)
`/etc/vault-store.env` banao (sirf root padh sake: `chmod 600`):
```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user
SMTP_PASS=password
SMTP_FROM=Vault Store <noreply@example.com>
```
Phir `sudo systemctl restart vault-store` aur admin Settings mein **Site URL** bharo (jaise `https://yourdomain.com`). Email setup na ho to bhi chalta hai: admin se reset link lo.

## Backup
Roz 03:30 par apne aap. Abhi lena ho: `sudo /usr/local/sbin/vault-backup.sh`. Backup mein inventory (account details) hai, isliye use private rakho.

## Payment settings
Admin panel > Settings mein UPI ID, Binance ID, USDT wallet address, confirmations aur min/max deposit bharo. Koi secret/API key code mein nahi hai.

## Security notes
- Passwords scrypt se hash, session cookie HttpOnly, har POST par custom header (CSRF), login/signup rate-limit.
- **Domain na ho to site sirf HTTP par hai: password aur cookie encrypted nahi.** Jaldi domain lekar `certbot --nginx` se HTTPS lagao. Tab tak koi aisa password mat rakho jo kahin aur use hota ho.
- Koi asli company ka logo nahi. Icons original "app tile" style mein hain; chaaho to admin se har product ki apni image upload karo.
