"""
WwiseSnap Snapshot Tab
Left panel: snapshot list with Save/Restore/Delete/Export/Import buttons
Right panel: tabbed parameter detail view
"""

import threading
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox, simpledialog, filedialog

from core.snapshot_manager import get_manager
from core.waapi_client import get_client


# Apple-style Color Palette (Synced with main_window)
COLOR_BG_DARK = "#1c1c1e"
COLOR_BG_MID = "#2c2c2e"
COLOR_ACCENT = "#3a3a3c"
COLOR_SELECTED = "#007aff"
COLOR_TEXT = "#f5f5f7"
COLOR_TEXT_DIM = "#8e8e93"
COLOR_GREEN = "#34c759"
COLOR_YELLOW = "#ffcc00"
COLOR_RED = "#ff3b30"
COLOR_BLUE = "#007aff"

# ── Detail tab configuration ──────────────────────────────────────────────

GROUP_TO_TAB = {
    # ── General ──────────────────────────────────────────────────────────────
    "Voice":   "General",
    "General": "General",
    "Random":  "General",   # Weight property (shown in General for all types)
    # ── Routing ──────────────────────────────────────────────────────────────
    "Output Bus":                            "Routing",
    "User-Defined Auxiliary Sends":          "Routing",
    "User-Defined Auxiliary Sends/Send 0":   "Routing",
    "User-Defined Auxiliary Sends/Send 1":   "Routing",
    "User-Defined Auxiliary Sends/Send 2":   "Routing",
    "User-Defined Auxiliary Sends/Send 3":   "Routing",
    "Game-Defined Auxiliary Sends":          "Routing",
    "Early Reflections":                     "Routing",
    "Audio Device":                          "Routing",
    # ── Positioning ──────────────────────────────────────────────────────────
    # Note: "Listener Relative Routing/3D Position" and "3D Position" are
    # intentionally excluded — their data (waypoints) lives in Position child
    # objects that can't be fully accessed via WAAPI.
    "Listener Relative Routing":             "Positioning",
    "Listener Relative Routing/Attenuation": "Positioning",
    "Spatialization":                        "Positioning",
    "Attenuation":                           "Positioning",
    # ── Advanced ─────────────────────────────────────────────────────────────
    "Virtual Voice":         "Advanced",
    "Playback Priority":     "Advanced",
    "Playback Limit":        "Advanced",
    "HDR":                   "Advanced",
    "Envelope Tracking":     "Advanced",
    "MIDI":                  "Advanced",
    "MIDI Events":           "Advanced",
    "Note Tracking":         "Advanced",
    "Filters":               "Advanced",
    "Transformation":        "Advanced",   # MIDI transposition/velocity (not spatial)
    # ── Audio Bus tab (AudioBus-specific) ────────────────────────────────────
    "Auto-Ducking":                     "Audio Bus",
    "Dynamics":                         "Audio Bus",
    "Window Top Output Game Parameter": "Audio Bus",
    # ── Random Container / Sequence Container tab ─────────────────────────────
    # "Loop" group routes to Random Container; Sound-specific loop props
    # (IsLoopingEnabled, LoopCount, IsLoopingInfinite) are overridden in
    # PROP_TO_TAB to go to "Sound SFX" instead.
    "Loop":        "Random Container",
    "Mode":        "Random Container",
    "Transitions": "Random Container",
    "Transition":  "Random Container",
    "Playlist":    "Random Container",
    # ── Switch Container tab ──────────────────────────────────────────────────
    "Switch Container":            "Switch Container",
    "Switch Group or State Group": "Switch Container",
    "Default Switch or State":     "Switch Container",
    # ── Blend Container tab ───────────────────────────────────────────────────
    "Blend Container": "Blend Container",
    # ── Sound SFX tab ────────────────────────────────────────────────────────
    "Stream": "Sound SFX",   # Streaming settings live in the Sound SFX tab
    # ── Conversion tab ───────────────────────────────────────────────────────
    "Conversion":             "Conversion",
    "Conversion Settings":    "Conversion",
    "Loudness Normalization": "Conversion",
}

# Per-property tab overrides — used for properties whose display.group is
# empty or incorrect (WAAPI doesn't always match the Property Editor tabs).
PROP_TO_TAB: dict[str, str] = {
    # Positioning tab
    "CenterPercentage": "Positioning",
    "SpeakerPanning":   "Positioning",
    # Advanced tab
    "BypassEffect":     "Advanced",
    # Sound SFX tab — loop source settings (group "Loop" normally routes to
    # "Random Container", but for Sound these belong in the Sound SFX tab)
    "IsLoopingEnabled":  "Sound SFX",
    "LoopCount":         "Sound SFX",
    "IsLoopingInfinite": "Sound SFX",
    # Random Container tab — no-group props (WAAPI group is empty)
    "NormalOrShuffle":            "Random Container",
    "RandomAvoidRepeating":       "Random Container",
    "RandomAvoidRepeatingCount":  "Random Container",
    "RestartBeginningOrBackward": "Random Container",   # sibling → Sequence Container
    # Switch Container tab — no-group prop
    "SwitchBehavior": "Switch Container",
    # Blend Container tab — no-group prop
    "BlendBehavior":  "Blend Container",
}

DEFAULT_TAB = "General"
PLACEHOLDER_TABS = set()

# Object-specific tabs in priority order.
# Props like Weight and InitialDelay, and the Randomizer section, belong in
# whichever object-specific tab is available for the current snapshot type.
_OBJECT_TAB_ORDER = [
    "Sound SFX", "Random Container", "Sequence Container",
    "Switch Container", "Blend Container", "Audio Bus", "Auxiliary Bus", "Music",
]
_OBJECT_TAB_SET = set(_OBJECT_TAB_ORDER)

# Props that should appear in the most specific object tab available rather
# than falling back to General.  First match in _OBJECT_TAB_ORDER wins.
PROP_PREFERRED_TABS: dict[str, list[str]] = {
    "Weight":       _OBJECT_TAB_ORDER,
    "InitialDelay": _OBJECT_TAB_ORDER,
}

# Modifier display names (as stored in snapshots) → prop key.
# Used as fallback when rand_name_to_tab lookup fails (e.g. when prop_display
# had no entry for a prop, so display_name was stored as the raw prop key).
_MODIFIER_DISPLAY_TO_PROP: dict[str, str] = {
    "Initial Delay": "InitialDelay",
    "No. of Loops":  "LoopCount",
    "Weight":        "Weight",
}

# Display order for General-tab Randomizer entries.
# Props listed here are sorted first (in order); others follow alphabetically.
_RANDOMIZER_GENERAL_ORDER: dict[str, int] = {
    "Voice Volume":  0,
    "Voice Pitch":   1,
    "Voice LPF":     2,
    "Voice HPF":     3,
    "Make-Up Gain":  4,
}

# Tabs available per Wwise object type. "All" is always first.
# "Attenuation Settings" is always last.
_BASE_TABS   = ["All", "General", "Routing", "Positioning", "Advanced"]
_TAIL_TABS   = ["Attenuation Settings"]

_CONV_TAB  = ["Conversion"]
_MUSIC_TABS = ["Music"]

