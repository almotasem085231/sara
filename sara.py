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

# Database Setup
conn = sqlite3.connect("genshin_bot.db")
cursor = conn.cursor()

# --- Database Tables Setup ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY
)
""")

# التأكد من وجود عمود description
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS server_offsets (
    server TEXT PRIMARY KEY,
    offset_hours INTEGER
)
""")

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
    if total_seconds <= 0:
        return "منتهي"
    
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    
    # تنسيق مختصر
    return f"{days}يوم و {hours}ساعة"

def parse_end_datetime(date_time_str: str, offset_hours: int = 0):
    try:
        tz = timezone(timedelta(hours=offset_hours))
        end_time = datetime.strptime(date_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        return end_time.astimezone(timezone.utc)
    except:
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

# --- Command Handlers ---

@dp.message(Command(
    'setbanner', 'setbanner_ar', 'setship_event', 'setship_event_ar', 'settower', 'settower_ar'
))
async def cmd_start_update_single_title_only(message: types.Message, state: FSMContext, command: Command):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 ليس لديك صلاحية تعديل المحتوى.")
        return
    command_text = command.command
    section = command_text.replace("set", "").replace("_ar", "")
    if section == 'ship_event': section = 'stygian'
    elif section == 'tower': section = 'spiral_abyss'
    
    await state.update_data(section=section)
    if 'banner' in command_text:
        await message.reply("أرسل البيانات: عنوان المحتوى ; اسم الحدث")
        await state.set_state(UpdateContent.waiting_for_title_and_name)
    else:
        await message.reply("أرسل البيانات: عنوان المحتوى")
        await state.set_state(UpdateContent.waiting_for_title)

@dp.message(UpdateContent.waiting_for_title, F.content_type == types.ContentType.TEXT)
async def process_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    if not title: return
    await state.update_data(title=title, name="")
    await message.reply("وقت آسيا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_title_and_name, F.content_type == types.ContentType.TEXT)
async def process_title_and_name(message: types.Message, state: FSMContext):
    text = message.text
    parts = [p.strip() for p in text.split(";", 1)]
    if len(parts) < 2: return
    await state.update_data(title=parts[0], name=parts[1])
    await message.reply("وقت آسيا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_asia_time, F.content_type == types.ContentType.TEXT)
async def process_asia_time(message: types.Message, state: FSMContext):
    await state.update_data(end_time_asia=message.text)
    await message.reply("وقت أوروبا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_europe_time)

@dp.message(UpdateContent.waiting_for_europe_time, F.content_type == types.ContentType.TEXT)
async def process_europe_time(message: types.Message, state: FSMContext):
    await state.update_data(end_time_europe=message.text)
    await message.reply("وقت أمريكا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_america_time)

@dp.message(UpdateContent.waiting_for_america_time, F.content_type == types.ContentType.TEXT)
async def process_america_time(message: types.Message, state: FSMContext):
    await state.update_data(end_time_america=message.text)
    await message.reply("أرسل الصورة.")
    await state.set_state(UpdateContent.waiting_for_photo)

@dp.message(UpdateContent.waiting_for_photo, F.content_type == types.ContentType.PHOTO)
async def process_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    section = data['section']
    
    asia_offset = get_server_offset_hours('asia')
    europe_offset = get_server_offset_hours('europe')
    america_offset = get_server_offset_hours('america')

    end_time_asia_utc = parse_end_datetime(data['end_time_asia'], offset_hours=asia_offset)
    end_time_europe_utc = parse_end_datetime(data['end_time_europe'], offset_hours=europe_offset)
    end_time_america_utc = parse_end_datetime(data['end_time_america'], offset_hours=america_offset)

    if not end_time_asia_utc or not end_time_europe_utc or not end_time_america_utc:
        await message.reply("❌ وقت خاطئ.")
        await state.clear()
        return

    end_time_asia = end_time_asia_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_time_europe = end_time_europe_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_time_america = end_time_america_utc.strftime("%Y-%m-%d %H:%M:%S")
    file_id = message.photo[-1].file_id

    cursor.execute("SELECT id FROM content WHERE section = ?", (section,))
    existing_row = cursor.fetchone()

    if existing_row:
        content_id = existing_row[0]
        cursor.execute("""
            UPDATE content SET title=?, name=?, end_time_asia=?, end_time_europe=?, end_time_america=?, image_file_id=?
            WHERE section=?
        """, (data.get('title'), data.get('name'), end_time_asia, end_time_europe, end_time_america, file_id, section))
        cursor.execute("DELETE FROM sent_alerts WHERE content_id = ?", (content_id,))
    else:
        cursor.execute("""
            INSERT INTO content (section, title, name, end_time_asia, end_time_europe, end_time_america, image_file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (section, data.get('title'), data.get('name'), end_time_asia, end_time_europe, end_time_america, file_id))
    conn.commit()
    await message.reply(f"✅ تم.")
    await state.clear()


# ==========================================
#  T H E   E V E N T   L O G I C (UPDATED)
# ==========================================

@dp.message(Command('setevents', 'setevents_ar'))
async def cmd_start_update_events(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 ليس لديك صلاحية تعديل المحتوى.")
        return
    await state.update_data(section='events')
    
    # طلب البيانات بالشكل الجديد (الاسم والوقت والنبذة)
    await message.reply(
        "أرسل البيانات بهذا الشكل:\n"
        "**اسم الحدث ; الوقت ; نبذة عن الحدث**\n\n"
        "⚠️ الوقت بتوقيت **أوروبا** (UTC+1)\n"
        "مثال:\n"
        "Whispers of the Waves ; 2025-10-25 15:30:00 ; سيتم اعطائك مهمة تصوير\n"
    )
    await state.set_state(UpdateContent.waiting_for_event_text)

@dp.message(UpdateContent.waiting_for_event_text, F.content_type == types.ContentType.TEXT)
async def process_event_text(message: types.Message, state: FSMContext):
    text = message.text
    # تقسيم النص إلى 3 أجزاء كحد أقصى
    parts = [p.strip() for p in text.split(";", 2)]

    if len(parts) < 2:
        await message.reply("❌ الصيغة خطأ. أقل شيء يجب إرسال الاسم والوقت.")
        return
    
    name = parts[0]
    time_str = parts[1]
    # إذا لم يكتب الوصف نتركه فارغاً
    description = parts[2] if len(parts) > 2 else ""
    
    europe_offset = get_server_offset_hours('europe')
    end_time_utc = parse_end_datetime(time_str, offset_hours=europe_offset)
    if not end_time_utc:
        await message.reply("❌ تنسيق الوقت غير صحيح.")
        return

    end_time_str = end_time_utc.strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO content (section, name, end_time_europe, description) 
        VALUES (?, ?, ?, ?)
    """, ('events', name, end_time_str, description))
    conn.commit()
    
    await message.reply(f"✅ تم إضافة الحدث: **{name}**")
    await state.clear()

@dp.message(Command('events', 'event'))
@dp.message(F.text.lower().in_(['الاحداث']))
async def cmd_show_events(message: types.Message):
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")

    # حذف الأحداث المنتهية
    cursor.execute("DELETE FROM content WHERE section='events' AND end_time_europe <= ?", (now_str,))
    conn.commit()

    cursor.execute("SELECT id, name, end_time_europe, description FROM content WHERE section='events'")
    events = cursor.fetchall()
    
    if not events:
        await message.reply("لا يوجد أحداث مضافة حاليًا.")
        return

    text = "قائمة الأيفنتات الحالية:\n\n"
    
    for i, event in enumerate(events):
        event_id, name, end_time_str, description = event
        end_time_utc = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        time_left = time_left_str(end_time_utc, now_utc)
        
        # التنسيق المطلوب
        if i == 0:
            # الحدث الرئيسي
            text += f"❖الأيفنت الرئيسي [{name}]\n"
        else:
            # الأحداث الفرعية
            text += f"✦ايفنت [{name}]\n"
        
        if description:
            text += f"-نبذة عن الأيفنت:\n{description}\n\n"
        
        # إضافة الخط الفاصل بجانب المهلة كما في طلبك
        text += f"المهلة المتبقية: {time_left} ༺━━━━━━━━━━━━━━━━━━━━━━༻\n"

    await message.reply(text, parse_mode="Markdown")

# ... (باقي الأكواد دون تغيير) ...

@dp.message(Command('the_banner', 'ship_event', 'tower'))
@dp.message(F.text.lower().in_(['البنر', 'السفينة', 'التاور']))
async def cmd_show_content_single(message: types.Message, command: Command = None):
    # (نفس دالة العرض القديمة للبنر والسفينة)
    section_map = {
        'the_banner': 'banner', 'البنر': 'banner',
        'ship_event': 'stygian', 'السفينة': 'stygian',
        'tower': 'spiral_abyss', 'التاور': 'spiral_abyss',
    }
    if command: section_key = section_map.get(command.command)
    else: section_key = section_map.get(message.text.lower())
    if not section_key: return
    
    cursor.execute("SELECT title, name, end_time_asia, end_time_europe, end_time_america, image_file_id FROM content WHERE section=?", (section_key,))
    row = cursor.fetchone()
    if not row:
        await message.reply(f"لا يوجد محتوى مضاف.")
        return
    
    title, name, end_time_asia, end_time_europe, end_time_america, file_id = row
    text = f"🔹 **{title if title else 'المحتوى'} :**\n\n"
    if section_key == 'banner' and name: text += f"**{name}**\n\n"
    
    times_dict = {'end_time_asia': end_time_asia, 'end_time_europe': end_time_europe, 'end_time_america': end_time_america}
    server_map = {'asia': 'اسيا', 'europe': 'اوروبا', 'america': 'امريكا'}
    now_utc = datetime.now(timezone.utc)
    
    for k, v in times_dict.items():
        if not v: continue
        srv = k.replace("end_time_", "")
        srv_ar = server_map.get(srv, srv)
        end_utc = datetime.strptime(v, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        tl = time_left_str(end_utc, now_utc)
        text += f"⏳الوقت المتبقي سيرفر {srv_ar} :\n ●← {tl}\n\n"
    
    if file_id: await message.reply_photo(photo=file_id, caption=text, parse_mode="Markdown")
    else: await message.reply(text, parse_mode="Markdown")

@dp.message(Command('delevents'))
async def cmd_delete_events(message: types.Message):
    if not is_admin(message.from_user.id): return
    cursor.execute("DELETE FROM content WHERE section='events'")
    cursor.execute("DELETE FROM sent_alerts WHERE content_id IN (SELECT id FROM content WHERE section='events')")
    conn.commit()
    await message.reply("✅ تم حذف جميع الأحداث.")

@dp.message(F.text.lower().in_(['الاوامر']))
async def cmd_custom_commands(message: types.Message):
    await message.reply(
        "اوامر غالبرينا :\n\n"
        "/the_banner البنر \n"
        "/ship_event السفينة \n"
        "/tower التاور \n"
        "/event الاحداث"
    )

@dp.message(Command('addadmin'))
async def cmd_addadmin(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    try:
        new_id = int(message.text.split()[1])
        cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_id,))
        conn.commit()
        await message.reply("✅ تم.")
    except: await message.reply("خطأ.")

@dp.message(Command('removeadmin'))
async def cmd_removeadmin(message: types.Message):
    if message.from_user.id != OWNER_ID: return
    try:
        rem_id = int(message.text.split()[1])
        cursor.execute("DELETE FROM admins WHERE user_id = ?", (rem_id,))
        conn.commit()
        await message.reply("✅ تم.")
    except: await message.reply("خطأ.")

@dp.message(Command('start', 'help'))
async def cmd_start(message: types.Message):
    await message.reply("مرحبًا بك في بوت غالبرينا!")

@dp.message(F.text.lower().in_(['مين حبيبة ماما', 'مين روح ماما', 'مين هطف القروب']))
async def handle_owner_questions(message: types.Message):
    if message.from_user.id == OWNER_ID:
        if message.text.lower() == 'مين هطف القروب': await message.reply("برهم")
        else: await message.reply("انا")

@dp.message(F.text.lower() == 'غوغو انتي تردي على احد غيري؟')
async def handle_gogo_owner_question(message: types.Message):
    if message.from_user.id == OWNER_ID: await message.reply("لا ماما انتي بس")

# --- Alert System ---
async def check_and_send_alerts():
    ONE_HOUR_THRESHOLD = 3600
    while True:
        await asyncio.sleep(60) 
        now_utc = datetime.now(timezone.utc)
        cursor.execute("SELECT id, section, title, name, end_time_asia, end_time_europe, end_time_america, description, image_file_id FROM content")
        all_content = cursor.fetchall()
        for row in all_content:
            content_id, section, title, name, end_time_asia, end_time_europe, end_time_america, description, image_file_id = row
            time_columns = {
                'asia': end_time_asia if section != 'events' else None,
                'europe': end_time_europe,
                'america': end_time_america if section != 'events' else None
            }
            for server, end_time_str in time_columns.items():
                if not end_time_str: continue
                try:
                    end_time_utc = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    time_diff = end_time_utc - now_utc
                    total_seconds = int(time_diff.total_seconds())
                    
                    if 0 < total_seconds <= ONE_HOUR_THRESHOLD:
                        if not was_alert_sent(content_id, server, '1_hour_remaining'):
                            alert_msg = format_alert_message(row, server, '1_hour_remaining')
                            try:
                                await bot.send_message(TARGET_CHAT_ID, alert_msg, parse_mode="Markdown")
                                mark_alert_sent(content_id, server, '1_hour_remaining')
                            except: pass
                    elif total_seconds <= 0:
                        if not was_alert_sent(content_id, server, 'expired'):
                            alert_msg = format_alert_message(row, server, 'expired')
                            try:
                                await bot.send_message(TARGET_CHAT_ID, alert_msg, parse_mode="Markdown")
                                mark_alert_sent(content_id, server, 'expired')
                                if section == 'events':
                                    cursor.execute("DELETE FROM content WHERE id = ?", (content_id,))
                                    cursor.execute("DELETE FROM sent_alerts WHERE content_id = ?", (content_id,))
                                    conn.commit()
                            except: pass
                except: pass

def format_alert_message(content_row: tuple, server: str, alert_type: str) -> str:
    content_id, section, title, name, end_time_asia, end_time_europe, end_time_america, description, image_file_id = content_row
    display_name = title if title and section != 'events' else (name if name else section)
    if section == 'events': display_name = name
    server_ar = {'asia': 'آسيا', 'europe': 'أوروبا', 'america': 'أمريكا'}.get(server, server)
    if alert_type == '1_hour_remaining': return f"🚨 **تنبيه!**\nباقي ساعة على انتهاء **{display_name}** ({server_ar})!"
    elif alert_type == 'expired': return f"✅ **انتهى!**\nانتهى **{display_name}** ({server_ar})."
    return ""

def was_alert_sent(content_id: int, server: str, alert_type: str) -> bool:
    cursor.execute("SELECT 1 FROM sent_alerts WHERE content_id=? AND server=? AND alert_type=?", (content_id, server, alert_type))
    return cursor.fetchone() is not None

def mark_alert_sent(content_id: int, server: str, alert_type: str):
    cursor.execute("INSERT OR IGNORE INTO sent_alerts (content_id, server, alert_type) VALUES (?, ?, ?)", (content_id, server, alert_type))
    conn.commit()

async def main():
    if TARGET_CHAT_ID: asyncio.create_task(check_and_send_alerts())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
