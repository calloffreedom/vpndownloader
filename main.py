#!/usr/bin/env python3

# F4S VPN Downloader — with OS override and extra features
# Corrected and improved by Gemini

# Requires: PyGObject (Gtk4, Adw), requests

import gi
import threading
import requests
import os
import re
import time
import platform
import subprocess
from urllib.parse import urlparse, unquote
from pathlib import Path
from email.utils import parsedate_to_datetime

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib



Adw.init()

# The second URL is a potential fallback for a typo
DEFAULT_MIRRORS_JSON_URLS = (
    "https://web.archive.org/web/2im_/https://raw.githubusercontent.com/calloffreedom/vpndownloader/refs/heads/main/mirrors.json",
    "https://web.archive.org/web/2im_/https://calloffreedom.github.io/vpndownloader/mirrors.json",
    "https://raw.githubusercontent.com/calloffreedom/vpndownloader/refs/heads/main/mirrors.json",
    "https://calloffreedom.github.io/vpndownloader/mirrors.json"
)

DOWNLOAD_DIR = Path(os.environ.get("XDG_DOWNLOAD_DIR", Path.home() / "Downloads"))

OS_CHOICES = ["Windows", "macOS", "Linux"]

# A list of predefined mirror lists.
PREDEFINED_MIRROR_LISTS = {}
index = 0
for i in DEFAULT_MIRRORS_JSON_URLS:
	PREDEFINED_MIRROR_LISTS[DEFAULT_MIRRORS_JSON_URLS[index]] = DEFAULT_MIRRORS_JSON_URLS[index]
	index += 1


def safe_filename_from_cd(cd):
    """
    Safely extract a filename from a Content-Disposition header.
    Handles both filename="file.txt" and filename*=UTF-8''file.txt formats.
    """
    if not cd:
        return None
    # RFC 6266, for UTF-8 filenames
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    if m:
        return os.path.basename(unquote(m.group(1)))
    # Fallback for standard filename attribute
    m = re.search(r'filename=\"?([^\";]+)\"?', cd)
    if m:
        return os.path.basename(m.group(1))
    return None


def _safe_get_os():
    """Returns the current OS in a standardized string format."""
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    return system


