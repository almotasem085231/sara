import sqlite3
import asyncio
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

# --- Configuration & Setup ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID"))

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Database Connection
conn = sqlite3.connect("genshin_bot.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS content (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section TEXT,
        title TEXT,
        name TEXT,
        end_time_asia TEXT,
        end_time_europe TEXT,
        end_time_america TEXT,
        description TEXT,
        image_file_id TEXT
    )
    """)
    cursor.execute("CREATE TABLE IF NOT EXISTS server_offsets (server TEXT PRIMARY KEY, offset_hours INTEGER)")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sent_alerts (
        content_id INTEGER,
        server TEXT,
        alert_type TEXT,
        PRIMARY KEY (content_id, server, alert_type)
    )
    """)
    
    # Defaults
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
    offsets = [('asia', 8), ('europe', 1), ('america', -5)]
    cursor.executemany("INSERT OR IGNORE INTO server_offsets VALUES (?, ?)", offsets)
    conn.commit()

init_db()

# --- Utility Functions ---

def is_admin(user_id: int) -> bool:
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None

def get_server_offset_hours(server: str) -> int:
    cursor.execute("SELECT offset_hours FROM server_offsets WHERE server = ?", (server,))
    result = cursor.fetchone()
    return result[0] if result else 0

def time_left_str(end_time: datetime, now: datetime) -> str:
    diff = end_time - now
    total_seconds = int(diff.total_seconds())
    if total_seconds <= 0:
        return "انتهى."
    
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{days} يوم و {hours} ساعة و {minutes} دقيقة و {seconds} ثانية"

def parse_end_datetime(date_time_str: str, offset_hours: int = 0):
    try:
        tz = timezone(timedelta(hours=offset_hours))
        # Parse local time then convert to UTC
        end_time = datetime.strptime(date_time_str.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        return end_time.astimezone(timezone.utc)
    except Exception:
        return None

# --- FSM States ---
class UpdateContent(StatesGroup):
    waiting_for_title_and_name = State()
    waiting_for_title = State()
    waiting_for_event_text = State()
    waiting_for_asia_time = State()
    waiting_for_europe_time = State()
    waiting_for_america_time = State()
    waiting_for_photo = State()

# --- Admin Handlers (Setting Content) ---

@dp.message(Command('setbanner', 'setbanner_ar', 'setship_event', 'setship_event_ar', 'settower', 'settower_ar'))
async def cmd_start_update(message: types.Message, state: FSMContext, command: Command):
    if not is_admin(message.from_user.id):
        return await message.reply("🚫 ليس لديك صلاحية.")
    
    cmd = command.command
    section = cmd.replace("set", "").replace("_ar", "")
    section = 'stygian' if section == 'ship_event' else ('spiral_abyss' if section == 'tower' else section)
    
    await state.update_data(section=section)
    
    if 'banner' in cmd:
        await message.reply("أرسل: عنوان المحتوى ; اسم الحدث\nمثال: بنرات 5.8 ; سيتلالي")
        await state.set_state(UpdateContent.waiting_for_title_and_name)
    else:
        await message.reply("أرسل: عنوان المحتوى\nمثال: أبس 5.8")
        await state.set_state(UpdateContent.waiting_for_title)

@dp.message(Command('setevents', 'setevents_ar'))
async def cmd_start_events(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(section='events')
    await message.reply("أرسل: اسم الحدث ; YYYY-MM-DD HH:MM:SS\n(بتوقيت أوروبا UTC+1)")
    await state.set_state(UpdateContent.waiting_for_event_text)

@dp.message(UpdateContent.waiting_for_title)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip(), name="")
    await message.reply("وقت آسيا (YYYY-MM-DD HH:MM:SS):")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_title_and_name)
async def process_title_name(message: types.Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split(";", 1)]
    if len(parts) < 2: return await message.reply("استخدم الفاصلة المنقوطة ;")
    await state.update_data(title=parts[0], name=parts[1])
    await message.reply("وقت آسيا (YYYY-MM-DD HH:MM:SS):")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_event_text)
