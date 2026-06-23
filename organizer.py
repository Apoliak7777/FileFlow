"""
FileFlow

Modern Windows file organizer with rich interactive preview, smart categorization,
Live Auto + tray, powerful Find & Delete, duplicates, undo and profiles.

Key things users rely on daily:
- Fast interactive list with thumbnails, per-file category cycling and exclusion
- High-accuracy categorization (name + content + EXIF + Slovak/English patterns)
- Live watching + background tray mode
- Whole-PC Find & Delete with safety protections
- Exact + perceptual duplicate detection
- Dry run, undo, profiles and rules

Clean, focused, no unnecessary bloat.

Built with Python + CustomTkinter + Pillow.
"""

from __future__ import annotations

import base64
import ctypes
import fnmatch
import io
import json
import os
import shutil
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageTk

# Optional premium deps (graceful fallback)
try:
    import tkinterdnd2 as dnd
    HAS_DND = True
except Exception:
    HAS_DND = False

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except Exception:
    HAS_WATCHDOG = False

try:
    import pystray
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False


# --------------------------------------------------------------------------- #
#  Constants & theming
# --------------------------------------------------------------------------- #

APP_NAME = "FileFlow"
VERSION = "7.0"
GITHUB_URL = "https://github.com/Apoliak7777/FileFlow"
UNDO_FILE = ".organizer_undo.json"
CONFIG_FILE = "organizer_config.json"
MAX_HISTORY = 20

# ==================== THEME & COLORS ====================
C = {
    "bg":        ("#F7F7F8", "#050505"),      # almost pure black
    "surface":   ("#FFFFFF", "#0F0F11"),      # deep card
    "surface2":  ("#F1F1F3", "#18181B"),      # control / hover
    "surface3":  ("#E8E8EB", "#1F1F22"),      # very subtle
    "card":      ("#FFFFFF", "#0F0F11"),
    "cardHover": ("#F9F9FA", "#16161A"),
    "border":    ("#D9D9DE", "#27272A"),
    "textHi":    ("#0A0A0C", "#F4F4F5"),
    "textLo":    ("#4B4B52", "#A3A3AA"),
    "textMuted": ("#6B6B72", "#71717A"),
    "glass":     ("#FFFFFF", "#0F0F11"),
    "sidebar":   ("#F0F0F2", "#08080A"),
}

# Accent color
DEFAULT_ACCENT = "#00F5D4"
ACCENT_HOVER = "#00D9BC"
SUCCESS = "#10B981"
DANGER = "#F43F5E"
WARNING = "#FBBF24"
INFO = "#00F5D4"

# Current runtime accent (updated live)
_current_accent = DEFAULT_ACCENT
_current_accent_hover = ACCENT_HOVER

# ==================== CATEGORIES ====================
CATEGORIES = {
    "Images":    ("#F472B6", "IMG", [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg",
                                    ".tiff", ".ico", ".heic", ".heif", ".avif", ".raw"]),
    "Documents": ("#60A5FA", "DOC", [".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls",
                                    ".xlsx", ".ppt", ".pptx", ".csv", ".md", ".epub", ".pages",
                                    ".numbers", ".key"]),
    "Videos":    ("#A78BFA", "VID", [".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm",
                                    ".m4v", ".mpg", ".mpeg", ".m4v"]),
    "Music":     ("#34D399", "MUS", [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma",
                                    ".opus"]),
    "Archives":  ("#FBBF24", "ZIP", [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso",
                                    ".lz", ".lzma"]),
    "Programs":  ("#FB7185", "EXE", [".exe", ".msi", ".bat", ".cmd", ".apk", ".jar", ".ps1"]),
    "Code":      ("#22D3EE", "COD", [".py", ".js", ".ts", ".html", ".css", ".php", ".java",
                                    ".c", ".cpp", ".cs", ".json", ".xml", ".sql",
                                    ".go", ".rs", ".yml", ".yaml", ".toml", ".ini", ".vue",
                                    ".tsx", ".jsx", ".bat", ".ps1"]),
    "Other":     ("#94A3B8", "OTH", []),
}

CATEGORY_ORDER = list(CATEGORIES.keys())
EXT_TO_CATEGORY = {
    ext: name for name, (_, _, exts) in CATEGORIES.items() for ext in exts
}
MANAGED_FOLDERS = set(CATEGORIES.keys())

# Module-level cache for generated category icons (shared by all FileRows).
_ICON_CACHE: dict = {}

# ==================== HELPERS ====================
def set_accent(new_accent: str):
    """Live update global accent color."""
    global _current_accent, _current_accent_hover
    _current_accent = new_accent
    # compute hover (slightly darker)
    try:
        r, g, b = int(new_accent[1:3], 16), int(new_accent[3:5], 16), int(new_accent[5:7], 16)
        _current_accent_hover = "#%02x%02x%02x" % (max(0, r-20), max(0, g-20), max(0, b-20))
    except Exception:
        _current_accent_hover = new_accent

def get_accent() -> str:
    return _current_accent

def get_accent_hover() -> str:
    return _current_accent_hover

def generate_category_icon(name: str, size: int = 72) -> ImageTk.PhotoImage:
    """Generate category icon."""
    color, short, _ = CATEGORIES.get(name, ("#94A3B8", "OTH", []))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = int(size * 0.28)

    # Rich background
    draw.rounded_rectangle([0, 0, size-1, size-1], radius=radius, fill=color)

    # Inner highlight
    shine = (*[min(255, c + 75) for c in (int(color[1:3],16), int(color[3:5],16), int(color[5:7],16))], 55)
    draw.rounded_rectangle([3, 3, size-4, size//2 + 4], radius=radius-3, fill=shine)

    # Text — prominent, high quality
    try:
        font = ImageFont.truetype("segoeui.ttf", int(size * 0.48))
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", int(size * 0.48))
        except Exception:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), short, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2
    y = (size - th) // 2 - 1
    draw.text((x, y), short, fill="white", font=font)

    return ImageTk.PhotoImage(img)

def generate_simple_icon(emoji_or_text: str, bg: str, size: int = 28) -> ImageTk.PhotoImage:
    """Small rounded icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size-1, size-1], radius=size//2.2, fill=bg)
    try:
        font = ImageFont.truetype("segoeui.ttf", int(size * 0.48))
    except:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), emoji_or_text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((size - tw) // 2, (size - th) // 2 - 1), emoji_or_text, fill="white", font=font)
    return ImageTk.PhotoImage(img)

def get_thumbnail(path: Path, size: int = 44) -> ImageTk.PhotoImage | None:
    """Generate a nice thumbnail for images. Returns None for non-images."""
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        return None
    try:
        with Image.open(path) as im:
            im.thumbnail((size, size))
            # Rounded mask for thumbnail
            rounded = Image.new("RGBA", (size, size), (0,0,0,0))
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0,0,size-1,size-1], radius=10, fill=255)
            out = Image.new("RGBA", (size, size), (0,0,0,0))
            out.paste(im.convert("RGBA"), (0,0))
            out.putalpha(mask)
            return ImageTk.PhotoImage(out)
    except Exception:
        return None

# Default ignore patterns (case-insensitive matching on Windows)
DEFAULT_IGNORES = [
    "desktop.ini",
    "thumbs.db",
    "ehthumbs.db",
    "*.tmp",
    "*~",
    "*.crdownload",
    "*.part",
    "~$*",
]


# --------------------------------------------------------------------------- #
#  Pure helpers
# --------------------------------------------------------------------------- #

def resource_path(rel: str) -> Path:
    """Resolve a bundled asset path, works in dev and inside a PyInstaller exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / rel


def mode_color(pair) -> str:
    """Return the hex for the current appearance mode from a (light, dark) tuple."""
    if isinstance(pair, (tuple, list)):
        return pair[0] if ctk.get_appearance_mode() == "Light" else pair[1]
    return pair


def category_for(path: Path) -> str:
    """Basic extension based. Enhanced smart logic is in smart_categorize."""
    return EXT_TO_CATEGORY.get(path.suffix.lower(), "Other")

def smart_categorize(path: Path) -> str:
    """
    Practical, high-accuracy categorization for real people.
    Focus on what users actually have cluttering Downloads/Desktop.
    """
    name = path.name.lower()
    suffix = path.suffix.lower()
    try:
        size = path.stat().st_size
    except:
        size = 0

    # === PRIORITY 1: Common real-world clutter patterns (Slovak + English) ===
    import re
    patterns = [
        # Images / Screenshots
        (r'(screenshot|snímka|screen.?shot|snimka|cap|img_|pic_|dsc_|photo|fotka|screen)', 'Images'),
        # Documents
        (r'(invoice|faktúra|faktur|receipt|uctenka|účet|bill|resume|cv|životopis|motivačný|cover|contract|zmluva|agreement|podpis|dohoda)', 'Documents'),
        # Archives / Backups
        (r'(backup|záloha|archive|archív|zip|rar|export)', 'Archives'),
        # Videos
        (r'(video|vid_|movie|film|rec_|nahrávka|screen.?record)', 'Videos'),
        # Music
        (r'(song|track|beat|mix|master|audio|hudba)', 'Music'),
        # Programs / Installers
        (r'(setup|install|installer|crack|patch|portable|exe)', 'Programs'),
        # Code
        (r'(\.py$|\.js$|src|source|code|projekt)', 'Code'),
    ]
    for pattern, cat in patterns:
        if re.search(pattern, name):
            return cat

    # === PRIORITY 2: Image intelligence (EXIF + content) ===
    if suffix in ('.jpg', '.jpeg', '.png', '.heic', '.webp', '.tiff'):
        try:
            with Image.open(path) as img:
                # EXIF date intelligence
                exif = img.getexif()
                if exif:
                    for tag_id in (36867, 36868, 306):  # DateTimeOriginal, etc.
                        if tag_id in exif:
                            return 'Images'
                # Large photos often personal
                if size > 3_000_000:
                    return 'Images'
        except:
            pass
        return 'Images'

    # === PRIORITY 3: Document intelligence (content sniffing + PDF) ===
    if suffix in ('.pdf', '.txt', '.docx', '.md'):
        text = ""
        try:
            if suffix == '.pdf':
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                for page in reader.pages[:3]:  # first 3 pages
                    text += page.extract_text() or ""
                text = text[:3000].lower()
            else:
                text = path.read_text(encoding='utf-8', errors='ignore')[:3000].lower()
            if any(w in text for w in ['invoice', 'faktúra', 'receipt', 'contract', 'zmluva', 'total', 'suma', 'účet']):
                return 'Documents'
            if any(w in text for w in ['def ', 'import ', 'class ', 'function', 'todo', 'fixme']):
                return 'Code'
            if 'screenshot' not in name and size < 2_000_000:
                return 'Documents'
        except:
            pass
        return 'Documents'

    # === Practical fallbacks for regular users ===
    # Old files -> Archives
    try:
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days > 180 and suffix not in ('.jpg', '.png', '.mp4'):
            return 'Archives'
    except:
        pass

    # Large files often archives or videos
    if size > 100_000_000:
        if suffix in ('.mp4', '.mov', '.avi'):
            return 'Videos'
        return 'Archives'

    # Default to extension-based
    return category_for(path)

def get_date_subfolder(path: Path) -> str:
    """Return YYYY-MM for date based organization."""
    try:
        ts = path.stat().st_mtime
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m")
    except Exception:
        return "Unknown"


def unique_destination(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    i = 1
    while True:
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def scan_folder(base: Path, recursive: bool = False, ignore_patterns: list[str] | None = None):
    """Return list of (Path, category) for loose files.

    By default only top-level files (original behavior).
    When recursive=True, walks subdirectories but skips any directory
    whose name is a managed category folder.
    ignore_patterns are matched case-insensitively against the filename.
    """
    ignore_patterns = ignore_patterns or []
    out = []

    def _should_skip_dir(d: Path) -> bool:
        return d.name in MANAGED_FOLDERS

    def _matches_ignore(name: str) -> bool:
        lname = name.lower()
        for pat in ignore_patterns:
            if fnmatch.fnmatch(lname, pat.lower()) or fnmatch.fnmatch(name, pat):
                return True
        return False

    if not recursive:
        for entry in base.iterdir():
            if entry.is_file() and not entry.name.startswith(".") and not _matches_ignore(entry.name):
                out.append((entry, category_for(entry)))
        return out

    # Recursive walk
    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        # Prune managed folders so we never descend into them
        dirs[:] = [d for d in dirs if not _should_skip_dir(root_path / d)]

        for fname in files:
            if fname.startswith("."):
                continue
            if _matches_ignore(fname):
                continue
            fpath = root_path / fname
            out.append((fpath, category_for(fpath)))
    return out


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024


def get_perceptual_hash(path: Path) -> str | None:
    """
    Simple but effective average hash (aHash) using only Pillow.
    Great for finding visually similar images/screenshots.
    Returns 16-char hex string or None.
    """
    try:
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic"):
            return None
        with Image.open(path) as im:
            # Resize to 8x8 grayscale
            im = im.convert("L").resize((8, 8), Image.LANCZOS)
            pixels = list(im.getdata())
            avg = sum(pixels) / len(pixels)
            # Build 64-bit binary string
            bits = "".join("1" if px > avg else "0" for px in pixels)
            return hex(int(bits, 2))[2:].zfill(16)
    except Exception:
        return None


def hamming_distance(hash1: str, hash2: str) -> int:
    """Count differing bits between two hex perceptual hashes."""
    try:
        i1 = int(hash1, 16)
        i2 = int(hash2, 16)
        return bin(i1 ^ i2).count("1")
    except Exception:
        return 999


def should_ignore(name: str, patterns: list[str]) -> bool:
    """Case-insensitive match against the provided patterns (globs or literals)."""
    lname = name.lower()
    for pat in patterns:
        p = pat.lower()
        if fnmatch.fnmatch(lname, p) or fnmatch.fnmatch(name, pat):
            return True
    return False

@dataclass
class PlanItem:
    """Mutable plan item for interactive file list."""
    path: Path
    category: str
    selected: bool = True
    custom_category: Optional[str] = None   # user override

    @property
    def effective_category(self) -> str:
        return self.custom_category or self.category

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except Exception:
            return 0

    @property
    def mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except Exception:
            return 0

    def to_tuple(self):
        return (str(self.path), self.effective_category)


@dataclass
class Rule:
    """Powerful rule for the best organizer."""
    condition_type: str  # "filename_contains", "filename_regex", "size_gt", "size_lt", "ext", "age_days_gt"
    condition_value: str
    target_category: str
    priority: int = 10  # lower = higher priority
    enabled: bool = True

    def matches(self, path: Path) -> bool:
        name = path.name.lower()
        suffix = path.suffix.lower()
        try:
            size = path.stat().st_size
            mtime = path.stat().st_mtime
            age_days = (time.time() - mtime) / 86400
        except:
            size = 0
            age_days = 999

        if self.condition_type == "filename_contains":
            return self.condition_value.lower() in name
        elif self.condition_type == "filename_regex":
            import re
            try:
                return bool(re.search(self.condition_value, name))
            except:
                return False
        elif self.condition_type == "ext":
            return suffix == self.condition_value.lower() or self.condition_value.lower() in suffix
        elif self.condition_type == "size_gt":
            return size > int(self.condition_value) * 1024 * 1024  # MB
        elif self.condition_type == "size_lt":
            return size < int(self.condition_value) * 1024 * 1024
        elif self.condition_type == "age_days_gt":
            return age_days > float(self.condition_value)
        return False


def get_config_path() -> Path:
    """Return a good location for config.json that keeps the exe portable when possible."""
    try:
        # When running as PyInstaller exe
        if getattr(sys, "_MEIPASS", None):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).parent
        candidate = base / CONFIG_FILE
        # Test writability (touch + unlink if possible)
        candidate.touch(exist_ok=True)
        candidate.unlink(missing_ok=True)
        return candidate
    except Exception:
        # Fallback
        return Path.home() / ".fileflow" / CONFIG_FILE


def load_config() -> dict:
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data: dict) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Reusable widgets
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
#  Admin elevation, path protection & safe delete (Find & Delete feature)
# --------------------------------------------------------------------------- #

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    from ctypes import wintypes

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]


