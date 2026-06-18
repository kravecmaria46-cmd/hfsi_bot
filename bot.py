# ============================================
# HFSI RPG BOT - ПОЛНАЯ ВЕРСИЯ
# ПЕРСОНА + ПЕРСОНАЖИ + КОМНАТЫ + АВТОУДАЛЕНИЕ + РЕДАКТОР + СБРОС + ГЕНЕРАЦИЯ МИРОВ + ГЕНЕРАЦИЯ ПЕРСОНАЖЕЙ + /regenerate
# ============================================

import asyncio
import os
import logging
import sys
from datetime import datetime
from typing import Optional, List
import json
import re
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, JSON, Table, select, update, delete
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler, ContextTypes
import openai

# ============================================
# 🔑 ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (из Render/Bothost)
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
POLZA_API_KEY = os.getenv("POLZA_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///hfsi_bot.db")
POLZA_MODEL = os.getenv("POLZA_MODEL", "deepseek/deepseek-v4-flash")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))

MAX_HISTORY_LENGTH = 20
TEMPERATURE = 0.8

# ============================================
# МОДЕЛИ БАЗЫ ДАННЫХ
# ============================================

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    active_persona_id = Column(Integer, ForeignKey('personas.id'))
    active_character_id = Column(Integer, ForeignKey('characters.id'))
    active_world_enabled = Column(Boolean, default=True)
    max_tokens = Column(Integer, default=1500)
    scenario_mode = Column(Boolean, default=False)
    scenario_context = Column(Text, nullable=True)
    rooms = Column(JSON, default=['Главная'])
    current_room = Column(String(100), default='Главная')

class World(Base):
    __tablename__ = 'worlds'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey('users.id'))
    created_room = Column(String(100), default='Главная')
    personas = relationship('Persona', back_populates='world')
    characters = relationship('Character', back_populates='world')
    lore_entries = relationship('LoreEntry', back_populates='world')

class Persona(Base):
    __tablename__ = 'personas'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    age = Column(Integer, nullable=True)
    appearance = Column(Text, nullable=True)
    personality = Column(Text, nullable=True)
    backstory = Column(Text, nullable=True)
    skills = Column(Text, nullable=True)
    goal = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    world_id = Column(Integer, ForeignKey('worlds.id'))
    room = Column(String(100), default='Главная')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship('User', foreign_keys=[user_id])
    world = relationship('World', back_populates='personas')
    memories = relationship('Memory', back_populates='persona')

class Character(Base):
    __tablename__ = 'characters'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    personality = Column(Text, nullable=True)
    backstory = Column(Text, nullable=True)
    role = Column(String(100), nullable=True)
    greeting = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    world_id = Column(Integer, ForeignKey('worlds.id'))
    room = Column(String(100), default='Главная')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship('User', foreign_keys=[user_id])
    world = relationship('World', back_populates='characters')

class LoreEntry(Base):
    __tablename__ = 'lore_entries'
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(50))
    world_id = Column(Integer, ForeignKey('worlds.id'))
    room = Column(String(100), default='Главная')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tags = Column(JSON, default=list)
    world = relationship('World', back_populates='lore_entries')

class Memory(Base):
    __tablename__ = 'memories'
    id = Column(Integer, primary_key=True)
    persona_id = Column(Integer, ForeignKey('personas.id'))
    character_id = Column(Integer, ForeignKey('characters.id'), nullable=True)
    content = Column(Text, nullable=False)
    memory_type = Column(String(20), default='personal')
    importance = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_auto = Column(Boolean, default=False)
    room = Column(String(100), default='Главная')
    persona = relationship('Persona', back_populates='memories')
    character = relationship('Character')

class ChatHistory(Base):
    __tablename__ = 'chat_history'
    id = Column(Integer, primary_key=True)
    persona_id = Column(Integer, ForeignKey('personas.id'))
    character_id = Column(Integer, ForeignKey('characters.id'))
    world_id = Column(Integer, ForeignKey('worlds.id'))
    user_message = Column(Text)
    bot_response = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    room = Column(String(100), default='Главная')
    persona = relationship('Persona')
    character = relationship('Character')

class Checkpoint(Base):
    __tablename__ = 'checkpoints'
    id = Column(Integer, primary_key=True)
    persona_id = Column(Integer, ForeignKey('personas.id'))
    character_id = Column(Integer, ForeignKey('characters.id'))
    title = Column(String(200))
    description = Column(Text)
    state = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    room = Column(String(100), default='Главная')
    persona = relationship('Persona')
    character = relationship('Character')

# ============================================
# БАЗА ДАННЫХ
# ============================================

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ База данных инициализирована")

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# ============================================
# АВТОУДАЛЕНИЕ СООБЩЕНИЙ
# ============================================

async def delete_after_delay(context, chat_id, message_id, delay=4):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

async def get_active_persona(user_id, room=None):
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user or not user.active_persona_id:
            return None, None
        room = room or user.current_room or "Главная"
        persona_result = await session.execute(
            select(Persona).where(
                Persona.id == user.active_persona_id,
                Persona.room == room
            )
        )
        persona = persona_result.scalar_one_or_none()
        return user, persona

async def get_active_character(user_id, room=None):
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user or not user.active_character_id:
            return None, None
        room = room or user.current_room or "Главная"
        character_result = await session.execute(
            select(Character).where(
                Character.id == user.active_character_id,
                Character.room == room
            )
        )
        character = character_result.scalar_one_or_none()
        return user, character

# ============================================
# МЕНЮ
# ============================================

