import os
import csv
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# ===== CẤU HÌNH CƠ BẢN =====
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
WAREHOUSE_FILE = "warehouses.csv"

# Lưu: { "YYYY-MM-DD": set(["21163000", "21095000", ...]) }
reported_by_date: dict[str, set[str]] = {}

# Lưu danh sách kho: {"21163000": "Kho Giao Hàng Nặng Ninh Thuận", ...}
WAREHOUSES: dict[str, str] = {}


def load_warehouses() -> dict[str, str]:
    warehouses: dict[str, str] = {}
    with open(WAREHOUSE_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            id_kho = str(row["id_kho"]).strip()
            ten_kho = str(row["ten_kho"]).strip()
            if id_kho and ten_kho:
                warehouses[id_kho] = ten_kho
    return warehouses


def extract_kho_from_text(text: str):
    """
    Dòng đầu dạng:
    21163000  - Kho Giao Hàng Nặng Ninh Thuận
    -> trả về: ("21163000", "Kho Giao Hàng Nặng Ninh Thuận")
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None, None

    first_line = lines[0]
    m = re.search(r"(?P<id>\d{8})\s*-\s*(?P<name>.+)", first_line)
    if not m:
        return None, None

    id_kho = m.group("id").strip()
    ten_kho_msg = m.group("name").strip()
    return id_kho, ten_kho_msg


def has_sections_1_to_4(text: str) -> bool:
    """
    Kiểm tra trong nội dung có đủ 4 mục bắt đầu bằng:
    1. , 2. , 3. , 4. (hoặc 1) 2) ...)
    """
    found = set()
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^(\d+)\s*[.)]", s)
        if m:
            found.add(m.group(1))
    return all(str(i) in found for i in range(1, 5))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Bot báo cáo kho Giao Hàng Nặng đang chạy.\n"
        "Cú pháp báo cáo:\n"
        "Dòng 1: ID_KHO  - Tên kho\n"
        "Sau đó là 4 mục 1,2,3,4 giống template."
    )


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text

    # 1. Parse ID + tên kho ở dòng đầu
    id_kho, ten_kho_msg = extract_kho_from_text(text)
    if not id_kho:
        # Không phải tin nhắn báo cáo -> bỏ qua
        return

    # 2. Kiểm tra ID có trong danh sách kho
    ten_kho_system = WAREHOUSES.get(id_kho)
    if not ten_kho_system:
        await update.message.reply_text(
            f"⚠️ ID kho {id_kho} chưa có trong danh sách, vui lòng kiểm tra lại."
        )
        return

    # 3. Kiểm tra tên kho có khớp không
    if ten_kho_msg.lower().strip() != ten_kho_system.lower().strip():
        await update.message.reply_text(
            "⚠️ Tên kho không khớp với danh sách.\n"
            f"Trong file là: {id_kho} - {ten_kho_system}"
        )
        return

    # 4. Kiểm tra có đủ 4 mục 1-4 không
    if not has_sections_1_to_4(text):
        await update.message.reply_text(
            "⚠️ Báo cáo chưa đủ 4 mục (1, 2, 3, 4). "
            "Vui lòng kiểm tra lại cú pháp."
        )
        return

    # 5. Ghi nhận kho đã báo cáo cho ngày hôm nay
    now = datetime.now(TIMEZONE)
    today_key = now.date().isoformat()  # VD: "2025-11-23"

    if today_key not in reported_by_date:
        reported_by_date[today_key] = set()
    reported_by_date[today_key].add(id_kho)

    await update.message.reply_text(
        f"✅ ĐÃ GHI NHẬN báo cáo ngày {now.strftime('%d/%m/%Y')} của:\n"
        f"{id_kho} - {ten_kho_system}"
    )


async def daily_summary(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TIMEZONE)
    today_key = now.date().isoformat()

    all_ids = set(WAREHOUSES.keys())
    done_ids = reported_by_date.get(today_key, set())
    missing_ids = sorted(all_ids - done_ids)

    if not missing_ids:
        text = (
            f"✅ {now.strftime('%d/%m/%Y')} - TẤT CẢ "
            f"{len(all_ids)} kho đã gửi báo cáo trước 15h00."
        )
    else:
        lines = [
            f"❌ Đến 15h00 ngày {now.strftime('%d/%m/%Y')}, "
            f"còn {len(missing_ids)} kho CHƯA gửi báo cáo:"
        ]
        for id_kho in missing_ids:
            ten_kho = WAREHOUSES.get(id_kho, "")
            lines.append(f"- {id_kho} - {ten_kho}")
        text = "\n".join(lines)

    summary_chat_id = int(os.environ["SUMMARY_CHAT_ID"])
    await context.bot.send_message(chat_id=summary_chat_id, text=text)


def main():
    global WAREHOUSES
    WAREHOUSES = load_warehouses()

    token = os.environ["BOT_TOKEN"]
    if not token:
        raise RuntimeError("Chưa cấu hình biến môi trường BOT_TOKEN")

    application = ApplicationBuilder().token(token).build()

    # Lệnh /start
    application.add_handler(CommandHandler("start", start))

    # Nhận mọi tin nhắn text (không phải command) -> check báo cáo
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, report_handler)
    )

    # Job tổng hợp 15h00 hàng ngày
    job_queue = application.job_queue
    job_queue.run_daily(
        daily_summary,
        time=time(hour=15, minute=0, tzinfo=TIMEZONE),
        name="daily_summary",
    )

    application.run_polling()


if __name__ == "__main__":
    main()
