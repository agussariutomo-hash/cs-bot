const express = require('express');
const axios = require('axios');
require('dotenv').config();

const app = express();

// Pasang pendeteksi dua jenis format data
app.use(express.json()); 
app.use(express.urlencoded({ extended: true })); 

const PORT = process.env.PORT || 3000;
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;

// ==========================================
// PINTU MASUK WEBHOOK DARI PROVIDER
// ==========================================
app.post('/webhook', async (req, res) => {
    // 1. Tangkap datanya
    const payload = req.body;

    // 2. Langsung balas OK ke provider detik itu juga biar mereka tenang
    res.status(200).send('OK');

    // 3. Siapkan pesan ke Telegram
    const pesan = `🔔 <b>UPDATE DARI PROVIDER (VIA RAILWAY)!</b>\n━━━━━━━━━━━━━━━━━\n📦 <b>Raw Data:</b>\n<pre>${JSON.stringify(payload, null, 2)}</pre>\n━━━━━━━━━━━━━━━━━`;

    // 4. Kirim ke Telegram di belakang layar
    try {
        await axios.post(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
            chat_id: TELEGRAM_CHAT_ID,
            text: pesan,
            parse_mode: 'HTML'
        });
        console.log('Notif Telegram sukses terkirim!');
    } catch (error) {
        console.error('Gagal ngirim ke Telegram:', error.message);
    }
});

// Halaman depan buat ngecek server idup atau mati
app.get('/', (req, res) => {
    res.send('✅ Server Webhook FlashOTP Berjalan Normal!');
});

// Nyalakan servernya
app.listen(PORT, () => {
    console.log(`Server jalan di port ${PORT}`);
});
