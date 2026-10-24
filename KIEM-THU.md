# Kiểm chứng bản local — 24/10/2026

## Sửa link chia sẻ từ ứng dụng điện thoại

- Nguyên nhân đã tái hiện: lite.tiktok.com chưa nằm trong hostname cho phép; urllib không mở được Facebook /share/r/ trong khi kết nối Chrome trả redirect sang Reel gốc.
- Đã thêm TikTok Lite và đổi resolver link rút gọn sang curl-cffi Chrome. Không tự theo redirect: kiểm host, DNS public, cùng nền tảng trước từng bước, tối đa 5 bước và chặn vòng lặp; đóng response sau mỗi bước.
- Đã tạo test đỏ trước sửa cho link Lite và Facebook share, sau sửa đạt. Toàn bộ Windows: 32 tests, 31 đạt và 1 test Linux được skip.
- Hai link ứng dụng điện thoại do xếp gửi tải thật local thành công: TikTok Lite 39.312789 giây, 944840 bytes; Facebook share 25.009297 giây, 601905 bytes.
- Kiểm chứng sau deploy được lưu trong bản bàn giao DEPLOY.md ở workspace; không coi kết quả local thay thế kiểm thử online.

## Bản mở rộng TikTok & Facebook

- Test Windows: 26 kiểm tra đạt, thêm URL Facebook/Reel/watch/share, domain giả và chặn redirect đổi nền tảng. Có thêm test Linux kiểm cây tiến trình, chạy riêng trên WSL.
- Đã tải MP3 từ Reel công khai do chủ website gửi: 18.043311 giây, 434512 bytes. Thử thêm video Facebook khác: 44.330667 giây, 1065645 bytes. Không đưa tệp MP3 thử vào mã nguồn.
- Tìm đúng nguyên nhân Facebook lỗi: cần kết nối Chrome qua curl-cffi, tên extractor là facebook:reel. Không nhập cookie hoặc dùng API bên thứ ba.
- Một Reel mẫu khác trả về video không có audio: ứng dụng báo lỗi, không coi là tải thành công.
- Đã nén ảnh nhận diện người dùng cung cấp: WebP chính 48174 bytes, ảnh nhỏ 4244 bytes; icon PNG 192/512 dưới 0.6 MB mỗi tệp. Không chỉnh ảnh gốc.
- Review độc lập không thấy lỗi quan trọng; đã sửa chữ lặp “hoặc Facebook”.
- Cấu hình Render plan free đã có. Chỉ coi deploy hoàn tất khi Render build thành công và URL thật tải MP3 được; đăng nhập tài khoản cần chủ website hoàn tất.

## Bằng chứng bản TikTok ban đầu

- Python venv riêng, Flask 3.1.3, Waitress 3.0.2, yt-dlp[curl-cffi] 2026.10.21, curl-cffi 0.16.3; FFmpeg/FFprobe có sẵn.
- `python -W error::ResourceWarning -m unittest discover -s tests -v`: **22/22 đạt**, exit 0, không ResourceWarning.
- `node --check static/app.js` và `node --check static/sw.js`: exit 0.
- `python -m pip check`: No broken requirements found, exit 0.
- Khởi động bằng chính `CHAY-UNG-DUNG.cmd`: thành công; `/api/health` trả 200, ready=true.
- Trình duyệt Codex, khung hẹp khoảng 304 px: nhập link TikTok, bấm Lấy âm thanh, thấy trạng thái xử lý rồi nút Tải MP3. Bấm nút tải đã thực hiện; kiểm tra HTTP độc lập xác nhận tệp hợp lệ.
- Tải lại trang sau khi ready: vẫn khôi phục đúng nút tải và metadata từ sessionStorage/API, không tạo tác vụ mới.
- Tải thật lần cuối sau bản sửa timeout: video `6742501081818877190`; HTTP 200, MIME audio/mpeg, attachment; **658956 bytes**, FFprobe exit 0, codec **mp3**, thời lượng **27.399546 giây**.
- Reviewer độc lập phát hiện DNS có thể vượt timeout. Test tái hiện thất bại trước sửa; sau khi đưa toàn bộ xử lý vào cây tiến trình có thể dừng, test đạt và cả bộ 22 tests đạt.
- Giao diện và manifest dùng asset SVG tự viết bằng code, không ảnh AI, không font/API giao diện ngoài. Service worker không chặn hoặc cache API/MP3.

## Chưa kiểm chứng / chưa triển khai

- Điện thoại Android thật, thao tác cài PWA và vị trí lưu tệp trên thiết bị.
- HTTPS, hosting, reverse proxy, truy cập từ ngoài máy tính; chưa mở LAN hoặc firewall.
- Docker build/run; kiểm thử tải đồng thời trên máy chủ thực.
- Link rút gọn thật do xếp chia sẻ; xử lý URL/redirect đã có unit test.
- Các kích thước desktop/tablet khác với khung trình duyệt đã xem; chưa xác nhận offline trong Android.

Không coi bản này là ứng dụng Android có URL Internet hoạt động mọi lúc. Để đạt trạng thái đó cần triển khai backend trên máy chủ HTTPS và kiểm tra thiết bị thật. Nguồn TikTok có thể đổi hoặc chặn tải.
