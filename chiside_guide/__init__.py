"""
chiside_guide — Guichi Shell sidewindow
Persistent AI guide backed by a local Ollama model (default: qwen2.5:3b).
Knows which page is active. Helps the user understand how to use the program.

Layout (250px wide, vertical stack):
  header_bar  — status dot + model label + ON/OFF toggle
  chat_area   — scrollable read-only chat history
  composer    — single-line input + Send button (visually separated)
"""

import os
import sys
import threading
import tkinter as tk

# ── sys.path: reach chi_reader/helpers from chiside_guide/ ────────────────────
_PACK_DIR   = os.path.dirname(os.path.abspath(__file__))   # chiside_guide/
_REPO_DIR   = os.path.dirname(_PACK_DIR)                   # pychi/
_GUI_FILES  = os.path.join(_REPO_DIR, "gui_files")
_CHI_READER = os.path.join(_REPO_DIR, "chi_reader")

if _GUI_FILES not in sys.path:
    sys.path.insert(0, _GUI_FILES)
if _CHI_READER not in sys.path:
    sys.path.insert(0, _CHI_READER)

try:
    from helpers.ollama_client import OllamaClient
    _IMPORT_OK = True
except Exception as _import_err:
    _IMPORT_OK = False
    _IMPORT_ERR_MSG = str(_import_err)

try:
    import shell_theme as _shell_theme
    _THEME_OK = True
except Exception:
    _THEME_OK = False

# ── Module identity ────────────────────────────────────────────────────────────

CODENAME = "chiside_guide"

# ── Defaults ───────────────────────────────────────────────────────────────────

_DEFAULT_MODEL    = "qwen2.5:3b"
_DEFAULT_BASE_URL = "http://localhost:11434"

_SYSTEM_TEMPLATE = (
    "Guichi shell guide. Page: {page_id}. {description} Answer briefly."
)
_WELCOME_SYSTEM = "Guichi shell guide. Answer briefly."

# ── Theme helpers ──────────────────────────────────────────────────────────────

def _load_theme_colors():
    if _THEME_OK:
        t = _shell_theme.get_theme()
    else:
        t = {}
    return {
        "bg":        t.get("panel_bg",      "#252525"),
        "panel_bg":  t.get("sidebar_bg",    "#1e1e1e"),
        "fg":        t.get("text_main",     "#cccccc"),
        "fg_muted":  t.get("text_muted",    "#777777"),
        "accent":    t.get("accent",        "#4ea0ff"),
        "btn_bg":    t.get("button_bg",     "#333333"),
        "btn_fg":    t.get("text_active",   "#cccccc"),
        "border":    t.get("border",        "#444444"),
        "dot_grey":  "#666666",
        "dot_green": "#4caf50",
        "dot_red":   "#e05050",
    }

# ── GuideSession ───────────────────────────────────────────────────────────────

class GuideSession:
    def __init__(self, enabled=True):
        self.history       = []
        self.model         = _DEFAULT_MODEL
        self.system_prompt = _WELCOME_SYSTEM
        self.enabled       = enabled
        self.connected     = False
        self.client        = OllamaClient(base_url=_DEFAULT_BASE_URL) if _IMPORT_OK else None


# ── GuidePanelController ───────────────────────────────────────────────────────