def get_main_keyboard():
    keyboard = [
        ["👤 Моя персона", "🎭 Персонажи (боты)"],
        ["🌍 Миры", "📚 Лорбук"],
        ["🧠 Память", "🔍 Поиск по памяти"],
        ["🎬 Режим сценария", "📂 Комнаты"],
        ["⚙️ Настройки"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_persona_keyboard():
    keyboard = [
        ["📋 Моя персона", "➕ Создать/редактировать"],
        ["👤 Выбрать персону", "🔙 Назад"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_characters_keyboard():
    keyboard = [
        ["📋 Список персонажей", "➕ Создать персонажа"],
        ["👤 Выбрать персонажа", "✏️ Редактировать"],
        ["🎭 Генерация персонажа", "🔄 Сбросить чат"],
        ["🔙 Назад"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_worlds_keyboard():
    keyboard = [
        ["🌍 Список миров", "➕ Создать мир"],
        ["🌐 Выбрать мир", "✏️ Редактировать мир"],
        ["🌍 Генерация мира", "⏸️ Вкл/Выкл мир"],
        ["🔙 Назад"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_settings_keyboard():
    keyboard = [
        ["🌐 Вкл/Выкл мир", "📏 Длина ответа"],
        ["🔄 Сбросить чат", "🔙 Назад"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_rooms_keyboard(rooms, current_room):
    keyboard = []
    for room in rooms:
        if room == current_room:
            keyboard.append([f"✅ {room}"])
        else:
            keyboard.append([f"📌 {room}"])
    keyboard.append(["🔀 Выбрать комнату"])
    keyboard.append(["➕ Создать комнату", "✏️ Переименовать"])
    keyboard.append(["🗑️ Удалить комнату"])
    keyboard.append(["🔙 Назад в меню"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ============================================
# ОБРАБОТЧИКИ
# ============================================

(PERSONA_NAME, PERSONA_AGE, PERSONA_APPEARANCE, PERSONA_PERSONALITY, PERSONA_BACKSTORY, PERSONA_SKILLS, PERSONA_GOAL) = range(7)
(CHAR_NAME, CHAR_DESC, CHAR_PERSONALITY, CHAR_BACKSTORY, CHAR_ROLE, CHAR_GREETING) = range(6)
(WORLD_NAME, WORLD_DESC) = range(2)
(LORE_TITLE, LORE_CONTENT, LORE_CATEGORY, LORE_TAGS) = range(4)

# ----- КОМНАТЫ -----

async def create_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    room_name = ' '.join(context.args) if context.args else None
    
    if not room_name:
        await update.message.reply_text("❌ Укажите название комнаты. Пример: /create_room Моя история")
        return
    
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        rooms = user.rooms or ["Главная"]
        if room_name in rooms:
            await update.message.reply_text(f"❌ Комната '{room_name}' уже существует!")
            return
        
        rooms.append(room_name)
        user.rooms = rooms
        user.current_room = room_name
        await session.commit()
        await update.message.reply_text(f"✅ Комната '{room_name}' создана и активирована!")

async def switch_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    room_name = ' '.join(context.args) if context.args else None
    
    if not room_name:
        await update.message.reply_text("❌ Укажите название комнаты. Пример: /switch_room Моя история")
        return
    
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        rooms = user.rooms or ["Главная"]
        if room_name not in rooms:
            await update.message.reply_text(f"❌ Комната '{room_name}' не найдена!")
            return
        
        user.current_room = room_name
        await session.commit()
        await update.message.reply_text(f"✅ Переключено на комнату: **{room_name}**", parse_mode='Markdown')

async def list_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        rooms = user.rooms or ["Главная"]
        current = user.current_room or "Главная"
        
        text = "📂 **Твои комнаты:**\n\n"
        for room in rooms:
            if room == current:
                text += f"✅ **{room}** (активная)\n"
            else:
                text += f"📌 {room}\n"
        await update.message.reply_text(text, parse_mode='Markdown')

async def rename_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text("❌ Укажите старое и новое название. Пример: /rename_room Старое Новое")
        return
    
    old_name = context.args[0]
    new_name = ' '.join(context.args[1:])
    
    if old_name == "Главная":
        await update.message.reply_text("❌ Нельзя переименовать главную комнату")
        return
    
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        rooms = user.rooms or ["Главная"]
        if old_name not in rooms:
            await update.message.reply_text(f"❌ Комната '{old_name}' не найдена")
            return
        if new_name in rooms and new_name != old_name:
            await update.message.reply_text(f"❌ Комната '{new_name}' уже существует")
            return
        
        index = rooms.index(old_name)
        rooms[index] = new_name
        if user.current_room == old_name:
            user.current_room = new_name
        user.rooms = rooms
        await session.commit()
        await update.message.reply_text(f"✅ Комната '{old_name}' переименована в '{new_name}'")

async def delete_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    room_name = ' '.join(context.args) if context.args else None
    
    if not room_name:
        await update.message.reply_text("❌ Укажите название комнаты для удаления. Пример: /delete_room Моя история")
        return
    
    if room_name == "Главная":
        await update.message.reply_text("❌ Нельзя удалить главную комнату")
        return
    
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        rooms = user.rooms or ["Главная"]
        if room_name not in rooms:
            await update.message.reply_text(f"❌ Комната '{room_name}' не найдена")
            return
        
        rooms.remove(room_name)
        if user.current_room == room_name:
            user.current_room = "Главная"
        user.rooms = rooms
        await session.commit()
        
        await session.execute(delete(Persona).where(Persona.room == room_name))
        await session.execute(delete(Character).where(Character.room == room_name))
        await session.execute(delete(LoreEntry).where(LoreEntry.room == room_name))
        await session.execute(delete(Memory).where(Memory.room == room_name))
        await session.execute(delete(ChatHistory).where(ChatHistory.room == room_name))
        await session.execute(delete(Checkpoint).where(Checkpoint.room == room_name))
        await session.execute(delete(World).where(World.created_room == room_name))
        await session.commit()
        await update.message.reply_text(f"✅ Комната '{room_name}' удалена вместе со всеми данными!")

async def rooms_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        rooms = user.rooms or ["Главная"]
        current = user.current_room or "Главная"
        await update.message.reply_text(
            f"📂 **Управление комнатами**\n\nТекущая: {current}\nВсего комнат: {len(rooms)}",
            reply_markup=get_rooms_keyboard(rooms, current),
            parse_mode='Markdown'
        )

async def select_room_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        rooms = user.rooms or ["Главная"]
        current = user.current_room or "Главная"
        
        keyboard = []
        for room in rooms:
            if room == current:
                keyboard.append([f"✅ {room} (активная)"])
            else:
                keyboard.append([f"📌 {room}"])
        keyboard.append(["🔙 Назад в меню"])
        
        await update.message.reply_text(
            "🔀 **Выбери комнату:**\n\nНажми на название, чтобы переключиться.",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
            parse_mode='Markdown'
        )

async def switch_room_by_name(update: Update, context: ContextTypes.DEFAULT_TYPE, room_name):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        rooms = user.rooms or ["Главная"]
        if room_name not in rooms:
            await update.message.reply_text(f"❌ Комната '{room_name}' не найдена")
            return
        
        user.current_room = room_name
        await session.commit()
        await update.message.reply_text(f"✅ Переключено на комнату: **{room_name}**\n\nТеперь все действия будут в этой комнате.", parse_mode='Markdown')
        await main_menu(update, context)

# ============================================
# РЕДАКТОР ПЕРСОНАЖЕЙ
# ============================================

async def character_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        room = user.current_room or "Главная"
        characters_result = await session.execute(
            select(Character).where(Character.user_id == user.id, Character.room == room)
        )
        characters = characters_result.scalars().all()
        if not characters:
            await update.message.reply_text("❌ У вас нет персонажей в этой комнате")
            return
        
        keyboard = []
        for char in characters:
            keyboard.append([InlineKeyboardButton(f"✏️ {char.name}", callback_data=f"edit_char_{char.id}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_characters")])
        
        await update.message.reply_text(
            "✏️ **Выберите персонажа для редактирования:**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def character_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_characters":
        await query.edit_message_text("🎭 **Управление персонажами**", reply_markup=get_characters_keyboard(), parse_mode='Markdown')
        return
    
    char_id = int(query.data.split('_')[2])
    context.user_data['edit_char_id'] = char_id
    
    keyboard = [
        [InlineKeyboardButton("📝 Имя", callback_data="edit_field_name")],
        [InlineKeyboardButton("📝 Описание", callback_data="edit_field_desc")],
        [InlineKeyboardButton("📝 Характер", callback_data="edit_field_personality")],
        [InlineKeyboardButton("📝 Предыстория", callback_data="edit_field_backstory")],
        [InlineKeyboardButton("📝 Роль", callback_data="edit_field_role")],
        [InlineKeyboardButton("📝 Приветствие", callback_data="edit_field_greeting")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_characters")]
    ]
    
    async for session in get_db():
        character = await session.get(Character, char_id)
        if not character:
            await query.edit_message_text("❌ Персонаж не найден")
            return
        
        text = f"""✏️ **Редактирование персонажа:** {character.name}

━━━━━━━━━━━━━━━━━━━━━━
📝 **Имя:** {character.name}
📝 **Описание:** {character.description or 'не указано'}
📝 **Характер:** {character.personality or 'не указан'}
📝 **Предыстория:** {character.backstory or 'не указана'}
📝 **Роль:** {character.role or 'не указана'}
📝 **Приветствие:** {character.greeting or 'не указано'}
━━━━━━━━━━━━━━━━━━━━━━

Выберите, что хотите изменить:"""
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def character_edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace('edit_field_', '')
    context.user_data['edit_field'] = field
    
    field_names = {
        'name': 'новое имя',
        'desc': 'новое описание',
        'personality': 'новый характер',
        'backstory': 'новую предысторию',
        'role': 'новую роль',
        'greeting': 'новое приветствие'
    }
    
    await query.edit_message_text(f"✏️ Введите **{field_names.get(field, field)}** для персонажа:", parse_mode='Markdown')
    return 1

async def character_edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    char_id = context.user_data.get('edit_char_id')
    field = context.user_data.get('edit_field')
    value = update.message.text
    
    if not char_id or not field:
        await update.message.reply_text("❌ Ошибка")
        return ConversationHandler.END
    
    async for session in get_db():
        character = await session.get(Character, char_id)
        if not character:
            await update.message.reply_text("❌ Персонаж не найден")
            return ConversationHandler.END
        
        field_map = {
            'name': 'name',
            'desc': 'description',
            'personality': 'personality',
            'backstory': 'backstory',
            'role': 'role',
            'greeting': 'greeting'
        }
        setattr(character, field_map.get(field, field), value)
        await session.commit()
        await update.message.reply_text(f"✅ **Поле обновлено!**\n\nНовое значение: {value}", parse_mode='Markdown')
    
    return ConversationHandler.END

character_edit_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(character_edit_field_callback, pattern="^edit_field_")],
    states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, character_edit_save)]},
    fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Отменено"))]
)

# ============================================
# РЕДАКТОР МИРА
# ============================================

async def world_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        room = user.current_room or "Главная"
        worlds_result = await session.execute(
            select(World).where(World.created_by == user.id, World.created_room == room)
        )
        worlds = worlds_result.scalars().all()
        if not worlds:
            await update.message.reply_text("❌ У вас нет миров в этой комнате")
            return
        
        keyboard = []
        for world in worlds:
            keyboard.append([InlineKeyboardButton(f"✏️ {world.name}", callback_data=f"edit_world_{world.id}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_worlds")])
        
        await update.message.reply_text(
            "✏️ **Выберите мир для редактирования:**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def world_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_worlds":
        await query.edit_message_text("🌍 **Управление мирами**", reply_markup=get_worlds_keyboard(), parse_mode='Markdown')
        return
    
    world_id = int(query.data.split('_')[2])
    context.user_data['edit_world_id'] = world_id
    
    keyboard = [
        [InlineKeyboardButton("📝 Название", callback_data="edit_world_name")],
        [InlineKeyboardButton("📝 Описание", callback_data="edit_world_desc")],
        [InlineKeyboardButton("📚 Добавить лор", callback_data="edit_world_lore")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_worlds")]
    ]
    
    async for session in get_db():
        world = await session.get(World, world_id)
        if not world:
            await query.edit_message_text("❌ Мир не найден")
            return
        
        text = f"""✏️ **Редактирование мира:** {world.name}

━━━━━━━━━━━━━━━━━━━━━━
📝 **Название:** {world.name}
📝 **Описание:** {world.description[:200] + '...' if len(world.description) > 200 else world.description}
━━━━━━━━━━━━━━━━━━━━━━

Выберите, что хотите изменить:"""
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def world_edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace('edit_world_', '')
    context.user_data['edit_world_field'] = field
    
    field_names = {
        'name': 'новое название',
        'desc': 'новое описание',
        'lore': 'новый лор (факты, локации, история)'
    }
    
    await query.edit_message_text(f"✏️ Введите **{field_names.get(field, field)}** для мира:", parse_mode='Markdown')
    return 1

async def world_edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    world_id = context.user_data.get('edit_world_id')
    field = context.user_data.get('edit_world_field')
    value = update.message.text
    user_id = update.effective_user.id
    
    if not world_id or not field:
        await update.message.reply_text("❌ Ошибка")
        return ConversationHandler.END
    
    async for session in get_db():
        world = await session.get(World, world_id)
        if not world:
            await update.message.reply_text("❌ Мир не найден")
            return ConversationHandler.END
        
        if field == 'name':
            world.name = value
            await session.commit()
            await update.message.reply_text(f"✅ **Название мира обновлено!**\n\nНовое название: {value}", parse_mode='Markdown')
        elif field == 'desc':
            world.description = value
            await session.commit()
            await update.message.reply_text(f"✅ **Описание мира обновлено!**", parse_mode='Markdown')
        elif field == 'lore':
            user_result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = user_result.scalar_one_or_none()
            room = user.current_room or "Главная" if user else "Главная"
            lore = LoreEntry(
                title=f"Дополнение к миру: {world.name}",
                content=value,
                category="редактирование",
                world_id=world_id,
                room=room,
                tags=["добавлено", "пользователь"]
            )
            session.add(lore)
            await session.commit()
            await update.message.reply_text(f"✅ **Лор добавлен!**\n\n{value}", parse_mode='Markdown')
    
    return ConversationHandler.END

world_edit_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(world_edit_field_callback, pattern="^edit_world_")],
    states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, world_edit_save)]},
    fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Отменено"))]
)

# ----- СБРОС ЧАТА -----

async def reset_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("✅ Да, сбросить", callback_data="reset_confirm")],
        [InlineKeyboardButton("❌ Нет, отмена", callback_data="reset_cancel")]
    ]
    await update.message.reply_text(
        "⚠️ **Сброс чата**\n\nЭто действие: \n- Удалит всю историю диалогов в этой комнате\n- Удалит воспоминания\n- Очистит память персонажа\n\nПерсонажи и миры останутся.\n\nВы уверены?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def reset_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            await query.edit_message_text("❌ Ошибка")
            return
        room = user.current_room or "Главная"
        await session.execute(delete(ChatHistory).where(ChatHistory.room == room, ChatHistory.persona_id == user.active_persona_id))
        await session.execute(delete(Memory).where(Memory.room == room, Memory.persona_id == user.active_persona_id))
        await session.execute(delete(Checkpoint).where(Checkpoint.room == room, Checkpoint.persona_id == user.active_persona_id))
        await session.commit()
    await query.edit_message_text("✅ **Чат сброшен!**\n\nВсе диалоги и воспоминания удалены.\nМожно начинать новую игру.", parse_mode='Markdown')
    await main_menu(update, context)

async def reset_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ **Сброс отменён**", parse_mode='Markdown')
    await main_menu(update, context)

# ----- ГЛАВНОЕ МЕНЮ -----

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user, persona = await get_active_persona(user_id)
    _, character = await get_active_character(user_id)
    room = user.current_room if user else "Главная"
    persona_text = persona.name if persona else "❌ не создана"
    char_text = character.name if character else "❌ не выбран"
    text = f"""🌟 **Главное меню HFSI RPG Bot**

📂 Комната: **{room}**
👤 Персона: **{persona_text}**
🎭 Активный бот: **{char_text}**

Выберите раздел:"""
    await update.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "👤 Моя персона":
        user, persona = await get_active_persona(user_id)
        char_text = f"👤 Активная персона: **{persona.name}**" if persona else "❌ Персона не создана"
        await update.message.reply_text(f"👤 **Управление персоной**{char_text}", reply_markup=get_persona_keyboard(), parse_mode='Markdown')
    elif text == "🎭 Персонажи (боты)":
        _, character = await get_active_character(user_id)
        char_text = f"🎭 Активный бот: **{character.name}**" if character else "❌ Бот не выбран"
        await update.message.reply_text(f"🎭 **Управление персонажами-ботами**{char_text}\n\nЗдесь вы создаёте ботов, с которыми будете общаться!", reply_markup=get_characters_keyboard(), parse_mode='Markdown')
    elif text == "🌍 Миры":
        await update.message.reply_text("🌍 **Управление мирами**", reply_markup=get_worlds_keyboard(), parse_mode='Markdown')
    elif text == "📚 Лорбук":
        await lore_add_start(update, context)
    elif text == "🧠 Память":
        await memory_add_start(update, context)
    elif text == "🔍 Поиск по памяти":
        await update.message.reply_text("🔍 **Поиск по памяти**\n\nНапишите слово или фразу для поиска:", parse_mode='Markdown')
        return 2
    elif text == "🎬 Режим сценария":
        await toggle_scenario(update, context)
    elif text == "📂 Комнаты":
        await rooms_menu(update, context)
    elif text == "⚙️ Настройки":
        await update.message.reply_text("⚙️ **Настройки**", reply_markup=get_settings_keyboard(), parse_mode='Markdown')
    elif text == "🔙 Назад" or text == "🔙 Назад в меню":
        await main_menu(update, context)
    elif text == "📋 Моя персона":
        await show_persona_profile(update, context)
    elif text == "➕ Создать/редактировать":
        await persona_new_start(update, context)
    elif text == "👤 Выбрать персону":
        await persona_select_command(update, context)
    elif text == "📋 Список персонажей":
        await character_list(update, context)
    elif text == "➕ Создать персонажа":
        await character_new_start(update, context)
    elif text == "👤 Выбрать персонажа":
        await character_select_command(update, context)
    elif text == "✏️ Редактировать":
        await character_edit_start(update, context)
    elif text == "🎭 Генерация персонажа":
        await generate_character_start(update, context)
        return 1
    elif text == "🔄 Сбросить чат":
        await reset_chat(update, context)
    elif text == "🌍 Список миров":
        await world_list(update, context)
    elif text == "➕ Создать мир":
        await world_new_start(update, context)
    elif text == "🌐 Выбрать мир":
        await world_select_start(update, context)
    elif text == "✏️ Редактировать мир":
        await world_edit_start(update, context)
    elif text == "🌍 Генерация мира":
        await generate_world_start(update, context)
        return 1
    elif text == "⏸️ Вкл/Выкл мир":
        await toggle_world(update, context)
    elif text == "📏 Длина ответа":
        await set_max_tokens(update, context)
    elif text == "🔀 Выбрать комнату":
        await select_room_menu(update, context)
    elif text.startswith("✅") or text.startswith("📌"):
        room_name = text.replace("✅", "").replace("📌", "").replace("(активная)", "").strip()
        if room_name:
            await switch_room_by_name(update, context, room_name)
    elif text == "➕ Создать комнату":
        await update.message.reply_text("📝 Введите название новой комнаты:\n/create_room Название")
    elif text == "✏️ Переименовать":
        await update.message.reply_text("✏️ Введите команду для переименования:\n/rename_room Старое_название Новое_название")
    elif text == "🗑️ Удалить комнату":
        await update.message.reply_text("🗑️ Введите команду для удаления:\n/delete_room Название_комнаты")
    else:
        await handle_message(update, context)

# ============================================
# ПРОПУСК ПЕРСОНЫ
# ============================================

async def persona_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ Создать персону", callback_data="persona_create")],
        [InlineKeyboardButton("⏭️ Пропустить", callback_data="persona_skip")]
    ]
    await update.message.reply_text(
        "👤 **Создание персоны**\n\nПерсона — это вы. Она нужна для ролевой игры.\n\nХотите создать персону или пропустить?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return PERSONA_NAME

async def persona_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=query.from_user.username)
            session.add(user)
            await session.commit()
        user.active_persona_id = None
        await session.commit()
    await query.edit_message_text("⏭️ **Персона пропущена**\n\nВы можете создать её позже через меню '👤 Моя персона'.", parse_mode='Markdown')
    
    user_id = query.from_user.id
    user, persona = await get_active_persona(user_id)
    _, character = await get_active_character(user_id)
    room = user.current_room if user else "Главная"
    persona_text = persona.name if persona else "❌ не создана"
    char_text = character.name if character else "❌ не выбран"
    text = f"""🌟 **Главное меню HFSI RPG Bot**

📂 Комната: **{room}**
👤 Персона: **{persona_text}**
🎭 Активный бот: **{char_text}**

Выберите раздел:"""
    await query.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode='Markdown')
    return ConversationHandler.END

async def persona_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👤 **Создание персоны**\n\n**Шаг 1 из 7:** Введите ваше **имя**:", parse_mode='Markdown')
    return PERSONA_NAME

async def persona_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_name'] = update.message.text
    await update.message.reply_text(f"✅ Имя: {context.user_data['persona_name']}\n\n**Шаг 2 из 7:** Введите **возраст**:", parse_mode='Markdown')
    return PERSONA_AGE

async def persona_new_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['persona_age'] = int(update.message.text)
    except ValueError:
        context.user_data['persona_age'] = None
    await update.message.reply_text(f"✅ Возраст: {context.user_data['persona_age'] or 'не указан'}\n\n**Шаг 3 из 7:** Опишите **внешность**:", parse_mode='Markdown')
    return PERSONA_APPEARANCE

async def persona_new_appearance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_appearance'] = update.message.text
    await update.message.reply_text("**Шаг 4 из 7:** Опишите **характер**:", parse_mode='Markdown')
    return PERSONA_PERSONALITY

async def persona_new_personality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_personality'] = update.message.text
    await update.message.reply_text("**Шаг 5 из 7:** Напишите **предысторию**:", parse_mode='Markdown')
    return PERSONA_BACKSTORY

async def persona_new_backstory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_backstory'] = update.message.text
    await update.message.reply_text("**Шаг 6 из 7:** Опишите **навыки/способности**:", parse_mode='Markdown')
    return PERSONA_SKILLS

async def persona_new_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_skills'] = update.message.text
    await update.message.reply_text("**Шаг 7 из 7:** Какая ваша **цель**?", parse_mode='Markdown')
    return PERSONA_GOAL

async def persona_new_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_goal'] = update.message.text
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.flush()
        room = user.current_room or "Главная"
        if user.active_persona_id:
            persona_result = await session.execute(select(Persona).where(Persona.id == user.active_persona_id, Persona.room == room))
            persona = persona_result.scalar_one_or_none()
            if persona:
                persona.name = context.user_data['persona_name']
                persona.age = context.user_data.get('persona_age')
                persona.appearance = context.user_data.get('persona_appearance')
                persona.personality = context.user_data.get('persona_personality')
                persona.backstory = context.user_data.get('persona_backstory')
                persona.skills = context.user_data.get('persona_skills')
                persona.goal = context.user_data.get('persona_goal')
                persona.room = room
                await session.commit()
                await update.message.reply_text(f"✅ **Персона обновлена!**\n\nИмя: {persona.name}", parse_mode='Markdown')
                return ConversationHandler.END
        persona = Persona(
            name=context.user_data['persona_name'],
            age=context.user_data.get('persona_age'),
            appearance=context.user_data.get('persona_appearance'),
            personality=context.user_data.get('persona_personality'),
            backstory=context.user_data.get('persona_backstory'),
            skills=context.user_data.get('persona_skills'),
            goal=context.user_data.get('persona_goal'),
            user_id=user.id,
            room=room
        )
        session.add(persona)
        await session.commit()
        user.active_persona_id = persona.id
        await session.commit()
        await update.message.reply_text(f"✅ **Персона создана!**\n\nИмя: {persona.name}", parse_mode='Markdown')
    return ConversationHandler.END

persona_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('persona_new', persona_new_start),
        MessageHandler(filters.Regex('^➕ Создать/редактировать$'), persona_new_start),
        CallbackQueryHandler(persona_create_callback, pattern="^persona_create$")
    ],
    states={
        PERSONA_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, persona_new_name)],
        PERSONA_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, persona_new_age)],
        PERSONA_APPEARANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, persona_new_appearance)],
        PERSONA_PERSONALITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, persona_new_personality)],
        PERSONA_BACKSTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, persona_new_backstory)],
        PERSONA_SKILLS: [MessageHandler(filters.TEXT & ~filters.COMMAND, persona_new_skills)],
        PERSONA_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, persona_new_goal)],
    },
    fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Отменено"))]
)

