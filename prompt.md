# Dự án: Git Smart Manager (GSM)

## 1. Mục tiêu

Xây dựng một ứng dụng desktop (chạy trên Windows) với giao diện web, giúp quản lý các dự án Git một cách trực quan, không cần dùng dòng lệnh. Ứng dụng cho phép:

- Quản lý danh sách các dự án (workspace).
- Tạo repository mới trên cả GitHub và Gitea đồng thời, sau đó clone về máy.
- Mở dự án trong một Git GUI client mạnh mẽ (Fork) để thực hiện các thao tác phức tạp (commit, push, merge, stash, xem log, conflict…).
- Lưu trữ token của GitHub và Gitea một cách an toàn (mã hóa).
- Cho phép push lên cả hai remote cùng lúc nhờ cấu hình multi-pushurl (sẽ hướng dẫn người dùng cấu hình thủ công một lần, hoặc tự động thiết lập).

## 2. Công nghệ sử dụng

- **Backend**: Python 3.10+ với Flask (hoặc FastAPI) để tạo REST API nội bộ.
- **Frontend**: HTML, CSS, JavaScript (sử dụng thư viện Vue.js 3 để tạo giao diện động, hoặc dùng Jinja2 + vanilla JS nếu đơn giản hơn). Giao diện sẽ được nhúng trong một cửa sổ desktop bằng **Electron** hoặc **Tauri** (ưu tiên Tauri vì nhẹ và an toàn).
- **Git tương tác**: Sử dụng thư viện `GitPython` hoặc gọi lệnh `git` qua subprocess để clone, kiểm tra trạng thái (dùng cho hiển thị thay đổi).
- **API tích hợp**: Sử dụng requests để gọi GitHub REST API và Gitea API.
- **Bảo mật token**: Dùng `cryptography` (Fernet) để mã hóa token lưu trong file cấu hình hoặc registry Windows (dùng `keyring` hoặc lưu trong SQLite mã hóa).
- **Lưu trữ dữ liệu**: SQLite để lưu danh sách dự án, token đã mã hóa, và cấu hình.

## 3. Kiến trúc tổng thể

- Ứng dụng chạy dưới dạng một service nhỏ, mở cửa sổ trình duyệt (hoặc cửa sổ Electron) với giao diện web.
- Người dùng khởi động ứng dụng, giao diện sẽ hiển thị danh sách dự án từ cơ sở dữ liệu.
- Các thao tác chính:
  - Thêm dự án mới: người dùng nhập URL repo (clone) hoặc tạo repo mới từ tool.
  - Tạo repo mới: gọi API GitHub/Gitea để tạo repo (public/private), sau đó clone về thư mục đã chọn.
  - Mở dự án: nhấp vào dự án -> gọi lệnh mở thư mục đó bằng Fork (hoặc Git GUI đã chọn).
  - Xóa dự án khỏi danh sách (không xóa repo trên remote, chỉ xóa khỏi DB và có thể xóa thư mục local nếu người dùng muốn).
- Màn hình cài đặt: nhập token cho GitHub và Gitea, chọn đường dẫn đến Fork (hoặc Git GUI).

## 4. Yêu cầu chức năng chi tiết

### 4.1. Quản lý dự án

- **Danh sách dự án**: hiển thị dạng bảng hoặc cards, mỗi dự án hiển thị: tên, đường dẫn, remote URL (GitHub, Gitea), trạng thái (đã commit chưa?), thời gian cập nhật cuối.
- **Thêm dự án từ URL clone**: nhập URL clone (GitHub hoặc Gitea), chọn thư mục đích, tool sẽ clone và thêm vào danh sách.
- **Tạo repo mới**: form với các trường: tên repo, mô tả, chọn public/private, chọn nền tảng (GitHub, Gitea, hoặc cả hai). Sau khi tạo, tự động clone về máy.
- **Xóa dự án**: xóa khỏi danh sách (có tùy chọn xóa thư mục local hoặc giữ lại).
- **Mở dự án**: nút "Mở trong Fork" – tool sẽ thực thi lệnh `fork.exe <đường_dẫn>`.

### 4.2. Xem trạng thái Git (nhanh)

- Khi chọn một dự án, hiển thị trạng thái Git hiện tại: nhánh hiện tại, số lượng file modified/staged/untracked.
- Có thể liệt kê danh sách các file thay đổi (tên, trạng thái).
- (Không yêu cầu commit/push từ tool này, nhưng có thể hiển thị để người dùng biết).

### 4.3. Quản lý token và cài đặt

- Trang cài đặt: nhập Personal Access Token (PAT) của GitHub và Gitea.
- Lưu token vào SQLite với mã hóa (dùng Fernet, khóa được lưu trong registry hoặc file cấu hình).
- Kiểm tra token hợp lệ bằng cách gọi API `/user` để lấy thông tin.
- Cấu hình đường dẫn đến Fork: lưu đường dẫn thực thi.

### 4.4. Tích hợp multi-pushurl

- Khi tạo repo mới, tự động thêm hai remote: `origin` (GitHub) và `gitea` (Gitea). Sau đó thiết lập pushurl cho `origin` để đẩy lên cả hai: `git remote set-url --add --push origin <url_gitea>` (hoặc hướng dẫn người dùng).
- Nếu người dùng muốn, có thể cung cấp nút "Cấu hình multi-push" cho dự án hiện tại.

### 4.5. Xử lý conflict (merge)

- Tool không thực hiện merge, nhưng khi conflict xảy ra (trong Fork), người dùng sẽ xử lý bằng Fork. Tool có thể hiển thị thông báo "Dự án đang có conflict, hãy mở Fork để giải quyết".

