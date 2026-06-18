# ============================================
# HFSI RPG BOT - ПОЛНАЯ ВЕРСИЯ ДЛЯ BOTHOST
# ПЕРСОНА + ПЕРСОНАЖИ (БОТЫ) + СЦЕНАРИЙ + РАСШИРЕННАЯ ПАМЯТЬ
# ============================================

import asyncio
import nest_asyncio
nest_asyncio.apply()

import os
import logging
import sys
from datetime import datetime
from typing import Optional, List
import json
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, JSON, Table, select, update
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler, ContextTypes
import openai

# ============================================
# 🔑 ВАШИ ДАННЫЕ (из переменных окружения на Bothost)
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
POLZA_API_KEY = os.getenv("POLZA_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///hfsi_bot.db")
POLZA_MODEL = "deepseek/deepseek-v4-flash"
ADMIN_USER_ID = 1068321899

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

class World(Base):
    __tablename__ = 'worlds'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey('users.id'))
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
    persona = relationship('Persona')
    character = relationship('Character')

# ============================================
# БАЗА ДАННЫХ
# ============================================

# НЕ УДАЛЯЕМ БАЗУ ПРИ ЗАПУСКЕ НА ХОСТИНГЕ!
# if os.path.exists("hfsi_bot.db"):
#     os.remove("hfsi_bot.db")
#     print("🗑️ Старая база удалена")

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
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

async def get_active_persona(user_id):
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user or not user.active_persona_id:
            return None, None
        persona = await session.get(Persona, user.active_persona_id)
        return user, persona

async def get_active_character(user_id):
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user or not user.active_character_id:
            return None, None
        character = await session.get(Character, user.active_character_id)
        return user, character

# ============================================
# МЕНЮ
# ============================================

