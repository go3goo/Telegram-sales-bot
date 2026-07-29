"""
Telegram Sales Bot — order collection (no in-bot payments)

Features:
- Product catalog (browse via inline buttons)
- Cart (add/remove items, view total)
- Checkout: collects name, phone, address
- Sends order to admin chat, confirms to customer
- SQLite storage for products, carts, orders

Setup:
1. pip install -r requirements.txt
2. Set BOT_TOKEN and ADMIN_CHAT_ID below (or via environment variables)
3. Edit the PRODUCTS list with your items, or add them later via /admin_add
4. Run: python bot.py
"""

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))  # your Telegram user/chat id
DB_PATH = os.environ.get("DB_PATH", "shop.db")

# Seed products (only used the first time the DB is created)
SEED_PRODUCTS = [
    ("Classic T-Shirt", "100% cotton, unisex fit", 15.00),
    ("Coffee Mug", "12oz ceramic mug", 8.00),
    ("Tote Bag", "Canvas, reinforced handles", 12.00),
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states for checkout
NAME, PHONE, ADDRESS, CONFIRM = range(4)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            active INTEGER DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cart_items (
            user_id INTEGER,
            product_id INTEGER,
            quantity INTEGER,
            PRIMARY KEY (user_id, product_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            name TEXT,
            phone TEXT,
            address TEXT,
            items_summary TEXT,
            total REAL,
            created_at TEXT
        )
        """
    )
    conn.commit()

    # Seed products only if table is empty
    cur.execute("SELECT COUNT(*) as c FROM products")
    if cur.fetchone()["c"] == 0:
        cur.executemany(
            "INSERT INTO products (name, description, price) VALUES (?, ?, ?)",
            SEED_PRODUCTS,
        )
        conn.commit()
    conn.close()


def get_active_products():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM products WHERE active = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def get_product(product_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    conn.close()
    return row


def add_to_cart(user_id: int, product_id: int, qty: int = 1):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
        (user_id, product_id),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE cart_items SET quantity = quantity + ? WHERE user_id = ? AND product_id = ?",
            (qty, user_id, product_id),
        )
    else:
        cur.execute(
            "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?)",
            (user_id, product_id, qty),
        )
    conn.commit()
    conn.close()


def get_cart(user_id: int):
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.price, c.quantity
        FROM cart_items c JOIN products p ON p.id = c.product_id
        WHERE c.user_id = ?
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def clear_cart(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def cart_total(user_id: int) -> float:
    return sum(r["price"] * r["quantity"] for r in get_cart(user_id))


def save_order(user_id, username, name, phone, address, items_summary, total):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO orders (user_id, username, name, phone, address, items_summary, total, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            name,
            phone,
            address,
            items_summary,
            total,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Persistent menu (reply keyboard shown at the bottom of the chat)
# ---------------------------------------------------------------------------

MENU_CATALOG = "🛍️ Catalog"
MENU_CART = "🧺 Cart"
MENU_CHECKOUT = "✅ Checkout"
MENU_HELP = "ℹ️ Help"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [MENU_CATALOG, MENU_CART],
            [MENU_CHECKOUT, MENU_HELP],
        ],
        resize_keyboard=True,
    )


async def set_bot_commands(app: Application):
    """Populate Telegram's native '/' menu button next to the text box."""
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Show the welcome message and menu"),
            BotCommand("catalog", "Browse products"),
            BotCommand("cart", "View your cart"),
            BotCommand("checkout", "Place your order"),
            BotCommand("cancel", "Cancel checkout in progress"),
        ]
    )


# ---------------------------------------------------------------------------
# Handlers: catalog & cart
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! 👋\nUse the menu below or the commands to get started.",
        reply_markup=main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛍️ Catalog — browse products\n"
        "🧺 Cart — view your cart\n"
        "✅ Checkout — place your order\n\n"
        "You can tap the buttons below or type the matching /command.",
        reply_markup=main_menu_keyboard(),
    )


async def catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = get_active_products()
    if not products:
        await update.message.reply_text("No products available right now.")
        return

    keyboard = [
        [
            InlineKeyboardButton(
                f"{p['name']} — ${p['price']:.2f}",
                callback_data=f"view_{p['id']}",
            )
        ]
        for p in products
    ]
    await update.message.reply_text(
        "🛍️ Our products:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def view_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split("_")[1])
    p = get_product(product_id)
    if not p:
        await query.edit_message_text("Product not found.")
        return

    text = f"*{p['name']}*\n{p['description']}\n\nPrice: ${p['price']:.2f}"
    keyboard = [
        [InlineKeyboardButton("➕ Add to cart", callback_data=f"add_{p['id']}")],
        [InlineKeyboardButton("⬅️ Back to catalog", callback_data="back_catalog")],
    ]
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )


async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    product_id = int(query.data.split("_")[1])
    add_to_cart(query.from_user.id, product_id, 1)
    await query.answer("Added to cart ✅")


