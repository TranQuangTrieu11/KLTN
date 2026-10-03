# Ghi chú phát triển chatbot tư vấn mua sắm

Tài liệu này ghi lại các giai đoạn phát triển; các đoạn cũ có thể mô tả phiên bản trước. Hướng dẫn chạy, cấu trúc thư mục và trạng thái hiện tại nằm trong [README.md](README.md). Tên cũ `DE_TAI_BO_SUNG.md` đã đổi thành `PROJECT_NOTES.md`; dữ liệu nằm ở `research/data/`, notebook ở `research/notebooks/`, trang chính là `index.html`.

## Phạm vi đã triển khai trong phiên bản này

- Backend HTTP độc lập, luồng công cụ: tìm/khuyến nghị → lấy review → so sánh khi được yêu cầu → xuất dữ liệu có nguồn. Planner hiện là luật Python, không phải Qwen tự chọn công cụ.
- Bộ lọc bắt buộc cho ngưỡng giá, tiền tệ, sàn và dung lượng GB/TB trong câu hỏi. Không quy đổi tiền tệ ngầm.
- Bộ nhớ hội thoại SQLite theo UUID phiên: giữ truy vấn, danh sách sản phẩm, lịch sử trả lời và nhật ký công cụ qua lần khởi động lại. Hỗ trợ “review sản phẩm số 1”, “sản phẩm thứ hai”, “cái vừa xem”, “so sánh sản phẩm 1 và 2”. “Cái vừa xem” tham chiếu danh sách kết quả trước, chưa theo dõi từng thao tác xem thẻ.
- Knowledge Editing tại tầng truy xuất: bản nháp, kiểm tra thuộc tính/giá trị, lý do và bằng chứng, phiên bản, xem trước thuộc tính, kích hoạt, kiểm tra xung đột, tắt/hoàn tác. Có thể bật lại bản cũ sau khi tắt bản đang hoạt động. Overlay áp dụng trước bộ lọc và xếp hạng, không sửa CSV hoặc trọng số mô hình.
- Trích dẫn mã sản phẩm và review, đánh dấu giá trong tập dữ liệu là giá lịch sử. Grounding hiện xuất trực tiếp các trường từ dữ liệu; chưa kiểm định ngữ nghĩa câu trả lời LLM.
- Theo dõi độ trễ từng công cụ, lỗi, tổng số lượt chat, độ trễ trung bình và p95 của tối đa 500 lượt gần nhất.
- Trang quản trị `/admin.html`, API ghi yêu cầu Bearer token; server chỉ phục vụ hai trang công khai, không phục vụ trực tiếp CSV/SQLite.

## Khởi chạy và sử dụng

Chạy `python agent_server.py` rồi mở `http://127.0.0.1:8765/`, hoặc dùng file BAT có sẵn (cổng 8780).

Để dùng quản trị, đặt biến môi trường trong PowerShell trước khi chạy:

```powershell
$env:AGENT_ADMIN_TOKEN = 'thay-bang-token-rieng-cua-ban'
python agent_server.py
```

Mở `/admin.html`, nhập cùng token. Token chỉ giữ trong ô nhập của trang. Sao chép mã sản phẩm từ phần nguồn dưới câu trả lời; tạo bản nháp → xem trước → kích hoạt → hỏi lại trong chatbot → hoàn tác → hỏi lại. Ghi rõ nguồn dữ liệu hoặc “dữ liệu giả lập” trong bằng chứng. Xem trước hiện là trước/sau thuộc tính; chưa sinh hai câu trả lời Qwen.

Chat gửi `POST /api/chat` với `{"message":"microSD 64GB dưới 20 USD và so sánh đánh giá","session_id":"UUID"}`. Không gửi session_id thì server tạo phiên mới. Xem lịch sử qua `GET /api/history?session_id=UUID`. Mỗi tab sử dụng sessionStorage giữ ID phiên khi tải lại trang.

API quản trị: `GET /api/admin/edits`, `GET /api/admin/metrics`; `POST /api/admin/edits` nhận product_id, field, new_value, reason, evidence; `POST /api/admin/preview`, `/activate`, `/rollback` nhận edit_id. Gửi `Authorization: Bearer TOKEN`.

Dữ liệu vận hành mới nằm trong `agent_state.sqlite3`. `knowledge_edits.json` của thí nghiệm notebook được giữ nguyên, chưa nhập vào registry mới. `chat_history.json` cũ cũng được giữ nguyên, lịch sử mới được lưu theo phiên trong SQLite.

