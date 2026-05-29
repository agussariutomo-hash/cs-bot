import os
import time
import random
import asyncio
from io import BytesIO
from dotenv import load_dotenv
from telethon import TelegramClient, events
from google import genai
from google.genai import types
from telethon.sessions import StringSession

load_dotenv()

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SESSION_NAME = "flashotp_admin_session"

if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
    raise ValueError("TELEGRAM_API_ID atau TELEGRAM_API_HASH belum diisi di file .env")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY belum diisi di file .env")

TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")

if TELEGRAM_SESSION_STRING:
    telegram = TelegramClient(
        StringSession(TELEGRAM_SESSION_STRING),
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH
    )
else:
    telegram = TelegramClient(
        SESSION_NAME,
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH
    )

gemini = genai.Client(api_key=GEMINI_API_KEY)

chat_history = {}
last_reply = {}

MAX_HISTORY = 10 # Sedikit dinaikkan agar AI ingat konteks troubleshooting
COOLDOWN_SECONDS = 5
GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """
Kamu adalah admin customer service resmi FlashOTP.shop, web penjual nomor virtual (nokos).

GAYA BAHASA & SIKAP (SANGAT PENTING):
- Bertingkahlah 100% seperti manusia. Gunakan bahasa Indonesia santai (kak, iya, waduh, coba deh, sebentar ya).
- JANGAN PERNAH membalas dengan format list/bullet points panjang.
- JANGAN PERNAH menggunakan markdown tebal (**teks**).
- Balas maksimal 1 sampai 3 kalimat pendek saja.
- Jangan bertingkah seperti AI atau asisten virtual.

TEKNIK PROBLEM SOLVING (INVESTIGATIF):
- Jangan memberikan semua solusi sekaligus di satu balasan! 
- Jika masalah user belum jelas, TANYAKAN SATU HAL SPESIFIK terlebih dahulu.
- Contoh: Jika user bilang "kode ga masuk", jangan langsung suruh clear cache dan ganti IP. Tanyain dulu: "Halo kak, ini untuk pendaftaran aplikasi apa ya kalau boleh tau?"
- Giring user perlahan untuk menemukan solusinya (Cek IP, Cek Cache, Cek Device terdeteksi).
- Minta ID Order HANYA jika sudah mentok dan butuh pengecekan transaksi.

ATURAN BISNIS (FlashOTP.shop):
- Top up hanya via QRIS, nama merchant-nya Pakasir. (Jangan sebut Pakasir itu metode, sebut saja QRIS Pakasir).
- Kalau saldo belum masuk, suruh kirim screenshot bukti transfer QRIS Pakasir, nominal, dan username.
- Kalau OTP tidak masuk/nomor diblokir (terutama WA, Telegram, Shopee, Gmail), sampaikan pelan-pelan bahwa itu dari sistem validasi aplikasinya (bisa karena IP, cache, atau device terdeteksi).
- Refund tidak selalu bisa dilakukan jika nomor sudah terbaca atau dibatasi oleh aplikasi target. Tolak refund dengan sangat halus dan tawarkan bantuan solusi lain.
- Dilarang minta password/OTP login akun customer.
"""

def clean_markdown(text):
    """Menghapus markdown tebal/miring bawaan AI agar terlihat natural"""
    return text.replace("**", "").replace("__", "").replace("*", "")

def cleanup_memory():
    """Menghapus history user yang tidak aktif selama 24 jam (86400 detik)"""
    now = time.time()
    inactive_users = [uid for uid, last_time in last_reply.items() if now - last_time > 6400]
    for uid in inactive_users:
        chat_history.pop(uid, None)
        last_reply.pop(uid, None)

def add_history(user_id, role, text):
    cleanup_memory() # Bersihkan memori usang setiap kali ada chat baru
    
    if user_id not in chat_history:
        chat_history[user_id] = []

    chat_history[user_id].append({
        "role": role,
        "text": text
    })

    chat_history[user_id] = chat_history[user_id][-MAX_HISTORY:]

def build_prompt(user_id, message, has_image=False):
    history_text = ""

    for item in chat_history.get(user_id, []):
        if item["role"] == "user":
            history_text += f"Customer: {item['text']}\n"
        else:
            history_text += f"Admin: {item['text']}\n"

    image_instruction = ""
    if has_image:
        image_instruction = """
[SYSTEM NOTE: Customer mengirim gambar/screenshot bersamaan dengan pesan ini. Baca gambar tersebut. 
Jika itu bukti transfer, cek apakah ada kata 'Pakasir'. Jika itu error aplikasi, baca teks errornya dan gunakan untuk menjawab masalah customer.]
"""

    return f"""
{SYSTEM_PROMPT}

Riwayat chat sejauh ini:
{history_text}

Pesan customer terbaru:
{message}
{image_instruction}

Balas pesan customer tersebut langsung sebagai admin. (Ingat: Pendek, natural, dan investigatif).
"""

