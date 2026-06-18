import os
import asyncio
import nest_asyncio
nest_asyncio.apply()

from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler, ContextTypes
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, JSON, Table, select
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import openai

# ============================================
# ТОКЕНЫ (из переменных окружения на Render)
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
POLZA_API_KEY = os.getenv("POLZA_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///hfsi_bot.db")
POLZA_MODEL = "deepseek/deepseek-v4-flash"
TEMPERATURE = 0.8

# ============================================
# БАЗА ДАННЫХ
# ============================================

Base = declarative_base()

character_world = Table(
    'character_world',
    Base.metadata,
    Column('character_id', Integer, ForeignKey('characters.id')),
    Column('world_id', Integer, ForeignKey('worlds.id'))
)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    active_character_id = Column(Integer, ForeignKey('characters.id'))
    active_world_enabled = Column(Boolean, default=True)

class World(Base):
    __tablename__ = 'worlds'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey('users.id'))
    characters = relationship('Character', secondary=character_world, back_populates='worlds')
    lore_entries = relationship('LoreEntry', back_populates='world')

class Character(Base):
    __tablename__ = 'characters'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    backstory = Column(Text)
    personality = Column(Text)
    user_id = Column(Integer, ForeignKey('users.id'))
    current_world_id = Column(Integer, ForeignKey('worlds.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    user = relationship('User', foreign_keys=[user_id])
    worlds = relationship('World', secondary=character_world, back_populates='characters')
    memories = relationship('Memory', back_populates='character')

class LoreEntry(Base):
    __tablename__ = 'lore_entries'
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(50))
    world_id = Column(Integer, ForeignKey('worlds.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    tags = Column(JSON, default=list)
    world = relationship('World', back_populates='lore_entries')

class Memory(Base):
    __tablename__ = 'memories'
    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey('characters.id'))
    content = Column(Text, nullable=False)
    memory_type = Column(String(20), default='personal')
    importance = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    character = relationship('Character', back_populates='memories')

class ChatHistory(Base):
    __tablename__ = 'chat_history'
    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey('characters.id'))
    world_id = Column(Integer, ForeignKey('worlds.id'))
    user_message = Column(Text)
    bot_response = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    character = relationship('Character')

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ База данных готова")

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# ============================================
# МЕНЮ
# ============================================

def get_main_keyboard():
    return ReplyKeyboardMarkup([
        ["🎭 Персонажи", "🌍 Миры"],
        ["📚 Лорбук", "🧠 Память"],
        ["💬 Диалог", "⚙️ Настройки"]
    ], resize_keyboard=True)

# ============================================
# КОМАНДЫ
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌟 **HFSI RPG Bot**\n\n"
        "Я помогаю вести ролевые игры с AI!\n\n"
        "Используйте кнопки меню ниже.",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Я пока учусь! Скоро я научусь отвечать на любые сообщения. А пока пользуйтесь кнопками меню.")

# ============================================
# ЗАПУСК
# ============================================

async def main():
    await init_db()
    print("🚀 Бот запускается...")
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот готов!")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