## Phần cần tích hợp tiếp và trình bày đúng trong báo cáo

| Thành phần | Hiện trạng server | Công việc tiếp theo |
|---|---|---|
| Qwen LLM | Chưa được nạp/gọi | Adapter inference, schema tool calling, vòng lặp có giới hạn bước và kiểm định câu trả lời |
| RAG FAISS | Artifact có trong dữ liệu; server tìm bằng từ khóa | Nạp encoder/index tương thích, ánh xạ ID, reranking và đánh giá retrieval |
| BPR | Artifact có trong dữ liệu; chưa chấm điểm tại server | Kiểm tra định dạng model/mappings, gắn user_id đã xác thực, hybrid ranking và cold start |
| Tài khoản | Phiên UUID, chưa đăng nhập | Xác thực người dùng, phân quyền lịch sử, hồ sơ, yêu thích |
| Grounding | Dữ liệu cấu trúc và mã nguồn | Kiểm định claim theo bằng chứng cho câu trả lời LLM, đo fallback |
| Triển khai | Server Python cục bộ | API production, TLS, sao lưu DB, cập nhật dữ liệu và artifact |

Không coi UUID phiên là tài khoản đăng nhập. Các chỉ số vận hành không phải kết quả Recall/NDCG hoặc chứng minh hiệu quả BPR. Các nhãn kiến trúc và mô phỏng có sẵn trên giao diện không phải bằng chứng các mô hình đang chạy.

## Kịch bản đánh giá đề tài

1. Cùng truy vấn với các mức giá và tiền tệ khác nhau: kiểm tra mọi kết quả đáp ứng bộ lọc.
2. Hai phiên riêng: phiên A tìm sản phẩm và hỏi review số 1; phiên B hỏi số 1 trước khi tìm phải được yêu cầu làm rõ.
3. Knowledge Editing giả lập: đổi giá sản phẩm để vượt ngân sách; khi kích hoạt sản phẩm biến mất khỏi kết quả, khi hoàn tác xuất hiện lại. Kiểm tra sản phẩm khác không thay đổi.
4. Một yêu cầu có tìm kiếm, review, so sánh: kiểm tra tool_trace, citations và bảng so sánh.
5. Công cụ review lỗi: ghi lỗi, trả thông báo có kiểm soát và giữ phiên.
6. Khi đã nối mô hình: đo Recall@K/NDCG@K cho retrieval, Recall@K/NDCG@K cho recommendation, độ chính xác chọn tool, grounding và tỷ lệ fallback. So sánh ablation lexical/FAISS, BPR/hybrid, bật/tắt overlay trên cùng tập kiểm thử.

Kiểm thử tự động: `python -m unittest -v test_agent_extensions.py`. Fixture là dữ liệu giả lập, không sửa dataset thật và không chứng minh hiệu năng mô hình.

## Cập nhật giao diện và chức năng theo yêu cầu

Giao diện khách hàng đã thay bằng bố cục đơn sắc, không icon: hội thoại là nội dung chính; tài khoản và lịch sử nằm ở cột phụ. Chi tiết sản phẩm, review và nhật ký công cụ mở theo yêu cầu. Trang quản trị dùng cùng phong cách.

Đã bổ sung:
- Đăng ký, đăng nhập, đăng xuất; mật khẩu băm PBKDF2 SHA-256 với salt riêng, token hết hạn sau 24 giờ.
- Hồ sơ tên và tùy chọn cá nhân; lưu/bỏ sản phẩm yêu thích trong SQLite.
- Lịch sử hội thoại của tài khoản, tạo và chọn phiên; kiểm tra quyền sở hữu trên API chat và lịch sử. Phiên khách vẫn dùng UUID như trước.
- Xem chi tiết, ảnh và review nguồn; yêu cầu sản phẩm tương tự từ thẻ sản phẩm.
- Knowledge Editing xem trước câu trả lời có căn cứ trước/sau, bằng chứng và phiên bản. Đây là câu trả lời dựng từ trường dữ liệu, không phải Qwen sinh.
- Quản trị tìm/xem sản phẩm và review; xem 50 nhật ký Agent gần nhất, độ trễ và lỗi.
- Fallback review: lỗi công cụ review không làm mất kết quả sản phẩm; ghi fallback_reason và tool_trace.

Kiểm thử cập nhật: `python -m unittest -v test_agent_extensions.py`: 7 kiểm thử đạt với dữ liệu giả lập.

