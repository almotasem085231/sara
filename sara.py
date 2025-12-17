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

# --- الإعدادات الأساسية ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID"))

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- قاعدة البيانات ---
conn = sqlite3.connect("genshin_bot.db")
cursor = conn.cursor()

def setup_db():
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
    )""")
    try:
        cursor.execute("ALTER TABLE content ADD COLUMN description TEXT")
    except:
        pass
    cursor.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
    conn.commit()

setup_db()

# --- حالات الإدخال (FSM) ---
class UpdateContent(StatesGroup):
    waiting_for_title_and_name = State()
    waiting_for_title = State()
    waiting_for_event_text = State()
    waiting_for_asia_time = State()
    waiting_for_europe_time = State()
    waiting_for_america_time = State()
    waiting_for_photo = State()

# --- دالة التحقق من الإدمن ---
def is_admin(user_id):
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None

# --- معالجة الوقت ---
def parse_time(dt_str, offset_hours):
    try:
        tz = timezone(timedelta(hours=offset_hours))
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        return dt.astimezone(timezone.utc)
    except:
        return None

def get_time_left(end_time_str):
    now = datetime.now(timezone.utc)
    end_dt = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    diff = end_dt - now
    if diff.total_seconds() <= 0:
        return "منتهي"
    days = diff.days
    hours = diff.seconds // 3600
    return f"{days}يوم و {hours}ساعة"

# --- أوامر الإضافة (البنرات وغيرها) ---
@dp.message(Command('setbanner'))
async def set_banner(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(section='banner')
    await message.reply("أرسل البيانات: عنوان المحتوى ; اسم الحدث")
    await state.set_state(UpdateContent.waiting_for_title_and_name)

@dp.message(Command('setship_event'))
async def set_ship(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(section='stygian', name="")
    await message.reply("أرسل عنوان المحتوى (للسفينة):")
    await state.set_state(UpdateContent.waiting_for_title)

@dp.message(Command('settower'))
async def set_tower(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(section='spiral_abyss', name="")
    await message.reply("أرسل عنوان المحتوى (للتاور):")
    await state.set_state(UpdateContent.waiting_for_title)

# --- استقبال البيانات المشترك ---
@dp.message(UpdateContent.waiting_for_title_and_name)
async def proc_title_name(message: types.Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split(";", 1)]
    if len(parts) < 2: return await message.reply("خطأ! استخدم الفاصلة المنقوطة.")
    await state.update_data(title=parts[0], name=parts[1])
    await message.reply("أرسل وقت آسيا (YYYY-MM-DD HH:MM:SS):")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_title)
async def proc_title_only(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.reply("أرسل وقت آسيا (YYYY-MM-DD HH:MM:SS):")
    await state.set_state(UpdateContent.waiting_for_asia_time)

@dp.message(UpdateContent.waiting_for_asia_time)
async def proc_asia(message: types.Message, state: FSMContext):
    await state.update_data(asia=message.text.strip())
    await message.reply("أرسل وقت أوروبا:")
    await state.set_state(UpdateContent.waiting_for_europe_time)

@dp.message(UpdateContent.waiting_for_europe_time)
async def proc_euro(message: types.Message, state: FSMContext):
    await state.update_data(euro=message.text.strip())
    await message.reply("أرسل وقت أمريكا:")
    await state.set_state(UpdateContent.waiting_for_america_time)

@dp.message(UpdateContent.waiting_for_america_time)
async def proc_amer(message: types.Message, state: FSMContext):
    await state.update_data(amer=message.text.strip())
    await message.reply("أرسل الصورة:")
    await state.set_state(UpdateContent.waiting_for_photo)

@dp.message(UpdateContent.waiting_for_photo, F.photo)
async def final_step(message: types.Message, state: FSMContext):
    data = await state.get_data()
    t_asia = parse_time(data['asia'], 8)
    t_euro = parse_time(data['euro'], 1)
    t_amer = parse_time(data['amer'], -5)
    
    if not all([t_asia, t_euro, t_amer]):
        return await message.reply("خطأ في تنسيق الوقت!")

    cursor.execute("DELETE FROM content WHERE section=?", (data['section'],))
    cursor.execute("""INSERT INTO content 
        (section, title, name, end_time_asia, end_time_europe, end_time_america, image_file_id) 
        VALUES (?,?,?,?,?,?,?)""", 
        (data['section'], data['title'], data.get('name', ""), 
         t_asia.strftime("%Y-%m-%d %H:%M:%S"), 
         t_euro.strftime("%Y-%m-%d %H:%M:%S"), 
         t_amer.strftime("%Y-%m-%d %H:%M:%S"), 
         message.photo[-1].file_id))
    conn.commit()
    await message.reply("✅ تم التحديث بنجاح.")
    await state.clear()

# --- قسم الأحداث الجديد ---
@dp.message(Command('setevents'))
async def start_event_add(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await message.reply("أرسل الحدث بالشكل التالي:\nالاسم ; الوقت ; النبذة")
    await state.set_state(UpdateContent.waiting_for_event_text)

@dp.message(UpdateContent.waiting_for_event_text)
async def save_event(message: types.Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split(";", 2)]
    if len(parts) < 2: return await message.reply("خطأ في الصيغة!")
    
    name, time_str = parts[0], parts[1]
    desc = parts[2] if len(parts) > 2 else ""
    utc_time = parse_time(time_str, 1) # أوروبا
    
    if not utc_time: return await message.reply("وقت خاطئ!")
    
    cursor.execute("INSERT INTO content (section, name, end_time_europe, description) VALUES ('events',?,?,?)",
                   (name, utc_time.strftime("%Y-%m-%d %H:%M:%S"), desc))
    conn.commit()
    await message.reply(f"✅ تمت إضافة: {name}")
    await state.clear()

@dp.message(Command('events', 'event'), F.text.lower().in_(['الاحداث', '/events', '/event']))
async def show_events_list(message: types.Message):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("DELETE FROM content WHERE section='events' AND end_time_europe <= ?", (now,))
    conn.commit()
    
    cursor.execute("SELECT name, end_time_europe, description FROM content WHERE section='events'")
    rows = cursor.fetchall()
    if not rows: return await message.reply("لا توجد أحداث حالية.")

    res = "قائمة الأيفنتات الحالية:\n\n"
    for i, (name, et, desc) in enumerate(rows):
        tl = get_time_left(et)
        icon = "❖" if i == 0 else "✦"
        label = "الأيفنت الرئيسي" if i == 0 else "ايفنت"
        
        res += f"{icon}{label} [{name}]\n"
        if desc: res += f"-نبذة عن الأيفنت:\n{desc}\n\n"
        res += f"المهلة المتبقية: {tl} ༺━━━━━━━━━━━━━━━━━━━━━━༻\n"
    
    await message.reply(res)

# --- عرض المحتوى الفردي (البنر/السفينة/التاور) ---
@dp.message(F.text.lower().in_(['البنر', 'السفينة', 'التاور']))
async def show_single_content(message: types.Message):
    mapping = {'البنر': 'banner', 'السفينة': 'stygian', 'التاور': 'spiral_abyss'}
    sec = mapping[message.text]
    cursor.execute("SELECT title, name, end_time_asia, end_time_europe, end_time_america, image_file_id FROM content WHERE section=?", (sec,))
    row = cursor.fetchone()
    if not row: return await message.reply("لا يوجد بيانات.")
    
    title, name, ea, ee, em, fid = row
    text = f"🔹 **{title} :**\n\n" + (f"**{name}**\n\n" if name else "")
    for s, v in [('اسيا', ea), ('اوروبا', ee), ('امريكا', em)]:
        text += f"⏳ سيرفر {s} :\n ●← {get_time_left(v)}\n\n"
    
    await message.reply_photo(fid, caption=text, parse_mode="Markdown")

# --- أوامر الترفيه والتحكم ---
@dp.message(F.text == 'الاوامر')
async def list_cmds(m):
    await m.reply("أوامر البوت:\n/the_banner\n/ship_event\n/tower\n/event")

@dp.message(F.text.in_(['مين هطف القروب', 'مين روح ماما', 'مين حبيبة ماما']))
async def owner_fun(m):
    if m.from_user.id == OWNER_ID:
        await m.reply("برهم" if "هطف" in m.text else "انا")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