async def persona_select_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        room = user.current_room or "Главная"
        personas_result = await session.execute(select(Persona).where(Persona.user_id == user.id, Persona.room == room))
        personas = personas_result.scalars().all()
        if not personas:
            await update.message.reply_text("❌ У вас нет персоны в этой комнате")
            return
        keyboard = []
        for p in personas:
            status = "✅" if user.active_persona_id == p.id else "⬜"
            keyboard.append([InlineKeyboardButton(f"{status} {p.name}", callback_data=f"select_persona_{p.id}")])
        await update.message.reply_text("👤 **Выберите персону:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def persona_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    persona_id = int(query.data.split('_')[2])
    async for session in get_db():
        persona = await session.get(Persona, persona_id)
        if not persona:
            await query.edit_message_text("❌ Персона не найдена")
            return
        user_result = await session.execute(select(User).where(User.telegram_id == query.from_user.id))
        user = user_result.scalar_one_or_none()
        if user:
            user.active_persona_id = persona_id
            await session.commit()
            await query.edit_message_text(f"✅ **Выбрана персона:** {persona.name}")

async def show_persona_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        if not user.active_persona_id:
            await update.message.reply_text("❌ У вас нет персоны. Создайте её!")
            return
        room = user.current_room or "Главная"
        persona_result = await session.execute(select(Persona).where(Persona.id == user.active_persona_id, Persona.room == room))
        persona = persona_result.scalar_one_or_none()
        if not persona:
            await update.message.reply_text("❌ Персона не найдена в этой комнате")
            return
        text = f"""📋 **Моя персона**

━━━━━━━━━━━━━━━━━━━━━━
**Имя:** {persona.name}
**Возраст:** {persona.age or 'не указан'}
**Мир:** {persona.world.name if persona.world else 'не выбран'}
━━━━━━━━━━━━━━━━━━━━━━

**Внешность:**
{persona.appearance or 'не указана'}

**Характер:**
{persona.personality or 'не указан'}

**Предыстория:**
{persona.backstory or 'не указана'}

**Навыки:**
{persona.skills or 'не указаны'}

**Цель:**
{persona.goal or 'не указана'}
"""
        await update.message.reply_text(text, parse_mode='Markdown')

# ----- ПЕРСОНАЖИ (БОТЫ) -----

async def character_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        room = user.current_room or "Главная"
        characters_result = await session.execute(select(Character).where(Character.user_id == user.id, Character.room == room))
        characters = characters_result.scalars().all()
        if not characters:
            await update.message.reply_text("❌ У вас нет персонажей в этой комнате")
            return
        text = "🎭 **Ваши персонажи-боты:**\n\n"
        for char in characters:
            status = "🟢" if user.active_character_id == char.id else "⬜"
            world_name = char.world.name if char.world else "Без мира"
            text += f"{status} **{char.name}**\n"
            text += f"   Роль: {char.role or 'не указана'}\n"
            text += f"   Мир: {world_name}\n"
            text += f"   ID: {char.id}\n\n"
        text += "\n🟢 - активный персонаж"
        await update.message.reply_text(text, parse_mode='Markdown')

async def character_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎭 **Создание персонажа-бота**\n\n**Шаг 1 из 6:** Введите **имя**:", parse_mode='Markdown')
    return CHAR_NAME

async def character_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_name'] = update.message.text
    await update.message.reply_text(f"✅ Имя: {context.user_data['char_name']}\n\n**Шаг 2 из 6:** Опишите **кто это**:", parse_mode='Markdown')
    return CHAR_DESC

async def character_new_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_desc'] = update.message.text
    await update.message.reply_text("**Шаг 3 из 6:** Опишите **характер**:", parse_mode='Markdown')
    return CHAR_PERSONALITY

async def character_new_personality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_personality'] = update.message.text
    await update.message.reply_text("**Шаг 4 из 6:** Напишите **предысторию**:", parse_mode='Markdown')
    return CHAR_BACKSTORY

async def character_new_backstory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_backstory'] = update.message.text
    await update.message.reply_text("**Шаг 5 из 6:** Укажите **роль** в мире:", parse_mode='Markdown')
    return CHAR_ROLE

async def character_new_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_role'] = update.message.text
    await update.message.reply_text("**Шаг 6 из 6:** Напишите **приветствие**:", parse_mode='Markdown')
    return CHAR_GREETING

async def character_new_greeting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_greeting'] = update.message.text
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.flush()
        room = user.current_room or "Главная"
        character = Character(
            name=context.user_data['char_name'],
            description=context.user_data['char_desc'],
            personality=context.user_data['char_personality'],
            backstory=context.user_data['char_backstory'],
            role=context.user_data['char_role'],
            greeting=context.user_data['char_greeting'],
            user_id=user.id,
            room=room
        )
        session.add(character)
        await session.commit()
        await update.message.reply_text(f"✅ **Персонаж-бот создан!**\n\nИмя: {character.name}\nРоль: {character.role}", parse_mode='Markdown')
    return ConversationHandler.END

character_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('character_new', character_new_start),
        MessageHandler(filters.Regex('^➕ Создать персонажа$'), character_new_start)
    ],
    states={
        CHAR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, character_new_name)],
        CHAR_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, character_new_desc)],
        CHAR_PERSONALITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, character_new_personality)],
        CHAR_BACKSTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, character_new_backstory)],
        CHAR_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, character_new_role)],
        CHAR_GREETING: [MessageHandler(filters.TEXT & ~filters.COMMAND, character_new_greeting)],
    },
    fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Отменено"))]
)