class GuidePanelController:

    def __init__(self, parent, shell=None):
        self._parent  = parent
        self._shell   = shell
        self._sending = False
        self._colors  = _load_theme_colors()

        enabled = True
        if shell is not None:
            enabled = bool(shell.config.get("guide_panel_enabled", True))

        if not _IMPORT_OK:
            self._show_import_error(parent)
            return

        self._session = GuideSession(enabled=enabled)
        self._build_ui(parent)
        self._set_dot(self._colors["dot_grey"])
        self._probe_connection()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self, parent):
        c = self._colors
        parent.configure(bg=c["bg"])
        self._build_header_bar(parent)

        chat_frame = tk.Frame(parent, bg=c["bg"])
        chat_frame.pack(fill=tk.BOTH, expand=True)
        self._build_chat_area(chat_frame)

        # Visible separator before composer
        sep = tk.Frame(parent, bg=c["border"], height=1)
        sep.pack(fill=tk.X)

        self._build_composer(parent)

    def _build_header_bar(self, parent):
        c = self._colors
        bar = tk.Frame(parent, bg=c["panel_bg"], height=28)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        self._dot_canvas = tk.Canvas(
            bar, width=10, height=10,
            bg=c["panel_bg"], highlightthickness=0,
        )
        self._dot_canvas.pack(side=tk.LEFT, padx=(6, 3), pady=9)
        self._dot_id = self._dot_canvas.create_oval(1, 1, 9, 9, fill=c["dot_grey"], outline="")

        self._model_label_var = tk.StringVar(value=_DEFAULT_MODEL)
        self._model_lbl = tk.Label(
            bar, textvariable=self._model_label_var,
            bg=c["panel_bg"], fg=c["fg_muted"],
            font=("TkFixedFont", 8), anchor=tk.W,
        )
        self._model_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self._toggle_btn = tk.Button(
            bar, text="ON" if self._session.enabled else "OFF",
            bg=c["btn_bg"], fg=c["btn_fg"],
            font=("TkDefaultFont", 7), relief=tk.FLAT,
            padx=4, pady=0,
            command=self._toggle_enabled,
        )
        self._toggle_btn.pack(side=tk.RIGHT, padx=(0, 5))

    def _build_chat_area(self, parent):
        c = self._colors
        scroll = tk.Scrollbar(parent, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._chat = tk.Text(
            parent,
            wrap=tk.WORD,
            state=tk.DISABLED,
            yscrollcommand=scroll.set,
            bg=c["bg"], fg=c["fg"],
            font=("TkFixedFont", 9),
            relief=tk.FLAT,
            padx=6, pady=4,
            cursor="arrow",
            highlightthickness=0,
        )
        self._chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self._chat.yview)

        self._chat.tag_configure("user",      foreground=c["accent"],  font=("TkFixedFont", 9, "bold"))
        self._chat.tag_configure("assistant", foreground=c["fg"])
        self._chat.tag_configure("error",     foreground=c["dot_red"])
        self._chat.tag_configure("meta",      foreground=c["fg_muted"], font=("TkDefaultFont", 8))

    def _build_composer(self, parent):
        c = self._colors
        row = tk.Frame(parent, bg=c["panel_bg"], height=32)
        row.pack(fill=tk.X)
        row.pack_propagate(False)

        self._send_btn = tk.Button(
            row, text="Send",
            bg=c["btn_bg"], fg=c["btn_fg"],
            font=("TkDefaultFont", 8), relief=tk.FLAT,
            padx=6,
            command=self._on_send,
        )
        self._send_btn.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 5), pady=3)

        self._entry = tk.Entry(
            row,
            bg=c["panel_bg"], fg=c["fg"],
            insertbackground=c["fg"],
            relief=tk.FLAT,
            font=("TkDefaultFont", 9),
            highlightthickness=1,
            highlightcolor=c["accent"],
            highlightbackground=c["border"],
        )
        self._entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 2), pady=5)
        self._entry.bind("<Return>", lambda e: self._on_send())

        self._update_composer_state()

    def _show_import_error(self, parent):
        c = self._colors
        parent.configure(bg=c["bg"])
        tk.Label(
            parent,
            text=f"chiside_guide: import failed\n{_IMPORT_ERR_MSG}",
            bg=c["bg"], fg=c["dot_red"],
            font=("TkDefaultFont", 8),
            wraplength=220, justify=tk.LEFT, anchor=tk.NW,
        ).pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    # ── Theme reactivity ───────────────────────────────────────────────────────

    def apply_theme(self, tokens):
        """Re-apply theme tokens to all widgets without rebuilding."""
        c = {
            "bg":        tokens.get("panel_bg",    "#252525"),
            "panel_bg":  tokens.get("sidebar_bg",  "#1e1e1e"),
            "fg":        tokens.get("text_main",   "#cccccc"),
            "fg_muted":  tokens.get("text_muted",  "#777777"),
            "accent":    tokens.get("accent",      "#4ea0ff"),
            "btn_bg":    tokens.get("button_bg",   "#333333"),
            "btn_fg":    tokens.get("text_active", "#cccccc"),
            "border":    tokens.get("border",      "#444444"),
            "dot_grey":  "#666666",
            "dot_green": "#4caf50",
            "dot_red":   "#e05050",
        }
        self._colors = c
        try:
            self._parent.configure(bg=c["bg"])
            self._model_lbl.configure(bg=c["panel_bg"], fg=c["fg_muted"])
            self._toggle_btn.configure(bg=c["btn_bg"], fg=c["btn_fg"])
            self._dot_canvas.configure(bg=c["panel_bg"])
            self._chat.configure(bg=c["bg"], fg=c["fg"])
            self._chat.tag_configure("user",      foreground=c["accent"])
            self._chat.tag_configure("assistant", foreground=c["fg"])
            self._chat.tag_configure("error",     foreground=c["dot_red"])
            self._chat.tag_configure("meta",      foreground=c["fg_muted"])
            self._send_btn.configure(bg=c["btn_bg"], fg=c["btn_fg"])
            self._entry.configure(
                bg=c["panel_bg"], fg=c["fg"],
                insertbackground=c["fg"],
                highlightcolor=c["accent"],
                highlightbackground=c["border"],
            )
        except Exception:
            pass

    # ── Connection probe ───────────────────────────────────────────────────────

    def _probe_connection(self):
        def _bg():
            result = self._session.client.list_models()
            self._parent.after(0, self._on_conn_result, result)
        threading.Thread(target=_bg, daemon=True).start()

    def _on_conn_result(self, result):
        if result.get("ok"):
            self._session.connected = True
            models = result.get("models", [])
            names = [m.get("name", "") for m in models]
            if _DEFAULT_MODEL not in names and names:
                self._session.model = names[0]
            self._set_dot(self._colors["dot_green"])
            self._model_label_var.set(self._session.model)
        else:
            self._session.connected = False
            self._set_dot(self._colors["dot_red"])
            self._model_label_var.set("offline")
        self._update_composer_state()

    # ── Page change ────────────────────────────────────────────────────────────

    def on_page_changed(self, page_id, pack_id, description):
        if page_id:
            self._session.system_prompt = _SYSTEM_TEMPLATE.format(
                page_id=page_id,
                description=description or "",
            )
            sep = f"── {page_id} ──"
        else:
            self._session.system_prompt = _WELCOME_SYSTEM
            sep = "── welcome ──"
        self._append_line(sep, tag="meta")

    # ── Send flow ──────────────────────────────────────────────────────────────

    def _on_send(self):
        if self._sending:
            return
        if not self._session.enabled or not self._session.connected:
            return
        text = self._entry.get().strip()
        if not text:
            return
        self._entry.delete(0, tk.END)
        self._append_bubble("user", text)
        self._sending = True
        self._update_composer_state()
        threading.Thread(target=self._do_send, args=(text,), daemon=True).start()

    def _do_send(self, user_text):
        messages = (
            [{"role": "system", "content": self._session.system_prompt}]
            + self._session.history
            + [{"role": "user", "content": user_text}]
        )
        result = self._session.client.chat(self._session.model, messages)
        self._parent.after(0, self._on_response, result, user_text)

    def _on_response(self, result, user_text):
        self._sending = False
        if result.get("ok"):
            reply = result.get("content", "").strip()
            self._append_bubble("assistant", reply)
            self._session.history.append({"role": "user",      "content": user_text})
            self._session.history.append({"role": "assistant", "content": reply})
        else:
            self._append_bubble("error", f"[{result.get('error', 'unknown error')}]")
        self._update_composer_state()
        self._scroll_to_bottom()

    # ── Toggle ─────────────────────────────────────────────────────────────────

    def _toggle_enabled(self):
        self._session.enabled = not self._session.enabled
        self._toggle_btn.config(text="ON" if self._session.enabled else "OFF")
        self._update_composer_state()
        if self._shell is not None:
            self._shell.config["guide_panel_enabled"] = self._session.enabled
            try:
                import guichi
                guichi.save_config(self._shell.config)
            except Exception:
                pass

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_dot(self, color):
        self._dot_canvas.itemconfig(self._dot_id, fill=color)

    def _update_composer_state(self):
        active = self._session.enabled and self._session.connected and not self._sending
        state  = tk.NORMAL if active else tk.DISABLED
        self._send_btn.config(state=state)
        self._entry.config(state=state)

    def _append_bubble(self, role, text):
        self._chat.config(state=tk.NORMAL)
        if role == "user":
            self._chat.insert(tk.END, "you: ", "user")
            self._chat.insert(tk.END, text + "\n", "user")
        elif role == "assistant":
            self._chat.insert(tk.END, "  ai: ", "assistant")
            self._chat.insert(tk.END, text + "\n\n", "assistant")
        else:
            self._chat.insert(tk.END, text + "\n", "error")
        self._chat.config(state=tk.DISABLED)
        self._scroll_to_bottom()

    def _append_line(self, text, tag="meta"):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, text + "\n", tag)
        self._chat.config(state=tk.DISABLED)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        self._chat.see(tk.END)


# ── Module-level singleton and public interface ────────────────────────────────

_controller: GuidePanelController | None = None


def build(parent, shell=None):
    global _controller
    _controller = GuidePanelController(parent, shell=shell)


def on_page_changed(page_id, pack_id, description):
    if _controller is not None:
        _controller.on_page_changed(page_id, pack_id, description)


def set_theme(tokens):
    if _controller is not None:
        _controller.apply_theme(tokens)
