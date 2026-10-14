"""
gui_explorer.py - Native Windows Desktop GUI for APFS Physical Drives & Images
Provides a genuine Windows desktop application (no browser required)
specifically designed to explore APFS physical drives (e.g. \\\\.\\PHYSICALDRIVE1)
and disk images.
"""

import os
import sys
import io
import time
import mimetypes
import zipfile
import subprocess
import threading
from datetime import datetime
from typing import List, Dict, Optional, Any

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

# Core APFS & Windows Disk modules
from disk_stream import WindowsDiskStream, is_admin, list_physical_drives
from apfs_engine import engine, APFSSession, get_kind, get_inode, to_windows_long_path, sanitize_windows_filename


class TransferProgressDialog(tk.Toplevel):
    """
    High-performance modal progress dialog for APFS to Windows file transfers.
    Displays live files copied, data volume transferred, MB/s speed, and supports graceful cancellation.
    """
    def __init__(self, parent, title="Copying Files to Windows", total_label="Preparing transfer..."):
        super().__init__(parent)
        self.title(title)
        self.geometry("540x260")
        self.resizable(False, False)
        self.configure(bg="#1e293b")
        self.transient(parent)
        self.grab_set()

        # Center on parent window
        self.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            w, h = 540, 260
            x = max(0, px + (pw - w) // 2)
            y = max(0, py + (ph - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        self.cancel_event = threading.Event()
        self.start_time = time.time()
        self.last_update = 0

        container = tk.Frame(self, bg="#1e293b", padx=24, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        self.lbl_title = tk.Label(
            container, text=title, font=("Segoe UI", 12, "bold"),
            bg="#1e293b", fg="#f8fafc", anchor="w"
        )
        self.lbl_title.pack(fill=tk.X, pady=(0, 4))

        self.lbl_dest = tk.Label(
            container, text=total_label, font=("Segoe UI", 9),
            bg="#1e293b", fg="#94a3b8", anchor="w", justify=tk.LEFT
        )
        self.lbl_dest.pack(fill=tk.X, pady=(0, 10))

        self.lbl_file = tk.Label(
            container, text="Preparing files...", font=("Segoe UI", 9),
            bg="#1e293b", fg="#38bdf8", anchor="w"
        )
        self.lbl_file.pack(fill=tk.X, pady=(0, 8))

        self.progress_bar = ttk.Progressbar(container, mode="indeterminate", length=490)
        self.progress_bar.pack(fill=tk.X, pady=(0, 12))
        self.progress_bar.start(10)

        stats_frame = tk.Frame(container, bg="#1e293b")
        stats_frame.pack(fill=tk.X, pady=(0, 16))

        self.lbl_stats = tk.Label(
            stats_frame, text="Copied: 0 files | 0 MB | Speed: 0 MB/s",
            font=("Segoe UI", 9), bg="#1e293b", fg="#cbd5e1", anchor="w"
        )
        self.lbl_stats.pack(side=tk.LEFT)

        btn_frame = tk.Frame(container, bg="#1e293b")
        btn_frame.pack(fill=tk.X)

        self.btn_cancel = tk.Button(
            btn_frame, text="Cancel Transfer", font=("Segoe UI", 9, "bold"),
            bg="#334155", fg="#f1f5f9", activebackground="#ef4444", activeforeground="#ffffff",
            relief="flat", padx=16, pady=4, cursor="hand2", command=self.on_cancel
        )
        self.btn_cancel.pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def on_cancel(self):
        if not self.cancel_event.is_set():
            self.cancel_event.set()
            self.lbl_file.config(text="Stopping transfer, cleaning up partial files...", fg="#f59e0b")
            self.btn_cancel.config(state=tk.DISABLED, text="Cancelling...")

    def update_stats(self, current_file: str, files_count: int, bytes_count: int):
        now = time.time()
        if now - self.last_update < 0.05:
            return
        self.last_update = now

        elapsed = max(0.001, now - self.start_time)
        speed_mb = (bytes_count / (1024 * 1024)) / elapsed

        if bytes_count < 1024 * 1024:
            size_str = f"{bytes_count / 1024:.1f} KB"
        elif bytes_count < 1024 * 1024 * 1024:
            size_str = f"{bytes_count / (1024 * 1024):.1f} MB"
        else:
            size_str = f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"

        display_name = current_file
        if len(display_name) > 55:
            display_name = display_name[:26] + "..." + display_name[-26:]

        self.lbl_file.config(text=f"Copying: {display_name}")
        self.lbl_stats.config(text=f"Copied: {files_count:,} files | {size_str} | Speed: {speed_mb:.1f} MB/s")

    def finish(self, stats: dict, dest_dir: str):
        try:
            self.progress_bar.stop()
            self.grab_release()
            self.destroy()
        except Exception:
            pass


class APFSDesktopApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("APFS File Explorer for Windows")
        self.root.geometry("1100x700")
        self.root.minsize(800, 500)

        # Apply dark theme colors
        self.colors = {
            "bg_dark": "#18191e",
            "bg_sidebar": "#1f2026",
            "bg_card": "#262832",
            "bg_hover": "#323542",
            "bg_select": "#0a84ff",
            "fg_primary": "#ffffff",
            "fg_secondary": "#a0a4b0",
            "fg_muted": "#6c7280",
            "accent_blue": "#0a84ff",
            "accent_green": "#30d158",
            "accent_amber": "#ff9f0a",
            "accent_red": "#ff453a",
            "border": "#2e313d"
        }

        self.root.configure(bg=self.colors["bg_dark"])

        # State
        self.current_drives = []
        self.active_vol_idx = 0
        self.current_path = "/"
        self.history = ["/"]
        self.history_idx = 0
        self.current_items = []
        self.sort_col = "name"
        self.sort_reverse = False

        # Configure TTK Styles
        self._setup_styles()

        # Build UI Layout
        self._build_ui()

        # Check Admin Status
        self._check_admin_status()

        # Initial Scan for Physical Drives
        self.root.after(100, self.refresh_drives)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Global treeview
        style.configure(
            "Treeview",
            background=self.colors["bg_dark"],
            foreground=self.colors["fg_primary"],
            fieldbackground=self.colors["bg_dark"],
            rowheight=26,
            font=("Segoe UI", 10),
            borderwidth=0
        )
        style.map(
            "Treeview",
            background=[("selected", self.colors["bg_select"])],
            foreground=[("selected", "#ffffff")]
        )

        style.configure(
            "Treeview.Heading",
            background=self.colors["bg_sidebar"],
            foreground=self.colors["fg_secondary"],
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padding=6
        )
        style.map(
            "Treeview.Heading",
            background=[("active", self.colors["bg_card"])]
        )

        # Scrollbars
        style.configure(
            "Vertical.TScrollbar",
            background=self.colors["bg_sidebar"],
            troughcolor=self.colors["bg_dark"],
            borderwidth=0,
            arrowsize=12
        )

    def _build_ui(self):
        # 1. Top Control / Address Bar
        self.top_bar = tk.Frame(self.root, bg=self.colors["bg_sidebar"], height=48, padx=10, pady=8)
        self.top_bar.pack(side=tk.TOP, fill=tk.X)

        # Nav Buttons (Back, Forward, Up, Refresh)
        self.btn_back = tk.Button(
            self.top_bar, text="◀", font=("Segoe UI", 9),
            bg=self.colors["bg_card"], fg=self.colors["fg_primary"],
            activebackground=self.colors["bg_hover"], activeforeground="#fff",
            relief="flat", padx=8, pady=2, command=self.go_back, state=tk.DISABLED
        )
        self.btn_back.pack(side=tk.LEFT, padx=(0, 2))

        self.btn_forward = tk.Button(
            self.top_bar, text="▶", font=("Segoe UI", 9),
            bg=self.colors["bg_card"], fg=self.colors["fg_primary"],
            activebackground=self.colors["bg_hover"], activeforeground="#fff",
            relief="flat", padx=8, pady=2, command=self.go_forward, state=tk.DISABLED
        )
        self.btn_forward.pack(side=tk.LEFT, padx=(0, 2))

        self.btn_up = tk.Button(
            self.top_bar, text="▲ Up", font=("Segoe UI", 9),
            bg=self.colors["bg_card"], fg=self.colors["fg_primary"],
            activebackground=self.colors["bg_hover"], activeforeground="#fff",
            relief="flat", padx=8, pady=2, command=self.go_up, state=tk.DISABLED
        )
        self.btn_up.pack(side=tk.LEFT, padx=(0, 8))

        # Path Entry
        self.path_var = tk.StringVar(value="/")
        self.path_entry = tk.Entry(
            self.top_bar, textvariable=self.path_var, font=("Segoe UI", 10),
            bg=self.colors["bg_dark"], fg=self.colors["fg_primary"],
            insertbackground="#ffffff", relief="flat", highlightthickness=1,
            highlightbackground=self.colors["border"], highlightcolor=self.colors["accent_blue"]
        )
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.path_entry.bind("<Return>", lambda e: self.navigate_to(self.path_var.get()))

        # Search Box
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self._on_search_change)
        self.search_entry = tk.Entry(
            self.top_bar, textvariable=self.search_var, font=("Segoe UI", 9),
            bg=self.colors["bg_dark"], fg=self.colors["fg_primary"],
            insertbackground="#ffffff", width=20, relief="flat", highlightthickness=1,
            highlightbackground=self.colors["border"], highlightcolor=self.colors["accent_blue"]
        )
        self.search_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.search_entry.insert(0, "Filter files...")
        self.search_entry.bind("<FocusIn>", lambda e: self.search_entry.delete(0, tk.END) if self.search_var.get() == "Filter files..." else None)

        # Admin Badge
        self.lbl_admin = tk.Label(
            self.top_bar, text="Checking...", font=("Segoe UI", 8, "bold"),
            bg=self.colors["bg_card"], fg=self.colors["accent_amber"],
            padx=8, pady=4, cursor="hand2"
        )
        self.lbl_admin.pack(side=tk.RIGHT)
        self.lbl_admin.bind("<Button-1>", lambda e: self.elevate_to_admin() if not is_admin() else None)

        # 2. Main Middle Workspace (PanedWindow: Left Sidebar + Right File View)
        self.paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=self.colors["border"], bd=0, sashwidth=4)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Left Sidebar Frame
        self.sidebar = tk.Frame(self.paned, bg=self.colors["bg_sidebar"], width=280)
        self.paned.add(self.sidebar, minsize=220)

        # Sidebar Title
        lbl_drives_title = tk.Label(
            self.sidebar, text="PHYSICAL DRIVES", font=("Segoe UI", 8, "bold"),
            bg=self.colors["bg_sidebar"], fg=self.colors["fg_muted"], anchor="w"
        )
        lbl_drives_title.pack(fill=tk.X, padx=12, pady=(10, 4))

        # Drive Selector Tree / List
        self.drive_tree = ttk.Treeview(self.sidebar, show="tree", selectmode="browse", height=5)
        self.drive_tree.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.drive_tree.bind("<<TreeviewSelect>>", self._on_drive_selected)

        # Button to Open DMG / Image File
        self.btn_open_img = tk.Button(
            self.sidebar, text="📁 Open .DMG / Disk Image...", font=("Segoe UI", 9),
            bg=self.colors["bg_card"], fg=self.colors["fg_primary"],
            activebackground=self.colors["bg_hover"], activeforeground="#fff",
            relief="flat", pady=4, command=self.open_image_dialog
        )
        self.btn_open_img.pack(fill=tk.X, padx=10, pady=(0, 12))

        # Volumes Header
        lbl_vols_title = tk.Label(
            self.sidebar, text="APFS VOLUMES", font=("Segoe UI", 8, "bold"),
            bg=self.colors["bg_sidebar"], fg=self.colors["fg_muted"], anchor="w"
        )
        lbl_vols_title.pack(fill=tk.X, padx=12, pady=(0, 4))

        # Volume Selector Tree
        self.volume_tree = ttk.Treeview(self.sidebar, show="tree", selectmode="browse", height=4)
        self.volume_tree.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.volume_tree.bind("<<TreeviewSelect>>", self._on_volume_selected)

        # Unlock Button (for encrypted volumes)
        self.btn_unlock = tk.Button(
            self.sidebar, text="🔒 Unlock Volume...", font=("Segoe UI", 9),
            bg=self.colors["bg_card"], fg=self.colors["accent_amber"],
            activebackground=self.colors["bg_hover"], activeforeground="#fff",
            relief="flat", pady=4, command=self.unlock_selected_volume, state=tk.DISABLED
        )
        self.btn_unlock.pack(fill=tk.X, padx=10, pady=(0, 12))

        # Action Buttons Section
        lbl_actions_title = tk.Label(
            self.sidebar, text="EXPORT ACTIONS", font=("Segoe UI", 8, "bold"),
            bg=self.colors["bg_sidebar"], fg=self.colors["fg_muted"], anchor="w"
        )
        lbl_actions_title.pack(fill=tk.X, padx=12, pady=(0, 4))

        self.btn_export_all = tk.Button(
            self.sidebar, text="⚡ Copy ENTIRE Drive...", font=("Segoe UI", 9, "bold"),
            bg="#0284c7", fg="#ffffff",
            activebackground="#0369a1", activeforeground="#ffffff",
            relief="flat", pady=6, command=self.export_entire_volume, state=tk.DISABLED
        )
        self.btn_export_all.pack(fill=tk.X, padx=10, pady=(0, 6))

        self.btn_export_file = tk.Button(
            self.sidebar, text="⬇ Save Selected to Windows...", font=("Segoe UI", 9),
            bg=self.colors["bg_card"], fg=self.colors["accent_blue"],
            activebackground=self.colors["bg_hover"], activeforeground="#fff",
            relief="flat", pady=4, command=self.export_selected_file, state=tk.DISABLED
        )
        self.btn_export_file.pack(fill=tk.X, padx=10, pady=(0, 6))

        self.btn_export_zip = tk.Button(
            self.sidebar, text="📦 Export Folder as ZIP...", font=("Segoe UI", 9),
            bg=self.colors["bg_card"], fg=self.colors["accent_green"],
            activebackground=self.colors["bg_hover"], activeforeground="#fff",
            relief="flat", pady=4, command=self.export_folder_zip, state=tk.DISABLED
        )
        self.btn_export_zip.pack(fill=tk.X, padx=10, pady=(0, 6))

        # Rescan Drives Button
        self.btn_rescan = tk.Button(
            self.sidebar, text="🔄 Refresh Physical Drives", font=("Segoe UI", 8),
            bg=self.colors["bg_sidebar"], fg=self.colors["fg_secondary"],
            activebackground=self.colors["bg_hover"], activeforeground="#fff",
            relief="flat", pady=4, command=self.refresh_drives
        )
        self.btn_rescan.pack(fill=tk.X, padx=10, pady=(12, 0))

        # Paragon Service Control Frame
        self.frame_paragon = tk.Frame(self.sidebar, bg=self.colors["bg_card"], padx=8, pady=6)
        self.lbl_paragon = tk.Label(
            self.frame_paragon, text="Paragon Mounter: Checking...", font=("Segoe UI", 8),
            bg=self.colors["bg_card"], fg=self.colors["fg_secondary"]
        )
        self.lbl_paragon.pack(anchor="w")
        self.btn_toggle_paragon = tk.Button(
            self.frame_paragon, text="Stop Service", font=("Segoe UI", 8),
            bg=self.colors["bg_hover"], fg=self.colors["accent_amber"],
            relief="flat", pady=2, command=self.toggle_paragon_service
        )
        self.btn_toggle_paragon.pack(fill=tk.X, pady=(4, 0))

        # Right Main File Browser Frame
        self.main_frame = tk.Frame(self.paned, bg=self.colors["bg_dark"])
        self.paned.add(self.main_frame, minsize=500)

        # Treeview for Files & Folders
        columns = ("name", "mtime", "kind", "size")
        self.file_tree = ttk.Treeview(self.main_frame, columns=columns, show="headings", selectmode="extended")
        
        self.file_tree.heading("name", text="Name", command=lambda: self._sort_by("name"))
        self.file_tree.heading("mtime", text="Date Modified", command=lambda: self._sort_by("mtime"))
        self.file_tree.heading("kind", text="Kind", command=lambda: self._sort_by("kind"))
        self.file_tree.heading("size", text="Size", command=lambda: self._sort_by("size"))

        self.file_tree.column("name", width=340, anchor="w")
        self.file_tree.column("mtime", width=160, anchor="w")
        self.file_tree.column("kind", width=100, anchor="w")
        self.file_tree.column("size", width=100, anchor="e")

        # Scrollbar for file tree
        self.scroll_y = ttk.Scrollbar(self.main_frame, orient=tk.VERTICAL, command=self.file_tree.yview, style="Vertical.TScrollbar")
        self.file_tree.configure(yscrollcommand=self.scroll_y.set)

        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        # Bindings
        self.file_tree.bind("<Double-1>", self._on_item_double_click)
        self.file_tree.bind("<<TreeviewSelect>>", self._on_item_selected)
        self.file_tree.bind("<Button-3>", self._on_right_click)
        self.file_tree.bind("<Control-a>", self.select_all_items)
        self.file_tree.bind("<Control-A>", self.select_all_items)
        self.root.bind("<Control-a>", self.select_all_items)
        self.root.bind("<Control-A>", self.select_all_items)

        # Right Click Context Menu
        self.context_menu = tk.Menu(self.root, tearoff=0, bg=self.colors["bg_card"], fg=self.colors["fg_primary"], activebackground=self.colors["accent_blue"], activeforeground="#fff")
        self.context_menu.add_command(label="Copy Selected to Windows...", command=self.export_selected_file)
        self.context_menu.add_command(label="Preview File (Text / Hex)...", command=self.preview_selected_file)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Select All (Ctrl+A)", command=self.select_all_items)
        self.context_menu.add_command(label="Copy APFS Path", command=self.copy_apfs_path)

        # 3. Bottom Status Bar
        self.status_bar = tk.Frame(self.root, bg=self.colors["bg_sidebar"], height=24, padx=10, pady=3)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.lbl_status = tk.Label(
            self.status_bar, text="Ready. Select a physical drive on the left.",
            font=("Segoe UI", 9), bg=self.colors["bg_sidebar"], fg=self.colors["fg_secondary"]
        )
        self.lbl_status.pack(side=tk.LEFT)

        self.lbl_items_info = tk.Label(
            self.status_bar, text="0 items",
            font=("Segoe UI", 9), bg=self.colors["bg_sidebar"], fg=self.colors["fg_muted"]
        )
        self.lbl_items_info.pack(side=tk.RIGHT)

    def _check_admin_status(self):
        admin = is_admin()
        if admin:
            self.lbl_admin.config(text="● Administrator", fg=self.colors["accent_green"])
        else:
            self.lbl_admin.config(text="⚠ Standard User (Click to Elevate)", fg=self.colors["accent_amber"])

    def elevate_to_admin(self):
        """Relaunch the app as Windows Administrator via UAC."""
        if messagebox.askyesno(
            "Administrator Rights Required",
            "Windows requires Administrator permissions to read raw sectors from physical drives.\n\n"
            "Would you like to restart the application as Administrator now?"
        ):
            import ctypes
            try:
                if getattr(sys, "frozen", False):
                    ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", sys.executable, None, None, 1
                    )
                else:
                    ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", sys.executable, f'"{os.path.abspath(__file__)}"', None, 1
                    )
                self.root.quit()
            except Exception as e:
                messagebox.showerror("Elevation Error", f"Could not elevate: {e}")

    def check_paragon_service(self):
        """Check if ParagonAPFSMounter service is running instantly via Win32."""
        try:
            import ctypes
            from ctypes import wintypes
            advapi32 = ctypes.windll.advapi32
            advapi32.OpenSCManagerW.restype = ctypes.c_void_p
            advapi32.OpenServiceW.restype = ctypes.c_void_p
            advapi32.OpenServiceW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, wintypes.DWORD]
            advapi32.CloseServiceHandle.argtypes = [ctypes.c_void_p]

            class SERVICE_STATUS(ctypes.Structure):
                _fields_ = [
                    ("dwServiceType", wintypes.DWORD),
                    ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD),
                    ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD),
                    ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD)
                ]
            advapi32.QueryServiceStatus.argtypes = [ctypes.c_void_p, ctypes.POINTER(SERVICE_STATUS)]

            scm = advapi32.OpenSCManagerW(None, None, 0x0001)
            if not scm:
                self.frame_paragon.pack_forget()
                return

            svc = advapi32.OpenServiceW(scm, "ParagonAPFSMounter", 0x0004)
            if not svc:
                advapi32.CloseServiceHandle(scm)
                self.frame_paragon.pack_forget()
                return

            status = SERVICE_STATUS()
            ok = advapi32.QueryServiceStatus(svc, ctypes.byref(status))
            advapi32.CloseServiceHandle(svc)
            advapi32.CloseServiceHandle(scm)

            if ok and status.dwCurrentState == 4:
                self.frame_paragon.pack(fill=tk.X, padx=10, pady=(12, 0))
                self.lbl_paragon.config(text="⚠️ Paragon Service: Running", fg=self.colors["accent_amber"])
                self.btn_toggle_paragon.config(text="Stop Paragon Service (Free Drive)", state=tk.NORMAL)
            elif ok and status.dwCurrentState == 1:
                self.frame_paragon.pack(fill=tk.X, padx=10, pady=(12, 0))
                self.lbl_paragon.config(text="✓ Paragon Service: Stopped", fg=self.colors["accent_green"])
                self.btn_toggle_paragon.config(text="Start Paragon Service", state=tk.NORMAL)
            else:
                self.frame_paragon.pack_forget()
        except Exception:
            self.frame_paragon.pack_forget()

    def toggle_paragon_service(self):
        """Stop or start ParagonAPFSMounter."""
        try:
            res = subprocess.run(["sc.exe", "query", "ParagonAPFSMounter"], capture_output=True, text=True, timeout=3)
            if "RUNNING" in res.stdout:
                subprocess.run(["net.exe", "stop", "ParagonAPFSMounter"], capture_output=True, timeout=10)
                messagebox.showinfo("Paragon Service", "Paragon APFS Mounter service stopped.\nLocks on physical USB drives released.")
            else:
                subprocess.run(["net.exe", "start", "ParagonAPFSMounter"], capture_output=True, timeout=10)
            self.check_paragon_service()
        except Exception as e:
            messagebox.showerror("Service Error", f"Could not toggle Paragon service: {e}")

    def refresh_drives(self):
        """Scan Windows for physical disk drives and populate the sidebar."""
        self.lbl_status.config(text="Scanning physical drives...")
        self.drive_tree.delete(*self.drive_tree.get_children())
        self.check_paragon_service()

        def _scan():
            drives = list_physical_drives()
            self.root.after(0, lambda: self._populate_drives(drives))

        threading.Thread(target=_scan, daemon=True).start()

    def _populate_drives(self, drives: List[Dict[str, Any]]):
        self.current_drives = drives
        apfs_drive_id = None

        for d in drives:
            idx = d.get("Index", 0)
            model = d.get("Model", f"Physical Drive {idx}")
            has_apfs = d.get("HasAPFS", False)
            size_gb = round(d.get("Size", 0) / (1024**3), 1)

            if has_apfs:
                label = f"Disk {idx}: {model} ({size_gb} GB) ⭐ [APFS - Mac]"
            else:
                label = f"Disk {idx}: {model} ({size_gb} GB) [Windows NTFS]"

            node = self.drive_tree.insert("", tk.END, iid=f"disk_{idx}", text=label)
            if has_apfs and apfs_drive_id is None:
                apfs_drive_id = f"disk_{idx}"

        if not apfs_drive_id:
            self.lbl_status.config(text="No APFS drive detected. Connect your USB drive and click 'Refresh Physical Drives'.")
        else:
            self.lbl_status.config(text=f"Found {len(drives)} physical drives. APFS drive detected!")

        # If an APFS drive was found (e.g. ADATA HD680 on Disk 1), auto-select it!
        if apfs_drive_id:
            self.drive_tree.selection_set(apfs_drive_id)
            self._on_drive_selected(None)

    def _on_drive_selected(self, event):
        sel = self.drive_tree.selection()
        if not sel:
            return
        disk_key = sel[0]  # e.g. "disk_1"
        if not disk_key.startswith("disk_"):
            return
        disk_idx = int(disk_key.split("_")[1])

        # Check if user selected internal Windows drive without APFS
        d_info = next((d for d in self.current_drives if d.get("Index") == disk_idx), None)
        if d_info and not d_info.get("HasAPFS", False):
            model = d_info.get("Model", f"Disk {disk_idx}")
            messagebox.showinfo(
                "Windows System Drive",
                f"Disk {disk_idx} ({model}) is your internal Windows drive, not an Apple APFS disk.\n\n"
                "Please connect your external APFS hard drive (e.g. ADATA HD680) via USB, "
                "then click 'Refresh Physical Drives'."
            )
            return

        self.lbl_status.config(text=f"Opening physical drive Disk {disk_idx}...")
        self.root.config(cursor="watch")

        def _open():
            try:
                summary = engine.open_physical_drive(disk_idx)
                self.root.after(0, lambda: self._on_session_loaded(summary))
            except Exception as e:
                self.root.after(0, lambda: self._on_open_error(str(e)))

        threading.Thread(target=_open, daemon=True).start()

    def open_image_dialog(self):
        file_path = filedialog.askopenfilename(
            title="Select Apple APFS Disk Image",
            filetypes=[
                ("Apple APFS Images", "*.dmg;*.img;*.raw;*.bin;*.vmdk"),
                ("All files", "*.*")
            ]
        )
        if not file_path:
            return

        self.lbl_status.config(text=f"Opening image {os.path.basename(file_path)}...")
        self.root.config(cursor="watch")

        def _open():
            try:
                summary = engine.open_image_file(file_path)
                self.root.after(0, lambda: self._on_session_loaded(summary))
            except Exception as e:
                self.root.after(0, lambda: self._on_open_error(str(e)))

        threading.Thread(target=_open, daemon=True).start()

    def _on_session_loaded(self, summary: Dict[str, Any]):
        self.root.config(cursor="")
        self.volume_tree.delete(*self.volume_tree.get_children())
        volumes = summary.get("volumes", [])

        if not volumes:
            messagebox.showwarning("No Volumes", "The container opened, but no APFS volumes were detected.")
            return

        first_vol_id = None
        for v in volumes:
            v_idx = v["index"]
            name = v["name"]
            is_enc = v["is_encrypted"]
            role = v.get("role", "Data")
            label = f"{name} ({role})"
            if is_enc:
                label += " 🔒 [Encrypted]"

            node = self.volume_tree.insert("", tk.END, iid=f"vol_{v_idx}", text=label)
            if first_vol_id is None:
                first_vol_id = f"vol_{v_idx}"

        self.lbl_status.config(text=f"APFS Container loaded. {len(volumes)} volumes found.")

        # Select first volume
        if first_vol_id:
            self.volume_tree.selection_set(first_vol_id)
            self._on_volume_selected(None)

    def _on_open_error(self, err_msg: str):
        self.root.config(cursor="")
        self.lbl_status.config(text="Failed to open drive.")

        if "The system cannot find the file specified" in err_msg or "error: (2," in err_msg:
            messagebox.showwarning(
                "Drive Disconnected",
                "The selected physical drive is currently disconnected or in power-save mode.\n\n"
                "Please reconnect your external USB drive and click 'Refresh Physical Drives'."
            )
            return

        if "Access is denied" in err_msg or "Permission" in err_msg or not is_admin():
            if messagebox.askyesno(
                "Administrator Rights Needed",
                f"Windows restricted raw sector access:\n\n{err_msg}\n\n"
                "Would you like to restart the application as Administrator to access this physical drive?"
            ):
                self.elevate_to_admin()
                return

        messagebox.showerror(
            "APFS Drive Error",
            f"Unable to read APFS partition:\n\n{err_msg}\n\n"
            "Tip: If Paragon APFS for Windows is installed, click 'Stop Paragon Service' in the sidebar to release device locks."
        )

    def _on_volume_selected(self, event):
        sel = self.volume_tree.selection()
        if not sel:
            return
        vol_idx = int(sel[0].split("_")[1])
        self.active_vol_idx = vol_idx

        # Check encryption
        session_summary = engine.get_session_summary()
        vol = session_summary["volumes"][vol_idx]
        
        if vol["is_encrypted"] and not vol["is_unlocked"]:
            self.btn_unlock.config(state=tk.NORMAL)
            self.btn_export_all.config(state=tk.DISABLED)
            self.unlock_selected_volume()
            return
        else:
            self.btn_unlock.config(state=tk.DISABLED)
            self.btn_export_all.config(state=tk.NORMAL)

        # Reset history
        self.current_path = "/"
        self.history = ["/"]
        self.history_idx = 0
        self.navigate_to("/")

    def unlock_selected_volume(self):
        session_summary = engine.get_session_summary()
        vol = session_summary["volumes"][self.active_vol_idx]
        hint = vol.get("password_hint", "")
        hint_text = f"\nPassword Hint: {hint}" if hint else ""

        pwd = simpledialog.askstring(
            "Encrypted APFS Volume",
            f"Enter password or recovery key for '{vol['name']}':{hint_text}",
            show="*"
        )
        if not pwd:
            return

        try:
            ok = engine.unlock_volume(self.active_vol_idx, pwd)
            if ok:
                messagebox.showinfo("Unlocked", f"Volume '{vol['name']}' unlocked successfully!")
                self.btn_unlock.config(state=tk.DISABLED)
                self.btn_export_all.config(state=tk.NORMAL)
                self.navigate_to("/")
            else:
                messagebox.showerror("Unlock Failed", "Invalid password or recovery key.")
        except Exception as e:
            messagebox.showerror("Unlock Error", str(e))

    def navigate_to(self, path: str, add_history: bool = True):
        self.root.config(cursor="watch")
        self.lbl_status.config(text=f"Reading {path}...")

        def _load():
            try:
                data = engine.list_directory(self.active_vol_idx, path)
                self.root.after(0, lambda: self._on_directory_loaded(data, add_history))
            except Exception as e:
                self.root.after(0, lambda: self._on_dir_error(str(e)))

        threading.Thread(target=_load, daemon=True).start()

    def _on_directory_loaded(self, data: Dict[str, Any], add_history: bool):
        self.root.config(cursor="")
        self.current_path = data["current_path"]
        self.path_var.set(self.current_path)
        self.current_items = data["items"]

        if add_history and (self.history[self.history_idx] != self.current_path):
            self.history = self.history[:self.history_idx + 1]
            self.history.append(self.current_path)
            self.history_idx = len(self.history) - 1

        self.btn_back.config(state=tk.NORMAL if self.history_idx > 0 else tk.DISABLED)
        self.btn_forward.config(state=tk.NORMAL if self.history_idx < len(self.history) - 1 else tk.DISABLED)
        self.btn_up.config(state=tk.NORMAL if self.current_path != "/" else tk.DISABLED)
        self.btn_export_zip.config(state=tk.NORMAL if self.current_path != "/" else tk.DISABLED)

        self._render_files()
        self.lbl_status.config(text=f"Browsing: {self.current_path}")

    def _on_dir_error(self, err_msg: str):
        self.root.config(cursor="")
        self.lbl_status.config(text="Directory read error.")
        messagebox.showerror("Error", f"Could not read directory:\n{err_msg}")

    def _render_files(self):
        self.file_tree.delete(*self.file_tree.get_children())
        query = self.search_var.get().strip().lower()
        if query == "filter files...":
            query = ""

        items = [it for it in self.current_items if query in it["name"].lower()]

        # Sort items
        def _get_sort_val(it):
            val = it.get(self.sort_col, "")
            if self.sort_col == "size":
                return it.get("size", 0)
            return str(val).lower()

        # Folders first
        items.sort(key=lambda it: (not it["is_dir"], _get_sort_val(it)), reverse=self.sort_reverse)

        for item in items:
            name = item["name"]
            is_dir = item["is_dir"]
            
            # Format size and date
            size_str = "" if is_dir else self._format_size(item["size"])
            date_str = item["mtime"][:19].replace("T", " ") if item.get("mtime") else "-"
            kind_str = "Folder" if is_dir else item["kind"].capitalize()
            
            # Icon prefix
            prefix = "📁 " if is_dir else ("🔗 " if item["is_symlink"] else "📄 ")
            display_name = prefix + name

            self.file_tree.insert(
                "", tk.END, iid=item["path"],
                values=(display_name, date_str, kind_str, size_str)
            )

        self.lbl_items_info.config(text=f"{len(items)} items")

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes == 0:
            return "0 B"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    def _sort_by(self, col: str):
        if self.sort_col == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col = col
            self.sort_reverse = False
        self._render_files()

    def _on_search_change(self, *args):
        self._render_files()

    def go_back(self):
        if self.history_idx > 0:
            self.history_idx -= 1
            self.navigate_to(self.history[self.history_idx], add_history=False)

    def go_forward(self):
        if self.history_idx < len(self.history) - 1:
            self.history_idx += 1
            self.navigate_to(self.history[self.history_idx], add_history=False)

    def go_up(self):
        if self.current_path != "/":
            parent = os.path.dirname(self.current_path.rstrip("/")) or "/"
            self.navigate_to(parent)

    def _on_item_double_click(self, event):
        sel = self.file_tree.selection()
        if not sel:
            return
        item_path = sel[0]
        # Find item in current_items
        item = next((it for it in self.current_items if it["path"] == item_path), None)
        if not item:
            return

        if item["is_dir"]:
            self.navigate_to(item["path"])
        else:
            self.preview_selected_file()

    def select_all_items(self, event=None):
        """Select all items currently visible in the file tree (Ctrl+A)."""
        children = self.file_tree.get_children()
        if children:
            self.file_tree.selection_set(children)
            self._on_item_selected(None)
        return "break"

    def _on_item_selected(self, event):
        sel = self.file_tree.selection()
        if sel:
            count = len(sel)
            if count == 1:
                item_path = sel[0]
                item = next((it for it in self.current_items if it["path"] == item_path), None)
                if item and item["is_dir"]:
                    display_name = item["name"]
                    if len(display_name) > 16:
                        display_name = display_name[:14] + "..."
                    self.btn_export_file.config(text=f"⬇ Copy Folder '{display_name}'...", state=tk.NORMAL)
                else:
                    self.btn_export_file.config(text="⬇ Save Selected File...", state=tk.NORMAL)
            else:
                self.btn_export_file.config(text=f"⬇ Copy {count} Selected Items...", state=tk.NORMAL)
        else:
            self.btn_export_file.config(text="⬇ Save Selected to Windows...", state=tk.DISABLED)

    def _on_right_click(self, event):
        iid = self.file_tree.identify_row(event.y)
        if iid:
            if iid not in self.file_tree.selection():
                self.file_tree.selection_set(iid)
                self._on_item_selected(None)
            self.context_menu.post(event.x_root, event.y_root)

    def copy_apfs_path(self):
        sel = self.file_tree.selection()
        if sel:
            self.root.clipboard_clear()
            self.root.clipboard_append(sel[0])

    def export_entire_volume(self):
        """Copy ALL files and folders from the current APFS volume to a Windows directory."""
        if self.active_vol_idx is None:
            messagebox.showwarning("No Volume Selected", "Please select an APFS volume first.")
            return

        summary = engine.get_session_summary()
        vols = summary.get("volumes", [])
        vol_name = "APFS Volume"
        if 0 <= self.active_vol_idx < len(vols):
            vol_name = vols[self.active_vol_idx].get("name", "APFS Volume")

        dest_dir = filedialog.askdirectory(
            title=f"Select Destination Folder on Windows to Copy ALL Files from '{vol_name}'"
        )
        if not dest_dir:
            return

        dlg = TransferProgressDialog(
            self.root,
            title="Copying Entire APFS Drive to Windows",
            total_label=f"Copying all files from '{vol_name}' to:\n{dest_dir}"
        )

        def _run_copy():
            try:
                stats = engine.copy_volume_all(
                    vol_idx=self.active_vol_idx,
                    dest_parent_dir=dest_dir,
                    create_subfolder=True,
                    skip_system_hidden=True,
                    progress_callback=lambda fname, fc, bc: self.root.after(
                        0, lambda: dlg.update_stats(fname, fc, bc)
                    ),
                    cancel_event=dlg.cancel_event
                )
                self.root.after(0, lambda: self._on_copy_finished(dlg, stats, dest_dir))
            except Exception as e:
                self.root.after(0, lambda: (dlg.finish({}, dest_dir), messagebox.showerror("Copy Error", f"Failed to copy files:\n{e}")))

        threading.Thread(target=_run_copy, daemon=True).start()

    def export_selected_file(self):
        """Copy single file, single folder, or multiple selected items to Windows."""
        sel = self.file_tree.selection()
        if not sel:
            messagebox.showinfo("No Selection", "Please select one or more files or folders to copy.")
            return

        if len(sel) == 1:
            item_path = sel[0]
            item = next((it for it in self.current_items if it["path"] == item_path), None)
            if not item:
                return

            if not item["is_dir"]:
                # Single file export
                default_name = item["name"]
                dest_target = filedialog.asksaveasfilename(
                    title=f"Save '{default_name}' to Windows",
                    initialfile=default_name
                )
                if not dest_target:
                    return

                dlg = TransferProgressDialog(
                    self.root,
                    title="Saving File to Windows",
                    total_label=f"Saving to:\n{dest_target}"
                )

                def _run_single_file():
                    try:
                        dest_dir = os.path.dirname(dest_target)
                        node = engine.get_file_node(self.active_vol_idx, item_path)
                        stats = {
                            "total_files": 1,
                            "copied_files": 0,
                            "total_bytes": 0,
                            "copied_bytes": 0,
                            "errors": [],
                            "cancelled": False
                        }
                        long_dest = to_windows_long_path(dest_target)
                        engine._copy_single_file(
                            node, long_dest, stats,
                            progress_callback=lambda fname, fc, bc: self.root.after(
                                0, lambda: dlg.update_stats(fname, fc, bc)
                            ),
                            cancel_event=dlg.cancel_event
                        )
                        self.root.after(0, lambda: self._on_copy_finished(dlg, stats, dest_dir))
                    except Exception as e:
                        self.root.after(0, lambda: (dlg.finish({}, os.path.dirname(dest_target)), messagebox.showerror("Save Error", f"Failed to save file:\n{e}")))

                threading.Thread(target=_run_single_file, daemon=True).start()
                return

            else:
                # Single folder export
                folder_name = item["name"]
                dest_parent = filedialog.askdirectory(
                    title=f"Select Destination Folder to Copy '{folder_name}'"
                )
                if not dest_parent:
                    return

                dlg = TransferProgressDialog(
                    self.root,
                    title=f"Copying Folder: {folder_name}",
                    total_label=f"Destination:\n{dest_parent}"
                )

                def _run_single_folder():
                    try:
                        stats = engine.copy_item_to_windows(
                            vol_idx=self.active_vol_idx,
                            apfs_path=item_path,
                            dest_parent_dir=dest_parent,
                            progress_callback=lambda fname, fc, bc: self.root.after(
                                0, lambda: dlg.update_stats(fname, fc, bc)
                            ),
                            cancel_event=dlg.cancel_event
                        )
                        self.root.after(0, lambda: self._on_copy_finished(dlg, stats, dest_parent))
                    except Exception as e:
                        self.root.after(0, lambda: (dlg.finish({}, dest_parent), messagebox.showerror("Copy Error", f"Failed to copy folder:\n{e}")))

                threading.Thread(target=_run_single_folder, daemon=True).start()
                return

        else:
            # Multiple items selected!
            dest_parent = filedialog.askdirectory(
                title=f"Select Destination Folder to Copy {len(sel)} Selected Items"
            )
            if not dest_parent:
                return

            dlg = TransferProgressDialog(
                self.root,
                title=f"Copying {len(sel)} Items to Windows",
                total_label=f"Destination:\n{dest_parent}"
            )

            paths_to_copy = list(sel)

            def _run_multi_copy():
                try:
                    stats = engine.copy_multiple_items_to_windows(
                        vol_idx=self.active_vol_idx,
                        apfs_paths=paths_to_copy,
                        dest_parent_dir=dest_parent,
                        progress_callback=lambda fname, fc, bc: self.root.after(
                            0, lambda: dlg.update_stats(fname, fc, bc)
                        ),
                        cancel_event=dlg.cancel_event
                    )
                    self.root.after(0, lambda: self._on_copy_finished(dlg, stats, dest_parent))
                except Exception as e:
                    self.root.after(0, lambda: (dlg.finish({}, dest_parent), messagebox.showerror("Copy Error", f"Failed to copy items:\n{e}")))

            threading.Thread(target=_run_multi_copy, daemon=True).start()

    def _on_copy_finished(self, dlg: TransferProgressDialog, stats: dict, dest_dir: str):
        dlg.finish(stats, dest_dir)
        self.root.config(cursor="")

        if stats.get("cancelled"):
            self.lbl_status.config(text="Copy cancelled by user.")
            messagebox.showinfo(
                "Copy Cancelled",
                f"Transfer was cancelled.\n\n"
                f"Files copied before cancellation: {stats.get('copied_files', 0):,}\n"
                f"Data transferred: {self._format_size(stats.get('copied_bytes', 0))}\n\n"
                f"Destination: {dest_dir}"
            )
            return

        copied_files = stats.get("copied_files", 0)
        copied_bytes = stats.get("copied_bytes", 0)
        errors = stats.get("errors", [])
        err_count = len(errors)

        size_str = self._format_size(copied_bytes)
        self.lbl_status.config(text=f"Copied {copied_files:,} files ({size_str}) successfully.")

        if err_count == 0:
            msg = (
                f"Successfully copied {copied_files:,} files ({size_str}) to Windows!\n\n"
                f"Destination:\n{dest_dir}\n\n"
                f"Would you like to open the destination folder in Windows Explorer?"
            )
            if messagebox.askyesno("Transfer Complete! 🎉", msg):
                try:
                    os.startfile(dest_dir)
                except Exception:
                    pass
        else:
            sample_errs = "\n".join(f"• {e[0]}: {e[1]}" for e in errors[:5])
            if err_count > 5:
                sample_errs += f"\n... and {err_count - 5} more."

            msg = (
                f"Copied {copied_files:,} files ({size_str}).\n\n"
                f"Note: {err_count} items had errors or were locked:\n{sample_errs}\n\n"
                f"Would you like to open the destination folder in Windows Explorer?"
            )
            if messagebox.askyesno("Transfer Completed with Warnings", msg):
                try:
                    os.startfile(dest_dir)
                except Exception:
                    pass

    def export_folder_zip(self):
        """Export current folder as a streaming ZIP file without high memory usage."""
        if self.current_path == "/":
            messagebox.showinfo("ZIP Export", "To copy the entire drive, please click '⚡ Copy ENTIRE Drive...' in the sidebar for fastest transfer.")
            return

        folder_name = os.path.basename(self.current_path.rstrip("/"))
        dest_zip = filedialog.asksaveasfilename(
            title=f"Export '{folder_name}' as ZIP Archive",
            initialfile=f"{folder_name}.zip",
            filetypes=[("ZIP Archive", "*.zip")]
        )
        if not dest_zip:
            return

        dlg = TransferProgressDialog(
            self.root,
            title=f"Creating ZIP: {folder_name}.zip",
            total_label=f"Saving archive to:\n{dest_zip}"
        )

        def _zip():
            copied_files = 0
            copied_bytes = 0
            cancelled = False
            errors = []
            try:
                node = engine.get_file_node(self.active_vol_idx, self.current_path)
                with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                    def _add(curr_node, rel):
                        nonlocal copied_files, copied_bytes, cancelled
                        if dlg.cancel_event.is_set():
                            cancelled = True
                            return
                        inode = get_inode(curr_node)
                        for entry in inode.iterdir():
                            if dlg.cancel_event.is_set():
                                cancelled = True
                                return
                            child_rel = f"{rel}/{entry.name}".lstrip("/")
                            is_d = entry.is_dir() if callable(getattr(entry, 'is_dir', None)) else bool(getattr(entry, 'is_dir', False))
                            is_sym = entry.is_symlink() if callable(getattr(entry, 'is_symlink', None)) else bool(getattr(entry, 'is_symlink', False))

                            if is_d and not is_sym:
                                zf.writestr(child_rel + "/", "")
                                _add(entry, child_rel)
                            elif not is_sym:
                                try:
                                    child_inode = get_inode(entry)
                                    with child_inode.open() as s:
                                        chunk_size = 2 * 1024 * 1024  # 2MB buffer
                                        with zf.open(child_rel, "w") as zdest:
                                            while True:
                                                if dlg.cancel_event.is_set():
                                                    cancelled = True
                                                    return
                                                chunk = s.read(chunk_size)
                                                if not chunk:
                                                    break
                                                zdest.write(chunk)
                                                copied_bytes += len(chunk)
                                                self.root.after(0, lambda fn=entry.name, fc=copied_files, bc=copied_bytes: dlg.update_stats(fn, fc, bc))
                                    copied_files += 1
                                except Exception as fe:
                                    errors.append((entry.name, str(fe)))
                    _add(node, "")

                if cancelled:
                    try:
                        if os.path.exists(dest_zip):
                            os.remove(dest_zip)
                    except Exception:
                        pass

                stats = {
                    "copied_files": copied_files,
                    "copied_bytes": copied_bytes,
                    "errors": errors,
                    "cancelled": cancelled
                }
                self.root.after(0, lambda: self._on_copy_finished(dlg, stats, os.path.dirname(dest_zip)))
            except Exception as e:
                self.root.after(0, lambda: (dlg.finish({}, os.path.dirname(dest_zip)), messagebox.showerror("ZIP Export Error", str(e))))

        threading.Thread(target=_zip, daemon=True).start()

    def preview_selected_file(self):
        sel = self.file_tree.selection()
        if not sel:
            return
        item_path = sel[0]
        try:
            preview = engine.preview_file(self.active_vol_idx, item_path)
            self._show_preview_window(item_path, preview)
        except Exception as e:
            messagebox.showerror("Preview Error", f"Unable to preview file:\n{e}")

    def _show_preview_window(self, file_path: str, preview: Dict[str, Any]):
        win = tk.Toplevel(self.root)
        win.title(f"Preview: {os.path.basename(file_path)}")
        win.geometry("700x500")
        win.configure(bg=self.colors["bg_dark"])

        meta = preview.get("metadata", {})
        info_frame = tk.Frame(win, bg=self.colors["bg_sidebar"], padx=12, pady=8)
        info_frame.pack(side=tk.TOP, fill=tk.X)

        info_text = f"File: {meta.get('name')}  |  Size: {self._format_size(meta.get('size', 0))}  |  Kind: {meta.get('kind')}"
        lbl_info = tk.Label(info_frame, text=info_text, font=("Segoe UI", 9, "bold"), bg=self.colors["bg_sidebar"], fg=self.colors["fg_primary"])
        lbl_info.pack(side=tk.LEFT)

        txt_frame = tk.Frame(win, bg=self.colors["bg_dark"])
        txt_frame.pack(fill=tk.BOTH, expand=True)

        txt = tk.Text(
            txt_frame, font=("Consolas", 10), bg=self.colors["bg_dark"],
            fg=self.colors["fg_primary"], insertbackground="#fff", wrap=tk.NONE
        )
        scroll_txt_y = ttk.Scrollbar(txt_frame, orient=tk.VERTICAL, command=txt.yview)
        scroll_txt_x = ttk.Scrollbar(txt_frame, orient=tk.HORIZONTAL, command=txt.xview)
        txt.configure(yscrollcommand=scroll_txt_y.set, xscrollcommand=scroll_txt_x.set)

        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_txt_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_txt_x.pack(side=tk.BOTTOM, fill=tk.X)

        if preview.get("is_text") and preview.get("text"):
            txt.insert(tk.END, preview["text"])
        else:
            txt.insert(tk.END, "--- HEX DUMP (First 4KB) ---\n\n" + preview.get("hex", "No data"))

        txt.config(state=tk.DISABLED)


def main():
    root = tk.Tk()
    
    # Try setting window icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception:
            pass

    app = APFSDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
