"""
WwiseSnap WAAPI Client
Wraps sk-wwise-mcp's call() with connection state tracking.
"""

import sys
import importlib.util
import threading
from pathlib import Path

# Load sk-wwise-mcp's waapi_util directly by file path to avoid name
# collision with WwiseSnap's own `core` package.
_SK_WWISE_MCP = Path.home() / "sk-wwise-mcp"
_WAAPI_UTIL_PATH = _SK_WWISE_MCP / "core" / "waapi_util.py"

def _load_waapi_call():
    """Import call() from sk-wwise-mcp/core/waapi_util.py without namespace collision."""
    spec = importlib.util.spec_from_file_location(
        "sk_wwise_mcp_waapi_util", str(_WAAPI_UTIL_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    # Ensure sk-wwise-mcp root is on path so waapi_util's own imports work
    sk_path = str(_SK_WWISE_MCP)
    if sk_path not in sys.path:
        sys.path.insert(0, sk_path)
    spec.loader.exec_module(mod)
    # Suppress txaio/AutoBahn WAAPI error logs — they fire at the WAMP
    # layer before our exception handler, producing harmless but noisy output.
    try:
        import txaio
        txaio.set_global_log_level("critical")
    except Exception:
        pass
    return mod.call


# ---------------------------------------------------------------------------
# Dynamic property schema cache
# ---------------------------------------------------------------------------

# Per-classId cache: classId -> {"unlink": [...], "override": {...}, "skip": [...], "display": {...}}
_PROP_CACHE: dict = {}
_PROP_CACHE_LOCK = threading.Lock()

# Metadata fields that are never "real" properties — skip them entirely.
_METADATA_FIELDS = frozenset({
    "id", "name", "path", "type", "shortId", "classId", "category",
    "filePath", "workunit", "parent", "owner", "notes", "color",
    "childrenCount", "totalSize", "pluginName", "isPlayable",
})

# Properties whose names start with these prefixes are Override flags —
# they are meta-controls, not settings, so skip them as standalone entries.
_OVERRIDE_FLAG_PREFIXES = ("Override", "overrideParent")

# Property display groups to exclude from snapshots entirely.
# 3D Position data relies on separate Position child objects whose drawn
# paths (waypoints) cannot be accessed or restored via WAAPI.
# Excluding the whole group avoids partial/misleading restores.
_SKIP_GROUPS = frozenset({
    "Listener Relative Routing/3D Position",
    "3D Position",
})

# Properties with supports.unlink=False and no override dependency are
# normally skipped (internal/computed). However, some are genuinely
# user-editable local settings (container mode, loop, MIDI filters, etc.)
# that just happen not to participate in the parent-inheritance system.
# This set explicitly includes them so they are saved and restored.
_FORCE_INCLUDE_PROPS = frozenset({
    # ── Sound SFX — loop source settings ─────────────────────────────────
    "IsLoopingEnabled", "LoopCount", "IsLoopingInfinite",
    # ── Playback Limit (all actor-mixer types) ────────────────────────────
    "IsGlobalLimit", "GlobalOrPerObject",
    "IgnoreParentMaxSoundInstance", "MaxReachedBehavior", "OverLimitBehavior",
    # ── MIDI Filters / Transformation (Advanced tab) ──────────────────────
    "MidiVelocityFilterMin", "MidiVelocityFilterMax",
    "MidiKeyFilterMin", "MidiKeyFilterMax", "MidiChannelFilter",
    "MidiTransposition", "MidiVelocityOffset",
    # ── RandomSequenceContainer — Loop ───────────────────────────────────
    "PlayMechanismLoop", "PlayMechanismLoopCount",
    "PlayMechanismInfiniteOrNumberOfLoops",
    "PlayMechanismResetPlaylistEachPlay",
    "RestartBeginningOrBackward",
    # ── RandomSequenceContainer — Mode ───────────────────────────────────
    "NormalOrShuffle", "RandomAvoidRepeating", "RandomAvoidRepeatingCount",
    "PlayMechanismStepOrContinuous",
    # ── RandomSequenceContainer — Transitions ────────────────────────────
    "PlayMechanismSpecialTransitions",
    "PlayMechanismSpecialTransitionsType",
    "PlayMechanismSpecialTransitionsValue",
    # ── SwitchContainer ───────────────────────────────────────────────────
    "SwitchGroupOrStateGroup", "DefaultSwitchOrState", "SwitchBehavior",
    # ── BlendContainer ────────────────────────────────────────────────────
    "BlendBehavior",
})


def _get_property_schema(call_fn, class_id: int) -> dict:
    """
    Build and cache a property schema for the given Wwise classId.

    Returns:
        {
            "unlink":   [prop_name, ...],           # Category B — always local value
            "override": {prop_name: flag_name, ...},# Category A — only valid when flag is True
            "skip":     [prop_name, ...],           # Override flags + metadata (query but don't store)
            "display":  {prop_name: {"name": display_name, "group": group_name}, ...},
        }
    """
    with _PROP_CACHE_LOCK:
        if class_id in _PROP_CACHE:
            return _PROP_CACHE[class_id]

    # Get all property/reference names for this classId.
    result = call_fn(
        "ak.wwise.core.object.getPropertyAndReferenceNames",
        {"classId": class_id},
    )
    all_props: list[str] = result.get("return", []) if result else []

    schema: dict = {"unlink": [], "override": {}, "skip": [], "display": {}, "randomizable": []}

    for prop in all_props:
        # Always skip metadata fields.
        if prop in _METADATA_FIELDS:
            continue

        # Skip Override* flag properties — they are used as keys in the
        # "override" dict values, not as standalone settings.
        if any(prop.startswith(pfx) for pfx in _OVERRIDE_FLAG_PREFIXES):
            schema["skip"].append(prop)
            continue

        # Ask Wwise about this property's semantics.
        info = call_fn(
            "ak.wwise.core.object.getPropertyInfo",
            {"classId": class_id, "property": prop},
        )

        if not info:
            # Unknown — treat as unlink (safe fallback).
            schema["unlink"].append(prop)
            continue

        disp = info.get("display", {})
        display_name = disp.get("name", prop)
        group_name   = disp.get("group", "")  # preserve empty group (for PROP_TO_TAB lookup)

        # Skip properties that belong to unsupported groups (e.g. 3D Position —
        # its data lives in separate Position child objects not accessible via WAAPI).
        if group_name in _SKIP_GROUPS:
            schema["skip"].append(prop)
            continue

        # Capture display formatting hints from the UI metadata.
        ui_display_as = info.get("ui", {}).get("displayAs", {})
        is_percentage  = bool(ui_display_as.get("percentage", False))

        supports     = info.get("supports", {})
        dependencies = info.get("dependencies", [])

        # Look for an "override" dependency — that makes this a Category A prop.
        override_flag = None
        for dep in dependencies:
            if dep.get("type") == "override":
                override_flag = dep.get("property")
                break

        if override_flag:
            schema["override"][prop] = override_flag
            # Include override_flag in display so the UI can look up the flag
            # state and show the effective (inherited) value when override is OFF.
            schema["display"][prop] = {
                "name": display_name,
                "group": group_name,
                "override_flag": override_flag,
                "percentage": is_percentage,
            }
        elif supports.get("unlink"):
            schema["unlink"].append(prop)
            schema["display"][prop] = {
                "name": display_name,
                "group": group_name,
                "percentage": is_percentage,
            }
        else:
            # supports.unlink=False and no override dependency.
            # Most are internal/computed. Explicitly whitelisted props are
            # locally editable settings (container mode, loop, MIDI filters…).
            if prop in _FORCE_INCLUDE_PROPS:
                schema["unlink"].append(prop)
                schema["display"][prop] = {
                    "name": display_name,
                    "group": group_name,
                    "percentage": is_percentage,
                }
            else:
                schema["skip"].append(prop)

        # Track properties that support the Randomizer module.
        # Used to show default Randomizer entries in the UI even when no
        # Modifier object has been created on the target.
        if supports.get("randomizer"):
            schema["randomizable"].append((prop, display_name))

    with _PROP_CACHE_LOCK:
        _PROP_CACHE[class_id] = schema

    return schema


# ---------------------------------------------------------------------------
# Client wrapper
# ---------------------------------------------------------------------------

class WaapiClientWrapper:
    """Thread-safe wrapper around sk-wwise-mcp's WAAPI call utility."""

    def __init__(self):
        self._connected = False
        self._lock = threading.Lock()
        self._call_fn = None
        self._project_name = ""
        self._wwise_version = ""
        self._on_status_change = None  # callback(connected: bool, message: str)

    def set_status_callback(self, callback):
        """Set callback for connection status changes: callback(connected, message)."""
        self._on_status_change = callback

    def _notify(self, connected: bool, message: str):
        self._connected = connected
        if self._on_status_change:
            self._on_status_change(connected, message)

    def get_project_name_from_waapi(self) -> str:
        """
        Query Wwise for the active project name via ak.wwise.core.object.get.
        Returns the project name string, or empty string on failure.
        """
        if self._call_fn is None:
            return ""
        try:
            result = self._call_fn(
                "ak.wwise.core.object.get",
                {
                    "from": {"ofType": ["Project"]},
                    "options": {"return": ["name", "filePath"]},
                },
            )
            if result and result.get("return"):
                return result["return"][0].get("name", "")
        except Exception:
            pass
        return ""

    def connect(self) -> bool:
        """Attempt to connect to WAAPI. Returns True on success."""
        try:
            self.clear_schema_cache()  # fresh schema on every reconnect
            self._call_fn = _load_waapi_call()
            # Test connection
            result = self._call_fn("ak.wwise.core.getInfo", {})
            if result:
                version = result.get("version", {}).get("displayName", "")
                self._wwise_version = version

                # Try to get actual project name from the project object
                project_name = self.get_project_name_from_waapi()
                if project_name:
                    self._project_name = project_name
                else:
                    # Fallback to displayName from getInfo
                    self._project_name = result.get("displayName", "Wwise")

                status_msg = f"Connected — {self._project_name} (v{version})" if version else f"Connected — {self._project_name}"
                self._notify(True, status_msg)
                return True
            else:
                self._notify(False, "No response from Wwise")
                return False
        except Exception as e:
            self._notify(False, f"Failed: {str(e)[:60]}")
            return False

    def disconnect(self):
        """Disconnect from WAAPI."""
        self._call_fn = None
        self._notify(False, "Disconnected")

    def clear_schema_cache(self):
        """Clear the per-classId property schema cache (call after filtering changes)."""
        with _PROP_CACHE_LOCK:
            _PROP_CACHE.clear()

    def is_connected(self) -> bool:
        return self._connected

    def get_project_name(self) -> str:
        return self._project_name

    def get_wwise_version(self) -> str:
        return self._wwise_version

    def call(self, uri: str, args: dict = None, timeout: float = 10) -> dict | None:
        """Make a WAAPI call. Returns result dict or None on failure."""
        if self._call_fn is None:
            return None
        try:
            result = self._call_fn(uri, args or {}, timeout=timeout)
            # Mark connected if we get a successful response
            if not self._connected:
                version = self._wwise_version
                status_msg = f"Connected — {self._project_name} (v{version})" if version else f"Connected — {self._project_name}"
                self._notify(True, status_msg)
            return result
        except Exception as e:
            err_str = str(e)
            # Check if it's a real disconnection
            if "CannotConnect" in err_str or "timed out" in err_str.lower():
                self._notify(False, "Connection lost")
            return None

    def get_selected_objects(self) -> list[dict]:
        """Get currently selected objects in Wwise UI."""
        result = self.call(
            "ak.wwise.ui.getSelectedObjects",
            {"options": {"return": ["id", "name", "type", "path"]}},
            timeout=5,
        )
        if result and "objects" in result:
            return result["objects"]
        return []

    def get_object_properties(self, guid: str, schema: dict) -> dict:
        """
        Fetch all relevant properties for *guid* given a pre-built schema dict.

        Queries: id, name, type, path  +  all unlink props  +  all override
        props  +  all override flag names (needed to decide Category A).

        For override props, uses @ prefix to get the local (non-inherited) value.
        """
        if not guid or not guid.strip():
            return {}
        all_flag_names = list(set(schema["override"].values()))

        # Base fields
        return_props = ["id", "name", "type", "path", "classId"]

        # UNLINK props — bare name returns local value
        return_props += schema["unlink"]

        # OVERRIDE props — @PropName = local value, bare PropName = effective value
        # (bare name returns the inherited/parent value when Override flag is OFF)
        for prop in schema["override"].keys():
            return_props.append(f"@{prop}")
            return_props.append(prop)  # effective value for display

        # Override flag names — bare (no @ prefix) to get the boolean flag
        return_props += all_flag_names

        # Deduplicate while preserving order.
        seen: set = set()
        deduped = []
        for p in return_props:
            if p not in seen:
                seen.add(p)
                deduped.append(p)

        result = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"id": [guid]},
                "options": {"return": deduped},
            },
            timeout=30,
        )
        if result and result.get("return"):
            return result["return"][0]
        return {}

    def get_modifiers(self, guid: str) -> list[dict]:
        """
        Get all Modifier (Randomizer) child objects for an object.

        Modifier objects are NOT accessible via children/descendants in the
        WAAPI tree. Instead, they exist as top-level objects of type 'Modifier'
        whose path follows the pattern:
            <parent_path>\\[Randomizer: <PropertyName>]

        Strategy:
        1. Get the object's path.
        2. Fetch ALL Modifier objects from Wwise.
        3. Filter to those whose path starts with <object_path>\\.

        Returns list of dicts:
            [{"property": "Voice Pitch", "min": -5.0, "max": 5.0,
              "enabled": True, "id": "{...}"}, ...]
        """
        import re

        if self._call_fn is None or not guid or not guid.strip():
            return []

        # Step 1: get the object's path
        meta = self.call(
            "ak.wwise.core.object.get",
            {"from": {"id": [guid]}, "options": {"return": ["path"]}},
            timeout=10,
        )
        if not meta or not meta.get("return"):
            return []
        obj_path: str = meta["return"][0].get("path", "")
        if not obj_path:
            return []

        # Step 2: fetch all Modifier objects
        all_mods_result = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"ofType": ["Modifier"]},
                "options": {"return": ["id", "path", "Min", "Max", "Enabled"]},
            },
            timeout=30,
        )
        if not all_mods_result or not all_mods_result.get("return"):
            return []

        # Step 3: filter to this object's DIRECT modifiers only.
        # A direct modifier path looks like: <obj_path>\[Randomizer: PropName]
        # Child object modifiers look like:  <obj_path>\ChildName\[Randomizer: PropName]
        # We only want the former — check that the remainder after the prefix
        # contains no backslash (i.e. it's a direct child, not a descendant).
        prefix = obj_path + "\\"
        result: list[dict] = []
        for mod in all_mods_result["return"]:
            mod_path: str = mod.get("path", "")
            if not mod_path.startswith(prefix):
                continue
            remainder = mod_path[len(prefix):]
            if "\\" in remainder:
                continue  # belongs to a descendant object, not this one
            match = re.search(r"\[Randomizer: (.+?)\]", remainder)
            prop_name = match.group(1) if match else "Unknown"
            result.append({
                "property": prop_name,
                "min": mod.get("Min", 0.0),
                "max": mod.get("Max", 0.0),
                "enabled": bool(mod.get("Enabled", False)),
                "id": mod.get("id", ""),
            })

        return result

    def set_modifiers(self, guid: str, modifiers: list[dict]) -> bool:
        """
        Restore Modifier values on an object.

        For each entry in `modifiers`, finds the matching Modifier on the
        TARGET object's current Modifier children (by property name) and
        sets Min/Max/Enabled.  The snapshot's stored Modifier GUIDs are
        intentionally NOT used here — they may belong to a different object
        or a different Wwise session and would cause unknown_object errors.

        Returns True if all modifiers were applied without error.
        """
        if self._call_fn is None or not modifiers or not guid or not guid.strip():
            return True

        # Get CURRENT modifiers on the target object so we can map
        # property names to the target's own Modifier GUIDs.
        current_mods = self.get_modifiers(guid)
        prop_to_id: dict[str, str] = {
            m["property"]: m["id"] for m in current_mods if m.get("id")
        }

        all_ok = True
        for mod in modifiers:
            prop_name = mod.get("property", "")
            # Look up by property name in the TARGET object's current modifiers
            mod_id = prop_to_id.get(prop_name)
            if not mod_id:
                # No matching modifier on target — skip (can't create one via WAAPI)
                continue

            # Set all three modifier properties in one call using object.set.
            # @ prefix is required — bare names are rejected by WAAPI.
            r = self.call(
                "ak.wwise.core.object.set",
                {
                    "objects": [{
                        "object":   mod_id,
                        "@Min":     mod.get("min", 0.0),
                        "@Max":     mod.get("max", 0.0),
                        "@Enabled": mod.get("enabled", False),
                    }]
                },
                timeout=10,
            )
            if r is None:
                all_ok = False

        return all_ok

    # curveType values for getAttenuationCurve (GET enum)
    _ATTENUATION_CURVE_USAGES = [
        # Distance
        "VolumeDryUsage",
        "VolumeWetGameUsage",
        "VolumeWetUserUsage",
        "LowPassFilterUsage",
        "HighPassFilterUsage",
        "DualShelfUsage",       # GET name; SET name is "HighShelfUsage"
        "SpreadUsage",
        "FocusUsage",
        # Obstruction
        "ObstructionVolumeUsage",
        "ObstructionHPFUsage",
        "ObstructionLPFUsage",
        "ObstructionDSFUsage",  # GET: DSF → SET: HSF
        # Occlusion
        "OcclusionVolumeUsage",
        "OcclusionHPFUsage",
        "OcclusionLPFUsage",
        "OcclusionDSFUsage",
        # Diffraction
        "DiffractionVolumeUsage",
        "DiffractionHPFUsage",
        "DiffractionLPFUsage",
        "DiffractionDSFUsage",
        # Transmission
        "TransmissionVolumeUsage",
        "TransmissionHPFUsage",
        "TransmissionLPFUsage",
        "TransmissionDSFUsage",
    ]

    # getAttenuationCurve enum → setAttenuationCurve enum (where they differ)
    _ATTENUATION_GET_TO_SET = {
        # DualShelfUsage is GET-only — setAttenuationCurve uses a different
        # internal name and writes a different curve; there is no WAAPI path to
        # restore it, so it is skipped in set_attenuation_curves().
        "ObstructionDSFUsage":    "ObstructionHSFUsage",
        "OcclusionDSFUsage":      "OcclusionHSFUsage",
        "DiffractionDSFUsage":    "DiffractionHSFUsage",
        "TransmissionDSFUsage":   "TransmissionHSFUsage",
    }

    # HSF curve types (and DualShelfUsage) reject "UseProject" mode.
    _HSF_CURVE_TYPES = frozenset({
        "ObstructionHSFUsage",
        "OcclusionHSFUsage",
        "DiffractionHSFUsage",
        "TransmissionHSFUsage",
    })

    # GET-only curve types that have no SET equivalent in WAAPI.
    _RESTORE_UNSUPPORTED = frozenset({"DualShelfUsage"})

    # setAttenuationCurve requires the last point's x to equal RadiusMax exactly.
    # getAttenuationCurve sometimes returns curves whose last x != RadiusMax
    # (e.g. Obstruction Volume stored as 0-100 when RadiusMax is 500).
    # We handle this universally: for any Custom curve whose last x != radius_max,
    # scale all x values proportionally so that last x = radius_max.

    # Cone filter properties on the Attenuation object (regular scalar props)
    _CONE_PROPS = [
        "ConeUse",
        "ConeInnerAngle",
        "ConeOuterAngle",
        "ConeAttenuation",
        "ConeLowPassFilterValue",
        "ConeHighPassFilterValue",
    ]

    def get_attenuation_curves(self, attenuation_guid: str) -> dict:
        """
        Fetch all curve data + cone properties + RadiusMax from an Attenuation ShareSet.

        Returns:
            {
                "guid":       attenuation_guid,
                "name":       "...",
                "radius_max": 500.0,
                "curves":     {"VolumeDryUsage": {"use": "Custom", "points": [...]}, ...},
                "cone":       {"ConeUse": True, "ConeInnerAngle": 360.0, ...},
            }
        Returns empty dict if the object can't be reached.
        Note: Attenuation RTPCs are intentionally excluded (WAAPI curve-write limitation).
        """
        if self._call_fn is None or not attenuation_guid or not attenuation_guid.strip():
            return {}

        # Get name, RadiusMax, and cone properties in one call
        return_fields = ["name", "RadiusMax"] + self._CONE_PROPS
        meta = self.call(
            "ak.wwise.core.object.get",
            {"from": {"id": [attenuation_guid]}, "options": {"return": return_fields}},
            timeout=10,
        )
        if not meta or not meta.get("return"):
            return {}
        meta_obj   = meta["return"][0]
        att_name   = meta_obj.get("name", "")
        radius_max = meta_obj.get("RadiusMax", 100.0) or 100.0

        cone: dict = {p: meta_obj[p] for p in self._CONE_PROPS if p in meta_obj}

        curves: dict = {}
        for usage in self._ATTENUATION_CURVE_USAGES:
            result = self.call(
                "ak.wwise.core.object.getAttenuationCurve",
                {"object": attenuation_guid, "curveType": usage},
                timeout=10,
            )
            if result is None:
                continue
            curves[usage] = {
                "use":    result.get("use", "None"),
                "points": result.get("points", []),
            }

        if not curves and not cone:
            return {}

        return {
            "guid":       attenuation_guid,
            "name":       att_name,
            "radius_max": radius_max,
            "curves":     curves,
            "cone":       cone,
        }

    def set_attenuation_curves(self, attenuation_data: dict) -> bool:
        """
        Restore all curves + cone properties to the stored Attenuation object.
        Attenuation RTPCs are intentionally excluded (WAAPI curve-write limitation).

        Returns True if all operations succeeded without error.
        """
        if self._call_fn is None or not attenuation_data:
            return True

        att_guid   = attenuation_data.get("guid", "")
        curves     = attenuation_data.get("curves", {})
        cone       = attenuation_data.get("cone", {})
        radius_max = attenuation_data.get("radius_max", 100.0) or 100.0
        if not att_guid or not att_guid.strip():
            return True

        # Verify the Attenuation object still exists in the current project
        # before attempting any writes (avoids unknown_object errors).
        verify = self.call(
            "ak.wwise.core.object.get",
            {"from": {"id": [att_guid]}, "options": {"return": ["id"]}},
            timeout=5,
        )
        if not verify or not verify.get("return"):
            print(f"[WwiseSnap] Attenuation GUID {att_guid} not found in current project — skipping restore.")
            return False

        all_ok = True

        # ── 1. Restore distance / obstruction / … curves ─────────────────────
        for get_usage, curve in curves.items():
            if get_usage in self._RESTORE_UNSUPPORTED:
                continue

            set_usage = self._ATTENUATION_GET_TO_SET.get(get_usage, get_usage)
            use       = curve.get("use", "Custom")
            points    = list(curve.get("points", []))

            if use == "UseProject" and set_usage in self._HSF_CURVE_TYPES:
                continue

            if use == "Custom" and points:
                last_x = points[-1].get("x", 0.0)
                if last_x > 0 and abs(last_x - radius_max) > 0.001:
                    s = radius_max / last_x
                    points = [
                        {"x": p["x"] * s, "y": p["y"], "shape": p.get("shape", "Linear")}
                        for p in points
                    ]

            r = self.call(
                "ak.wwise.core.object.setAttenuationCurve",
                {
                    "object":    att_guid,
                    "curveType": set_usage,
                    "use":       use,
                    "points":    points,
                },
                timeout=10,
            )
            if r is None:
                all_ok = False

        # ── 2. Restore cone scalar properties ────────────────────────────────
        if cone:
            r = self.call(
                "ak.wwise.core.object.set",
                {"objects": [{"object": att_guid, **{"@" + k: v for k, v in cone.items()}}]},
                timeout=10,
            )
            if r is None:
                all_ok = False

        return all_ok

    def get_all_properties(self, guid: str) -> dict:
        """
        Return ALL non-metadata properties regardless of default value.
        Safely handles cases where the object might no longer exist in Wwise.
        """
        if self._call_fn is None or not guid or not guid.strip():
            return {"properties": {}, "display": {}, "modifiers": [], "attenuation": {}}

        try:
            # Step 1 — get classId
            meta = self.call(
                "ak.wwise.core.object.get",
                {
                    "from": {"id": [guid]},
                    "options": {"return": ["classId"]},
                },
                timeout=10,
            )
            if not meta or not meta.get("return"):
                return {"properties": {}, "display": {}, "modifiers": [], "attenuation": {}}
            class_id: int = meta["return"][0].get("classId", 0)
            if not class_id:
                return {"properties": {}, "display": {}, "modifiers": [], "attenuation": {}}

            # Step 2 — get schema (may take a few seconds on first call per classId)
            schema = _get_property_schema(self._call_fn, class_id)

            # Step 3 — fetch all property values in one WAAPI round-trip
            props = self.get_object_properties(guid, schema)
            if not props:
                return {"properties": {}, "display": {}, "modifiers": [], "attenuation": {}}
        except Exception as e:
            # Object might have been deleted or connection lost
            print(f"[WwiseSnap] Error fetching object info: {e}")
            return {"properties": {}, "display": {}, "modifiers": [], "attenuation": {}}

        all_props: dict = {}
        schema_display: dict = schema.get("display", {})

        # Category B — UNLINK props: bare value is always the object's own local value.
        # Save ALL of them regardless of default.
        for key in schema["unlink"]:
            if key not in props:
                continue
            val = props[key]
            # Reference props return a dict — store full {id, name} for restore
            if isinstance(val, dict) and "id" in val:
                all_props[key] = {"id": val["id"], "name": val.get("name", "")}
            else:
                all_props[key] = val

        # Category A — Override-flag props: save local value AND override flag state.
        # The @ prefix was used in the query, so the key in props is "@PropName".
        saved_flags: set = set()
        for key, flag in schema["override"].items():
            at_key = f"@{key}"
            if at_key not in props and key not in props:
                continue

            # Local value (@PropName) — what restore will write back
            local_val = props.get(at_key, props.get(key))
            # Effective value (bare PropName) — inherited from parent when Override OFF
            effective_val = props.get(key)
            override_active = bool(props.get(flag, False))

            # Store local value
            if isinstance(local_val, dict) and "id" in local_val:
                all_props[key] = {"id": local_val["id"], "name": local_val.get("name", "")}
            else:
                all_props[key] = local_val

            # When Override is OFF, store the effective (inherited) value separately
            # so the UI can display what's actually connected rather than the local default.
            if not override_active and effective_val is not None:
                eff_key = f"_effective_{key}"
                if isinstance(effective_val, dict) and "id" in effective_val:
                    all_props[eff_key] = {"id": effective_val["id"], "name": effective_val.get("name", "")}
                else:
                    all_props[eff_key] = effective_val

            # Save the Override flag (e.g. OverrideOutput) for restore. Once per flag.
            if flag not in saved_flags:
                all_props[flag] = override_active
                saved_flags.add(flag)

        # Build display info for ALL stored properties (excluding internal _effective_ keys)
        filtered_display: dict = {}
        for key in list(all_props.keys()):
            if key.startswith("_effective_"):
                continue
            if key in schema_display:
                filtered_display[key] = schema_display[key]

        # Step 4 — fetch Attenuation curve data if an Attenuation is assigned
        attenuation_data: dict = {}
        att_ref = all_props.get("Attenuation")
        if isinstance(att_ref, dict):
            att_guid = att_ref.get("id", "")
            if att_guid:
                attenuation_data = self.get_attenuation_curves(att_guid)

        # Step 5 — fetch Modifier (Randomizer) objects for this guid
        modifiers_list = self.get_modifiers(guid)

        # Step 6 — for randomizable props with no Modifier, add a default entry
        # (id="" marks it as display-only; restore skips these).
        existing_rand_props = {m["property"] for m in modifiers_list}
        for _prop_key, rand_display_name in schema.get("randomizable", []):
            if rand_display_name not in existing_rand_props:
                modifiers_list.append({
                    "property": rand_display_name,
                    "min": 0.0,
                    "max": 0.0,
                    "enabled": False,
                    "id": "",  # display-only default — not restored
                })

        return {
            "properties": all_props,
            "display":    filtered_display,
            "modifiers":  modifiers_list,
            "attenuation": attenuation_data,
        }

    def get_supported_properties(self, guid: str) -> set[str]:
        """Return a set of all property and reference names supported by this object."""
        if self._call_fn is None or not guid:
            return set()
        result = self.call(
            "ak.wwise.core.object.getPropertyAndReferenceNames",
            {"object": guid}
        )
        if result and result.get("return"):
            return set(result["return"])
        return set()

    def get_non_default_properties(self, guid: str) -> dict:
        """
        Return only properties that are locally overridden / differ from defaults.
        Kept for compatibility — use get_all_properties() for full snapshots.

        Alias for get_changed_properties().
        """
        return self.get_changed_properties(guid)

    def get_changed_properties(self, guid: str) -> dict:
        """
        Return only properties that differ from zero-like defaults or have
        an active override flag. Useful for display filtering in detail view.

        Steps:
        1. Fetch classId for the object.
        2. Build (or retrieve from cache) the property schema for that classId.
        3. Fetch all relevant property values.
        4. Filter: unlink props kept if non-zero/non-False/non-None/{};
                   override props kept only when their Override flag is True.

        Returns:
            {
                "properties": {prop_name: value, ...},
                "display": {prop_name: {"name": display_name, "group": group_name}, ...},
            }
        """
        if self._call_fn is None or not guid or not guid.strip():
            return {"properties": {}, "display": {}}

        # Step 1 — get classId
        meta = self.call(
            "ak.wwise.core.object.get",
            {
                "from": {"id": [guid]},
                "options": {"return": ["classId"]},
            },
            timeout=10,
        )
        if not meta or not meta.get("return"):
            return {"properties": {}, "display": {}}
        class_id: int = meta["return"][0].get("classId", 0)
        if not class_id:
            return {"properties": {}, "display": {}}

        # Step 2 — get schema (may take a few seconds on first call per classId)
        schema = _get_property_schema(self._call_fn, class_id)

        # Step 3 — fetch all property values in one WAAPI round-trip
        props = self.get_object_properties(guid, schema)
        if not props:
            return {"properties": {}, "display": {}}

        filtered: dict = {}
        schema_display: dict = schema.get("display", {})

        # Category B — UNLINK_SUPPORTED: bare value is always the object's own local value.
        # Save if it differs from a "zero-like" default.
        _zero_like = (0, 0.0, False, None, {})
        for key in schema["unlink"]:
            if key not in props:
                continue
            val = props[key]
            # For reference properties that return a dict, extract the name string.
            if isinstance(val, dict):
                val = val.get("name", val)
            if val not in _zero_like:
                filtered[key] = val

        # Category A — Override-flag properties: only save when the flag is True.
        for key, flag in schema["override"].items():
            at_key = f"@{key}"
            if at_key not in props and key not in props:
                continue
            if not props.get(flag, False):
                continue
            val = props.get(at_key, props.get(key))
            # For reference properties that return a dict, extract the name string.
            if isinstance(val, dict):
                val = val.get("name", val)
            # Keep even if val is False — override is explicitly active.
            filtered[key] = val

        # Build display info only for the properties we're keeping.
        filtered_display: dict = {}
        for key in filtered:
            if key in schema_display:
                filtered_display[key] = schema_display[key]

        return {"properties": filtered, "display": filtered_display}

    def set_object_properties(self, guid: str, properties: dict) -> bool:
        """
        Set scalar properties on an object using @ notation.

        All scalar properties including Override flags (OverrideOutput,
        OverridePositioning, …) use the @ prefix — bare names are rejected
        by ak.wwise.core.object.set with 'unknown argument'.
        """
        if not guid or not guid.strip() or not properties:
            return False
        at_props = {f"@{k}": v for k, v in properties.items()}
        obj_spec = {"object": guid, **at_props}
        result = self.call(
            "ak.wwise.core.object.set",
            {"objects": [obj_spec]},
            timeout=10,
        )
        return result is not None

    def set_object_reference(self, obj_guid: str, reference_name: str, ref_guid: str) -> bool:
        """
        Set a reference property (e.g. OutputBus, Attenuation) on an object.

        Uses ak.wwise.core.object.setReference with the GUID of the target object.
        """
        if not obj_guid or not obj_guid.strip() or not ref_guid or not ref_guid.strip():
            return False
        result = self.call(
            "ak.wwise.core.object.setReference",
            {
                "object": obj_guid,
                "reference": reference_name,
                "value": ref_guid,
            },
            timeout=10,
        )
        return result is not None


# Module-level singleton
_client: WaapiClientWrapper | None = None


def get_client() -> WaapiClientWrapper:
    global _client
    if _client is None:
        _client = WaapiClientWrapper()
    return _client