async def process_event_text(message: types.Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split(";", 1)]
    if len(parts) < 2: return await message.reply("استخدم الصيغة: اسم ; وقت")
    
    offset = get_server_offset_hours('europe')
    utc_time = parse_end_datetime(parts[1], offset)
    if not utc_time: return await message.reply("خطأ في تنسيق الوقت.")
    
    cursor.execute("INSERT INTO content (section, name, end_time_europe) VALUES (?, ?, ?)", 
                   ('events', parts[0], utc_time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    await message.reply("✅ تم إضافة الحدث.")
    await state.clear()

@dp.message(UpdateContent.waiting_for_asia_time)
async def p_asia(m: types.Message, s: FSMContext):
    await s.update_data(end_time_asia=m.text)
    await m.reply("وقت أوروبا:")
    await s.set_state(UpdateContent.waiting_for_europe_time)

@dp.message(UpdateContent.waiting_for_europe_time)
async def p_euro(m: types.Message, s: FSMContext):
    await s.update_data(end_time_europe=m.text)
    await m.reply("وقت أمريكا:")
    await s.set_state(UpdateContent.waiting_for_america_time)

@dp.message(UpdateContent.waiting_for_america_time)
async def p_amer(m: types.Message, s: FSMContext):
    await s.update_data(end_time_america=m.text)
    await m.reply("أرسل الصورة:")
    await s.set_state(UpdateContent.waiting_for_photo)

@dp.message(UpdateContent.waiting_for_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    # Parse all times to UTC
    t_asia = parse_end_datetime(data['end_time_asia'], get_server_offset_hours('asia'))
    t_euro = parse_end_datetime(data['end_time_europe'], get_server_offset_hours('europe'))
    t_amer = parse_end_datetime(data['end_time_america'], get_server_offset_hours('america'))

    if not all([t_asia, t_euro, t_amer]):
        return await message.reply("خطأ في التواريخ. أعد المحاولة.")

    file_id = message.photo[-1].file_id
    section = data['section']
    
    # Upsert logic
    cursor.execute("SELECT id FROM content WHERE section = ?", (section,))
    row = cursor.fetchone()
    
    vals = (data.get('title'), data.get('name'), t_asia.strftime("%Y-%m-%d %H:%M:%S"), 
            t_euro.strftime("%Y-%m-%d %H:%M:%S"), t_amer.strftime("%Y-%m-%d %H:%M:%S"), file_id, section)

    if row:
        cursor.execute("""UPDATE content SET title=?, name=?, end_time_asia=?, end_time_europe=?, 
                          end_time_america=?, image_file_id=? WHERE section=?""", vals)
        cursor.execute("DELETE FROM sent_alerts WHERE content_id = ?", (row[0],))
    else:
        cursor.execute("""INSERT INTO content (title, name, end_time_asia, end_time_europe, 
                          end_time_america, image_file_id, section) VALUES (?,?,?,?,?,?,?)""", vals)

    conn.commit()
    await message.reply(f"✅ تم تحديث {section}.")
    await state.clear()

# --- Public Handlers (Displaying Content) ---

@dp.message(Command('the_banner', 'ship_event', 'tower'))
@dp.message(F.text.in_(['البنر', 'السفينة', 'التاور']))
async def show_content(message: types.Message, command: Command = None):
    mapping = {'the_banner': 'banner', 'البنر': 'banner', 'ship_event': 'stygian', 
               'السفينة': 'stygian', 'tower': 'spiral_abyss', 'التاور': 'spiral_abyss'}
    key = mapping.get(command.command if command else message.text)
    
    cursor.execute("SELECT title, name, end_time_asia, end_time_europe, end_time_america, image_file_id FROM content WHERE section=?", (key,))
    row = cursor.fetchone()
    if not row: return await message.reply("لا يوجد محتوى حالياً.")
    
    title, name, t_asia, t_euro, t_amer, file_id = row
    now = datetime.now(timezone.utc)
    
    text = f"🔹 **{title or 'المعلومات'}**\n"
    if name: text += f"**{name}**\n\n"
    
    for s_name, t_str in [('آسيا', t_asia), ('أوروبا', t_euro), ('أمريكا', t_amer)]:
        if t_str:
            dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            text += f"⏳ سيرفر {s_name}:\n ●← {time_left_str(dt, now)}\n\n"

    if file_id: await message.reply_photo(file_id, caption=text, parse_mode="Markdown")
    else: await message.reply(text, parse_mode="Markdown")

@dp.message(Command('events', 'event'))
@dp.message(F.text == 'الاحداث')
async def show_events(message: types.Message):
    now = datetime.now(timezone.utc)
    cursor.execute("SELECT id, name, end_time_europe FROM content WHERE section='events'")
    events = cursor.fetchall()
    
    if not events: return await message.reply("لا يوجد أحداث حالياً.")
    
    text = "📌 **الأحداث الحالية:**\n\n"
    for i, (_, name, t_str) in enumerate(events):
        dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if dt > now:
            text += f"**{i+1}. {name}**\n⏳ {time_left_str(dt, now)}\n---\n"
            
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command('delevents'))
@dp.message(F.text == 'حذف_الاحداث')
async def del_ev(message: types.Message):
    if not is_admin(message.from_user.id): return
    cursor.execute("DELETE FROM content WHERE section='events'")
    conn.commit()
    await message.reply("✅ تم الحذف.")

@dp.message(F.text == 'الاوامر')
async def cmd_list(message: types.Message):
    await message.reply("الأوامر: البنر، السفينة، التاور، الاحداث")

# --- Alert System ---

async def alert_loop():
    while True:
        await asyncio.sleep(60)
        now = datetime.now(timezone.utc)
        cursor.execute("SELECT * FROM content")
        for row in cursor.fetchall():
            c_id, section, title, name, t_asia, t_euro, t_amer, _, _ = row
            times = {'asia': t_asia, 'europe': t_euro, 'america': t_amer}
            
            for srv, t_str in times.items():
                if not t_str: continue
                dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                diff = (dt - now).total_seconds()
                
                # 1 Hour Alert
                if 0 < diff <= 3600:
                    cursor.execute("SELECT 1 FROM sent_alerts WHERE content_id=? AND server=? AND alert_type='1h'", (c_id, srv))
                    if not cursor.fetchone():
                        msg = f"🚨 ساعة واحدة تنتهي على {name or title} ({srv})"
                        await bot.send_message(TARGET_CHAT_ID, msg)
                        cursor.execute("INSERT INTO sent_alerts VALUES (?, ?, '1h')", (c_id, srv))
                        conn.commit()
                
                # Expired Alert
                elif diff <= 0:
                    cursor.execute("SELECT 1 FROM sent_alerts WHERE content_id=? AND server=? AND alert_type='exp'", (c_id, srv))
                    if not cursor.fetchone():
                        msg = f"✅ انتهى {name or title} في سيرفر {srv}"
                        await bot.send_message(TARGET_CHAT_ID, msg)
                        cursor.execute("INSERT INTO sent_alerts VALUES (?, ?, 'exp')", (c_id, srv))
                        if section == 'events': cursor.execute("DELETE FROM content WHERE id=?", (c_id,))
                        conn.commit()

# --- Entry Point ---

async def main():
    asyncio.create_task(alert_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
