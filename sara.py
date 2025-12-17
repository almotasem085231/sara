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
# ADD YOUR TARGET CHAT/GROUP ID HERE
# تأكد من وضع ID المجموعة/القناة هنا
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

# Create the 'content' table with separate time columns
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

# NEW: Table to track sent alerts
cursor.execute("""
CREATE TABLE IF NOT EXISTS sent_alerts (
    content_id INTEGER,
    server TEXT,
    alert_type TEXT, -- '1_hour_remaining' or 'expired'
    PRIMARY KEY (content_id, server, alert_type)
)
""")

conn.commit()

# Populate default admins and server offsets
cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
cursor.execute("INSERT OR IGNORE INTO server_offsets (server, offset_hours) VALUES (?, ?)", ('asia', 8)) # UTC+8
cursor.execute("INSERT OR IGNORE INTO server_offsets (server, offset_hours) VALUES (?, ?)", ('europe', 1)) # UTC+1
cursor.execute("INSERT OR IGNORE INTO server_offsets (server, offset_hours) VALUES (?, ?)", ('america', -5)) # UTC-5
conn.commit()

# --- Utility Functions ---

def is_admin(user_id: int) -> bool:
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None

def get_server_offset_hours(server: str) -> int:
    """Retrieves the UTC offset for a given server."""
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
        # Create a timezone with the specified offset
        tz = timezone(timedelta(hours=offset_hours))
        # Parse the string and attach the timezone
        end_time = datetime.strptime(date_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        # Convert it to UTC for consistent comparison
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

# Unified handler for setting commands
@dp.message(Command(
    'setbanner',
    'setbanner_ar',
    'setship_event',
    'setship_event_ar',
    'settower',
    'settower_ar'
))
async def cmd_start_update_single_title_only(message: types.Message, state: FSMContext, command: Command):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 ليس لديك صلاحية تعديل المحتوى.")
        return
    
    command_text = command.command
    section = command_text.replace("set", "").replace("_ar", "")
    
    # Map new commands to their old sections
    if section == 'ship_event':
        section = 'stygian'
    elif section == 'tower':
        section = 'spiral_abyss'
    
    await state.update_data(section=section)
    
    if 'banner' in command_text:
        await message.reply(
            "أرسل البيانات بهذا الشكل:\n"
            "عنوان المحتوى ; اسم الحدث\n"
            "مثال:\n"
            "بنرات 5.8 النصف الاول ; سيتلالي + اينيفيا\n"
        )
        await state.set_state(UpdateContent.waiting_for_title_and_name)
    else:
        await message.reply(
            "أرسل البيانات بهذا الشكل:\n"
            "عنوان المحتوى\n"
            "مثال:\n"
            "أبس 5.8\n"
        )
        await state.set_state(UpdateContent.waiting_for_title)

@dp.message(Command('setevents', 'setevents_ar'))
async def cmd_start_update_events(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 ليس لديك صلاحية تعديل المحتوى.")
        return
    await state.update_data(section='events')
    await message.reply(
        "أرسل البيانات بهذا الشكل لإضافة حدث جديد:\n"
        "اسم الحدث ; YYYY-MM-DD HH:MM:SS\n"
        "ملاحظة: الوقت الذي ترسله هو **بتوقيت سيرفر أوروبا (UTC+1)**.\n"
        "مثال:\n"
        "حدث جديد ; 2025-10-25 15:30:00\n"
    )
    await state.set_state(UpdateContent.waiting_for_event_text)

@dp.message(UpdateContent.waiting_for_title, F.content_type == types.ContentType.TEXT)
async def process_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    if not title:
        await message.reply("❌ العنوان لا يمكن أن يكون فارغًا. يرجى إرسال: عنوان المحتوى")
        return
    
    await state.update_data(title=title, name="")
    await message.reply("يرجى إدخال وقت انتهاء سيرفر آسيا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_title_and_name, F.content_type == types.ContentType.TEXT)
async def process_title_and_name(message: types.Message, state: FSMContext):
    text = message.text
    parts = [p.strip() for p in text.split(";", 1)]
    
    if len(parts) < 2:
        await message.reply("❌ الخطأ في الصيغة.\nالصيغة:\nعنوان المحتوى ; اسم الحدث")
        return
    
    title = parts[0]
    name = parts[1]
    
    await state.update_data(title=title, name=name)
    await message.reply("يرجى إدخال وقت انتهاء سيرفر آسيا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_event_text, F.content_type == types.ContentType.TEXT)
async def process_event_text(message: types.Message, state: FSMContext):
    text = message.text
    parts = [p.strip() for p in text.split(";", 1)]

    if len(parts) < 2:
        await message.reply("❌ الخطأ في الصيغة.\nالصيغة:\nاسم الحدث ; YYYY-MM-DD HH:MM:SS")
        return
    
    name = parts[0]
    # UPDATED: Use parse_end_datetime with EUROPE's offset
    europe_offset = get_server_offset_hours('europe')
    end_time_utc = parse_end_datetime(parts[1], offset_hours=europe_offset)
    if not end_time_utc:
        await message.reply("❌ تنسيق التاريخ والوقت غير صحيح. استخدم الصيغة `YYYY-MM-DD HH:MM:SS`.")
        return

    end_time_str = end_time_utc.strftime("%Y-%m-%d %H:%M:%S")
    
    # UPDATED: Insert into end_time_europe instead of end_time_asia
    cursor.execute("""
        INSERT INTO content (section, name, end_time_europe) 
        VALUES (?, ?, ?)
    """, ('events', name, end_time_str))
    conn.commit()
    await message.reply(f"✅ تم إضافة حدث جديد بنجاح. **(الوقت المخزن هو UTC بناءً على وقت أوروبا المدخل)**")
    await state.clear()

@dp.message(UpdateContent.waiting_for_asia_time, F.content_type == types.ContentType.TEXT)
async def process_asia_time(message: types.Message, state: FSMContext):
    end_time_str = message.text
    # We will parse this time later in process_photo
    await state.update_data(end_time_asia=end_time_str)
    await message.reply("يرجى إدخال وقت انتهاء سيرفر أوروبا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_europe_time)

@dp.message(UpdateContent.waiting_for_europe_time, F.content_type == types.ContentType.TEXT)
async def process_europe_time(message: types.Message, state: FSMContext):
    end_time_str = message.text
    await state.update_data(end_time_europe=end_time_str)
    await message.reply("يرجى إدخال وقت انتهاء سيرفر أمريكا: YYYY-MM-DD HH:MM:SS")
    await state.set_state(UpdateContent.waiting_for_america_time)

@dp.message(UpdateContent.waiting_for_america_time, F.content_type == types.ContentType.TEXT)
async def process_america_time(message: types.Message, state: FSMContext):
    end_time_str = message.text
    await state.update_data(end_time_america=end_time_str)
    await message.reply("الآن أرسل صورة مرفقة للحدث.")
    await state.set_state(UpdateContent.waiting_for_photo)

@dp.message(UpdateContent.waiting_for_photo, F.content_type == types.ContentType.PHOTO)
async def process_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    section = data['section']
    title = data.get('title', '')
    name = data.get('name', '')
    
    # Get server offsets from the database
    asia_offset = get_server_offset_hours('asia')
    europe_offset = get_server_offset_hours('europe')
    america_offset = get_server_offset_hours('america')

    # Parse and convert to UTC based on the offsets
    end_time_asia_utc = parse_end_datetime(data['end_time_asia'], offset_hours=asia_offset)
    end_time_europe_utc = parse_end_datetime(data['end_time_europe'], offset_hours=europe_offset)
    end_time_america_utc = parse_end_datetime(data['end_time_america'], offset_hours=america_offset)

    if not end_time_asia_utc or not end_time_europe_utc or not end_time_america_utc:
        await message.reply("❌ تنسيق التاريخ والوقت غير صحيح في أحد السيرفرات. يرجى البدء من جديد.")
        await state.clear()
        return

    # Convert back to string for database storage (in UTC)
    end_time_asia = end_time_asia_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_time_europe = end_time_europe_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_time_america = end_time_america_utc.strftime("%Y-%m-%d %H:%M:%S")
    
    photo = message.photo[-1]
    file_id = photo.file_id

    cursor.execute("SELECT id FROM content WHERE section = ?", (section,))
    existing_row = cursor.fetchone()

    if existing_row:
        content_id = existing_row[0]
        cursor.execute("""
            UPDATE content SET 
                title=?,
                name=?, 
                end_time_asia=?, 
                end_time_europe=?, 
                end_time_america=?, 
                image_file_id=?
            WHERE section=?
        """, (title, name, end_time_asia, end_time_europe, end_time_america, file_id, section))
        # Clear old alerts for updated content
        cursor.execute("DELETE FROM sent_alerts WHERE content_id = ?", (content_id,))
    else:
        cursor.execute("""
            INSERT INTO content (section, title, name, end_time_asia, end_time_europe, end_time_america, image_file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (section, title, name, end_time_asia, end_time_europe, end_time_america, file_id))

    conn.commit()

    await message.reply(f"✅ تم تحديث محتوى {section} بنجاح.")
    await state.clear()

@dp.message(UpdateContent.waiting_for_photo, F.content_type != types.ContentType.PHOTO)
async def process_not_photo(message: types.Message):
    await message.reply("❌ الرجاء إرسال صورة فقط.")

# Unified handler for showing content
@dp.message(Command('the_banner', 'ship_event', 'tower'))
@dp.message(F.text.lower().in_(['البنر', 'السفينة', 'التاور']))
async def cmd_show_content_single(message: types.Message, command: Command = None):
    section_map = {
        'the_banner': 'banner', 'البنر': 'banner',
        'ship_event': 'stygian', 'السفينة': 'stygian',
        'tower': 'spiral_abyss', 'التاور': 'spiral_abyss',
    }

    if command:
        section_key = section_map.get(command.command)
    else:
        section_key = section_map.get(message.text.lower())
    
    if not section_key:
        return
    
    cursor.execute("SELECT title, name, end_time_asia, end_time_europe, end_time_america, image_file_id FROM content WHERE section=?", (section_key,))
    row = cursor.fetchone()
    
    if not row:
        arabic_section_titles_new = {
            'stygian': 'السفينة',
            'spiral_abyss': 'التاور',
            'banner': 'البنر'
        }
        arabic_section_title = arabic_section_titles_new.get(section_key, section_key)
        await message.reply(f"لا يوجد محتوى مضاف لقسم {arabic_section_title}.")
        return
    
    title, name, end_time_asia, end_time_europe, end_time_america, file_id = row
    
    if title:
        text = f"🔹 **{title} :**\n\n"
    else:
        arabic_section_titles_new = {
            'stygian': 'السفينة',
            'spiral_abyss': 'التاور',
            'banner': 'البنر'
        }
        arabic_section_title = arabic_section_titles_new.get(section_key, section_key)
        text = f"🔹 **{arabic_section_title} :**\n\n"
    
    if section_key == 'banner' and name:
        text += f"**{name}**\n\n"
    
    times_dict = {
        'end_time_asia': end_time_asia,
        'end_time_europe': end_time_europe,
        'end_time_america': end_time_america
    }
    
    server_name_map = {
        'asia': 'اسيا',
        'europe': 'اوروبا',
        'america': 'امريكا'
    }
    
    now_utc = datetime.now(timezone.utc)
    
    for server_key, end_time_str in times_dict.items():
        if not end_time_str:
            continue
        
        # 🟢 التعديل الصحيح: استخلاص اسم السيرفر النقي
        server_name_only = server_key.replace("end_time_", "")
        arabic_server_name = server_name_map.get(server_name_only, server_name_only)
        
        # The stored time is now UTC, so we can replace the timezone directly
        end_time_utc = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        time_left = time_left_str(end_time_utc, now_utc)

        text += f"⏳الوقت المتبقي سيرفر {arabic_server_name} :\n"
        text += f" ●← {time_left}\n\n"
    
    if file_id:
        await message.reply_photo(photo=file_id, caption=text, parse_mode="Markdown")
    else:
        await message.reply(text, parse_mode="Markdown")

# Unified handler for events (UPDATED to use Europe time)
@dp.message(Command('events', 'event'))
@dp.message(F.text.lower().in_(['الاحداث']))
async def cmd_show_events(message: types.Message):
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")

    # UPDATED: Clean up expired events based on end_time_europe
    cursor.execute("DELETE FROM content WHERE section='events' AND end_time_europe <= ?", (now_str,))
    conn.commit()

    # UPDATED: Select end_time_europe
    cursor.execute("SELECT id, name, end_time_europe FROM content WHERE section='events'")
    events = cursor.fetchall()
    
    if not events:
        await message.reply("لا يوجد أحداث مضافة حاليًا.")
        return

    text = "📌 **قائمة الأحداث الحالية:**\n\n"
    for i, event in enumerate(events):
        event_id, name, end_time_str = event
        end_time_utc = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        time_left = time_left_str(end_time_utc, now_utc)
        
        text += f"**{i+1}. {name}**\n\n"
        # UPDATED: Label to Europe
        text += f"⏳الوقت المتبقي (وقت أوروبا المعتمد للأحداث)\n{time_left}\n"
        text += "---\n"

    await message.reply(text, parse_mode="Markdown")

# Unified handler for deleting events
@dp.message(Command('delevents'))
@dp.message(F.text.lower().in_(['حذف_الاحداث']))
async def cmd_delete_events(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("🚫 ليس لديك صلاحية حذف الأحداث.")
        return

    cursor.execute("DELETE FROM content WHERE section='events'")
    # NEW: Clear alerts for deleted events
    cursor.execute("DELETE FROM sent_alerts WHERE content_id IN (SELECT id FROM content WHERE section='events')")
    conn.commit()
    await message.reply("✅ تم حذف جميع الأحداث بنجاح.")

# New handler for the custom 'الاوامر' command
@dp.message(F.text.lower().in_(['الاوامر']))
async def cmd_custom_commands(message: types.Message):
    await message.reply(
        "اوامر غالبرينا :\n\n"
        "/the_banner البنر او\n"
        "/ship_event السفينة او\n"
        "/tower التاور او\n"
        "/event الاحداث او"
    )

# Unified handler for adding admin
@dp.message(Command('addadmin'))
@dp.message(F.text.lower().startswith('اضافة_مشرف'))
async def cmd_addadmin(message: types.Message, command: Command=None):
    if message.from_user.id != OWNER_ID:
        await message.reply("🚫 فقط المالك يمكنه إضافة مشرفين.")
        return
    
    if command and command.args:
        args = command.args.split()
    else:
        args = message.text.split()[1:]
        
    if not args:
        await message.reply("يرجى كتابة معرف المستخدم لإضافته كمشرف.\nمثال:\n/addadmin 123456789")
        return
    try:
        new_id = int(args[0])
        cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_id,))
        conn.commit()
        await message.reply(f"✅ تم إضافة المستخدم {new_id} كمشرف.")
    except (ValueError, IndexError):
        await message.reply("❌ حدث خطأ أثناء الإضافة. يرجى التأكد من أن المعرف هو رقم صحيح.")

# Unified handler for removing admin
@dp.message(Command('removeadmin'))
@dp.message(F.text.lower().startswith('ازالة_مشرف'))
async def cmd_removeadmin(message: types.Message, command: Command=None):
    if message.from_user.id != OWNER_ID:
        await message.reply("🚫 فقط المالك يمكنه إزالة المشرفين.")
        return
        
    if command and command.args:
        args = command.args.split()
    else:
        args = message.text.split()[1:]
        
    if not args:
        await message.reply("يرجى كتابة معرف المستخدم لإزالته من المشرفين.\nمثال:\n/removeadmin 123456789")
        return
    try:
        rem_id = int(args[0])
        if rem_id == OWNER_ID:
            await message.reply("🚫 لا يمكن إزالة المالك نفسه.")
            return
        cursor.execute("DELETE FROM admins WHERE user_id = ?", (rem_id,))
        conn.commit()
        await message.reply(f"✅ تم إزالة المستخدم {rem_id} من المشرفين.")
    except (ValueError, IndexError):
        await message.reply("❌ حدث خطأ أثناء الحذف. يرجى التأكد من أن المعرف هو رقم صحيح.")

# Unified handler for start/help message
@dp.message(Command('start', 'help'))
@dp.message(F.text.lower().in_(['بدء']))
async def cmd_start(message: types.Message):
    await message.reply(
        "مرحبًا بك في بوت غالبرينا! أنا هنا لمساعدتك في تتبع أوقات الأحداث.\n"
        "إليك قائمة الأوامر المتاحة:\n\n"
        "/the_banner البنر - لعرض البنر الحالي.\n"
        "/ship_event السفينة - لعرض موعد السفينة.\n"
        "/tower التاور - لعرض موعد التاور.\n"
        "/event الاحداث - لعرض قائمة الأحداث الحالية.\n\n"
        "للمشرفين:\n"
        "setbanner أو setbanner_ar - لتحديث البنر (يرسل نص ثم صورة).\n"
        "setship_event أو setship_event_ar - لتحديث السفينة (يرسل نص ثم صورة).\n"
        "settower أو settower_ar - لتحديث التاور (يرسل نص ثم صورة).\n"
        "setevents أو setevents_ar - لإضافة حدث جديد (يرسل نص فقط).\n"
        "delevents أو حذف_الاحداث - لحذف جميع الأحداث (للمشرفين).\n\n"
        "لإدارة المشرفين:\n"
        "addadmin [user_id] أو اضافة_مشرف [user_id]\n"
        "removeadmin [user_id] أو ازالة_مشرف [user_id]"
    )

# ردود المالك الخاصة
@dp.message(F.text.lower().in_(['مين حبيبة ماما', 'مين روح ماما', 'مين هطف القروب']))
async def handle_owner_questions(message: types.Message):
    if message.from_user.id == OWNER_ID:
        if message.text.lower() == 'مين هطف القروب':
            await message.reply("برهم")
        else:
            await message.reply("انا")

# رد المالك على سؤال "غوغو"
@dp.message(F.text.lower() == 'غوغو انتي تردي على احد غيري؟')
async def handle_gogo_owner_question(message: types.Message):
    if message.from_user.id == OWNER_ID:
        await message.reply("لا ماما انتي بس")
    else:
        # يمكن ترك هذا الجزء فارغًا لتجاهل الرسالة من غير المالك
        pass

# --- Alert System Logic ---

SERVER_ARABIC_NAMES = {
    'asia': 'آسيا',
    'europe': 'أوروبا',
    'america': 'أمريكا'
}

SECTION_ARABIC_NAMES = {
    'banner': 'البنر',
    'stygian': 'حدث السفينة (Stygian)',
    'spiral_abyss': 'التاور (Spiral Abyss)',
    'events': 'الحدث'
}

def format_alert_message(content_row: tuple, server: str, alert_type: str) -> str:
    """Formats the alert message based on content and alert type."""
    content_id, section, title, name, end_time_asia, end_time_europe, end_time_america, description, image_file_id = content_row
    
    arabic_section = SECTION_ARABIC_NAMES.get(section, section)
    arabic_server = SERVER_ARABIC_NAMES.get(server, server)
    
    # Determine the name/title to display
    display_name = title if title and section != 'events' else (name if name else arabic_section)
    
    if section == 'events':
        # Events use only the name field and end_time_europe (now)
        display_name = name if name else arabic_section
        
    if alert_type == '1_hour_remaining':
        return f"🚨 **تنبيه!** 🚨\n\nباقي **ساعة واحدة** على انتهاء **{display_name}** في سيرفر **{arabic_server}**!"
    elif alert_type == 'expired':
        return f"✅ **انتهى!** ✅\n\nلقد انتهى **{display_name}** في سيرفر **{arabic_server}**."
    return ""

def was_alert_sent(content_id: int, server: str, alert_type: str) -> bool:
    """Checks if a specific alert has already been sent."""
    cursor.execute(
        "SELECT 1 FROM sent_alerts WHERE content_id = ? AND server = ? AND alert_type = ?",
        (content_id, server, alert_type)
    )
    return cursor.fetchone() is not None

def mark_alert_sent(content_id: int, server: str, alert_type: str):
    """Marks an alert as sent in the database."""
    cursor.execute(
        "INSERT OR IGNORE INTO sent_alerts (content_id, server, alert_type) VALUES (?, ?, ?)",
        (content_id, server, alert_type)
    )
    conn.commit()

async def check_and_send_alerts():
    """Periodically checks all content end times and sends alerts."""
    
    # Define the time thresholds for alerts (in seconds)
    ONE_HOUR_THRESHOLD = 3600 # 1 hour
    
    while True:
        # Check every 60 seconds
        await asyncio.sleep(60) 
        
        now_utc = datetime.now(timezone.utc)
        
        cursor.execute("SELECT id, section, title, name, end_time_asia, end_time_europe, end_time_america, description, image_file_id FROM content")
        all_content = cursor.fetchall()

        for row in all_content:
            content_id, section, title, name, end_time_asia, end_time_europe, end_time_america, description, image_file_id = row
            
            # UPDATED: Special handling for 'events' section: it now uses end_time_europe
            time_columns = {
                'asia': end_time_asia if section != 'events' else None,
                'europe': end_time_europe,
                'america': end_time_america if section != 'events' else None
            }
            
            for server, end_time_str in time_columns.items():
                if not end_time_str:
                    continue
                
                try:
                    end_time_utc = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    time_diff = end_time_utc - now_utc
                    total_seconds = int(time_diff.total_seconds())
                    
                    # --- 1 Hour Remaining Alert ---
                    # Check if time remaining is between 0 and 1 hour
                    if 0 < total_seconds <= ONE_HOUR_THRESHOLD:
                        if not was_alert_sent(content_id, server, '1_hour_remaining'):
                            alert_message = format_alert_message(row, server, '1_hour_remaining')
                            try:
                                await bot.send_message(TARGET_CHAT_ID, alert_message, parse_mode="Markdown")
                                mark_alert_sent(content_id, server, '1_hour_remaining')
                                print(f"Sent 1-hour alert for {section} on {server}")
                            except Exception as e:
                                print(f"Error sending alert: {e}")
                                
                    # --- Expired Alert ---
                    # Check if time has just passed zero 
                    elif total_seconds <= 0:
                        if not was_alert_sent(content_id, server, 'expired'):
                            alert_message = format_alert_message(row, server, 'expired')
                            try:
                                await bot.send_message(TARGET_CHAT_ID, alert_message, parse_mode="Markdown")
                                mark_alert_sent(content_id, server, 'expired')
                                print(f"Sent expired alert for {section} on {server}")
                                
                                # Cleanup for 'events' content after expiration
                                if section == 'events':
                                    cursor.execute("DELETE FROM content WHERE id = ?", (content_id,))
                                    cursor.execute("DELETE FROM sent_alerts WHERE content_id = ?", (content_id,))
                                    conn.commit()
                                    print(f"Cleaned up expired event {name} ({content_id})")

                            except Exception as e:
                                print(f"Error sending alert: {e}")

                except Exception as e:
                    print(f"Error processing content ID {content_id}: {e}")
        
# --- Main Run Function ---

async def main():
    print("بوت غالبرينا شغال...")
    # Start the background alert task
    if TARGET_CHAT_ID != 0:
        asyncio.create_task(check_and_send_alerts())
    else:
        print("تحذير: لم يتم تعيين TARGET_CHAT_ID، لن يتم إرسال التنبيهات التلقائية.")
        
    # Start the bot polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Check if TARGET_CHAT_ID is set (in case of error during startup)
    try:
        if not TARGET_CHAT_ID or TARGET_CHAT_ID == 0:
             print("ERROR: TARGET_CHAT_ID is not set in your .env file. Please set the ID of the group/channel (must start with -100) to enable alerts.")
        else:
             asyncio.run(main())
    except ValueError:
        print("ERROR: TARGET_CHAT_ID must be a valid integer (usually starting with -100). Please check your .env file.")
