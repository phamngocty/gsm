#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TYMAP & Tdriver — Automated Release & OTA Distribution Tool
Tự động đồng bộ version vào build.gradle.kts, build APK, đóng gói Firmware, upload lên Gitea NAS Releases, cập nhật version.json và sync NAS Fusion Engine.
"""

import os
import sys
import json
import re
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent
if ROOT_DIR.name == "gsm":
    ROOT_DIR = ROOT_DIR.parent

TYMAP_DIR = ROOT_DIR / "TYMAP"
APK_PATH = TYMAP_DIR / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
BIN_PATH = TYMAP_DIR / "firmware" / "esp32_s3_gc9a01" / ".pio" / "build" / "esp32-s3-devkitc-1" / "firmware.bin"
OLED_BIN_PATH = TYMAP_DIR / "firmware" / "esp32_c3_oled" / ".pio" / "build" / "esp32-c3-devkitm-1" / "firmware.bin"
VERSION_FILE = ROOT_DIR / "version.json"
GRADLE_FILE = TYMAP_DIR / "app" / "build.gradle.kts"

GITEA_SERVER = "http://192.168.1.114:3002"
GITEA_PUBLIC_URL = "https://git.nas152.duckdns.org"
GITEA_OWNER = "nas152"
GITEA_REPO = "Tdriver"
GITEA_USER = "nas152"
GITEA_PASS = "271000"

def print_banner():
    print("=" * 65)
    print("      🚀 TYMAP & TDRIVER — CÔNG CỤ PHÁT HÀNH BẢN MỚI (RELEASE OTA)    ")
    print("=" * 65)

def run_cmd(cmd, cwd=None):
    print(f"⚙️  Thực thi: {cmd}")
    res = subprocess.run(cmd, shell=True, cwd=cwd or ROOT_DIR, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"⚠️ ({res.returncode}): {res.stderr.strip() if res.stderr else res.stdout.strip()}")
        return False, res.stderr
    return True, res.stdout

def get_current_version():
    if VERSION_FILE.exists():
        try:
            with open(VERSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "app": {"versionCode": 1, "versionName": "1.0.0", "apkUrl": "", "changelog": ""},
        "firmware": {"versionCode": 1, "versionName": "1.0.0", "binUrl": "", "changelog": ""}
    }

def update_gradle_version(ver_code, ver_name):
    """Tự động ghi đè versionCode và versionName vào app/build.gradle.kts"""
    if GRADLE_FILE.exists():
        content = GRADLE_FILE.read_text(encoding="utf-8")
        content = re.sub(r'versionCode\s*=\s*\d+', f'versionCode = {ver_code}', content)
        content = re.sub(r'versionName\s*=\s*"[^"]+"', f'versionName = "{ver_name}"', content)
        GRADLE_FILE.write_text(content, encoding="utf-8")
        print(f"✅ Đã đồng bộ build.gradle.kts: versionCode = {ver_code}, versionName = \"{ver_name}\"")

def build_android_apk():
    print("\n📦 Đang Build lại Android APK (assembleDebug)...")
    gradle_cmd = ".\\gradlew.bat assembleDebug" if sys.platform == "win32" else "./gradlew assembleDebug"
    ok, _ = run_cmd(gradle_cmd, cwd=TYMAP_DIR)
    if ok and APK_PATH.exists():
        size_mb = APK_PATH.stat().st_size / (1024 * 1024)
        print(f"✅ Build APK thành công! ({size_mb:.2f} MB)")
        return True
    return False

def create_gitea_release_and_upload(tag_name, release_name, changelog):
    """Tự động gọi API Gitea tạo Release và upload APK + BIN đính kèm."""
    print("\n📦 [2/4] Đang tạo Release & Upload File APK + Firmware BIN lên Gitea NAS...")
    try:
        import requests
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "requests"], check=False)
        import requests

    auth = (GITEA_USER, GITEA_PASS)
    
    # 1. Tạo hoặc lấy Release hiện tại
    rel_id = None
    try:
        resp = requests.post(f"{GITEA_SERVER}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/releases", auth=auth, json={
            "tag_name": tag_name,
            "name": release_name or tag_name,
            "body": changelog,
            "draft": False,
            "prerelease": False
        }, timeout=15)
        if resp.status_code in (200, 201):
            rel_id = resp.json().get("id")
        else:
            get_rel = requests.get(f"{GITEA_SERVER}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/releases/tags/{tag_name}", auth=auth, timeout=15)
            if get_rel.status_code == 200:
                rel_id = get_rel.json().get("id")
    except Exception as e:
        print(f"⚠️ Lỗi kết nối Gitea API: {e}")

    if not rel_id:
        print(f"❌ Không thể tạo hoặc tìm Release {tag_name} trên Gitea!")
        return "", ""

    print(f"✅ Đã tạo/kết nối Release ID: {rel_id}")

    apk_url = f"{GITEA_PUBLIC_URL}/{GITEA_OWNER}/{GITEA_REPO}/releases/download/{tag_name}/app-debug.apk"
    bin_url = f"{GITEA_PUBLIC_URL}/{GITEA_OWNER}/{GITEA_REPO}/releases/download/{tag_name}/firmware.bin"

    # Xóa file cũ đính kèm nếu đã có để upload file mới nhất
    try:
        old_assets = requests.get(f"{GITEA_SERVER}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/releases/{rel_id}/assets", auth=auth, timeout=15).json()
        for a in old_assets:
            requests.delete(f"{GITEA_SERVER}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/releases/{rel_id}/assets/{a.get('id')}", auth=auth, timeout=10)
    except Exception:
        pass

    # 2. Upload APK
    if APK_PATH.exists():
        print(f"📤 Đang upload APK ({APK_PATH.stat().st_size / (1024*1024):.1f} MB)...")
        try:
            with open(APK_PATH, "rb") as f:
                up_resp = requests.post(f"{GITEA_SERVER}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/releases/{rel_id}/assets?name=app-debug.apk", auth=auth, files={"attachment": ("app-debug.apk", f, "application/octet-stream")}, timeout=180)
                if up_resp.status_code in (200, 201):
                    print("✅ Upload APK lên Gitea thành công!")
                else:
                    print(f"⚠️ Upload APK response: {up_resp.status_code}")
        except Exception as e:
            print(f"⚠️ Lỗi upload APK: {e}")
    else:
        print(f"⚠️ Không tìm thấy file APK tại: {APK_PATH}")

    # 3. Upload BIN (GC9A01)
    if BIN_PATH.exists():
        print(f"📤 Đang upload Firmware GC9A01 BIN ({BIN_PATH.stat().st_size / 1024:.1f} KB)...")
        try:
            with open(BIN_PATH, "rb") as f:
                up_resp = requests.post(f"{GITEA_SERVER}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/releases/{rel_id}/assets?name=firmware.bin", auth=auth, files={"attachment": ("firmware.bin", f, "application/octet-stream")}, timeout=180)
                if up_resp.status_code in (200, 201):
                    print("✅ Upload Firmware GC9A01 BIN lên Gitea thành công!")
                else:
                    print(f"⚠️ Upload BIN response: {up_resp.status_code}")
        except Exception as e:
            print(f"⚠️ Lỗi upload Firmware GC9A01 BIN: {e}")
    else:
        print(f"⚠️ Không tìm thấy file Firmware GC9A01 BIN tại: {BIN_PATH}")

    # 4. Upload BIN (OLED)
    oled_bin_url = f"{GITEA_PUBLIC_URL}/{GITEA_OWNER}/{GITEA_REPO}/releases/download/{tag_name}/firmware_oled.bin"
    if OLED_BIN_PATH.exists():
        print(f"📤 Đang upload Firmware OLED BIN ({OLED_BIN_PATH.stat().st_size / 1024:.1f} KB)...")
        try:
            with open(OLED_BIN_PATH, "rb") as f:
                up_resp = requests.post(f"{GITEA_SERVER}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/releases/{rel_id}/assets?name=firmware_oled.bin", auth=auth, files={"attachment": ("firmware_oled.bin", f, "application/octet-stream")}, timeout=180)
                if up_resp.status_code in (200, 201):
                    print("✅ Upload Firmware OLED BIN lên Gitea thành công!")
                else:
                    print(f"⚠️ Upload OLED BIN response: {up_resp.status_code}")
        except Exception as e:
            print(f"⚠️ Lỗi upload Firmware OLED BIN: {e}")
    else:
        print(f"⚠️ Không tìm thấy file Firmware OLED BIN tại: {OLED_BIN_PATH}")

    return apk_url, bin_url, oled_bin_url

def sync_version_to_nas(version_data):
    print("\n📡 [4/4] Đồng bộ trực tiếp version.json & file nhị phân OTA sang trạm NAS Fusion Engine...")
    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect("192.168.1.114", username="nas152", password="271000", timeout=10)
        sftp = ssh.open_sftp()
        dest_dir = "/home/nas152/tymap_data/cameras"

        # 1. Upload APK nếu có
        if APK_PATH.exists():
            print(f"  📤 Đang đồng bộ APK sang NAS ({APK_PATH.stat().st_size / (1024*1024):.1f} MB)...")
            sftp.put(str(APK_PATH), f"{dest_dir}/app-debug.apk")
            print("  ✅ Đã tải APK lên NAS!")

        # 2. Upload GC9A01 BIN nếu có
        if BIN_PATH.exists():
            print(f"  📤 Đang đồng bộ Firmware GC9A01 BIN sang NAS...")
            sftp.put(str(BIN_PATH), f"{dest_dir}/firmware.bin")
            print("  ✅ Đã tải Firmware GC9A01 BIN lên NAS!")

        # 3. Upload OLED BIN nếu có
        if OLED_BIN_PATH.exists():
            print(f"  📤 Đang đồng bộ Firmware OLED BIN sang NAS...")
            sftp.put(str(OLED_BIN_PATH), f"{dest_dir}/firmware_oled.bin")
            print("  ✅ Đã tải Firmware OLED BIN lên NAS!")

        # 4. Upload version.json
        v_temp = ROOT_DIR / "version.json"
        sftp.put(str(v_temp), f"{dest_dir}/version.json")
        sftp.close()
        ssh.exec_command("docker restart tymap_fusion_engine")
        ssh.close()
        print("✅ Đã đồng bộ version.json & OTA Assets sang máy chủ NAS (https://alert.nas152.duckdns.org)!")
    except Exception as e:
        print(f"⚠️ Cảnh báo đồng bộ NAS: {e}")

def main():
    print_banner()
    curr = get_current_version()
    curr_app_ver = curr.get("app", {}).get("versionName", "1.0.0")
    curr_app_code = curr.get("app", {}).get("versionCode", 1)
    
    suggested_code = curr_app_code + 1
    parts = curr_app_ver.split(".")
    if len(parts) == 3 and parts[-1].isdigit():
        suggested_ver = f"{parts[0]}.{parts[1]}.{int(parts[-1]) + 1}"
    else:
        suggested_ver = f"1.0.{suggested_code}"

    print(f"📌 Phiên bản hiện tại: v{curr_app_ver} (Code: {curr_app_code})")
    print(f"💡 Phiên bản đề xuất : v{suggested_ver} (Code: {suggested_code})\n")

    tag_input = input(f"Nhập Tag phiên bản mới [{suggested_ver}]: ").strip()
    tag = tag_input if tag_input else suggested_ver
    tag_name = tag if tag.startswith("v") else f"v{tag}"
    ver_name = tag_name.lstrip("v")

    code_input = input(f"Nhập Version Code mới [{suggested_code}]: ").strip()
    ver_code = int(code_input) if code_input.isdigit() else suggested_code

    print("\nNhập nội dung cập nhật (Changelog):")
    changelog_input = input("Changelog [Cập nhật cải tiến tính năng & sửa lỗi]: ").strip()
    changelog = changelog_input if changelog_input else "Cập nhật cải tiến tính năng & sửa lỗi."

    # 1. Tự động đồng bộ vào app/build.gradle.kts & Build lại APK
    update_gradle_version(ver_code, ver_name)
    build_android_apk()

    # 2. Commit Git & Tạo Tag
    print("\n🚀 [1/4] Commit Git & Tạo Tag...")
    run_cmd("git add .")
    run_cmd(f'git commit -m "release({tag_name}): publish update v{ver_name}"')
    run_cmd(f'git tag -a {tag_name} -m "Release {tag_name}: {changelog}"')
    run_cmd("git push origin master")
    run_cmd("git push origin main")
    run_cmd(f"git push origin {tag_name}")

    # 3. Upload APK & BIN lên Gitea Releases
    apk_url, bin_url, oled_bin_url = create_gitea_release_and_upload(tag_name, tag_name, changelog)
    # Ưu tiên URL phân phối trực tiếp từ NAS (https://alert.nas152.duckdns.org/downloads)
    nas_apk_url = "https://alert.nas152.duckdns.org/downloads/app-debug.apk"
    nas_bin_url = "https://alert.nas152.duckdns.org/downloads/firmware.bin"
    nas_oled_bin_url = "https://alert.nas152.duckdns.org/downloads/firmware_oled.bin"

    if not apk_url:
        apk_url = nas_apk_url
    if not bin_url:
        bin_url = nas_bin_url
    if not oled_bin_url:
        oled_bin_url = nas_oled_bin_url

    # 4. Ghi file version.json & push
    print("\n📝 [3/4] Cập nhật version.json...")
    new_version_data = {
        "app": {
            "versionCode": ver_code,
            "versionName": ver_name,
            "apkUrl": apk_url,
            "changelog": changelog
        },
        "firmware": {
            "versionCode": ver_code,
            "versionName": ver_name,
            "binUrl": bin_url,
            "oledBinUrl": oled_bin_url,
            "changelog": changelog
        },
        "firmware_oled": {
            "versionCode": ver_code,
            "versionName": ver_name,
            "binUrl": oled_bin_url,
            "changelog": changelog
        }
    }

    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(new_version_data, f, ensure_ascii=False, indent=2)

    run_cmd("git add version.json")
    run_cmd(f'git commit -m "chore(ota): update version.json for {tag_name}"')
    run_cmd("git push origin master")
    run_cmd("git push origin main")

    # 5. Sync to NAS
    sync_version_to_nas(new_version_data)

    print("\n" + "=" * 65)
    print(f"🎉 PHÁT HÀNH HOÀN TẤT PHIÊN BẢN {tag_name}!")
    print(f"🔗 Xem trên Gitea: {GITEA_SERVER}/{GITEA_OWNER}/{GITEA_REPO}/releases")
    print(f"📱 App APK: {apk_url}")
    print(f"⌚ Firmware GC9A01: {bin_url}")
    print(f"📟 Firmware OLED: {oled_bin_url}")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    main()
