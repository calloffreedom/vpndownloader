import gi
import threading
import requests
import os
from urllib.parse import urlparse
from gi.repository import Gtk, Adw, Gio, GLib

Adw.init()

DEFAULT_MIRRORS_JSON_URL = "https://example.com/f4s-mirrors.json"  # Replace with real URL
DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

class Downloader(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)

        self.mirror_url = DEFAULT_MIRRORS_JSON_URL

        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("Mirrors JSON URL")
        self.url_entry.set_text(self.mirror_url)
        self.append(self.url_entry)

        self.update_url_button = Gtk.Button(label="Set Mirror URL")
        self.update_url_button.connect("clicked", self.update_mirror_url)
        self.append(self.update_url_button)

        self.status_label = Gtk.Label(label="Idle", xalign=0)
        self.append(self.status_label)

        self.progress_bar = Gtk.ProgressBar(show_text=True)
        self.append(self.progress_bar)

        buttons = [
            ("Download ProtonVPN", "protonvpn"),
            ("Download X-VPN", "xvpn"),
            ("Download Tor Browser", "tor")
        ]

        for label, key in buttons:
            button = Gtk.Button(label=label)
            button.connect("clicked", self.on_download_clicked, key)
            self.append(button)

    def update_mirror_url(self, button):
        self.mirror_url = self.url_entry.get_text()
        self.status_label.set_text(f"Mirror URL set to: {self.mirror_url}")

    def on_download_clicked(self, button, key):
        self.status_label.set_text(f"Fetching mirrors for {key}...")
        threading.Thread(target=self.fetch_and_download, args=(key,), daemon=True).start()

    def fetch_and_download(self, key):
        try:
            resp = requests.get(self.mirror_url)
            mirror_data = resp.json()
            urls = mirror_data.get(key, [])
            if not urls:
                GLib.idle_add(self.status_label.set_text, f"No mirrors available for {key}.")
                return
            
            for url in urls:
                success = self.try_download(url)
                if success:
                    GLib.idle_add(self.status_label.set_text, f"Downloaded {key} from {url}")
                    return
            GLib.idle_add(self.status_label.set_text, f"Failed to download {key} from all mirrors.")

        except Exception as e:
            GLib.idle_add(self.status_label.set_text, f"Error: {str(e)}")

    def try_download(self, url):
        try:
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path)
            dest_path = os.path.join(DOWNLOAD_DIR, filename)
            with requests.get(url, stream=True, timeout=10) as r:
                r.raise_for_status()
                total = int(r.headers.get('content-length', 0))
                downloaded = 0
                chunk_size = 8192
                with open(dest_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            progress = downloaded / total if total else 0
                            GLib.idle_add(self.progress_bar.set_fraction, progress)
                            GLib.idle_add(self.progress_bar.set_text, f"{int(progress * 100)}%")
            return True
        except Exception as e:
            return False

class F4SWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("F4S VPN Downloader")
        self.set_default_size(400, 300)

        self.set_content(Downloader())

class F4SApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="nz.f4s.VPNDownloader", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = F4SWindow(self)
        win.present()

if __name__ == '__main__':
    app = F4SApp()
    app.run()
