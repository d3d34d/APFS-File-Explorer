# APFS File Explorer for Windows 🍏 💻

[![Download Portable ZIP](https://img.shields.io/badge/Download-APFS__Explorer__v1.0.0.zip-0078d7?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/d3d34d/APFS-File-Explorer/releases/latest)
[![Release](https://img.shields.io/github/v/release/d3d34d/APFS-File-Explorer?style=for-the-badge&color=success)](https://github.com/d3d34d/APFS-File-Explorer/releases/latest)

[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011%20(64--bit)-0078d7.svg)](https://microsoft.com/windows)
[![Python](https://img.shields.io/badge/python-3.10+-3776ab.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Transfer Speed](https://img.shields.io/badge/speed-100%2B%20MB%2Fs-brightgreen.svg)]()
[![Operation](https://img.shields.io/badge/mode-100%25%20Read--Only%20(Safe)-blue.svg)]()

A high-performance, native Windows desktop application designed to explore, browse, preview, and extract files directly from Apple File System (**APFS**) physical drives, external USB hard disks, and disk images (`.dmg`, `.img`, `.raw`).

Built with pure Python and native Windows Win32 APIs—**no paid drivers, kernel extensions, or third-party mounting software required.**

---

## 📥 Download Pre-Built Executable (`.exe`)

> **No Python installation required!** You do not need to install Python, Git, or any coding tools to use this software. A pre-compiled, portable Windows 64-bit application is ready for immediate use.

### ⬇️ [Click Here to Download Latest Release (v1.0.0)](https://github.com/d3d34d/APFS-File-Explorer/releases/download/v1.0.0/APFS-File-Explorer-v1.0.0-Windows-x64.zip)

### How to Run:
1. Download **[`APFS-File-Explorer-v1.0.0-Windows-x64.zip`](https://github.com/d3d34d/APFS-File-Explorer/releases/download/v1.0.0/APFS-File-Explorer-v1.0.0-Windows-x64.zip)**.
2. Right-click the `.zip` file and select **Extract All...** (e.g. to your Desktop or Program Files).
3. Open the extracted folder and right-click **`APFS_Explorer.exe`** ➔ select **Run as Administrator** *(Administrator rights are required by Windows to read raw sectors from physical drives)*.
4. Select your connected drive under **PHYSICAL DRIVES** and click **`⚡ Copy ENTIRE Drive...`** or browse your files!

---

## ⚡ Key Features

- **🚀 Blazing Fast Direct Streaming (100+ MB/s):** Powered by an optimized extent-slicing engine that eliminates upstream re-read bottlenecks, enabling sustained multi-gigabyte video transfers at full physical hardware speeds.
- **🔌 Physical Drives & Disk Images:** Automatically scans and detects connected external Apple hard drives (`\\.\PHYSICALDRIVE*`, `\\.\HarddiskNPartitionM`) and supports opening `.dmg`, `.img`, and `.raw` disk images.
- **⚡ One-Click Full Drive Export:** Copy the entire APFS volume to any Windows directory with a single click, automatically organizing folders and skipping macOS metadata caches (`.fseventsd`, `.Spotlight-V100`).
- **📁 Multi-Selection & Batch Copying (`Ctrl+A`):** Select single files, entire folders, or multiple items simultaneously using `Ctrl+Click` or `Ctrl+A`.
- **📊 Real-Time Transfer Progress Dialog:** Live status modal displaying current file name, copied items counter, transferred data volume (MB/GB), live throughput speed (MB/s), and graceful cancellation.
- **🔒 APFS Encryption Support:** Built-in password and recovery key prompt for encrypted APFS volumes (AES-XTS).
- **🛡️ Windows Long Path & Filename Sanitizer:** Automatically handles macOS filenames exceeding 260 characters using `\\?\` prefixing and sanitizes illegal Windows NTFS/FAT32 characters (`:`, `?`, `*`, trailing spaces/dots).
- **👁️ File Previewer:** Instant preview window with both decoded text preview and a formatted 16-column hex dump.
- **🔄 Paragon APFS Mounter Conflict Resolver:** Detects if the background Paragon APFS Mounter service is holding a lock on the physical drive and provides a 1-click button to stop/restart the service to release device handles.
- **🛡️ 100% Read-Only Safety:** Opens physical drives exclusively with `GENERIC_READ` and `FILE_SHARE_READ | FILE_SHARE_WRITE`. Never writes to your APFS drive, guaranteeing zero risk of filesystem corruption.

---

## 🏗️ Architecture & Engineering Highlights

```
┌────────────────────────────────────────────────────────┐
│             APFS Desktop GUI (Tkinter)                │
│       File TreeView | Live Progress Modal | Previews   │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│                   APFS Engine                          │
│     Targeted Extent Slicing & B-Tree Metadata Cache    │
│            dissect.apfs High-Speed Streamer            │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│              WindowsDiskStream (Win32)                 │
│      64-bit Sector Aligned Kernel32 / Advapi32 I/O     │
│   DeviceIoControl IOCTL_DISK_GET_DRIVE_LAYOUT_EX       │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│          Physical Drive / USB Disk / DMG Image         │
│         (\\.\PHYSICALDRIVE1, \\.\Harddisk1Partition2)  │
└────────────────────────────────────────────────────────┘
```

### Why Standard APFS Python Implementations Are Slow (And How We Fixed It)
In default Python APFS implementations, reading file chunks triggers an $O(N^2)$ disk read pattern: requesting a 1MB chunk causes the parser to re-read the **entire file extent from block 0** on the physical hard disk. For a 2GB video file, chunked reading causes over 5 Terabytes of redundant mechanical disk seeks!

Our custom engine patches `FileStream._read` with:
1. **Targeted Extent Slicing:** Computes the exact physical block offset `(offset_in_extent // 4096)` and reads *only* the blocks requested by the stream.
2. **Extent Metadata Caching:** Remembers the active extent coordinates to bypass repetitive B-Tree searches for sequential streaming.
3. **Aligned Direct Read Fast-Path:** Streams directly from `win32file.ReadFile` without intermediate buffer conversions, achieving **85 – 113 MB/s** on standard USB 3.0 external drives.

---

## 📋 System Requirements

- **Operating System:** Windows 10 or Windows 11 (64-bit)
- **Permissions:** **Administrator Rights** (Required by Windows OS to access raw physical disk sectors via `CreateFileW` / `DeviceIoControl`)
- **Python:** Python 3.10 or higher (only required if running from source)

---

## 🚀 Quick Start

### Option 1: Running from Source

1. **Clone the repository:**
   ```bash
   git clone https://github.com/d3d34d/APFS-File-Explorer.git
   cd APFS-File-Explorer
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch the application as Administrator:**
   Open PowerShell or Command Prompt **as Administrator** and run:
   ```bash
   python gui_explorer.py
   ```
   *(Or double-click `Start_APFS_Explorer.bat`)*

---

### Option 2: Building Standalone Executable (`.exe`)

You can compile the entire application into a standalone folder that launches instantly without Python installed:

1. **Install PyInstaller:**
   ```bash
   pip install pyinstaller pywin32
   ```

2. **Build with PyInstaller:**
   ```bash
   pyinstaller --clean --noconfirm APFS_Explorer.spec
   ```

3. The compiled application will be generated in `dist\APFS_Explorer\APFS_Explorer.exe`. It automatically embeds a Windows UAC Administrator manifest so it prompts for elevation upon launch.

4. **(Optional) Compile the Instant C# Launcher:**
   ```bash
   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /target:winexe /win32icon:app_icon.ico /out:APFS_Explorer.exe launcher.cs
   ```

---

## 📖 Usage Guide

1. **Connect your APFS drive:** Plug in your external USB hard drive or SSD formatted on macOS (APFS).
2. **Select the Physical Drive:** In the left sidebar under **PHYSICAL DRIVES**, click your drive (e.g. `Disk 1: ADATA HD680`).
3. **Select the APFS Volume:** Under **APFS VOLUMES**, select your container volume. If the volume is encrypted with FileVault/APFS Encryption, click **🔒 Unlock Volume...** and enter your password or recovery key.
4. **Browse & Copy:**
   - **Copy Entire Drive:** Click **`⚡ Copy ENTIRE Drive...`** in the sidebar. Select a destination folder on your Windows computer.
   - **Copy Specific Folders/Files:** Select one or more items (press `Ctrl+A` to select all), then click **`⬇ Save Selected to Windows...`**.
   - **Export as ZIP:** Click **`📦 Export Folder as ZIP...`** to create a compressed streaming ZIP archive directly from the APFS folder.
   - **Preview Files:** Double-click any file (or right-click and choose **Preview File**) to view its text contents or hex dump.

---

## 🗂️ Project Structure

```
APFS-File-Explorer/
├── gui_explorer.py         # Native Tkinter desktop GUI & transfer dialog
├── apfs_engine.py          # High-performance APFS session manager & extent streaming patch
├── disk_stream.py          # 64-bit sector-aligned Windows physical disk stream (Win32)
├── launcher.cs             # Lightweight C# UAC elevation launcher
├── APFS_Explorer.spec      # PyInstaller build specification
├── app.manifest            # Windows UAC Administrator manifest
├── app_icon.ico            # Application icon
├── Start_APFS_Explorer.bat # Quick launcher script
├── requirements.txt        # Python dependency manifest
├── LICENSE                 # MIT License
└── README.md               # Documentation
```

---

## ⚠️ Notes & Disclaimers

- **Read-Only Operation:** This software is strictly read-only. It does not write, format, or alter partition tables or sectors on your storage devices.
- **Administrative Privileges:** Windows security model restricts raw sector access (`\\.\PHYSICALDRIVE*`) to elevated processes. If not launched as Administrator, click the **Standard User (Click to Elevate)** badge in the top right to restart with elevation.
- **Trademarks:** Apple, macOS, APFS, and FileVault are trademarks of Apple Inc., registered in the U.S. and other countries. This project is an independent open-source tool and is not affiliated with, endorsed by, or sponsored by Apple Inc.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.