class Downloader(Gtk.Box):
    def __init__(self):
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        self.session = requests.Session()
        self.current_download_thread = None
        self.should_cancel = False
        self.user_os = _safe_get_os()
        self.mirror_data = {}

        # Mirror list dropdown
        self.append(Gtk.Label(label="Select Mirror List:", halign=Gtk.Align.START))
        self.mirror_dropdown = Gtk.DropDown()
        self.mirror_dropdown.connect("notify::selected-item", self.on_mirror_list_changed)
        self.append(self.mirror_dropdown)

        # Download dropdown
        self.append(Gtk.Label(label="Select Download:", halign=Gtk.Align.START))
        self.download_dropdown = Gtk.DropDown()
        self.append(self.download_dropdown)

        # Action buttons
        button_box = Gtk.Box(spacing=6, orientation=Gtk.Orientation.HORIZONTAL)
        self.download_button = Gtk.Button(label="Download Selected")
        self.download_button.connect("clicked", self.on_download_clicked)
        self.download_button.set_sensitive(False)
        button_box.append(self.download_button)

        self.cancel_button = Gtk.Button(label="Cancel")
        self.cancel_button.connect("clicked", self.on_cancel_clicked)
        self.cancel_button.set_sensitive(False)
        button_box.append(self.cancel_button)
        self.append(button_box)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Progress and status display
        self.status_label = Gtk.Label(label="Idle", halign=Gtk.Align.START, wrap=True)
        self.append(self.status_label)
        self.progress_bar = Gtk.ProgressBar()
        self.append(self.progress_bar)
        self.progress_text = Gtk.Label(label="", halign=Gtk.Align.START)
        self.append(self.progress_text)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Log view
        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView(buffer=self.log_buffer, editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroller = Gtk.ScrolledWindow(min_content_height=150)
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.log_view)
        self.append(scroller)

        # Log action buttons
        log_buttons_box = Gtk.Box(spacing=6, orientation=Gtk.Orientation.HORIZONTAL)
        self.clear_logs_button = Gtk.Button(label="Clear Logs")
        self.clear_logs_button.connect("clicked", lambda *_: self.log_buffer.set_text(""))
        log_buttons_box.append(self.clear_logs_button)

        self.open_folder_button = Gtk.Button(label="Open Downloads Folder")
        self.open_folder_button.connect("clicked", self.open_downloads_folder)
        log_buttons_box.append(self.open_folder_button)
        self.append(log_buttons_box)

        self.append(Gtk.Label(label=f"Downloads saved to: {DOWNLOAD_DIR}", halign=Gtk.Align.START, selectable=True))

    def append_log(self, text):
        GLib.idle_add(self._do_append_log, text)

    def _do_append_log(self, text):
        end_iter = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end_iter, f"{time.strftime('%H:%M:%S')}: {text}\n")
        # Auto-scroll to the end
        mark = self.log_buffer.create_mark(None, self.log_buffer.get_end_iter(), False)
        self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        return False

    def set_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def set_progress(self, fraction, text=None):
        GLib.idle_add(self._do_set_progress, fraction, text)

    def _do_set_progress(self, fraction, text):
        self.progress_bar.set_fraction(max(0.0, min(1.0, fraction)))
        if text is not None:
            self.progress_text.set_text(text)
        return False

    def set_buttons_for_download(self, is_downloading):
        GLib.idle_add(self._do_set_buttons, is_downloading)

    def _do_set_buttons(self, is_downloading):
        self.download_button.set_sensitive(not is_downloading)
        self.cancel_button.set_sensitive(is_downloading)
        return False

    def _update_dropdown(self, dropdown: Gtk.DropDown, keys: list):
        model = Gtk.StringList.new(keys)
        dropdown.set_model(model)
        has_options = bool(keys)
        if has_options:
            dropdown.set_selected(0)
        # The download button should only be sensitive if both dropdowns have options
        self.download_button.set_sensitive(bool(self.mirror_dropdown.get_selected_item()) and bool(self.download_dropdown.get_selected_item()))

    def update_mirror_dropdown(self, available_keys: list):
        GLib.idle_add(self._update_dropdown, self.mirror_dropdown, available_keys)

    def update_download_dropdown(self, available_keys: list):
        GLib.idle_add(self._update_dropdown, self.download_dropdown, available_keys)

    def on_mirror_list_changed(self, dropdown, _):
        """Handler to update the download list when the mirror list changes."""
        selected_item = dropdown.get_selected_item()
        if not selected_item or not self.mirror_data:
            self.update_download_dropdown([])
            return
        
        mirror_list_name = selected_item.get_string()
        if mirror_list_name in self.mirror_data:
            download_keys = []
            for key, downloads in self.mirror_data[mirror_list_name].items():
                # Check if the download is available for the current OS
                if isinstance(downloads, dict) and self.user_os in downloads:
                    download_keys.append(key)
                elif isinstance(downloads, list):
                    # If it's a list, it's not OS-specific, so it's always available
                    download_keys.append(key)

            self.update_download_dropdown(download_keys)
        else:
            self.update_download_dropdown([])

    def open_downloads_folder(self, *args):
        try:
            if platform.system() == "Windows":
                os.startfile(DOWNLOAD_DIR)
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(DOWNLOAD_DIR)], check=True)
            else:
                subprocess.run(["xdg-open", str(DOWNLOAD_DIR)], check=True)
        except Exception as e:
            self.append_log(f"Could not open folder: {e}")

    def on_download_clicked(self, button):
        selected_mirror_item = self.mirror_dropdown.get_selected_item()
        selected_download_item = self.download_dropdown.get_selected_item()
        if not selected_mirror_item or not selected_download_item:
            self.append_log("Please select a mirror list and a download.")
            self.set_status("No mirror list or download selected.")
            return

        if self.current_download_thread and self.current_download_thread.is_alive():
            self.append_log("A download is already in progress.")
            return

        mirror_list_name = selected_mirror_item.get_string()
        download_key = selected_download_item.get_string()

        self.set_status(f"Preparing to download {download_key}...")
        self.append_log(f"Starting download for: {download_key} ({self.user_os})")
        self.should_cancel = False
        self.set_buttons_for_download(is_downloading=True)
        self.set_progress(0.0, "")

        self.current_download_thread = threading.Thread(
            target=self.fetch_and_download,
            args=(mirror_list_name, download_key),
            daemon=True
        )
        self.current_download_thread.start()

    def on_cancel_clicked(self, button):
        self.append_log("Cancel request sent.")
        self.should_cancel = True
        self.set_status("Cancelling download...")
        button.set_sensitive(False) # Prevent multiple clicks

    def fetch_and_download(self, mirror_list_name, download_key):
        try:
            # Get the mirrors for the selected download. This could be a dict or a list.
            mirrors_for_download = self.mirror_data.get(mirror_list_name, {}).get(download_key)
            
            os_specific_mirrors = []
            if isinstance(mirrors_for_download, dict):
                # If it's a dictionary, get the list for the current OS.
                os_specific_mirrors = mirrors_for_download.get(self.user_os, [])
            elif isinstance(mirrors_for_download, list):
                # If it's already a list, use it directly (not OS-specific).
                os_specific_mirrors = mirrors_for_download
            
            if not os_specific_mirrors:
                self.append_log(f"No mirrors found for '{download_key}' on {self.user_os}.")
                self.set_status(f"No mirrors available for {download_key} on {self.user_os}.")
                self.set_buttons_for_download(is_downloading=False)
                return

            self.append_log(f"Found {len(os_specific_mirrors)} mirror(s). Trying in order.")
            download_successful = False
            for idx, url in enumerate(os_specific_mirrors, start=1):
                if self.should_cancel:
                    self.append_log("Download cancelled by user.")
                    break
                self.set_status(f"Trying mirror {idx}/{len(os_specific_mirrors)}: {urlparse(url).netloc}")
                if self.try_download_from_url(url):
                    download_successful = True
                    self.append_log(f"Success from: {url}")
                    self.set_status(f"Successfully downloaded {download_key}!")
                    break
                else:
                    if not self.should_cancel:
                        self.append_log(f"Mirror failed: {url}")

            if self.should_cancel:
                self.set_status("Download cancelled.")
            elif not download_successful:
                self.set_status("All mirrors failed for the selected download.")
                self.append_log("All mirrors failed.")
        except Exception as e:
            self.append_log(f"An unexpected error occurred: {e}")
            self.set_status("Error during download process.")
        finally:
            self.set_buttons_for_download(is_downloading=False)

    def try_download_from_url(self, url):
        try:
            with self.session.get(url, stream=True, timeout=20) as r:
                r.raise_for_status()
                filename = safe_filename_from_cd(r.headers.get("Content-Disposition")) or \
                           os.path.basename(urlparse(url).path) or \
                           "downloaded_file"

                filepath = DOWNLOAD_DIR / filename
                tmp_filepath = filepath.with_suffix(filepath.suffix + ".part")
                total_size = int(r.headers.get("Content-Length", 0))
                downloaded = 0
                
                self.append_log(f"Downloading '{filename}' from {urlparse(url).netloc}")
                with open(tmp_filepath, "wb") as f:
                    start_time = time.time()
                    for chunk in r.iter_content(chunk_size=8192):
                        if self.should_cancel:
                            tmp_filepath.unlink(missing_ok=True)
                            return False
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            elapsed = time.time() - start_time
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            frac = downloaded / total_size if total_size > 0 else 0
                            size_str = f"{downloaded / 1_048_576:.2f} MB"
                            total_str = f"{total_size / 1_048_576:.2f} MB"
                            progress_text = f"{size_str} / {total_str} ({self._format_speed(speed)})"
                            self.set_progress(frac, progress_text)

                # Rename partial file to final name
                tmp_filepath.rename(filepath)
                
                # Preserve server's last-modified timestamp if available
                lm_header = r.headers.get("Last-Modified")
                if lm_header:
                    try:
                        dt = parsedate_to_datetime(lm_header)
                        mod_time = dt.timestamp()
                        os.utime(filepath, (mod_time, mod_time))
                    except Exception as e:
                        self.append_log(f"Warning: Could not set file modification time: {e}")
                return True
        except requests.RequestException as e:
            self.append_log(f"Network error: {e}")
        except IOError as e:
            self.append_log(f"File error: {e}")
        except Exception as e:
            self.append_log(f"Unexpected download error: {e}")
        return False

    @staticmethod
    def _format_speed(bytes_per_sec):
        if bytes_per_sec > 1_000_000:
            return f"{bytes_per_sec / 1_000_000:.2f} MB/s"
        if bytes_per_sec > 1_000:
            return f"{bytes_per_sec / 1_000:.2f} KB/s"
        return f"{bytes_per_sec:.0f} B/s"