async def character_select_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        room = user.current_room or "Главная"
        characters_result = await session.execute(select(Character).where(Character.user_id == user.id, Character.room == room))
        characters = characters_result.scalars().all()
        if not characters:
            await update.message.reply_text("❌ У вас нет персонажей в этой комнате")
            return
        keyboard = []
        for char in characters:
            status = "✅" if user.active_character_id == char.id else "⬜"
            keyboard.append([InlineKeyboardButton(f"{status} {char.name}", callback_data=f"select_char_{char.id}")])
        await update.message.reply_text("🎭 **Выберите персонажа-бота:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def character_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    char_id = int(query.data.split('_')[2])
    async for session in get_db():
        character = await session.get(Character, char_id)
        if not character:
            await query.edit_message_text("❌ Персонаж не найден")
            return
        user_result = await session.execute(select(User).where(User.telegram_id == query.from_user.id))
        user = user_result.scalar_one_or_none()
        if user:
            user.active_character_id = char_id
            await session.commit()
            await query.edit_message_text(f"✅ **Выбран персонаж:** {character.name}\n\n{character.greeting or 'Приветствую тебя, путник!'}")

# ----- МИРЫ -----

async def world_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        room = user.current_room or "Главная"
        worlds_result = await session.execute(select(World).where(World.created_by == user.id, World.created_room == room))
        worlds = worlds_result.scalars().all()
        if not worlds:
            await update.message.reply_text("❌ Нет созданных миров в этой комнате")
            return
        text = "🌍 **Доступные миры:**\n\n"
        for world in worlds:
            text += f"📌 **{world.name}** (ID: {world.id})\n"
            text += f"   {world.description[:100]}...\n\n"
        await update.message.reply_text(text, parse_mode='Markdown')

async def world_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌍 **Создание мира**\n\nВведите название:", parse_mode='Markdown')
    return WORLD_NAME

async def world_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['world_name'] = update.message.text
    await update.message.reply_text("📝 Введите описание мира:", parse_mode='Markdown')
    return WORLD_DESC

async def world_new_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['world_desc'] = update.message.text
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.flush()
        room = user.current_room or "Главная"
        world = World(
            name=context.user_data['world_name'],
            description=context.user_data['world_desc'],
            created_by=user.id,
            created_room=room
        )
        session.add(world)
        await session.commit()
        await update.message.reply_text(f"✅ **Мир создан!**\n\n🌍 {world.name}\n📝 {world.description}\n🆔 ID: {world.id}", parse_mode='Markdown')
    return ConversationHandler.END

world_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('world_new', world_new_start),
        MessageHandler(filters.Regex('^➕ Создать мир$'), world_new_start)
    ],
    states={
        WORLD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, world_new_name)],
        WORLD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, world_new_description)],
    },
    fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Отменено"))]
)

