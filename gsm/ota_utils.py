"""
OTA and Release helper utilities for GSM (Git Smart Manager).
Supports auto-discovery of Android APKs, PlatformIO Firmware BINs, version.json parsing,
and automated Gitea/NAS OTA distribution.
"""

import os
import json
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

from gsm.api_utils import parse_github_repo_url, create_github_release, upload_github_asset
from gsm.storage import get_token

log = logging.getLogger("gsm.ota")


def find_release_assets(project_path: str) -> Dict[str, Any]:
    """
    Tự động quét thư mục dự án để tìm:
    - File APK Android (app-debug.apk, app-release.apk)
    - File Firmware ESP32 (firmware.bin)
    - File version.json để lấy thông tin phiên bản hiện tại
    """
    result = {
        "apk_path": "",
        "bin_path": "",
        "oled_bin_path": "",
        "version_file": "",
        "app_version_code": 1,
        "app_version_name": "1.0.0",
        "fw_version_code": 1,
        "fw_version_name": "1.0.0",
        "suggested_tag": "v1.0.1",
        "suggested_app_code": 2,
        "suggested_fw_code": 2,
        "changelog": "",
    }

    if not project_path or not os.path.exists(project_path):
        return result

    proj_dir = Path(project_path)

    # 1. Tìm file version.json
    version_candidates = [
        proj_dir / "version.json",
        proj_dir / "TYMAP" / "version.json",
        proj_dir.parent / "version.json"
    ]
    for v_file in version_candidates:
        if v_file.exists():
            try:
                with open(v_file, "r", encoding="utf-8") as f:
                    v_data = json.load(f)
                result["version_file"] = str(v_file)
                
                app_obj = v_data.get("app", {})
                result["app_version_code"] = app_obj.get("versionCode", 1)
                result["app_version_name"] = app_obj.get("versionName", "1.0.0")
                result["changelog"] = app_obj.get("changelog", "")
                
                fw_obj = v_data.get("firmware", {})
                result["fw_version_code"] = fw_obj.get("versionCode", 1)
                result["fw_version_name"] = fw_obj.get("versionName", "1.0.0")
                break
            except Exception as e:
                log.warning(f"Error parsing {v_file}: {e}")

    # Đề xuất phiên bản kế tiếp
    curr_code = max(result["app_version_code"], result["fw_version_code"])
    result["suggested_app_code"] = curr_code + 1
    result["suggested_fw_code"] = curr_code + 1

    ver_name = result["app_version_name"]
    parts = ver_name.split(".")
    if len(parts) == 3 and parts[-1].isdigit():
        result["suggested_tag"] = f"v{parts[0]}.{parts[1]}.{int(parts[-1]) + 1}"
    else:
        result["suggested_tag"] = f"v1.0.{curr_code + 1}"

    # 2. Tìm file APK (app-debug.apk, app-release.apk, *.apk)
    apk_candidates = [
        proj_dir / "TYMAP" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk",
        proj_dir / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk",
        proj_dir / "TYMAP" / "app" / "build" / "intermediates" / "apk" / "debug" / "app-debug.apk",
        proj_dir / "app" / "build" / "intermediates" / "apk" / "debug" / "app-debug.apk",
        proj_dir / "TYMAP" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk",
        proj_dir / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk",
        proj_dir / "TYMAP" / "app" / "build" / "intermediates" / "apk" / "release" / "app-release.apk",
        proj_dir / "release_dist" / "TYMAP_Latest.apk",
    ]
    for apk_file in apk_candidates:
        if apk_file.exists():
            result["apk_path"] = str(apk_file)
            break

    if not result["apk_path"]:
        # Quét đệ quy tìm file .apk mới nhất trong thư mục dự án
        try:
            apks = [p for p in proj_dir.glob("**/*.apk") if ".gradle" not in str(p)]
            if apks:
                apks.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                result["apk_path"] = str(apks[0])
        except Exception:
            pass

    # 3. Tìm file firmware.bin ESP32 (Chính / Mặc định)
    bin_candidates = [
        proj_dir / "TYMAP" / "firmware" / "esp32_s3_gc9a01" / ".pio" / "build" / "esp32-s3-devkitc-1" / "firmware.bin",
        proj_dir / "firmware" / "esp32_s3_gc9a01" / ".pio" / "build" / "esp32-s3-devkitc-1" / "firmware.bin",
        proj_dir / ".pio" / "build" / "esp32-s3-devkitc-1" / "firmware.bin",
        proj_dir / ".pio" / "build" / "esp32dev" / "firmware.bin",
        proj_dir / ".pio" / "build" / "esp32-c3-devkitm-1" / "firmware.bin",
        proj_dir / "build" / "firmware.bin",
        proj_dir / "firmware.bin"
    ]
    for bin_file in bin_candidates:
        if bin_file.exists():
            result["bin_path"] = str(bin_file)
            break

    # Nếu chưa tìm thấy, quét tìm bất kỳ file .bin hợp lệ nào (bỏ qua bootloader, partitions)
    ignore_bin_names = {"bootloader.bin", "partitions.bin", "boot_app0.bin"}
    if not result["bin_path"]:
        try:
            pio_bins = [
                p for p in proj_dir.glob("**/.pio/build/**/firmware.bin")
                if p.is_file() and p.name.lower() not in ignore_bin_names
            ]
            if not pio_bins:
                pio_bins = [
                    p for p in proj_dir.glob("**/*.bin")
                    if p.is_file() and p.name.lower() not in ignore_bin_names and ".git" not in str(p)
                ]
            if pio_bins:
                pio_bins.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                result["bin_path"] = str(pio_bins[0])
        except Exception:
            pass

    # 4. Tìm file firmware.bin ESP32 phụ / tùy chọn (nếu có thêm file .bin thứ hai)
    oled_candidates = [
        proj_dir / "TYMAP" / "firmware" / "esp32_c3_oled" / ".pio" / "build" / "esp32-c3-devkitm-1" / "firmware.bin",
        proj_dir / "firmware" / "esp32_c3_oled" / ".pio" / "build" / "esp32-c3-devkitm-1" / "firmware.bin",
    ]
    for oled_file in oled_candidates:
        if oled_file.exists() and str(oled_file) != result["bin_path"]:
            result["oled_bin_path"] = str(oled_file)
            break

    if not result["oled_bin_path"]:
        try:
            all_bins = [
                p for p in proj_dir.glob("**/*.bin")
                if p.is_file() and p.name.lower() not in ignore_bin_names and ".git" not in str(p) and str(p) != result["bin_path"]
            ]
            if all_bins:
                all_bins.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                result["oled_bin_path"] = str(all_bins[0])
        except Exception:
            pass

    return result