class SettingsTab(Gtk.Box):
    def __init__(self, on_mirror_url_changed, on_os_override_changed, current_url, current_os):
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        self.on_mirror_url_changed = on_mirror_url_changed
        self.on_os_override_changed = on_os_override_changed
        self.predefined_mirror_list_urls = PREDEFINED_MIRROR_LISTS

        # Section for Predefined Mirror Lists
        self.append(
            Gtk.Label(label="Mirror List to Use:", halign=Gtk.Align.START, css_classes=["title-4"])
        )
        predefined_mirrors_model = Gtk.StringList.new(list(self.predefined_mirror_list_urls.keys()))
        self.predefined_mirror_dropdown = Gtk.DropDown(model=predefined_mirrors_model)
        self.predefined_mirror_dropdown.connect("notify::selected-item", self.on_predefined_mirror_changed)

        # Wrap dropdown in a box with fixed width to limit dropdown width
        mirror_box = Gtk.Box()
        mirror_box.set_size_request(150, -1)  # fix width to 150px, height unlimited
        mirror_box.append(self.predefined_mirror_dropdown)
        self.append(mirror_box)

        # Section for Custom Mirror URL
        self.mirror_url_entry = Gtk.Entry(text=current_url)
        self.mirror_url_entry.connect("activate", self.on_reload_clicked)
        # self.append(self.mirror_url_entry)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # OS Override section
        self.append(
            Gtk.Label(label="Override OS for Downloads:", halign=Gtk.Align.START, css_classes=["title-4"])
        )
        self.os_override_dropdown = Gtk.DropDown.new_from_strings(["Auto-detect"] + OS_CHOICES)
        if current_os and current_os in OS_CHOICES:
            self.os_override_dropdown.set_selected(OS_CHOICES.index(current_os) + 1)
        else:
            self.os_override_dropdown.set_selected(0)
        self.os_override_dropdown.connect("notify::selected-item", self.on_os_dropdown_changed)

        # Wrap OS dropdown in fixed-width box too
        os_box = Gtk.Box()
        os_box.set_size_request(150, -1)  # fix width to 150px
        os_box.append(self.os_override_dropdown)
        self.append(os_box)

        self.sync_entry_with_predefined_dropdown()

    def on_predefined_mirror_changed(self, dropdown, _):
        selected_item = dropdown.get_selected_item()
        if selected_item:
            name = selected_item.get_string()
            url = self.predefined_mirror_list_urls.get(name)
            self.mirror_url_entry.set_text(url)
            self.on_mirror_url_changed(url)

    def on_reload_clicked(self, _):
        url = self.mirror_url_entry.get_text().strip()
        if url:
            self.on_mirror_url_changed(url)

    def on_os_dropdown_changed(self, dropdown, _):
        selected_idx = dropdown.get_selected()
        if selected_idx == 0:
            self.on_os_override_changed(None)  # Auto-detect
        else:
            self.on_os_override_changed(OS_CHOICES[selected_idx - 1])

    def sync_entry_with_predefined_dropdown(self):
        """Finds the current URL in the predefined list and sets the dropdown selection."""
        urls = list(self.predefined_mirror_list_urls.values())
        try:
            idx = urls.index(self.mirror_url_entry.get_text())
            self.predefined_mirror_dropdown.set_selected(idx)
        except ValueError:
            # The current URL is not in the predefined list, do nothing
            pass


class VPNInstallerWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, default_width=600, default_height=700)
        self.set_resizable(False)
        self.mirrors_data = {}
        self.current_mirror_url = DEFAULT_MIRRORS_JSON_URLS[0]
        self.os_override = None

        # --- Main Vertical Box Container ---
        # This box will hold the header bar and the main content stack.
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_vbox) # Set this as the window's single child widget.

        # --- Header Bar Setup ---
        # The header is now a regular widget at the top of the main_vbox.
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="F4S VPN Downloader", subtitle="By Call of Freedom"))
        main_vbox.append(header)

        about_button = Gtk.Button.new_from_icon_name("help-about-symbolic")
        about_button.set_tooltip_text("About")
        about_button.connect("clicked", self.on_about_clicked)
        header.pack_end(about_button)

        # --- Main Content Area (using a Stack) ---
        # The stack is added below the header, and set to expand to fill the window.
        self.main_stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            vexpand=True
        )
        main_vbox.append(self.main_stack)

        # 1. Loading page
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        spinner = Gtk.Spinner(spinning=True, height_request=48, width_request=48)
        loading_box.append(spinner)
        loading_box.append(Gtk.Label(label="Fetching mirror information..."))
        self.main_stack.add_named(loading_box, "loading")

        # 2. Error page
        self.error_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        error_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        error_icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
        error_icon.set_pixel_size(48)
        error_box.append(error_icon)
        error_box.append(self.error_label)
        self.main_stack.add_named(error_box, "error")

        # 3. Main content page (will be created after mirrors load)
        self.notebook = None
        self.download_tab = None
        self.settings_tab = None

        self.main_stack.set_visible_child_name("loading")
        self.load_initial_mirrors()

    def on_about_clicked(self, *_):
        dialog = Gtk.AboutDialog(transient_for=self)
        dialog.set_program_name("F4S VPN Downloader")
        dialog.set_version("1.0")
        #dialog.set_developer("Call of Freedom")
        dialog.set_comments("Download VPN clients and Tor Browser using reliable mirrors.")
        dialog.set_website("https://github.com/calloffreedom/vpndownloader")
        dialog.set_logo_icon_name("network-vpn-symbolic")
        dialog.present()

    def load_initial_mirrors(self):
        """Try fetching from default mirror URLs on startup."""
        def _fetch():
            last_error = None
            for url in DEFAULT_MIRRORS_JSON_URLS:
                try:
                    r = requests.get(url, timeout=10)
                    r.raise_for_status()
                    data = r.json()
                    self.current_mirror_url = url
                    GLib.idle_add(self.on_mirrors_loaded, data)
                    return
                except Exception as e:
                    last_error = e
            GLib.idle_add(self.on_mirrors_failed, last_error)
        threading.Thread(target=_fetch, daemon=True).start()

    def on_mirrors_loaded(self, data):
        self.mirrors_data = data
        if not self.notebook:
            self.download_tab = Downloader()
            self.settings_tab = SettingsTab(
                on_mirror_url_changed=self.reload_from_url,
                on_os_override_changed=self.set_os_override,
                current_url=self.current_mirror_url,
                current_os=self.os_override,
            )
            self.notebook = Gtk.Notebook()
            self.notebook.append_page(self.download_tab, Gtk.Label(label="Download"))
            self.notebook.append_page(self.settings_tab, Gtk.Label(label="Settings"))
            self.main_stack.add_named(self.notebook, "main_content")

        # Update data in existing widgets
        self.download_tab.mirror_data = data
        self.download_tab.user_os = self.os_override or _safe_get_os()
        self.settings_tab.mirror_url_entry.set_text(self.current_mirror_url)

        # Repopulate dropdowns
        mirror_keys = list(data.keys())
        self.download_tab.update_mirror_dropdown(mirror_keys)

        self.main_stack.set_visible_child_name("main_content")
        return False

    def on_mirrors_failed(self, error):
        self.error_label.set_text(f"Failed to load initial mirror list.\nPlease check your connection and restart.\n\nDetails: {error}")
        self.main_stack.set_visible_child_name("error")
        return False

    def reload_from_url(self, url):
        self.download_tab.set_status("Reloading mirrors...")
        self.download_tab.append_log(f"Attempting to reload mirrors from: {url}")
        
        def _fetch():
            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                data = r.json()
                self.current_mirror_url = url
                GLib.idle_add(self.on_mirrors_loaded, data)
            except Exception as e:
                GLib.idle_add(self.on_reload_failed, url, e)
        threading.Thread(target=_fetch, daemon=True).start()

    def on_reload_failed(self, url, error):
        self.download_tab.append_log(f"Failed to load mirrors from {url}: {error}")
        self.download_tab.set_status(f"Failed to reload from new URL.")
        return False

    def set_os_override(self, os_name):
        self.os_override = os_name
        if self.download_tab:
            new_os = os_name or _safe_get_os()
            self.download_tab.user_os = new_os
            self.download_tab.append_log(f"OS for downloads set to: {new_os}")
            
            # Now that the OS has changed, we must update the download list
            # to only show compatible files. We do this by triggering the mirror
            # list's changed signal.
            selected_mirror_item = self.download_tab.mirror_dropdown.get_selected_item()
            if selected_mirror_item:
                self.download_tab.on_mirror_list_changed(self.download_tab.mirror_dropdown, None)

class VPNInstallerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="nz.calloffreedom.vpndownloader", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        win = self.props.active_window or VPNInstallerWindow(self)
        win.present()


if __name__ == "__main__":
    app = VPNInstallerApp()
    raise SystemExit(app.run(None))