async def world_select_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        room = user.current_room or "Главная"
        worlds_result = await session.execute(select(World).where(World.created_by == user.id, World.created_room == room))
        worlds = worlds_result.scalars().all()
        if not worlds:
            await update.message.reply_text("❌ Нет миров в этой комнате")
            return
        keyboard = []
        for world in worlds:
            keyboard.append([InlineKeyboardButton(f"🌍 {world.name}", callback_data=f"select_world_{world.id}")])
        await update.message.reply_text("🌐 **Выберите мир:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def world_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    world_id = int(query.data.split('_')[2])
    user_id = query.from_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=query.from_user.username)
            session.add(user)
            await session.commit()
        if user.active_persona_id:
            persona = await session.get(Persona, user.active_persona_id)
            if persona:
                persona.world_id = world_id
        if user.active_character_id:
            character = await session.get(Character, user.active_character_id)
            if character:
                character.world_id = world_id
        await session.commit()
        world = await session.get(World, world_id)
        await query.edit_message_text(f"✅ Мир **{world.name}** выбран!")

# ----- ГЕНЕРАЦИЯ МИРА -----

async def generate_world_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌍 **Генерация мира**\n\nОпиши, какой мир ты хочешь создать.\n\nНапример:\n— «Мир Гарри Поттера, но в стиле киберпанк»\n— «Средневековое фэнтези с драконами и магией»\n— «Постапокалипсис, где люди живут в подземных городах»\n\nНапиши описание, и я создам для тебя мир с историей, географией и лором!\n\n❌ Если не понравится результат — напиши /regenerate",
        parse_mode='Markdown'
    )
    return 1

async def generate_world_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass
    
    await update.message.chat.send_action(action="typing")
    
    prompt = f"""Создай подробный мир на основе описания пользователя.

Описание пользователя: {user_message}

Создай мир со следующими разделами:
1. Название мира (краткое, запоминающееся)
2. Краткое описание (2-3 предложения)
3. География (основные локации)
4. История (ключевые события)
5. Магия/технологии (что есть в этом мире)
6. Основные расы или народы
7. Интересные факты

Ответ должен быть структурированным и вдохновляющим."""
    
    openai.api_key = POLZA_API_KEY
    openai.base_url = "https://polza.ai/api/v1/"
    
    try:
        response = openai.chat.completions.create(
            model=POLZA_MODEL,
            messages=[{"role": "system", "content": prompt}],
            temperature=0.9,
            max_tokens=2500,
            extra_headers={"HTTP-Referer": "https://colab.research.google.com/"}
        )
        generated_text = response.choices[0].message.content
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка генерации: {str(e)}")
        return ConversationHandler.END
    
    lines = generated_text.split('\n')
    world_name = "Сгенерированный мир"
    for line in lines:
        if line.startswith("1.") or line.startswith("Название"):
            world_name = line.replace("1.", "").replace("Название:", "").strip()
            if len(world_name) > 50:
                world_name = world_name[:50]
            break
    
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        room = user.current_room or "Главная"
        existing_result = await session.execute(select(World).where(World.name == world_name, World.created_room == room))
        if existing_result.scalar_one_or_none():
            world_name = f"{world_name} (копия)"
        
        world = World(
            name=world_name,
            description=generated_text[:500],
            created_by=user.id,
            created_room=room
        )
        session.add(world)
        await session.commit()
        
        lore = LoreEntry(
            title=f"Описание мира: {world_name}",
            content=generated_text,
            category="генерация",
            world_id=world.id,
            room=room,
            tags=["сгенерировано", "AI"]
        )
        session.add(lore)
        await session.commit()
        
        msg = await update.message.reply_text(
            f"🌍 **Мир создан!**\n\n"
            f"**{world_name}**\n\n"
            f"📖 **Описание:**\n{generated_text}\n\n"
            f"✅ Мир сохранён в лорбуке.\n"
            f"💡 Чтобы использовать его, выбери мир через '🌐 Выбрать мир'.\n"
            f"✏️ Чтобы отредактировать мир, используй '✏️ Редактировать мир'.\n"
            f"➕ Чтобы добавить лор, используй '📚 Добавить лор'.\n\n"
            f"❌ Если мир не понравился, нажми /regenerate",
            parse_mode='Markdown'
        )
        
        context.user_data['last_generated_world_id'] = world.id
        context.user_data['last_generated_message_id'] = msg.message_id
        context.user_data['last_generated_prompt'] = user_message
    
    return ConversationHandler.END

async def regenerate_world(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
    except Exception:
        pass
    
    world_id = context.user_data.get('last_generated_world_id')
    prompt = context.user_data.get('last_generated_prompt')
    msg_id = context.user_data.get('last_generated_message_id')
    
    if not world_id or not prompt:
        await update.message.reply_text("❌ Нет предыдущей генерации. Создай мир через /generate_world или кнопку '🌍 Генерация мира'", parse_mode='Markdown')
        return
    
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass
    
    async for session in get_db():
        world = await session.get(World, world_id)
        if world:
            await session.delete(world)
            await session.commit()
    
    await generate_world_process(update, context)

# ----- ГЕНЕРАЦИЯ ПЕРСОНАЖА -----

async def generate_character_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎭 **Генерация персонажа через AI**\n\n"
        "Опиши, какого персонажа ты хочешь создать.\n\n"
        "Например:\n"
        "— «Маким Кац из аниме»\n"
        "— «Шото Тодороки из Моей Геройской Академии»\n"
        "— «Гермиона Грейнджер из Гарри Поттера»\n"
        "— «Средневековый воин с драконьей кровью»\n\n"
        "Напиши описание, и я создам для тебя персонажа с историей, характером и ролью!",
        parse_mode='Markdown'
    )
    return 1

