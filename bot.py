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
    - 15h00: luôn gửi tổng kết.
    - 16h00: chỉ gửi nếu 15h00 còn thiếu kho.
    Nội dung:
    1. Số kho đã báo cáo: X/Y
    2. Các kho chưa báo cáo
    + Dòng CC a @nghinm
    """
    global summary_15_done, last_summary_date

    now = datetime.now(TIMEZONE)
    today = now.date()
    today_key = today.isoformat()
    date_label = today.strftime("%d/%m/%Y")

    # Nếu sang ngày mới thì reset trạng thái 15h
    if last_summary_date != today_key:
        summary_15_done = False
        last_summary_date = today_key

    # Danh sách tất cả kho
    all_ids = sorted(WAREHOUSES.keys())
    total_kho = len(all_ids)

    # Những kho đã báo cáo trong ngày
    reported_ids = reported_by_date.get(today_key, set())
    num_reported = len(reported_ids)

    # Những kho chưa báo cáo
    missing_ids = [kid for kid in all_ids if kid not in reported_ids]
    num_missing = len(missing_ids)

    # ======= LOGIC 15H00 =======
    if check_time == "15":
        summary_15_done = (num_missing == 0)  # nếu hết thiếu thì đánh dấu đủ

        lines = []
        lines.append(f"Tổng kết ngày {date_label}:")
        lines.append(f"1. Số kho đã báo cáo: {num_reported}/{total_kho} kho")

        if num_missing == 0:
            lines.append("2. Các kho chưa báo cáo: Không, tất cả kho đã báo cáo.")
        else:
            lines.append(f"2. Các kho chưa báo cáo ({num_missing} kho):")
            for kid in missing_ids:
                ten_kho = WAREHOUSES.get(kid, "")
                lines.append(f"- {kid} - {ten_kho}")

        # 👉 Thêm dòng CC
        lines.append("")
        lines.append("CC a @nghinm vào nắm thông tin")

        text = "\n".join(lines)

        summary_chat_id_raw = os.environ.get("SUMMARY_CHAT_ID", "")
        chat_ids = [cid.strip() for cid in summary_chat_id_raw.split(",") if cid.strip()]

        for cid in chat_ids:
            try:
                await context.bot.send_message(chat_id=int(cid), text=text)
            except Exception as e:
                print(f"Lỗi gửi tới {cid}: {e}")
        return

    # ======= LOGIC 16H00 =======
    if check_time == "16":
        # Nếu 15h tất cả đã đủ thì thôi, không gửi nữa
        if summary_15_done:
            return

        lines = []
        lines.append(f"Tổng kết lại lúc 16h00 ngày {date_label}:")
        lines.append(f"1. Số kho đã báo cáo: {num_reported}/{total_kho} kho")

        if num_missing == 0:
            lines.append("2. Các kho chưa báo cáo: Không, tất cả kho đã báo cáo.")
        else:
            lines.append(f"2. Các kho chưa báo cáo ({num_missing} kho):")
            for kid in missing_ids:
                ten_kho = WAREHOUSES.get(kid, "")
                lines.append(f"- {kid} - {ten_kho}")

        # 👉 Thêm dòng CC
        lines.append("")
        lines.append("CC a @nghinm vào nắm thông tin")

        text = "\n".join(lines)

        summary_chat_id_raw = os.environ.get("SUMMARY_CHAT_ID", "")
        chat_ids = [cid.strip() for cid in summary_chat_id_raw.split(",") if cid.strip()]

        for cid in chat_ids:
            try:
                await context.bot.send_message(chat_id=int(cid), text=text)
            except Exception as e:
                print(f"Lỗi gửi tới {cid}: {e}")
                

    # Báo lại ở group đang gõ lệnh cho dễ biết
    if update.message:
        await update.message.reply_text("✅ Đã gửi tổng kết vào các group cấu hình.")


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