def sync_version_to_nas(version_data: dict, nas_ip: str = "192.168.1.114", username: str = "nas152", password: str = "271000",
                        apk_path: str = "", bin_path: str = "", oled_bin_path: str = "") -> bool:
    """Đồng bộ version.json và các file nhị phân OTA (APK, BIN) sang trạm NAS Fusion Engine qua SSH/SFTP."""
    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(nas_ip, username=username, password=password, timeout=10)
        
        sftp = ssh.open_sftp()
        dest_dir = f"/home/{username}/tymap_data/cameras"

        # 1. Upload APK nếu có
        if apk_path and os.path.exists(apk_path):
            try:
                sftp.put(apk_path, f"{dest_dir}/app-debug.apk")
                log.info("Uploaded app-debug.apk to NAS")
            except Exception as e:
                log.warning(f"Failed to upload APK to NAS: {e}")

        # 2. Upload Firmware chính nếu có
        if bin_path and os.path.exists(bin_path):
            try:
                bin_name = os.path.basename(bin_path) or "firmware.bin"
                sftp.put(bin_path, f"{dest_dir}/firmware.bin")
                if bin_name != "firmware.bin":
                    try:
                        sftp.put(bin_path, f"{dest_dir}/{bin_name}")
                    except Exception:
                        pass
                log.info(f"Uploaded {bin_name} (firmware.bin) to NAS")
            except Exception as e:
                log.warning(f"Failed to upload firmware.bin to NAS: {e}")

        # 3. Upload Firmware phụ nếu có
        if oled_bin_path and os.path.exists(oled_bin_path):
            try:
                sec_name = os.path.basename(oled_bin_path) or "firmware_oled.bin"
                sftp.put(oled_bin_path, f"{dest_dir}/firmware_oled.bin")
                if sec_name != "firmware_oled.bin":
                    try:
                        sftp.put(oled_bin_path, f"{dest_dir}/{sec_name}")
                    except Exception:
                        pass
                log.info(f"Uploaded {sec_name} (firmware_oled.bin) to NAS")
            except Exception as e:
                log.warning(f"Failed to upload secondary firmware to NAS: {e}")

        # 4. Upload version.json
        temp_file = Path(os.environ.get("TEMP", "/tmp")) / "version_sync.json"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(version_data, f, ensure_ascii=False, indent=2)
            
        sftp.put(str(temp_file), f"{dest_dir}/version.json")
        sftp.close()
        
        ssh.exec_command("docker restart tymap_fusion_engine")
        ssh.close()
        return True
    except Exception as e:
        log.warning(f"Failed to sync version & assets to NAS: {e}")
        return False


