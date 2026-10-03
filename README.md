# Chatbot tư vấn mua sắm

Ứng dụng tiếng Việt giúp tìm sản phẩm trên Amazon, Shopee và Tiki, chọn tối đa 5 sản phẩm phù hợp, đọc đánh giá, so sánh và hỏi tiếp theo ngữ cảnh hội thoại.

## Chạy ứng dụng

Yêu cầu **Python 3.10 trở lên**. Backend dùng thư viện chuẩn Python, không cần cài thư viện để chạy các chức năng hiện tại.

Nếu tải từ GitHub, chuẩn bị `research/data/products.csv` và `research/data/reviews.csv` trước theo [hướng dẫn dữ liệu](research/data/README.md). Dataset lớn, cơ sở dữ liệu tài khoản/cache và lịch sử chat riêng không được đưa lên repository. Ảnh Amazon cần được nhập lại bằng lệnh ở phần bên dưới.

Trên Windows, mở **`start_local.bat`**, rồi truy cập:

**http://127.0.0.1:8781/**

Hoặc chạy trong thư mục dự án:

```powershell
python agent_server.py
```

Chờ dữ liệu nạp xong trước khi tìm kiếm. Lần chạy đầu cần chuẩn bị bộ nhớ đệm review; những lần sau dùng bộ nhớ đệm đã lưu. Nhấn **Ctrl+F5** nếu trình duyệt còn hiển thị giao diện cũ. Dừng app bằng **Ctrl+C** trong cửa sổ chạy server.

Để test từ thiết bị cùng mạng, dùng `start_lan.bat`. Server in địa chỉ LAN khi khởi chạy. Đừng chạy đồng thời hai file BAT trên cùng cổng.

## Cách sử dụng

- **Trò chuyện:** nhập loại sản phẩm, ngân sách, sàn hoặc thương hiệu. Enter gửi; Shift+Enter xuống dòng.
- **Hỏi tiếp:** “review sản phẩm số 2”, “so sánh 1 và 2”, “còn loại 128GB”, “dưới 500k”, “chỉ lấy Tiki”.
- **Sản phẩm tương tự:** bấm dưới mẫu cần tham chiếu. Kết quả không gồm mẫu gốc.
- **Tìm sản phẩm / Xem đánh giá:** tìm kiếm độc lập, không cần đăng nhập.
- **Tài khoản:** đăng ký với mật khẩu ít nhất 10 ký tự để lưu hội thoại, hồ sơ và sản phẩm yêu thích.

## Quản trị và Knowledge Editing

Đặt token riêng trước khi chạy server:

```powershell
$env:AGENT_ADMIN_TOKEN = 'thay-bang-token-rieng'
python agent_server.py
```

Mở **http://127.0.0.1:8781/admin.html**, nhập cùng token rồi tải dữ liệu. Trang quản trị cho phép xem sản phẩm/review, nhật ký và thống kê; tạo bản chỉnh sửa, xem trước kết quả trước/sau, kích hoạt hoặc hoàn tác.

Bản chỉnh sửa áp dụng khi truy xuất, không sửa CSV gốc hoặc trọng số mô hình. Giá trị mới cần lý do và nguồn bằng chứng. Với thử nghiệm, ghi rõ **dữ liệu giả lập**.

## Cấu trúc dự án

```text
index.html                  Trang khách hàng
admin.html                  Trang quản trị
app.css / app.js            Giao diện và thao tác khách hàng
agent_server.py             HTTP server, tìm kiếm và đọc dữ liệu
agent_extensions.py         Ngữ cảnh, hội thoại, chỉnh sửa và thống kê
conversation_context.py     Hiểu câu hỏi nối tiếp và thay bộ lọc
customer_accounts.py        Tài khoản, hồ sơ và yêu thích
product_enrichment.py       Bổ sung ảnh/review có nguồn
agent_learning_rules.json   Quy tắc nhận biết nhóm sản phẩm
agent_state.sqlite3         Tài khoản, hội thoại, chỉnh sửa và cache
chat_history.json           Lịch sử cũ được giữ để tham khảo
research/data/              Dataset và artifact thí nghiệm
research/notebooks/         Các notebook của đề tài
PROJECT_NOTES.md            Ghi chú quá trình phát triển
test_agent_extensions.py    Kiểm thử backend
test_browser_smoke.py       Kiểm tra thao tác trên trình duyệt
start_local.bat             Chạy trên máy cá nhân
start_lan.bat               Chạy để test trong mạng LAN
.runtime/                  Log và ảnh kiểm tra tạm
```

