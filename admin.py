"""
admin.py — Панель администратора.

Возможности:
  • /admin            — войти (верификация по номеру телефона)
  • 📋 Активные сессии — список групп
  • 📢 Авторассылка    — старт/стоп по КД
  • 🔗 Заменить ссылку — поменять ссылку/текст внутри шаблона
  • ⚙️ Настройки       — КД и шаблон сообщения
  • 🎧 Поддержка       — ответы пользователям
"""

import asyncio
import logging
from typing import Dict, Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────
ADMIN_PHONE = "+79215242167"

# ─────────────────────────────────────────
# ГЛОБАЛЬНОЕ ХРАНИЛИЩЕ (in-memory)
# ─────────────────────────────────────────
verified_admins: set[int] = set()
active_sessions: Dict[int, str] = {}      # {chat_id: title}
support_queue:   Dict[int, str] = {}      # {user_id: text}

broadcast_settings: Dict = {
    "template":  "📢 Реклама!\n\n{link}\n\nПодписывайтесь!",
    "link":      "https://t.me/example",   # Заменяемая ссылка/текст
    "cooldown":  60,                        # Секунды между сообщениями
    "running":   False,
}

_broadcast_task: Optional[asyncio.Task] = None

admin_router = Router()


# ─────────────────────────────────────────
# FSM
# ─────────────────────────────────────────
class AdminStates(StatesGroup):
    waiting_phone = State()
    main_menu     = State()
    set_link      = State()
    set_template  = State()
    set_cooldown  = State()
    support_reply = State()


# ─────────────────────────────────────────
# КЛАВИАТУРЫ
# ─────────────────────────────────────────
def admin_menu_kb() -> InlineKeyboardMarkup:
    status = "🟢 Стоп рассылку" if broadcast_settings["running"] else "🔴 Старт рассылки"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Активные сессии",   callback_data="admin_sessions")],
        [InlineKeyboardButton(text=f"📢 {status}",         callback_data="admin_toggle_broadcast")],
        [InlineKeyboardButton(text="🔗 Заменить ссылку",  callback_data="admin_set_link")],
        [InlineKeyboardButton(text="⚙️ Настройки",        callback_data="admin_settings")],
        [InlineKeyboardButton(text="🎧 Поддержка",        callback_data="admin_support")],
        [InlineKeyboardButton(text="❌ Выйти",            callback_data="admin_logout")],
    ])


def back_kb(target: str = "admin_back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data=target)]
    ])


def settings_kb() -> InlineKeyboardMarkup:
    cd = broadcast_settings["cooldown"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⏱ КД: {cd} сек — изменить", callback_data="settings_cooldown")],
        [InlineKeyboardButton(text="📝 Изменить шаблон",          callback_data="settings_template")],
        [InlineKeyboardButton(text="↩️ Назад",                    callback_data="admin_back")],
    ])


# ─────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    return user_id in verified_admins


def render_message() -> str:
    return broadcast_settings["template"].format(link=broadcast_settings["link"])


async def _auto_broadcast_loop(bot: Bot) -> None:
    logger.info("Авторассылка запущена")
    while broadcast_settings["running"]:
        text = render_message()
        for chat_id in list(active_sessions.keys()):
            try:
                await bot.send_message(chat_id, text)
            except Exception as e:
                logger.warning(f"Ошибка рассылки в {chat_id}: {e}")
        await asyncio.sleep(broadcast_settings["cooldown"])
    logger.info("Авторассылка остановлена")


async def start_broadcast(bot: Bot) -> None:
    global _broadcast_task
    if _broadcast_task and not _broadcast_task.done():
        return
    broadcast_settings["running"] = True
    _broadcast_task = asyncio.create_task(_auto_broadcast_loop(bot))


async def stop_broadcast() -> None:
    global _broadcast_task
    broadcast_settings["running"] = False
    if _broadcast_task and not _broadcast_task.done():
        _broadcast_task.cancel()
        try:
            await _broadcast_task
        except asyncio.CancelledError:
            pass


# ─────────────────────────────────────────
# ВХОД /admin
# ─────────────────────────────────────────
@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer("👑 Панель администратора доступна только в личных сообщениях.")
        return

    uid = message.from_user.id
    if is_admin(uid):
        await state.set_state(AdminStates.main_menu)
        await message.answer(
            "👑 <b>Панель администратора</b>\n\nВыберите действие:",
            reply_markup=admin_menu_kb(),
        )
        return

    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await state.set_state(AdminStates.waiting_phone)
    await message.answer("🔐 Для входа отправьте свой номер телефона:", reply_markup=kb)


