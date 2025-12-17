import sqlite3
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
import asyncio
from dotenv import load_dotenv
import os

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID"))

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- Database Setup ---
conn = sqlite3.connect("genshin_bot.db")
cursor = conn.cursor()

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
conn.commit()

# Populate default admins and server offsets
cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
cursor.execute("INSERT OR IGNORE INTO server_offsets (server, offset_hours) VALUES (?, ?)", ('asia', 8))
cursor.execute("INSERT OR IGNORE INTO server_offsets (server, offset_hours) VALUES (?, ?)", ('europe', 1))
cursor.execute("INSERT OR IGNORE INTO server_offsets (server, offset_hours) VALUES (?, ?)", ('america', -5))
conn.commit()

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
    if total_seconds <= 0: return "انتهى."
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{days} يوم و {hours} ساعة و {minutes} دقيقة"

def parse_end_datetime(date_time_str: str, offset_hours: int = 0):
    try:
        tz = timezone(timedelta(hours=offset_hours))
        end_time = datetime.strptime(date_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        return end_time.astimezone(timezone.utc)
    except: return None

# --- FSM States ---
class UpdateContent(StatesGroup):
    waiting_for_title_and_name = State()
    waiting_for_title = State()
    waiting_for_event_details = State() # Updated for Name;Description;Time
    waiting_for_asia_time = State()
    waiting_for_europe_time = State()
    waiting_for_america_time = State()
    waiting_for_photo = State()

# --- Admin Handlers (Banner, Ship, Tower) ---
@dp.message(Command('setbanner', 'setbanner_ar', 'setship_event', 'setship_event_ar', 'settower', 'settower_ar'))
async def cmd_start_update_single(message: types.Message, state: FSMContext, command: Command):
    if not is_admin(message.from_user.id): return
    section = command.command.replace("set", "").replace("_ar", "")
    if section == 'ship_event': section = 'stygian'
    elif section == 'tower': section = 'spiral_abyss'
    
    await state.update_data(section=section)
    if 'banner' in command.command:
        await message.reply("أرسل البيانات: عنوان المحتوى ; اسم الحدث")
        await state.set_state(UpdateContent.waiting_for_title_and_name)
    else:
        await message.reply("أرسل البيانات: عنوان المحتوى")
        await state.set_state(UpdateContent.waiting_for_title)

# --- Admin Handlers (Events - Europe Time + Description) ---
@dp.message(Command('setevents', 'setevents_ar'))
async def cmd_start_update_events(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(section='events')
    await message.reply(
        "أرسل بيانات الحدث بهذا الشكل:\n"
        "اسم الحدث ; نبذة عن الحدث ; YYYY-MM-DD HH:MM:SS\n\n"
        "ملاحظة: الوقت سيتم اعتباره بتوقيت **سيرفر أوروبا (UTC+1)**."
    )
    await state.set_state(UpdateContent.waiting_for_event_details)

@dp.message(UpdateContent.waiting_for_event_details, F.content_type == types.ContentType.TEXT)
async def process_event_details(message: types.Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split(";", 2)]
    if len(parts) < 3:
        await message.reply("❌ خطأ! استخدم الصيغة: الاسم ; النبذة ; الوقت")
        return
    
    eu_offset = get_server_offset_hours('europe')
    end_time_utc = parse_end_datetime(parts[2], offset_hours=eu_offset)
    if not end_time_utc:
        await message.reply("❌ التاريخ غير صحيح. استخدم الصيغة: YYYY-MM-DD HH:MM:SS")
        return

    cursor.execute("""
        INSERT INTO content (section, name, description, end_time_europe) 
        VALUES (?, ?, ?, ?)
    """, ('events', parts[0], parts[1], end_time_utc.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    await message.reply(f"✅ تم إضافة الحدث **{parts[0]}** بنجاح.")
    await state.clear()

# --- Content View (Events - Custom Styled) ---
@dp.message(Command('events', 'event'))
@dp.message(F.text.lower().in_(['الاحداث', 'الأحداث']))
async def cmd_show_events(message: types.Message):
    now_utc = datetime.now(timezone.utc)
    # Clean expired
    cursor.execute("DELETE FROM content WHERE section='events' AND end_time_europe <= ?", (now_utc.strftime("%Y-%m-%d %H:%M:%S"),))
    conn.commit()

    cursor.execute("SELECT name, description, end_time_europe FROM content WHERE section='events'")
    events = cursor.fetchall()
    if not events:
        await message.reply("لا يوجد أحداث مضافة حاليًا.")
        return

    text = "قائمة الأيفنتات الحالية:\n\n"
    for event in events:
        name, desc, et_str = event
        et_utc = datetime.strptime(et_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        text += f"✦ايفنت [{name}]\n"
        text += f"-نبذة عن الأيفنت:\n{desc}\n\n"
        text += f"المهلة المتبقية: {time_left_str(et_utc, now_utc)}\n"
        text += "༺━━━━━━━━━━━━━━━━━━━━━━༻\n"

    await message.reply(text, parse_mode="Markdown")

# --- Common Process Handlers (Asia/Europe/America times) ---
@dp.message(UpdateContent.waiting_for_title, F.content_type == types.ContentType.TEXT)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip(), name="")
    await message.reply("أدخل وقت آسيا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_title_and_name, F.content_type == types.ContentType.TEXT)
async def process_title_and_name(message: types.Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split(";", 1)]
    if len(parts) < 2:
        await message.reply("❌ الصيغة: عنوان ; اسم")
        return
    await state.update_data(title=parts[0], name=parts[1])
    await message.reply("أدخل وقت آسيا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_asia_time, F.content_type == types.ContentType.TEXT)
async def process_asia_time(message: types.Message, state: FSMContext):
    await state.update_data(end_time_asia=message.text)
    await message.reply("أدخل وقت أوروبا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_europe_time)

@dp.message(UpdateContent.waiting_for_europe_time, F.content_type == types.ContentType.TEXT)
async def process_europe_time(message: types.Message, state: FSMContext):
    await state.update_data(end_time_europe=message.text)
    await message.reply("أدخل وقت أمريكا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_america_time)

@dp.message(UpdateContent.waiting_for_america_time, F.content_type == types.ContentType.TEXT)
async def process_america_time(message: types.Message, state: FSMContext):
    await state.update_data(end_time_america=message.text)
    await message.reply("الآن أرسل صورة.")
    await state.set_state(UpdateContent.waiting_for_photo)

@dp.message(UpdateContent.waiting_for_photo, F.content_type == types.ContentType.PHOTO)
async def process_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    a_off, e_off, am_off = get_server_offset_hours('asia'), get_server_offset_hours('europe'), get_server_offset_hours('america')
    
    t_asia = parse_end_datetime(data['end_time_asia'], a_off)
    t_euro = parse_end_datetime(data['end_time_europe'], e_off)
    t_amer = parse_end_datetime(data['end_time_america'], am_off)

    if not all([t_asia, t_euro, t_amer]):
        await message.reply("❌ خطأ في تنسيق الوقت.")
        await state.clear(); return

    file_id = message.photo[-1].file_id
    cursor.execute("SELECT id FROM content WHERE section = ?", (data['section'],))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE content SET title=?, name=?, end_time_asia=?, end_time_europe=?, end_time_america=?, image_file_id=?
            WHERE section=?
        """, (data.get('title',''), data.get('name',''), t_asia.strftime("%Y-%m-%d %H:%M:%S"), 
              t_euro.strftime("%Y-%m-%d %H:%M:%S"), t_amer.strftime("%Y-%m-%d %H:%M:%S"), file_id, data['section']))
        cursor.execute("DELETE FROM sent_alerts WHERE content_id = ?", (existing[0],))
    else:
        cursor.execute("""
            INSERT INTO content (section, title, name, end_time_asia, end_time_europe, end_time_america, image_file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data['section'], data.get('title',''), data.get('name',''), t_asia.strftime("%Y-%m-%d %H:%M:%S"), 
              t_euro.strftime("%Y-%m-%d %H:%M:%S"), t_amer.strftime("%Y-%m-%d %H:%M:%S"), file_id))
    
    conn.commit()
    await message.reply(f"✅ تم تحديث {data['section']} بنجاح.")
    await state.clear()

# --- Content View (Banner/Tower/Ship) ---
@dp.message(Command('the_banner', 'ship_event', 'tower'))
@dp.message(F.text.lower().in_(['البنر', 'السفينة', 'التاور']))
async def cmd_show_single(message: types.Message, command: Command = None):
    m = {'the_banner':'banner', 'البنر':'banner', 'ship_event':'stygian', 'السفينة':'stygian', 'tower':'spiral_abyss', 'التاور':'spiral_abyss'}
    key = m.get(command.command if command else message.text.lower())
    if not key: return
    
    cursor.execute("SELECT title, name, end_time_asia, end_time_europe, end_time_america, image_file_id FROM content WHERE section=?", (key,))
    row = cursor.fetchone()
    if not row:
        await message.reply("لا يوجد محتوى.")
        return

    title, name, et_a, et_e, et_am, file_id = row
    now_utc = datetime.now(timezone.utc)
    text = f"🔹 **{title if title else key} :**\n\n"
    if key == 'banner' and name: text += f"**{name}**\n\n"

    for s_ar, et_str in [('آسيا', et_a), ('أوروبا', et_e), ('أمريكا', et_am)]:
        if et_str:
            et_utc = datetime.strptime(et_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            text += f"⏳سيرفر {s_ar}:\n ●← {time_left_str(et_utc, now_utc)}\n\n"

    if file_id: await message.reply_photo(photo=file_id, caption=text, parse_mode="Markdown")
    else: await message.reply(text, parse_mode="Markdown")

# --- Other Admin Commands ---
@dp.message(Command('delevents'))
@dp.message(F.text.lower().in_(['حذف_الاحداث']))
async def cmd_delete_events(message: types.Message):
    if not is_admin(message.from_user.id): return
    cursor.execute("DELETE FROM content WHERE section='events'")
    conn.commit()
    await message.reply("✅ تم حذف جميع الأحداث.")

@dp.message(F.text.lower().in_(['الاوامر']))
async def cmd_custom_commands(message: types.Message):
    await message.reply("اوامر البوت:\n/the_banner\n/ship_event\n/tower\n/event")

# --- Alert System Logic ---
async def check_and_send_alerts():
    ONE_HOUR = 3600
    while True:
        await asyncio.sleep(60)
        now_utc = datetime.now(timezone.utc)
        cursor.execute("SELECT id, section, name, title, end_time_asia, end_time_europe, end_time_america FROM content")
        rows = cursor.fetchall()

        for r in rows:
            cid, sec, name, title, et_a, et_e, et_am = r
            # Logic: Events only Europe, others all 3
            srv_times = {'europe': et_e} if sec == 'events' else {'asia': et_a, 'europe': et_e, 'america': et_am}
            
            for srv, et_str in srv_times.items():
                if not et_str: continue
                et_utc = datetime.strptime(et_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                diff = (et_utc - now_utc).total_seconds()
                disp_name = name if sec == 'events' else (title if title else sec)
                srv_ar = {'asia':'آسيا', 'europe':'أوروبا', 'america':'أمريكا'}.get(srv)

                # 1 Hour Alert
                if 0 < diff <= ONE_HOUR:
                    cursor.execute("SELECT 1 FROM sent_alerts WHERE content_id=? AND server=? AND alert_type='1h'", (cid, srv))
                    if not cursor.fetchone():
                        await bot.send_message(TARGET_CHAT_ID, f"🚨 **تنبيه!**\nباقي ساعة واحدة على انتهاء **{disp_name}** في سيرفر **{srv_ar}**!", parse_mode="Markdown")
                        cursor.execute("INSERT INTO sent_alerts (content_id, server, alert_type) VALUES (?, ?, '1h')", (cid, srv))
                        conn.commit()
                
                # Expired Alert
                elif diff <= 0:
                    cursor.execute("SELECT 1 FROM sent_alerts WHERE content_id=? AND server=? AND alert_type='exp'", (cid, srv))
                    if not cursor.fetchone():
                        await bot.send_message(TARGET_CHAT_ID, f"✅ **انتهى!**\nلقد انتهى **{disp_name}** في سيرفر **{srv_ar}**.", parse_mode="Markdown")
                        cursor.execute("INSERT INTO sent_alerts (content_id, server, alert_type) VALUES (?, ?, 'exp')", (cid, srv))
                        if sec == 'events': cursor.execute("DELETE FROM content WHERE id=?", (cid,))
                        conn.commit()

# --- Main Run ---
async def main():
    print("بوت غالبرينا شغال...")
    if TARGET_CHAT_ID != 0: asyncio.create_task(check_and_send_alerts())
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not TARGET_CHAT_ID or TARGET_CHAT_ID == 0:
        print("ERROR: TARGET_CHAT_ID not set!")
    else:
        asyncio.run(main())