def local_fallback_reply(message, has_image=False):
    msg = (message or "").lower()

    if has_image:
        return "Noted kak gambarnya. Ini kendalanya pas di tahap mana ya tadi?"

    if any(k in msg for k in ["metode", "bayar pakai", "dana", "ovo", "gopay"]):
        return "Kita topup-nya pakai metode QRIS ya kak. Nanti pas di-scan munculnya atas nama Pakasir."

    if any(k in msg for k in ["saldo", "belum masuk", "depo", "top up"]):
        return "Boleh kirim screenshot bukti transfer QRIS Pakasir-nya kak? Sama username webnya ya biar aku bantu cek."

    if any(k in msg for k in ["otp", "kode", "gak masuk"]):
        return "Itu untuk daftar aplikasi apa kak kalau boleh tau? Biar aku cek status layanannya."

    return "Halo kak, ada yang bisa dibantu untuk nomor atau transaksinya?"

async def download_image_bytes(event):
    try:
        if not event.photo and not event.document:
            return None, None

        bio = BytesIO()
        await event.download_media(file=bio)
        image_bytes = bio.getvalue()

        if not image_bytes:
            return None, None

        mime_type = "image/jpeg"
        if event.document and getattr(event.document, "mime_type", None):
            mime_type = event.document.mime_type

        if mime_type not in ["image/jpeg", "image/png", "image/webp"]:
            mime_type = "image/jpeg"

        return image_bytes, mime_type

    except Exception as e:
        print("ERROR DOWNLOAD GAMBAR:", repr(e))
        return None, None

async def generate_reply(user_id, message, image_bytes=None, mime_type=None):
    has_image = image_bytes is not None
    user_history_text = message if message else "[Customer mengirim screenshot/foto]"
    add_history(user_id, "user", user_history_text)

    try:
        prompt = build_prompt(
            user_id=user_id,
            message=user_history_text,
            has_image=has_image
        )

        if has_image:
            contents = [
                prompt,
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type or "image/jpeg"
                )
            ]
        else:
            contents = prompt

        response = gemini.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents
        )

        reply = (response.text or "").strip()
        reply = clean_markdown(reply)

        if not reply:
            reply = local_fallback_reply(message, has_image=has_image)

    except Exception as e:
        print("ERROR GEMINI:", repr(e))
        reply = local_fallback_reply(message, has_image=has_image)

    add_history(user_id, "assistant", reply)
    return reply

async def safe_reply(event, text):
    """
    Simulasi Human Presence yang realistis:
    1. Mark as Read (Centang 2 biru)
    2. Jeda mikir sejenak
    3. Action Typing... (durasinya menyesuaikan panjang teks balasan)
    """
    chat_id = event.chat_id
    
    # 1. Tandai pesan sudah dibaca
    await event.client.send_read_acknowledge(chat_id, event.message)
    
    # 2. Jeda "membaca & mikir" (1 - 2 detik)
    await asyncio.sleep(random.uniform(1.0, 2.5))
    
    # 3. Hitung durasi mengetik yang masuk akal (asumsi 1 dtk ngetik 25 karakter)
    typing_duration = min(len(text) / 25.0, 6.0) # Maksimal ngetik 6 detik aja biar user ga kelamaan nunggu
    
    # 4. Tampilkan status "Typing..."
    async with event.client.action(chat_id, 'typing'):
        await asyncio.sleep(typing_duration)
    
    # 5. Kirim balasan
    await event.reply(text)

@telegram.on(events.NewMessage(incoming=True))
async def handle_message(event):
    if not event.is_private or event.out:
        return

    sender = await event.get_sender()
    user_id = sender.id

    message = event.raw_text.strip() if event.raw_text else ""
    image_bytes, mime_type = None, None

    if event.photo or event.document:
        image_bytes, mime_type = await download_image_bytes(event)

    if not message and not image_bytes:
        return

    now = time.time()
    
    # Simple Anti-Spam
    if user_id in last_reply and now - last_reply[user_id] < COOLDOWN_SECONDS:
        print(f"Spam terdeteksi dari {user_id}. Menunggu.")
        return

    last_reply[user_id] = now

    try:
        reply = await generate_reply(
            user_id=user_id,
            message=message,
            image_bytes=image_bytes,
            mime_type=mime_type
        )
        
        await safe_reply(event, reply)

    except Exception as e:
        print("ERROR SAAT BALAS TELEGRAM:", repr(e))
        fallback_msg = local_fallback_reply(message, has_image=image_bytes is not None)
        await safe_reply(event, fallback_msg)


async def main():
    await telegram.connect()

    if not await telegram.is_user_authorized():
        print("\nSESSION BELUM LOGIN. Gunakan script login_session.py terlebih dahulu.\n")
        await telegram.disconnect()
        return

    me = await telegram.get_me()
    username = f"@{me.username}" if me.username else "tanpa username"

    print(f"Session aktif sebagai: {me.first_name} | {username}")
    print("Auto-reply CS FlashOTP V2.0 (Human-like) Berjalan...\n")

    await telegram.run_until_disconnected()

if __name__ == "__main__":
    telegram.loop.run_until_complete(main())