def get_main_keyboard():
    keyboard = [
        ["👤 Моя персона", "🎭 Персонажи (боты)"],
        ["🌍 Миры", "📚 Лорбук"],
        ["🧠 Память", "🔍 Поиск по памяти"],
        ["🎬 Режим сценария", "⚙️ Настройки"]
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
        ["👤 Выбрать персонажа", "🔙 Назад"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_worlds_keyboard():
    keyboard = [
        ["🌍 Список миров", "➕ Создать мир"],
        ["🌐 Выбрать мир", "⏸️ Вкл/Выкл мир"],
        ["🔙 Назад"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_settings_keyboard():
    keyboard = [
        ["🌐 Вкл/Выкл мир", "📏 Длина ответа"],
        ["🔙 Назад"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ============================================
# ОБРАБОТЧИКИ
# ============================================

(PERSONA_NAME, PERSONA_AGE, PERSONA_APPEARANCE, PERSONA_PERSONALITY, PERSONA_BACKSTORY, PERSONA_SKILLS, PERSONA_GOAL) = range(7)
(CHAR_NAME, CHAR_DESC, CHAR_PERSONALITY, CHAR_BACKSTORY, CHAR_ROLE, CHAR_GREETING) = range(6)
(WORLD_NAME, WORLD_DESC) = range(2)
(LORE_TITLE, LORE_CONTENT, LORE_CATEGORY, LORE_TAGS) = range(4)

# ----- ГЛАВНОЕ МЕНЮ -----

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user, persona = await get_active_persona(user_id)
    _, character = await get_active_character(user_id)
    
    persona_text = f"👤 {persona.name}" if persona else "❌ не создана"
    char_text = f"🎭 {character.name}" if character else "❌ не выбран"
    
    text = f"""🌟 **Главное меню HFSI RPG Bot**

👤 Персона: **{persona_text}**
🎭 Активный бот: **{char_text}**

Выберите раздел:"""
    await update.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "👤 Моя персона":
        user, persona = await get_active_persona(user_id)
        char_text = f"\n👤 Активная персона: **{persona.name}**" if persona else "\n❌ Персона не создана"
        await update.message.reply_text(
            f"👤 **Управление персоной**{char_text}",
            reply_markup=get_persona_keyboard(),
            parse_mode='Markdown'
        )
    elif text == "🎭 Персонажи (боты)":
        _, character = await get_active_character(user_id)
        char_text = f"\n🎭 Активный бот: **{character.name}**" if character else "\n❌ Бот не выбран"
        await update.message.reply_text(
            f"🎭 **Управление персонажами-ботами**{char_text}\n\nЗдесь вы создаёте ботов, с которыми будете общаться!",
            reply_markup=get_characters_keyboard(),
            parse_mode='Markdown'
        )
    elif text == "🌍 Миры":
        await update.message.reply_text("🌍 **Управление мирами**", reply_markup=get_worlds_keyboard(), parse_mode='Markdown')
    elif text == "📚 Лорбук":
        await lore_add_start(update, context)
    elif text == "🧠 Память":
        await memory_add_start(update, context)
    elif text == "🔍 Поиск по памяти":
        await update.message.reply_text(
            "🔍 **Поиск по памяти**\n\n"
            "Напишите слово или фразу для поиска:",
            parse_mode='Markdown'
        )
        return 2
    elif text == "🎬 Режим сценария":
        await toggle_scenario(update, context)
    elif text == "⚙️ Настройки":
        await update.message.reply_text("⚙️ **Настройки**", reply_markup=get_settings_keyboard(), parse_mode='Markdown')
    elif text == "🔙 Назад":
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
    elif text == "🌍 Список миров":
        await world_list(update, context)
    elif text == "➕ Создать мир":
        await world_new_start(update, context)
    elif text == "🌐 Выбрать мир":
        await world_select_start(update, context)
    elif text == "⏸️ Вкл/Выкл мир" or text == "🌐 Вкл/Выкл мир":
        await toggle_world(update, context)
    elif text == "📏 Длина ответа":
        await set_max_tokens(update, context)
    else:
        await handle_message(update, context)

# ----- ПЕРСОНА (ВЫ) -----

async def show_persona_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user or not user.active_persona_id:
            await update.message.reply_text("❌ У вас нет персоны. Создайте её через '➕ Создать/редактировать'")
            return
        persona = await session.get(Persona, user.active_persona_id)
        if not persona:
            await update.message.reply_text("❌ Персона не найдена")
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

async def persona_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if user and user.active_persona_id:
            await update.message.reply_text(
                "✏️ **Редактирование персоны**\n\n"
                "Введите новое **имя** (или напишите /cancel для отмены):",
                parse_mode='Markdown'
            )
            return PERSONA_NAME
    await update.message.reply_text(
        "👤 **Создание персоны**\n\n"
        "**Шаг 1 из 7:** Введите ваше **имя**:",
        parse_mode='Markdown'
    )
    return PERSONA_NAME

async def persona_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_name'] = update.message.text
    await update.message.reply_text(
        f"✅ Имя: {context.user_data['persona_name']}\n\n"
        "**Шаг 2 из 7:** Введите **возраст**:",
        parse_mode='Markdown'
    )
    return PERSONA_AGE

async def persona_new_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['persona_age'] = int(update.message.text)
    except ValueError:
        context.user_data['persona_age'] = None
    await update.message.reply_text(
        f"✅ Возраст: {context.user_data['persona_age'] or 'не указан'}\n\n"
        "**Шаг 3 из 7:** Опишите **внешность**:",
        parse_mode='Markdown'
    )
    return PERSONA_APPEARANCE

async def persona_new_appearance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_appearance'] = update.message.text
    await update.message.reply_text(
        "**Шаг 4 из 7:** Опишите **характер**:",
        parse_mode='Markdown'
    )
    return PERSONA_PERSONALITY

async def persona_new_personality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_personality'] = update.message.text
    await update.message.reply_text(
        "**Шаг 5 из 7:** Напишите **предысторию**:",
        parse_mode='Markdown'
    )
    return PERSONA_BACKSTORY

async def persona_new_backstory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_backstory'] = update.message.text
    await update.message.reply_text(
        "**Шаг 6 из 7:** Опишите **навыки/способности**:",
        parse_mode='Markdown'
    )
    return PERSONA_SKILLS

async def persona_new_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_skills'] = update.message.text
    await update.message.reply_text(
        "**Шаг 7 из 7:** Какая ваша **цель**?",
        parse_mode='Markdown'
    )
    return PERSONA_GOAL

async def persona_new_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['persona_goal'] = update.message.text
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.flush()
        
        if user.active_persona_id:
            persona = await session.get(Persona, user.active_persona_id)
            if persona:
                persona.name = context.user_data['persona_name']
                persona.age = context.user_data.get('persona_age')
                persona.appearance = context.user_data.get('persona_appearance')
                persona.personality = context.user_data.get('persona_personality')
                persona.backstory = context.user_data.get('persona_backstory')
                persona.skills = context.user_data.get('persona_skills')
                persona.goal = context.user_data.get('persona_goal')
                await session.commit()
                await update.message.reply_text(
                    f"✅ **Персона обновлена!**\n\nИмя: {persona.name}",
                    reply_markup=get_main_keyboard(),
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
        
        persona = Persona(
            name=context.user_data['persona_name'],
            age=context.user_data.get('persona_age'),
            appearance=context.user_data.get('persona_appearance'),
            personality=context.user_data.get('persona_personality'),
            backstory=context.user_data.get('persona_backstory'),
            skills=context.user_data.get('persona_skills'),
            goal=context.user_data.get('persona_goal'),
            user_id=user.id
        )
        session.add(persona)
        await session.commit()
        user.active_persona_id = persona.id
        await session.commit()
        await update.message.reply_text(
            f"✅ **Персона создана!**\n\nИмя: {persona.name}",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    return ConversationHandler.END

persona_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('persona_new', persona_new_start),
        MessageHandler(filters.Regex('^➕ Создать/редактировать$'), persona_new_start)
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
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            await update.message.reply_text("❌ У вас нет персоны. Создайте её!")
            return
        personas = await session.execute(select(Persona).where(Persona.user_id == user.id))
        personas = personas.scalars().all()
        if not personas:
            await update.message.reply_text("❌ У вас нет персоны. Создайте её!")
            return
        keyboard = []
        for p in personas:
            status = "✅" if user.active_persona_id == p.id else "⬜"
            keyboard.append([InlineKeyboardButton(f"{status} {p.name}", callback_data=f"select_persona_{p.id}")])
        await update.message.reply_text(
            "👤 **Выберите персону:**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def persona_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    persona_id = int(query.data.split('_')[2])
    async for session in get_db():
        persona = await session.get(Persona, persona_id)
        if not persona:
            await query.edit_message_text("❌ Персона не найдена")
            return
        user = await session.execute(select(User).where(User.telegram_id == query.from_user.id))
        user = user.scalar_one_or_none()
        if user:
            user.active_persona_id = persona_id
            await session.commit()
            await query.edit_message_text(f"✅ **Выбрана персона:** {persona.name}")

# ----- ПЕРСОНАЖИ (БОТЫ) -----

async def character_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            await update.message.reply_text("❌ У вас нет персонажей. Создайте первого!")
            return
        characters = await session.execute(select(Character).where(Character.user_id == user.id))
        characters = characters.scalars().all()
        if not characters:
            await update.message.reply_text("❌ У вас нет персонажей. Создайте первого!")
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
    await update.message.reply_text(
        "🎭 **Создание персонажа-бота**\n\n"
        "**Шаг 1 из 6:** Введите **имя** персонажа:",
        parse_mode='Markdown'
    )
    return CHAR_NAME

async def character_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_name'] = update.message.text
    await update.message.reply_text(
        f"✅ Имя: {context.user_data['char_name']}\n\n"
        "**Шаг 2 из 6:** Опишите **кто это** (роль, сущность):\n"
        "Например: 'Могучий волшебник, хранитель древних знаний'",
        parse_mode='Markdown'
    )
    return CHAR_DESC

async def character_new_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_desc'] = update.message.text
    await update.message.reply_text(
        "**Шаг 3 из 6:** Опишите **характер** персонажа:\n"
        "(черты, манера речи, привычки)",
        parse_mode='Markdown'
    )
    return CHAR_PERSONALITY

async def character_new_personality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_personality'] = update.message.text
    await update.message.reply_text(
        "**Шаг 4 из 6:** Напишите **предысторию** персонажа:",
        parse_mode='Markdown'
    )
    return CHAR_BACKSTORY

async def character_new_backstory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_backstory'] = update.message.text
    await update.message.reply_text(
        "**Шаг 5 из 6:** Укажите **роль** в мире:\n"
        "(маг, воин, торговец, король и т.д.)",
        parse_mode='Markdown'
    )
    return CHAR_ROLE

async def character_new_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_role'] = update.message.text
    await update.message.reply_text(
        "**Шаг 6 из 6:** Напишите **приветствие** персонажа:\n"
        "(что он скажет при начале диалога)",
        parse_mode='Markdown'
    )
    return CHAR_GREETING

async def character_new_greeting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_greeting'] = update.message.text
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.flush()
        
        character = Character(
            name=context.user_data['char_name'],
            description=context.user_data['char_desc'],
            personality=context.user_data['char_personality'],
            backstory=context.user_data['char_backstory'],
            role=context.user_data['char_role'],
            greeting=context.user_data['char_greeting'],
            user_id=user.id
        )
        session.add(character)
        await session.commit()
        await update.message.reply_text(
            f"✅ **Персонаж-бот создан!**\n\n"
            f"Имя: {character.name}\n"
            f"Роль: {character.role}\n\n"
            f"Теперь выберите его через '👤 Выбрать персонажа'",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
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
    fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Создание отменено"))]
)

async def character_select_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            await update.message.reply_text("❌ У вас нет персонажей. Создайте первого!")
            return
        characters = await session.execute(select(Character).where(Character.user_id == user.id))
        characters = characters.scalars().all()
        if not characters:
            await update.message.reply_text("❌ У вас нет персонажей. Создайте первого!")
            return
        keyboard = []
        for char in characters:
            status = "✅" if user.active_character_id == char.id else "⬜"
            keyboard.append([InlineKeyboardButton(f"{status} {char.name}", callback_data=f"select_char_{char.id}")])
        await update.message.reply_text(
            "🎭 **Выберите персонажа-бота:**\n\n✅ - активный",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def character_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    char_id = int(query.data.split('_')[2])
    async for session in get_db():
        character = await session.get(Character, char_id)
        if not character:
            await query.edit_message_text("❌ Персонаж не найден")
            return
        user = await session.execute(select(User).where(User.telegram_id == query.from_user.id))
        user = user.scalar_one_or_none()
        if user:
            user.active_character_id = char_id
            await session.commit()
            await query.edit_message_text(
                f"✅ **Выбран персонаж:** {character.name}\n\n"
                f"{character.greeting or 'Приветствую тебя, путник!'}"
            )

# ----- МИРЫ -----

async def world_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async for session in get_db():
        worlds = await session.execute(select(World))
        worlds = worlds.scalars().all()
        if not worlds:
            await update.message.reply_text("❌ Нет созданных миров. Создайте новый!")
            return
        text = "🌍 **Доступные миры:**\n\n"
        for world in worlds:
            text += f"📌 **{world.name}** (ID: {world.id})\n"
            text += f"   {world.description[:100]}...\n\n"
        await update.message.reply_text(text, parse_mode='Markdown')

async def world_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌍 **Создание мира**\n\nВведите название:")
    return WORLD_NAME

async def world_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['world_name'] = update.message.text
    await update.message.reply_text("Введите описание мира:")
    return WORLD_DESC

async def world_new_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['world_desc'] = update.message.text
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.flush()
        world = World(
            name=context.user_data['world_name'],
            description=context.user_data['world_desc'],
            created_by=user.id
        )
        session.add(world)
        await session.commit()
        await update.message.reply_text(
            f"✅ **Мир создан!**\n\n🌍 {world.name}\n📝 {world.description}\n🆔 ID: {world.id}",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    return ConversationHandler.END

async def world_select_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            await update.message.reply_text("❌ Вы не авторизованы")
            return
        worlds = await session.execute(select(World))
        worlds = worlds.scalars().all()
        if not worlds:
            await update.message.reply_text("❌ Нет миров. Создайте с '➕ Создать мир'")
            return
        keyboard = []
        for world in worlds:
            keyboard.append([InlineKeyboardButton(f"🌍 {world.name}", callback_data=f"select_world_{world.id}")])
        await update.message.reply_text(
            "🌐 **Выберите мир:**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def world_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    world_id = int(query.data.split('_')[2])
    user_id = query.from_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if user:
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

world_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('world_new', world_new_start),
        MessageHandler(filters.Regex('^➕ Создать мир$'), world_new_start)
    ],
    states={
        WORLD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, world_new_name)],
        WORLD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, world_new_description)],
    },
    fallbacks=[CommandHandler('cancel', lambda u,c: u.message.reply_text("❌ Создание отменено"))]
)

# ----- ЛОРБУК -----

async def lore_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 **Добавление в лорбук**\n\nВведите заголовок записи:")
    return LORE_TITLE

async def lore_add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lore_title'] = update.message.text
    await update.message.reply_text("Введите содержание записи:")
    return LORE_CONTENT

async def lore_add_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lore_content'] = update.message.text
    await update.message.reply_text("Введите категорию (история, география, магия):")
    return LORE_CATEGORY

async def lore_add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['lore_category'] = update.message.text
    await update.message.reply_text("Введите теги через запятую (или 'пропустить'):")
    return LORE_TAGS

async def lore_add_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tags_text = update.message.text
    tags = []
    if tags_text.lower() != 'пропустить':
        tags = [t.strip() for t in tags_text.split(',') if t.strip()]
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            await update.message.reply_text("❌ Ошибка")
            return ConversationHandler.END
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
            tags=tags
        )
        session.add(lore)
        await session.commit()
        await update.message.reply_text(
            f"✅ **Запись добавлена!**\n\n📖 {lore.title}\n📂 {lore.category}",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
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

# ----- ПАМЯТЬ (ОБНОВЛЁННАЯ) -----

async def memory_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 **Добавить воспоминание**\n\nВведите воспоминание:")
    return 1

async def memory_add_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    content = update.message.text
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user or not user.active_persona_id:
            await update.message.reply_text("❌ Сначала создайте персону")
            return ConversationHandler.END
        
        character_id = user.active_character_id if user.active_character_id else None
        
        memory = Memory(
            persona_id=user.active_persona_id,
            character_id=character_id,
            content=content,
            memory_type='personal',
            importance=1.0
        )
        session.add(memory)
        await session.commit()
        await update.message.reply_text(
            "✅ **Воспоминание сохранено!**\n\n"
            "Теперь бот будет помнить это в диалогах.",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    return ConversationHandler.END

async def memory_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всех воспоминаний"""
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        
        if not user or not user.active_persona_id:
            await update.message.reply_text("❌ Сначала создайте персону")
            return
        
        memories = await session.execute(
            select(Memory).where(Memory.persona_id == user.active_persona_id)
            .order_by(Memory.importance.desc()).limit(30)
        )
        memories = memories.scalars().all()
        
        if not memories:
            await update.message.reply_text("🧠 У вас пока нет воспоминаний\n\nДобавьте их через '🧠 Память' или просто играйте — важные события сохраняются автоматически!")
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
    """Поиск по воспоминаниям"""
    user_id = update.effective_user.id
    
    query = ' '.join(context.args) if context.args else None
    if not query:
        await update.message.reply_text(
            "🔍 **Поиск по памяти**\n\n"
            "Используйте: /memory_search <запрос>\n"
            "Например: /memory_search дракон",
            parse_mode='Markdown'
        )
        return
    
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        
        if not user or not user.active_persona_id:
            await update.message.reply_text("❌ Сначала создайте персону")
            return
        
        memories = await session.execute(
            select(Memory).where(
                Memory.persona_id == user.active_persona_id,
                Memory.content.ilike(f"%{query}%")
            ).order_by(Memory.importance.desc()).limit(20)
        )
        memories = memories.scalars().all()
        
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
            
            if len(text) > 3000:
                text += "...\n(показаны не все результаты)"
                break
        
        await update.message.reply_text(text, parse_mode='Markdown')

async def memory_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление воспоминания по ID"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "🗑️ **Удаление воспоминания**\n\n"
            "Используйте: /memory_delete <ID>\n"
            "ID можно узнать через /memory_list",
            parse_mode='Markdown'
        )
        return
    
    try:
        memory_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")
        return
    
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        
        if not user or not user.active_persona_id:
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

# ----- АВТО-СОХРАНЕНИЕ ВАЖНЫХ СОБЫТИЙ -----

async def auto_save_memory(persona_id, character_id, user_message, bot_response, session):
    """Автоматически сохраняет важные события в память"""
    
    important_keywords = ['победил', 'нашел', 'встретил', 'получил', 'узнал', 'спас', 'убил', 'открыл', 'нашёл', 'убила', 'победила', 'нашла']
    
    text_to_check = f"{user_message} {bot_response}".lower()
    is_important = any(keyword in text_to_check for keyword in important_keywords)
    
    if is_important and len(user_message) > 10:
        memory_text = f"📌 {user_message[:100]}"
        if len(user_message) > 100:
            memory_text += "..."
        
        existing = await session.execute(
            select(Memory).where(
                Memory.persona_id == persona_id,
                Memory.content.ilike(f"%{user_message[:50]}%")
            )
        )
        existing = existing.scalar_one_or_none()
        
        if not existing:
            memory = Memory(
                persona_id=persona_id,
                character_id=character_id,
                content=memory_text,
                memory_type='personal',
                importance=0.7,
                is_auto=True
            )
            session.add(memory)
            await session.commit()
            return True
    return False

# ----- РЕЖИМ СЦЕНАРИЯ -----

async def toggle_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Включить/выключить режим сценария"""
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if user:
            user.scenario_mode = not user.scenario_mode
            if user.scenario_mode:
                user.scenario_context = None
            await session.commit()
            
            status = "ВКЛЮЧЁН ✅" if user.scenario_mode else "ВЫКЛЮЧЕН ❌"
            await update.message.reply_text(
                f"🎬 **Режим сценария {status}**\n\n"
                f"{'Теперь бот будет вести сюжет! Просто пишите свои действия.' if user.scenario_mode else 'Теперь бот будет отвечать в обычном режиме.'}",
                parse_mode='Markdown'
            )

# ----- ВКЛЮЧЕНИЕ/ВЫКЛЮЧЕНИЕ МИРА -----

async def toggle_world(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if user:
            user.active_world_enabled = not user.active_world_enabled
            await session.commit()
            status = "ВКЛЮЧЕН ✅" if user.active_world_enabled else "ВЫКЛЮЧЕН ❌"
            await update.message.reply_text(f"🌐 Мир {status}")

# ----- НАСТРОЙКА ДЛИНЫ ОТВЕТА -----

async def set_max_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            await update.message.reply_text("❌ Пользователь не найден")
            return
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
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if user:
            user.max_tokens = tokens
            await session.commit()
            await query.edit_message_text(f"✅ **Длина ответа:** {tokens} токенов")

# ----- ОСНОВНОЙ ДИАЛОГ -----

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
            await update.message.reply_text(
                "👋 Привет! Сначала создай персону ('👤 Моя персона' → '➕ Создать/редактировать') и персонажа-бота ('🎭 Персонажи (боты)' → '➕ Создать персонажа')",
                reply_markup=get_main_keyboard()
            )
            return
        
        if not user.active_persona_id:
            await update.message.reply_text(
                "❌ Сначала создай персону: '👤 Моя персона' → '➕ Создать/редактировать'",
                reply_markup=get_main_keyboard()
            )
            return
        persona = await session.get(Persona, user.active_persona_id)
        if not persona:
            await update.message.reply_text("❌ Персона не найдена")
            return
        
        if not user.active_character_id:
            await update.message.reply_text(
                "❌ Сначала выбери персонажа-бота: '🎭 Персонажи (боты)' → '👤 Выбрать персонажа'",
                reply_markup=get_main_keyboard()
            )
            return
        character = await session.get(Character, user.active_character_id)
        if not character:
            user.active_character_id = None
            await session.commit()
            await update.message.reply_text("❌ Персонаж не найден")
            return
        
        # ---- РЕЖИМ СЦЕНАРИЯ ----
        scenario_prompt = ""
        if user.scenario_mode:
            scenario_prompt = f"""
Ты - {character.name}, ведущий/мастер игры в режиме сценария.

Твоя задача - вести сюжет, описывать сцены и реагировать на действия игрока.

Правила:
1. Начинай с описания сцены (где находится игрок, что происходит вокруг)
2. После описания сцены дай игроку выбор действий (2-3 варианта)
3. Реагируй на действия игрока, развивай сюжет
4. Если игрок отклоняется от сценария - мягко возвращай его в сюжет
5. Добавляй повороты сюжета, встречи с NPC, находки

Игрок: {persona.name}
Описание игрока: {persona.appearance or 'неизвестно'}, {persona.personality or 'неизвестно'}
Цель игрока: {persona.goal or 'не указана'}

{user.scenario_context or 'Начни новую сцену. Опиши место и предложи игроку выбор действий.'}
"""
        
        # Собираем информацию о мире
        world_info = ""
        if user.active_world_enabled and character.world_id:
            world = await session.get(World, character.world_id)
            if world:
                world_info = f"Мир: {world.name}\n{world.description[:200] if world.description else ''}"
                lore = await session.execute(
                    select(LoreEntry).where(LoreEntry.world_id == world.id).limit(5)
                )
                lore = lore.scalars().all()
                if lore:
                    world_info += "\n\nЗнания о мире:\n" + "\n".join([f"- {l.title}: {l.content[:150]}..." for l in lore])
        
        # Формируем основной промпт
        if user.scenario_mode:
            system_prompt = f"""Ты — {character.name}.
Роль: {character.role or 'ведущий сценария'}
Описание: {character.description or 'не описано'}
Характер: {character.personality or 'не описан'}

{scenario_prompt}

{world_info}

Отвечай от лица {character.name} как ведущий сценария. Будь креативен, описывай атмосферу, давай выбор. Используй markdown для форматирования.
"""
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
        
        # История диалога
        history_limit = 15 if user.scenario_mode else 10
        history = await session.execute(
            select(ChatHistory).where(
                ChatHistory.persona_id == persona.id,
                ChatHistory.character_id == character.id
            ).order_by(ChatHistory.timestamp.desc()).limit(history_limit)
        )
        history = history.scalars().all()[::-1]
        
        # Получаем воспоминания персоны
        memories = await session.execute(
            select(Memory).where(Memory.persona_id == persona.id)
            .order_by(Memory.importance.desc()).limit(5)
        )
        memories = memories.scalars().all()
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Добавляем воспоминания в промпт
        if memories:
            memory_text = "\n\nВоспоминания:\n" + "\n".join([f"- {m.content}" for m in memories])
            messages[0]["content"] += memory_text
        
        for h in history:
            messages.append({"role": "user", "content": h.user_message})
            messages.append({"role": "assistant", "content": h.bot_response})
        messages.append({"role": "user", "content": user_message})
        
        # Запрос к AI
        openai.api_key = POLZA_API_KEY
        openai.base_url = "https://polza.ai/api/v1/"
        max_tokens = user.max_tokens or 1500
        
        try:
            response = openai.chat.completions.create(
                model=POLZA_MODEL,
                messages=messages,
                temperature=TEMPERATURE + 0.1 if user.scenario_mode else TEMPERATURE,
                max_tokens=max_tokens,
                extra_headers={"HTTP-Referer": "https://bothost.ru/"}
            )
            bot_response = response.choices[0].message.content
        except Exception as e:
            bot_response = f"❌ Ошибка: {str(e)}"
        
        # ---- АВТО-СОХРАНЕНИЕ ВАЖНЫХ СОБЫТИЙ ----
        try:
            saved = await auto_save_memory(
                persona.id,
                character.id,
                user_message,
                bot_response,
                session
            )
            if saved:
                print(f"📌 Авто-сохранено воспоминание для {persona.name}")
        except Exception as e:
            print(f"Ошибка авто-сохранения: {e}")
        
        # Сохраняем контекст сценария
        if user.scenario_mode:
            user.scenario_context = f"Последнее событие: {user_message[:100]}\nОтвет ведущего: {bot_response[:200]}..."
            await session.commit()
        
        chat_entry = ChatHistory(
            persona_id=persona.id,
            character_id=character.id,
            world_id=character.world_id,
            user_message=user_message,
            bot_response=bot_response
        )
        session.add(chat_entry)
        await session.commit()
        
        await update.message.reply_text(
            f"**{character.name}:**\n\n{bot_response}",
            parse_mode='Markdown'
        )

# ============================================
# ЗАПУСК
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async for session in get_db():
        user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = user.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id, username=update.effective_user.username)
            session.add(user)
            await session.commit()
        
        persona_name = "не создана"
        if user.active_persona_id:
            persona = await session.get(Persona, user.active_persona_id)
            if persona:
                persona_name = persona.name
        
        char_name = "не выбран"
        if user.active_character_id:
            character = await session.get(Character, user.active_character_id)
            if character:
                char_name = character.name
        
        scenario_status = "✅ ВКЛ" if user.scenario_mode else "❌ ВЫКЛ"
        
        await update.message.reply_text(
            f"""🌟 **HFSI RPG Bot**

👤 Персона: **{persona_name}**
🎭 Активный бот: **{char_name}**
📏 Длина: **{user.max_tokens}** токенов
🎬 Сценарий: **{scenario_status}**

**Как это работает:**
1. Создай свою **персону** (кто ты)
2. Создай **персонажей-ботов** (с кем общаешься)
3. Выбери бота и просто пиши сообщения!
4. Включи **режим сценария** для сюжетной игры

**Память:**
- Добавляй воспоминания через 🧠 Память
- Ищи по памяти через 🔍 Поиск по памяти
- Важные события сохраняются автоматически!

Используй кнопки меню для управления.""",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )

async def main():
    await init_db()
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("scenario", toggle_scenario))
    application.add_handler(CommandHandler("memory_list", memory_list))
    application.add_handler(CommandHandler("memory_search", memory_search))
    application.add_handler(CommandHandler("memory_delete", memory_delete))
    
    # Персона
    application.add_handler(persona_conv_handler)
    application.add_handler(CommandHandler("persona_select", persona_select_command))
    application.add_handler(CallbackQueryHandler(persona_select_callback, pattern="^select_persona_"))
    
    # Персонажи-боты
    application.add_handler(character_conv_handler)
    application.add_handler(CommandHandler("character_list", character_list))
    application.add_handler(CommandHandler("character_select", character_select_command))
    application.add_handler(CallbackQueryHandler(character_select_callback, pattern="^select_char_"))
    
    # Миры
    application.add_handler(world_conv_handler)
    application.add_handler(CommandHandler("world_list", world_list))
    application.add_handler(CommandHandler("world_select", world_select_start))
    application.add_handler(CallbackQueryHandler(world_select_callback, pattern="^select_world_"))
    
    # Лорбук
    application.add_handler(lore_conv_handler)
    
    # Память
    application.add_handler(memory_conv_handler)
    
    # Настройки
    application.add_handler(CommandHandler("toggle_world", toggle_world))
    application.add_handler(CommandHandler("set_tokens", set_max_tokens))
    application.add_handler(CallbackQueryHandler(set_tokens_callback, pattern="^tokens_"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons))
    
    print("🚀 Бот запущен!")
    print("📱 @HFSI_AI_bot")
    print("🎬 Режим сценария: готов")
    print("🧠 Расширенная память: готова")
    print("🔍 Поиск по памяти: готов")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
