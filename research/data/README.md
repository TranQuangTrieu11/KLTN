# Dữ liệu chạy ứng dụng

Dataset và các artifact lớn được giữ ngoài Git. Đặt `products.csv` và
`reviews.csv` của bộ dữ liệu dự án vào thư mục này trước khi chạy app.

Hai file này được tạo trong quy trình chuẩn bị và hợp nhất dữ liệu tại
`research/notebooks/`. Có thể dùng bản sao từ máy đang phát triển dự án.
Không thay bằng dữ liệu giả nếu cần tái hiện kết quả nghiên cứu.

Cơ sở dữ liệu `agent_state.sqlite3` được tạo khi chạy; tài khoản, lịch sử
hội thoại, bản chỉnh sửa và bộ nhớ đệm ảnh không được đưa lên GitHub.
Sau khi chuẩn bị catalog, chạy `python import_amazon_images.py --all`
để bổ sung lại ảnh Amazon (cần cài `pyarrow` và có kết nối mạng).
