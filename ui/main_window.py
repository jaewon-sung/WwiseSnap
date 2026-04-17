"""
WwiseSnap Main Window
Dark-themed GUI with connection bar, selected object display, and tabview.
"""

import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.waapi_client import get_client
from core.snapshot_manager import get_manager
from ui.snapshot_tab import SnapshotTab


# Apple-style Color Palette
COLOR_BG_DARK = "#1c1c1e"       # iOS Dark Background
COLOR_BG_MID = "#2c2c2e"        # iOS Dark Grouped Background
COLOR_ACCENT = "#3a3a3c"        # iOS Dark Separator / Gray
COLOR_SELECTED = "#007aff"      # iOS Blue
COLOR_TEXT = "#f5f5f7"          # Apple Silver/White
COLOR_TEXT_DIM = "#8e8e93"      # iOS Gray
COLOR_GREEN = "#34c759"         # iOS Green
COLOR_YELLOW = "#ffcc00"        # iOS Yellow
COLOR_RED = "#ff3b30"           # iOS Red
COLOR_ORANGE = "#ff9500"        # iOS Orange

POLL_INTERVAL_MS = 1500  # 1.5 seconds


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self._polling = False
        self._poll_thread: threading.Thread | None = None
        self._selected_objects: list[dict] = []

        self._setup_window()
        self._build_ui()
        self._start_polling()

    def _setup_window(self):
        self.title("WwiseSnap")
        self.geometry("1100x700")  # Slightly larger for Apple-style spacing
        self.minsize(800, 550)
        self.configure(fg_color=COLOR_BG_DARK)

        # Window icon text (no .ico needed)
        self.iconbitmap(default="")

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ── Title Bar ─────────────────────────────────────────────────────
        title_bar = ctk.CTkFrame(self, fg_color=COLOR_BG_DARK, height=45, corner_radius=0)
        title_bar.grid(row=0, column=0, sticky="ew")
        title_bar.grid_columnconfigure(1, weight=1)
        title_bar.grid_propagate(False)

        title_lbl = ctk.CTkLabel(
            title_bar,
            text="  WwiseSnap",
            font=ctk.CTkFont(family="SF Pro Display", size=18, weight="bold"),
            text_color=COLOR_TEXT,
            anchor="w",
        )
        title_lbl.grid(row=0, column=0, padx=12, pady=8, sticky="w")

        # Top-right Management Buttons
        btn_container = ctk.CTkFrame(title_bar, fg_color="transparent")
        btn_container.grid(row=0, column=2, padx=12, pady=6, sticky="e")

        self._btn_import = ctk.CTkButton(
            btn_container,
            text="Import JSON",
            font=ctk.CTkFont(size=11),
            fg_color=COLOR_BG_MID,
            hover_color=COLOR_ACCENT,
            width=90,
            height=28,
            corner_radius=6,
            command=lambda: self._snapshot_tab._on_import(),
        )
        self._btn_import.pack(side="left", padx=4)

        self._btn_export = ctk.CTkButton(
            btn_container,
            text="Export JSON",
            font=ctk.CTkFont(size=11),
            fg_color=COLOR_BG_MID,
            hover_color=COLOR_ACCENT,
            width=90,
            height=28,
            corner_radius=6,
            command=lambda: self._snapshot_tab._on_export(),
        )
        self._btn_export.pack(side="left", padx=4)

        # ── Connection Bar ─────────────────────────────────────────────────
        conn_bar = ctk.CTkFrame(self, fg_color=COLOR_BG_MID, height=52, corner_radius=0)
        conn_bar.grid(row=1, column=0, sticky="ew")
        conn_bar.grid_columnconfigure(3, weight=1)
        conn_bar.grid_propagate(False)

        # Status dot (canvas circle)
        self._status_canvas = tk.Canvas(
            conn_bar, width=16, height=16,
            bg=COLOR_BG_MID, highlightthickness=0,
        )
        self._status_canvas.grid(row=0, column=0, padx=(16, 6), pady=16)
        self._status_dot = self._status_canvas.create_oval(3, 3, 13, 13, fill=COLOR_RED, outline="")

        # Connect button
        self._btn_connect = ctk.CTkButton(
            conn_bar,
            text="Connect",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLOR_SELECTED,
            hover_color="#005ecb",
            width=100,
            height=32,
            corner_radius=8,
            command=self._on_connect,
        )
        self._btn_connect.grid(row=0, column=1, padx=4, pady=10)

        # Status label
        self._status_label = ctk.CTkLabel(
            conn_bar,
            text="Disconnected",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        )
        self._status_label.grid(row=0, column=2, padx=12, pady=11, sticky="w")

        # DB indicator
        self._file_indicator = ctk.CTkLabel(
            conn_bar,
            text="DB: snapshots.db",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_GREEN,
            anchor="e",
        )
        self._file_indicator.grid(row=0, column=3, padx=16, pady=11, sticky="e")

        # Selected object bar
        selected_bar = ctk.CTkFrame(self, fg_color="#121214", height=32, corner_radius=0)
        selected_bar.grid(row=2, column=0, sticky="ew")
        selected_bar.grid_columnconfigure(1, weight=1)
        selected_bar.grid_propagate(False)

        sel_prefix = ctk.CTkLabel(
            selected_bar,
            text="  Selected Object:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLOR_TEXT_DIM,
        )
        sel_prefix.grid(row=0, column=0, padx=(12, 6), pady=6)

        self._selected_label = ctk.CTkLabel(
            selected_bar,
            text="—",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_YELLOW,
            anchor="w",
        )
        self._selected_label.grid(row=0, column=1, padx=(0, 16), pady=6, sticky="w")

        # ── Tab View ──────────────────────────────────────────────────────
        self._tabview = ctk.CTkTabview(
            self,
            fg_color=COLOR_BG_DARK,
            segmented_button_fg_color=COLOR_ACCENT,
            segmented_button_selected_color=COLOR_SELECTED,
            segmented_button_selected_hover_color=COLOR_SELECTED,
            segmented_button_unselected_color=COLOR_ACCENT,
            segmented_button_unselected_hover_color="#1a3a6e",
            text_color=COLOR_TEXT,
            corner_radius=8,
        )
        self._tabview.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.grid_rowconfigure(3, weight=1)

        # Add tabs
        self._tabview.add("Snapshots")
        self._tabview.add("About")

        # Configure Snapshots tab
        snap_tab = self._tabview.tab("Snapshots")
        snap_tab.grid_columnconfigure(0, weight=1)
        snap_tab.grid_rowconfigure(0, weight=1)

        self._snapshot_tab = SnapshotTab(snap_tab, app_ref=self, fg_color="transparent")
        self._snapshot_tab.grid(row=0, column=0, sticky="nsew")

        # About tab
        about_tab = self._tabview.tab("About")
        about_tab.grid_columnconfigure(0, weight=1)
        about_tab.grid_rowconfigure(0, weight=1)

        about_frame = ctk.CTkFrame(about_tab, fg_color=COLOR_BG_MID, corner_radius=8)
        about_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        about_frame.grid_columnconfigure(0, weight=1)
        about_frame.grid_rowconfigure(0, weight=1)

        about_text = (
            "WwiseSnap  —  Wwise Parameter Snapshot Tool\n\n"
            "Connects to Wwise via WAAPI (ws://127.0.0.1:8080/waapi)\n"
            "and captures scalar property snapshots of selected objects.\n\n"
            "Supports: Properties, Override flags, References,\n"
            "Randomizer modifiers, Attenuation curves\n\n"
            "Note: RTPC and Effects are not supported\n"
            "(WAAPI does not provide a write API for RTPC curves)\n\n"
            "Built with Python 3.11 + customtkinter"
        )
        about_lbl = ctk.CTkLabel(
            about_frame,
            text=about_text,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT,
            justify="left",
            anchor="nw",
        )
        about_lbl.grid(row=0, column=0, padx=20, pady=20, sticky="nw")

    # ── Connection ─────────────────────────────────────────────────────────

    def _on_connect(self):
        """Handle connect/disconnect button."""
        client = get_client()
        if client.is_connected():
            client.disconnect()
            self._update_status(False, "Disconnected")
        else:
            self._btn_connect.configure(text="Connecting...", state="disabled")
            self.update_idletasks()
            threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        client = get_client()
        client.set_status_callback(self._on_status_change)
        ok = client.connect()
        self.after(0, self._on_connect_done, ok)

    def _on_connect_done(self, ok: bool):
        self._btn_connect.configure(state="normal")
        if ok:
            self._btn_connect.configure(text="Disconnect")
            client = get_client()
            project = client.get_project_name() or "Wwise"
            version = client.get_wwise_version()
            if version:
                status_msg = f"Connected — {project} (v{version})"
            else:
                status_msg = f"Connected — {project}"
            self._update_status(True, status_msg)
        else:
            self._btn_connect.configure(text="Connect")
            self._update_status(False, "Connection failed")

    def _on_status_change(self, connected: bool, message: str):
        """Called from WAAPI client on status changes (may be from background thread)."""
        self.after(0, self._update_status, connected, message)

    def _update_status(self, connected: bool, message: str):
        """Update UI status indicators (must be called on main thread)."""
        dot_color = COLOR_GREEN if connected else COLOR_RED
        self._status_canvas.itemconfig(self._status_dot, fill=dot_color)
        self._status_label.configure(
            text=message,
            text_color=COLOR_TEXT if connected else COLOR_TEXT_DIM,
        )
        if connected:
            self._btn_connect.configure(text="Disconnect")
        else:
            self._btn_connect.configure(text="Connect")

    # ── File Management ────────────────────────────────────────────────────

    def _on_open_file(self):
        """No-op: DB file is fixed. Button kept for layout compatibility."""
        from core.snapshot_manager import get_manager as _get_manager
        manager = _get_manager()
        messagebox.showinfo(
            "WwiseSnap",
            f"Snapshots are stored in:\n{manager.get_file_display()}\n\n"
            "Use Export JSON / Import JSON in the Snapshots tab to transfer data.",
        )

    # ── Background Polling ─────────────────────────────────────────────────

    def _start_polling(self):
        """Start the background polling loop."""
        self._polling = True
        self._poll_cycle()

    def _poll_cycle(self):
        """Schedule one poll on a background thread, then reschedule."""
        if not self._polling:
            return
        threading.Thread(target=self._poll_selected, daemon=True).start()

    def _poll_selected(self):
        """Background thread: get selected objects from Wwise."""
        client = get_client()
        if not client.is_connected():
            # Try a quiet check
            self.after(POLL_INTERVAL_MS, self._poll_cycle)
            return

        objects = client.get_selected_objects()
        self.after(0, self._on_poll_result, objects)
        self.after(POLL_INTERVAL_MS, self._poll_cycle)

    def _on_poll_result(self, objects: list[dict]):
        """Update selected object label (main thread)."""
        self._selected_objects = objects
        if not objects:
            self._selected_label.configure(text="—", text_color=COLOR_TEXT_DIM)
            return

        obj = objects[0]
        name = obj.get("name", "?")
        path = obj.get("path", "")
        obj_type = obj.get("type", "")

        if len(objects) > 1:
            display = f"{name}  ({obj_type})  +{len(objects)-1} more  |  {path}"
        else:
            display = f"{name}  ({obj_type})  |  {path}"

        self._selected_label.configure(text=display, text_color=COLOR_YELLOW)

    def on_close(self):
        """Cleanup on window close."""
        self._polling = False
        client = get_client()
        if client.is_connected():
            client.disconnect()
        self.destroy()