Không xoá `agent_state.sqlite3` nếu cần giữ tài khoản, hội thoại và lịch sử chỉnh sửa. Sao lưu file này cùng `research/data/` khi sao lưu dự án. Log và ảnh trong `.runtime/` có thể dọn sau khi dừng các tiến trình đang sử dụng chúng.

## Dữ liệu và giới hạn hiện tại

Dữ liệu gốc gồm **164.926 sản phẩm**: 121.917 Amazon, 41.575 Tiki và 1.434 Shopee.

- Giá hiển thị là giá ghi nhận trong dataset, không phải cam kết giá bán hiện tại.
- Dataset gốc thiếu toàn bộ giá Shopee và review Tiki. Không tự điền giá hoặc tạo đánh giá giả.
- Ảnh/review Tiki được bổ sung theo mã sản phẩm từ nguồn Tiki khi truy cập được, lưu nguồn và thời điểm lấy. Đây là thông tin của trang bán hiện tại, không phải review lịch sử của dataset.
- Shopee dùng ảnh có sẵn. Amazon ưu tiên ảnh có nguồn từ metadata gốc, khớp chính xác ASIN; nếu không có ảnh phù hợp thì ghi rõ chưa có ảnh.
- Tìm kiếm và hội thoại hiện dùng xử lý Python. Qwen, FAISS và BPR có phần thí nghiệm/artifact nhưng **chưa được nối để chạy trong server**. Hồ sơ sở thích được lưu, chưa dùng để cá nhân hoá bằng BPR.
- Chưa có thêm sản phẩm mới, kiểm duyệt review, chuỗi lịch sử giá hoặc quy cách đóng gói chuẩn hoá.

API key OpenAI không tự bổ sung giá và review còn thiếu; cần nguồn dữ liệu thật của nơi bán.

### Bổ sung ảnh Amazon và giá có nguồn

`import_amazon_images.py` đọc cột ASIN/ảnh của metadata gốc [Amazon Reviews 2023](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/tree/main/raw_meta_Electronics) qua HTTP range, không tải toàn bộ các cột dữ liệu. Cần `pyarrow` và kết nối mạng:

```powershell
python import_amazon_images.py B0C1H1Q3C1 B07LG5WBTS
python import_amazon_images.py --all
```

Giá Shopee không có trong nguồn gốc. Khi có file giá từ shop, dùng CSV gồm các cột `product_id,price,currency,source_url,recorded_at`; mã sản phẩm phải khớp catalog, giá phải dương, tiền tệ USD/VND, nguồn là URL và thời điểm là ISO 8601 kèm múi giờ. Kiểm tra trước rồi nhập:

```powershell
python import_product_prices.py prices.csv --check
python import_product_prices.py prices.csv
```

Giá được lưu thành các phiên bản Knowledge Editing có nguồn, không sửa CSV gốc. Giao dịch nhập được hoàn tác toàn bộ nếu xảy ra xung đột. Tính hợp lệ của file không đồng nghĩa đã xác minh nội dung trang nguồn; người cung cấp file chịu trách nhiệm đối chiếu giá và đúng sản phẩm.

Câu chọn mẫu tốt nhất trong danh sách trước không chạy tìm kiếm mới. Khi không có kết quả, điều kiện tìm mới vẫn được giữ cho câu nối tiếp, thay vì quay về ngân sách cũ. Đây là xử lý các dạng hội thoại có kiểm thử, chưa phải khả năng hiểu mọi câu hỏi tự do bằng LLM.

Lần bổ sung ngày 03/10/2026: đã có ảnh metadata khớp ASIN cho **121.902/121.917 sản phẩm Amazon**; 15 mã không tìm được ảnh trong nguồn Electronics nên vẫn để trống. Kiểm thử với câu “sản phẩm nào tốt nhất trong 5 cái bạn vừa gửi” và câu giải thích tiếp theo đã đạt; trình duyệt đã kiểm tra ảnh Amazon hiển thị thực tế. **Giá Shopee vẫn chưa được bổ sung**, do chưa có file giá/nguồn shop.

## Kiểm thử

```powershell
python -m unittest -v test_agent_extensions.py
```

Kiểm thử dùng dữ liệu giả lập và SQLite tạm, không sửa dataset gốc. Bộ kiểm thử gồm phân quyền tài khoản, bộ lọc giá/dung lượng, top 5, sản phẩm tương tự, ngữ cảnh, review cache, fallback và Knowledge Editing.

`test_browser_smoke.py` cần thêm gói `websocket-client`, app chạy ở cổng 8781 và trình duyệt có CDP ở cổng 9223. File này kiểm tra thao tác giao diện; không phải điều kiện để chạy app.

Các kiểm thử chức năng không thay thế đánh giá chất lượng mô hình, Recall/NDCG hoặc đánh giá câu trả lời tiếng Việt.
