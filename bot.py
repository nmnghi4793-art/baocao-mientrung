import os
import csv
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# ===== CẤU HÌNH CƠ BẢN =====
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
WAREHOUSE_FILE = "warehouses.csv"

# Lưu: { "YYYY-MM-DD": set(["21163000", "21095000", ...]) }
reported_by_date = {}  # type: dict[str, set[str]]

# Lưu danh sách kho: { "21163000": "Kho Giao Hàng Nặng Ninh Thuận", ... }
WAREHOUSES = {}  # type: dict[str, str]


def load_warehouses():
    warehouses = {}
    with open(WAREHOUSE_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            id_kho = str(row["id_kho"]).strip()
            ten_kho = str(row["ten_kho"]).strip()
            if id_kho and ten_kho:
                warehouses[id_kho] = ten_kho
    return warehouses


def extract_kho_from_text(text: str):
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
    found = set()
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^(\d+)\s*[.)]", s)
        if m:
            found.add(m.group(1))
    return all(str(i) in found for i in range(1, 5))


def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "✅ Bot báo cáo kho Giao Hàng Nặng đang chạy.\n"
        "Cú pháp báo cáo:\n"
        "Dòng 1: ID_KHO  - Tên kho\n"
        "Sau đó là 4 mục 1,2,3,4 giống template."
    )


def report_handler(update: Update, context: CallbackContext):
    if not update.message or not update.message.text:
        return

    text = update.message.text

    id_kho, ten_kho_msg = extract_kho_from_text(text)
    if not id_kho:
        return

    ten_kho_system = WAREHOUSES.get(id_kho)
    if not ten_kho_system:
        update.message.reply_text(
            "⚠️ ID kho {} chưa có trong danh sách, vui lòng kiểm tra lại.".format(
                id_kho
            )
        )
        return

    if ten_kho_msg.lower().strip() != ten_kho_system.lower().strip():
        update.message.reply_text(
            "⚠️ Tên kho không khớp với danh sách.\n"
            "Trong file là: {} - {}".format(id_kho, ten_kho_system)
        )
        return

    if not has_sections_1_to_4(text):
        update.message.reply_text(
            "⚠️ Báo cáo chưa đủ 4 mục (1, 2, 3, 4). Vui lòng kiểm tra lại cú pháp."
        )
        return

    now = datetime.now(TIMEZONE)
    today_key = now.date().isoformat()

    if today_key not in reported_by_date:
        reported_by_date[today_key] = set()
    reported_by_date[today_key].add(id_kho)

    update.message.reply_text(
        "✅ ĐÃ GHI NHẬN báo cáo ngày {} của:\n{} - {}".format(
            now.strftime("%d/%m/%Y"), id_kho, ten_kho_system
        )
    )


def daily_summary(context: CallbackContext):
    now = datetime.now(TIMEZONE)
    today_key = now.date().isoformat()

    all_ids = set(WAREHOUSES.keys())
    done_ids = reported_by_date.get(today_key, set())
    missing_ids = sorted(all_ids - done_ids)

    if not missing_ids:
        text = (
            "✅ {} - TẤT CẢ {} kho đã gửi báo cáo trước 15h00.".format(
                now.strftime("%d/%m/%Y"), len(all_ids)
            )
        )
    else:
        lines = [
            "❌ Đến 15h00 ngày {}, còn {} kho CHƯA gửi báo cáo:".format(
                now.strftime("%d/%m/%Y"), len(missing_ids)
            )
        ]
        for id_kho in missing_ids:
            ten_kho = WAREHOUSES.get(id_kho, "")
            lines.append("- {} - {}".format(id_kho, ten_kho))
        text = "\n".join(lines)

    summary_chat_id = int(os.environ["SUMMARY_CHAT_ID"])
    context.bot.send_message(chat_id=summary_chat_id, text=text)


def main():
    global WAREHOUSES
    WAREHOUSES.update(load_warehouses())

    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Chưa cấu hình biến môi trường BOT_TOKEN")

    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, report_handler))

    job_queue = updater.job_queue
    job_queue.run_daily(
        daily_summary,
        time=time(hour=15, minute=0, tzinfo=TIMEZONE),
        name="daily_summary",
    )

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