async def back_to_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    products = get_active_products()
    keyboard = [
        [
            InlineKeyboardButton(
                f"{p['name']} — ${p['price']:.2f}",
                callback_data=f"view_{p['id']}",
            )
        ]
        for p in products
    ]
    await query.edit_message_text(
        "🛍️ Our products:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    items = get_cart(user_id)
    if not items:
        await update.message.reply_text("Your cart is empty. Use /catalog to browse.")
        return

    lines = [f"{r['name']} x{r['quantity']} — ${r['price'] * r['quantity']:.2f}" for r in items]
    total = cart_total(user_id)
    text = "🧺 Your cart:\n" + "\n".join(lines) + f"\n\n*Total: ${total:.2f}*"
    await update.message.reply_text(text, parse_mode="Markdown")
    await update.message.reply_text("Ready? Use /checkout to place your order.")


# ---------------------------------------------------------------------------
# Checkout conversation
# ---------------------------------------------------------------------------

async def checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not get_cart(user_id):
        await update.message.reply_text("Your cart is empty. Use /catalog first.")
        return ConversationHandler.END

    await update.message.reply_text("Let's get your order details.\nWhat's your full name?")
    return NAME


async def checkout_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Phone number?")
    return PHONE


async def checkout_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Delivery address?")
    return ADDRESS


async def checkout_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text
    user_id = update.effective_user.id
    items = get_cart(user_id)
    total = cart_total(user_id)
    summary = "\n".join(f"{r['name']} x{r['quantity']}" for r in items)

    text = (
        f"Please confirm your order:\n\n"
        f"Name: {context.user_data['name']}\n"
        f"Phone: {context.user_data['phone']}\n"
        f"Address: {context.user_data['address']}\n\n"
        f"{summary}\n\nTotal: ${total:.2f}\n\n"
        f"Reply YES to confirm or /cancel to abort."
    )
    await update.message.reply_text(text)
    return CONFIRM


async def checkout_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() != "yes":
        await update.message.reply_text("Okay, reply YES when ready, or /cancel to abort.")
        return CONFIRM

    user = update.effective_user
    items = get_cart(user.id)
    total = cart_total(user.id)
    summary = ", ".join(f"{r['name']} x{r['quantity']}" for r in items)

    save_order(
        user.id,
        user.username or "",
        context.user_data["name"],
        context.user_data["phone"],
        context.user_data["address"],
        summary,
        total,
    )
    clear_cart(user.id)

    await update.message.reply_text(
        "🎉 Order placed! We'll contact you soon to confirm delivery.",
        reply_markup=main_menu_keyboard(),
    )

    if ADMIN_CHAT_ID:
        admin_text = (
            f"🆕 New order!\n\n"
            f"Customer: {context.user_data['name']} (@{user.username or 'n/a'})\n"
            f"Phone: {context.user_data['phone']}\n"
            f"Address: {context.user_data['address']}\n\n"
            f"Items: {summary}\n"
            f"Total: ${total:.2f}"
        )
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text)

    context.user_data.clear()
    return ConversationHandler.END


async def checkout_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Checkout cancelled. Your cart is still saved.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Basic admin command (add product on the fly)
# ---------------------------------------------------------------------------

async def admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Not authorized.")
        return

    # Usage: /admin_add Name | Description | Price
    try:
        payload = update.message.text.split(" ", 1)[1]
        name, description, price = [p.strip() for p in payload.split("|")]
        conn = get_conn()
        conn.execute(
            "INSERT INTO products (name, description, price) VALUES (?, ?, ?)",
            (name, description, float(price)),
        )
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Added '{name}' at ${float(price):.2f}")
    except Exception:
        await update.message.reply_text(
            "Usage: /admin_add Name | Description | Price\n"
            "Example: /admin_add Hoodie | Warm fleece hoodie | 30.00"
        )


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(set_bot_commands).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("catalog", catalog))
    app.add_handler(CommandHandler("cart", view_cart))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin_add", admin_add))

    # Persistent menu buttons route to the same handlers as their /commands
    app.add_handler(MessageHandler(filters.Regex(f"^{MENU_CATALOG}$"), catalog))
    app.add_handler(MessageHandler(filters.Regex(f"^{MENU_CART}$"), view_cart))
    app.add_handler(MessageHandler(filters.Regex(f"^{MENU_HELP}$"), help_command))

    app.add_handler(CallbackQueryHandler(view_product, pattern=r"^view_\d+$"))
    app.add_handler(CallbackQueryHandler(add_item, pattern=r"^add_\d+$"))
    app.add_handler(CallbackQueryHandler(back_to_catalog, pattern=r"^back_catalog$"))

    checkout_conv = ConversationHandler(
        entry_points=[
            CommandHandler("checkout", checkout_start),
            MessageHandler(filters.Regex(f"^{MENU_CHECKOUT}$"), checkout_start),
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_address)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_confirm)],
        },
        fallbacks=[CommandHandler("cancel", checkout_cancel)],
    )
    app.add_handler(checkout_conv)

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
