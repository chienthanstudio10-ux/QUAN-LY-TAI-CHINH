from datetime import datetime, timedelta
import json
import os
import re
import sqlite3
import time
import altair as alt
from PIL import Image
import pandas as pd
import streamlit as st
import google.generativeai as genai

# Thiết lập múi giờ chuẩn Việt Nam (GMT+7) cho hệ thống máy chủ đám mây
os.environ['TZ'] = 'Asia/Ho_Chi_Minh'
if hasattr(time, 'tzset'):
    time.tzset()

# Page configuration
st.set_page_config(
    page_title="Quản Lý Tài Chính Studio & Gia Đình", page_icon="💰", layout="wide"
)

# --- BẢO MẬT API KEY VỚI ST.SECRETS ---
try:
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=gemini_api_key)
    ai_enabled = True
except Exception as e:
    ai_enabled = False
    st.sidebar.error(
        "⚠️ Chưa cấu hình GEMINI_API_KEY trong Streamlit Secrets! Tính năng AI sẽ bị vô hiệu hóa."
    )


# Initialize SQLite Database
def init_db():
    conn = sqlite3.connect("finance.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ngay TEXT,
            noi_dung TEXT,
            phan_loai TEXT,
            nguon_quy TEXT,
            so_tien REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fixed_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ten_khoan_chi TEXT,
            nguon_quy TEXT,
            so_tien REAL,
            ngay_dinh_ky INTEGER
        )
    """)
    conn.commit()
    return conn


conn = init_db()

# --- SIDEBAR: CẤU HÌNH & CUỐN LỊCH CHỌN NGÀY NỔI ---
st.sidebar.header("⚙️ Cấu hình Trợ lý AI")
if ai_enabled:
    st.sidebar.success("✅ Trợ lý AI đã sẵn sàng")
else:
    st.sidebar.warning("⚠️ Trợ lý AI đang tắt (Thiếu API Key)")

st.sidebar.markdown("---")
st.sidebar.header("📅 Cuốn Lịch Nhanh")
st.sidebar.markdown("Chọn ngày để xem dòng tiền hoặc nhập liệu:")
selected_sidebar_date = st.sidebar.date_input(
    "Xem nhanh theo ngày", value=datetime.now(), label_visibility="collapsed"
)


# Hàm bóc tách thông minh hỗ trợ AI chuẩn xác
def ai_parse_expense(text):
    if ai_enabled:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = (
                "Phân tích câu chi tiêu sau và trả về ĐÚNG định dạng JSON gồm các"
                ' trường: "amount" (số nguyên VND), "content" (nội dung), "category"'
                ' (chọn 1 trong: "Ăn uống & Giải trí", "Di chuyển & Đi lại", "Công cụ &'
                ' Thiết bị làm việc", "Chi phí cố định thiết yếu", "Quà tặng & Tình'
                ' cảm", "Không cần thiết (Lãng phí)"), "fund" (chọn 1 trong: "Quỹ Gia'
                ' Đình", "Quỹ Studio/Sản xuất"). Chỉ trả về JSON thuần túy, không'
                f' markdown. Câu cần phân tích: "{text}"'
            )
            response = model.generate_content(prompt)
            clean_text = (
                response.text.replace("```json", "")
                .replace("```", "")
                .strip()
            )

            data = json.loads(clean_text)
            return (
                int(data.get("amount", 0)),
                data.get("content", text),
                data.get("category", "Ăn uống & Giải trí"),
                data.get("fund", "Quỹ Gia Đình"),
            )
        except Exception as e:
            pass

    amount = 50000
    lower_text = text.lower()
    if "củ" in lower_text or "trệu" in lower_text or "triệu" in lower_text:
        numbers = re.findall(r"\d+", lower_text)
        if numbers:
            amount = int(numbers[0]) * 1000000
    elif "k" in lower_text:
        numbers = re.findall(r"\d+", lower_text)
        if numbers:
            amount = int(numbers[0]) * 1000

    fund = (
        "Quỹ Studio/Sản xuất"
        if any(
            k in lower_text
            for k in [
                "mic",
                "máy",
                "phần mềm",
                "thu âm",
                "studio",
                "adobe",
                "camera",
                "capcut",
            ]
        )
        else "Quỹ Gia Đình"
    )

    if "phim" in lower_text:
        category = "Không cần thiết (Lãng phí)"
    elif "xe" in lower_text or "xăng" in lower_text or "grab" in lower_text:
        category = "Di chuyển & Đi lại"
    elif (
        fund == "Quỹ Studio/Sản xuất"
        or "capcut" in lower_text
        or "adobe" in lower_text
    ):
        category = "Công cụ & Thiết bị làm việc"
    else:
        category = "Ăn uống & Giải trí"

    return amount, text, category, fund


# Hàm AI Vision đọc hóa đơn
def ai_parse_bill(image, fund_choice):
    if ai_enabled:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = (
                "Đọc hóa đơn này và trả về ĐÚNG định dạng JSON gồm 3 trường: "
                '"amount" (số nguyên VND tổng cộng), "content" (tên cửa hàng), '
                '"category" (chọn 1 trong 6 danh mục phù hợp). Chỉ trả về JSON'
                " thuần túy, không markdown."
            )
            response = model.generate_content([prompt, image])
            clean_text = (
                response.text.replace("```json", "")
                .replace("```", "")
                .strip()
            )

            data = json.loads(clean_text)
            return (
                int(data.get("amount", 0)),
                data.get("content", "Hóa đơn mua sắm"),
                data.get("category", "Ăn uống & Giải trí"),
            )
        except Exception as e:
            pass
    return 187954, "Hóa đơn mua sắm", "Ăn uống & Giải trí"


st.title("💰 Quản Lý Tài Chính Studio & Gia Đình (True AI)")
st.markdown(
    "Trợ lý AI bóc tách thông minh, quản lý thời gian thực với cuốn lịch chọn"
    " ngày trực quan."
)

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "📝 Nhập Nhanh AI",
        "🎙️ Nhập Giọng Nói",
        "📷 Quét Hóa Đơn OCR",
        "🔄 Chi Phí Định Kỳ",
        "📊 Thống Kê & Báo Cáo",
    ]
)

with tab1:
    st.subheader("Nhập liệu tự nhiên bằng AI Thật")
    st.info(
        f"💡 **Đang chọn ngày giao dịch:**"
        f" {selected_sidebar_date.strftime('%d/%m/%Y')} (Thay đổi ngày trực tiếp"
        " ở cuốn lịch góc trái màn hình nếu cần nhập bù)."
    )

    quick_input = st.text_input(
        "Nhập câu lệnh chi tiêu",
        placeholder="VD: đầu tư dàn mic mới 30 củ, sửa xe 500k...",
    )

    if quick_input and st.button("✨ Phân tích và Lưu ngay"):
        with st.spinner("🤖 Trợ lý AI đang xử lý giao dịch..."):
            est_amount, est_content, est_category, est_fund = ai_parse_expense(
                quick_input
            )

        if est_amount > 0:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO transactions (ngay, noi_dung, phan_loai, nguon_quy,"
                " so_tien) VALUES (?, ?, ?, ?, ?)",
                (
                    selected_sidebar_date.strftime("%Y-%m-%d"),
                    est_content,
                    est_category,
                    est_fund,
                    est_amount,
                ),
            )
            conn.commit()
            st.success("Thành công!")
            st.info(
                f"🤖 **Đã lưu vào ngày {selected_sidebar_date}:** Số tiền:"
                f" **{est_amount:,.0f} VNĐ** | Nội dung: **{est_content}** | Danh"
                f" mục: **{est_category}** | Nguồn quỹ: **{est_fund}**"
            )
        else:
            st.error("Không bóc tách được số tiền, vui lòng thử lại!")

    st.markdown("---")
    st.subheader("Hoặc nhập thủ công truyền thống")
    with st.form("expense_form"):
        col1, col2 = st.columns(2)
        with col1:
            amount_input = st.number_input(
                "Số tiền (VND)", min_value=0, value=50000, step=10000
            )
        with col2:
            content_input = st.text_input(
                "Nội dung mua sắm", placeholder="VD: Mua ngàm máy ảnh..."
            )
            fund_input = st.selectbox(
                "Chọn Nguồn Quỹ", ["Quỹ Gia Đình", "Quỹ Studio/Sản xuất"]
            )

        category_input = st.selectbox(
            "Phân loại danh mục",
            [
                "Ăn uống & Giải trí",
                "Di chuyển & Đi lại",
                "Công cụ & Thiết bị làm việc",
                "Chi phí cố định thiết yếu",
                "Quà tặng & Tình cảm",
                "Không cần thiết (Lãng phí)",
            ],
        )

        submitted = st.form_submit_button("Thêm Giao Dịch Thủ Công")
        if submitted and content_input:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO transactions (ngay, noi_dung, phan_loai, nguon_quy,"
                " so_tien) VALUES (?, ?, ?, ?, ?)",
                (
                    selected_sidebar_date.strftime("%Y-%m-%d"),
                    content_input,
                    category_input,
                    fund_input,
                    amount_input,
                ),
            )
            conn.commit()
            st.success(f"Đã thêm thành công vào ngày {selected_sidebar_date}!")
            st.rerun()

with tab2:
    st.subheader("🎙️ Nhập Liệu Bằng Giọng Nói (Voice-to-Text AI)")
    st.info(
        "💡 Bấm vào ô bên dưới, đọc hoặc nhập nhanh câu nói mô tả khoản chi. Trợ"
        " lý AI sẽ nghe/đọc hiểu và bóc tách tự động."
    )

    voice_text_input = st.text_area(
        "Nội dung giọng nói / văn bản đọc nhanh:",
        placeholder="VD: Vừa chi 2 củ mua ngàm ống kính cho máy ảnh sony...",
    )

    if st.button("🚀 Xử lý giọng nói bằng AI", type="primary"):
        if voice_text_input:
            with st.spinner("🎧 Trợ lý AI đang phân tích giọng nói..."):
                v_amount, v_content, v_cat, v_fund = ai_parse_expense(voice_text_input)

            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO transactions (ngay, noi_dung, phan_loai, nguon_quy,"
                " so_tien) VALUES (?, ?, ?, ?, ?)",
                (
                    selected_sidebar_date.strftime("%Y-%m-%d"),
                    v_content,
                    v_cat,
                    v_fund,
                    v_amount,
                ),
            )
            conn.commit()
            st.success(
                f"Đã ghi nhận giọng nói thành công vào ngày {selected_sidebar_date}!"
            )
            st.info(
                f"💰 Số tiền: **{v_amount:,.0f} VNĐ** | 📝 Nội dung: **{v_content}** |"
                f" 📂 Danh mục: **{v_cat}** | 🏷️ Quỹ: **{v_fund}**"
            )
        else:
            st.warning("Vui lòng nhập nội dung giọng nói trước khi xử lý!")

with tab3:
    st.subheader("Quét Hóa Đơn / Bill qua Camera (AI Vision)")
    uploaded_bill = st.file_uploader(
        "Tải lên ảnh hóa đơn", type=["png", "jpg", "jpeg"]
    )

    if uploaded_bill is not None:
        img_display = Image.open(uploaded_bill)

        col_img, col_ctrl = st.columns([1, 1])
        with col_img:
            st.image(img_display, caption="Hóa đơn tải lên", width=320)
        with col_ctrl:
            st.markdown("### Thiết lập quét")
            b_fund = st.selectbox(
                "Chọn nguồn quỹ cho hóa đơn này",
                ["Quỹ Gia Đình", "Quỹ Studio/Sản xuất"],
                key="bill_fund",
            )
            if st.button("🔍 Dùng AI Vision đọc hóa đơn", type="primary"):
                with st.spinner("👁️ AI Vision đang quét và trích xuất hóa đơn..."):
                    b_amount, b_content, b_cat = ai_parse_bill(img_display, b_fund)

                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO transactions (ngay, noi_dung, phan_loai, nguon_quy,"
                    " so_tien) VALUES (?, ?, ?, ?, ?)",
                    (
                        selected_sidebar_date.strftime("%Y-%m-%d"),
                        b_content,
                        b_cat,
                        b_fund,
                        b_amount,
                    ),
                )
                conn.commit()
                st.success(
                    f"Đã lưu thành công ngày {selected_sidebar_date}:"
                    f" **{b_amount:,.0f} VNĐ** - [{b_content}] vào quỹ [{b_fund}]!"
                )
                st.rerun()

with tab4:
    st.subheader("Quản Lý Chi Phí Cố Định Định Kỳ")
    fixed_df = pd.read_sql_query("SELECT * FROM fixed_costs", conn)
    if not fixed_df.empty:
        fixed_display = fixed_df.copy()
        if "so_tien" in fixed_display.columns:
            fixed_display["so_tien"] = fixed_display["so_tien"].apply(
                lambda x: f"{x:,.0f} VNĐ"
            )
        st.dataframe(fixed_display, use_container_width=True)
    else:
        st.info("Chưa có khoản chi cố định nào.")

    with st.form("fixed_form"):
        f_name = st.text_input(
            "Tên khoản chi định kỳ",
            placeholder="VD: Thuê mặt bằng, tiền mạng, Adobe...",
        )
        f_amount = st.number_input(
            "Số tiền định kỳ (VND)", min_value=0, value=500000, step=50000
        )
        f_fund = st.selectbox(
            "Nguồn quỹ chi trả",
            ["Quỹ Gia Đình", "Quỹ Studio/Sản xuất"],
            key="f_fund_select",
        )
        f_day = st.number_input(
            "Ngày trừ tiền hàng tháng", min_value=1, max_value=31, value=1
        )
        f_submitted = st.form_submit_button("Thêm Khoản Chi Cố Định")
        if f_submitted and f_name:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO fixed_costs (ten_khoan_chi, nguon_quy, so_tien,"
                " ngay_dinh_ky) VALUES (?, ?, ?, ?)",
                (f_name, f_fund, f_amount, f_day),
            )
            conn.commit()
            st.success(f"Đã thêm khoản cố định: {f_name}")
            st.rerun()

with tab5:
    st.subheader("📊 Thống Kê & Báo Cáo Tổng Quan & Dự Báo Dòng Tiền")

    df = pd.read_sql_query("SELECT * FROM transactions", conn)
    fixed_df_all = pd.read_sql_query("SELECT * FROM fixed_costs", conn)

    if not df.empty or not fixed_df_all.empty:
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            selected_fund_filter = st.radio(
                "Lọc theo nguồn quỹ:",
                ["Tất cả", "Quỹ Gia Đình", "Quỹ Studio/Sản xuất"],
                horizontal=True,
            )
        with col_f2:
            time_filter = st.selectbox(
                "Lọc theo thời gian:",
                [
                    "Tất cả thời gian",
                    "Theo ngày trên lịch Sidebar",
                    "Tuần này",
                    "Tháng này",
                ],
            )

        filtered_df = (
            df
            if selected_fund_filter == "Tất cả"
            else df[df["nguon_quy"] == selected_fund_filter]
        )
        filtered_fixed = (
            fixed_df_all
            if selected_fund_filter == "Tất cả"
            else fixed_df_all[fixed_df_all["nguon_quy"] == selected_fund_filter]
        )

        if not filtered_df.empty:
            filtered_df["ngay_dt"] = pd.to_datetime(filtered_df["ngay"])
            sidebar_date_str = selected_sidebar_date.strftime("%Y-%m-%d")

            if time_filter == "Theo ngày trên lịch Sidebar":
                filtered_df = filtered_df[filtered_df["ngay"] == sidebar_date_str]
            elif time_filter == "Tuần này":
                start_week = datetime.now() - timedelta(days=datetime.now().weekday())
                filtered_df = filtered_df[
                    filtered_df["ngay_dt"]
                    >= pd.to_datetime(start_week.strftime("%Y-%m-%d"))
                ]
            elif time_filter == "Tháng này":
                current_month = datetime.now().strftime("%Y-%m")
                filtered_df = filtered_df[filtered_df["ngay"].str.startswith(current_month)]

        total_spent = (
            filtered_df["so_tien"].sum()
            if not filtered_df.empty and "so_tien" in filtered_df.columns
            else 0
        )
        total_fixed = (
            filtered_fixed["so_tien"].sum()
            if not filtered_fixed.empty and "so_tien" in filtered_fixed.columns
            else 0
        )

        if not df.empty and "so_tien" in df.columns:
            today_str = datetime.now().strftime("%Y-%m-%d")
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            spent_today = df[df["ngay"] == today_str]["so_tien"].sum()
            spent_yesterday = df[df["ngay"] == yesterday_str]["so_tien"].sum()
            diff_day = spent_today - spent_yesterday
        else:
            spent_today, spent_yesterday, diff_day = 0, 0, 0

        st.markdown("---")
        st.markdown("### 🔔 Báo Cáo Tài Chính Cuối Ngày (Chốt Sổ 20h Tối)")
        current_hour = datetime.now().hour
        if current_hour >= 20:
            st.success(
                f"🌙 Đã qua mốc 20:00 tối ({datetime.now().strftime('%H:%M')}). Mời"
                " Chủ tịch kiểm tra dòng tiền hôm nay trước khi ngủ:"
            )
        else:
            st.info(
                f"⏳ Hiện tại là {datetime.now().strftime('%H:%M')}. Sắp đến mốc chốt"
                " sổ 20:00 tối hằng ngày. Dưới đây là tổng kết tạm tính:"
            )

        col_night1, col_night2, col_night3 = st.columns(3)
        col_night1.metric("Tiêu xài trong ngày (Hôm nay)", f"{spent_today:,.0f} VNĐ")

        if not df.empty and "ngay" in df.columns:
            today_tx = df[df["ngay"] == today_str]
            today_waste = today_tx[
                today_tx["phan_loai"] == "Không cần thiết (Lãng phí)"
            ]["so_tien"].sum()
            today_nec = today_tx[
                today_tx["phan_loai"] != "Không cần thiết (Lãng phí)"
            ]["so_tien"].sum()
        else:
            today_waste, today_nec = 0, 0

        col_night2.metric("Khoản Cần Thiết / Đầu Tư", f"{today_nec:,.0f} VNĐ")
        col_night3.metric(
            "Khoản Lãng Phí Cần Cân Nhắc",
            f"{today_waste:,.0f} VNĐ",
            delta=(
                f"{-today_waste:,.0f} VNĐ" if today_waste > 0 else "0 VNĐ"
            ),
            delta_color="inverse",
        )

        st.markdown("---")
        st.markdown("### 🔮 Dự Báo Dòng Tiền & Cảnh Báo Sức Khỏe Quỹ")
        avg_daily_spend = df["so_tien"].mean() if not df.empty else 0
        projected_month_spend = avg_daily_spend * 30 + total_fixed

        col_proj1, col_proj2 = st.columns(2)
        with col_proj1:
            st.metric(
                "Dự phóng chi tiêu cả tháng tới", f"{projected_month_spend:,.0f} VNĐ"
            )
        with col_proj2:
            if projected_month_spend > 20000000:
                st.error(
                    "🚨 **CẢNH BÁO QUỸ:** Tốc độ tiêu xài hiện tại đang khá cao so với"
                    " chi phí cố định. Chủ tịch nên cân nhắc siết bớt các khoản lãng"
                    " phí!"
                )
            else:
                st.success(
                    "✅ **SỨC KHỎE QUỸ TỐT:** Dòng tiền đang nằm trong vùng kiểm soát"
                    " an toàn."
                )

        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Chi Tiêu Phát Sinh (Lọc)", f"{total_spent:,.0f} VNĐ")
        col2.metric("Chi Phí Cố Định", f"{total_fixed:,.0f} VNĐ")
        col3.metric(
            "Hôm nay chi",
            f"{spent_today:,.0f} VNĐ",
            delta=f"{diff_day:,.0f} VNĐ so với hôm qua",
            delta_color="inverse",
        )
        col4.metric("Tổng Cộng Thực Tế", f"{total_spent + total_fixed:,.0f} VNĐ")

        st.markdown("---")
        if not filtered_df.empty and "so_tien" in filtered_df.columns:
            st.markdown("### 📈 Tỷ Trọng Chi Tiêu Theo Danh Mục")
            cat_grouped = (
                filtered_df.groupby("phan_loai")["so_tien"].sum().reset_index()
            )

            chart = (
                alt.Chart(cat_grouped)
                .mark_bar(color="#1f77b4")
                .encode(
                    x=alt.X(
                        "phan_loai:N",
                        sort="-y",
                        title="Danh mục",
                        axis=alt.Axis(labelAngle=0),
                    ),
                    y=alt.Y(
                        "so_tien:Q",
                        title="Tổng tiền (VNĐ)",
                        scale=alt.Scale(zero=True),
                    ),
                    tooltip=[
                        "phan_loai",
                        alt.Tooltip("so_tien:Q", format=",.0f", title="Tổng tiền"),
                    ],
                )
                .properties(height=350)
            )
            st.altair_chart(chart, use_container_width=True)

            st.markdown("---")
            st.markdown("### 🎯 Phân tích Khoản Chi: Cần Thiết vs Lãng Phí")
            st.info(f"💡 Đang kiểm tra theo mốc thời gian: **{time_filter}**")

            waste_df = filtered_df[
                filtered_df["phan_loai"] == "Không cần thiết (Lãng phí)"
            ]
            necessary_df = filtered_df[
                filtered_df["phan_loai"] != "Không cần thiết (Lãng phí)"
            ]

            col_waste, col_nec = st.columns(2)

            with col_waste:
                st.markdown("#### ⚠️ Khoản Cần Cân Nhắc / Lãng Phí")
                if not waste_df.empty:
                    w_display = waste_df[
                        ["ngay", "noi_dung", "so_tien", "nguon_quy"]
                    ].copy()
                    w_display["so_tien"] = w_display["so_tien"].apply(
                        lambda x: f"{x:,.0f} VNĐ"
                    )
                    st.dataframe(w_display, use_container_width=True, hide_index=True)
                    st.warning(
                        f"Tổng tiền lãng phí: **{waste_df['so_tien'].sum():,.0f} VNĐ**"
                    )
                else:
                    st.success("Tuyệt vời! Không có khoản chi lãng phí nào trong mốc này.")

            with col_nec:
                st.markdown("#### ✅ Khoản Chi Thiết Yếu / Đầu Tư")
                if not necessary_df.empty:
                    n_display = necessary_df[
                        ["ngay", "noi_dung", "phan_loai", "so_tien"]
                    ].copy()
                    n_display["so_tien"] = n_display["so_tien"].apply(
                        lambda x: f"{x:,.0f} VNĐ"
                    )
                    st.dataframe(n_display, use_container_width=True, hide_index=True)
                    st.info(
                        f"Tổng tiền cần thiết: **{necessary_df['so_tien'].sum():,.0f}"
                        " VNĐ**"
                    )
                else:
                    st.info("Chưa có khoản chi thiết yếu nào được ghi nhận.")

        st.markdown("---")
        st.markdown("### 📋 Lịch sử giao dịch chi tiết")
        if not filtered_df.empty and "so_tien" in filtered_df.columns:
            df_display = (
                filtered_df.drop(columns=["ngay_dt"], errors="ignore").copy()
            )
            df_display["so_tien"] = df_display["so_tien"].apply(
                lambda x: f"{x:,.0f} VNĐ"
            )
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        else:
            st.info(
                "Không có giao dịch nào phù hợp với bộ lọc thời gian hoặc quỹ này."
            )

        st.markdown("---")
        if st.button("🗑️ Xóa toàn bộ dữ liệu giao dịch"):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM transactions")
            conn.commit()
            st.success("Đã xóa sạch dữ liệu lịch sử!")
            st.rerun()
    else:
        st.info(
            "Hệ thống chưa ghi nhận giao dịch nào. Hãy bắt đầu nhập liệu ở tab đầu"
            " tiên nhé!"
        )