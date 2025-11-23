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

# Lưu trạng thái tổng kết 15h xem đã đủ chưa
summary_15_done: bool = False
last_summary_date: str | None = None


def load_warehouses() -> dict[str, str]:
    """
    Đọc file warehouses.csv, xử lý BOM bằng utf-8-sig.
    File cần có 2 cột: id_kho, ten_kho
    """
    warehouses: dict[str, str] = {}
    with open(WAREHOUSE_FILE, encoding="utf-8-sig") as f:
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
    1. , 2. , 3. , 4. (hoặc 1) 2) ... )
    """
    found = set()
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^(\d+)\s*[.)]", s)
        if m:
            found.add(m.group(1))
    return all(str(i) in found for i in range(1, 5))


def extract_report_date(text: str):
    """
    Tìm ngày trong nội dung báo cáo dạng:
    'Ngày 22/11/2025' hoặc 'Ngày 22//11/2025'
    -> trả về đối tượng date
    Nếu không tìm được hoặc sai format -> trả về None
    """
    m = re.search(r"Ngày\s+(\d{1,2})/+(\d{1,2})/+(\d{4})", text)
    if not m:
        return None
    d, mth, y = map(int, m.groups())
    try:
        return datetime(y, mth, d).date()
    except ValueError:
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Bot báo cáo kho Giao Hàng Nặng đang chạy.\n"
        "Cú pháp báo cáo:\n"
        "Dòng 1: ID_KHO  - Tên kho\n"
        "Dòng 2: Ngày dd/mm/yyyy\n"
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

    # 5. Lấy ngày báo cáo trong nội dung & so với ngày hiện tại
    now = datetime.now(TIMEZONE)
    today = now.date()
    report_date = extract_report_date(text)

    if report_date is None:
        await update.message.reply_text(
            "⚠️ Không tìm thấy dòng 'Ngày dd/mm/yyyy' trong báo cáo.\n"
            "Vui lòng bổ sung hoặc ghi đúng định dạng."
        )
        return

    if report_date != today:
        await update.message.reply_text(
            "⚠️ Ngày báo cáo không đúng ngày hiện tại.\n"
            f"- Trong báo cáo: {report_date.strftime('%d/%m/%Y')}\n"
            f"- Hôm nay: {today.strftime('%d/%m/%Y')}\n"
            "Vui lòng chỉnh lại ngày báo cáo cho đúng rồi gửi lại."
        )
        return

    # 6. Ghi nhận kho đã báo cáo cho ngày hôm nay
    date_key = today.isoformat()
    date_label = today.strftime("%d/%m/%Y")

    if date_key not in reported_by_date:
        reported_by_date[date_key] = set()
    reported_by_date[date_key].add(id_kho)

    await update.message.reply_text(
        f"✅ ĐÃ GHI NHẬN báo cáo ngày {date_label} của:\n"
        f"{id_kho} - {ten_kho_system}"
    )

async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE, check_time: str):
    """
    check_time = "15" hoặc "16"
    """
    global summary_15_done, last_summary_date

    now = datetime.now(TIMEZONE)
    today_key = now.date().isoformat()
    date_label = now.strftime("%d/%m/%Y")

    # Reset khi sang ngày mới
    if last_summary_date != today_key:
        summary_15_done = False
        last_summary_date = today_key

    all_ids = set(WAREHOUSES.keys())
    done_ids = reported_by_date.get(today_key, set())
    missing_ids = sorted(all_ids - done_ids)

    # ================== 15h00 ==================
    if check_time == "15":
        if not missing_ids:
            summary_15_done = True
            lines = [
                f"Tổng kết ngày {date_label}: tất cả kho đã gửi báo cáo.",
                "👤 CC anh @nghinm"
            ]
        else:
            summary_15_done = False
            lines = [
                f"Tổng kết ngày {date_label}: còn {len(missing_ids)} kho chưa gửi báo cáo:",
            ]
            for id_kho in missing_ids:
                ten = WAREHOUSES.get(id_kho, "")
                lines.append(f"- {id_kho} - {ten}")

            lines.append("👤 CC anh @nghinm")

        text = "\n".join(lines)
        chat_ids = os.environ["SUMMARY_CHAT_ID"].split(",")

        for cid in chat_ids:
            cid = cid.strip()
            if cid:
                await context.bot.send_message(chat_id=int(cid), text=text)
        return

    # ================== 16h00 ==================
    if check_time == "16":
        if summary_15_done:
            return  # 15h đã đầy đủ → không gởi lại 16h

        if not missing_ids:
            lines = [
                f"Tổng kết ngày {date_label}: tất cả kho đã gửi báo cáo.",
                "👤 CC anh @nghinm"
            ]
        else:
            lines = [
                f"Tổng kết ngày {date_label}: còn {len(missing_ids)} kho chưa gửi báo cáo:",
            ]
            for id_kho in missing_ids:
                ten = WAREHOUSES.get(id_kho, "")
                lines.append(f"- {id_kho} - {ten}")

            lines.append("👤 CC anh @nghinm")

        text = "\n".join(lines)
        chat_ids = os.environ["SUMMARY_CHAT_ID"].split(",")

        for cid in chat_ids:
            cid = cid.strip()
            if cid:
                await context.bot.send_message(chat_id=int(cid), text=text)
        return



    # ======== LOGIC 16H00 ========
    if check_time == "16":
        # Nếu 15h đã đủ thì thôi
        if summary_15_done:
            return

        if not missing_ids:
            text = (
                f"Tổng kết ngày {date_label}: "
                f"Tất cả các kho đã gửi báo cáo trong ngày.\n"
                f"👤 CC anh @nghinm"
            )
        else:
            lines = [
                f"Tổng kết ngày {date_label}: còn {len(missing_ids)} kho chưa gửi báo cáo:",
            ]
            for id_kho in missing_ids:
                ten = WAREHOUSES.get(id_kho, "")
                lines.append(f"- {id_kho} - {ten}")
            lines.append("\n👤 CC anh @nghinm")
            text = "\n".join(lines)

        # Gửi tới nhiều group
        chat_ids_raw = os.environ.get("SUMMARY_CHAT_ID", "")
        chat_ids = [cid.strip() for cid in chat_ids_raw.split(",") if cid.strip()]

        for cid in chat_ids:
            try:
                await context.bot.send_message(chat_id=int(cid), text=text)
            except Exception as e:
                print(f"Lỗi gửi tới {cid}: {e}")

        return



# ================== JOB 15H VÀ 16H =====================
async def daily_summary_15(context: ContextTypes.DEFAULT_TYPE):
    await send_daily_summary(context, check_time="15")


async def daily_summary_16(context: ContextTypes.DEFAULT_TYPE):
    await send_daily_summary(context, check_time="16")


def main():
    global WAREHOUSES
    WAREHOUSES = load_warehouses()

# ================== LỆNH /report =====================
async def report_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Lệnh /report:
    Tổng kết số kho đã báo cáo và chưa báo cáo trong ngày hôm nay.
    Gửi sang SUMMARY_CHAT_ID và reply lại group đang gọi lệnh.
    """

    now = datetime.now(TIMEZONE)
    today_key = now.date().isoformat()
    date_label = now.strftime("%d/%m/%Y")

    all_ids = set(WAREHOUSES.keys())
    done_ids = reported_by_date.get(today_key, set())
    missing_ids = sorted(all_ids - done_ids)

    # 1. số kho đã báo cáo
    total = len(all_ids)
    done = len(done_ids)
    miss = len(missing_ids)

    lines = [
        f"📊 **Tổng kết ngày {date_label}:**",
        f"1️⃣ Số kho đã báo cáo: {done}/{total} kho",
        f"2️⃣ Các kho chưa báo cáo ({miss} kho):"
    ]

    if miss == 0:
        lines.append("✔️ Tất cả các kho đã gửi báo cáo.")
    else:
        for id_kho in missing_ids:
            ten = WAREHOUSES.get(id_kho, "")
            lines.append(f"- {id_kho} - {ten}")

    # Thêm CC anh Nghị
    lines.append("\n👤 CC anh @nghinm để nắm thông tin.")

    text = "\n".join(lines)

    # Gửi vào group tổng hợp
    summary_chat_id = int(os.environ["SUMMARY_CHAT_ID"])
    await context.bot.send_message(chat_id=summary_chat_id, text=text)

    # Gửi lại group hiện tại để báo đã gửi
    if update.message:
        await update.message.reply_text("✅ Đã gửi tổng hợp vào group tổng hợp.")


def main():
    global WAREHOUSES
    WAREHOUSES = load_warehouses()

    token = os.environ["BOT_TOKEN"]
    if not token:
        raise RuntimeError("Chưa cấu hình biến môi trường BOT_TOKEN")

    application = ApplicationBuilder().token(token).build()

    # Lệnh /start
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("report", report_status))


    # Nhận mọi tin nhắn text (không phải command) -> check báo cáo
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, report_handler)
    )

    # Job tổng hợp 15h00 & 16h00 hàng ngày
    job_queue = application.job_queue
    job_queue.run_daily(
        daily_summary_15,
        time=time(hour=15, minute=0, tzinfo=TIMEZONE),
        name="daily_summary_15",
    )
    job_queue.run_daily(
        daily_summary_16,
        time=time(hour=16, minute=0, tzinfo=TIMEZONE),
        name="daily_summary_16",
    )

    application.run_polling()


if __name__ == "__main__":
    main()