async def generate_character_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass
    
    await update.message.chat.send_action(action="typing")
    
    prompt = f"""Создай подробного персонажа на основе описания пользователя.

Описание пользователя: {user_message}

Создай персонажа со следующими разделами. КАЖДЫЙ РАЗДЕЛ ДОЛЖЕН БЫТЬ НА ОТДЕЛЬНОЙ СТРОКЕ И НАЧИНАТЬСЯ С ЖИРНОГО ЗАГОЛОВКА:
1. 👤 **Имя:** - имя персонажа
2. 📅 **Возраст:** - возраст
3. 📝 **Описание:** - внешность и общее описание
4. 🔥 **Характер:** - черты характера
5. 📖 **Предыстория:** - история персонажа
6. ⚔️ **Навыки:** - способности
7. 🎯 **Цель:** - мотивация
8. 💬 **Приветствие:** - что скажет при встрече

Ответ должен быть структурированным, с эмодзи и жирными заголовками."""
    
    openai.api_key = POLZA_API_KEY
    openai.base_url = "https://polza.ai/api/v1/"
    
    try:
        response = openai.chat.completions.create(
            model=POLZA_MODEL,
            messages=[{"role": "system", "content": prompt}],
            temperature=0.9,
            max_tokens=1500,
            extra_headers={"HTTP-Referer": "https://colab.research.google.com/"}
        )
        generated_text = response.choices[0].message.content
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка генерации: {str(e)}")
        return ConversationHandler.END
    
    lines = generated_text.split('\n')
    char_name = "Сгенерированный персонаж"
    age = "не указан"
    description = ""
    personality = ""
    backstory = ""
    skills = ""
    goal = ""
    greeting = ""
    
    for line in lines:
        line_lower = line.lower()
        if "имя" in line_lower:
            char_name = line.replace("Имя", "").replace("имя", "").replace("👤", "").replace("**", "").strip(": .")
        elif "возраст" in line_lower:
            age = line.replace("Возраст", "").replace("возраст", "").replace("📅", "").replace("**", "").strip(": .")
        elif "описание" in line_lower and "предыстория" not in line_lower:
            description = line.replace("Описание", "").replace("описание", "").replace("📝", "").replace("**", "").strip(": .")
        elif "характер" in line_lower:
            personality = line.replace("Характер", "").replace("характер", "").replace("🔥", "").replace("**", "").strip(": .")
        elif "предыстория" in line_lower:
            backstory = line.replace("Предыстория", "").replace("предыстория", "").replace("📖", "").replace("**", "").strip(": .")
        elif "навык" in line_lower:
            skills = line.replace("Навыки", "").replace("навыки", "").replace("⚔️", "").replace("**", "").strip(": .")
        elif "цель" in line_lower:
            goal = line.replace("Цель", "").replace("цель", "").replace("🎯", "").replace("**", "").strip(": .")
        elif "приветствие" in line_lower:
            greeting = line.replace("Приветствие", "").replace("приветствие", "").replace("💬", "").replace("**", "").strip(": .")
    
    if not char_name or char_name == "Сгенерированный персонаж":
        char_name = "Сгенерированный персонаж"
        description = generated_text
    
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        room = user.current_room or "Главная"
        
        character = Character(
            name=char_name,
            description=description or "Описание не указано",
            personality=personality or "Характер не указан",
            backstory=backstory or "Предыстория не указана",
            role="Сгенерированный персонаж",
            greeting=greeting or f"Приветствую тебя, путник! Я {char_name}.",
            user_id=user.id,
            room=room
        )
        session.add(character)
        await session.commit()
        
        output = f"""🎭 **{char_name}**

━━━━━━━━━━━━━━━━━━━━━━
👤 **Имя:** {char_name}
📅 **Возраст:** {age}
━━━━━━━━━━━━━━━━━━━━━━

📝 **Описание:**
{description or 'не указано'}

🔥 **Характер:**
{personality or 'не указан'}

📖 **Предыстория:**
{backstory or 'не указана'}

⚔️ **Навыки:**
{skills or 'не указаны'}

🎯 **Цель:**
{goal or 'не указана'}

💬 **Приветствие:**
{greeting or 'не указано'}

━━━━━━━━━━━━━━━━━━━━━━
✅ Персонаж сохранён в твоей комнате.
💡 Чтобы использовать его, выбери персонажа через '👤 Выбрать персонажа'."""
        
        await update.message.reply_text(output, parse_mode='Markdown')
    
    return ConversationHandler.END

# ----- ЛОРБУК -----

async def lore_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 **Добавление в лорбук**\n\nВведите заголовок:", parse_mode='Markdown')
    return LORE_TITLE

async def lore_add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lore_title'] = update.message.text
    await update.message.reply_text("📝 Введите содержание:", parse_mode='Markdown')
    return LORE_CONTENT

async def lore_add_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lore_content'] = update.message.text
    await update.message.reply_text("📂 Введите категорию (история, география, магия):", parse_mode='Markdown')
    return LORE_CATEGORY

async def lore_add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lore_category'] = update.message.text
    await update.message.reply_text("🏷️ Введите теги через запятую (или 'пропустить'):", parse_mode='Markdown')
    return LORE_TAGS

async def lore_add_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tags_text = update.message.text
    tags = []
    if tags_text.lower() != 'пропустить':
        tags = [t.strip() for t in tags_text.split(',') if t.strip()]
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        room = user.current_room or "Главная"
        world_id = None
        if user.active_character_id:
            character = await session.get(Character, user.active_character_id)
            if character:
                world_id = character.world_id
        lore = LoreEntry(
            title=context.user_data['lore_title'],
            content=context.user_data['lore_content'],
            category=context.user_data['lore_category'],
            world_id=world_id,
            room=room,
            tags=tags
        )
        session.add(lore)
        await session.commit()
        await update.message.reply_text(f"✅ **Запись добавлена!**\n\n📖 {lore.title}\n📂 {lore.category}", parse_mode='Markdown')
    return ConversationHandler.END

lore_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('lore_add', lore_add_start),
        MessageHandler(filters.Regex('^📚 Лорбук$'), lore_add_start)
    ],
    states={
        LORE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lore_add_title)],
        LORE_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, lore_add_content)],
        LORE_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, lore_add_category)],
        LORE_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, lore_add_tags)],
    },
    fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Отменено"))]
)

# ----- ПАМЯТЬ -----

async def memory_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 **Добавить воспоминание**\n\nВведите воспоминание:", parse_mode='Markdown')
    return 1

async def memory_add_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    content = update.message.text
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        if not user.active_persona_id:
            await update.message.reply_text("❌ Сначала создайте персону")
            return ConversationHandler.END
        room = user.current_room or "Главная"
        character_id = user.active_character_id if user.active_character_id else None
        memory = Memory(
            persona_id=user.active_persona_id,
            character_id=character_id,
            content=content,
            memory_type='personal',
            importance=1.0,
            room=room
        )
        session.add(memory)
        await session.commit()
        await update.message.reply_text("✅ **Воспоминание сохранено!**", parse_mode='Markdown')
    return ConversationHandler.END

async def memory_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        if not user.active_persona_id:
            await update.message.reply_text("❌ Сначала создайте персону")
            return
        room = user.current_room or "Главная"
        memories_result = await session.execute(
            select(Memory).where(Memory.persona_id == user.active_persona_id, Memory.room == room)
            .order_by(Memory.importance.desc()).limit(30)
        )
        memories = memories_result.scalars().all()
        if not memories:
            await update.message.reply_text("🧠 У вас пока нет воспоминаний")
            return
        text = "🧠 **Ваши воспоминания:**\n\n"
        for i, mem in enumerate(memories, 1):
            auto_tag = " 🤖" if mem.is_auto else ""
            char_name = ""
            if mem.character_id:
                character = await session.get(Character, mem.character_id)
                if character:
                    char_name = f" (от {character.name})"
            text += f"{i}. {mem.content}{auto_tag}{char_name}\n"
            text += f"   ⭐ {mem.importance*10:.0f}% | {mem.created_at.strftime('%d.%m.%Y')}\n\n"
        await update.message.reply_text(text, parse_mode='Markdown')

async def memory_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = ' '.join(context.args) if context.args else None
    if not query:
        await update.message.reply_text("🔍 Используйте: /memory_search <запрос>", parse_mode='Markdown')
        return
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        if not user.active_persona_id:
            await update.message.reply_text("❌ Сначала создайте персону")
            return
        room = user.current_room or "Главная"
        memories_result = await session.execute(
            select(Memory).where(Memory.persona_id == user.active_persona_id, Memory.room == room, Memory.content.ilike(f"%{query}%"))
            .order_by(Memory.importance.desc()).limit(20)
        )
        memories = memories_result.scalars().all()
        if not memories:
            await update.message.reply_text(f"🔍 Ничего не найдено по запросу: '{query}'")
            return
        text = f"🔍 **Результаты поиска:** '{query}'\n\n"
        for i, mem in enumerate(memories, 1):
            auto_tag = " 🤖" if mem.is_auto else ""
            char_name = ""
            if mem.character_id:
                character = await session.get(Character, mem.character_id)
                if character:
                    char_name = f" (с {character.name})"
            text += f"{i}. {mem.content}{auto_tag}{char_name}\n"
            text += f"   ⭐ {mem.importance*10:.0f}% | {mem.created_at.strftime('%d.%m.%Y')}\n\n"
        await update.message.reply_text(text, parse_mode='Markdown')

async def memory_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("🗑️ Используйте: /memory_delete <ID>", parse_mode='Markdown')
        return
    try:
        memory_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")
        return
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        if not user.active_persona_id:
            await update.message.reply_text("❌ Сначала создайте персону")
            return
        memory = await session.get(Memory, memory_id)
        if not memory:
            await update.message.reply_text(f"❌ Воспоминание с ID {memory_id} не найдено")
            return
        if memory.persona_id != user.active_persona_id:
            await update.message.reply_text("❌ Это не ваше воспоминание")
            return
        await session.delete(memory)
        await session.commit()
        await update.message.reply_text(f"✅ Воспоминание #{memory_id} удалено")

memory_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('memory_add', memory_add_start),
        MessageHandler(filters.Regex('^🧠 Память$'), memory_add_start)
    ],
    states={
        1: [MessageHandler(filters.TEXT & ~filters.COMMAND, memory_add_content)],
    },
    fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Отменено"))]
)

# ----- КОМАНДА /regenerate -----