TYPE_TO_TABS: dict[str, list[str]] = {
    # Bus types
    "AudioBus":                _BASE_TABS + ["Audio Bus"]                      + _TAIL_TABS,
    "AuxBus":                  _BASE_TABS + ["Auxiliary Bus"]                  + _TAIL_TABS,
    # Sound
    "Sound":                   _BASE_TABS + ["Sound SFX"] + _CONV_TAB          + _TAIL_TABS,
    # Container types — all support Conversion override
    "PropertyContainer":       _BASE_TABS + _CONV_TAB                            + _TAIL_TABS,
    "ActorMixer":              _BASE_TABS + _CONV_TAB                            + _TAIL_TABS,  # legacy name
    # RandomSequenceContainer sub-types (resolved at save time via RandomOrSequence property)
    "RandomContainer":         _BASE_TABS + ["Random Container"]   + _CONV_TAB   + _TAIL_TABS,
    "SequenceContainer":       _BASE_TABS + ["Sequence Container"] + _CONV_TAB   + _TAIL_TABS,
    "RandomSequenceContainer": _BASE_TABS + ["Random Container"]   + _CONV_TAB   + _TAIL_TABS,  # fallback
    "SwitchContainer":         _BASE_TABS + ["Switch Container"]   + _CONV_TAB   + _TAIL_TABS,
    "BlendContainer":          _BASE_TABS + ["Blend Container"]    + _CONV_TAB   + _TAIL_TABS,
    # Music types
    "MusicSwitchContainer":    _BASE_TABS + _MUSIC_TABS + _CONV_TAB            + _TAIL_TABS,
    "MusicSegment":            _BASE_TABS + _MUSIC_TABS + _CONV_TAB            + _TAIL_TABS,
    "MusicPlaylistContainer":  _BASE_TABS + _MUSIC_TABS + _CONV_TAB            + _TAIL_TABS,
}
DEFAULT_TABS = _BASE_TABS + _TAIL_TABS


def _tabs_for_type(obj_type: str) -> list[str]:
    return TYPE_TO_TABS.get(obj_type, DEFAULT_TABS)


# When the natural tab isn't available for a type, try the sibling tab.
# Handles Sequence Container ↔ Random Container: they share the same property
# groups (Loop, Mode, Transitions) but use different tab names depending on
# the RandomOrSequence property value.
_TAB_SIBLINGS: dict[str, str] = {
    "Random Container":   "Sequence Container",
    "Sequence Container": "Random Container",
}


def _object_tab_for(available_tabs: list[str]) -> str:
    """Return the object-specific tab for this snapshot type, or DEFAULT_TAB."""
    for t in _OBJECT_TAB_ORDER:
        if t in available_tabs:
            return t
    return DEFAULT_TAB


def _group_to_tab(group: str, available_tabs: list[str], prop_key: str = "") -> str:
    """
    Return the tab name for a property, constrained to available_tabs.

    Priority:
    1. PROP_PREFERRED_TABS — contextual props (Weight, InitialDelay) go to the
       most specific object tab available for this type.
    2. PROP_TO_TAB — explicit per-property overrides.
    3. GROUP_TO_TAB — group-name based lookup.
    4. Sibling tab fallback (Random Container ↔ Sequence Container).
    5. DEFAULT_TAB ("General").
    """
    if prop_key:
        # 1. Preferred-tab list (first available wins)
        if prop_key in PROP_PREFERRED_TABS:
            for preferred in PROP_PREFERRED_TABS[prop_key]:
                if preferred in available_tabs:
                    return preferred

        # 2. Explicit override
        if prop_key in PROP_TO_TAB:
            tab = PROP_TO_TAB[prop_key]
            if tab in available_tabs:
                return tab

    # 3. Group-based lookup
    tab = GROUP_TO_TAB.get(group, DEFAULT_TAB)
    if tab in available_tabs:
        return tab

    # 4. Try sibling tab (e.g. "Random Container" props → "Sequence Container" tab)
    sibling = _TAB_SIBLINGS.get(tab)
    if sibling and sibling in available_tabs:
        return sibling

    return DEFAULT_TAB


def _format_prop_value(val, is_percentage: bool = False) -> str:
    """Format a property value for display."""
    if isinstance(val, dict):
        name = val.get("name", "")
        guid = val.get("id", "")
        return name if name else str(guid)
    if isinstance(val, bool):
        return "True" if val else "False"
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if is_percentage:
            pct = val * 100
            return f"{pct:.4g}%"
        if isinstance(val, float):
            return f"{val:.4g}"
    return str(val)


def _make_accordion(parent, row, title, content_fn, expanded=True):
    """Build one accordion section; returns next row index."""
    state = {"open": expanded}

    # Count custom curves in this section for badge
    custom_count = content_fn(None, count_only=True)
    badge = f"  ({custom_count} custom)" if custom_count else ""

    toggle_btn = ctk.CTkButton(
        parent,
        text=f"▼ {title}{badge}" if expanded else f"▶ {title}{badge}",
        font=ctk.CTkFont(size=11, weight="bold"),
        fg_color=COLOR_ACCENT,
        hover_color="#1a4a8a",
        anchor="w",
        height=28,
        corner_radius=3,
    )
    toggle_btn.grid(row=row, column=0, sticky="ew", padx=8, pady=(6, 0))

    content = ctk.CTkFrame(parent, fg_color=COLOR_BG_MID, corner_radius=3)
    content.grid_columnconfigure(0, weight=0, minsize=170)
    content.grid_columnconfigure(1, weight=1)
    if expanded:
        content.grid(row=row + 1, column=0, sticky="ew", padx=8, pady=(0, 2))
        content_fn(content)

    def toggle():
        state["open"] = not state["open"]
        if state["open"]:
            content.grid(row=row + 1, column=0, sticky="ew", padx=8, pady=(0, 2))
            content_fn(content)
            toggle_btn.configure(text=f"▼ {title}{badge}")
        else:
            content.grid_remove()
            for w in content.winfo_children():
                w.destroy()
            toggle_btn.configure(text=f"▶ {title}{badge}")

    toggle_btn.configure(command=toggle)
    return row + 2