def publish_two_repo_ota(
    project_path: str,
    public_repo_url: str,
    tag_name: str,
    app_ver_code: int = 1,
    fw_ver_code: int = 1,
    changelog: str = "",
    apk_path: str = "",
    bin_path: str = "",
    oled_bin_path: str = "",
    extra_files: list = None,
    github_token: str = "",
) -> dict:
    """
    Tái cấu trúc phát hành OTA theo mô hình 'Cách ly vật lý 2 Repository':
    - Repo 1 (Source Code - Private): Đã được commit/push riêng biệt.
    - Repo 2 (OTA Distribution - Public): Nhận tài nguyên tĩnh (/docs), version.json và Release Assets.
    
    Quy trình 4 bước:
    Bước 1: Clone hoặc init thư mục tạm cho Repo 2, copy thư mục Web HTML vào /docs.
    Bước 2: Tự động sinh version.json vào /docs hỗ trợ nhiều file nhị phân linh hoạt.
    Bước 3: Dùng subprocess gọi git add, commit, push thư mục /docs lên Repo 2.
    Bước 4: Gọi GitHub API tạo Release trên Repo 2 và upload tất cả file nhị phân (BIN, APK, các file phụ tùy chọn) vào Release Assets.
    """
    logs = []
    token = github_token or get_token("github_token") or ""
    if not token:
        raise ValueError("Chưa cấu hình GitHub token. Vui lòng vào Cài Đặt nhập token trước khi phát hành OTA.")

    owner, repo = parse_github_repo_url(public_repo_url)
    if not owner or not repo:
        raise ValueError(f"URL Repository OTA công khai không hợp lệ: '{public_repo_url}'")

    logs.append(f"🔗 Bắt đầu phát hành OTA sang Repo 2 (Public): {owner}/{repo}")

    # Build authenticated git clone/push URL
    auth_repo_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"

    temp_dir = tempfile.mkdtemp(prefix="gsm_ota_repo2_")
    try:
        # Bước 1: Xử lý Web tĩnh
        logs.append("📥 Bước 1: Chuẩn bị Repo 2 và đồng bộ thư mục Web tĩnh...")
        clone_cmd = ["git", "clone", auth_repo_url, "."]
        clone_proc = subprocess.run(clone_cmd, cwd=temp_dir, capture_output=True, text=True, timeout=120)

        if clone_proc.returncode != 0:
            logs.append("ℹ️ Repo 2 chưa có commit hoặc clone trực tiếp thất bại, tiến hành khởi tạo git repository...")
            subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True, text=True)
            subprocess.run(["git", "remote", "add", "origin", auth_repo_url], cwd=temp_dir, capture_output=True, text=True)

        docs_dir = Path(temp_dir) / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        # Copy tài nguyên web từ project_path vào docs_dir
        web_copied = False
        proj_p = Path(project_path)
        candidate_web_dirs = [
            proj_p / "docs",
            proj_p / "web",
            proj_p / "html",
            proj_p / "data" / "web",
            proj_p / "static",
        ]
        for cdir in candidate_web_dirs:
            if cdir.is_dir() and any(cdir.iterdir()):
                shutil.copytree(cdir, docs_dir, dirs_exist_ok=True)
                logs.append(f"📁 Đã copy thư mục web '{cdir.name}' vào /docs của Repo 2")
                web_copied = True
                break

        # Nếu có các file html rời tại thư mục gốc project_path
        for f in proj_p.glob("*.html"):
            shutil.copy2(f, docs_dir / f.name)
            web_copied = True

        if not web_copied:
            # Tạo file index.html mặc định làm trang thông tin cập nhật OTA
            default_index = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{repo} - OTA Distribution</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; padding: 40px 20px; text-align: center; }}
        .card {{ max-width: 580px; margin: 0 auto; background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 30px; text-align: left; }}
        h1 {{ color: #58a6ff; font-size: 24px; margin-top: 0; }}
        .badge {{ background: #238636; color: #fff; padding: 4px 10px; border-radius: 20px; font-size: 13px; font-weight: bold; }}
        pre {{ background: #0d1117; padding: 12px; border-radius: 6px; overflow-x: auto; color: #7ee787; }}
        a.btn {{ display: inline-block; background: #238636; color: white; text-decoration: none; padding: 10px 18px; border-radius: 6px; font-weight: 600; margin-top: 15px; }}
        a.btn:hover {{ background: #2ea043; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>📡 {repo} OTA Distribution</h1>
        <p>Phiên bản phát hành mới nhất: <span class="badge">{tag_name}</span></p>
        <p><strong>Ghi chú:</strong> {changelog or 'Bản cập nhật tối ưu hiệu năng và sửa lỗi.'}</p>
        <p>File cấu hình OTA cho thiết bị:</p>
        <pre><a href="version.json" style="color:#7ee787;">version.json</a></pre>
        <a class="btn" href="https://github.com/{owner}/{repo}/releases/tag/{tag_name}" target="_blank">Xem GitHub Release & Tải File</a>
    </div>
</body>
</html>
"""
            with open(docs_dir / "index.html", "w", encoding="utf-8") as f_idx:
                f_idx.write(default_index)
            logs.append("📄 Đã tạo file docs/index.html giới thiệu OTA cập nhật")

        # Bước 2: Tạo version.json
        logs.append("📝 Bước 2: Tạo file version.json trong thư mục /docs...")
        apk_filename = os.path.basename(apk_path) if apk_path else f"{repo}-release.apk"
        bin_filename = os.path.basename(bin_path) if bin_path else "firmware.bin"
        oled_bin_filename = os.path.basename(oled_bin_path) if oled_bin_path else "firmware_secondary.bin"
        if oled_bin_path and bin_path and bin_filename == oled_bin_filename:
            oled_bin_filename = f"secondary_{oled_bin_filename}"

        download_base = f"https://github.com/{owner}/{repo}/releases/download/{tag_name}"
        public_apk_url = f"{download_base}/{apk_filename}" if apk_path else ""
        public_bin_url = f"{download_base}/{bin_filename}" if bin_path else ""
        public_oled_bin_url = f"{download_base}/{oled_bin_filename}" if oled_bin_path else ""

        clean_version_name = tag_name.lstrip("v")
        version_data = {
            "app": {
                "versionCode": int(app_ver_code),
                "versionName": clean_version_name,
                "apkUrl": public_apk_url,
                "apkName": apk_filename if apk_path else "",
                "changelog": changelog,
            },
            "firmware": {
                "versionCode": int(fw_ver_code),
                "versionName": clean_version_name,
                "binUrl": public_bin_url,
                "binName": bin_filename if bin_path else "firmware.bin",
                "secondaryBinUrl": public_oled_bin_url if oled_bin_path else "",
                "secondaryBinName": oled_bin_filename if oled_bin_path else "",
                "oledBinUrl": public_oled_bin_url,
                "changelog": changelog,
            },
            "assets": []
        }

        # Bổ sung các file nhị phân/tài nguyên phụ khác vào version_data
        extra_assets_list = []
        if extra_files and isinstance(extra_files, list):
            for ef in extra_files:
                ef_path = ef.get("path", "").strip() if isinstance(ef, dict) else str(ef).strip()
                ef_label = ef.get("label", "").strip() if isinstance(ef, dict) else ""
                if ef_path and os.path.exists(ef_path):
                    ef_filename = os.path.basename(ef_path)
                    ef_url = f"{download_base}/{ef_filename}"
                    extra_assets_list.append({
                        "name": ef_filename,
                        "label": ef_label or ef_filename,
                        "path": ef_path,
                        "url": ef_url
                    })
                    version_data["assets"].append({
                        "name": ef_filename,
                        "label": ef_label or ef_filename,
                        "url": ef_url
                    })

        with open(docs_dir / "version.json", "w", encoding="utf-8") as f_v:
            json.dump(version_data, f_v, ensure_ascii=False, indent=2)

        # Lưu thêm một bản ở root repo 2 nếu cần
        with open(Path(temp_dir) / "version.json", "w", encoding="utf-8") as f_vr:
            json.dump(version_data, f_vr, ensure_ascii=False, indent=2)

        logs.append(f"✅ Đã ghi docs/version.json (App code: {app_ver_code}, FW code: {fw_ver_code}, Assets: {len(extra_assets_list) + 2})")

        # Bước 3: Push Repo 2 qua subprocess
        logs.append("🚀 Bước 3: Thực hiện Git add, commit và push /docs lên Repo 2...")
        subprocess.run(["git", "config", "user.name", "Git Smart Manager"], cwd=temp_dir, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "gsm@antigravity.local"], cwd=temp_dir, capture_output=True, text=True)

        subprocess.run(["git", "add", "docs"], cwd=temp_dir, capture_output=True, text=True)
        subprocess.run(["git", "add", "version.json"], cwd=temp_dir, capture_output=True, text=True)

        st = subprocess.run(["git", "status", "--porcelain"], cwd=temp_dir, capture_output=True, text=True)
        if st.stdout.strip():
            c_res = subprocess.run(
                ["git", "commit", "-m", f"release(ota): publish web and version.json for {tag_name}"],
                cwd=temp_dir, capture_output=True, text=True
            )
            if c_res.returncode == 0:
                logs.append(f"💾 Đã commit thay đổi cho /docs ({tag_name})")

        # Ensure branch is main
        subprocess.run(["git", "branch", "-M", "main"], cwd=temp_dir, capture_output=True, text=True)
        push_res = subprocess.run(["git", "push", "-u", "origin", "HEAD:main"], cwd=temp_dir, capture_output=True, text=True, timeout=60)
        if push_res.returncode != 0:
            # Fallback nếu branch hiện tại là master
            push_res2 = subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=temp_dir, capture_output=True, text=True, timeout=60)
            if push_res2.returncode != 0:
                logs.append(f"⚠️ Cảnh báo push git Repo 2: {push_res.stderr.strip() or push_res2.stderr.strip()}")
            else:
                logs.append("✅ Đã push thành công thư mục /docs lên Repo 2")
        else:
            logs.append("✅ Đã push thành công thư mục /docs lên nhánh main của Repo 2")

        # Bước 4: Upload File Nhị phân qua GitHub API
        logs.append("☁️ Bước 4: Tạo GitHub Release và upload file nhị phân vào Release Assets của Repo 2...")
        rel = create_github_release(token, owner, repo, tag_name, name=tag_name, body=changelog)
        if not rel:
            raise RuntimeError(f"Không thể tạo hoặc tìm thấy Release {tag_name} trên GitHub Repo {owner}/{repo}")

        rel_id = rel.get("id")
        logs.append(f"✅ Đã tạo GitHub Release trên {owner}/{repo} (Release ID: {rel_id})")

        # Upload Firmware BIN chính
        if bin_path and os.path.exists(bin_path):
            asset_b, err_b = upload_github_asset(token, owner, repo, rel_id, bin_path, custom_name=bin_filename)
            if asset_b:
                logs.append(f"📦 Đã upload Firmware BIN ({bin_filename}) vào Release Assets")
            else:
                logs.append(f"❌ Lỗi upload Firmware BIN vào Release Assets: {err_b}")

        # Upload APK Android
        if apk_path and os.path.exists(apk_path):
            asset_a, err_a = upload_github_asset(token, owner, repo, rel_id, apk_path, custom_name=apk_filename)
            if asset_a:
                logs.append(f"📦 Đã upload Android APK ({apk_filename}) vào Release Assets")
            else:
                logs.append(f"❌ Lỗi upload Android APK vào Release Assets: {err_a}")

        # Upload Firmware phụ (nếu có)
        if oled_bin_path and os.path.exists(oled_bin_path):
            asset_o, err_o = upload_github_asset(token, owner, repo, rel_id, oled_bin_path, custom_name=oled_bin_filename)
            if asset_o:
                logs.append(f"📦 Đã upload Firmware phụ BIN ({oled_bin_filename}) vào Release Assets")
            else:
                logs.append(f"❌ Lỗi upload Firmware phụ BIN vào Release Assets: {err_o}")

        # Upload tất cả các file khác (tùy chọn mở rộng không giới hạn)
        for ef_item in extra_assets_list:
            ef_fpath = ef_item["path"]
            ef_fname = ef_item["name"]
            asset_ex, err_ex = upload_github_asset(token, owner, repo, rel_id, ef_fpath, custom_name=ef_fname)
            if asset_ex:
                logs.append(f"📦 Đã upload file bổ sung ({ef_fname} - {ef_item['label']}) vào Release Assets")
            else:
                logs.append(f"❌ Lỗi upload file bổ sung ({ef_fname}): {err_ex}")

        return {
            "success": True,
            "logs": logs,
            "public_repo": f"{owner}/{repo}",
            "apk_url": public_apk_url,
            "bin_url": public_bin_url,
            "oled_bin_url": public_oled_bin_url,
            "extra_assets": extra_assets_list,
            "release_id": rel_id,
            "html_url": rel.get("html_url", f"https://github.com/{owner}/{repo}/releases/tag/{tag_name}"),
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
