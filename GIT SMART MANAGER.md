# BỘ TÀI LIỆU KỸ THUẬT TOÀN DIỆN DỰ ÁN: GIT SMART MANAGER (GSM)
## PHỤC VỤ TÁI CẤU TRÚC (REFACTORING & MODERNIZATION SPECIFICATION)

---

### 1. NGÔN NGỮ VÀ THƯ VIỆN UI (TECH STACK & ASYNC MECHANISM)

- **Kiến trúc tổng thể**: **Web GUI ứng dụng cục bộ (Local Single-Page Application - SPA)** theo mô hình Client-Server.
  - **Backend**: **Python 3** với **Flask 3.1.0** (`flask-cors 5.0.1`, `requests 2.32.3`, `keyring 25.6.0`).
  - **Frontend**: **Vue.js 3** (Bản build CDN `vue.global.prod.js` tích hợp sẵn trong template, sử dụng Composition API `setup()`), kết hợp thư viện vẽ nhánh Git **`@gitgraph/js`** và canvas SVG tùy biến.
  - **Giao diện & Styling**: CSS thuần hiện đại (`static/css/style.css`), phong cách **GitHub / GitKraken Dark Theme**, hỗ trợ layout linh hoạt có thể kéo dãn kích thước thanh bên (resizable split panes).