### 4.6. Lịch sử commit (log)

- Có thể hiển thị 5-10 commit gần nhất dưới dạng danh sách (hash, message, tác giả, thời gian) bằng cách gọi `git log --oneline --graph` và parse kết quả (hoặc dùng GitPython). Không cần đồ họa phức tạp.

## 5. Mô tả giao diện chi tiết (UI/UX)

### 5.1. Bố cục tổng thể

Ứng dụng gồm 3 vùng chính:

- **Thanh tiêu đề (Top bar)**: Logo, tên ứng dụng, nút "Cài đặt" (biểu tượng bánh răng), nút "Làm mới", nút "Thêm dự án" (+).
- **Thanh điều hướng bên trái (Sidebar)**: Danh sách các dự án (dạng cây hoặc danh sách). Mỗi dự án hiển thị tên, biểu tượng trạng thái (màu xanh nếu clean, vàng nếu có thay đổi, đỏ nếu có conflict).
- **Vùng nội dung chính (Main)**: Chia làm 2 panel:
  - **Panel trên**: Thông tin dự án đang chọn (tên, đường dẫn, remote, nhánh hiện tại). Kèm nút "Mở trong Fork" nổi bật.
  - **Panel dưới**: Hiển thị trạng thái Git: danh sách các file đã thay đổi (có thể tương tác click để xem diff nếu muốn) và lịch sử commit gần đây (dưới dạng bảng).

### 5.2. Các màn hình chính

#### a) Màn hình Dashboard (Mặc định)

- **Sidebar**: Danh sách dự án, có thể tìm kiếm lọc.
- **Main - Panel thông tin**: Khi chưa chọn dự án, hiển thị thông báo "Vui lòng chọn một dự án".
- **Main - Panel trạng thái**: Ẩn hoặc hiển thị trống.

#### b) Màn hình chi tiết dự án

- Khi click vào một dự án trong sidebar:
  - **Panel trên**: Hiển thị tên dự án, đường dẫn, remote GitHub và Gitea, nhánh hiện tại. Nút "Mở trong Fork" (lớn), nút "Cấu hình multi-push" (nếu chưa có), nút "Xóa dự án".
  - **Panel dưới (trạng thái)**:
    - Dòng thông tin: "Nhánh: main | Commits chưa push: 3" (nếu có).
    - Bảng các file thay đổi: cột "Tên file", cột "Trạng thái" (Modified, Staged, Untracked, Conflict).
    - Bên dưới: lịch sử commit (dạng danh sách rút gọn).

#### c) Màn hình "Thêm dự án" (Pop-up hoặc trang)

- Hai tab: "Clone từ URL" và "Tạo repo mới".
- **Tab Clone**: Nhập URL, chọn thư mục (browse), nút "Clone".
- **Tab Tạo repo mới**:
  - Nhập tên repo (bắt buộc).
  - Nhập mô tả (tùy chọn).
  - Radio: Public / Private.
  - Checkbox: "Tạo trên GitHub" và "Tạo trên Gitea" (mặc định cả hai).
  - Chọn thư mục đích để clone về (browse).
  - Nút "Tạo và Clone".

#### d) Màn hình Cài đặt

- Form nhập token GitHub (PAT) và token Gitea.
- Nút "Kiểm tra kết nối" cho từng nền tảng.
- Đường dẫn đến Fork: ô nhập và nút "Duyệt".
- Nút "Lưu cài đặt".

### 5.3. Tương tác và phản hồi

- Sử dụng thông báo toast (thành công, lỗi) cho các thao tác.
- Hiển thị tiến trình (progress bar) khi clone hoặc tạo repo.
- Lưu trạng thái đăng nhập (token) để không phải nhập lại sau mỗi lần khởi động.

## 6. Yêu cầu kỹ thuật bổ sung

- Sử dụng cơ sở dữ liệu SQLite với bảng `projects` (id, name, path, github_remote, gitea_remote, branch, last_commit, created_at), bảng `settings` (key, value).
- Mã hóa token bằng Fernet, khóa được tạo ngẫu nhiên và lưu vào file `.key` trong thư mục ứng dụng (hoặc sử dụng Windows Data Protection API).
- Xây dựng REST API nội bộ cho frontend:
  - GET /api/projects
  - POST /api/projects (clone hoặc tạo mới)
  - DELETE /api/projects/<id>
  - GET /api/projects/<id>/status
  - GET /api/projects/<id>/commits?limit=10
  - POST /api/settings
  - GET /api/settings
  - POST /api/settings/check_token (cho GitHub/Gitea)

## 7. Hướng dẫn cài đặt và chạy (sẽ được tự động tạo bởi AI)

- Yêu cầu Python, pip, git, và Fork đã cài đặt.
- File requirements.txt.
- File run.py hoặc script start.

## 8. Lưu ý bảo mật

- Không lưu token dưới dạng plaintext.
- Tất cả giao tiếp với API GitHub/Gitea đều qua HTTPS.

## 9. Mở rộng tương lai

- Hỗ trợ thêm các nền tảng khác (GitLab, Bitbucket).
- Hỗ trợ đa người dùng (nếu cần).

---

**Bắt đầu phát triển**: Hãy tạo cấu trúc thư mục, cài đặt các thư viện cần thiết, viết backend Flask, frontend Vue.js, và đóng gói bằng Electron/Tauri. Đảm bảo mã nguồn sạch, có comment và hướng dẫn chạy.
