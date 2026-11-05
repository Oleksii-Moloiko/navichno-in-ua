"""Telegram-бот navichno.

Що вміє:
  1. Збирає заявку у 5 кроків і надсилає її в групу компанії.
  2. Допомагає обрати формат за трьома питаннями.
  3. Відповідає на типові питання кнопками (FAQ з сайту).
  4. Приймає матеріали (фото, відео, документи, тексти) і пересилає їх у групу
     відповіддю на заявку цієї родини.
  5. «Поговорити з людиною»: будь-яке повідомлення йде в групу, а reply з групи
     на це повідомлення бот повертає родині в особистий чат.

Налаштування через змінні середовища (див. .env.example).
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import sqlite3
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReactionTypeEmoji,
    ReplyKeyboardMarkup,
)

# ---------------------------------------------------------------------------
# Конфігурація
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", "0") or 0)
_thread = os.environ.get("GROUP_THREAD_ID", "").strip()
GROUP_THREAD_ID = int(_thread) if _thread else None
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
SITE_URL = os.environ.get("SITE_URL", "https://navichno.in.ua")
PHONE = os.environ.get("PHONE", "+380 73 982 83 38")
INSTAGRAM = os.environ.get("INSTAGRAM", "https://www.instagram.com/navichno.in.ua/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("navichno-bot")

# ---------------------------------------------------------------------------
# Сховище: SQLite, два невеликі словники
#   apps   — user_id -> id повідомлення із заявкою в групі
#   relay  — id повідомлення в групі -> user_id (для відповідей з групи)
# ---------------------------------------------------------------------------


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS apps (user_id INTEGER PRIMARY KEY, app_msg_id INTEGER, label TEXT)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS relay (group_msg_id INTEGER PRIMARY KEY, user_id INTEGER)")
        self.db.commit()

    def save_app(self, user_id: int, app_msg_id: int, label: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO apps (user_id, app_msg_id, label) VALUES (?, ?, ?)",
            (user_id, app_msg_id, label),
        )
        self.db.commit()

    def get_app(self, user_id: int) -> tuple[int, str] | None:
        row = self.db.execute("SELECT app_msg_id, label FROM apps WHERE user_id = ?", (user_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def save_relay(self, group_msg_id: int, user_id: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO relay (group_msg_id, user_id) VALUES (?, ?)", (group_msg_id, user_id))
        self.db.commit()

    def get_relay(self, group_msg_id: int) -> int | None:
        row = self.db.execute("SELECT user_id FROM relay WHERE group_msg_id = ?", (group_msg_id,)).fetchone()
        return row[0] if row else None


store = Store(DATA_DIR / "bot.sqlite3")

# ---------------------------------------------------------------------------
# Тексти й клавіатури
# ---------------------------------------------------------------------------

BTN_APPLY = "📝 Залишити заявку"
BTN_PICK = "🧭 Підібрати формат"
BTN_FAQ = "❓ Питання й відповіді"
BTN_MATERIALS = "📎 Надіслати матеріали"
BTN_HUMAN = "👤 Поговорити з людиною"
BTN_MENU = "🏠 Головне меню"
BTN_SKIP = "Пропустити"
BTN_CANCEL = "✖️ Скасувати"
BTN_TG_CONTACT = "💬 Написати мені тут, у Telegram"

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_APPLY)],
        [KeyboardButton(text=BTN_PICK), KeyboardButton(text=BTN_FAQ)],
        [KeyboardButton(text=BTN_MATERIALS), KeyboardButton(text=BTN_HUMAN)],
    ],
    resize_keyboard=True,
)

CANCEL_KB = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)
SKIP_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_SKIP)], [KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True
)
CONTACT_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Поділитися номером", request_contact=True)],
        [KeyboardButton(text=BTN_TG_CONTACT)],
        [KeyboardButton(text=BTN_CANCEL)],
    ],
    resize_keyboard=True,
)
MENU_ONLY_KB = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_MENU)]], resize_keyboard=True)

WELCOME = (
    "Вітаємо. Це бот сервісу <b>navichno</b> — сайти пам’яті та QR-коди на пам’ятники.\n\n"
    "Тут можна залишити заявку, підібрати формат сторінки, знайти відповіді на типові "
    "питання або надіслати нам фото й тексти.\n\n"
    "Ми на зв’язку 24/7. Якщо зручніше голосом — телефонуйте: " + html.escape(PHONE) + "."
)

FORMATS = {
    "memory": "Пам’ять",
    "story": "Історія",
    "legacy": "Спадщина",
    "custom": "Під ключ",
    "unsure": "Ще не знаю",
}

FORMAT_DESC = {
    "memory": "Одна гідна сторінка: біографія й дати, до 7 фото, до 4 нагород, цитата або епітафія, QR-код і посилання для рідних.",
    "story": "Повна історія життя: до 30 фото, до 10 нагород, таймлайн, «Слова, які пам’ятають», свічка пам’яті, місце поховання з маршрутом, спогади близьких, до 2 відео.",
    "legacy": "Цифровий меморіал, який родина веде сама: власна адмінка, фото й відео без обмежень, окремі розділи, спогади відвідувачів з модерацією, українська та англійська версії.",
    "custom": "Усе з варіанта «Спадщина», а також унікальний дизайн, власний домен, біографія від нашого автора, реставрація фото, пам’ятний відеоролик, металева пластина з QR.",
}

MONUMENT = {
    "has": "Пам’ятник уже є",
    "planned": "Пам’ятник ще у планах",
    "none": "Пам’ятника не буде, потрібна лише сторінка",
}

FAQ = [
    (
        "Скільки часу займає створення сайту?",
        "Після того як ви надіслали анкету й фото, сторінку «Пам’ять» ми готуємо за кілька днів, "
        "а більші варіанти — від одного до трьох тижнів. Точний строк назвемо одразу після розмови.",
    ),
    (
        "Чи можна змінити текст чи додати фото пізніше?",
        "Так. У варіантах «Пам’ять» та «Історія» зміни вносимо ми на ваше прохання. "
        "У варіантах «Спадщина» й «Під ключ» у вас є власна адмінка, де можна редагувати все самостійно.",
    ),
    (
        "Як довго працюватиме сайт?",
        "Ми створюємо сторінки, щоб вони працювали десятиліттями. Умови зберігання та підтримки фіксуємо в договорі.",
    ),
    (
        "Хто бачить спогади, які залишають люди?",
        "Жоден спогад не з’являється на сайті автоматично. Спершу його перевіряє родина або ми, "
        "і лише потім він публікується.",
    ),
    (
        "Як встановити QR-код на пам’ятник?",
        "Ми надаємо QR-код у форматі для гравіювання чи друку. У варіанті «Під ключ» виготовимо "
        "металеву пластину, яку легко закріпити на камені чи табличці.",
    ),
    (
        "Чи можна поділитися сторінкою з рідними за кордоном?",
        "Так, посилання відкривається з будь-якої країни й на будь-якому телефоні. "
        "У варіантах «Спадщина» й «Під ключ» є англійська версія.",
    ),
    (
        "Скільки це коштує?",
        "Вартість залежить від формату й побажань родини, тому називаємо її після короткої розмови. "
        "Залиште заявку, і ми підберемо рішення під ваш бюджет.",
    ),
]


def faq_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=q, callback_data=f"faq:{i}")] for i, (q, _) in enumerate(FAQ)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← До списку питань", callback_data="faq:list")],
            [InlineKeyboardButton(text="📝 Залишити заявку", callback_data="go:apply")],
        ]
    )


def inline_rows(prefix: str, items: dict[str, str], per_row: int = 1) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=v, callback_data=f"{prefix}:{k}") for k, v in items.items()]
    rows = [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_label(m: Message) -> str:
    u = m.from_user
    name = html.escape(u.full_name) if u else "невідомо"
    uname = f" @{u.username}" if u and u.username else ""
    uid = u.id if u else "?"
    return f"{name}{uname} (id {uid})"


# ---------------------------------------------------------------------------
# Стани
# ---------------------------------------------------------------------------


class Apply(StatesGroup):
    person = State()
    fmt = State()
    monument = State()
    contact = State()
    comment = State()


class Pick(StatesGroup):
    photos = State()
    edit = State()
    english = State()


class Chat(StatesGroup):
    materials = State()
    human = State()


# ---------------------------------------------------------------------------
# Роутери
# ---------------------------------------------------------------------------

private = Router()
private.message.filter(F.chat.type == ChatType.PRIVATE)
private.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

group = Router()
group.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


async def send_to_group(bot: Bot, text: str, reply_to: int | None = None) -> Message:
    return await bot.send_message(
        GROUP_CHAT_ID,
        text,
        message_thread_id=GROUP_THREAD_ID,
        reply_to_message_id=reply_to,
    )


async def go_menu(m: Message, state: FSMContext, text: str = "Чим ще можемо допомогти?") -> None:
    await state.clear()
    await m.answer(text, reply_markup=MAIN_KB)


# --- старт і меню -----------------------------------------------------------


@private.message(CommandStart())
@private.message(Command("menu"))
@private.message(F.text == BTN_MENU)
async def cmd_start(m: Message, state: FSMContext) -> None:
    await state.clear()
    await m.answer(WELCOME, reply_markup=MAIN_KB)


@private.message(F.text == BTN_CANCEL)
async def cmd_cancel(m: Message, state: FSMContext) -> None:
    await go_menu(m, state, "Добре, зупинилися. Повертайтеся, коли буде зручно.")


# --- 1. Заявка ----------------------------------------------------------------


@private.message(F.text == BTN_APPLY)
@private.callback_query(F.data == "go:apply")
async def apply_start(event: Message | CallbackQuery, state: FSMContext) -> None:
    m = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()
    await state.clear()
    await state.set_state(Apply.person)
    await m.answer(
        "Крок 1 з 5. Напишіть, будь ласка, <b>ім’я людини та роки життя</b>.\n"
        "Наприклад: <i>Іван Петренко, 1985–2023</i>",
        reply_markup=CANCEL_KB,
    )


@private.message(Apply.person, F.text)
async def apply_person(m: Message, state: FSMContext) -> None:
    await state.update_data(person=m.text.strip())
    await state.set_state(Apply.fmt)
    await m.answer(
        "Крок 2 з 5. <b>Який формат вас цікавить?</b>\nЯкщо ще не визначилися, оберіть «Ще не знаю», ми допоможемо.",
        reply_markup=inline_rows("fmt", FORMATS),
    )


@private.callback_query(Apply.fmt, F.data.startswith("fmt:"))
async def apply_fmt(c: CallbackQuery, state: FSMContext) -> None:
    key = c.data.split(":", 1)[1]
    await state.update_data(fmt=FORMATS.get(key, key))
    await c.answer()
    await c.message.edit_text(f"Формат: <b>{FORMATS.get(key, key)}</b>")
    await state.set_state(Apply.monument)
    await c.message.answer(
        "Крок 3 з 5. <b>Чи є вже пам’ятник</b>, на який ставитимемо QR-код?",
        reply_markup=inline_rows("mon", MONUMENT),
    )


@private.callback_query(Apply.monument, F.data.startswith("mon:"))
async def apply_monument(c: CallbackQuery, state: FSMContext) -> None:
    key = c.data.split(":", 1)[1]
    await state.update_data(monument=MONUMENT.get(key, key))
    await c.answer()
    await c.message.edit_text(f"Пам’ятник: <b>{MONUMENT.get(key, key)}</b>")
    await state.set_state(Apply.contact)
    await c.message.answer(
        "Крок 4 з 5. <b>Як з вами зв’язатися?</b>\n"
        "Поділіться номером, напишіть його текстом або оберіть спілкування тут, у Telegram.",
        reply_markup=CONTACT_KB,
    )


@private.message(Apply.contact, F.contact)
async def apply_contact_shared(m: Message, state: FSMContext) -> None:
    await state.update_data(contact=f"телефон {m.contact.phone_number}")
    await apply_ask_comment(m, state)


@private.message(Apply.contact, F.text)
async def apply_contact_text(m: Message, state: FSMContext) -> None:
    if m.text == BTN_TG_CONTACT:
        await state.update_data(contact="у Telegram (цей чат)")
    else:
        await state.update_data(contact=m.text.strip())
    await apply_ask_comment(m, state)


async def apply_ask_comment(m: Message, state: FSMContext) -> None:
    await state.set_state(Apply.comment)
    await m.answer(
        "Крок 5 з 5. Якщо хочете, <b>розкажіть коротко про людину</b> або про свої побажання. "
        "Цей крок можна пропустити.",
        reply_markup=SKIP_KB,
    )


@private.message(Apply.comment, F.text)
async def apply_comment(m: Message, state: FSMContext, bot: Bot) -> None:
    comment = "" if m.text == BTN_SKIP else m.text.strip()
    data = await state.get_data()

    text = (
        "🕯 <b>Нова заявка</b>\n\n"
        f"<b>Людина:</b> {html.escape(data.get('person', ''))}\n"
        f"<b>Формат:</b> {html.escape(data.get('fmt', ''))}\n"
        f"<b>Пам’ятник:</b> {html.escape(data.get('monument', ''))}\n"
        f"<b>Контакт:</b> {html.escape(data.get('contact', ''))}\n"
        f"<b>Від:</b> {user_label(m)}\n"
    )
    if comment:
        text += f"\n<b>Коментар:</b>\n{html.escape(comment)}\n"
    text += "\n<i>Відповідь reply на це повідомлення піде родині в чат.</i>"

    sent = await send_to_group(bot, text)
    store.save_app(m.from_user.id, sent.message_id, data.get("person", ""))
    store.save_relay(sent.message_id, m.from_user.id)

    await state.clear()
    await state.set_state(Chat.materials)
    await m.answer(
        "Дякуємо. Заявку отримали, ми зв’яжемося з вами найближчим часом.\n\n"
        "Уже зараз можете надсилати сюди <b>фото, відео, тексти чи скани нагород</b>: "
        "усе, що надішлете в цей чат, потрапить до вашої заявки.",
        reply_markup=MENU_ONLY_KB,
    )


# --- 2. Підбір формату --------------------------------------------------------

PHOTOS = {"7": "До 7 фото", "30": "До 30 фото", "inf": "Без обмежень"}
YESNO = {"yes": "Так", "no": "Ні"}


@private.message(F.text == BTN_PICK)
async def pick_start(m: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Pick.photos)
    await m.answer(
        "Три короткі питання, і ми підкажемо формат.\n\n1 з 3. <b>Скільки приблизно фото</b> хочете розмістити?",
        reply_markup=inline_rows("ph", PHOTOS, per_row=3),
    )


@private.callback_query(Pick.photos, F.data.startswith("ph:"))
async def pick_photos(c: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(photos=c.data.split(":", 1)[1])
    await c.answer()
    await state.set_state(Pick.edit)
    await c.message.edit_text(
        "2 з 3. <b>Чи хоче родина сама редагувати сторінку</b> і додавати матеріали з часом?",
        reply_markup=inline_rows("ed", YESNO, per_row=2),
    )


@private.callback_query(Pick.edit, F.data.startswith("ed:"))
async def pick_edit(c: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(edit=c.data.split(":", 1)[1])
    await c.answer()
    await state.set_state(Pick.english)
    await c.message.edit_text(
        "3 з 3. <b>Чи потрібна англійська версія</b> для рідних за кордоном?",
        reply_markup=inline_rows("en", YESNO, per_row=2),
    )


@private.callback_query(Pick.english, F.data.startswith("en:"))
async def pick_english(c: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    english = c.data.split(":", 1)[1] == "yes"
    edit = data.get("edit") == "yes"
    photos = data.get("photos")

    if english or edit or photos == "inf":
        key = "legacy"
    elif photos == "30":
        key = "story"
    else:
        key = "memory"

    await c.answer()
    await state.clear()
    text = (
        f"Вам підійде формат <b>«{FORMATS[key]}»</b>.\n\n{FORMAT_DESC[key]}\n\n"
        "Якщо хочеться унікального дизайну, власного домену чи металевої пластини з QR, "
        "є формат «Під ключ»: усе, що підкаже серце.\n\n"
        f"Детальніше про всі формати: {SITE_URL}#plans"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Залишити заявку", callback_data="go:apply")],
            [InlineKeyboardButton(text="🔁 Пройти ще раз", callback_data="go:pick")],
        ]
    )
    await c.message.edit_text(text, reply_markup=kb)


@private.callback_query(F.data == "go:pick")
async def pick_again(c: CallbackQuery, state: FSMContext) -> None:
    await c.answer()
    await pick_start(c.message, state)


# --- 3. FAQ -------------------------------------------------------------------


@private.message(F.text == BTN_FAQ)
async def faq_start(m: Message, state: FSMContext) -> None:
    await state.clear()
    await m.answer("Оберіть питання:", reply_markup=faq_kb())


@private.callback_query(F.data.startswith("faq:"))
async def faq_answer(c: CallbackQuery) -> None:
    await c.answer()
    arg = c.data.split(":", 1)[1]
    if arg == "list":
        await c.message.edit_text("Оберіть питання:", reply_markup=faq_kb())
        return
    q, a = FAQ[int(arg)]
    await c.message.edit_text(f"<b>{q}</b>\n\n{a}", reply_markup=faq_back_kb())


# --- 4. Матеріали і 5. Розмова з людиною -------------------------------------


@private.message(F.text == BTN_MATERIALS)
async def materials_start(m: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Chat.materials)
    app = store.get_app(m.from_user.id)
    if app:
        hint = f"Матеріали додамо до заявки <b>{html.escape(app[1])}</b>."
    else:
        hint = "Ви ще не залишали заявку, тож матеріали прийдуть нам окремо. Якщо зручно, спершу заповніть заявку."
    await m.answer(
        "Надсилайте сюди фото, відео, документи чи тексти. Можна кількома повідомленнями.\n\n" + hint,
        reply_markup=MENU_ONLY_KB,
    )


@private.message(F.text == BTN_HUMAN)
async def human_start(m: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Chat.human)
    await m.answer(
        "Напишіть, що хочете запитати чи розповісти. Повідомлення одразу побачить наша команда, "
        "і відповідь прийде сюди, в цей чат.\n\n"
        f"Якщо зручніше голосом: {html.escape(PHONE)}",
        reply_markup=MENU_ONLY_KB,
    )


@private.message(StateFilter(Chat.materials, Chat.human, None))
async def relay_to_group(m: Message, state: FSMContext, bot: Bot) -> None:
    """Будь-яке інше повідомлення з приватного чату летить у групу."""
    current = await state.get_state()
    app = store.get_app(m.from_user.id)

    if current is None and app is None:
        # Випадкове повідомлення без контексту: нагадуємо про меню, але все одно передаємо.
        await m.answer("Передали команді. Щоб залишити заявку або поставити питання, скористайтеся меню нижче.", reply_markup=MAIN_KB)

    if app:
        reply_to = app[0]
    else:
        kind = "💬 Повідомлення" if current == Chat.human.state else "📎 Матеріали"
        header = await send_to_group(bot, f"{kind} від {user_label(m)} (без заявки)\n<i>Reply на це повідомлення піде відправнику.</i>")
        store.save_relay(header.message_id, m.from_user.id)
        reply_to = header.message_id

    copied = await bot.copy_message(
        chat_id=GROUP_CHAT_ID,
        from_chat_id=m.chat.id,
        message_id=m.message_id,
        message_thread_id=GROUP_THREAD_ID,
        reply_to_message_id=reply_to,
    )
    store.save_relay(copied.message_id, m.from_user.id)

    if current == Chat.human.state:
        await m.answer("Передали. Відповімо тут.", reply_markup=MENU_ONLY_KB)
    elif current == Chat.materials.state:
        await m.answer("Отримали ✅", reply_markup=MENU_ONLY_KB)


@private.message(StateFilter(Apply.fmt, Apply.monument, Pick.photos, Pick.edit, Pick.english))
async def need_button(m: Message) -> None:
    await m.answer("Будь ласка, оберіть варіант кнопкою вище. Або натисніть «Скасувати».", reply_markup=CANCEL_KB)


@private.message(StateFilter(Apply.person, Apply.contact, Apply.comment))
async def need_text(m: Message) -> None:
    await m.answer("Напишіть, будь ласка, текстом. Фото й файли можна буде надіслати після заявки.", reply_markup=CANCEL_KB)


# --- Група компанії -----------------------------------------------------------


@group.message(Command("id"))
async def group_id(m: Message) -> None:
    """Підказка для налаштування: показує chat_id і thread_id."""
    thread = m.message_thread_id if m.is_topic_message else None
    await m.reply(f"chat_id: <code>{m.chat.id}</code>\nthread_id: <code>{thread}</code>")


@group.message(F.reply_to_message)
async def group_reply(m: Message, bot: Bot) -> None:
    """Reply на повідомлення бота в групі йде відповідному користувачу."""
    if m.chat.id != GROUP_CHAT_ID or m.from_user is None or m.from_user.is_bot:
        return
    user_id = store.get_relay(m.reply_to_message.message_id)
    if user_id is None:
        return
    try:
        await bot.copy_message(chat_id=user_id, from_chat_id=m.chat.id, message_id=m.message_id)
        await m.react([ReactionTypeEmoji(emoji="👍")])
    except Exception as e:  # noqa: BLE001
        log.warning("Не вдалося надіслати відповідь користувачу %s: %s", user_id, e)
        await m.reply("Не вдалося доставити: користувач, схоже, заблокував бота.")


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------


async def main() -> None:
    if not BOT_TOKEN or not GROUP_CHAT_ID:
        raise SystemExit("Задайте BOT_TOKEN і GROUP_CHAT_ID у середовищі (див. .env.example).")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(private)
    dp.include_router(group)
    await bot.delete_webhook(drop_pending_updates=False)
    log.info("Бот запущено. Група: %s, гілка: %s", GROUP_CHAT_ID, GROUP_THREAD_ID)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