- **Cơ chế khởi chạy**:
  - Script [app.py](file:///c:/Users/phamn/Documents/PlatformIO/gsm/app.py) tự động quét tìm cổng mạng trống (`DEFAULT_PORT = 8765`, quét tối đa 50 cổng qua `find_free_port()`).
  - Tự động kích hoạt trình duyệt mặc định của hệ thống mở `http://127.0.0.1:<port>` sau 1.5 giây thông qua `webbrowser.open()` và `threading.Timer`.
- **Cơ chế xử lý bất đồng bộ & Chống đơ giao diện**:
  - **Phía Frontend**: Toàn bộ thao tác API đều dùng hàm `async/await` gọi qua hàm bọc `api(endpoint, options)` hoặc native `fetch()`. Có các cờ Reactive State phản hồi tức thì (`syncing`, `loading`, `cloning`, `creating`, `otaLoading`, `stagingProgress`) để khóa tạm thời (disable) các nút bấm và hiển thị hiệu ứng xoay (spinner).
  - **Phía Backend**:
    - Đối với các tác vụ nặng kéo dài (như Stage hàng ngàn file cùng lúc): Hỗ trợ **Server-Sent Events (SSE)** thông qua `Response(stream_with_context(...), mimetype='text/event-stream')` (ví dụ route `/api/projects/<project_id>/stage-all-stream`) để liên tục truyền dữ liệu tiến độ phần trăm và tên file đang xử lý về cho Vue hiển thị thời gian thực.
    - Đối với tác vụ khởi chạy ứng dụng ngoài (Fork Client, File Explorer): Sử dụng `subprocess.Popen()` ngầm, không chặn (non-blocking) luồng xử lý web của Flask.

---

### 2. CẤU TRÚC THƯ MỤC GỐC & CƠ CHẾ LƯU TRỮ CẤU HÌNH (PROJECT STRUCTURE)

```
c:\Users\phamn\Documents\PlatformIO\gsm\
├── app.py                      # Entrypoint khởi động Flask server & đăng ký 47 routes REST API
├── release_ota.py              # CLI độc lập hỗ trợ nạp phát hành OTA firmware
├── requirements.txt            # Khai báo dependencies (flask, requests, keyring, flask-cors)
├── prompt.md                   # Tài liệu mô tả & prompt dự án
│
├── gsm/                        # Package lõi xử lý logic nghiệp vụ Python
│   ├── __init__.py             # Khởi tạo package
│   ├── config.py               # Hằng số, định danh APP, hàm định vị thư mục DATA_DIR của OS
│   ├── storage.py              # Quản lý đọc/ghi JSON và tương tác OS Keyring
│   ├── git_utils.py            # Toàn bộ hàm thao tác Git CLI bằng subprocess (hơn 890 dòng)
│   ├── ota_utils.py            # Quét file build (.bin, .apk), tự sinh version.json, đồng bộ NAS
│   └── api_utils.py            # Giao tiếp GitHub REST API & Gitea API qua requests
│
├── templates/                  # Template giao diện Jinja2 kết hợp Vue 3
│   ├── base.html               # Khung sườn HTML5, load Vue 3, GitGraph, CSS, JS
│   ├── index.html              # Giao diện chính (Topbar, Sidebar, Dashboard, Workspace, Panels)
│   └── partials/
│       ├── add_modal.html      # Modal thêm dự án mới (Clone URL / Tạo Repo / Nhập từ Gitea)
│       └── settings_modal.html # Modal cấu hình Git Author, Tokens GitHub, Gitea, NAS, Fork
│
├── static/                     # Tài nguyên tĩnh
│   ├── css/
│   │   └── style.css           # Toàn bộ hệ thống giao diện Dark Mode, GitKraken layout
│   └── js/
│       └── app.js              # Toàn bộ Vue 3 app (2072 dòng), quản lý reactive state và API
│
└── tests/
    └── test_gsm_features.py    # Bộ kiểm thử đơn vị (Unit Tests)
```

- **Định dạng và vị trí lưu trữ file cấu hình**:
  - **Định dạng file**: **`.json`**.
  - **Vị trí thư mục**: Lưu tại thư mục dữ liệu ứng dụng của hệ thống (`DATA_DIR` xác định trong [gsm/config.py](file:///c:/Users/phamn/Documents/PlatformIO/gsm/gsm/config.py)):
    - **Windows**: `%APPDATA%\gsm\` (thực tế tại `C:\Users\<user>\AppData\Roaming\gsm\`)
    - **Linux**: `~/.local/share/gsm/`
    - **macOS**: `~/Library/Application Support/gsm/`
  - **Các file cấu hình cụ thể**:
    1. **`projects.json`**: Lưu mảng danh sách repository (các trường: `id`, `name`, `path`, `icon`, `tags`, `enable_ota`, `github_remote`, `gitea_remote`, `status_summary`).
    2. **`settings.json`**: Lưu cấu hình cài đặt chung (các trường: `gitea_server_url`, `gitea_owner`, `nas_ota_path`, `fork_path`, `default_author`, `dark_mode`, ...).
    3. **`credentials.json`**: Lưu dự phòng tài khoản trong trường hợp OS không hỗ trợ Keyring.
  - **Cơ chế lưu trữ Token & Mật khẩu nhạy cảm**:
    - Ứng dụng **KHÔNG lưu token dạng clear-text trong file JSON** mà sử dụng thư viện **`keyring`** của Python để mã hóa và lưu trực tiếp vào **Windows Credential Manager / macOS Keychain** với Service Name là `"gsm"`:
      - `KEYRING_KEYS["github_token"]` $\rightarrow$ GitHub Personal Access Token (PAT)
      - `KEYRING_KEYS["gitea_token"]` $\rightarrow$ Gitea Access Token
      - `KEYRING_KEYS["gitea_username"]` $\rightarrow$ Tên đăng nhập Gitea
      - `KEYRING_KEYS["gitea_password"]` $\rightarrow$ Mật khẩu Gitea

---

### 3. THƯ VIỆN XỬ LÝ GIT HIỆN TẠI (GIT ENGINE)

- **Phương pháp thực thi**: Sử dụng **gọi lệnh Terminal ẩn trực tiếp thông qua module chuẩn `subprocess`** của Python, **HOÀN TOÀN KHÔNG DÙNG GitPython hay LibGit2**.
- **Chi tiết triển khai trong [gsm/git_utils.py](file:///c:/Users/phamn/Documents/PlatformIO/gsm/gsm/git_utils.py)**:
  - **Hàm thực thi cốt lõi `_run_git`**:
    ```python
    def _run_git(args: list, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        return result
    ```
  - **Lệnh streaming thời gian thực (Clone)**:
    - Hàm `clone_repo(url, target_dir)` sử dụng `subprocess.Popen(["git", "clone", url, target_dir], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)` để đọc từng dòng đầu ra đẩy vào giao diện.
  - **Cơ chế tự bảo vệ chống treo (Anti-lock Mechanism)**:
    - Hàm `git_check_index_lock(project_path)`: Kiểm tra sự tồn tại của `.git/index.lock`.
    - Hàm `git_unlock(project_path)`: Tự động hoặc cho phép người dùng bấm xóa `.git/index.lock` khi tiến trình Git trước đó bị tắt đột ngột (stale lock).
  - **Hệ thống lệnh phong phú được hỗ trợ**:
    - Status, Commit, Push, Pull, Fetch, Merge, Stash (push/pop/list/drop).
    - Quản lý nhánh (list, create, delete, switch, rename).
    - Tag & Release, Reset (Soft / Mixed / Hard), Revert commit.
    - Parsed Diff trực quan (chia theo hunks, số dòng cũ, số dòng mới, add/del).
    - Giải quyết xung đột (Conflict Resolver): Giữ nhánh của mình (`git checkout --ours`), lấy nhánh remote (`git checkout --theirs`), đánh dấu đã sửa (`git add`).

---

### 4. DANH SÁCH UI COMPONENTS & REACTIVE STATE BINDINGS

Toàn bộ giao diện được điều khiển bởi ứng dụng Vue 3 với Delimiter `[[' và ']]'` trong [static/js/app.js](file:///c:/Users/phamn/Documents/PlatformIO/gsm/static/js/app.js) và các template Jinja2.

#### 4.1 Thanh điều hướng & Header (Top Bar & Sidebar Navigation)
| Tên Component | Loại (Tag/Type) | Vue Binding (v-model / event) | Chức năng chi tiết |
| :--- | :--- | :--- | :--- |
| **Ô tìm kiếm repo** | `<input type="text">` | `v-model="searchQuery"`, `@input="filterProjects"` | Tìm kiếm dự án local theo tên hoặc đường dẫn |
| **Nút Refresh All** | `<button class="btn-icon">` | `@click="refreshAll"` | Làm mới toàn bộ danh sách repo và trạng thái git |
| **Nút Mở Settings** | `<button class="btn-icon">` | `@click="openSettings"` | Mở cửa sổ cấu hình hệ thống |
| **Nút Tab Trang chủ** | `<button class="nav-btn">` | `@click="goHome"`, `:class="{ active: navTab === 'home' }"` | Quay về Dashboard chính |
| **Nút Tab Clone** | `<button class="nav-btn">` | `@click="navTab = 'clone'"` | Mở màn hình Clone repository |
| **Nút Tab Tạo Repo** | `<button class="nav-btn">` | `@click="navTab = 'create'"` | Mở màn hình Khởi tạo repo mới |
| **Nút Tab Kho Gitea** | `<button class="nav-btn">` | `@click="navTab = 'gitea_browse'"` | Duyệt danh sách repo trên Gitea Server |
| **Nút Tab Kho GitHub** | `<button class="nav-btn">` | `@click="navTab = 'github_browse'"` | Duyệt danh sách repo trên tài khoản GitHub |

#### 4.2 Workspace & Action Bar (Khi chọn 1 dự án Git)
| Tên Component | Loại (Tag/Type) | Vue Binding (v-model / event) | Chức năng chi tiết |
| :--- | :--- | :--- | :--- |
| **Tab Đồ Thị & Lịch Sử** | `<button class="pm-tab-btn">` | `projectMainTab = 'graph'`, `@click="fetchGraph"` | Xem cây commit GitKraken-style |
| **Tab Thay Đổi & Staging**| `<button class="pm-tab-btn">` | `projectMainTab = 'changes'` | Màn hình 2 cột: danh sách file và Visual Diff |
| **Tab Sơ Đồ Nhánh** | `<button class="pm-tab-btn">` | `projectMainTab = 'branches'` | Quản lý nhánh trực quan (Local vs Remote) |
| **Tab Releases & OTA** | `<button class="pm-tab-btn">` | `projectMainTab = 'releases'` | Quản lý Tag, GitHub/Gitea Release & Firmware OTA |
| **Nút Pull (Kéo về)** | `<button class="abtn">` | `@click="executePull"`, `:disabled="syncing"` | Chạy `git pull` |
| **Nút Push (Đẩy lên)** | `<button class="abtn">` | `@click="executePush"`, `:disabled="syncing"` | Chạy `git push` |
| **Nút Mở Fork App** | `<button class="btn">` | `@click="openInFork"`, `:disabled="!settings.fork_path"` | Mở dự án trong ứng dụng Fork Git Client |
| **Nút Mở Stash / Cất giữ** | `<button class="abtn">` | `@click="executeStashPush"` | Chạy `git stash push` |
| **Nút Khôi phục (Reset)** | `<button class="abtn-danger">` | `@click="showResetPanel = !showResetPanel"` | Mở panel Soft/Mixed/Hard Reset & Revert |

#### 4.3 Khối Commit & Quản lý Staging (Changes Pane)
| Tên Component | Loại (Tag/Type) | Vue Binding (v-model / event) | Chức năng chi tiết |
| :--- | :--- | :--- | :--- |
| **Nút Stage Tất Cả** | `<button class="btn">` | `@click="stageAll"`, `:disabled="stagingProgress.active"` | Đưa tất cả file thay đổi vào Staging area |
| **Nút Bỏ Stage Tất Cả** | `<button class="btn">` | `@click="unstageAll"` | Đưa file ra khỏi Staging area (`git reset`) |
| **Checkbox từng file** | `<input type="checkbox">` | `:checked="isStaged(file.status)"`, `@change="toggleStage(file)"` | Stage/Unstage đơn lẻ từng file |
| **Preset Commit Tags** | `<button class="btn-xs">` | `@click="setCommitPreset('feat'/'fix'/...)"` | Gán nhanh tiền tố `feat:`, `fix:`, `update:` |
| **Ô Nhập Commit Message**| `<input>` hoặc `<textarea>`| `v-model="commitMessage"` | Tiêu đề commit bắt buộc |
| **Ô Nhập Mô tả Commit** | `<textarea>` | `v-model="commitDescription"` | Nội dung mô tả chi tiết mở rộng |
| **Checkbox Auto Push** | `<input type="checkbox">` | `v-model="autoPushAfterCommit"` | Tự động gọi `git push` ngay sau khi commit |
| **Nút Thực thi Commit** | `<button class="btn">` | `@click="executeCommit"`, `:disabled="!commitMessage.trim()"` | Chạy `git commit` (tự động stage nếu chưa stage) |
| **Tiến trình Staging SSE** | `<div class="progress-bar-fill">`| `:style="{ width: stagingProgress.percent + '%' }"` | Hiển thị % tiến độ thời gian thực khi stage file |

#### 4.4 Khối Giải Quyết Xung Đột (Conflict Resolver)
| Tên Component | Loại (Tag/Type) | Vue Binding (v-model / event) | Chức năng chi tiết |
| :--- | :--- | :--- | :--- |
| **Nút Giữ Code của tôi** | `<button class="btn-primary">`| `@click="resolveConflict(file, 'ours')"` | `git checkout --ours <file>` + `git add` |
| **Nút Lấy Code Remote** | `<button class="btn-warning">`| `@click="resolveConflict(file, 'theirs')"`| `git checkout --theirs <file>` + `git add` |
| **Nút Đã sửa xong** | `<button class="btn-success">`| `@click="resolveConflict(file, 'mark_resolved')"` | `git add <file>` |
| **Nút Mở file sửa tay** | `<button class="btn-secondary">`| `@click="openFileInExplorer(file)"` | Mở thư mục chứa file để chỉnh sửa ngoài |

#### 4.5 Khối Quản lý Nhánh (Branches Manager)
| Tên Component | Loại (Tag/Type) | Vue Binding (v-model / event) | Chức năng chi tiết |
| :--- | :--- | :--- | :--- |
| **Ô Nhập Tên Nhánh Mới** | `<input type="text">` | `v-model="newBranchName"`, `@keyup.enter="createBranch"` | Tên nhánh mới cần tạo |
| **Select Điểm bắt đầu** | `<select>` | `v-model="branchCreateFrom"` | Chọn nhánh hoặc commit làm gốc tạo nhánh |
| **Ô Tìm kiếm Nhánh** | `<input type="text">` | `v-model="branchSearchQuery"` | Lọc nhánh hiển thị |
| **Nút Checkout Nhánh** | `<button class="btn-xs">` | `@click="switchBranch(b.name)"` | Chuyển nhánh làm việc (`git checkout`) |
| **Nút Merge Nhánh** | `<button class="btn-xs">` | `@click="mergeBranchInto(b.name)"` | Bắt đầu quy trình merge nhánh |
| **Nút Xóa Nhánh** | `<button class="btn-xs">` | `@click="deleteBranch(b.name)"` | Xóa nhánh local (`git branch -d`) |

#### 4.6 Khối Cài Đặt (Settings Modal - `templates/partials/settings_modal.html`)
| Tên Component | Loại (Tag/Type) | Vue Binding (v-model / event) | Chức năng chi tiết |
| :--- | :--- | :--- | :--- |
| **Tab Chọn Cài đặt** | `<button class="tab">` | `settingsTab = 'author'` hoặc `'services'` | Chuyển giữa cài Git Author và Dịch vụ Token |
| **Select Tài khoản lưu** | `<select>` | `v-model="selectedAuthorIndex"`, `@change="onSelectSavedAuthor"` | Chọn profile tác giả Git đã lưu |
| **Ô Tên tác giả Git** | `<input type="text">` | `v-model="authorForm.name"` | Thiết lập `user.name` |
| **Ô Email tác giả Git** | `<input type="email">` | `v-model="authorForm.email"` | Thiết lập `user.email` |
| **Checkbox Lưu danh sách**| `<input type="checkbox">` | `v-model="authorForm.save_to_list"` | Lưu profile này vào danh bạ tài khoản |
| **Radio Phạm vi áp dụng**| `<input type="radio">` | `v-model="authorScope"` (`'global'` hoặc `'local'`) | Cấu hình cho toàn máy hoặc riêng dự án này |
| **Nút Áp dụng Tác giả** | `<button class="btn">` | `@click="applyGitAuthor"`, `:disabled="savingAuthor"` | Lưu và chạy lệnh `git config` tương ứng |
| **Ô GitHub Token (PAT)** | `<input type="password">` | `v-model="formSettings.github_token"` | Token truy cập GitHub API |
| **Nút Test GitHub Token**| `<button class="btn">` | `@click="checkToken('github')"` | Kiểm tra tính hợp lệ của token qua API |
| **Ô Gitea Server URL** | `<input type="text">` | `v-model="formSettings.gitea_server_url"` | Địa chỉ máy chủ Gitea |
| **Ô Gitea Token** | `<input type="password">` | `v-model="formSettings.gitea_token"` | Token truy cập Gitea API |
| **Ô Gitea Username** | `<input type="text">` | `v-model="formSettings.gitea_username"` | Tên đăng nhập Gitea |
| **Ô Gitea Password** | `<input type="password">` | `v-model="formSettings.gitea_password"` | Mật khẩu Gitea |
| **Ô Đường dẫn Fork App** | `<input type="text">` | `v-model="formSettings.fork_path"` | Đường dẫn file thực thi `fork.exe` |
| **Nút Lưu Cài Đặt** | `<button class="btn-primary">`| `@click="saveSettings"` | Lưu cài đặt và cập nhật Keyring |

#### 4.7 Khối Thêm Dự Án (Add Project Modal - `templates/partials/add_modal.html`)
| Tên Component | Loại (Tag/Type) | Vue Binding (v-model / event) | Chức năng chi tiết |
| :--- | :--- | :--- | :--- |
| **Tab Kiểu Thêm** | `<button class="tab">` | `addTab = 'clone'` / `'create'` / `'gitea'` | Lựa chọn cách thêm dự án |
| **Ô URL Clone** | `<input type="text">` | `v-model="cloneForm.url"` | URL repository Git cần clone |
| **Ô Thư mục Đích** | `<input type="text">` | `v-model="cloneForm.targetDir"` | Thư mục local để chứa mã nguồn |
| **Nút Duyệt Thư Mục** | `<button class="btn">` | `@click="browseDir('clone')"` | Mở hộp thoại chọn thư mục Windows |
| **Nút Bắt Đầu Clone** | `<button class="btn">` | `@click="submitClone"`, `:disabled="cloning"` | Thực thi `git clone` và hiển thị progress |
| **Ô Tên Repo Mới** | `<input type="text">` | `v-model="createForm.name"` | Tên repo mới muốn tạo |
| **Select Quyền Riêng Tư** | `<select>` | `v-model="createForm.private"` | Chọn Public hoặc Private |
| **Checkbox Tạo trên GitHub**| `<input type="checkbox">`| `v-model="createForm.github"` | Tự động tạo repo từ xa trên GitHub |
| **Checkbox Tạo trên Gitea** | `<input type="checkbox">`| `v-model="createForm.gitea"` | Tự động tạo repo từ xa trên Gitea |
| **Nút Tạo và Clone** | `<button class="btn">` | `@click="submitCreate"`, `:disabled="creating"` | Tạo đồng thời trên cloud và khởi tạo local |

#### 4.8 Khối Quản lý Firmware OTA & Phát Hành (Releases & OTA Panel)
| Tên Component | Loại (Tag/Type) | Vue Binding (v-model / event) | Chức năng chi tiết |
| :--- | :--- | :--- | :--- |
| **Checkbox Bật Tiện ích OTA**| `<input type="checkbox">`| `:checked="selectedProject.enable_ota"`, `@change="toggleProjectOta"` | Bật/Tắt module nạp OTA cho dự án |
| **Ô Tên Release Tag** | `<input type="text">` | `v-model="otaReleaseTag"` | Tên thẻ phát hành (ví dụ: `v1.0.1`) |
| **Ô App Version Code** | `<input type="number">`| `v-model="otaAppVerCode"` | Mã phiên bản ứng dụng Android (số nguyên) |
| **Ô Firmware Version Code** | `<input type="number">`| `v-model="otaFwVerCode"` | Mã phiên bản firmware ESP32 (số nguyên) |
| **Ô File Android APK** | `<input type="text">` | `v-model="otaApkPath"` | Đường dẫn file `.apk` đã build |
| **Ô File Firmware BIN** | `<input type="text">` | `v-model="otaBinPath"` | Đường dẫn file firmware `.bin` ESP32 chính (bất kỳ file .bin nào) |
| **Ô File Firmware BIN Phụ**| `<input type="text">` | `v-model="otaOledBinPath"` | File `.bin` tùy chọn (Màn hình phụ / OLED / Mở rộng) |
| **Danh sách File Bổ Sung Mở Rộng**| Dynamic List + `<button>` | `v-for="item in otaExtraFiles"`, `@click="addExtraOtaFile"` | Đính kèm không giới hạn số lượng và định dạng file (SPIFFS, LittleFS, PDF, v.v.) |
| **Ô URL Repo OTA Public** | `<input type="text">` | `v-model="otaPublicRepoUrl"` | URL Repo phân phối OTA công khai (Kiến trúc 2 Repo cách ly vật lý) |
| **Ô Nội dung Changelog** | `<textarea>` | `v-model="otaChangelog"` | Ghi chú cập nhật tính năng mới |
| **Checkbox Tự Build APK** | `<input type="checkbox">`| `v-model="otaAutoBuildApk"` | Tự gọi `gradlew assembleDebug` |
| **Checkbox Sync Trạm NAS** | `<input type="checkbox">`| `v-model="otaSyncNas"` | Tự động upload file firmware sang máy chủ NAS |
| **Nút Quét Tự Động Build** | `<button class="btn">` | `@click="autoDetectOtaAssets"`, `:disabled="otaDetecting"` | Quét tự động thư mục tìm file .apk/.bin mới nhất |
| **Nút Xuất Bản OTA** | `<button class="btn-primary">`| `@click="submitOtaRelease"`, `:disabled="otaLoading"` | Đẩy Release sang GitHub + Gitea + NAS (hoặc Repo 2 Public) |
| **Tab Hướng Dẫn & Code Mẫu**| Subtab Navigation | `otaSubTab = 'guide'` | Mã nguồn C++ WiFi OTA, BLE OTA, Android Kotlin In-App Update mẫu |
| **Tab AI Prompt Tạo Dự Án Mới**| Subtab Navigation | `otaSubTab = 'prompt'` | Prompt động phổ quát để copy đưa cho mọi AI Agent xây dựng OTA cho dự án mới |