async def regenerate_last_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
    except Exception:
        pass
    
    last_bot_msg_id = context.user_data.get('last_bot_message_id')
    last_user_msg_id = context.user_data.get('last_user_message_id')
    last_user_message = context.user_data.get('last_user_message_text')
    
    if not last_bot_msg_id or not last_user_msg_id or not last_user_message:
        await update.message.reply_text("❌ Нет предыдущего ответа для регенерации.\nНапиши сначала сообщение боту, а потом используй /regenerate", parse_mode='Markdown')
        return
    
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=last_bot_msg_id)
    except Exception:
        pass
    
    await update.message.chat.send_action(action="typing")
    
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        if not user.active_persona_id or not user.active_character_id:
            await update.message.reply_text("❌ Ошибка: персонаж или персона не выбраны")
            return
        room = user.current_room or "Главная"
        persona_result = await session.execute(select(Persona).where(Persona.id == user.active_persona_id, Persona.room == room))
        persona = persona_result.scalar_one_or_none()
        character_result = await session.execute(select(Character).where(Character.id == user.active_character_id, Character.room == room))
        character = character_result.scalar_one_or_none()
        if not persona or not character:
            await update.message.reply_text("❌ Ошибка: персонаж или персона не найдены")
            return
        
        history_result = await session.execute(
            select(ChatHistory).where(ChatHistory.persona_id == persona.id, ChatHistory.character_id == character.id, ChatHistory.room == room)
            .order_by(ChatHistory.timestamp.desc()).limit(10)
        )
        history = history_result.scalars().all()[::-1]
        
        system_prompt = f"""Ты — {character.name}.
Роль: {character.role or 'неизвестна'}
Описание: {character.description or 'не описано'}
Характер: {character.personality or 'не описан'}
Предыстория: {character.backstory or 'не известна'}

Ты общаешься с {persona.name}.
О персоне:
- Возраст: {persona.age or 'неизвестен'}
- Внешность: {persona.appearance or 'не описана'}
- Характер: {persona.personality or 'не описан'}
- Навыки: {persona.skills or 'не указаны'}
- Цель: {persona.goal or 'не указана'}

Отвечай от лица {character.name}, сохраняя его характер и роль. Будь креативен."""
        
        messages = [{"role": "system", "content": system_prompt}]
        for h in history:
            messages.append({"role": "user", "content": h.user_message})
            messages.append({"role": "assistant", "content": h.bot_response})
        messages.append({"role": "user", "content": last_user_message})
        
        openai.api_key = POLZA_API_KEY
        openai.base_url = "https://polza.ai/api/v1/"
        max_tokens = user.max_tokens or 1500
        
        try:
            response = openai.chat.completions.create(
                model=POLZA_MODEL,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=max_tokens,
                extra_headers={"HTTP-Referer": "https://colab.research.google.com/"}
            )
            bot_response = response.choices[0].message.content
        except Exception as e:
            bot_response = f"❌ Ошибка: {str(e)}"
            await update.message.reply_text(bot_response)
            return
        
        last_entry_result = await session.execute(
            select(ChatHistory).where(ChatHistory.persona_id == persona.id, ChatHistory.character_id == character.id, ChatHistory.room == room)
            .order_by(ChatHistory.timestamp.desc()).limit(1)
        )
        last_entry = last_entry_result.scalar_one_or_none()
        if last_entry:
            await session.delete(last_entry)
        
        chat_entry = ChatHistory(
            persona_id=persona.id,
            character_id=character.id,
            world_id=character.world_id,
            user_message=last_user_message,
            bot_response=bot_response,
            room=room
        )
        session.add(chat_entry)
        await session.commit()
        
        msg = await update.message.reply_text(f"**{character.name}:**\n\n{bot_response}", parse_mode='Markdown')
        context.user_data['last_bot_message_id'] = msg.message_id

# ----- АВТО-СОХРАНЕНИЕ -----

async def auto_save_memory(persona_id, character_id, user_message, bot_response, session, room="Главная"):
    important_keywords = ['победил', 'нашел', 'встретил', 'получил', 'узнал', 'спас', 'убил', 'открыл', 'нашёл', 'убила', 'победила', 'нашла']
    text_to_check = f"{user_message} {bot_response}".lower()
    is_important = any(keyword in text_to_check for keyword in important_keywords)
    if is_important and len(user_message) > 10:
        memory_text = f"📌 {user_message[:100]}"
        if len(user_message) > 100:
            memory_text += "..."
        existing_result = await session.execute(
            select(Memory).where(Memory.persona_id == persona_id, Memory.content.ilike(f"%{user_message[:50]}%"), Memory.room == room)
        )
        existing = existing_result.scalar_one_or_none()
        if not existing:
            memory = Memory(
                persona_id=persona_id,
                character_id=character_id,
                content=memory_text,
                memory_type='personal',
                importance=0.7,
                is_auto=True,
                room=room
            )
            session.add(memory)
            await session.commit()
            return True
    return False

# ----- РЕЖИМ СЦЕНАРИЯ -----

async def toggle_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        user.scenario_mode = not user.scenario_mode
        if user.scenario_mode:
            user.scenario_context = None
        await session.commit()
        status = "ВКЛЮЧЁН ✅" if user.scenario_mode else "ВЫКЛЮЧЕН ❌"
        await update.message.reply_text(f"🎬 **Режим сценария {status}**", parse_mode='Markdown')

# ----- ВКЛЮЧЕНИЕ/ВЫКЛЮЧЕНИЕ МИРА -----

