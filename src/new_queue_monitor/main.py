"""NEW Queue Monitor — Monitor Debian FTP NEW queue."""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, Gio, GLib, Pango

import gettext
import locale
import os
import sys
import json
import datetime
import threading
import subprocess
import re
from new_queue_monitor.accessibility import AccessibilityManager

LOCALE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "po")
if not os.path.isdir(LOCALE_DIR):
    LOCALE_DIR = "/usr/share/locale"
locale.bindtextdomain("new-queue-monitor", LOCALE_DIR)
gettext.bindtextdomain("new-queue-monitor", LOCALE_DIR)
gettext.textdomain("new-queue-monitor")
_ = gettext.gettext

APP_ID = "se.danielnylander.new.queue.monitor"
SETTINGS_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "new-queue-monitor"
)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")


def _load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {"welcome_shown": False}


def _save_settings(s):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)



def _fetch_new_queue():
    """Fetch Debian NEW queue from API."""
    import urllib.request
    url = "https://ftp-master.debian.org/new.html"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            html = r.read().decode()
            # Parse basic table rows
            entries = []
            for match in re.finditer(r'<td[^>]*>\s*<a[^>]*>([^<]+)</a>\s*</td>\s*<td[^>]*>([^<]*)</td>', html):
                entries.append({"package": match.group(1), "version": match.group(2).strip()})
            return entries
    except:
        return []



class NewQueueMonitorWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("NEW Queue Monitor"), default_width=1000, default_height=700)
        self.settings = _load_settings()
        self._queue = []

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header
        headerbar = Adw.HeaderBar()
        title_widget = Adw.WindowTitle(title=_("NEW Queue Monitor"), subtitle="")
        headerbar.set_title_widget(title_widget)
        self._title_widget = title_widget

        
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Refresh queue"))
        refresh_btn.connect("clicked", self._on_refresh)
        headerbar.pack_start(refresh_btn)
        
        self._search = Gtk.SearchEntry(placeholder_text=_("Filter packages..."))
        self._search.connect("search-changed", self._on_filter)
        headerbar.pack_start(self._search)

        # Menu
        menu = Gio.Menu()
        menu.append(_("Settings"), "app.settings")
        menu.append(_("Copy Debug Info"), "app.copy-debug")
        menu.append(_("Keyboard Shortcuts"), "app.shortcuts")
        menu.append(_("About NEW Queue Monitor"), "app.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        headerbar.pack_end(menu_btn)

        main_box.append(headerbar)

        
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._list.set_margin_start(12)
        self._list.set_margin_end(12)
        self._list.set_margin_top(8)
        self._list.set_margin_bottom(8)
        scroll.set_child(self._list)
        
        self._empty = Adw.StatusPage()
        self._empty.set_icon_name("mail-inbox-symbolic")
        self._empty.set_title(_("NEW Queue"))
        self._empty.set_description(_("Click refresh to fetch the Debian FTP NEW queue."))
        self._empty.set_vexpand(True)
        
        self._stack = Gtk.Stack()
        self._stack.add_named(self._empty, "empty")
        self._stack.add_named(scroll, "list")
        self._stack.set_vexpand(True)
        main_box.append(self._stack)

        # Status bar
        self._status = Gtk.Label(label=_("Ready"), xalign=0)
        self._status.set_margin_start(12)
        self._status.set_margin_end(12)
        self._status.set_margin_top(4)
        self._status.set_margin_bottom(4)
        self._status.add_css_class("dim-label")
        main_box.append(self._status)

        self.set_content(main_box)

        if not self.settings.get("welcome_shown"):
            GLib.idle_add(self._show_welcome)

    def _show_welcome(self):
        dialog = Adw.Dialog()
        dialog.set_title(_("Welcome"))
        dialog.set_content_width(420)
        dialog.set_content_height(480)

        page = Adw.StatusPage()
        page.set_icon_name("mail-inbox-symbolic")
        page.set_title(_("Welcome to NEW Queue Monitor"))
        page.set_description(_("Watch the Debian NEW queue.\n\n"
            "✓ Monitor packages in the FTP NEW queue\n"
            "✓ Desktop notifications on status changes\n"
            "✓ Filter by maintainer or package name\n"
            "✓ History of processed packages\n"
            "✓ Auto-refresh support"))

        btn = Gtk.Button(label=_("Get Started"))
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_margin_top(12)
        btn.connect("clicked", self._on_welcome_close, dialog)
        page.set_child(btn)

        box = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_show_title(False)
        box.add_top_bar(hb)
        box.set_content(page)
        dialog.set_child(box)
        dialog.present(self)

    def _on_welcome_close(self, btn, dialog):
        self.settings["welcome_shown"] = True
        _save_settings(self.settings)
        dialog.close()

    
    def _on_refresh(self, btn):
        self._status.set_text(_("Fetching NEW queue..."))
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        queue = _fetch_new_queue()
        GLib.idle_add(self._show_queue, queue)

    def _show_queue(self, queue):
        self._queue = queue
        self._populate()

    def _populate(self):
        while True:
            row = self._list.get_row_at_index(0)
            if row is None:
                break
            self._list.remove(row)
        
        search = self._search.get_text().lower() if hasattr(self, '_search') else ""
        shown = 0
        for entry in self._queue:
            if search and search not in entry["package"].lower():
                continue
            row = Adw.ActionRow()
            row.set_title(entry["package"])
            row.set_subtitle(entry.get("version", ""))
            self._list.append(row)
            shown += 1
        
        self._stack.set_visible_child_name("list")
        self._status.set_text(_("%(count)d packages in NEW queue") % {"count": shown})

    def _on_filter(self, entry):
        self._populate()


class NewQueueMonitorApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

        for name, callback in [
            ("settings", self._on_settings),
            ("copy-debug", self._on_copy_debug),
            ("shortcuts", self._on_shortcuts),
            ("about", self._on_about),
            ("quit", self._on_quit),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        self.set_accels_for_action("app.quit", ["<Ctrl>q"])
        self.set_accels_for_action("app.shortcuts", ["<Ctrl>slash"])

    def do_activate(self):
        if not self.window:
            self.window = NewQueueMonitorWindow(self)
        self.window.present()

    def _on_settings(self, *_args):
        if not self.window:
            return
        dialog = Adw.PreferencesDialog()
        dialog.set_title(_("Settings"))
        page = Adw.PreferencesPage()
        
        group = Adw.PreferencesGroup(title=_("Monitoring"))
        row = Adw.SwitchRow(title=_("Auto-refresh"))
        group.add(row)
        row2 = Adw.SpinRow.new_with_range(1, 60, 5)
        row2.set_title(_("Refresh interval (minutes)"))
        row2.set_value(10)
        group.add(row2)
        page.add(group)
        dialog.add(page)
        dialog.present(self.window)

    def _on_copy_debug(self, *_args):
        if not self.window:
            return
        from . import __version__
        info = (
            f"NEW Queue Monitor {__version__}\n"
            f"Python {sys.version}\n"
            f"GTK {Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION}\n"
            f"Adw {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}\n"
            f"OS: {os.uname().sysname} {os.uname().release}\n"
        )
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(info)
        self.window._status.set_text(_("Debug info copied"))

    def _on_shortcuts(self, *_args):
        if self.window:
            dialog = Gtk.ShortcutsWindow(transient_for=self.window)
            section = Gtk.ShortcutsSection(visible=True)
            group = Gtk.ShortcutsGroup(title=_("General"), visible=True)
            for accel, title in [
                ("<Ctrl>q", _("Quit")),
                ("<Ctrl>slash", _("Keyboard shortcuts")),
            ]:
                group.append(Gtk.ShortcutsShortcut(accelerator=accel, title=title, visible=True))
            section.append(group)
            dialog.append(section)
            dialog.present()

    def _on_about(self, *_args):
        from . import __version__
        dialog = Adw.AboutDialog(
            application_name=_("NEW Queue Monitor"),
            application_icon="mail-inbox-symbolic",
            version=__version__,
            developer_name="Daniel Nylander",
            website="https://github.com/yeager/new-queue-monitor",
            license_type=Gtk.License.GPL_3_0,
            issue_url="https://github.com/yeager/new-queue-monitor/issues",
            comments=_("Monitor the Debian FTP NEW queue with notifications when packages are accepted or rejected."),
        )
        dialog.present(self.window)

    def _on_quit(self, *_args):
        self.quit()


def main():
    app = NewQueueMonitorApp()
    app.run(sys.argv)


# --- Session restore ---
import json as _json
import os as _os

def _save_session(window, app_name):
    config_dir = _os.path.join(_os.path.expanduser('~'), '.config', app_name)
    _os.makedirs(config_dir, exist_ok=True)
    state = {'width': window.get_width(), 'height': window.get_height(),
             'maximized': window.is_maximized()}
    try:
        with open(_os.path.join(config_dir, 'session.json'), 'w') as f:
            _json.dump(state, f)
    except OSError:
        pass

def _restore_session(window, app_name):
    path = _os.path.join(_os.path.expanduser('~'), '.config', app_name, 'session.json')
    try:
        with open(path) as f:
            state = _json.load(f)
        window.set_default_size(state.get('width', 800), state.get('height', 600))
        if state.get('maximized'):
            window.maximize()
    except (FileNotFoundError, _json.JSONDecodeError, OSError):
        pass


# --- Fullscreen toggle (F11) ---
def _setup_fullscreen(window, app):
    """Add F11 fullscreen toggle."""
    from gi.repository import Gio
    if not app.lookup_action('toggle-fullscreen'):
        action = Gio.SimpleAction.new('toggle-fullscreen', None)
        action.connect('activate', lambda a, p: (
            window.unfullscreen() if window.is_fullscreen() else window.fullscreen()
        ))
        app.add_action(action)
        app.set_accels_for_action('app.toggle-fullscreen', ['F11'])


# --- Plugin system ---
import importlib.util
import os as _pos

def _load_plugins(app_name):
    """Load plugins from ~/.config/<app>/plugins/."""
    plugin_dir = _pos.path.join(_pos.path.expanduser('~'), '.config', app_name, 'plugins')
    plugins = []
    if not _pos.path.isdir(plugin_dir):
        return plugins
    for fname in sorted(_pos.listdir(plugin_dir)):
        if fname.endswith('.py') and not fname.startswith('_'):
            path = _pos.path.join(plugin_dir, fname)
            try:
                spec = importlib.util.spec_from_file_location(fname[:-3], path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                plugins.append(mod)
            except Exception as e:
                print(f"Plugin {fname}: {e}")
    return plugins
