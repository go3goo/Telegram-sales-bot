# Telegram Sales Bot (order collection, no in-bot payments)

A small Python bot for selling a handful of products via Telegram. Customers
browse a catalog, add items to a cart, and check out by providing their name,
phone, and address. You (the admin) get notified in Telegram with the order
details — you handle payment collection separately (bank transfer, cash on
delivery, etc.).

## 1. Create your bot

1. Open Telegram, message **@BotFather**.
2. Send `/newbot` and follow the prompts (choose a name and a username ending in `bot`).
3. BotFather gives you a token like `123456789:AAExampleTokenString`. Save it.

## 2. Get your admin chat ID

1. Message **@userinfobot** (or **@RawDataBot**) on Telegram.
2. It replies with your numeric user ID — that's your `ADMIN_CHAT_ID`.
   Orders will be sent to you at this ID.

## 3. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate   # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Configure

Easiest: set environment variables before running.

```bash
export BOT_TOKEN="123456789:AAExampleTokenString"
export ADMIN_CHAT_ID="987654321"
```

Or edit the constants directly at the top of `bot.py`.

## 5. Add your products

Edit the `SEED_PRODUCTS` list near the top of `bot.py` before first run:

```python
SEED_PRODUCTS = [
    ("Classic T-Shirt", "100% cotton, unisex fit", 15.00),
    ("Coffee Mug", "12oz ceramic mug", 8.00),
]
```

These are only inserted the first time the database (`shop.db`) is created.
After that, add more products anytime from Telegram as the admin:

```
/admin_add Hoodie | Warm fleece hoodie | 30.00
```

## 6. Run it

```bash
python bot.py
```

Leave this running (on a VPS, Render, Railway, etc. for 24/7 uptime — on
your own machine it only works while the script is running).

## Customer commands & menu

On `/start`, customers get a persistent menu at the bottom of the chat:

```
🛍️ Catalog     🧺 Cart
✅ Checkout    ℹ️ Help
```

Tapping a button does the same thing as typing its matching command. Telegram's
native menu button (the icon next to the text box) is also populated with the
command list, so both ways of navigating work.

- `/start` — welcome message + shows the menu
- `/catalog` — browse products, tap to view details, tap "Add to cart"
- `/cart` — see cart contents and total
- `/checkout` — collects name, phone, address, then confirms the order
- `/help` — reminder of what each menu button does
- `/cancel` — abort checkout mid-way

## ⚠️ Railway deployment note

If your bot crashes on Railway with `ModuleNotFoundError: No module named 'telegram'`,
it means `requirements.txt` wasn't found during the build — check Railway's
**Build** log for a `Packages` section; it should list `pip` alongside `python`.
If it only shows `python`, `requirements.txt` is missing or misnamed in your
GitHub repo. It must be:
- named exactly `requirements.txt` (all lowercase)
- placed in the **root** of the repo, next to `bot.py`
- committed and pushed to GitHub before Railway builds

After fixing it, push a new commit (or trigger a manual redeploy) so Railway
rebuilds with the dependency installed.

## How orders reach you

When a customer confirms checkout, you (ADMIN_CHAT_ID) receive a Telegram
message with their name, phone, address, items, and total. All orders are
also saved in the `orders` table in `shop.db` for your records — you can
open it with any SQLite browser (e.g. DB Browser for SQLite) or query it
with Python.

## Next steps you might want

- **Real payments**: Telegram's Payments API (works with Stripe and others)
  can replace the "pay outside the bot" flow if you decide you need it later.
- **Order status updates**: add an `/admin_orders` command to list pending
  orders and mark them shipped.
- **Multiple quantities per item**: currently "Add to cart" adds 1 unit each
  tap — you can tap repeatedly, or extend `add_item` to ask for quantity.
- **Deploying 24/7**: Railway, Render, or a $5/month VPS (e.g. DigitalOcean)
  are common cheap options; run `bot.py` as a background service (e.g. with
  `systemd` or a process manager like `pm2`/`supervisor`).
