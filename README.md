# Tải âm thanh TikTok & Facebook

Website tiếng Việt dùng chung trên iPhone, Android và máy tính: dán link video/Reel công khai → Lấy âm thanh → Tải MP3. Giữ nguyên nhạc, lời nói và tiếng động. Không bắt buộc cài PWA.

Ảnh nhận diện do chủ website cung cấp, đã nén bản copy cho web; không dùng ảnh AI. Không yêu cầu mật khẩu/cookie nền tảng, không gửi link sang API tải của bên thứ ba.

## Deploy miễn phí

[Deploy to Render](https://render.com/deploy?repo=https://github.com/huutrana/lay-am-thanh)

1. Chủ website đăng nhập/tạo tài khoản Render và tự hoàn tất xác thực/điều khoản nếu có.
2. Mở Deploy to Render, kiểm tra blueprint render.yaml: Docker, plan free, Singapore, một instance.
3. Tạo dịch vụ, chờ build thành công, mở URL HTTPS onrender.com Render cung cấp.
4. Kiểm tra tải TikTok/Facebook thật trên URL đó. Push GitHub không đồng nghĩa đã deploy.

Render cấp PORT và RENDER_EXTERNAL_HOSTNAME; app tự nhận đúng hostname. Gói free có thể ngủ sau 15 phút không dùng; lần mở đầu có thể cần chờ. Tệp tạm mất khi restart/redeploy. Không ping để né cơ chế ngủ; không tự nâng gói có phí.

Mã nguồn quản lý bằng GitHub như web Lành Mỹ, nhưng **GitHub Pages không chạy Python/FFmpeg**. Vì vậy website này cần backend trên Render; không đưa lên Pages một giao diện thiếu phần xử lý.

## Chạy local

Windows: mở CHAY-UNG-DUNG.cmd, truy cập http://127.0.0.1:8765. Giữ cửa sổ server mở, Ctrl+C để dừng. Trong workspace hiện tại launcher có thể dùng venv riêng ở ../../work/venv.

Máy mới cần Python 3.11+ và FFmpeg/FFprobe trong PATH:

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Linux dùng .venv/bin/python. Localhost chỉ truy cập từ máy đang chạy server.

## Cấu hình

HOST mặc định 127.0.0.1, dùng 0.0.0.0 trên máy chủ. PORT mặc định 8765, Render tự cấp. DATA_DIR chỉ định thư mục tệp tạm (mặc định data). ALLOWED_HOSTS chứa hostname/IP được phép, cách bằng dấu phẩy, không protocol/port. RENDER_EXTERNAL_HOSTNAME do Render cấp được tự thêm vào host tin cậy.

Dockerfile chạy user không đặc quyền, cài FFmpeg, dùng Waitress. Chạy một process/instance vì hàng đợi trong bộ nhớ. Sau reverse proxy, nhiều người có thể dùng chung rate limit; không tự tin tưởng X-Forwarded-For.

## Phạm vi

- TikTok: video chuẩn, vt/vm và /t/ rút gọn. Luôn lấy audio từ luồng video, tránh luồng nhạc riêng khác nội dung video.
- Facebook: Reel, page/videos/id, watch/?v=id, video.php?v=id, share/r hoặc share/v, fb.watch. Dùng curl-cffi kết nối kiểu Chrome. Không hỗ trợ trang tài khoản, nhóm, bài viết thông thường hoặc link cần đăng nhập.
- Một video/lượt, tối đa 10 phút, nguồn 100 MiB, tổng trung gian 200 MiB; MP3 192 kb/s, không tăng chất lượng vượt nguồn.
- Một worker, hai lượt chờ; sáu yêu cầu/phút/IP; dừng toàn bộ tác vụ sau khoảng ba phút, có thể thêm vài giây dọn tiến trình.
- MP3 và trạng thái hết hạn sau 30 phút; tự dọn. sessionStorage giữ mã lượt gần nhất để reload còn khôi phục nút tải.
- Cách lưu phụ thuộc trình duyệt: iPhone thường trong Tệp, Android trong Tệp đã tải xuống. Không tự ghi vào Music.
- Link công khai vẫn có thể bị nền tảng chặn hoặc không có audio; báo lỗi rõ, không tạo tệp giả/rỗng. Cần thử lại trên IP máy chủ sau deploy.
- Manifest/service worker là tùy chọn; chỉ cache giao diện/ảnh nhận diện, không cache API hoặc MP3. Tải luôn cần mạng và backend.

## Kiểm tra

```text
python -W error::ResourceWarning -m unittest discover -s tests -v
node --check static/app.js
node --check static/sw.js
```

Xem KIEM-THU.md cho kết quả thực tế. Không có tài khoản/khóa API bắt buộc trong repository.

Nguồn: [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Render free](https://render.com/docs/free), [Render Docker](https://render.com/docs/docker), [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site).