Các giới hạn còn cần hoàn thiện để đáp ứng toàn bộ đề tài:
- Chưa chạy Qwen tool calling, FAISS retrieval/reranking hoặc BPR ở server. Máy hiện thiếu faiss, sentence-transformers và implicit. Không đánh dấu các mục này đã hoàn thành.
- Tùy chọn hồ sơ được lưu nhưng chưa tham gia cá nhân hóa. Tài khoản mới chưa ánh xạ với user_id trong mô hình BPR đã huấn luyện.
- Review hiện là trích đoạn có mã nguồn, chưa có tóm tắt ngữ nghĩa bằng LLM.
- Quản trị chưa thêm sản phẩm mới; sửa các trường hỗ trợ bằng overlay Knowledge Editing. Chưa có quy trình kiểm duyệt review.
- Chưa có chuỗi giá theo thời gian hoặc quy cách đóng gói chuẩn hóa. Giá hiện là giá ghi nhận trong dataset.
- Chưa kiểm thử giao diện tự động trên trình duyệt hay đánh giá chất lượng mô hình.

API tài khoản: POST `/api/account/register`, `/login` nhận email/password; `/logout`, `/session`, `/profile`, `/favorite` cần Bearer token. GET `/api/account` trả hồ sơ, yêu thích và các phiên của tài khoản. Khi đăng nhập, dùng session_id server trả về để tránh nhập lịch sử khách vào tài khoản.

## Cập nhật sửa lỗi trải nghiệm mua sắm

- Khung chat lớn theo chiều cao màn hình, bong bóng người dùng/trợ lý, nền kem và xanh sage nhẹ. Tài khoản chuyển vào hộp thoại để dành diện tích cho trò chuyện. Enter gửi, Shift+Enter xuống dòng.
- Tab Tìm sản phẩm và Xem đánh giá dùng API công khai `/api/search`, không cần token quản trị; tối đa 5 sản phẩm mỗi lần.
- Nút tương tự gửi product_id cụ thể, loại chính sản phẩm gốc khỏi kết quả và giữ điều kiện tìm trước đó. Câu hỏi tương tự chưa xác định mẫu sẽ được hỏi lại.
- Nhớ danh sách và sản phẩm vừa mở chi tiết. Hỏi review một mẫu không làm đổi thứ tự danh sách trước. Hỗ trợ so sánh 1 và 2, giá bao nhiêu, còn loại 32GB/128GB, đổi ngân sách, đổi sàn, rẻ hơn và chọn mẫu tốt nhất trong danh sách vừa xem.
- Không tự bắt buộc tai nghe không dây khi người dùng chỉ hỏi tai nghe. Loại túi hình chuột và phụ kiện chuyển đổi khỏi kết quả chuột/tai nghe.
- Câu trả lời khách hàng không dùng thuật ngữ kỹ thuật; nhật ký vẫn có ở trang quản trị.
- Review CSV được đọc một lần, lưu tối đa 5 nhận xét không rỗng mỗi sản phẩm trong bảng review_samples. Truy cập review sau đó theo khóa sản phẩm, không quét lại 767.179 dòng cho mỗi yêu cầu. Cache được xây lại khi file nguồn thay đổi.
- Bổ sung ảnh/review Tiki theo ID listing từ API Tiki, lưu nguồn và thời điểm lấy trong bảng product_enrichment. Thực hiện nền, cache 24 giờ, không sửa CSV hoặc bịa giá/review. Ảnh Shopee dùng ảnh sẵn có. Amazon thử ảnh từ trang sản phẩm chính xác; nếu bị chặn hoặc không tìm được ảnh thì hiển thị Chưa có ảnh sản phẩm.
- Review Tiki mới được lấy từ listing hiện tại; không được coi là review lịch sử đã có trong dataset gốc. Giá trên giao diện vẫn là giá ghi nhận trong dataset, chưa phải giá hiện tại.

Dữ liệu gốc đã kiểm tra: 121.917 sản phẩm Amazon, 41.575 Tiki, 1.434 Shopee. Toàn bộ giá Shopee trống; dataset review chỉ có Amazon/Shopee. Amazon/Tiki không có ảnh trong products.csv. Không dùng OpenAI để suy đoán giá hoặc tạo đánh giá khách hàng.

Kiểm thử: 12 kiểm thử backend đạt. Kiểm tra trình duyệt bằng test_browser_smoke.py với app chạy cổng 8781 và trình duyệt CDP cổng 9223: chat, tương tự, tìm kiếm, review; không có lỗi JavaScript. Ảnh màn hình lưu app-preview.png. Không xem các kiểm tra luồng này là đánh giá năng lực LLM.