# ─────────────────────────────────────────
# ВЕРИФИКАЦИЯ
# ─────────────────────────────────────────
@admin_router.message(AdminStates.waiting_phone, F.contact)
async def verify_phone(message: Message, state: FSMContext) -> None:
    from aiogram.types import ReplyKeyboardRemove

    contact = message.contact
    if contact.user_id != message.from_user.id:
        await message.answer("⛔ Отправьте именно свой контакт.")
        return

    phone = contact.phone_number.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone

    if phone == ADMIN_PHONE:
        verified_admins.add(message.from_user.id)
        logger.info(f"Админ верифицирован: {message.from_user.id}")
        await state.set_state(AdminStates.main_menu)
        await message.answer(
            "✅ Верификация прошла!\n\n👑 <b>Добро пожаловать, администратор</b>",
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer("Выберите действие:", reply_markup=admin_menu_kb())
    else:
        await state.clear()
        await message.answer("⛔ Доступ запрещён.", reply_markup=ReplyKeyboardRemove())


@admin_router.message(AdminStates.waiting_phone)
async def verify_wrong(message: Message) -> None:
    await message.answer("Нажмите кнопку для отправки контакта.")


# ─────────────────────────────────────────
# АКТИВНЫЕ СЕССИИ
# ─────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_sessions")
async def cb_sessions(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    if not active_sessions:
        text = "📋 <b>Активные сессии</b>\n\nБот ещё не добавлен ни в одну группу."
    else:
        lines = [f"📋 <b>Активные сессии</b> ({len(active_sessions)}):\n"]
        for chat_id, title in active_sessions.items():
            lines.append(f"• <b>{title}</b>\n  <code>{chat_id}</code>")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=admin_menu_kb())
    await callback.answer()


# ─────────────────────────────────────────
# АВТОРАССЫЛКА — СТАРТ / СТОП
# ─────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_toggle_broadcast")
async def cb_toggle_broadcast(callback: CallbackQuery, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    if not active_sessions:
        await callback.answer("⚠️ Нет групп для рассылки! Сначала добавьте бота в группу.", show_alert=True)
        return

    if broadcast_settings["running"]:
        await stop_broadcast()
        note = "🔴 Авторассылка <b>остановлена</b>"
    else:
        await start_broadcast(bot)
        note = "🟢 Авторассылка <b>запущена</b>"

    cd = broadcast_settings["cooldown"]
    preview = render_message()
    await callback.message.edit_text(
        f"📢 <b>Управление рассылкой</b>\n\n"
        f"{note}\n"
        f"⏱ КД: <b>{cd} сек</b>  |  👥 Групп: <b>{len(active_sessions)}</b>\n\n"
        f"<b>Текущее сообщение:</b>\n<i>{preview}</i>",
        reply_markup=admin_menu_kb(),
    )
    await callback.answer()


# ─────────────────────────────────────────
# ЗАМЕНА ССЫЛКИ
# ─────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_set_link")
async def cb_set_link(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    current = broadcast_settings["link"]
    await state.set_state(AdminStates.set_link)
    await callback.message.edit_text(
        f"🔗 <b>Замена ссылки / текста</b>\n\n"
        f"Сейчас: <code>{current}</code>\n\n"
        f"Отправьте новую ссылку или любой текст — он подставится в шаблон на место <code>{{link}}</code>:",
        reply_markup=back_kb("admin_back"),
    )
    await callback.answer()


@admin_router.message(AdminStates.set_link, F.text)
async def do_set_link(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    broadcast_settings["link"] = message.text.strip()
    logger.info(f"Ссылка обновлена: {broadcast_settings['link']}")
    await state.set_state(AdminStates.main_menu)

    preview = render_message()
    await message.answer(
        f"✅ <b>Ссылка / текст обновлены!</b>\n\n"
        f"<b>Предпросмотр сообщения:</b>\n\n<i>{preview}</i>",
        reply_markup=admin_menu_kb(),
    )


# ─────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_settings")
async def cb_settings(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    cd   = broadcast_settings["cooldown"]
    tmpl = broadcast_settings["template"]
    link = broadcast_settings["link"]
    await callback.message.edit_text(
        f"⚙️ <b>Настройки рассылки</b>\n\n"
        f"⏱ <b>КД между сообщениями:</b> {cd} сек\n"
        f"🔗 <b>Ссылка / текст:</b> <code>{link}</code>\n\n"
        f"📝 <b>Шаблон:</b>\n<code>{tmpl}</code>\n\n"
        f"<i>Переменная <code>{{link}}</code> заменяется текущей ссылкой.</i>",
        reply_markup=settings_kb(),
    )
    await callback.answer()


@admin_router.callback_query(F.data == "settings_cooldown")
async def cb_settings_cooldown(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.set_cooldown)
    await callback.message.edit_text(
        f"⏱ <b>Изменение КД</b>\n\n"
        f"Текущий: <b>{broadcast_settings['cooldown']} сек</b>\n\n"
        f"Введите новое значение в секундах (минимум 10):",
        reply_markup=back_kb("admin_settings"),
    )
    await callback.answer()


@admin_router.message(AdminStates.set_cooldown, F.text)
async def do_set_cooldown(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    val = message.text.strip()
    if not val.isdigit() or int(val) < 10:
        await message.answer("⚠️ Введите целое число не меньше 10 (секунды).")
        return

    broadcast_settings["cooldown"] = int(val)
    logger.info(f"КД обновлён: {broadcast_settings['cooldown']} сек")
    await state.set_state(AdminStates.main_menu)
    await message.answer(
        f"✅ КД обновлён: <b>{broadcast_settings['cooldown']} сек</b>",
        reply_markup=admin_menu_kb(),
    )


@admin_router.callback_query(F.data == "settings_template")
async def cb_settings_template(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.set_template)
    await callback.message.edit_text(
        "📝 <b>Изменение шаблона</b>\n\n"
        "Напишите новый шаблон. Используйте <code>{link}</code> — туда подставится ссылка.\n\n"
        "<b>Пример:</b>\n"
        "<code>🔥 Лучший канал!\n\n{link}\n\nЖми и подписывайся!</code>",
        reply_markup=back_kb("admin_settings"),
    )
    await callback.answer()


@admin_router.message(AdminStates.set_template, F.text)
async def do_set_template(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    tmpl = message.text.strip()
    if "{link}" not in tmpl:
        await message.answer(
            "⚠️ Шаблон должен содержать <code>{link}</code>.\n"
            "Это место, куда подставится ссылка. Попробуйте снова."
        )
        return

    broadcast_settings["template"] = tmpl
    logger.info("Шаблон обновлён")
    await state.set_state(AdminStates.main_menu)

    preview = render_message()
    await message.answer(
        f"✅ <b>Шаблон обновлён!</b>\n\n<b>Предпросмотр:</b>\n\n<i>{preview}</i>",
        reply_markup=admin_menu_kb(),
    )


# ─────────────────────────────────────────
# ПОДДЕРЖКА
# ─────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_support")
async def cb_support(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    if not support_queue:
        await callback.message.edit_text(
            "🎧 <b>Поддержка</b>\n\nОчередь пуста — обращений нет.",
            reply_markup=admin_menu_kb(),
        )
    else:
        buttons = []
        for uid, msg_text in support_queue.items():
            preview = msg_text[:28] + "…" if len(msg_text) > 28 else msg_text
            buttons.append([InlineKeyboardButton(
                text=f"👤 {uid}: {preview}",
                callback_data=f"support_reply:{uid}",
            )])
        buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="admin_back")])
        await callback.message.edit_text(
            f"🎧 <b>Поддержка</b> — обращений: {len(support_queue)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("support_reply:"))
async def cb_support_reply(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    uid = int(callback.data.split(":")[1])
    await state.update_data(reply_to_uid=uid)
    await state.set_state(AdminStates.support_reply)

    original = support_queue.get(uid, "(нет текста)")
    await callback.message.edit_text(
        f"🎧 Ответ пользователю <code>{uid}</code>\n\n"
        f"<b>Его сообщение:</b>\n{original}\n\n"
        f"Введите ответ:",
        reply_markup=back_kb("admin_support"),
    )
    await callback.answer()


@admin_router.message(AdminStates.support_reply, F.text)
async def do_support_reply(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    uid = data.get("reply_to_uid")
    try:
        await bot.send_message(uid, f"🎧 <b>Ответ от поддержки</b>\n\n{message.text}")
        support_queue.pop(uid, None)
        await message.answer("✅ Ответ отправлен!", reply_markup=admin_menu_kb())
    except Exception as e:
        logger.error(f"Ошибка ответа {uid}: {e}")
        await message.answer(f"❌ Ошибка: {e}", reply_markup=admin_menu_kb())

    await state.set_state(AdminStates.main_menu)


# ─────────────────────────────────────────
# НАВИГАЦИЯ
# ─────────────────────────────────────────
@admin_router.callback_query(F.data == "admin_back")
async def cb_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.main_menu)
    await callback.message.edit_text(
        "👑 <b>Панель администратора</b>\n\nВыберите действие:",
        reply_markup=admin_menu_kb(),
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin_logout")
async def cb_logout(callback: CallbackQuery, state: FSMContext) -> None:
    verified_admins.discard(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text("👋 Вы вышли из панели администратора.")
    await callback.answer()


# ─────────────────────────────────────────
# ОТСЛЕЖИВАНИЕ ГРУПП
# ─────────────────────────────────────────
@admin_router.my_chat_member()
async def track_chat_member(event, bot: Bot) -> None:
    from aiogram.types import ChatMemberUpdated
    update: ChatMemberUpdated = event
    chat = update.chat
    new_status = update.new_chat_member.status

    if new_status in ("member", "administrator"):
        active_sessions[chat.id] = chat.title or str(chat.id)
        logger.info(f"Бот добавлен: {chat.title} ({chat.id}) — {new_status}")
        if new_status == "member":
            try:
                await bot.send_message(
                    chat.id,
                    "⚠️ <b>Нужны права администратора!</b>\n\n"
                    "Выдайте мне права администратора группы для работы рассылки.",
                )
            except Exception:
                pass
    elif new_status in ("left", "kicked", "banned"):
        active_sessions.pop(chat.id, None)
        logger.info(f"Бот удалён из группы: {chat.id}")