def is_admin() -> bool:
    """True if the process is running elevated (Administrator)."""
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Restart this app elevated via UAC. Returns True if the elevated process
    launched (the caller should then close the current instance)."""
    if not IS_WINDOWS:
        return False
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv[1:])
        else:
            exe = sys.executable
            params = " ".join([f'"{os.path.abspath(sys.argv[0])}"']
                              + [f'"{a}"' for a in sys.argv[1:]])
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return int(r) > 32
    except Exception:
        return False


def _system_trees() -> list[str]:
    env = os.environ
    drive = env.get("SystemDrive", "C:")
    cand = [
        env.get("SystemRoot") or env.get("windir") or (drive + "\\Windows"),
        drive + "\\Program Files",
        drive + "\\Program Files (x86)",
        env.get("ProgramData") or (drive + "\\ProgramData"),
        drive + "\\$Recycle.Bin",
        drive + "\\Recovery",
        drive + "\\System Volume Information",
    ]
    try:
        cand.append(str(Path(sys.argv[0]).resolve().parent))  # the app's own dir
    except Exception:
        pass
    out = []
    for c in cand:
        if c:
            out.append(os.path.normpath(c).rstrip("\\/").lower())
    return list(dict.fromkeys(out))


SYSTEM_TREES = _system_trees() if IS_WINDOWS else []


def is_protected_path(path: Path) -> bool:
    """Paths that must never be deleted, even with admin: drive roots, the
    Windows / Program Files / ProgramData trees, C:\\Users and any whole user
    profile, the user's own home, and the app's own folder."""
    try:
        rp = path.resolve()
    except Exception:
        rp = path
    low = os.path.normpath(str(rp)).rstrip("\\/").lower()
    if not low or low in (".", ".."):
        return True
    if len(low) <= 3 and low.endswith(":"):       # drive root  e.g. "c:" / "c:\"
        return True
    if IS_WINDOWS:
        users_dir = (os.environ.get("SystemDrive", "C:") + "\\users").lower()
        if low == users_dir or os.path.dirname(low) == users_dir:
            return True                            # C:\Users or a whole profile
    try:
        if rp == Path.home().resolve():
            return True
    except Exception:
        pass
    for tree in SYSTEM_TREES:
        if low == tree or low.startswith(tree + "\\"):
            return True
    return False


def send_to_recycle_bin(path: Path) -> bool:
    """Move a file/folder to the Recycle Bin (recoverable). Windows only."""
    if not IS_WINDOWS:
        return False
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = 3                                   # FO_DELETE
    op.pFrom = str(path) + "\x00\x00"              # must be double-null terminated
    op.pTo = None
    op.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400  # ALLOWUNDO|NOCONFIRM|SILENT|NOERRORUI
    try:
        return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0
    except Exception:
        return False


def delete_path(path: Path, to_recycle: bool) -> tuple[bool, str]:
    """Delete a path safely. Returns (ok, human message)."""
    if is_protected_path(path):
        return False, "protected system path — refused"
    try:
        if to_recycle:
            return (True, "moved to Recycle Bin") if send_to_recycle_bin(path) \
                else (False, "could not move to Recycle Bin")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True, "permanently deleted"
    except PermissionError:
        return False, "permission denied (try Restart as Admin)"
    except FileNotFoundError:
        return False, "already gone"
    except Exception as e:
        return False, str(e)


# ------------------ Windows Context Menu (FileFlow) ------------------

def _get_exe_path_for_registry() -> str:
    """Return the path to the exe (or python script during dev)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    else:
        # Dev mode: run with python
        return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


def register_context_menu(app_name: str = "FileFlow"):
    """Add right-click options for folders."""
    if not IS_WINDOWS:
        return False, "Only available on Windows"

    import winreg as reg
    try:
        exe_cmd = _get_exe_path_for_registry()

        # For folders
        for root in [r"Directory\shell", r"Directory\Background\shell"]:
            key_path = rf"{root}\{app_name}"
            with reg.CreateKey(reg.HKEY_CLASSES_ROOT, key_path) as key:
                reg.SetValue(key, "", reg.REG_SZ, "Organize with FileFlow")
                reg.SetValueEx(key, "Icon", 0, reg.REG_SZ, sys.executable if getattr(sys, "frozen", False) else "")

            cmd_key = rf"{key_path}\command"
            with reg.CreateKey(reg.HKEY_CLASSES_ROOT, cmd_key) as key:
                # %V or %1 gives the folder path
                reg.SetValue(key, "", reg.REG_SZ, f'{exe_cmd} "%V"')

        # Also add "Find & Delete here"
        for root in [r"Directory\shell", r"Directory\Background\shell"]:
            key_path = rf"{root}\{app_name}Find"
            with reg.CreateKey(reg.HKEY_CLASSES_ROOT, key_path) as key:
                reg.SetValue(key, "", reg.REG_SZ, "Find & Delete with FileFlow")
            cmd_key = rf"{key_path}\command"
            with reg.CreateKey(reg.HKEY_CLASSES_ROOT, cmd_key) as key:
                reg.SetValue(key, "", reg.REG_SZ, f'{exe_cmd} "%V"')

        return True, "Context menu registered successfully. Restart Explorer or log out to see changes."
    except Exception as e:
        return False, f"Failed to register: {e}"


def unregister_context_menu(app_name: str = "FileFlow"):
    """Remove the context menu entries."""
    if not IS_WINDOWS:
        return False, "Only available on Windows"

    import winreg as reg
    try:
        for root in [r"Directory\shell", r"Directory\Background\shell"]:
            for name in [app_name, f"{app_name}Find"]:
                try:
                    reg.DeleteKey(reg.HKEY_CLASSES_ROOT, rf"{root}\{name}\command")
                except:
                    pass
                try:
                    reg.DeleteKey(reg.HKEY_CLASSES_ROOT, rf"{root}\{name}")
                except:
                    pass
        return True, "Context menu unregistered."
    except Exception as e:
        return False, f"Failed to unregister: {e}"


class ConfirmDialog(ctk.CTkToplevel):
    """Small modal Yes/No dialog that matches the app theme."""

    def __init__(self, parent, title, message, ok_text="Confirm",
                 ok_color=get_accent(), ok_hover=get_accent_hover()):
        super().__init__(parent)
        self.result = False
        self.title(title)
        self.resizable(False, False)
        self.configure(fg_color=C["surface"])
        self.transient(parent)

        w, h = 400, 190
        self.geometry(self._center(parent, w, h))

        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=C["textHi"]).pack(padx=26, pady=(24, 6), anchor="w")
        ctk.CTkLabel(self, text=message, font=ctk.CTkFont(size=13),
                     text_color=C["textLo"], justify="left", wraplength=340
                     ).pack(padx=26, anchor="w")

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=22, pady=20)
        ctk.CTkButton(row, text="Cancel", width=110, height=38, corner_radius=10,
                      fg_color=C["surface2"], hover_color=C["border"],
                      text_color=C["textHi"], command=self._cancel
                      ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(row, text=ok_text, width=130, height=38, corner_radius=10,
                      fg_color=ok_color, hover_color=ok_hover,
                      command=self._ok).pack(side="right")

        self.after(10, self._grab)
        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self._cancel())

    def _center(self, parent, w, h):
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        return f"{w}x{h}+{x}+{y}"

    def _grab(self):
        try:
            self.grab_set()
            self.focus()
        except tk.TclError:
            pass

    def _ok(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()

    @classmethod
    def ask(cls, *args, **kwargs) -> bool:
        dlg = cls(*args, **kwargs)
        dlg.wait_window()
        return dlg.result


class SummaryDialog(ctk.CTkToplevel):
    """Success summary dialog."""

    def __init__(self, parent, base_name: str, moves: list[tuple[str, str]]):
        super().__init__(parent)
        self.title("✨ Perfectly Organized")
        self.resizable(True, True)
        self.configure(fg_color=C["surface"])
        self.transient(parent)

        w, h = 560, 420
        self.geometry(self._center(parent, w, h))

        # Header
        ctk.CTkLabel(self, text=f"Beautifully organized {len(moves)} files",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=C["textHi"]).pack(padx=26, pady=(22, 4), anchor="w")
        ctk.CTkLabel(self, text=f"in {base_name}",
                     font=ctk.CTkFont(size=13), text_color=get_accent()).pack(padx=26, anchor="w")

        # Content box
        box = ctk.CTkTextbox(self, height=250, corner_radius=12,
                             fg_color=C["surface2"], border_color=C["border"],
                             font=ctk.CTkFont(size=12))
        box.pack(fill="both", expand=True, padx=26, pady=14)

        by_cat = {}
        for src, dst in moves:
            cat = Path(dst).parent.name
            by_cat.setdefault(cat, []).append(Path(src).name)

        for cat in sorted(by_cat):
            box.insert("end", f"▶ {cat} ({len(by_cat[cat])})\n")
            for name in by_cat[cat][:6]:
                box.insert("end", f"   • {name}\n")
            if len(by_cat[cat]) > 6:
                box.insert("end", f"   … +{len(by_cat[cat]) - 6} more\n")
            box.insert("end", "\n")

        box.configure(state="disabled")

        # Actions
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=26, pady=(0, 22))

        def _open_folder():
            try:
                p = Path(self.master.folder.get()) if hasattr(self.master, 'folder') else Path.home() / base_name
                os.startfile(str(p))
            except Exception:
                pass
            self.destroy()
        ctk.CTkButton(row, text="Open folder", width=130, height=38, corner_radius=10,
                      fg_color=C["surface2"], hover_color=C["border"],
                      command=_open_folder).pack(side="left")

        ctk.CTkButton(row, text="Done — Amazing!", width=160, height=38, corner_radius=10,
                      fg_color=get_accent(), hover_color=get_accent_hover(),
                      command=self.destroy).pack(side="right")

        self.after(60, self._grab)
        self.bind("<Escape>", lambda _: self.destroy())
        self.bind("<Return>", lambda _: self.destroy())

    def _center(self, parent, w, h):
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        return f"{w}x{h}+{x}+{y}"

    def _grab(self):
        try:
            self.grab_set()
            self.focus()
        except tk.TclError:
            pass


class StatCard(ctk.CTkFrame):
    """Animated stat card."""

    def __init__(self, parent, caption, value="—", accent=None):
        accent = accent or get_accent()
        super().__init__(parent, fg_color=C["card"], corner_radius=10,
                         border_width=1, border_color=C["border"])
        self.accent = accent
        self.caption = caption
        self._target = 0
        self.value_lbl = ctk.CTkLabel(
            self, text=value, font=ctk.CTkFont(size=26, weight="bold"),
            text_color=accent)
        self.value_lbl.pack(padx=16, pady=(12, 0), anchor="w")
        ctk.CTkLabel(self, text=caption, font=ctk.CTkFont(size=10),
                     text_color=C["textMuted"]).pack(padx=16, pady=(0, 12), anchor="w")

    def set_value(self, text: str, animate: bool = True):
        if not animate:
            self.value_lbl.configure(text=text)
            return
        # Simple count-up for numeric values
        try:
            target = int(''.join(c for c in str(text) if c.isdigit()) or 0)
        except:
            target = 0
        self._animate_to(target, text)

    def _animate_to(self, target: int, final_text: str):
        self._target = target
        current = 0
        try:
            current = int(''.join(c for c in self.value_lbl.cget("text") if c.isdigit()) or 0)
        except:
            current = 0

        steps = 14
        diff = target - current
        if diff == 0:
            self.value_lbl.configure(text=final_text)
            return

        def step(i=0):
            if i > steps:
                self.value_lbl.configure(text=final_text)
                return
            val = current + int(diff * (i / steps) ** 0.85)
            display = str(val) if "size" not in self.caption.lower() else human_size(val * 1024)  # rough
            # For size we keep final text
            if "size" in self.caption.lower() or "kb" in final_text.lower() or "mb" in final_text.lower():
                self.value_lbl.configure(text=final_text)
                return
            self.value_lbl.configure(text=str(val))
            self.after(18, lambda: step(i+1))
        step()


class CategoryRow(ctk.CTkFrame):
    """A legend row: color dot, name, count and a full-width share bar.

    Lives in a single column so it always fills the available width and never
    forces horizontal overflow.
    """

    def __init__(self, parent, name):
        super().__init__(parent, fg_color="transparent")
        color, glyph, _ = CATEGORIES[name]
        self.color = color
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text=glyph, width=32, height=32, corner_radius=8,
                     fg_color=self._tint(color), text_color=color,
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(self, text=name, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["textHi"]).grid(row=0, column=1, sticky="w")
        self.count_lbl = ctk.CTkLabel(self, text="0", anchor="e",
                                      font=ctk.CTkFont(size=12, weight="bold"),
                                      text_color=C["textHi"])
        self.count_lbl.grid(row=0, column=2, sticky="e")
        self.bar = ctk.CTkProgressBar(self, height=5, width=80, corner_radius=3,
                                      progress_color=color,
                                      fg_color=C["surface2"])
        self.bar.set(0)
        self.bar.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(3, 0))

    @staticmethod
    def _tint(hex_color: str) -> str:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        bg = (20, 20, 22)
        f = 0.18
        return "#%02x%02x%02x" % tuple(
            int(c * f + bg[i] * (1 - f)) for i, c in enumerate((r, g, b)))

    def update_count(self, count, total):
        self.count_lbl.configure(text=str(count))
        self.bar.set(count / total if total else 0)


# ==================== FILE ROW ====================
class FileRow(ctk.CTkFrame):
    """Interactive file row with thumbnail and category controls."""

    def __init__(self, parent, item: PlanItem, on_change, on_toggle_cat, thumbnail_cache):
        super().__init__(parent, fg_color=C["surface2"], corner_radius=8)
        self.item = item
        self.on_change = on_change
        self.on_toggle_cat = on_toggle_cat
        self.thumbnail_cache = thumbnail_cache

        self.grid_columnconfigure(2, weight=1)

        # Colored left accent bar for category indication
        cat_color = CATEGORIES.get(item.effective_category, ("#888", "", []))[0]
        accent_bar = ctk.CTkFrame(self, width=6, fg_color=cat_color, corner_radius=3)
        accent_bar.grid(row=0, column=0, sticky="ns", padx=(5, 0), pady=8)

        # Checkbox - bigger
        self.var = ctk.BooleanVar(value=item.selected)
        self.cb = ctk.CTkCheckBox(self, text="", variable=self.var, width=18,
                                  command=self._toggle_selected,
                                  checkmark_color=get_accent())
        self.cb.grid(row=0, column=1, padx=(10, 6), pady=10)

        # Thumbnail - much bigger
        self.thumb_lbl = ctk.CTkLabel(self, text="", width=48, height=48)
        self.thumb_lbl.grid(row=0, column=2, padx=(0, 10), pady=8)

        # Content - bigger fonts
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=3, sticky="ew", padx=(0, 8))
        content.grid_columnconfigure(0, weight=1)

        self.name_lbl = ctk.CTkLabel(content, text=item.path.name,
                                     font=ctk.CTkFont(size=13, weight="bold"),
                                     text_color=C["textHi"], anchor="w")
        self.name_lbl.grid(row=0, column=0, sticky="w")

        self.sub_lbl = ctk.CTkLabel(content,
                                    text=f"{item.path.parent.name} · {human_size(item.size)}",
                                    font=ctk.CTkFont(size=10), text_color=C["textMuted"], anchor="w")
        self.sub_lbl.grid(row=1, column=0, sticky="w")

        # Category tag - bigger and bolder
        self.cat_btn = ctk.CTkButton(self, text=item.effective_category,
                                     width=68, height=22, corner_radius=999,
                                     fg_color=cat_color, hover_color=cat_color,
                                     text_color="white", font=ctk.CTkFont(size=9, weight="bold"),
                                     command=self._cycle_category)
        self.cat_btn.grid(row=0, column=4, padx=(6, 10))

        # Date
        try:
            mtime = datetime.fromtimestamp(item.mtime).strftime("%d %b")
        except:
            mtime = "—"
        self.date_lbl = ctk.CTkLabel(self, text=mtime,
                                     font=ctk.CTkFont(size=10), text_color=C["textMuted"], width=52)
        self.date_lbl.grid(row=0, column=5, padx=(0, 10))

        self._refresh_visuals()

    def _refresh_visuals(self):
        # Try thumbnail first, fallback to category icon
        thumb = get_thumbnail(self.item.path, 52)
        if thumb:
            self.thumb_lbl.configure(image=thumb, text="")
            self.thumbnail_cache[id(self)] = thumb  # keep ref
        else:
            cat = self.item.effective_category
            if cat not in _ICON_CACHE:
                try:
                    _ICON_CACHE[cat] = generate_category_icon(cat, 36)
                except Exception:
                    pass
            icon = _ICON_CACHE.get(cat)
            if icon:
                self.thumb_lbl.configure(image=icon, text="")

        self._refresh_cat_button()

    def _refresh_cat_button(self):
        cat = self.item.effective_category
        col = CATEGORIES.get(cat, ("#888", "OTH", []))[0]
        self.cat_btn.configure(text=cat, fg_color=col, hover_color=col)

    def _toggle_selected(self):
        self.item.selected = self.var.get()
        self.on_change()

    def _cycle_category(self):
        cats = CATEGORY_ORDER
        current = self.item.effective_category
        idx = cats.index(current) if current in cats else 0
        new_cat = cats[(idx + 1) % len(cats)]
        self.item.custom_category = new_cat
        self._refresh_cat_button()

        # User learning - auto create high-priority rule for best experience
        app = self.winfo_toplevel()  # reliably the OrganizerApp instance
        if hasattr(app, "rules"):
            rule = Rule(condition_type="filename_contains", condition_value=self.item.path.name.lower()[:20],
                        target_category=new_cat, priority=2)
            app.rules.append(rule)
            app._save_config()
            if hasattr(app, "_refresh_rules_list"):
                app._refresh_rules_list()
        self.on_toggle_cat()