class SnapshotTab(ctk.CTkFrame):
    def __init__(self, parent, app_ref=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._app = app_ref
        self._selected_snap_id: str | None = None
        self._snap_buttons: dict[str, ctk.CTkButton] = {}

        self._build_layout()
        self.refresh_list()

    def _build_layout(self):
        # Configure grid: left panel | right panel
        self.grid_columnconfigure(0, weight=0, minsize=260)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Left Panel (Snapshots & Actions) ──
        self._left = ctk.CTkFrame(self, fg_color=COLOR_BG_MID, corner_radius=12)
        self._left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        self._left.grid_rowconfigure(1, weight=1)
        self._left.grid_columnconfigure(0, weight=1)

        # DB indicator
        self._file_label = ctk.CTkLabel(
            self._left, text="DB: snapshots.db",
            font=ctk.CTkFont(size=9), text_color=COLOR_TEXT_DIM
        )
        self._file_label.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        # Snapshot list area
        self._list_frame = ctk.CTkScrollableFrame(
            self._left, fg_color=COLOR_BG_DARK, corner_radius=10,
            label_text="SNAPSHOTS",
            label_font=ctk.CTkFont(size=11, weight="bold"),
            label_fg_color=COLOR_ACCENT,
            label_text_color=COLOR_TEXT,
        )
        self._list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self._list_frame.grid_columnconfigure(0, weight=1)

        # ── Quick Actions (Save & Restore Grids) ──
        actions_frame = ctk.CTkFrame(self._left, fg_color="transparent")
        actions_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=8)
        actions_frame.grid_columnconfigure((0, 1), weight=1)

        btn_opts = {"font": ctk.CTkFont(size=11, weight="bold"), "height": 34, "corner_radius": 8}

        # --- SAVE SECTION ---
        ctk.CTkLabel(actions_frame, text="SAVE NEW", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 2))

        self._btn_save_all = ctk.CTkButton(actions_frame, text="All", fg_color=COLOR_BLUE, hover_color="#005ecb", command=lambda: self._on_save(mode="all"), **btn_opts)
        self._btn_save_all.grid(row=1, column=0, padx=2, pady=2, sticky="ew")

        self._btn_save_att = ctk.CTkButton(actions_frame, text="Atten", fg_color=COLOR_ACCENT, hover_color=COLOR_SELECTED, command=lambda: self._on_save(mode="attenuation"), **btn_opts)
        self._btn_save_att.grid(row=1, column=1, padx=2, pady=2, sticky="ew")

        # --- RESTORE SECTION ---
        ctk.CTkLabel(actions_frame, text="RESTORE SELECTED", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLOR_TEXT_DIM).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(12, 2))

        self._btn_restore_all = ctk.CTkButton(actions_frame, text="All", fg_color=COLOR_GREEN, hover_color="#28a745", command=self._on_restore, **btn_opts)
        self._btn_restore_all.grid(row=3, column=0, padx=2, pady=2, sticky="ew")

        self._btn_restore_att = ctk.CTkButton(actions_frame, text="Atten", fg_color=COLOR_ACCENT, hover_color=COLOR_GREEN, command=self._on_restore_attenuation_only, **btn_opts)
        self._btn_restore_att.grid(row=3, column=1, padx=2, pady=2, sticky="ew")

        # Utility Buttons
        util_frame = ctk.CTkFrame(self._left, fg_color="transparent")
        util_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        util_frame.grid_columnconfigure((0, 1), weight=1)

        self._btn_delete = ctk.CTkButton(util_frame, text="Delete", font=ctk.CTkFont(size=10), fg_color="transparent", text_color=COLOR_RED, hover_color="#3a1a1a", height=24, command=self._on_delete)
        self._btn_delete.grid(row=0, column=0, padx=2, sticky="ew")

        self._btn_del_all = ctk.CTkButton(util_frame, text="Clear All", font=ctk.CTkFont(size=10), fg_color="transparent", text_color=COLOR_RED, hover_color="#3a1a1a", height=24, command=self._on_delete_all)
        self._btn_del_all.grid(row=0, column=1, padx=2, sticky="ew")

        # ── Right Panel (Details) ──
        self._right = ctk.CTkFrame(self, fg_color=COLOR_BG_DARK, corner_radius=12)
        self._right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        self._right.grid_columnconfigure(0, weight=1)
        self._right.grid_rowconfigure(1, weight=1)

        # Header
        self._detail_header = ctk.CTkLabel(
            self._right, text="Parameter Details",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLOR_TEXT, anchor="w"
        )
        self._detail_header.grid(row=0, column=0, sticky="w", padx=20, pady=16)

        self._detail_tabview: ctk.CTkTabview | None = None
        self._show_placeholder()

    # ── Placeholder ────────────────────────────────────────────────────────

    def _show_placeholder(self):
        """Show placeholder text in detail panel when no snapshot is selected."""
        # Hide current view safely
        if self._detail_tabview is not None:
            try:
                # Only call grid_forget if the widget still exists
                if self._detail_tabview.winfo_exists():
                    self._detail_tabview.grid_forget()
            except (tk.TclError, AttributeError):
                pass
            self._detail_tabview = None

        # Remove any existing placeholder widget
        for widget in self._right.winfo_children():
            if widget is not self._detail_header and not isinstance(widget, ctk.CTkTabview):
                widget.destroy()

        lbl = ctk.CTkLabel(
            self._right,
            text="Select a snapshot to view parameters",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
        )
        lbl.grid(row=1, column=0, padx=12, pady=20)

    # ── List management ────────────────────────────────────────────────────

    def refresh_list(self):
        """Reload snapshot list from manager."""
        manager = get_manager()

        # Update DB path label
        db_display = manager.get_file_display()
        from pathlib import Path as _Path
        db_display_short = _Path(db_display).name
        self._file_label.configure(text=f"DB: {db_display_short}")

        # Clear existing buttons
        for widget in self._list_frame.winfo_children():
            widget.destroy()
        self._snap_buttons.clear()

        snaps = manager.get_snapshots()
        if not snaps:
            empty_lbl = ctk.CTkLabel(
                self._list_frame, text="No snapshots yet",
                font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM
            )
            empty_lbl.grid(row=0, column=0, padx=8, pady=20)
            return

        for i, snap in enumerate(snaps):
            snap_id = snap["id"]
            name = snap.get("name", "Unnamed")
            obj_name = snap.get("object_name", "?")
            timestamp = snap.get("timestamp", "")[:10]  # date only

            btn_text = f"{name}\n{obj_name}  [{timestamp}]"

            # Determine visual state based on selection
            is_selected = (snap_id == self._selected_snap_id)
            fg = COLOR_SELECTED if is_selected else "transparent"
            txt_color = "#ffffff" if is_selected else COLOR_TEXT

            btn = ctk.CTkButton(
                self._list_frame,
                text=btn_text,
                font=ctk.CTkFont(size=11, weight="bold" if is_selected else "normal"),
                text_color=txt_color,
                fg_color=fg,
                hover_color="#3a3a3c" if not is_selected else "#005ecb",
                anchor="w",
                height=52,
                corner_radius=8,
                command=lambda sid=snap_id: self._on_select(sid),
            )
            btn.grid(row=i, column=0, sticky="ew", padx=6, pady=3)
            self._snap_buttons[snap_id] = btn

        # If selected snap no longer exists, clear selection
        if self._selected_snap_id and self._selected_snap_id not in self._snap_buttons:
            self._selected_snap_id = None
            self._show_placeholder()
            self._set_restore_buttons_state("disabled")

    # ── Selection ──────────────────────────────────────────────────────────

    def _on_select(self, snap_id: str):
        """Handle clicking a snapshot in the list with strong Apple-style feedback."""
        # Reset previous selection style to transparent (Apple style)
        if self._selected_snap_id and self._selected_snap_id in self._snap_buttons:
            self._snap_buttons[self._selected_snap_id].configure(
                fg_color="transparent",
                text_color=COLOR_TEXT,
                font=ctk.CTkFont(size=11, weight="normal")
            )

        self._selected_snap_id = snap_id

        # Apply strong highlight to new selection (iOS Blue)
        if snap_id in self._snap_buttons:
            self._snap_buttons[snap_id].configure(
                fg_color=COLOR_SELECTED,
                text_color="#ffffff",
                font=ctk.CTkFont(size=11, weight="bold")
            )

        self._set_restore_buttons_state("normal")
        self._btn_delete.configure(state="normal")
        self._show_detail(snap_id)

    def _set_restore_buttons_state(self, state):
        self._btn_restore_all.configure(state=state)
        self._btn_restore_att.configure(state=state)

    # ── Detail view ────────────────────────────────────────────────────────

    def _show_detail(self, snap_id: str):
        """Populate right panel with tabbed snapshot parameter view (with caching)."""
        manager = get_manager()
        snap = manager.get_snapshot_by_id(snap_id)
        if not snap:
            self._show_placeholder()
            return

        name = snap.get("name", "Unnamed")
        obj_name = snap.get("object_name", "?")
        obj_path = snap.get("object_path", "?")
        obj_type = snap.get("object_type", "?")
        timestamp = snap.get("timestamp", "")
        props = snap.get("properties", {})
        prop_display = snap.get("property_display", {})
        snap_modifiers = snap.get("modifiers", [])
        snap_attenuation = snap.get("attenuation", {})

        self._detail_header.configure(text=f"{name}  —  {obj_name}")

        # Destroy previous tabview and any placeholder widgets
        if self._detail_tabview is not None:
            try:
                if self._detail_tabview.winfo_exists():
                    self._detail_tabview.destroy()
            except (tk.TclError, AttributeError):
                pass
            self._detail_tabview = None

        for widget in self._right.winfo_children():
            if widget is not self._detail_header:
                widget.destroy()

        # Determine tabs for this object type
        detail_tabs = _tabs_for_type(obj_type)

        # Build new CTkTabview
        tv = ctk.CTkTabview(
            self._right,
            fg_color=COLOR_BG_DARK,
            segmented_button_fg_color=COLOR_ACCENT,
            segmented_button_selected_color=COLOR_SELECTED,
            segmented_button_selected_hover_color=COLOR_SELECTED,
            segmented_button_unselected_color=COLOR_ACCENT,
            segmented_button_unselected_hover_color="#1a3a6e",
            text_color=COLOR_TEXT,
            corner_radius=6,
        )
        tv.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._detail_tabview = tv

        for tab_name in detail_tabs:
            tv.add(tab_name)

        # ── Build grouped data structure ──────────────────────────────────
        # groups maps: tab_name -> group_name -> [(prop_key, display_name, value, is_override_active)]
        tab_groups: dict[str, dict[str, list]] = {t: {} for t in detail_tabs}

        # Map: property display_name -> tab  (used to route Randomizer entries)
        rand_name_to_tab: dict[str, str] = {}

        for prop_key, prop_val in props.items():
            # Skip Override* flags and _effective_ internal keys
            if (prop_key.startswith("Override") or
                    prop_key.startswith("_effective_")):
                continue
            disp = prop_display.get(prop_key)
            if disp:
                display_name = disp.get("name", prop_key)
                group = disp.get("group", "") or "General"
            else:
                display_name = prop_key
                group = "General"

            tab = _group_to_tab(group, detail_tabs, prop_key=prop_key)

            # Record display_name → tab for Randomizer routing
            rand_name_to_tab[display_name] = tab

            # Determine override state and effective (inherited) value for display
            override_flag_name = disp.get("override_flag") if disp else None
            if override_flag_name:
                override_active = props.get(override_flag_name)  # True / False
                # When override is OFF, show the effective inherited value instead
                effective_val = props.get(f"_effective_{prop_key}")
            else:
                override_active = None   # unlink prop — no override concept
                effective_val = None

            is_percentage = disp.get("percentage", False) if disp else False
            entry = (prop_key, display_name, prop_val, override_active, effective_val, is_percentage)

            # Add to "All" tab
            if group not in tab_groups["All"]:
                tab_groups["All"][group] = []
            tab_groups["All"][group].append(entry)

            # Add to specific tab
            if group not in tab_groups[tab]:
                tab_groups[tab][group] = []
            tab_groups[tab][group].append(entry)

        # ── Group Randomizer entries by the tab of their target property ──
        # Each Randomizer entry belongs in the same tab as the property it
        # modifies (Voice Volume → General, Initial Delay → Sound SFX, etc.)
        tab_modifiers: dict[str, list[dict]] = {t: [] for t in detail_tabs}
        for mod in snap_modifiers:
            mod_prop_name = mod.get("property", "")
            mod_tab = rand_name_to_tab.get(mod_prop_name)

            # Fallback: rand_name_to_tab may have stored the raw prop key
            # (e.g. "InitialDelay") while the Modifier uses the display name
            # (e.g. "Initial Delay").  Try _MODIFIER_DISPLAY_TO_PROP to get the
            # prop key, then apply PROP_PREFERRED_TABS logic.
            if mod_tab is None:
                prop_key = _MODIFIER_DISPLAY_TO_PROP.get(mod_prop_name, "")
                if prop_key and prop_key in PROP_PREFERRED_TABS:
                    for preferred in PROP_PREFERRED_TABS[prop_key]:
                        if preferred in tab_modifiers:
                            mod_tab = preferred
                            break

            if mod_tab is None or mod_tab not in tab_modifiers:
                mod_tab = DEFAULT_TAB
            tab_modifiers[mod_tab].append(mod)

        # Sort each tab's modifier list: defined order first, then alphabetical.
        def _mod_sort_key(mod: dict, order_map: dict) -> tuple:
            name = mod.get("property", "")
            return (order_map.get(name, 999), name)

        for _tab, _mods in tab_modifiers.items():
            order_map = _RANDOMIZER_GENERAL_ORDER if _tab == DEFAULT_TAB else {}
            _mods.sort(key=lambda m: _mod_sort_key(m, order_map))

        # ── Meta info shown at top of All tab ─────────────────────────────
        all_tab = tv.tab("All")
        all_tab.grid_columnconfigure(0, weight=1)
        all_tab.grid_rowconfigure(0, weight=1)

        all_scroll = ctk.CTkScrollableFrame(
            all_tab,
            fg_color=COLOR_BG_DARK,
            corner_radius=4,
        )
        all_scroll.grid(row=0, column=0, sticky="nsew")
        all_scroll.grid_columnconfigure(0, weight=0, minsize=160)
        all_scroll.grid_columnconfigure(1, weight=1)

        row_idx = 0
        meta = [
            ("Object", obj_name),
            ("Type", obj_type),
            ("Path", obj_path),
            ("Saved", timestamp),
            ("Properties", str(len([k for k in props if not k.startswith("Override") and not k.startswith("_effective_")]))),
        ]
        for label, value in meta:
            lbl = ctk.CTkLabel(
                all_scroll,
                text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=COLOR_TEXT_DIM,
                anchor="e",
            )
            lbl.grid(row=row_idx, column=0, sticky="e", padx=(8, 4), pady=2)
            val_lbl = ctk.CTkLabel(
                all_scroll,
                text=str(value),
                font=ctk.CTkFont(size=11),
                text_color=COLOR_TEXT,
                anchor="w",
                wraplength=300,
            )
            val_lbl.grid(row=row_idx, column=1, sticky="w", padx=(4, 8), pady=2)
            row_idx += 1

        sep = ctk.CTkFrame(all_scroll, height=1, fg_color=COLOR_ACCENT)
        sep.grid(row=row_idx, column=0, columnspan=2, sticky="ew", padx=8, pady=6)
        row_idx += 1

        if not any(v for v in tab_groups["All"].values()):
            no_lbl = ctk.CTkLabel(
                all_scroll,
                text="(no properties saved)",
                font=ctk.CTkFont(size=11),
                text_color=COLOR_TEXT_DIM,
            )
            no_lbl.grid(row=row_idx, column=0, columnspan=2, padx=8, pady=8)
            row_idx += 1
        else:
            row_idx = self._populate_tab_scroll(all_scroll, tab_groups["All"], row_idx)

        # Modifiers section in All tab — show all modifiers together
        # Sort: General-order props first, then alphabetical.
        if snap_modifiers:
            sorted_all_mods = sorted(
                snap_modifiers,
                key=lambda m: _mod_sort_key(m, _RANDOMIZER_GENERAL_ORDER),
            )
            row_idx = self._populate_modifiers(all_scroll, sorted_all_mods, row_idx)


        # ── Populate each property tab ─────────────────────────────────────
        for tab_name in detail_tabs[1:]:  # skip "All"
            tab_frame = tv.tab(tab_name)
            tab_frame.grid_columnconfigure(0, weight=1)
            tab_frame.grid_rowconfigure(0, weight=1)

            if tab_name == "Attenuation Settings":
                self._populate_attenuation_tab(tab_frame, snap_attenuation)
                continue

            if tab_name in PLACEHOLDER_TABS:
                ph = ctk.CTkLabel(
                    tab_frame,
                    text="Not yet implemented",
                    font=ctk.CTkFont(size=12),
                    text_color=COLOR_TEXT_DIM,
                )
                ph.grid(row=0, column=0, padx=20, pady=20)
                continue

            scroll = ctk.CTkScrollableFrame(
                tab_frame,
                fg_color=COLOR_BG_DARK,
                corner_radius=4,
            )
            scroll.grid(row=0, column=0, sticky="nsew")
            scroll.grid_columnconfigure(0, weight=0, minsize=160)
            scroll.grid_columnconfigure(1, weight=1)

            groups_for_tab = tab_groups.get(tab_name, {})
            has_props = any(groups_for_tab.values())
            mods_for_tab = tab_modifiers.get(tab_name, [])

            if not has_props and not mods_for_tab:
                ph = ctk.CTkLabel(
                    scroll,
                    text="No properties in this category",
                    font=ctk.CTkFont(size=11),
                    text_color=COLOR_TEXT_DIM,
                )
                ph.grid(row=0, column=0, columnspan=2, padx=12, pady=20)
            else:
                next_row = self._populate_tab_scroll(scroll, groups_for_tab, 0)
                # Append Randomizer entries that belong to this tab
                if mods_for_tab:
                    self._populate_modifiers(scroll, mods_for_tab, next_row)

    def _populate_tab_scroll(
        self,
        scroll: ctk.CTkScrollableFrame,
        groups: dict[str, list],
        start_row: int,
    ) -> int:
        """
        Render group headers + property rows into scroll frame.
        Returns the next available row index.
        """
        row_idx = start_row
        for group_name, entries in groups.items():
            if not entries:
                continue
            # Group header
            hdr = ctk.CTkLabel(
                scroll,
                text=f"  ▸ {group_name}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=COLOR_TEXT,
                fg_color=COLOR_ACCENT,
                anchor="w",
                corner_radius=4,
            )
            hdr.grid(row=row_idx, column=0, columnspan=2, sticky="ew", padx=8, pady=(6, 2))
            row_idx += 1

            for prop_key, display_name, prop_val, override_active, effective_val, is_percentage in entries:
                key_lbl = ctk.CTkLabel(
                    scroll,
                    text=display_name,
                    font=ctk.CTkFont(size=12),
                    text_color=COLOR_TEXT_DIM,
                    anchor="e",
                )
                key_lbl.grid(row=row_idx, column=0, sticky="e", padx=(16, 6), pady=2)

                if override_active is False:
                    # Override OFF: show the effective inherited value (what's actually used)
                    show_val = effective_val if effective_val is not None else prop_val
                    display_val = _format_prop_value(show_val, is_percentage) + "  [Override OFF]"
                    val_color = COLOR_TEXT_DIM
                elif override_active is True:
                    display_val = _format_prop_value(prop_val, is_percentage) + "  [Override ON]"
                    val_color = COLOR_YELLOW
                else:
                    # Unlink prop — no override concept, just show value
                    display_val = _format_prop_value(prop_val, is_percentage)
                    val_color = COLOR_YELLOW

                val_lbl = ctk.CTkLabel(
                    scroll,
                    text=display_val,
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=val_color,
                    anchor="w",
                )
                val_lbl.grid(row=row_idx, column=1, sticky="w", padx=(4, 8), pady=2)
                row_idx += 1

        return row_idx

    def _populate_modifiers(
        self,
        scroll: ctk.CTkScrollableFrame,
        modifiers: list[dict],
        start_row: int,
    ) -> int:
        """
        Render a 'Randomizer' section header + one row per modifier.
        Each row shows: '<Property> Randomizer: Min=X, Max=Y, Enabled=Z'
        Returns the next available row index.
        """
        row_idx = start_row

        # Section header
        hdr = ctk.CTkLabel(
            scroll,
            text="  ▸ Randomizer",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLOR_TEXT,
            fg_color=COLOR_ACCENT,
            anchor="w",
            corner_radius=4,
        )
        hdr.grid(row=row_idx, column=0, columnspan=2, sticky="ew", padx=8, pady=(6, 2))
        row_idx += 1

        for mod in modifiers:
            prop = mod.get("property", "Unknown")
            min_val = mod.get("min", 0.0)
            max_val = mod.get("max", 0.0)
            enabled = mod.get("enabled", False)
            is_default = not mod.get("id")  # id="" means no Modifier object exists

            label_text = f"{prop} Randomizer"
            if is_default:
                val_text = "Min=0, Max=0, Enabled=False  [not configured]"
                val_color = COLOR_TEXT_DIM
            else:
                val_text = f"Min={min_val:.4g}, Max={max_val:.4g}, Enabled={enabled}"
                val_color = COLOR_YELLOW if enabled else COLOR_TEXT_DIM

            key_lbl = ctk.CTkLabel(
                scroll,
                text=label_text,
                font=ctk.CTkFont(size=12),
                text_color=COLOR_TEXT_DIM,
                anchor="e",
            )
            key_lbl.grid(row=row_idx, column=0, sticky="e", padx=(16, 6), pady=2)

            val_lbl = ctk.CTkLabel(
                scroll,
                text=val_text,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=val_color,
                anchor="w",
            )
            val_lbl.grid(row=row_idx, column=1, sticky="w", padx=(4, 8), pady=2)
            row_idx += 1

        return row_idx

    def _populate_attenuation_tab(self, tab_frame: ctk.CTkFrame, attenuation: dict):
        """Render Attenuation curve data into the Attenuation Settings tab (accordion UI)."""
        tab_frame.grid_columnconfigure(0, weight=1)
        tab_frame.grid_rowconfigure(0, weight=1)

        outer = ctk.CTkScrollableFrame(tab_frame, fg_color=COLOR_BG_DARK, corner_radius=4)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_columnconfigure(0, weight=1)

        if not attenuation:
            ctk.CTkLabel(
                outer,
                text="No Attenuation assigned",
                font=ctk.CTkFont(size=11),
                text_color=COLOR_TEXT_DIM,
            ).grid(row=0, column=0, padx=12, pady=20)
            return

        att_name   = attenuation.get("name", "Unknown")
        att_guid   = attenuation.get("guid", "")
        curves     = attenuation.get("curves", {})
        cone       = attenuation.get("cone", {})
        radius_max = attenuation.get("radius_max", 100.0)

        # ── Attenuation object header ─────────────────────────────────────
        hdr_frame = ctk.CTkFrame(outer, fg_color=COLOR_ACCENT, corner_radius=4)
        hdr_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        hdr_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(hdr_frame, text=f"  {att_name}", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLOR_TEXT, anchor="w").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ctk.CTkLabel(hdr_frame, text=f"MaxDist: {radius_max:.4g}",
                     font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_DIM, anchor="e"
                     ).grid(row=0, column=1, sticky="e", padx=8, pady=4)
        ctk.CTkLabel(hdr_frame, text=att_guid, font=ctk.CTkFont(size=9),
                     text_color=COLOR_TEXT_DIM, anchor="w"
                     ).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))

        # ── Curve label maps ──────────────────────────────────────────────
        _CURVE_LABELS = {
            "VolumeDryUsage":          ("Volume (Dry)",            "★"),
            "VolumeWetGameUsage":      ("Volume (Game Aux)",       ""),
            "VolumeWetUserUsage":      ("Volume (User Aux)",       ""),
            "LowPassFilterUsage":      ("Low-Pass Filter",         ""),
            "HighPassFilterUsage":     ("High-Pass Filter",        ""),
            "DualShelfUsage":          ("Dual-Shelf Filter",       "⚠"),
            "SpreadUsage":             ("Spread",                  ""),
            "FocusUsage":              ("Focus",                   ""),
            "ObstructionVolumeUsage":  ("Volume",                  ""),
            "ObstructionHPFUsage":     ("HPF",                     ""),
            "ObstructionLPFUsage":     ("LPF",                     ""),
            "ObstructionDSFUsage":     ("Dual-Shelf",              ""),
            "OcclusionVolumeUsage":    ("Volume",                  ""),
            "OcclusionHPFUsage":       ("HPF",                     ""),
            "OcclusionLPFUsage":       ("LPF",                     ""),
            "OcclusionDSFUsage":       ("Dual-Shelf",              ""),
            "DiffractionVolumeUsage":  ("Volume",                  ""),
            "DiffractionHPFUsage":     ("HPF",                     ""),
            "DiffractionLPFUsage":     ("LPF",                     ""),
            "DiffractionDSFUsage":     ("Dual-Shelf",              ""),
            "TransmissionVolumeUsage": ("Volume",                  ""),
            "TransmissionHPFUsage":    ("HPF",                     ""),
            "TransmissionLPFUsage":    ("LPF",                     ""),
            "TransmissionDSFUsage":    ("Dual-Shelf",              ""),
        }

        _GROUPS = [
            ("Distance",     ["VolumeDryUsage", "VolumeWetGameUsage", "VolumeWetUserUsage",
                              "LowPassFilterUsage", "HighPassFilterUsage", "DualShelfUsage",
                              "SpreadUsage", "FocusUsage"]),
            ("Obstruction",  ["ObstructionVolumeUsage", "ObstructionHPFUsage",
                              "ObstructionLPFUsage", "ObstructionDSFUsage"]),
            ("Occlusion",    ["OcclusionVolumeUsage", "OcclusionHPFUsage",
                              "OcclusionLPFUsage", "OcclusionDSFUsage"]),
            ("Diffraction",  ["DiffractionVolumeUsage", "DiffractionHPFUsage",
                              "DiffractionLPFUsage", "DiffractionDSFUsage"]),
            ("Transmission", ["TransmissionVolumeUsage", "TransmissionHPFUsage",
                              "TransmissionLPFUsage", "TransmissionDSFUsage"]),
        ]

        next_row = [1]  # mutable for closure

        for group_title, usages in _GROUPS:
            group_curves = [(u, curves[u]) for u in usages if u in curves]

            def make_content_fn(gc):
                def content_fn(frame, count_only=False):
                    if count_only:
                        return sum(1 for _, c in gc if c.get("use") == "Custom" and c.get("points"))
                    r = 0
                    for usage, curve in gc:
                        use_mode = curve.get("use", "None")
                        points   = curve.get("points", [])
                        label, icon = _CURVE_LABELS.get(usage, (usage, ""))
                        is_custom = use_mode == "Custom" and bool(points)
                        is_no_restore = usage == "DualShelfUsage"

                        # Row background alternates
                        row_bg = COLOR_BG_DARK if r % 2 == 0 else COLOR_BG_MID

                        row_frame = ctk.CTkFrame(frame, fg_color=row_bg, corner_radius=0)
                        row_frame.grid(row=r, column=0, columnspan=2, sticky="ew")
                        row_frame.grid_columnconfigure(0, weight=0, minsize=170)
                        row_frame.grid_columnconfigure(1, weight=1)

                        name_text = f"{icon}  {label}" if icon else f"  {label}"
                        ctk.CTkLabel(row_frame, text=name_text,
                                     font=ctk.CTkFont(size=11),
                                     text_color=COLOR_TEXT if is_custom else COLOR_TEXT_DIM,
                                     anchor="e").grid(row=0, column=0, sticky="e", padx=(8, 4), pady=3)

                        if is_no_restore and is_custom:
                            mode_text = f"{use_mode}  (read-only)"
                            mode_color = COLOR_TEXT_DIM
                        elif is_custom:
                            mode_text = use_mode
                            mode_color = COLOR_YELLOW
                        else:
                            mode_text = use_mode
                            mode_color = COLOR_TEXT_DIM

                        ctk.CTkLabel(row_frame, text=mode_text,
                                     font=ctk.CTkFont(size=11, weight="bold" if is_custom else "normal"),
                                     text_color=mode_color,
                                     anchor="w").grid(row=0, column=1, sticky="w", padx=(4, 8), pady=3)

                        if is_custom and points:
                            pts_text = "  ".join(
                                f"({p.get('x',0):.4g}, {p.get('y',0):.4g})" for p in points
                            )
                            ctk.CTkLabel(row_frame, text=pts_text,
                                         font=ctk.CTkFont(size=10),
                                         text_color=COLOR_TEXT_DIM,
                                         anchor="w", wraplength=300).grid(
                                             row=1, column=0, columnspan=2,
                                             sticky="w", padx=(174, 8), pady=(0, 4))
                        r += 1
                return content_fn

            fn = make_content_fn(group_curves)
            next_row[0] = _make_accordion(outer, next_row[0], group_title, fn,
                                          expanded=(group_title == "Distance"))

        # ── Cone Filter accordion ─────────────────────────────────────────
        if cone:
            _CONE_LABELS = [
                ("ConeUse",                "Cone Enabled"),
                ("ConeInnerAngle",         "Inner Angle"),
                ("ConeOuterAngle",         "Outer Angle"),
                ("ConeAttenuation",        "Outer Volume (dB)"),
                ("ConeLowPassFilterValue", "LPF"),
                ("ConeHighPassFilterValue","HPF"),
            ]

            def cone_fn(frame, count_only=False, _cone=cone):
                if count_only:
                    return 0
                for r_i, (prop_key, label) in enumerate(_CONE_LABELS):
                    if prop_key not in _cone:
                        continue
                    val = _cone[prop_key]
                    val_str = str(val) if isinstance(val, bool) else \
                              f"{val:.4g}" if isinstance(val, float) else str(val)
                    row_bg = COLOR_BG_DARK if r_i % 2 == 0 else COLOR_BG_MID
                    rf = ctk.CTkFrame(frame, fg_color=row_bg, corner_radius=0)
                    rf.grid(row=r_i, column=0, columnspan=2, sticky="ew")
                    rf.grid_columnconfigure(0, weight=0, minsize=170)
                    rf.grid_columnconfigure(1, weight=1)
                    ctk.CTkLabel(rf, text=f"  {label}", font=ctk.CTkFont(size=11),
                                 text_color=COLOR_TEXT_DIM, anchor="e"
                                 ).grid(row=0, column=0, sticky="e", padx=(8, 4), pady=3)
                    ctk.CTkLabel(rf, text=val_str, font=ctk.CTkFont(size=11, weight="bold"),
                                 text_color=COLOR_YELLOW, anchor="w"
                                 ).grid(row=0, column=1, sticky="w", padx=(4, 8), pady=3)

            next_row[0] = _make_accordion(outer, next_row[0], "Cone Filter", cone_fn, expanded=False)

        # ── Restore button ────────────────────────────────────────────────
        btn_restore_att = ctk.CTkButton(
            outer,
            text="Restore Attenuation Settings Only",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_GREEN,
            hover_color="#3d8b40",
            height=28,
            command=self._on_restore_attenuation_only,
        )
        btn_restore_att.grid(row=next_row[0], column=0, padx=12, pady=20)
        next_row[0] += 1

    # ── Save ───────────────────────────────────────────────────────────────

    def _on_save(self, mode="all"):
        """Save snapshot of current selected Wwise object."""
        client = get_client()
        manager = get_manager()

        if not client.is_connected():
            messagebox.showerror("WwiseSnap", "Not connected to Wwise.\nPlease connect first.")
            return

        # Get selected object(s) from Wwise
        objects = client.get_selected_objects()
        if not objects:
            messagebox.showwarning("WwiseSnap", "No object selected in Wwise.\nSelect an object first.")
            return

        obj = objects[0]
        obj_guid = obj.get("id", "")
        obj_name = obj.get("name", "Unknown")
        obj_type = obj.get("type", "Unknown")
        obj_path = obj.get("path", "\\")

        if not obj_guid:
            messagebox.showerror("WwiseSnap", "Selected object has no valid ID.")
            return

        # Resolve RandomSequenceContainer sub-type
        if obj_type == "RandomSequenceContainer":
            rand_info = client.call(
                "ak.wwise.core.object.get",
                {"from": {"id": [obj_guid]}, "options": {"return": ["RandomOrSequence"]}},
                timeout=5,
            )
            if rand_info and rand_info.get("return"):
                rand_or_seq = rand_info["return"][0].get("RandomOrSequence", 1)
                obj_type = "RandomContainer" if rand_or_seq == 1 else "SequenceContainer"

        # Auto-generate name
        suffix = "_ATTEN" if mode == "attenuation" else ""
        initial_name = f"Snap_{len(manager.get_snapshots()) + 1:03d}{suffix}"

        # Ask for snapshot name
        snap_name = simpledialog.askstring(
            "Snapshot Name",
            f"Name for this {mode} snapshot of '{obj_name}':",
            initialvalue=initial_name,
        )
        if not snap_name:
            return
        snap_name = snap_name.strip()
        if not snap_name:
            return

        # Disable all save buttons during worker
        self._set_save_buttons_state("disabled")

        def _worker():
            try:
                if mode == "all":
                    result = client.get_all_properties(obj_guid)
                elif mode == "attenuation":
                    meta = client.get_all_properties(obj_guid)
                    result = {"attenuation": meta.get("attenuation", {})}
                else:
                    result = {}
            except Exception as e:
                self.after(0, lambda err=e: _on_error(err))
                return
            self.after(0, lambda r=result: _on_done(r))

        def _on_error(err):
            self._set_save_buttons_state("normal")
            messagebox.showerror("WwiseSnap", f"Failed to read properties:\n{err}")

        def _on_done(result):
            self._set_save_buttons_state("normal")

            props = result.get("properties", {})
            prop_display = result.get("display", {})
            modifiers = result.get("modifiers", [])
            attenuation = result.get("attenuation", {})

            snap = manager.save_snapshot(
                name=snap_name,
                object_path=obj_path,
                object_name=obj_name,
                object_guid=obj_guid,
                object_type=obj_type,
                properties=props,
                property_display=prop_display,
                modifiers=modifiers,
                attenuation=attenuation,
            )
            self.refresh_list()
            self._on_select(snap["id"])

            msg = f"Snapshot '{snap_name}' saved!\nMode: {mode}\nObject: {obj_name}"
            if mode == "all":
                prop_count = len([k for k in props if not k.startswith("Override") and not k.startswith("_effective_")])
                msg += f"\nProperties: {prop_count}"
            if attenuation: msg += f"\nAttenuation: {attenuation.get('name', 'Custom')}"

            messagebox.showinfo("WwiseSnap", msg)

        threading.Thread(target=_worker, daemon=True).start()

    def _set_save_buttons_state(self, state):
        self._btn_save_all.configure(state=state)
        self._btn_save_att.configure(state=state)

    # ── Restore ────────────────────────────────────────────────────────────

    def _on_restore(self):
        """Restore selected snapshot to the currently selected Wwise object."""
        if not self._selected_snap_id:
            messagebox.showwarning("WwiseSnap", "No snapshot selected.")
            return

        client = get_client()
        manager = get_manager()

        if not client.is_connected():
            messagebox.showerror("WwiseSnap", "Not connected to Wwise.\nPlease connect first.")
            return

        # Get selected Wwise object
        objects = client.get_selected_objects()
        if not objects:
            messagebox.showwarning("WwiseSnap", "No object selected in Wwise.\nSelect a target object first.")
            return

        obj = objects[0]
        obj_guid = obj.get("id", "")
        obj_name = obj.get("name", "Unknown")

        if not obj_guid:
            messagebox.showerror("WwiseSnap", "Selected object has no valid ID.")
            return

        snap = manager.get_snapshot_by_id(self._selected_snap_id)
        if not snap:
            return

        snap_name = snap.get("name", "?")
        obj_type = snap.get("object_type", "")
        props = snap.get("properties", {})
        snap_modifiers = snap.get("modifiers", [])
        snap_attenuation = snap.get("attenuation", {})

        if not props and not snap_modifiers and not snap_attenuation:
            messagebox.showinfo("WwiseSnap", "This snapshot has no properties to restore.")
            return

        # Type Safety Check
        target_obj = objects[0]
        target_type = target_obj.get("type", "")
        if target_type != obj_type:
            msg = (
                f"Type Mismatch!\n\n"
                f"Snapshot type: {obj_type}\n"
                f"Selected object type: {target_type}\n\n"
                f"Restoring settings to a different object type may cause errors.\n"
                f"Do you want to proceed anyway?"
            )
            if not messagebox.askyesno("WwiseSnap Warning", msg):
                return

        # Get supported properties of the target object to filter out invalids
        supported_props = client.get_supported_properties(obj_guid)
        
        # Separate scalar props from reference props (dicts with "id" key).
        scalar_props = {}
        reference_props = {}
        for k, v in props.items():
            # _effective_ keys are display-only — never restore them
            if k.startswith("_effective_"):
                continue
            
            # Filter: only keep if the target object supports this property
            if k not in supported_props and not k.startswith("Override"):
                continue

            if isinstance(v, dict) and "id" in v:
                reference_props[k] = v
            else:
                scalar_props[k] = v

        override_count = sum(1 for k in scalar_props if k.startswith("Override"))
        # Count only real modifiers (id != "") for the confirm dialog
        real_mods = [m for m in snap_modifiers if m.get("id")]
        mod_info = f"\nRandomizer modifiers: {len(real_mods)}" if real_mods else ""
        att_name = snap_attenuation.get("name", "")
        att_info = f"\nAttenuation: {att_name} ({len(snap_attenuation.get('curves', {}))} curves)" if snap_attenuation else ""

        confirm_msg = (
            f"Apply snapshot '{snap_name}' to:\n{obj_name}\n\n"
            f"Scalar properties: {len(scalar_props) - override_count}\n"
            f"Override flags: {override_count}\n"
            f"Reference properties: {len(reference_props)}"
            f"{mod_info}"
            f"{att_info}"
        )

        if not messagebox.askyesno("Restore Snapshot", confirm_msg):
            return

        # Disable buttons during restore
        self._set_save_buttons_state("disabled")
        self._set_restore_buttons_state("disabled")

        _SKIP_REFS = {"AudioDevice"}

        def _worker():
            errors = []

            # Scalar properties
            if scalar_props:
                ok = client.set_object_properties(obj_guid, scalar_props)
                if not ok:
                    errors.append("Failed to apply scalar properties.")

            # Reference properties
            # SwitchGroupOrStateGroup must be set before DefaultSwitchOrState —
            # Wwise rejects DefaultSwitchOrState via setReference if the Switch
            # Group hasn't been assigned yet.
            _REF_ORDER = {"SwitchGroupOrStateGroup": 0, "DefaultSwitchOrState": 1}
            sorted_refs = sorted(
                reference_props.items(),
                key=lambda kv: _REF_ORDER.get(kv[0], 99),
            )
            ref_ok = 0
            ref_fail = 0
            for ref_name, ref_val in sorted_refs:
                if ref_name in _SKIP_REFS:
                    continue
                ref_guid = ref_val.get("id", "")
                if not ref_guid:
                    ref_fail += 1
                    continue
                ok = client.set_object_reference(obj_guid, ref_name, ref_guid)
                if ok:
                    ref_ok += 1
                else:
                    ref_fail += 1
                    errors.append(f"Failed to set reference '{ref_name}'.")

            # Randomizer modifiers
            # Use snap_modifiers (not real_mods) so that entries saved with id=""
            # (no Modifier object existed at save time) still get applied —
            # set_modifiers() looks up the current object's modifiers by property
            # name, so id="" entries correctly reset existing modifiers to defaults.
            mod_ok = True
            if snap_modifiers:
                mod_ok = client.set_modifiers(obj_guid, snap_modifiers)
                if not mod_ok:
                    errors.append("Some Randomizer modifiers failed to apply.")

            # Attenuation curves
            att_ok = True
            if snap_attenuation:
                att_ok = client.set_attenuation_curves(snap_attenuation)
                if not att_ok:
                    errors.append("Some Attenuation curves failed to apply.")

            self.after(0, lambda: _on_done(errors, ref_ok, ref_fail, mod_ok, att_ok))

        def _on_done(errors, ref_ok, ref_fail, mod_ok, att_ok):
            self._set_save_buttons_state("normal")
            self._set_restore_buttons_state("normal")

            if errors:
                msg = (
                    f"Snapshot '{snap_name}' partially restored to '{obj_name}'.\n"
                    f"Scalar: {len(scalar_props)} applied.\n"
                    f"References: {ref_ok} applied, {ref_fail} failed.\n"
                    + ("Randomizers: applied with errors.\n" if real_mods and not mod_ok else "")
                    + ("Attenuation curves: applied with errors.\n" if snap_attenuation and not att_ok else "")
                    + "\n".join(errors[:5])
                )
                messagebox.showwarning("WwiseSnap", msg)
            else:
                mod_line = f"\n{len(snap_modifiers)} Randomizer modifier(s) applied." if snap_modifiers else ""
                att_line = f"\nAttenuation '{att_name}' curves applied." if snap_attenuation else ""
                msg = (
                    f"Snapshot '{snap_name}' restored to '{obj_name}'.\n"
                    f"{len(scalar_props)} scalar + {ref_ok} reference properties applied."
                    f"{mod_line}"
                    f"{att_line}"
                )
                messagebox.showinfo("WwiseSnap", msg)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Delete ─────────────────────────────────────────────────────────────

    def _on_delete(self):
        """Delete the selected snapshot."""
        if not self._selected_snap_id:
            messagebox.showwarning("WwiseSnap", "No snapshot selected.")
            return

        manager = get_manager()
        snap = manager.get_snapshot_by_id(self._selected_snap_id)
        if not snap:
            return

        confirm = messagebox.askyesno(
            "Delete Snapshot",
            f"Delete snapshot '{snap.get('name', '?')}'?\nThis cannot be undone.",
        )
        if confirm:
            manager.delete_snapshot(self._selected_snap_id)
            self._selected_snap_id = None
            self._detail_header.configure(text="Parameter Details")
            self._show_placeholder()
            self.refresh_list()

    def _on_delete_all(self):
        """Delete all snapshots from the database."""
        manager = get_manager()
        count = len(manager.get_snapshots())
        if count == 0:
            messagebox.showinfo("WwiseSnap", "삭제할 스냅샷이 없습니다.")
            return
        if not messagebox.askyesno(
            "Delete All Snapshots",
            f"스냅샷 {count}개를 모두 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
        ):
            return
        
        manager.delete_all_snapshots()
        self._selected_snap_id = None
        self._detail_header.configure(text="Parameter Details")
        self._show_placeholder()
        self.refresh_list()

    # ── Export / Import ────────────────────────────────────────────────────

    def _on_export(self):
        """Export all snapshots to a JSON file."""
        manager = get_manager()
        snaps = manager.get_snapshots()
        if not snaps:
            messagebox.showinfo("WwiseSnap", "No snapshots to export.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Export Snapshots to JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="wwisesnap_export.json",
        )
        if not file_path:
            return

        if manager.export_json(file_path):
            messagebox.showinfo(
                "WwiseSnap",
                f"Exported {len(snaps)} snapshot(s) to:\n{file_path}",
            )
        else:
            messagebox.showerror("WwiseSnap", f"Failed to write file:\n{file_path}")

    def _on_import(self):
        """Import snapshots from a JSON file (merges, skips duplicates)."""
        file_path = filedialog.askopenfilename(
            title="Import Snapshots from JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not file_path:
            return

        manager = get_manager()
        count = manager.import_json(file_path)
        self.refresh_list()
        messagebox.showinfo(
            "WwiseSnap",
            f"Import complete.\n{count} snapshot(s) imported (duplicates skipped).",
        )

    # ── Notification ───────────────────────────────────────────────────────

    def notify_file_loaded(self):
        """Called from main window when DB/file is changed (kept for compat)."""
        self.refresh_list()
        self._show_placeholder()
        self._detail_header.configure(text="Parameter Details")

    def _on_restore_attenuation_only(self):
        """Restore only the attenuation settings from the current snapshot."""
        if not self._selected_snap_id:
            return
        snap = get_manager().get_snapshot_by_id(self._selected_snap_id)
        client = get_client()
        if not client.is_connected():
            messagebox.showerror("WwiseSnap", "Not connected to Wwise.\nPlease connect first.")
            return
        objects = client.get_selected_objects()
        if not objects:
            messagebox.showwarning("WwiseSnap", "No object selected in Wwise.")
            return
        if not snap:
            return

        att_data = snap.get("attenuation", {})
        if not att_data:
            messagebox.showinfo("WwiseSnap", "No attenuation data in this snapshot.")
            return

        if messagebox.askyesno("Restore Attenuation", f"Restore attenuation '{att_data.get('name')}' to selected object?"):
            ok = client.set_attenuation_curves(att_data)
            if ok:
                messagebox.showinfo("WwiseSnap", "Attenuation settings restored.")
            else:
                messagebox.showerror("WwiseSnap", "Failed to restore attenuation settings.\nThe Attenuation ShareSet may not exist in the current project.")

