"""
stant.py — Пользовательский режим (обычные участники).

Возможности:
  • /start      — приветствие
  • /help       — помощь
  • /support    — написать в поддержку (из ЛС бота)
  • Получение рассылок от администратора
  • В группах: бот проверяет наличие прав администратора перед работой
"""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# Импортируем очередь поддержки из admin.py
from admin import support_queue

logger = logging.getLogger(__name__)

user_router = Router()


# ─────────────────────────────────────────
# FSM — состояния пользователя
# ─────────────────────────────────────────
class UserStates(StatesGroup):
    support_message = State()   # Ввод обращения в поддержку


# ─────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────
async def bot_is_admin_in_chat(bot: Bot, chat_id: int) -> bool:
    """Проверяет, является ли бот администратором в указанном чате."""
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        return member.status == "administrator"
    except Exception as e:
        logger.warning(f"Не удалось проверить статус бота в чате {chat_id}: {e}")
        return False


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎧 Написать в поддержку", callback_data="open_support")],
        [InlineKeyboardButton(text="ℹ️ Помощь",              callback_data="open_help")],
    ])


# ─────────────────────────────────────────
# /start
# ─────────────────────────────────────────
@user_router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    chat = message.chat

    # В личных сообщениях — стандартное приветствие
    if chat.type == "private":
        await message.answer(
            f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
            "Я бот для групповых рассылок и поддержки.\n\n"
            "• Добавьте меня в группу и выдайте права <b>администратора</b>.\n"
            "• Через меня вы можете обратиться в поддержку.",
            reply_markup=main_kb(),
        )
        return

    # В группе — проверяем, является ли бот администратором
    if not await bot_is_admin_in_chat(bot, chat.id):
        await message.answer(
            "⚠️ <b>Требуются права администратора!</b>\n\n"
            "Для корректной работы выдайте мне права администратора этой группы.\n"
            "После этого все функции будут доступны.",
        )
    else:
        await message.answer(
            "✅ <b>Бот активен и готов к работе!</b>\n\n"
            "Администратор может запустить рассылку через ЛС-команду /admin.",
        )


# ─────────────────────────────────────────
# /help
# ─────────────────────────────────────────
@user_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    text = (
        "ℹ️ <b>Справка</b>\n\n"
        "<b>Для пользователей:</b>\n"
        "• /start — запустить бота\n"
        "• /help — эта справка\n"
        "• /support — написать в поддержку (только в ЛС)\n\n"
        "<b>Для администратора:</b>\n"
        "• /admin — войти в панель управления\n"
        "  — Рассылка по всем группам\n"
        "  — Просмотр активных сессий\n"
        "  — Ответы пользователям\n\n"
        "⚙️ Для работы в группе боту необходимы права <b>администратора</b>."
    )
    await message.answer(text)


# ─────────────────────────────────────────
# /support — ОБРАЩЕНИЕ В ПОДДЕРЖКУ
# ─────────────────────────────────────────
@user_router.message(Command("support"))
async def cmd_support(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer(
            "✉️ Обращения в поддержку принимаются только в личных сообщениях.\n"
            "Напишите мне в ЛС: /support"
        )
        return

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_support")]
    ])
    await state.set_state(UserStates.support_message)
    await message.answer(
        "🎧 <b>Поддержка</b>\n\n"
        "Опишите вашу проблему — администратор ответит вам в ближайшее время:",
        reply_markup=cancel_kb,
    )


@user_router.message(UserStates.support_message, F.text)
async def receive_support_message(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id
    support_queue[uid] = message.text

    logger.info(f"Новое обращение в поддержку от user_id={uid}")
    await state.clear()
    await message.answer(
        "✅ <b>Обращение принято!</b>\n\n"
        "Администратор рассмотрит его и ответит вам в этом чате.",
    )


@user_router.callback_query(F.data == "cancel_support")
async def cb_cancel_support(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Обращение отменено.")
    await callback.answer()


# ─────────────────────────────────────────
# INLINE-КНОПКИ ГЛАВНОГО МЕНЮ
# ─────────────────────────────────────────
@user_router.callback_query(F.data == "open_support")
async def cb_open_support(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message.chat.type != "private":
        await callback.answer("Поддержка доступна только в ЛС", show_alert=True)
        return

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_support")]
    ])
    await state.set_state(UserStates.support_message)
    await callback.message.edit_text(
        "🎧 <b>Поддержка</b>\n\n"
        "Опишите вашу проблему:",
        reply_markup=cancel_kb,
    )
    await callback.answer()


@user_router.callback_query(F.data == "open_help")
async def cb_open_help(callback: CallbackQuery) -> None:
    text = (
        "ℹ️ <b>Справка</b>\n\n"
        "• /start — запустить бота\n"
        "• /help — эта справка\n"
        "• /support — написать в поддержку (ЛС)\n\n"
        "Рассылки от администратора приходят автоматически."
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data="go_back_main")]
    ])
    await callback.message.edit_text(text, reply_markup=back_kb)
    await callback.answer()


@user_router.callback_query(F.data == "go_back_main")
async def cb_go_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=main_kb(),
    )
    await callback.answer()


# ─────────────────────────────────────────
# ЗАЩИТА ГРУППЫ: напоминание о правах
# (если кто-то пишет @бот без нужных прав)
# ─────────────────────────────────────────
@user_router.message(F.chat.type.in_({"group", "supergroup"}))
async def group_message_guard(message: Message, bot: Bot) -> None:
    """
    Перехватывает упоминания бота в группе.
    Если бот не администратор — напоминает об этом.
    Иначе — молчит (обработка рассылок происходит через send_message от admin).
    """
    me = await bot.get_me()
    # Реагируем только если упомянули бота напрямую
    if message.text and f"@{me.username}" in (message.text or ""):
        if not await bot_is_admin_in_chat(bot, message.chat.id):
            await message.reply(
                "⚠️ Мне нужны права <b>администратора</b> для работы в этой группе."
            )