class DonutChart(ctk.CTkFrame):
    """Interactive donut chart for category breakdown."""

    def __init__(self, parent, size=210, on_segment_click=None):
        super().__init__(parent, fg_color="transparent")
        self.size = size
        self.on_segment_click = on_segment_click
        self.canvas = tk.Canvas(self, width=size, height=size,
                                highlightthickness=0, bd=0,
                                bg=mode_color(C["card"]))
        self.canvas.pack()
        self.data = {}
        self._last_counts = {}
        self.draw({})
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_hover)

    def draw(self, counts: dict, highlight: str | None = None):
        self.data = counts
        self._last_counts = counts
        cv = self.canvas
        cv.configure(bg=mode_color(C["card"]))
        cv.delete("all")
        s = self.size
        pad = 10
        ring_width = 18
        box = (pad, pad, s - pad, s - pad)
        total = sum(counts.values()) or 1

        # Soft outer ring
        cv.create_oval(pad-2, pad-2, s-pad+2, s-pad+2, outline=mode_color(C["surface3"]), width=1)

        # Track
        cv.create_arc(*box, start=0, extent=359.9, style="arc",
                      outline=mode_color(C["surface2"]), width=ring_width)

        # Segments
        angle = 90.0
        for name in CATEGORY_ORDER:
            n = counts.get(name, 0)
            if n <= 0:
                continue
            extent = -(n / total) * 360
            col = CATEGORIES[name][0]
            if highlight and highlight != name:
                col = self._desaturate(col)
            cv.create_arc(*box, start=angle, extent=extent, style="arc",
                          outline=col, width=ring_width)
            angle += extent

        # Center disc
        cx = cy = s / 2
        inner_r = (s - pad*2 - ring_width) / 2 
        cv.create_oval(cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r,
                       fill=mode_color(C["card"]), outline=mode_color(C["border"]), width=1)

        # Typography
        cv.create_text(cx, cy - 4, text=str(sum(counts.values())),
                       fill=mode_color(C["textHi"]),
                       font=("Segoe UI", 28, "bold"))
        cv.create_text(cx, cy + 16, text="files",
                       fill=mode_color(C["textMuted"]), font=("Segoe UI", 9))

    def _desaturate(self, hexcol: str, factor=0.55) -> str:
        try:
            r, g, b = int(hexcol[1:3],16), int(hexcol[3:5],16), int(hexcol[5:7],16)
            gray = int(0.3*r + 0.59*g + 0.11*b)
            nr = int(gray * factor + r * (1-factor))
            ng = int(gray * factor + g * (1-factor))
            nb = int(gray * factor + b * (1-factor))
            return f"#{nr:02x}{ng:02x}{nb:02x}"
        except:
            return hexcol

    def _on_click(self, event):
        if not self.on_segment_click or not self.data:
            return
        # crude hit test by angle
        cx = cy = self.size / 2
        dx, dy = event.x - cx, event.y - cy
        import math
        ang = (math.degrees(math.atan2(dy, dx)) + 90) % 360   # our start is 90
        total = sum(self.data.values()) or 1
        current = 90.0
        for name in CATEGORY_ORDER:
            n = self.data.get(name, 0)
            if n > 0:
                ext = (n / total) * 360
                if current - ext <= ang <= current:
                    self.on_segment_click(name)
                    return
                current -= ext

    def _on_hover(self, event):
        # subtle cursor hint
        self.canvas.config(cursor="hand2")


# --------------------------------------------------------------------------- #
#  Main application
# --------------------------------------------------------------------------- #

class OrganizerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(APP_NAME)
        self.geometry("1260x820")
        self.minsize(1100, 720)
        self.configure(fg_color=C["bg"])
        try:
            self.iconbitmap(resource_path("assets/app.ico"))
        except Exception:
            pass

        # State
        self.folder = ctk.StringVar(value=str(self._default_folder()))
        self.confirm_before = ctk.BooleanVar(value=True)
        self.open_after = ctk.BooleanVar(value=False)
        self.recursive = ctk.BooleanVar(value=False)
        self.live_mode = ctk.BooleanVar(value=False)
        self.use_date_folders = ctk.BooleanVar(value=False)
        self.dry_run = ctk.BooleanVar(value=False)  # Best safety feature - simulation mode
        self.delete_empty_after = ctk.BooleanVar(value=True)  # Practical: clean up empty category folders
        self.rules: list[Rule] = []  # User + profile rules for ultimate control
        self.current_profile = "Default"
        self.profiles: dict = {"Default": {}}  # Will store rules, ignores etc per profile

        self.cards: dict[str, CategoryRow] = {}
        self.last_plan: list[PlanItem] = []
        self.nav_buttons = {}
        self.ignore_patterns: list[str] = list(DEFAULT_IGNORES)

        # Interactive file list state
        self.file_rows: list = []          # list of FileRow widgets
        self.search_var = ctk.StringVar(value="")
        self.active_filter: Optional[str] = None   # None or category name

        # Watchdog
        self._observer: Optional["Observer"] = None
        self._watched_path: Optional[Path] = None

        # Icons cache
        self._icon_cache: dict[str, ImageTk.PhotoImage] = {}

        # Find & Delete (whole-PC search) state
        self.finder_safe_mode = ctk.BooleanVar(value=True)
        self.finder_search_content = ctk.BooleanVar(value=False)
        self.finder_rows: list[dict] = []
        self._finder_thread = None
        self._finder_stop = threading.Event()
        self._finder_buffer: list = []
        self._finder_match_count = 0
        self._finder_checked = 0

        # Duplicates
        self.use_perceptual_duplicates = ctk.BooleanVar(value=True)

        # Tray / Background
        self.minimize_to_tray = ctk.BooleanVar(value=True)
        self.start_minimized = ctk.BooleanVar(value=False)
        self._tray_icon = None
        self._tray_thread: Optional[threading.Thread] = None

        # Load config
        self._load_persisted_config()

        # Built-in magic profiles for the best experience ever
        if len(self.profiles) <= 1:
            self.profiles.update({
                "Downloads Pro": {
                    "rules": [
                        {"condition_type": "filename_contains", "condition_value": "screenshot", "target_category": "Images", "priority": 1},
                        {"condition_type": "filename_contains", "condition_value": "invoice", "target_category": "Documents", "priority": 1},
                    ],
                    "use_date_folders": True,
                },
                "Photo Archive": {
                    "rules": [{"condition_type": "ext", "condition_value": ".jpg", "target_category": "Images", "priority": 1}],
                    "use_date_folders": True,
                },
                "Strict Clean": {
                    "ignore_patterns": list(DEFAULT_IGNORES) + ["*.log", "*.bak"],
                },
            })

        # Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()
        self._show_view("organize")
        self.after(180, self._preview)

        # Keyboard + command palette
        self.bind("<Control-k>", lambda e: self._show_command_palette())
        self.bind("<Control-K>", lambda e: self._show_command_palette())
        self.bind("<Control-p>", lambda e: self._preview())
        self.bind("<Control-o>", lambda e: self._organize())
        self.bind("<Escape>", lambda e: self._clear_filter())
        self.bind("<F5>", lambda e: self._preview())
        self.bind("<Control-f>", lambda e: self._show_view("finder"))
        self.bind("<Control-F>", lambda e: self._show_view("finder"))

        # Drag & drop (if available)
        if HAS_DND:
            try:
                self.TkdndVersion = dnd.TkinterDnD._require(self)  # type: ignore
            except Exception:
                pass

        # Window close → tray instead of quit (when enabled)
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Start minimized to tray if configured
        if HAS_TRAY and self.start_minimized.get():
            self.after(350, self._hide_to_tray)
            # If Live Auto was persisted ON, start watching even in background
            if self.live_mode.get():
                self.after(800, self._start_watching)

    # ---- setup helpers ----

    @staticmethod
    def _default_folder() -> Path:
        d = Path.home() / "Downloads"
        return d if d.exists() else Path.home()

    def _load_persisted_config(self):
        cfg = load_config()
        if not cfg:
            return
        try:
            if "last_folder" in cfg:
                p = cfg["last_folder"]
                if p and Path(p).exists():
                    self.folder.set(p)
            if "confirm_before" in cfg:
                self.confirm_before.set(bool(cfg["confirm_before"]))
            if "open_after" in cfg:
                self.open_after.set(bool(cfg["open_after"]))
            if "recursive" in cfg:
                self.recursive.set(bool(cfg["recursive"]))
            if "live_mode" in cfg:
                self.live_mode.set(bool(cfg["live_mode"]))
            if "delete_empty_after" in cfg:
                self.delete_empty_after.set(bool(cfg["delete_empty_after"]))
            if "theme" in cfg and cfg["theme"] in ("Dark", "Light"):
                ctk.set_appearance_mode(cfg["theme"])
            if isinstance(cfg.get("ignore_patterns"), list) and cfg["ignore_patterns"]:
                self.ignore_patterns = list(cfg["ignore_patterns"])
            if cfg.get("accent"):
                set_accent(cfg["accent"])
            if isinstance(cfg.get("rules"), list):
                self.rules = [Rule(**r) for r in cfg["rules"] if isinstance(r, dict)]
            if cfg.get("current_profile"):
                self.current_profile = cfg["current_profile"]
            if "minimize_to_tray" in cfg:
                self.minimize_to_tray.set(bool(cfg["minimize_to_tray"]))
            if "start_minimized" in cfg:
                self.start_minimized.set(bool(cfg["start_minimized"]))
            if "use_perceptual_duplicates" in cfg:
                self.use_perceptual_duplicates.set(bool(cfg["use_perceptual_duplicates"]))
        except Exception:
            pass

    def _save_config(self):
        data = {
            "last_folder": self.folder.get(),
            "confirm_before": self.confirm_before.get(),
            "open_after": self.open_after.get(),
            "recursive": self.recursive.get(),
            "live_mode": self.live_mode.get(),
            "delete_empty_after": self.delete_empty_after.get(),
            "theme": ctk.get_appearance_mode(),
            "ignore_patterns": self.ignore_patterns,
            "accent": get_accent(),
            "rules": [r.__dict__ for r in self.rules],
            "current_profile": self.current_profile,
            "minimize_to_tray": self.minimize_to_tray.get(),
            "start_minimized": self.start_minimized.get(),
            "use_perceptual_duplicates": self.use_perceptual_duplicates.get(),
        }
        save_config(data)

    def _save_profile(self, name: str):
        """Save current state as a profile."""
        self.profiles[name] = {
            "rules": [r.__dict__ for r in self.rules],
            "ignore_patterns": list(self.ignore_patterns),
            "use_date_folders": self.use_date_folders.get(),
            "recursive": self.recursive.get(),
        }
        self.current_profile = name
        self._save_config()
        self._toast(f"Profile '{name}' saved", SUCCESS)

    def _load_profile(self, name: str):
        """Load a profile."""
        if name not in self.profiles:
            self._toast(f"Profile '{name}' not found", WARNING)
            return
        prof = self.profiles[name]
        if "rules" in prof:
            self.rules = [Rule(**r) for r in prof["rules"]]
        if "ignore_patterns" in prof:
            self.ignore_patterns = list(prof["ignore_patterns"])
        if "use_date_folders" in prof:
            self.use_date_folders.set(prof["use_date_folders"])
        if "recursive" in prof:
            self.recursive.set(prof["recursive"])
        self.current_profile = name
        self._save_config()
        self._preview()
        if hasattr(self, "_refresh_rules_list"):
            self._refresh_rules_list()
        self._toast(f"Switched to profile '{name}'", get_accent())

    def _refresh_rules_list(self):
        if not hasattr(self, "rules_list"):
            return
        for child in self.rules_list.winfo_children():
            child.destroy()
        for i, rule in enumerate(self.rules):
            row = ctk.CTkFrame(self.rules_list, fg_color=C["surface"])
            row.pack(fill="x", pady=2, padx=4)
            text = f"{rule.condition_type}={rule.condition_value} → {rule.target_category} (p{rule.priority})"
            ctk.CTkLabel(row, text=text, font=ctk.CTkFont(size=11)).pack(side="left", padx=8)
            ctk.CTkButton(row, text="✕", width=24, height=22, corner_radius=4,
                          fg_color=DANGER, hover_color="#C53030",
                          command=lambda r=rule: self._delete_rule(r)).pack(side="right", padx=4)

    def _add_rule_dialog(self):
        # Simple but powerful add rule
        dlg = ctk.CTkToplevel(self)
        dlg.title("Add Rule")
        dlg.geometry("420x280")
        dlg.transient(self)

        ctk.CTkLabel(dlg, text="Condition (simple & useful)", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(16,2))
        cond_type = ctk.CTkOptionMenu(dlg, values=["filename_contains", "ext"])
        cond_type.pack(fill="x", padx=20)

        ctk.CTkLabel(dlg, text="Value (e.g. 'screenshot' or '.pdf')", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(12,2))
        val_entry = ctk.CTkEntry(dlg)
        val_entry.pack(fill="x", padx=20)

        ctk.CTkLabel(dlg, text="Target Category", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(12,2))
        cat_menu = ctk.CTkOptionMenu(dlg, values=CATEGORY_ORDER)
        cat_menu.pack(fill="x", padx=20)

        def do_add():
            try:
                rule = Rule(
                    condition_type=cond_type.get(),
                    condition_value=val_entry.get(),
                    target_category=cat_menu.get(),
                    priority=5  # high priority for user rules
                )
                self.rules.append(rule)
                self._save_config()
                self._refresh_rules_list()
                self._preview()
                dlg.destroy()
            except Exception as e:
                self._toast(str(e), DANGER)
        ctk.CTkButton(dlg, text="Add Rule", fg_color=get_accent(), command=do_add).pack(pady=16)

    def _delete_rule(self, rule):
        if rule in self.rules:
            self.rules.remove(rule)
            self._save_config()
            self._refresh_rules_list()
            self._preview()

    def _clear_rules(self):
        self.rules = []
        self._save_config()
        self._refresh_rules_list()
        self._preview()
        self._toast("All user rules cleared", WARNING)

    def _refresh_duplicates(self):
        if not hasattr(self, "dup_list"):
            return
        for child in self.dup_list.winfo_children():
            child.destroy()

        base = self._valid_folder()
        if not base:
            self.dup_empty.grid()
            self.dup_list.grid_remove()
            return

        # Use current plan if available, else scan
        items = self.last_plan or [PlanItem(p, cat) for p, cat in scan_folder(base, self.recursive.get(), self.ignore_patterns)]
        use_p = getattr(self, "use_perceptual_duplicates", ctk.BooleanVar(value=True)).get()
        dups = self._find_duplicates(items, use_perceptual=use_p)

        if not dups:
            self.dup_empty.grid()
            self.dup_list.grid_remove()
            return

        self.dup_empty.grid_remove()
        self.dup_list.grid()

        for digest, group in dups.items():
            group.sort(key=lambda x: x.mtime, reverse=True)  # newest first
            frame = ctk.CTkFrame(self.dup_list, fg_color=C["surface2"], corner_radius=8)
            frame.pack(fill="x", pady=6, padx=4)

            ctk.CTkLabel(frame, text=f"{len(group)} copies  •  {group[0].path.name}", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(8, 2))

            for item in group:
                row = ctk.CTkFrame(frame, fg_color="transparent")
                row.pack(fill="x", padx=12)
                ctk.CTkLabel(row, text=f"  {item.path}  ({human_size(item.size)})", font=ctk.CTkFont(size=11)).pack(side="left")
                if item != group[0]:
                    ctk.CTkButton(row, text="Delete", width=70, height=22, corner_radius=5,
                                  fg_color=DANGER, hover_color="#C53030",
                                  command=lambda i=item: self._delete_dup_file(i, frame)).pack(side="right", padx=4)

    def _delete_dup_file(self, item, parent_frame):
        try:
            item.path.unlink()
            self._toast(f"Deleted {item.path.name}", SUCCESS)
            # Refresh the whole view
            self._refresh_duplicates()
            self._preview()
        except Exception as e:
            self._toast(f"Failed: {e}", DANGER)

    def _delete_all_duplicates_but_newest(self):
        base = self._valid_folder()
        if not base: return
        items = self.last_plan or []
        use_p = self.use_perceptual_duplicates.get()
        dups = self._find_duplicates(items, use_perceptual=use_p)
        deleted = 0
        for group in dups.values():
            group.sort(key=lambda x: x.mtime, reverse=True)
            for item in group[1:]:
                try:
                    item.path.unlink()
                    deleted += 1
                except: pass
        self._toast(f"Deleted {deleted} duplicate files", SUCCESS)
        self._refresh_duplicates()
        self._preview()

    def _on_perceptual_toggle(self):
        self._save_config()
        self._refresh_duplicates()

    # ---------------- Context Menu UI ----------------
    def _register_context_menu_ui(self):
        if not IS_WINDOWS:
            self._toast("Only on Windows", WARNING)
            return
        ok, msg = register_context_menu()
        if ok:
            self._toast(msg, SUCCESS)
        else:
            self._toast(msg, DANGER)

    def _unregister_context_menu_ui(self):
        if not IS_WINDOWS:
            self._toast("Only on Windows", WARNING)
            return
        ok, msg = unregister_context_menu()
        if ok:
            self._toast(msg, SUCCESS)
        else:
            self._toast(msg, DANGER)

    def _refresh_analytics(self):
        if not hasattr(self, "stats_labels"):
            return

        base = Path(self.folder.get())
        undo = base / UNDO_FILE
        total_files = 0
        total_size = 0
        cat_count = {}
        last = "—"

        if undo.exists():
            try:
                data = json.loads(undo.read_text(encoding="utf-8"))
                ops = data.get("operations", [])
                for op in ops:
                    total_files += op.get("count", 0)
                    last = op.get("when", last)
                    for src, dst in op.get("moves", []):
                        try:
                            cat = Path(dst).parent.name
                            cat_count[cat] = cat_count.get(cat, 0) + 1
                            total_size += Path(src).stat().st_size if Path(src).exists() else 0
                        except: pass
            except: pass

        self.stats_labels["Total files moved"].configure(text=str(total_files))
        self.stats_labels["Space organized"].configure(text=human_size(total_size))
        top_cat = max(cat_count, key=cat_count.get) if cat_count else "—"
        self.stats_labels["Top category"].configure(text=top_cat)
        self.stats_labels["Last organized"].configure(text=last)

    def _prompt_save_profile(self):
        # Simple dialog for new profile name
        dlg = ctk.CTkInputDialog(text="Enter profile name:", title="Save Profile")
        name = dlg.get_input()
        if name:
            self._save_profile(name.strip())

    def _build_sidebar(self):
        """Clean, modern, highly readable left navigation."""
        bar = ctk.CTkFrame(self, width=210, corner_radius=0, fg_color=C["sidebar"])
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)

        # Brand - prominent and clean
        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(18, 14))
        try:
            logo_img = ctk.CTkImage(Image.open(resource_path("assets/logo.png")), size=(26, 26))
            ctk.CTkLabel(brand, image=logo_img, text="").pack(side="left")
        except Exception:
            pass
        t = ctk.CTkFrame(brand, fg_color="transparent")
        t.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(t, text="FileFlow", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=C["textHi"]).pack(anchor="w")
        ctk.CTkLabel(t, text=f"v{VERSION}", font=ctk.CTkFont(size=9),
                     text_color=C["textMuted"]).pack(anchor="w")

        # Navigation - readable, spacious, with icons
        nav = ctk.CTkFrame(bar, fg_color="transparent")
        nav.pack(fill="x", padx=10, pady=(4, 0))

        icons = {
            "organize": "📁",
            "finder": "🔍",
            "duplicates": "🔄",
            "analytics": "📊",
            "history": "🕒",
            "settings": "⚙",
            "about": "ℹ"
        }

        for key, label in (("organize", "Organize"), ("finder", "Find & Delete"),
                           ("duplicates", "Duplicates"), ("analytics", "Insights"),
                           ("history", "History"), ("settings", "Settings"),
                           ("about", "About")):
            icon = icons.get(key, "•")
            b = ctk.CTkButton(nav, text=f"  {icon}   {label}", anchor="w", height=44, corner_radius=8,
                              fg_color="transparent", text_color=C["textHi"],
                              hover_color=C["surface2"],
                              font=ctk.CTkFont(size=15),
                              command=lambda k=key: self._show_view(k))
            b.pack(fill="x", pady=2)
            self.nav_buttons[key] = b

        # Appearance / Theme at bottom - clear
        bottom = ctk.CTkFrame(bar, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=14, pady=14)
        ctk.CTkLabel(bottom, text="THEME", font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=C["textMuted"]).pack(anchor="w", pady=(0, 4))
        seg = ctk.CTkSegmentedButton(bottom, values=["Dark", "Light"],
                                     fg_color=C["surface2"], unselected_color=C["surface2"],
                                     selected_color=get_accent(),
                                     selected_hover_color=get_accent_hover(),
                                     command=self._set_theme)
        seg.set("Dark")
        seg.pack(fill="x")

    def _build_main(self):
        self.content = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.views = {
            "organize": self._make_organize_view(),
            "finder": self._make_finder_view(),
            "duplicates": self._make_duplicates_view(),
            "analytics": self._make_analytics_view(),
            "history": self._make_history_view(),
            "settings": self._make_settings_view(),
            "about": self._make_about_view(),
        }

    # ---- views ----

    def _header(self, parent, title, subtitle):
        head = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(head, text=title, anchor="w",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["textHi"]).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(head, text=subtitle, anchor="w",
                         font=ctk.CTkFont(size=11), text_color=C["textMuted"]
                         ).pack(anchor="w", pady=(2, 0))
        return head

    def _make_organize_view(self):
        view = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        view.grid(row=0, column=0, sticky="nsew")
        view.grid_columnconfigure(0, weight=1)

        # Main header
        head = self._header(view, "Organize", "Select folder • review files • organize")
        head.grid(row=0, column=0, sticky="ew", padx=24, pady=(12, 4))

        # Folder picker card
        pick = ctk.CTkFrame(view, fg_color=C["surface"], corner_radius=14,
                            border_width=1, border_color=C["border"])
        pick.grid(row=1, column=0, sticky="ew", padx=24)
        pick.grid_columnconfigure(0, weight=1)

        pinner = ctk.CTkFrame(pick, fg_color="transparent")
        pinner.grid(row=0, column=0, sticky="ew", padx=16, pady=14)
        pinner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(pinner, text="FOLDER", font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=C["textMuted"]).grid(row=0, column=0, sticky="w")

        self.path_entry = ctk.CTkEntry(pinner, textvariable=self.folder, height=42,
                                       corner_radius=10, fg_color=C["surface2"],
                                       border_color=C["border"], font=ctk.CTkFont(size=14))
        self.path_entry.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        browse_btn = ctk.CTkButton(pinner, text="Browse", width=100, height=42, corner_radius=10,
                                   fg_color=C["surface2"], hover_color=C["border"],
                                   text_color=C["textHi"], command=self._browse)
        browse_btn.grid(row=1, column=1, padx=(10, 0))

        # Drag & drop hint
        if HAS_DND:
            dnd_label = ctk.CTkLabel(pinner, text="or drop folder here",
                                     font=ctk.CTkFont(size=11), text_color=get_accent())
            dnd_label.grid(row=2, column=0, columnspan=2, pady=(6, 0))
            # Attach dnd when the entry is ready
            self.after(200, lambda: self._attach_dnd(pick))

        # Quick folders
        quick = ctk.CTkFrame(pinner, fg_color="transparent")
        quick.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ctk.CTkLabel(quick, text="Quick", font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=C["textMuted"]).pack(side="left", padx=(0, 6))
        for label, p in [("Downloads", Path.home() / "Downloads"),
                         ("Desktop", Path.home() / "Desktop"),
                         ("Documents", Path.home() / "Documents")]:
            ctk.CTkButton(quick, text=label, height=26, corner_radius=999,
                          fg_color=C["surface2"], hover_color=get_accent(),
                          text_color=C["textHi"], font=ctk.CTkFont(size=10),
                          command=lambda pp=p: self._switch_preset(pp)).pack(side="left", padx=(0, 4))

        # Action bar
        actions = ctk.CTkFrame(view, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=24, pady=(12, 6))

        self.preview_btn = ctk.CTkButton(actions, text="Preview", width=130, height=42,
                                         corner_radius=10, fg_color=C["surface"],
                                         hover_color=C["border"], text_color=C["textHi"],
                                         border_width=1, border_color=C["border"],
                                         font=ctk.CTkFont(size=13, weight="bold"),
                                         command=self._preview)
        self.preview_btn.pack(side="left")

        ctk.CTkButton(actions, text="Simulate", width=100, height=42,
                      corner_radius=10, fg_color=C["surface"],
                      hover_color=C["border"], text_color=C["textHi"],
                      border_width=1, border_color=C["border"],
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._simulate_changes).pack(side="left", padx=6)

        self.organize_btn = ctk.CTkButton(actions, text="Organize selected", width=190, height=42,
                                          corner_radius=10, fg_color=get_accent(),
                                          hover_color=get_accent_hover(),
                                          font=ctk.CTkFont(size=13, weight="bold"),
                                          command=self._organize)
        self.organize_btn.pack(side="left", padx=8)

        self.progress = ctk.CTkProgressBar(actions, height=8, corner_radius=10,
                                           progress_color=get_accent(), fg_color=C["surface2"])
        self.progress.set(0)

        # Options + search bar
        topbar = ctk.CTkFrame(view, fg_color="transparent")
        topbar.grid(row=3, column=0, sticky="ew", padx=32, pady=(4, 8))
        topbar.grid_columnconfigure(1, weight=1)

        opts = ctk.CTkFrame(topbar, fg_color="transparent")
        opts.grid(row=0, column=0, sticky="w")

        self.recursive_cb = ctk.CTkCheckBox(opts, text="Include subfolders",
                                            variable=self.recursive, text_color=C["textHi"],
                                            border_color=C["border"], checkmark_color=get_accent(),
                                            command=lambda: (self._save_config(), self._preview()))
        self.recursive_cb.pack(side="left", padx=(0, 16))

        ctk.CTkCheckBox(opts, text="Use date subfolders (e.g. 2026-06)", variable=self.use_date_folders,
                        text_color=C["textHi"], border_color=C["border"],
                        checkmark_color=get_accent()).pack(side="left")

        ctk.CTkCheckBox(opts, text="Confirm before move", variable=self.confirm_before,
                        text_color=C["textHi"], border_color=C["border"],
                        checkmark_color=get_accent()).pack(side="left")

        # Search
        self.search_var.trace_add("write", lambda *a: self._filter_file_list())
        search_frame = ctk.CTkFrame(topbar, fg_color=C["surface2"], corner_radius=10)
        search_frame.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(search_frame, text="⌘", font=ctk.CTkFont(size=13),
                     text_color=C["textMuted"]).pack(side="left", padx=(10, 4))
        self.search_entry = ctk.CTkEntry(search_frame, textvariable=self.search_var,
                                         placeholder_text="Search files...", width=240,
                                         height=34, corner_radius=9,
                                         fg_color=C["surface"], border_width=0)
        self.search_entry.pack(side="left", padx=(0, 6), pady=3)

        # Stats row
        stats = ctk.CTkFrame(view, fg_color="transparent")
        stats.grid(row=4, column=0, sticky="ew", padx=24)
        for i in range(3):
            stats.grid_columnconfigure(i, weight=1)
        self.stat_files = StatCard(stats, "Files", "0")
        self.stat_cats = StatCard(stats, "Categories", "0")
        self.stat_size = StatCard(stats, "Size", "0 B")
        for i, card in enumerate((self.stat_files, self.stat_cats, self.stat_size)):
            card.grid(row=0, column=i, sticky="ew", padx=4)

        # === MAIN CONTENT ===
        main_area = ctk.CTkFrame(view, fg_color="transparent")
        main_area.grid(row=5, column=0, sticky="nsew", padx=24, pady=(8, 4))
        main_area.grid_columnconfigure(0, weight=0)
        main_area.grid_columnconfigure(1, weight=1)
        main_area.grid_rowconfigure(0, weight=1)

        # Left: Donut card
        left = ctk.CTkFrame(main_area, fg_color=C["card"], corner_radius=14,
                            border_width=1, border_color=C["border"])
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))

        ctk.CTkLabel(left, text="BREAKDOWN", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["textMuted"]).pack(anchor="w", padx=16, pady=(12, 2))
        self.donut = DonutChart(left, size=210, on_segment_click=self._filter_by_category)
        self.donut.pack(padx=16, pady=(2, 12))

        # Compact category legend
        legend = ctk.CTkFrame(left, fg_color="transparent")
        legend.pack(fill="x", padx=14, pady=(0, 14))
        self.cards = {}
        for name in CATEGORY_ORDER:
            row = CategoryRow(legend, name)
            row.pack(fill="x", pady=3)
            self.cards[name] = row

        # Right: Interactive file list
        right = ctk.CTkFrame(main_area, fg_color=C["surface"], corner_radius=18,
                             border_width=1, border_color=C["border"])
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        fl_head = ctk.CTkFrame(right, fg_color="transparent")
        fl_head.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))

        ctk.CTkLabel(fl_head, text="FILES", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["textMuted"]).pack(side="left")

        # File list controls — bigger
        fl_ctrl = ctk.CTkFrame(fl_head, fg_color="transparent")
        fl_ctrl.pack(side="right")
        ctk.CTkButton(fl_ctrl, text="All", width=64, height=24, corner_radius=6,
                      fg_color=C["surface2"], hover_color=C["border"],
                      font=ctk.CTkFont(size=10, weight="bold"),
                      command=lambda: self._select_all_files(True)).pack(side="left", padx=2)
        ctk.CTkButton(fl_ctrl, text="None", width=56, height=24, corner_radius=6,
                      fg_color=C["surface2"], hover_color=C["border"],
                      font=ctk.CTkFont(size=10, weight="bold"),
                      command=lambda: self._select_all_files(False)).pack(side="left", padx=2)
        ctk.CTkButton(fl_ctrl, text="Clear", width=64, height=24, corner_radius=6,
                      fg_color=C["surface2"], hover_color=C["border"],
                      font=ctk.CTkFont(size=10, weight="bold"),
                      command=self._clear_filter).pack(side="left", padx=2)

        # File list
        self.file_list_frame = ctk.CTkScrollableFrame(right, fg_color="transparent",
                                                      scrollbar_button_color=C["border"])
        self.file_list_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        # Status
        self.status = ctk.CTkLabel(view, text="Ready",
                                   anchor="w", font=ctk.CTkFont(size=9), text_color=C["textMuted"])
        self.status.grid(row=6, column=0, sticky="ew", padx=20, pady=(2, 8))

        # Nice empty state hint (visible until preview populates)
        self.after(900, lambda: self._maybe_show_initial_hint())

        # Store reference for updates
        self._file_list_container = self.file_list_frame
        return view

    def _make_history_view(self):
        view = ctk.CTkFrame(self.content, fg_color="transparent")
        view.grid_columnconfigure(0, weight=1)
        self._header(view, "History", "Undo previous organizes. Newest first.").grid(row=0, column=0, sticky="ew", padx=24,
                                     pady=(16, 8))
        card = ctk.CTkFrame(view, fg_color=C["surface"], corner_radius=16,
                            border_width=1, border_color=C["border"])
        card.grid(row=1, column=0, sticky="nsew", padx=30)
        card.grid_rowconfigure(0, weight=1)

        # Scrollable list container
        self.history_list = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self.history_list.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        # Fallback label if empty
        self.history_empty = ctk.CTkLabel(
            card, text="No history yet for this folder.\nOrganize some files first.",
            font=ctk.CTkFont(size=13), text_color=C["textLo"])
        self.history_empty.grid(row=0, column=0, sticky="nsew", padx=22, pady=22)

        return view

    def _make_settings_view(self):
        """Modern settings UI."""
        view = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        view.grid_columnconfigure(0, weight=1)
        self._header(view, "Settings", "Appearance • Behavior • Rules"
                     ).grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 8))

        # Helper to create a section card
        def section_card(title, subtitle=None):
            card = ctk.CTkFrame(view, fg_color=C["surface"], corner_radius=10,
                                border_width=1, border_color=C["border"])
            card.grid(row=len(view.winfo_children()) or 1, column=0, sticky="ew", padx=28, pady=(0, 14))
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=20, pady=(16, 8))
            ctk.CTkLabel(inner, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=C["textHi"]).pack(anchor="w")
            if subtitle:
                ctk.CTkLabel(inner, text=subtitle, font=ctk.CTkFont(size=11),
                             text_color=C["textLo"]).pack(anchor="w", pady=(1, 0))
            return card

        def add_switch_row(parent, text, desc, var, pady=10):
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", padx=20, pady=pady)
            left = ctk.CTkFrame(r, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(left, text=text, font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=C["textHi"]).pack(anchor="w")
            if desc:
                ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(size=11), text_color=C["textLo"]).pack(anchor="w")
            sw = ctk.CTkSwitch(r, text="", variable=var, progress_color=get_accent(), width=46)
            sw.pack(side="right")
            return sw

        # === APPEARANCE ===
        app_card = section_card("Appearance", "Theme and accent color")
        theme_row = ctk.CTkFrame(app_card, fg_color="transparent")
        theme_row.pack(fill="x", padx=20, pady=(8, 4))
        ctk.CTkLabel(theme_row, text="Theme", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["textHi"]).pack(side="left")
        seg = ctk.CTkSegmentedButton(theme_row, values=["Dark", "Light"],
                                     fg_color=C["surface2"], unselected_color=C["surface2"],
                                     selected_color=get_accent(),
                                     selected_hover_color=get_accent_hover(),
                                     command=self._set_theme)
        seg.pack(side="right")
        seg.set(ctk.get_appearance_mode())

        # Nice accent swatches
        acc_label = ctk.CTkLabel(app_card, text="Accent color", font=ctk.CTkFont(size=12, weight="bold"),
                                  text_color=C["textLo"])
        acc_label.pack(anchor="w", padx=20, pady=(12, 4))
        swatch_row = ctk.CTkFrame(app_card, fg_color="transparent")
        swatch_row.pack(fill="x", padx=20, pady=(0, 14))
        accent_colors = ["#0078D4", "#10893E", "#C42B1C", "#9D5D00", "#5C2D91", "#0078D4", "#00B294", "#E81123"]
        for col in accent_colors:
            def make_set(c=col):
                def _set():
                    set_accent(c)
                    self._save_config()
                    self._toast("Accent changed", get_accent())
                    self.after(40, lambda: (self._preview() if hasattr(self, "_preview") else None))
                return _set
            sw = ctk.CTkButton(swatch_row, text="", width=26, height=26, corner_radius=13,
                               fg_color=col, hover_color=col, border_width=2,
                               border_color=C["border"], command=make_set())
            sw.pack(side="left", padx=4)

        # === BEHAVIOR ===
        beh_card = section_card("Behavior")
        add_switch_row(beh_card, "Ask for confirmation", "Show a confirmation dialog before organizing", self.confirm_before)
        add_switch_row(beh_card, "Open folder after organizing", "Automatically open the target folder when done", self.open_after)
        add_switch_row(beh_card, "Scan subfolders (recursive)", "Include files inside subdirectories", self.recursive)

        # === AUTOMATION ===
        auto_card = section_card("Automation", "Live watching and organization rules")
        self.live_switch = add_switch_row(auto_card, "Live Auto", "Automatically organize new files as they arrive", self.live_mode, pady=8)
        # reconnect command
        self.live_switch.configure(command=self._toggle_live)

        add_switch_row(auto_card, "Use date folders (YYYY-MM)", "Organize files into dated subfolders inside categories", self.use_date_folders)
        add_switch_row(auto_card, "Dry run mode", "Simulate everything without moving files", self.dry_run)
        add_switch_row(auto_card, "Clean empty category folders", "Remove empty folders created by the organizer", self.delete_empty_after)

        # === TRAY & BACKGROUND ===
        tray_card = section_card("Tray & Background")
        add_switch_row(tray_card, "Minimize to tray on close", "Keep running in the background when you close the window", self.minimize_to_tray)
        add_switch_row(tray_card, "Start minimized to tray", "Launch straight into the system tray (excellent with Live Auto)", self.start_minimized)

        # === WINDOWS INTEGRATION ===
        if IS_WINDOWS:
            win_card = section_card("Windows Integration", "Right-click folders in Explorer")
            win_inner = ctk.CTkFrame(win_card, fg_color="transparent")
            win_inner.pack(fill="x", padx=20, pady=(6, 14))
            ctk.CTkButton(win_inner, text="Register 'Organize with FileFlow' context menu",
                          fg_color=get_accent(), hover_color=get_accent_hover(),
                          height=34, corner_radius=8,
                          command=self._register_context_menu_ui).pack(fill="x", pady=3)
            ctk.CTkButton(win_inner, text="Unregister context menu",
                          fg_color=C["surface2"], hover_color=C["border"],
                          height=32, corner_radius=8,
                          command=self._unregister_context_menu_ui).pack(fill="x", pady=3)
            ctk.CTkLabel(win_inner, text="Tip: Restart Explorer or log out for changes to appear.",
                         font=ctk.CTkFont(size=10), text_color=C["textMuted"]).pack(anchor="w", pady=(4, 0))

        # === IGNORE PATTERNS ===
        ign_card = section_card("Ignore Patterns", "Files matching these patterns are skipped")
        self.ignore_text = ctk.CTkTextbox(ign_card, height=72, corner_radius=10,
                                          fg_color=C["surface2"], border_color=C["border"],
                                          font=ctk.CTkFont(size=12))
        self.ignore_text.pack(fill="x", padx=20, pady=(4, 8))
        self._refresh_ignore_text()

        ib = ctk.CTkFrame(ign_card, fg_color="transparent")
        ib.pack(fill="x", padx=20, pady=(0, 14))
        ctk.CTkButton(ib, text="Save ignores", height=30, corner_radius=8,
                      fg_color=get_accent(), hover_color=get_accent_hover(),
                      command=self._save_ignores).pack(side="left")
        ctk.CTkButton(ib, text="Reset to defaults", height=30, corner_radius=8,
                      fg_color=C["surface2"], hover_color=C["border"],
                      command=self._reset_ignores).pack(side="left", padx=8)

        # === RULES ===
        rule_card = section_card("User Rules", "High-priority custom categorization rules (saved per profile)")
        self.rules_list = ctk.CTkScrollableFrame(rule_card, height=100, fg_color=C["surface2"], corner_radius=10)
        self.rules_list.pack(fill="x", padx=20, pady=4)
        self._refresh_rules_list()

        rb = ctk.CTkFrame(rule_card, fg_color="transparent")
        rb.pack(fill="x", padx=20, pady=(4, 12))
        ctk.CTkButton(rb, text="+ Add rule", height=28, corner_radius=7,
                      fg_color=get_accent(), hover_color=get_accent_hover(),
                      command=self._add_rule_dialog).pack(side="left")
        ctk.CTkButton(rb, text="Clear all rules", height=28, corner_radius=7,
                      fg_color=C["surface2"], hover_color=C["border"],
                      command=self._clear_rules).pack(side="left", padx=8)

        # === PROFILES + RESET ===
        prof_card = section_card("Profiles")
        pr = ctk.CTkFrame(prof_card, fg_color="transparent")
        pr.pack(fill="x", padx=20, pady=8)
        self.profile_var = ctk.StringVar(value=self.current_profile)
        ctk.CTkOptionMenu(pr, values=list(self.profiles.keys()), variable=self.profile_var,
                          command=self._load_profile, width=170,
                          fg_color=C["surface2"], button_color=C["border"]).pack(side="left")
        ctk.CTkButton(pr, text="Save current as new profile", height=30, corner_radius=8,
                      fg_color=C["surface2"], hover_color=C["border"],
                      command=self._prompt_save_profile).pack(side="left", padx=8)

        # Global reset
        reset_row = ctk.CTkFrame(view, fg_color="transparent")
        reset_row.grid(row=999, column=0, sticky="ew", padx=28, pady=(4, 22))
        ctk.CTkButton(reset_row, text="Reset all settings to defaults",
                      fg_color=C["surface2"], hover_color=C["border"], height=32,
                      command=self._reset_all_settings).pack(side="left")

        return view

    def _make_duplicates_view(self):
        view = ctk.CTkFrame(self.content, fg_color="transparent")
        view.grid_columnconfigure(0, weight=1)
        self._header(view, "Duplicates", "Exact + visually similar images (perceptual hash).").grid(row=0, column=0, sticky="ew", padx=32, pady=(24, 12))

        card = ctk.CTkFrame(view, fg_color=C["surface"], corner_radius=12, border_width=1, border_color=C["border"])
        card.grid(row=1, column=0, sticky="nsew", padx=32)
        card.grid_rowconfigure(0, weight=1)

        self.dup_list = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self.dup_list.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        self.dup_empty = ctk.CTkLabel(card, text="No duplicates found.\nRun Preview in Organize tab first to scan.", font=ctk.CTkFont(size=13), text_color=C["textLo"])
        self.dup_empty.grid(row=0, column=0, sticky="nsew", padx=22, pady=22)

        # Perceptual toggle
        perc_row = ctk.CTkFrame(view, fg_color="transparent")
        perc_row.grid(row=2, column=0, padx=32, pady=(0, 4), sticky="w")
        ctk.CTkCheckBox(perc_row, text="Include visually similar images (perceptual hash)",
                        variable=self.use_perceptual_duplicates,
                        command=self._on_perceptual_toggle,
                        text_color=C["textHi"]).pack(side="left")

        btn_row = ctk.CTkFrame(view, fg_color="transparent")
        btn_row.grid(row=3, column=0, padx=32, pady=12)
        ctk.CTkButton(btn_row, text="Refresh from current folder", command=self._refresh_duplicates).pack(side="left")
        ctk.CTkButton(btn_row, text="Delete all but the newest in each group", fg_color=DANGER, hover_color="#C53030",
                      command=self._delete_all_duplicates_but_newest).pack(side="left", padx=8)

        return view

    def _make_analytics_view(self):
        view = ctk.CTkFrame(self.content, fg_color="transparent")
        view.grid_columnconfigure(0, weight=1)
        self._header(view, "Insights", "Real numbers from your history.").grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 8))

        card = ctk.CTkFrame(view, fg_color=C["surface"], corner_radius=12, border_width=1, border_color=C["border"])
        card.grid(row=1, column=0, sticky="ew", padx=32)

        self.stats_labels = {}
        for label in ["Total files moved", "Space organized", "Top category", "Last organized"]:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=26, pady=14)
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=13), text_color=C["textLo"]).pack(side="left")
            lbl = ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=15, weight="bold"), text_color=C["textHi"])
            lbl.pack(side="right")
            self.stats_labels[label] = lbl

        tip = ctk.CTkLabel(view, text="Stats come from the history file in the target folder.", font=ctk.CTkFont(size=11), text_color=C["textMuted"])
        tip.grid(row=2, column=0, padx=32, pady=10)

        return view

    def _make_about_view(self):
        view = ctk.CTkFrame(self.content, fg_color="transparent")
        view.grid_columnconfigure(0, weight=1)
        self._header(view, "About", "").grid(row=0, column=0, sticky="ew",
                                              padx=24, pady=(16, 8))
        card = ctk.CTkFrame(view, fg_color=C["surface"], corner_radius=12,
                            border_width=1, border_color=C["border"])
        card.grid(row=1, column=0, sticky="ew", padx=24)
        ctk.CTkLabel(
            card, justify="left", anchor="w", text_color=C["textLo"],
            font=ctk.CTkFont(size=12),
            text=(f"{APP_NAME}  v{VERSION}\n\n"
                  "A local file organizer for Windows.\n"
                  "Preview, organize, live auto, tray, search & clean.\n\n"
                  "Made to keep your files tidy.")
            ).pack(anchor="w", padx=18, pady=(16, 6))

        ctk.CTkButton(
            card,
            text="GitHub",
            height=34,
            corner_radius=8,
            fg_color=get_accent(),
            hover_color=get_accent_hover(),
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: webbrowser.open(GITHUB_URL)
        ).pack(anchor="w", padx=18, pady=(2, 16))

        return view

    # ==================== HELPERS ====================

    def _attach_dnd(self, target_widget):
        if not HAS_DND:
            return
        try:
            target_widget.drop_target_register(dnd.DND_FILES)
            target_widget.dnd_bind('<<Drop>>', self._on_drop)
        except Exception:
            pass

    def _on_drop(self, event):
        try:
            raw = event.data
            # Windows paths come quoted
            paths = [p.strip('{}" ') for p in raw.split() if p.strip()]
            if paths:
                folder = paths[0]
                if os.path.isdir(folder):
                    self.folder.set(folder)
                    self._save_config()
                    self.after(80, self._preview)
        except Exception:
            pass

    def _switch_preset(self, path: Path):
        if path.exists() and path.is_dir():
            self.folder.set(str(path))
            self._save_config()
            self._preview()
            self._toast(f"Switched to {path.name}", get_accent())

    def _filter_file_list(self):
        if not hasattr(self, 'file_rows') or not self.file_rows:
            return
        q = self.search_var.get().lower().strip()
        for row in self.file_rows:
            name = row.item.path.name.lower()
            cat = row.item.effective_category.lower()
            match = (not q) or (q in name) or (q in cat)
            if match:
                row.pack(fill="x", pady=3, padx=6)
            else:
                row.pack_forget()

    def _filter_by_category(self, category: str):
        if self.active_filter == category:
            self._clear_filter()
        else:
            self.active_filter = category
            self._refresh_file_list_display()
            self._toast(f"Filtering: {category}", get_accent())

    def _clear_filter(self):
        self.active_filter = None
        self.search_var.set("")
        self._refresh_file_list_display()

    def _refresh_file_list_display(self):
        if not hasattr(self, "file_rows"):
            return
        q = self.search_var.get().lower().strip()
        for row in self.file_rows:
            show = True
            if self.active_filter and row.item.effective_category != self.active_filter:
                show = False
            if show and q:
                name = row.item.path.name.lower()
                if q not in name and q not in row.item.effective_category.lower():
                    show = False
            if show:
                row.pack(fill="x", pady=3, padx=6)
            else:
                row.pack_forget()

    def _select_all_files(self, state: bool):
        for row in getattr(self, "file_rows", []):
            row.item.selected = state
            row.var.set(state)
        self._update_stats_from_plan()

    def _rebuild_file_list(self, items: list[PlanItem]):
        """Rebuild clean file list (no artificial 400 limit, better for large folders)"""
        if not hasattr(self, "_file_list_container"):
            return
        for child in self._file_list_container.winfo_children():
            child.destroy()
        self.file_rows = []
        self.thumbnail_cache = {}

        # Process all but display with good performance (no hard cap)
        for item in items:
            if self.active_filter and item.effective_category != self.active_filter:
                continue
            row = FileRow(self._file_list_container, item,
                          on_change=self._update_stats_from_plan,
                          on_toggle_cat=self._update_stats_from_plan,
                          thumbnail_cache=self.thumbnail_cache)
            row.pack(fill="x", pady=4, padx=8)
            self.file_rows.append(row)

        self._update_stats_from_plan()

    def _update_stats_from_plan(self):
        if not self.last_plan:
            return
        selected = [p for p in self.last_plan if p.selected]
        counts = {}
        total_size = 0
        for p in selected:
            cat = p.effective_category
            counts[cat] = counts.get(cat, 0) + 1
            total_size += p.size

        total = len(selected)
        for name, card in self.cards.items():
            card.update_count(counts.get(name, 0), total)

        self.donut.draw(counts, highlight=self.active_filter)
        self.stat_files.set_value(str(total))
        self.stat_cats.set_value(str(sum(1 for v in counts.values() if v)))
        self.stat_size.set_value(human_size(total_size))

        selected_count = len([p for p in self.last_plan if p.selected])
        self._toast(f"{selected_count} file(s) selected to organize", get_accent())

    def _export_report(self):
        if not self.last_plan:
            self._toast("Nothing to export yet. Preview first.", WARNING)
            return
        selected = [p for p in self.last_plan if p.selected]
        if not selected:
            self._toast("No files selected.", WARNING)
            return

        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        base = Path(self.folder.get())
        report_path = base / f"organize_report_{ts}.html"

        by_cat = {}
        total_size = 0
        for item in selected:
            cat = item.effective_category
            by_cat.setdefault(cat, []).append(item)
            total_size += item.size

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Organize Report {ts}</title>
<style>
body {{ font-family: system-ui, sans-serif; background:#0B0D13; color:#F1F3F9; padding:40px; }}
h1 {{ color:#5B7CFA; }} .cat {{ margin-top:30px; border-left:4px solid #5B7CFA; padding-left:12px; }}
.file {{ padding:4px 0; font-family:monospace; }} .stats {{ background:#1C222D; padding:16px; border-radius:8px; }}
</style></head><body>
<h1>FileFlow Report</h1>
<div class="stats">
<b>Folder:</b> {base}<br>
<b>Date:</b> {ts}<br>
<b>Files:</b> {len(selected)} &nbsp; <b>Size:</b> {human_size(total_size)}
</div>"""

        for cat, items in sorted(by_cat.items()):
            html += f'<div class="cat"><h2>{cat} ({len(items)})</h2>'
            for it in items:
                html += f'<div class="file">{it.path.name} — {human_size(it.size)}</div>'
            html += '</div>'

        html += "</body></html>"

        try:
            report_path.write_text(html, encoding="utf-8")
            self._toast(f"HTML report saved", SUCCESS)
            os.startfile(str(report_path))
        except Exception as e:
            self._toast(f"Export failed: {e}", DANGER)

    def _maybe_show_initial_hint(self):
        if not self.last_plan and hasattr(self, "status"):
            self._toast("Drop a folder or click Preview to begin the magic.")

    def _apply_smart_rules(self, items: list[PlanItem]):
        """Built-in smart rules (easy to extend)."""
        for item in items:
            name = item.path.name.lower()
            # Screenshot / screen recordings → Images
            if "screenshot" in name or "snímka" in name or "screen" in name:
                item.custom_category = "Images"
            # Invoices / faktúry / receipts
            elif any(k in name for k in ["invoice", "faktur", "receipt", "uctenka", "objednavka"]):
                item.custom_category = "Documents"
            # Code projects or zips containing source
            elif name.endswith(".zip") and any(k in name for k in ["src", "code", "project", "backup"]):
                item.custom_category = "Archives"
            # Large videos or long movies → Videos (already correct usually)
            # Music stems or audio projects
            elif any(k in name for k in ["mix", "master", "vocal", "beat"]):
                item.custom_category = "Music"

    def _find_duplicates(self, items: list[PlanItem], use_perceptual: bool = False) -> dict:
        """Exact (SHA256) + optional perceptual duplicate detection for images."""
        import hashlib
        exact_hashes = {}
        dups = {}

        # 1. Exact content duplicates (all files)
        for item in items:
            try:
                h = hashlib.sha256()
                with open(item.path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        h.update(chunk)
                digest = h.hexdigest()
                if digest in exact_hashes:
                    if digest not in dups:
                        dups[digest] = [exact_hashes[digest]]
                    dups[digest].append(item)
                else:
                    exact_hashes[digest] = item
            except Exception:
                continue

        # 2. Perceptual duplicates for images (if enabled)
        if use_perceptual:
            img_items = [it for it in items if it.path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp")]
            phash_map = {}
            for item in img_items:
                ph = get_perceptual_hash(item.path)
                if not ph:
                    continue
                # Group images with very similar perceptual hashes (hamming <= 3)
                matched = False
                for existing_ph, group in list(phash_map.items()):
                    if hamming_distance(ph, existing_ph) <= 3:
                        group.append(item)
                        matched = True
                        break
                if not matched:
                    phash_map[ph] = [item]

            # Add perceptual groups (only if >1 images)
            for ph, group in phash_map.items():
                if len(group) > 1:
                    # Use perceptual hash as key with prefix so it doesn't collide with exact
                    key = "ph_" + ph
                    if key not in dups:
                        dups[key] = group
                    else:
                        # merge if needed
                        dups[key].extend(group)

        return dups

    def _apply_rules_and_smart(self, path: Path) -> str:
        """Apply user rules first (priority order), then fall back to ultra-smart categorization."""
        # Sort rules by priority (lower first)
        sorted_rules = sorted([r for r in self.rules if r.enabled], key=lambda r: r.priority)
        for rule in sorted_rules:
            if rule.matches(path):
                return rule.target_category
        return smart_categorize(path)

    def _handle_conflicts(self, conflicts: list) -> bool:
        """Conflict Resolver - returns True if user wants to proceed."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("Conflicts Found")
        dlg.geometry("620x420")
        dlg.transient(self)

        ctk.CTkLabel(dlg, text=f"{len(conflicts)} files would overwrite existing ones.", font=ctk.CTkFont(size=14, weight="bold")).pack(padx=20, pady=(16, 8), anchor="w")

        text = ctk.CTkTextbox(dlg, height=260)
        text.pack(fill="both", padx=20, pady=8)
        for item, dest in conflicts:
            text.insert("end", f"• {item.path.name} → {dest.name} (exists)\n")
        text.configure(state="disabled")

        choices = ctk.CTkFrame(dlg, fg_color="transparent")
        choices.pack(fill="x", padx=20, pady=12)

        strategy = ctk.StringVar(value="rename")
        ctk.CTkRadioButton(choices, text="Rename all (add numbers)", variable=strategy, value="rename").pack(anchor="w")
        ctk.CTkRadioButton(choices, text="Replace if source is newer", variable=strategy, value="replace_newer").pack(anchor="w")
        ctk.CTkRadioButton(choices, text="Skip conflicting files", variable=strategy, value="skip").pack(anchor="w")

        result = {"proceed": False}

        def decide():
            result["proceed"] = True
            result["strategy"] = strategy.get()
            dlg.destroy()

        ctk.CTkButton(dlg, text="Cancel", width=120, command=dlg.destroy).pack(side="left", padx=20, pady=12)
        ctk.CTkButton(dlg, text="Proceed with chosen strategy", fg_color=get_accent(), command=decide).pack(side="right", padx=20)

        dlg.wait_window()
        if result["proceed"]:
            self._conflict_strategy = result["strategy"]
        return result["proceed"]

    def _simulate_changes(self):
        """Powerful simulation preview - shows exactly what will happen."""
        base = self._valid_folder()
        if base is None:
            return
        plan = [item for item in self.last_plan if item.selected]
        if not plan:
            self._toast("No files selected.", WARNING)
            return

        # Group by final category
        by_cat = {}
        total_size = 0
        for item in plan:
            cat = item.effective_category
            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append(item)
            total_size += item.size

        dlg = ctk.CTkToplevel(self)
        dlg.title("Simulation Preview")
        dlg.geometry("720x520")
        dlg.transient(self)

        ctk.CTkLabel(dlg, text=f"Planned changes for {base.name}", font=ctk.CTkFont(size=16, weight="bold")).pack(padx=20, pady=(16, 8), anchor="w")
        ctk.CTkLabel(dlg, text=f"{len(plan)} files • {human_size(total_size)}", font=ctk.CTkFont(size=12), text_color=C["textLo"]).pack(padx=20, anchor="w")

        text = ctk.CTkTextbox(dlg, height=340, font=ctk.CTkFont(size=12))
        text.pack(fill="both", expand=True, padx=20, pady=12)

        for cat in sorted(by_cat):
            text.insert("end", f"\n▶ {cat} ({len(by_cat[cat])} files)\n")
            for item in by_cat[cat][:8]:
                text.insert("end", f"   → {item.path.name}\n")
            if len(by_cat[cat]) > 8:
                text.insert("end", f"   ... and {len(by_cat[cat])-8} more\n")

        text.configure(state="disabled")

        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=12)
        ctk.CTkButton(btns, text="Close", width=120, command=dlg.destroy).pack(side="left")
        ctk.CTkButton(btns, text="Proceed to Organize", width=180, fg_color=get_accent(), command=lambda: (dlg.destroy(), self._organize())).pack(side="right")

    # ---- navigation / theme ----

    def _show_view(self, key):
        for v in self.views.values():
            v.grid_forget()
        self.views[key].grid(row=0, column=0, sticky="nsew")
        for k, b in self.nav_buttons.items():
            if k == key:
                b.configure(fg_color=get_accent(), text_color="#FFFFFF")
            else:
                b.configure(fg_color="transparent", text_color=C["textHi"])
        if key == "history":
            self._refresh_history()
        elif key == "duplicates":
            self._refresh_duplicates()
        elif key == "analytics":
            self._refresh_analytics()
        elif key == "finder":
            self._finder_set_admin_badge()
        elif key == "settings":
            if hasattr(self, "_refresh_ignore_text"):
                self.after(30, self._refresh_ignore_text)
            if hasattr(self, "_refresh_rules_list"):
                self.after(50, self._refresh_rules_list)

    def _set_theme(self, value):
        ctk.set_appearance_mode("light" if value == "Light" else "dark")
        self.after(60, lambda: self.donut.draw(self.donut.data))
        self._save_config()

    # ---- actions ----

    def _browse(self):
        from tkinter import filedialog
        chosen = filedialog.askdirectory(initialdir=self.folder.get(),
                                          title="Choose a folder to organize")
        if chosen:
            self.folder.set(chosen)
            self._save_config()

    def _refresh_ignore_text(self):
        if not hasattr(self, "ignore_text"):
            return
        text = "\n".join(self.ignore_patterns)
        self.ignore_text.delete("0.0", "end")
        self.ignore_text.insert("0.0", text)

    def _parse_ignore_text(self) -> list[str]:
        if not hasattr(self, "ignore_text"):
            return list(self.ignore_patterns)
        raw = self.ignore_text.get("0.0", "end").strip()
        parts = []
        for line in raw.replace(",", "\n").splitlines():
            p = line.strip()
            if p:
                parts.append(p)
        return parts or list(DEFAULT_IGNORES)

    def _save_ignores(self):
        self.ignore_patterns = self._parse_ignore_text()
        self._save_config()
        self._toast("Ignore patterns saved.", SUCCESS)
        # Re-preview current if valid
        self.after(100, self._preview)

    def _reset_ignores(self):
        self.ignore_patterns = list(DEFAULT_IGNORES)
        self._refresh_ignore_text()
        self._save_config()
        self._toast("Ignores reset to defaults.", WARNING)

    def _reset_all_settings(self):
        if not ConfirmDialog.ask(self, "Reset all settings?",
                                 "This will restore defaults for theme, behavior, ignores, rules and tray options.",
                                 ok_text="Reset", ok_color=DANGER):
            return
        # Reset variables
        self.confirm_before.set(True)
        self.open_after.set(False)
        self.recursive.set(False)
        self.live_mode.set(False)
        self.use_date_folders.set(False)
        self.dry_run.set(False)
        self.delete_empty_after.set(True)
        self.minimize_to_tray.set(True)
        self.start_minimized.set(False)
        self.use_perceptual_duplicates.set(True)
        self.ignore_patterns = list(DEFAULT_IGNORES)
        self.rules = []
        self.current_profile = "Default"
        set_accent(DEFAULT_ACCENT)
        ctk.set_appearance_mode("Dark")

        self._save_config()
        if hasattr(self, "ignore_text"):
            self._refresh_ignore_text()
        if hasattr(self, "rules_list"):
            self._refresh_rules_list()
        self._toast("All settings restored to defaults", get_accent())
        self.after(80, self._preview)

    def _valid_folder(self):
        base = Path(self.folder.get())
        if not base.exists() or not base.is_dir():
            self._toast("That folder does not exist.", DANGER)
            return None
        return base

    def _toast(self, text, color=None):
        self.status.configure(text=text, text_color=color or C["textLo"])

    def _preview(self):
        base = self._valid_folder()
        if base is None:
            return
        raw = scan_folder(base, self.recursive.get(), self.ignore_patterns)
        # Convert using the BEST possible local intelligence + user rules
        self.last_plan = []
        for p, basic_cat in raw:
            cat = self._apply_rules_and_smart(p)
            self.last_plan.append(PlanItem(path=p, category=cat))

        # Built-in smart rules
        self._apply_smart_rules(self.last_plan)

        self._save_config()

        # Rebuild the gorgeous interactive list
        self._rebuild_file_list(self.last_plan)

        # Update donut + cards from all (initially all selected)
        counts, size = {}, 0
        for item in self.last_plan:
            cat = item.effective_category
            counts[cat] = counts.get(cat, 0) + 1
            size += item.size

        total = len(self.last_plan)
        for name, card in self.cards.items():
            card.update_count(counts.get(name, 0), total)
        self.donut.draw(counts)
        self.stat_files.set_value(str(total))
        self.stat_cats.set_value(str(sum(1 for v in counts.values() if v)))
        self.stat_size.set_value(human_size(size))

        if total:
            self._toast(f"{total} files ready.", get_accent())
            use_p = getattr(self, "use_perceptual_duplicates", ctk.BooleanVar(value=True)).get()
            dups = self._find_duplicates(self.last_plan, use_perceptual=use_p)
            dup_count = sum(len(v) for v in dups.values())
            if dup_count > 0:
                label = "exact + similar images" if use_p else "exact content"
                self._toast(f"{dup_count} duplicate files found ({label})", WARNING)
        else:
            self._toast("Folder is clean. Nothing to organize.", WARNING)

    def _organize(self):
        base = self._valid_folder()
        if base is None:
            return

        to_move = [item for item in self.last_plan if item.selected]
        if not to_move:
            self._toast("No files selected to organize.", WARNING)
            return

        # Pre-check for conflicts
        conflicts = []
        for item in to_move:
            cat = item.effective_category
            target = base / cat
            if self.use_date_folders.get():
                target = target / get_date_subfolder(item.path)
            dest = target / item.path.name
            if dest.exists():
                conflicts.append((item, dest))

        if conflicts and not self.dry_run.get():
            if not self._handle_conflicts(conflicts):
                return  # user cancelled

        if self.confirm_before.get():
            ok = ConfirmDialog.ask(
                self, "Organize selected files?",
                f"Move {len(to_move)} selected file(s) into smart folders?\n\n"
                f"Target: {base.name}",
                ok_text="Organize Now")
            if not ok:
                return

        self._set_busy(True)
        self.progress.pack(side="left", fill="x", expand=True, padx=(16, 0))
        self.progress.set(0)

        plan_tuples = [item.to_tuple() for item in to_move]
        threading.Thread(target=self._do_organize, args=(base, plan_tuples),
                         daemon=True).start()

    def _do_organize(self, base, plan):
        moved, errors, total = [], 0, len(plan)
        use_date = self.use_date_folders.get()
        is_dry = self.dry_run.get()

        for i, (source_str, cat) in enumerate(plan, 1):
            try:
                source = Path(source_str)
                target = base / cat

                if use_date:
                    date_folder = get_date_subfolder(source)
                    target = target / date_folder

                target.mkdir(parents=True, exist_ok=True)
                dest = target / source.name

                # Best-in-class conflict resolution (uses strategy from wizard if set)
                strategy = getattr(self, '_conflict_strategy', 'rename')
                if dest.exists():
                    if strategy == "skip":
                        continue  # skip this file
                    elif strategy == "replace_newer":
                        try:
                            if source.stat().st_mtime <= dest.stat().st_mtime:
                                dest = unique_destination(dest)
                            else:
                                dest.unlink()
                        except:
                            dest = unique_destination(dest)
                    else:  # rename
                        dest = unique_destination(dest)

                if is_dry:
                    moved.append((str(source), str(dest)))
                else:
                    shutil.move(str(source), str(dest))
                    moved.append((str(source), str(dest)))
            except Exception:
                errors += 1
            self.after(0, self.progress.set, i / total)
            if i % 4 == 0 or i == total:
                status = "Simulating" if is_dry else "Moving"
                self.after(0, self._toast, f"{status}... {i}/{total}", get_accent())

        if moved:
            op = {
                "when": datetime.now().isoformat(timespec="seconds"),
                "moves": moved,
                "count": len(moved),
            }
            try:
                undo_path = base / UNDO_FILE
                existing = {"operations": []}
                if undo_path.exists():
                    try:
                        existing = json.loads(undo_path.read_text(encoding="utf-8"))
                        if "moves" in existing and "operations" not in existing:
                            existing = {"operations": [existing]}
                    except Exception:
                        existing = {"operations": []}
                ops = existing.get("operations", [])
                ops.append(op)
                if len(ops) > MAX_HISTORY:
                    ops = ops[-MAX_HISTORY:]
                existing["operations"] = ops
                with open(undo_path, "w", encoding="utf-8") as fh:
                    json.dump(existing, fh, ensure_ascii=False, indent=2)
            except Exception:
                pass

        if self.delete_empty_after.get() and not self.dry_run.get():
            for cat in CATEGORY_ORDER:
                try:
                    folder = base / cat
                    if folder.exists() and not any(folder.iterdir()):
                        folder.rmdir()
                except:
                    pass

        self.after(0, self._organize_done, base, len(moved), errors)

    def _organize_done(self, base, moved_count, errors):
        self._set_busy(False)
        self.after(650, self.progress.pack_forget)
        self._preview()

        if self.dry_run.get():
            msg = f"🔍 Dry Run complete — would have organized {moved_count} files."
        else:
            msg = f"Organized {moved_count} file(s)."
        if errors:
            msg += f"  ({errors} issues)"
        self._toast(msg, SUCCESS)

        # Summary dialog
        try:
            undo_path = base / UNDO_FILE
            if undo_path.exists():
                data = json.loads(undo_path.read_text(encoding="utf-8"))
                ops = data.get("operations") or ([data] if "moves" in data else [])
                if ops:
                    last_moves = ops[-1].get("moves", [])
                    if last_moves:
                        SummaryDialog(self, base.name, last_moves)
        except Exception:
            pass

        if self.open_after.get():
            try:
                os.startfile(str(base))
            except Exception:
                pass

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        if hasattr(self, "preview_btn"):
            self.preview_btn.configure(state=state)
        if hasattr(self, "organize_btn"):
            self.organize_btn.configure(
                state=state, text="Organizing…" if busy else "Organize files")

    # ==================== LIVE WATCH ====================
    def _toggle_live(self):
        enabled = self.live_mode.get()
        self._save_config()

        if enabled:
            self._start_watching()
            self._toast("Live mode ON — new files will be auto-organized", SUCCESS)
        else:
            self._stop_watching()
            self._toast("Live mode OFF", C["textLo"])

    def _start_watching(self):
        if not HAS_WATCHDOG:
            self._toast("watchdog not installed — live mode unavailable", DANGER)
            self.live_mode.set(False)
            return
        base = self._valid_folder()
        if not base:
            self.live_mode.set(False)
            return
        self._stop_watching()

        class _Handler(FileSystemEventHandler):
            def __init__(self, app, base_path):
                self.app = app
                self.base = base_path

            def on_created(self, event):
                if event.is_directory:
                    return
                time.sleep(0.6)  # let file finish writing
                try:
                    p = Path(event.src_path)
                    if p.parent != self.base:
                        return
                    if should_ignore(p.name, self.app.ignore_patterns):
                        return
                    cat = category_for(p)
                    target = self.base / cat
                    target.mkdir(exist_ok=True)
                    dest = unique_destination(target / p.name)
                    shutil.move(str(p), str(dest))
                    # record for undo
                    self.app._record_auto_move(str(p), str(dest), str(self.base))
                    self.app.after(200, self.app._preview)
                    self.app.after(250, lambda: self.app._toast(f"Auto: {p.name} → {cat}", SUCCESS))
                except Exception:
                    pass

        self._watched_path = base
        self._observer = Observer()
        handler = _Handler(self, base)
        self._observer.schedule(handler, str(base), recursive=False)
        self._observer.start()

    def _stop_watching(self):
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=1)
            except Exception:
                pass
        self._observer = None
        self._watched_path = None

    def _record_auto_move(self, src, dst, base_str):
        """Record auto move to history."""
        try:
            undo_path = Path(base_str) / UNDO_FILE
            op = {"when": datetime.now().isoformat(timespec="seconds"), "moves": [(src, dst)], "count": 1, "auto": True}
            existing = {"operations": []}
            if undo_path.exists():
                try:
                    existing = json.loads(undo_path.read_text(encoding="utf-8"))
                except:
                    existing = {"operations": []}
            ops = existing.get("operations", [])
            ops.append(op)
            if len(ops) > MAX_HISTORY:
                ops = ops[-MAX_HISTORY:]
            existing["operations"] = ops
            with open(undo_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        except:
            pass

    def _refresh_history(self):
        if not hasattr(self, 'history_list'):
            return
        # Clear previous dynamic content
        for child in self.history_list.winfo_children():
            child.destroy()

        base = Path(self.folder.get())
        undo = base / UNDO_FILE

        ops = []
        if undo.exists():
            try:
                data = json.loads(undo.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    if "operations" in data:
                        ops = data["operations"]
                    elif "moves" in data:
                        # legacy
                        ops = [data]
            except Exception:
                pass

        if not ops:
            self.history_list.grid_remove()
            self.history_empty.grid()
            return

        self.history_empty.grid_remove()
        self.history_list.grid()

        # Show newest first
        for idx, op in reversed(list(enumerate(ops))):
            when = op.get("when", "unknown")
            count = op.get("count", len(op.get("moves", [])))
            moves = op.get("moves", [])
            is_auto = op.get("auto", False)

            row = ctk.CTkFrame(self.history_list, fg_color=C["surface2"], corner_radius=10)
            row.pack(fill="x", pady=4, padx=4)

            prefix = "⚡ AUTO  " if is_auto else ""
            info = ctk.CTkLabel(row, text=f"{prefix}{when}  ·  {count} file(s)",
                                font=ctk.CTkFont(size=12), text_color=C["textHi"], anchor="w")
            info.pack(side="left", padx=14, pady=9)

            def make_undo_handler(m=moves, op_idx=idx):
                def handler(): self._undo_operation(base, m, op_idx)
                return handler

            ctk.CTkButton(row, text="Undo", width=78, height=26, corner_radius=7,
                          fg_color=DANGER, hover_color="#C53030",
                          font=ctk.CTkFont(size=11, weight="bold"),
                          command=make_undo_handler()).pack(side="right", padx=10)

    def _undo_operation(self, base: Path, moves: list, op_idx: int):
        if not moves:
            return
        if not ConfirmDialog.ask(
                self, "Undo this organize?",
                f"Move {len(moves)} file(s) back to their original place?",
                ok_text="Undo", ok_color=DANGER, ok_hover="#D63A33"):
            return

        restored = 0
        for src_s, dst_s in moves:
            try:
                src, dst = Path(src_s), Path(dst_s)
                if dst.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dst), str(unique_destination(src)))
                    restored += 1
            except Exception:
                pass

        # Remove this operation from the history file
        self._remove_history_op(base, op_idx)

        # Clean empty managed folders
        for name in MANAGED_FOLDERS:
            folder = base / name
            if folder.is_dir() and not any(folder.iterdir()):
                try:
                    folder.rmdir()
                except OSError:
                    pass

        self._refresh_history()
        self._show_view("organize")
        self._preview()
        self._toast(f"Restored {restored} file(s).", SUCCESS)

    def _remove_history_op(self, base: Path, op_idx: int):
        undo = base / UNDO_FILE
        if not undo.exists():
            return
        try:
            data = json.loads(undo.read_text(encoding="utf-8"))
            if "operations" in data:
                ops = data["operations"]
                if 0 <= op_idx < len(ops):
                    del ops[op_idx]
                if not ops:
                    undo.unlink(missing_ok=True)
                else:
                    with open(undo, "w", encoding="utf-8") as fh:
                        json.dump(data, fh, ensure_ascii=False, indent=2)
            else:
                # legacy single
                undo.unlink(missing_ok=True)
        except Exception:
            pass

    def _undo(self):
        # Legacy single-button undo (falls back to newest)
        base = Path(self.folder.get())
        undo = base / UNDO_FILE
        if not undo.exists():
            return
        try:
            data = json.loads(undo.read_text(encoding="utf-8"))
            if "operations" in data and data["operations"]:
                moves = data["operations"][-1].get("moves", [])
            else:
                moves = data.get("moves", [])
        except Exception:
            return
        if not moves:
            return
        # Reuse the per-op logic on the last one
        self._undo_operation(base, moves, len(data.get("operations", [data])) - 1)

    # ==================== TRAY ICON + BACKGROUND MODE ====================

    def _get_tray_image(self):
        """Load a nice tray icon (prefers logo.png, falls back to app.ico)."""
        try:
            img = Image.open(resource_path("assets/logo.png"))
            img = img.convert("RGBA").resize((64, 64), Image.LANCZOS)
            return img
        except Exception:
            try:
                img = Image.open(resource_path("assets/app.ico"))
                img = img.convert("RGBA").resize((64, 64), Image.LANCZOS)
                return img
            except Exception:
                # last resort: simple colored square
                img = Image.new("RGBA", (64, 64), (10, 132, 255, 255))
                return img

    def _create_tray_icon(self):
        if not HAS_TRAY:
            return None

        def on_show(icon, item):
            self.after(0, self._show_window_from_tray)

        def on_organize(icon, item):
            self.after(0, self._organize_from_tray)

        def on_toggle_live(icon, item):
            self.after(0, self._toggle_live_from_tray)

        def on_quit(icon, item):
            self.after(0, self._quit_from_tray)

        menu = pystray.Menu(
            pystray.MenuItem("Show FileFlow", on_show, default=True),
            pystray.MenuItem("Organize now", on_organize),
            pystray.MenuItem(lambda item: "Stop Live Auto" if self.live_mode.get() else "Start Live Auto",
                             on_toggle_live),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )

        icon = pystray.Icon(
            "FileFlow",
            self._get_tray_image(),
            APP_NAME,
            menu
        )
        return icon

    def _show_window_from_tray(self):
        """Restore the main window from tray."""
        try:
            if self._tray_icon:
                self._tray_icon.visible = False
        except Exception:
            pass
        self.deiconify()
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.attributes("-topmost", False)

    def _hide_to_tray(self):
        """Hide main window and show tray icon."""
        if not HAS_TRAY:
            self.iconify()
            return

        self.withdraw()  # hide window completely

        if self._tray_icon is None:
            self._tray_icon = self._create_tray_icon()
            if self._tray_icon:
                self._tray_thread = threading.Thread(target=self._tray_icon.run, daemon=True)
                self._tray_thread.start()

        if self._tray_icon:
            self._tray_icon.visible = True
            # Update title/menu dynamically if needed
            try:
                self._tray_icon.title = f"{APP_NAME} — {Path(self.folder.get()).name}"
            except Exception:
                pass

    def _on_closing(self):
        """Called when user clicks X."""
        if not HAS_TRAY or not self.minimize_to_tray.get():
            # Normal close
            self._cleanup_and_quit()
            return

        # Minimize to tray instead of closing
        self._hide_to_tray()
        self._toast("FileFlow is running in the background (tray)")

    def _organize_from_tray(self):
        """Quick organize triggered from tray."""
        try:
            self._show_window_from_tray()
            self.after(200, self._preview)
            self.after(600, self._organize)
        except Exception:
            pass

    def _toggle_live_from_tray(self):
        """Toggle Live Auto from tray and keep background running."""
        try:
            new_state = not self.live_mode.get()
            self.live_mode.set(new_state)
            self._toggle_live()
            # If window is hidden, still show a toast somehow is hard — update tray title
            if self._tray_icon:
                status = "LIVE" if new_state else "idle"
                try:
                    self._tray_icon.title = f"FileFlow • {status}"
                except Exception:
                    pass
        except Exception:
            pass

    def _quit_from_tray(self):
        """Properly quit from tray menu."""
        self._cleanup_and_quit()

    def _cleanup_and_quit(self):
        """Stop watchers, tray, and exit."""
        # Stop live watch
        try:
            self._stop_watching()
        except Exception:
            pass

        # Stop tray
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None

        # Destroy window
        try:
            self.destroy()
        except Exception:
            pass

        # Force exit (pystray + tkinter on Windows can leave threads)
        try:
            import sys as _sys
            _sys.exit(0)
        except SystemExit:
            raise
        except Exception:
            import os as _os
            _os._exit(0)

    # ==================== COMMAND PALETTE ====================
    def _show_command_palette(self):
        palette = ctk.CTkToplevel(self)
        palette.title("Command Palette")
        palette.geometry("520x340")
        palette.resizable(False, False)
        palette.configure(fg_color=C["surface"])
        palette.transient(self)

        # Center
        palette.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 520) // 2
        y = self.winfo_rooty() + 120
        palette.geometry(f"+{x}+{y}")

        entry = ctk.CTkEntry(palette, placeholder_text="Type a command... (preview, organize, undo, live, settings...)",
                             height=44, corner_radius=12, font=ctk.CTkFont(size=14))
        entry.pack(fill="x", padx=18, pady=(18, 10))
        entry.focus()

        list_frame = ctk.CTkScrollableFrame(palette, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        actions = [
            ("Preview current folder", self._preview),
            ("Organize selected files", self._organize),
            ("Toggle Live Auto mode", lambda: (self.live_mode.set(not self.live_mode.get()), self._toggle_live())),
            ("Switch to History", lambda: self._show_view("history")),
            ("Switch to Settings", lambda: self._show_view("settings")),
            ("Undo last operation", self._undo),
            ("Clear file filters", self._clear_filter),
            ("Refresh", self._preview),
            ("Open target folder", lambda: os.startfile(self.folder.get())),
            ("Find & delete on the whole PC", lambda: self._show_view("finder")),
            ("Minimize to tray", self._hide_to_tray),
        ]

        def filter_actions(*_):
            q = entry.get().lower().strip()
            for child in list_frame.winfo_children():
                child.destroy()
            for label, cmd in actions:
                if not q or q in label.lower():
                    b = ctk.CTkButton(list_frame, text=label, anchor="w",
                                      fg_color="transparent", hover_color=C["surface2"],
                                      text_color=C["textHi"], height=34,
                                      command=lambda c=cmd: (palette.destroy(), c()))
                    b.pack(fill="x", pady=2, padx=8)

        entry.bind("<KeyRelease>", filter_actions)
        entry.bind("<Return>", lambda e: filter_actions())

        filter_actions()  # initial render

        def close(e=None):
            palette.destroy()
        palette.bind("<Escape>", close)
        self.after(10, lambda: palette.focus())

    # ========================================================================= #
    #  Find & Delete  —  whole-PC folder/file search + safe delete / rename     #
    # ========================================================================= #

    def _make_finder_view(self):
        F = ctk.CTkFont
        view = ctk.CTkFrame(self.content, fg_color="transparent")
        view.grid(row=0, column=0, sticky="nsew")
        view.grid_columnconfigure(0, weight=1)
        view.grid_rowconfigure(4, weight=1)

        # Header + admin badge
        head = ctk.CTkFrame(view, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 8))
        head.grid_columnconfigure(0, weight=1)
        tb = ctk.CTkFrame(head, fg_color="transparent")
        tb.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(tb, text="Find & Delete", anchor="w",
                     font=F(size=22, weight="bold"), text_color=C["textHi"]).pack(anchor="w")
        ctk.CTkLabel(tb, text="Search files/folders by name or inside content (PDFs & text). Open, rename or delete.",
                     anchor="w", font=F(size=13), text_color=C["textLo"]).pack(anchor="w", pady=(2, 0))
        ab = ctk.CTkFrame(head, fg_color="transparent")
        ab.grid(row=0, column=1, sticky="e")
        self.admin_badge = ctk.CTkLabel(ab, text="", font=F(size=12, weight="bold"))
        self.admin_badge.pack(anchor="e")
        self.admin_btn = ctk.CTkButton(ab, text="Restart as Admin", height=32, width=170,
                                       corner_radius=8, fg_color=C["surface2"],
                                       hover_color=C["border"], text_color=C["textHi"],
                                       command=self._finder_restart_admin)
        self.admin_btn.pack(anchor="e", pady=(6, 0))

        # Search card
        card = ctk.CTkFrame(view, fg_color=C["surface"], corner_radius=16,
                            border_width=1, border_color=C["border"])
        card.grid(row=1, column=0, sticky="ew", padx=28)
        card.grid_columnconfigure(0, weight=1)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 6))
        inner.grid_columnconfigure(0, weight=1)
        self.finder_query = ctk.StringVar()
        ent = ctk.CTkEntry(inner, textvariable=self.finder_query, height=44, corner_radius=10,
                           fg_color=C["surface2"], border_color=C["border"], font=F(size=14),
                           placeholder_text="Folder or file name to find   (e.g.  old backups )")
        ent.grid(row=0, column=0, columnspan=4, sticky="ew")
        ent.bind("<Return>", lambda e: self._finder_search())

        drives = ["All drives"] + [f"{l}:\\" for l in "CDEFGHIJKLMNOPQRSTUVWXYZ"
                                   if os.path.exists(f"{l}:\\")]
        self.finder_scope = ctk.CTkOptionMenu(inner, values=drives, width=132,
                                              fg_color=C["surface2"], button_color=C["border"],
                                              text_color=C["textHi"])
        self.finder_scope.grid(row=1, column=0, sticky="w", pady=(12, 0))
        ctk.CTkButton(inner, text="Browse…", width=90, height=30, corner_radius=8,
                      fg_color=C["surface2"], hover_color=C["border"], text_color=C["textHi"],
                      command=self._finder_browse_scope).grid(row=1, column=1, sticky="w",
                                                              padx=8, pady=(12, 0))
        self.finder_match = ctk.CTkOptionMenu(inner, values=["Folders", "Files", "Both"], width=112,
                                              fg_color=C["surface2"], button_color=C["border"],
                                              text_color=C["textHi"])
        self.finder_match.set("Folders")
        self.finder_match.grid(row=1, column=2, sticky="w", padx=8, pady=(12, 0))
        self.finder_btn = ctk.CTkButton(inner, text="Search", width=130, height=36, corner_radius=10,
                                        fg_color=get_accent(), hover_color=get_accent_hover(),
                                        font=F(size=14, weight="bold"), command=self._finder_search)
        self.finder_btn.grid(row=1, column=3, sticky="e", pady=(12, 0))

        saferow = ctk.CTkFrame(card, fg_color="transparent")
        saferow.grid(row=1, column=0, sticky="ew", padx=18, pady=(2, 14))
        ctk.CTkSwitch(saferow, text="Safe mode — send deletions to the Recycle Bin (recommended)",
                      variable=self.finder_safe_mode, progress_color=SUCCESS,
                      command=self._finder_safe_changed, text_color=C["textHi"],
                      font=F(size=12)).pack(side="left")
        self.finder_safe_warn = ctk.CTkLabel(saferow, text="", font=F(size=12, weight="bold"),
                                             text_color=DANGER)
        self.finder_safe_warn.pack(side="left", padx=(10, 0))

        # Content search option
        content_row = ctk.CTkFrame(card, fg_color="transparent")
        content_row.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 10))
        ctk.CTkCheckBox(content_row,
                        text="Also search inside files (PDF, TXT, etc.) — slower but powerful",
                        variable=self.finder_search_content,
                        text_color=C["textHi"], font=F(size=12)).pack(side="left")

        # Action / status bar
        bar = ctk.CTkFrame(view, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=28, pady=(14, 2))
        bar.grid_columnconfigure(0, weight=1)
        self.finder_status = ctk.CTkLabel(bar, text="Type a name and press Search.", anchor="w",
                                          font=F(size=13), text_color=C["textLo"])
        self.finder_status.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(bar, text="Select all", width=90, height=30, corner_radius=8,
                      fg_color=C["surface2"], hover_color=C["border"], text_color=C["textHi"],
                      command=lambda: self._finder_select_all(True)).grid(row=0, column=1, padx=4)
        ctk.CTkButton(bar, text="Clear", width=70, height=30, corner_radius=8,
                      fg_color=C["surface2"], hover_color=C["border"], text_color=C["textHi"],
                      command=lambda: self._finder_select_all(False)).grid(row=0, column=2, padx=4)
        ctk.CTkButton(bar, text="Delete selected", width=146, height=30, corner_radius=8,
                      fg_color=DANGER, hover_color="#C53030", font=F(size=12, weight="bold"),
                      command=self._finder_delete_selected).grid(row=0, column=3, padx=(4, 0))

        self.finder_toast_lbl = ctk.CTkLabel(view, text="", anchor="w", font=F(size=12),
                                             text_color=C["textLo"])
        self.finder_toast_lbl.grid(row=3, column=0, sticky="ew", padx=28, pady=(2, 0))

        self.finder_results = ctk.CTkScrollableFrame(view, fg_color="transparent")
        self.finder_results.grid(row=4, column=0, sticky="nsew", padx=24, pady=(8, 16))
        self.finder_results.grid_columnconfigure(0, weight=1)

        self._finder_set_admin_badge()
        return view

    def _finder_safe_changed(self):
        self.finder_safe_warn.configure(
            text="" if self.finder_safe_mode.get() else "⚠ Permanent delete is ON — no undo!")

    def _finder_set_admin_badge(self):
        if not hasattr(self, "admin_badge"):
            return
        if is_admin():
            self.admin_badge.configure(text="● Administrator — full access", text_color=SUCCESS)
            self.admin_btn.configure(state="disabled", text="Admin granted")
        else:
            self.admin_badge.configure(text="● Standard user — limited access", text_color=WARNING)
            self.admin_btn.configure(state="normal", text="Restart as Admin")

    def _finder_restart_admin(self):
        if is_admin():
            return
        if not ConfirmDialog.ask(
                self, "Restart as Administrator?",
                "The app will close and reopen with administrator rights so it can search "
                "and delete inside protected locations. Continue?", ok_text="Restart"):
            return
        if relaunch_as_admin():
            self.after(150, lambda: (self.destroy(), sys.exit(0)))
        else:
            self._finder_toast("Could not get admin rights (UAC was cancelled).", DANGER)

    def _finder_browse_scope(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Choose a folder to search in")
        if not d:
            return
        d = os.path.normpath(d)
        vals = list(self.finder_scope.cget("values"))
        if d not in vals:
            vals.append(d)
            self.finder_scope.configure(values=vals)
        self.finder_scope.set(d)

    def _finder_toast(self, text, color=None):
        self.finder_toast_lbl.configure(text=text, text_color=color or C["textLo"])

    def _finder_select_all(self, state: bool):
        for e in self.finder_rows:
            try:
                e["var"].set(state)
            except Exception:
                pass

    def _finder_roots(self):
        v = self.finder_scope.get()
        if v == "All drives":
            return [f"{l}:\\" for l in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{l}:\\")]
        return [v] if os.path.exists(v) else []

    def _finder_search(self):
        # While a scan is running this button acts as Stop.
        if self._finder_thread and self._finder_thread.is_alive():
            self._finder_stop.set()
            self.finder_btn.configure(text="Stopping…")
            return
        query = self.finder_query.get().strip()
        if len(query) < 2:
            self._finder_toast("Type at least 2 characters to search.", WARNING)
            return
        roots = self._finder_roots()
        if not roots:
            self._finder_toast("That scope is not available.", DANGER)
            return
        for e in self.finder_rows:
            e["frame"].destroy()
        self.finder_rows = []
        self._finder_buffer = []
        self._finder_match_count = 0
        self._finder_checked = 0
        self._finder_stop.clear()
        match = self.finder_match.get()
        md, mf = match in ("Folders", "Both"), match in ("Files", "Both")
        self.finder_btn.configure(text="Stop", fg_color=DANGER, hover_color="#C53030")
        self.finder_status.configure(text="Scanning…", text_color=get_accent())
        self._finder_toast("")
        search_content = self.finder_search_content.get()
        self._finder_thread = threading.Thread(
            target=self._finder_worker, args=(query.lower(), roots, md, mf, search_content), daemon=True)
        self._finder_thread.start()
        self.after(120, self._finder_poll)

    def _finder_worker(self, q, roots, match_dirs, match_files, search_content=False):
        PRUNE = {"$recycle.bin", "system volume information"}
        CAP = 500
        text_exts = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".ini", ".py", ".js", ".html", ".css"}

        def _file_contains_text(fpath: str, query: str) -> bool:
            try:
                suf = Path(fpath).suffix.lower()
                if suf == ".pdf":
                    try:
                        from pypdf import PdfReader
                        reader = PdfReader(fpath)
                        text = ""
                        for page in reader.pages[:4]:  # limit pages
                            text += page.extract_text() or ""
                        return query in text.lower()
                    except:
                        return False
                elif suf in text_exts:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(20000).lower()  # limit size
                        return query in content
            except Exception:
                return False
            return False

        for root in roots:
            if self._finder_stop.is_set():
                break
            for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
                if self._finder_stop.is_set():
                    break
                self._finder_checked += 1
                dirnames[:] = [d for d in dirnames if d.lower() not in PRUNE]
                if match_dirs:
                    for d in dirnames:
                        if q in d.lower():
                            self._finder_buffer.append((os.path.join(dirpath, d), True))
                            self._finder_match_count += 1
                if match_files:
                    for fn in filenames:
                        full = os.path.join(dirpath, fn)
                        name_match = q in fn.lower()
                        content_match = False
                        if search_content and not name_match:
                            content_match = _file_contains_text(full, q)
                        if name_match or content_match:
                            self._finder_buffer.append((full, False))
                            self._finder_match_count += 1
                if self._finder_match_count >= CAP:
                    self._finder_stop.set()
                    break

    def _finder_poll(self):
        buf = self._finder_buffer
        if buf:
            take = buf[:40]
            del buf[:40]
            for full, is_dir in take:
                if len(self.finder_rows) < 500:
                    self._add_finder_row(full, is_dir)
        alive = bool(self._finder_thread and self._finder_thread.is_alive())
        capped = self._finder_match_count >= 500
        self.finder_status.configure(
            text=f"{'Scanning' if alive else 'Done'} — checked {self._finder_checked:,} "
                 f"folders · {self._finder_match_count:,} match(es)"
                 + ("  (showing first 500)" if capped else ""),
            text_color=get_accent() if alive else C["textLo"])
        if alive or buf:
            self.after(120, self._finder_poll)
        else:
            self.finder_btn.configure(text="Search", fg_color=get_accent(),
                                      hover_color=get_accent_hover())

    def _add_finder_row(self, full, is_dir):
        p = Path(full)
        row = ctk.CTkFrame(self.finder_results, fg_color=C["card"], corner_radius=10,
                           border_width=1, border_color=C["border"])
        row.pack(fill="x", pady=4, padx=2)
        row.grid_columnconfigure(2, weight=1)
        var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row, text="", width=24, variable=var, checkmark_color="#FFFFFF",
                        fg_color=get_accent(), hover_color=get_accent_hover()
                        ).grid(row=0, column=0, rowspan=2, padx=(12, 4), pady=12)
        ctk.CTkLabel(row, text="DIR" if is_dir else "FILE", width=44, height=26, corner_radius=7,
                     fg_color=C["surface2"],
                     text_color=get_accent() if is_dir else C["textLo"],
                     font=ctk.CTkFont(size=10, weight="bold")
                     ).grid(row=0, column=1, rowspan=2, padx=(0, 10))
        name_lbl = ctk.CTkLabel(row, text=p.name, anchor="w",
                                font=ctk.CTkFont(size=13, weight="bold"), text_color=C["textHi"])
        name_lbl.grid(row=0, column=2, sticky="w", pady=(8, 0))
        disp = full if len(full) <= 74 else "…" + full[-73:]
        try:
            size_txt = "" if is_dir else "   ·   " + human_size(p.stat().st_size)
        except Exception:
            size_txt = ""
        ctk.CTkLabel(row, text=disp + size_txt, anchor="w", font=ctk.CTkFont(size=11),
                     text_color=C["textLo"]).grid(row=1, column=2, sticky="w", pady=(0, 8))

        entry = {"frame": row, "var": var, "path": p, "is_dir": is_dir, "name_lbl": name_lbl}
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.grid(row=0, column=3, rowspan=2, padx=(8, 12))
        ctk.CTkButton(btns, text="Open", width=58, height=30, corner_radius=8,
                      fg_color=C["surface2"], hover_color=C["border"], text_color=C["textHi"],
                      command=lambda: self._finder_open(entry)).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="Rename", width=68, height=30, corner_radius=8,
                      fg_color=C["surface2"], hover_color=C["border"], text_color=C["textHi"],
                      command=lambda: self._finder_rename(entry)).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="Delete", width=64, height=30, corner_radius=8,
                      fg_color=DANGER, hover_color="#C53030",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: self._finder_delete_one(entry)).pack(side="left", padx=3)
        self.finder_rows.append(entry)

    def _finder_open(self, entry):
        try:
            os.startfile(str(entry["path"]))
        except Exception as e:
            self._finder_toast(f"Could not open: {e}", DANGER)

    def _finder_rename(self, entry):
        p = entry["path"]
        dlg = ctk.CTkInputDialog(text=f"New name for:\n{p.name}", title="Rename")
        new = dlg.get_input()
        if not new or not new.strip() or new.strip() == p.name:
            return
        try:
            target = p.with_name(new.strip())
            if target.exists():
                self._finder_toast("Something with that name already exists.", DANGER)
                return
            p.rename(target)
            entry["path"] = target
            entry["name_lbl"].configure(text=target.name)
            self._finder_toast(f"Renamed to “{target.name}”.", SUCCESS)
        except Exception as e:
            self._finder_toast(f"Rename failed: {e}", DANGER)

    def _finder_delete_one(self, entry):
        p = entry["path"]
        if is_protected_path(p):
            self._finder_toast(f"Refused — “{p.name}” is a protected system path.", DANGER)
            return
        safe = self.finder_safe_mode.get()
        msg = (f"Move to the Recycle Bin?\n\n{p}" if safe
               else f"PERMANENTLY delete this — it cannot be undone?\n\n{p}")
        if not ConfirmDialog.ask(self, "Delete?", msg, ok_text="Delete",
                                 ok_color=DANGER, ok_hover="#C53030"):
            return
        ok, m = delete_path(p, safe)
        if ok:
            entry["frame"].destroy()
            self.finder_rows = [e for e in self.finder_rows if e is not entry]
            self._finder_toast(f"“{p.name}” — {m}.", SUCCESS)
        else:
            self._finder_toast(f"“{p.name}” — {m}.", DANGER)

    def _finder_delete_selected(self):
        sel = [e for e in self.finder_rows if e["var"].get()]
        if not sel:
            self._finder_toast("Nothing selected — tick the items you want to delete.", WARNING)
            return
        safe = self.finder_safe_mode.get()
        msg = (f"Move {len(sel)} item(s) to the Recycle Bin?" if safe
               else f"PERMANENTLY delete {len(sel)} item(s)? This cannot be undone.")
        if not ConfirmDialog.ask(self, "Delete selected?", msg, ok_text="Delete",
                                 ok_color=DANGER, ok_hover="#C53030"):
            return
        done = blocked = failed = 0
        for e in sel:
            if is_protected_path(e["path"]):
                blocked += 1
                continue
            ok, _ = delete_path(e["path"], safe)
            if ok:
                e["frame"].destroy()
                done += 1
            else:
                failed += 1
        self.finder_rows = [e for e in self.finder_rows if e["frame"].winfo_exists()]
        parts = [f"deleted {done}"]
        if blocked:
            parts.append(f"blocked {blocked} protected")
        if failed:
            parts.append(f"failed {failed}")
        self._finder_toast(", ".join(parts) + ".", SUCCESS if done else WARNING)


def main():
    # Basic CLI support (for context menu + future)
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip('"')
        p = Path(arg)
        if p.exists() and p.is_dir():
            # Open app with this folder pre-selected
            app = OrganizerApp()
            app.folder.set(str(p))
            # Trigger preview after UI is ready
            app.after(400, app._preview)
            app.mainloop()
            return

    app = OrganizerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