async def toggle_world(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        user.active_world_enabled = not user.active_world_enabled
        await session.commit()
        status = "ВКЛЮЧЕН ✅" if user.active_world_enabled else "ВЫКЛЮЧЕН ❌"
        await update.message.reply_text(f"🌐 Мир {status}")

# ----- НАСТРОЙКА ДЛИНЫ ОТВЕТА -----

async def set_max_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        current = user.max_tokens
        keyboard = [
            [InlineKeyboardButton("500 токенов", callback_data="tokens_500")],
            [InlineKeyboardButton("1000 токенов", callback_data="tokens_1000")],
            [InlineKeyboardButton("1500 токенов", callback_data="tokens_1500")],
            [InlineKeyboardButton("2000 токенов", callback_data="tokens_2000")],
            [InlineKeyboardButton("4000 токенов", callback_data="tokens_4000")],
        ]
        await update.message.reply_text(
            f"📏 **Длина ответа:** {current} токенов\n\nВыберите новую длину:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def set_tokens_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tokens = int(query.data.split('_')[1])
    user_id = query.from_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=query.from_user.username)
            session.add(user)
            await session.commit()
        user.max_tokens = tokens
        await session.commit()
        await query.edit_message_text(f"✅ **Длина ответа:** {tokens} токенов")

# ----- ОСНОВНОЙ ДИАЛОГ -----

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    context.user_data['last_user_message_id'] = update.message.message_id
    context.user_data['last_user_message_text'] = user_message
    
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
            await update.message.reply_text(
                "👋 Привет! Добро пожаловать в HFSI RPG Bot!\n\n1. Создай свою **персону** через '👤 Моя персона'\n2. Создай **персонажа-бота** через '🎭 Персонажи (боты)'\n3. Выбери персонажа и начинай играть!\n\nИспользуй кнопки меню для управления.",
                reply_markup=get_main_keyboard()
            )
            return
        
        room = user.current_room or "Главная"
        
        if not user.active_persona_id:
            await update.message.reply_text("❌ Сначала создай персону: '👤 Моя персона' → '➕ Создать/редактировать'", reply_markup=get_main_keyboard())
            return
        
        persona_result = await session.execute(select(Persona).where(Persona.id == user.active_persona_id, Persona.room == room))
        persona = persona_result.scalar_one_or_none()
        if not persona:
            await update.message.reply_text("❌ Персона не найдена в этой комнате")
            return
        
        if not user.active_character_id:
            await update.message.reply_text("❌ Сначала выбери персонажа-бота: '🎭 Персонажи (боты)' → '👤 Выбрать персонажа'", reply_markup=get_main_keyboard())
            return
        
        character_result = await session.execute(select(Character).where(Character.id == user.active_character_id, Character.room == room))
        character = character_result.scalar_one_or_none()
        if not character:
            user.active_character_id = None
            await session.commit()
            await update.message.reply_text("❌ Персонаж не найден в этой комнате")
            return
        
        scenario_prompt = ""
        if user.scenario_mode:
            scenario_prompt = f"""
Ты - {character.name}, ведущий/мастер игры в режиме сценария.

Твоя задача - вести сюжет, описывать сцены и реагировать на действия игрока.

Правила:
1. Начинай с описания сцены
2. После описания сцены дай игроку выбор действий (2-3 варианта)
3. Реагируй на действия игрока, развивай сюжет
4. Если игрок отклоняется от сценария - мягко возвращай его в сюжет
5. Добавляй повороты сюжета, встречи с NPC, находки

Игрок: {persona.name}
Описание игрока: {persona.appearance or 'неизвестно'}, {persona.personality or 'неизвестно'}
Цель игрока: {persona.goal or 'не указана'}

{user.scenario_context or 'Начни новую сцену. Опиши место и предложи игроку выбор действий.'}
"""
        
        world_info = ""
        if user.active_world_enabled and character.world_id:
            world = await session.get(World, character.world_id)
            if world:
                world_info = f"Мир: {world.name}\n{world.description[:200] if world.description else ''}"
                lore_result = await session.execute(select(LoreEntry).where(LoreEntry.world_id == world.id, LoreEntry.room == room).limit(5))
                lore = lore_result.scalars().all()
                if lore:
                    world_info += "\n\nЗнания о мире:\n" + "\n".join([f"- {l.title}: {l.content[:150]}..." for l in lore])
        
        if user.scenario_mode:
            system_prompt = f"""Ты — {character.name}.
Роль: {character.role or 'ведущий сценария'}
Описание: {character.description or 'не описано'}
Характер: {character.personality or 'не описан'}

{scenario_prompt}

{world_info}

Отвечай от лица {character.name} как ведущий сценария. Будь креативен, описывай атмосферу, давай выбор. Используй markdown для форматирования."""
        else:
            system_prompt = f"""Ты — {character.name}.
Роль: {character.role or 'неизвестна'}
Описание: {character.description or 'не описано'}
Характер: {character.personality or 'не описан'}
Предыстория: {character.backstory or 'не известна'}

Ты общаешься с {persona.name}.
О персоне:
- Возраст: {persona.age or 'неизвестен'}
- Внешность: {persona.appearance or 'не описана'}
- Характер: {persona.personality or 'не описан'}
- Навыки: {persona.skills or 'не указаны'}
- Цель: {persona.goal or 'не указана'}

{world_info}

Отвечай от лица {character.name}, сохраняя его характер и роль. Будь креативен, но не противоречь лору мира. Обращайся к {persona.name} по имени."""
        
        history_limit = 15 if user.scenario_mode else 10
        history_result = await session.execute(
            select(ChatHistory).where(ChatHistory.persona_id == persona.id, ChatHistory.character_id == character.id, ChatHistory.room == room)
            .order_by(ChatHistory.timestamp.desc()).limit(history_limit)
        )
        history = history_result.scalars().all()[::-1]
        
        memories_result = await session.execute(
            select(Memory).where(Memory.persona_id == persona.id, Memory.room == room)
            .order_by(Memory.importance.desc()).limit(5)
        )
        memories = memories_result.scalars().all()
        
        messages = [{"role": "system", "content": system_prompt}]
        
        if memories:
            memory_text = "\n\nВоспоминания:\n" + "\n".join([f"- {m.content}" for m in memories])
            messages[0]["content"] += memory_text
        
        for h in history:
            messages.append({"role": "user", "content": h.user_message})
            messages.append({"role": "assistant", "content": h.bot_response})
        messages.append({"role": "user", "content": user_message})
        
        openai.api_key = POLZA_API_KEY
        openai.base_url = "https://polza.ai/api/v1/"
        max_tokens = user.max_tokens or 1500
        
        try:
            response = openai.chat.completions.create(
                model=POLZA_MODEL,
                messages=messages,
                temperature=TEMPERATURE + 0.1 if user.scenario_mode else TEMPERATURE,
                max_tokens=max_tokens,
                extra_headers={"HTTP-Referer": "https://colab.research.google.com/"}
            )
            bot_response = response.choices[0].message.content
        except Exception as e:
            bot_response = f"❌ Ошибка: {str(e)}"
        
        try:
            saved = await auto_save_memory(persona.id, character.id, user_message, bot_response, session, room)
            if saved:
                print(f"📌 Авто-сохранено воспоминание для {persona.name}")
        except Exception as e:
            print(f"Ошибка авто-сохранения: {e}")
        
        if user.scenario_mode:
            user.scenario_context = f"Последнее событие: {user_message[:100]}\nОтвет ведущего: {bot_response[:200]}..."
            await session.commit()
        
        chat_entry = ChatHistory(
            persona_id=persona.id,
            character_id=character.id,
            world_id=character.world_id,
            user_message=user_message,
            bot_response=bot_response,
            room=room
        )
        session.add(chat_entry)
        await session.commit()
        
        msg = await update.message.reply_text(f"**{character.name}:**\n\n{bot_response}", parse_mode='Markdown')
        context.user_data['last_bot_message_id'] = msg.message_id

# ----- ЗАПУСК -----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user_result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user_result.scalar_one_or_none()
        
        if not user:
            user = User(
                telegram_id=user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )
            session.add(user)
            await session.commit()
        
        room = user.current_room or "Главная"
        persona_name = "не создана"
        if user.active_persona_id:
            persona_result = await session.execute(
                select(Persona).where(
                    Persona.id == user.active_persona_id,
                    Persona.room == room
                )
            )
            persona = persona_result.scalar_one_or_none()
            if persona:
                persona_name = persona.name
        
        char_name = "не выбран"
        if user.active_character_id:
            char_result = await session.execute(
                select(Character).where(
                    Character.id == user.active_character_id,
                    Character.room == room
                )
            )
            character = char_result.scalar_one_or_none()
            if character:
                char_name = character.name
        
        scenario_status = "✅ ВКЛ" if user.scenario_mode else "❌ ВЫКЛ"
        
        await update.message.reply_text(
            f"""🌟 **HFSI RPG Bot**

📂 Комната: **{room}**
👤 Персона: **{persona_name}**
🎭 Активный бот: **{char_name}**
📏 Длина: **{user.max_tokens}** токенов
🎬 Сценарий: **{scenario_status}**

**Как это работает:**
1. Создай свою **персону** (кто ты)
2. Создай **персонажей-ботов** (с кем общаешься)
3. Выбери бота и просто пиши сообщения!
4. Включи **режим сценария** для сюжетной игры
5. Создавай **комнаты** для разных сюжетов

**Память:**
- Добавляй воспоминания через 🧠 Память
- Ищи по памяти через 🔍 Поиск по памяти
- Важные события сохраняются автоматически!

**Управление:**
- ✏️ Редактировать — изменяй персонажей
- ✏️ Редактировать мир — изменяй миры
- 🎭 Генерация персонажа — создай AI-персонажа
- 🌍 Генерация мира — создай мир через AI
- 🔄 Сбросить чат — начни историю заново
- /regenerate — перегенерируй последний ответ

Используй кнопки меню для управления.""",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )

async def main():
    await init_db()
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    
    application.add_handler(CommandHandler("create_room", create_room))
    application.add_handler(CommandHandler("switch_room", switch_room))
    application.add_handler(CommandHandler("list_rooms", list_rooms))
    application.add_handler(CommandHandler("rename_room", rename_room))
    application.add_handler(CommandHandler("delete_room", delete_room))
    
    application.add_handler(CommandHandler("scenario", toggle_scenario))
    application.add_handler(CommandHandler("memory_list", memory_list))
    application.add_handler(CommandHandler("memory_search", memory_search))
    application.add_handler(CommandHandler("memory_delete", memory_delete))
    
    application.add_handler(persona_conv_handler)
    application.add_handler(CommandHandler("persona_select", persona_select_command))
    application.add_handler(CallbackQueryHandler(persona_select_callback, pattern="^select_persona_"))
    
    application.add_handler(character_conv_handler)
    application.add_handler(CommandHandler("character_list", character_list))
    application.add_handler(CommandHandler("character_select", character_select_command))
    application.add_handler(CallbackQueryHandler(character_select_callback, pattern="^select_char_"))
    
    application.add_handler(world_conv_handler)
    application.add_handler(CommandHandler("world_list", world_list))
    application.add_handler(CommandHandler("world_select", world_select_start))
    application.add_handler(CallbackQueryHandler(world_select_callback, pattern="^select_world_"))
    
    application.add_handler(lore_conv_handler)
    application.add_handler(memory_conv_handler)
    
    application.add_handler(character_edit_handler)
    application.add_handler(CallbackQueryHandler(character_edit_callback, pattern="^edit_char_"))
    application.add_handler(CallbackQueryHandler(character_edit_callback, pattern="^back_to_characters$"))
    
    application.add_handler(world_edit_handler)
    application.add_handler(CallbackQueryHandler(world_edit_callback, pattern="^edit_world_"))
    application.add_handler(CallbackQueryHandler(world_edit_callback, pattern="^back_to_worlds$"))
    
    application.add_handler(CallbackQueryHandler(reset_confirm_callback, pattern="^reset_confirm$"))
    application.add_handler(CallbackQueryHandler(reset_cancel_callback, pattern="^reset_cancel$"))
    
    application.add_handler(CallbackQueryHandler(persona_skip_callback, pattern="^persona_skip$"))
    
    application.add_handler(CommandHandler("generate_world", generate_world_start))
    application.add_handler(CommandHandler("regenerate", regenerate_world))
    
    generate_world_handler = ConversationHandler(
        entry_points=[
            CommandHandler('generate_world', generate_world_start),
            MessageHandler(filters.Regex('^🌍 Генерация мира$'), generate_world_start)
        ],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_world_process)],
        },
        fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Отменено"))]
    )
    application.add_handler(generate_world_handler)
    
    generate_character_handler = ConversationHandler(
        entry_points=[
            CommandHandler('generate_character', generate_character_start),
            MessageHandler(filters.Regex('^🎭 Генерация персонажа$'), generate_character_start)
        ],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_character_process)],
        },
        fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Отменено"))]
    )
    application.add_handler(generate_character_handler)
    
    application.add_handler(CommandHandler("regenerate", regenerate_last_response))
    
    application.add_handler(CommandHandler("toggle_world", toggle_world))
    application.add_handler(CommandHandler("set_tokens", set_max_tokens))
    application.add_handler(CallbackQueryHandler(set_tokens_callback, pattern="^tokens_"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons))
    
    print("🚀 Бот запущен!")
    print("📱 @HFSI_AI_bot")
    print("🎬 Режим сценария: готов")
    print("🧠 Расширенная память: готова")
    print("🔍 Поиск по памяти: готов")
    print("📂 Система комнат: готова")
    print("🧹 Автоудаление: активно")
    print("✏️ Редактор персонажей: активен")
    print("✏️ Редактор миров: активен")
    print("🔄 Сброс чата: готов")
    print("🌍 Генерация миров: активна")
    print("🎭 Генерация персонажей: активна")
    print("🔄 Команда /regenerate: активна")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
