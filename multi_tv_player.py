import sys
import math
from pathlib import Path
from datetime import datetime
import requests
import re
import yaml

import vlc
from screeninfo import get_monitors
from PIL import Image
from pprint import pprint

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QFrame,
    QDialog, QPushButton
)
from PySide6.QtCore import Qt, QTimer, QObject, QEvent
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

# --- Configuration Loading Function ---
def load_config(config_filename="config.yaml", example_config_filename="example_config.yaml"):
    config_path = Path(config_filename)
    example_config_path = Path(example_config_filename)

    if config_path.exists():
        print(f"Loading configuration from {config_filename}")
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    elif example_config_path.exists():
        print(f"Loading configuration from {example_config_filename} (rename it to {config_filename} for custom settings)")
        with open(example_config_path, 'r') as f:
            return yaml.safe_load(f)
    else:
        raise FileNotFoundError(f"Neither {config_filename} nor {example_config_filename} found.")

class MultiPlayerApp(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.setWindowTitle("Multi-TV-player - Videos")
        self.setMinimumSize(640, 480)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.grid_layout = QGridLayout(self.central_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)

        self.is_fullscreen = False
        self.players = []
        self.videos = []
        self.grid_rows = 2
        self.grid_cols = 2

        self.config = config
        self.load_channels_from_url()

        self.stream_groups_numbers = list(self.config['stream_groups'].values())
        self.all_groups_labels = list(self.config['stream_groups'].keys())
        self.stream_groups = [
            [self.channels_by_number[number] for number in group] for group in self.stream_groups_numbers
        ]
        self.current_group_index = 0

        self.instance = vlc.Instance('--quiet', '--network-caching=100', "--aout=directsound")
        self.setup_players(self.stream_groups[self.current_group_index])
        self.showFullScreenOnMonitor(0)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.setWindowFlag(Qt.FramelessWindowHint, False)  # reset frameless
                self.showNormal()
            else:
                self.setWindowFlag(Qt.FramelessWindowHint, True)
                self.showFullScreen()
        else:
            super().keyPressEvent(event)

    def load_channels_from_url(self):
        url = self.config['playlist_url']
        self.channels = {}            # channel_name -> URL
        self.channels_by_number = {}  # channel_number -> (channel_name, URL)

        try:
            response = requests.get(url)
            response.raise_for_status()
            lines = response.text.splitlines()
        except requests.RequestException as e:
            print(f"Error fetching playlist: {e}")
            return

        for i in range(len(lines)):
            line = lines[i].strip()
            if line.startswith('#EXTINF'):
                # Extract channel name
                name_match = line.split(',', 1)
                channel_name = name_match[1].strip() if len(name_match) > 1 else f"Unknown_{i}"

                if 'HD' in channel_name:
                    print(line)

                # Extract channel number using regex (e.g., tvg-chno="101")
                chno_match = re.search(r'tvg-chno="(\d+)"', line)
                channel_number = chno_match.group(1) if chno_match else None

                # Get the URL from the next line
                if i + 1 < len(lines):
                    stream_url = lines[i + 1].strip()
                    self.channels[channel_name] = stream_url
                    if channel_number:
                        self.channels_by_number[channel_number] = (channel_name, stream_url)

    def setup_players(self, streams):
        for player in self.players:
            player.stop()
        for video in self.videos:
            self.grid_layout.removeWidget(video)
            video.deleteLater()
        self.videos.clear()
        self.players.clear()

        num_streams = len(streams)
        if num_streams == 1:
            self.grid_rows, self.grid_cols = 1, 1
        elif num_streams <= 4:
            self.grid_rows, self.grid_cols = 2, 2
        else:
            self.grid_rows, self.grid_cols = 3, 3

        for i, (name,url) in enumerate(streams):
            player = self.instance.media_player_new()
            media = self.instance.media_new(url)
            player.set_media(media)
            self.players.append(player)

            video_widget = QFrame(self)
            video_widget.setStyleSheet("background-color: black; border: none;")
            self.grid_layout.addWidget(video_widget, i // self.grid_cols, i % self.grid_cols)
            self.videos.append(video_widget)
            self.set_vlc_video_widget(player, video_widget)
            player.play()
            player.audio_set_mute(num_streams != 1)

    def set_vlc_video_widget(self, player, widget):
        if sys.platform.startswith('linux'):
            player.set_xwindow(widget.winId())
        elif sys.platform == "win32":
            player.set_hwnd(int(widget.winId()))
        elif sys.platform == "darwin":
            player.set_nsobject(int(widget.winId()))

    def showFullScreenOnMonitor(self, monitor_index):
        monitors = get_monitors()
        if monitor_index >= len(monitors):
            monitor_index = 0

        mon = monitors[monitor_index]
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setGeometry(mon.x, mon.y, mon.width, mon.height)
        self.show()
        self.showFullScreen()

    def switch_group(self, group_index):
        if 0 <= group_index < len(self.stream_groups):
            self.current_group_index = group_index
            self.setup_players(self.stream_groups[group_index])

class ControlsWindow(QDialog):
    def __init__(self, master, players, stream_groups, all_groups_labels):
        super().__init__(master)
        self.setWindowTitle("Multi-TV-player - Controls")
        self.setMinimumSize(600, 200)
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowDoesNotAcceptFocus
            # Qt.WindowStaysOnTopHint
        )
        self.players = players
        self.stream_groups = stream_groups
        self.all_groups_labels = all_groups_labels
        self.master_app = master
        self.sub_states = [True] * len(players)
        self.mute_states = []
        self.layout = QGridLayout(self)
        self.mute_buttons = []
        self.sub_buttons = []
        self.scr_buttons = []

        self.build_controls_ui()
        self.position_middle_right()
        self.show()

        QTimer.singleShot(1000, lambda: self.subs_all_on())

        # Add application-wide shortcuts
        mute_shortcut = QShortcut(QKeySequence("M"), self)
        mute_shortcut.setContext(Qt.ApplicationShortcut)
        mute_shortcut.activated.connect(self.handle_mute_toggle)

        subs_shortcut = QShortcut(QKeySequence("S"), self)
        subs_shortcut.setContext(Qt.ApplicationShortcut)
        subs_shortcut.activated.connect(self.handle_sub_toggle)

        # Number keys 1-9 shortcuts
        for i in range(1, 10):
            key_seq = QKeySequence(str(i))
            num_shortcut = QShortcut(key_seq, self)
            num_shortcut.setContext(Qt.ApplicationShortcut)
            num_shortcut.activated.connect(lambda i=i-1: self.mute_only(i))

    def build_controls_ui(self):
        # Clear previous state
        self.mute_buttons.clear()
        self.sub_buttons.clear()
        self.scr_buttons.clear()
        self.mute_states.clear()

        players_count = len(self.players)
        players_per_row = 2 if players_count <= 4 else 3
        total_rows = math.ceil(players_count / players_per_row)

        # Clear existing widgets
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # Build new controls
        for idx, player in enumerate(self.players):
            row = (idx // players_per_row) * 2
            col = idx % players_per_row

            muted = player.audio_get_mute()
            self.mute_states.append(not muted)
            mute_icon = "🔇" if muted else "🔊"
            mute_text = f"{mute_icon} {idx+1} [{'OFF' if muted else 'ON'}]"
            mute_btn = QPushButton(mute_text)
            mute_btn.clicked.connect(lambda checked, i=idx: self.toggle_mute(i))
            self.layout.addWidget(mute_btn, row, col)
            self.mute_buttons.append(mute_btn)

            sub_btn = QPushButton(f"SUB{idx+1} [---]")
            sub_btn.clicked.connect(lambda checked, i=idx: self.toggle_subtitles(i))
            self.layout.addWidget(sub_btn, row, col + players_per_row)
            self.sub_buttons.append(sub_btn)

            scr_btn = QPushButton(f"📸{idx+1}")
            scr_btn.clicked.connect(lambda checked, i=idx: self.take_screenshot_one(i))
            self.layout.addWidget(scr_btn, row, col + 2 * players_per_row)
            self.scr_buttons.append(scr_btn)

            QTimer.singleShot(1000, lambda i=idx, p=player: self.update_subtitle_state(i, p))

        control_row = total_rows * 2
        for col, (label, slot) in enumerate([
            ("Unmute All", self.unmute_all),
            ("Mute All", self.mute_all),
            ("All Subs ON", self.subs_all_on),
            ("All Subs OFF", self.subs_all_off),
            ("Screenshots", self.take_screenshot_all),
            ("Screenshots Combined", self.take_combined_screenshot)
        ]):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            self.layout.addWidget(btn, control_row, col)

        for i, label in enumerate(self.all_groups_labels):
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, i=i: self.switch_group(i))
            self.layout.addWidget(btn, control_row + 1, i)

    def handle_mute_toggle(self, event=None):
        if not self.players:
            return
        any_unmuted = any(not player.audio_get_mute() for player in self.players)
        if any_unmuted:
            self.mute_all()
        else:
            self.unmute_all()

    def handle_sub_toggle(self, event=None):
        if not self.players:
            return
        any_subs_on = any(self.sub_states)
        if any_subs_on:
            self.subs_all_off()
        else:
            self.subs_all_on()

    def position_middle_right(self):
        screens = QGuiApplication.screens()
        screen = screens[0]  # Always use first/primary monitor
        geometry = screen.geometry()

        self.adjustSize()
        w, h = self.width(), self.height()

        x = geometry.x() + geometry.width() - w - 50
        y = geometry.y() + (geometry.height() - h) // 2

        # self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, False)
        self.move(x, y)

    def unmute_all(self):
        for i, player in enumerate(self.players):
            player.audio_set_mute(False)
            self.mute_buttons[i].setText(f"🔊 {i+1} [ON]")

    def mute_all(self):
        for i, player in enumerate(self.players):
            player.audio_set_mute(True)
            self.mute_buttons[i].setText(f"🔇 {i+1} [OFF]")

    def subs_all_on(self):
        for i, player in enumerate(self.players):
            tracks = player.video_get_spu_description() or []
            for track in tracks:
                track_id = track[0]
                if track_id != -1:
                    player.video_set_spu(track_id)
                    self.sub_states[i] = True
                    self.sub_buttons[i].setText(f"SUB{i+1} [ON]")
                    print(f"Player {i+1}: Subtitles ON track: {track_id}")
                    break

    def subs_all_off(self):
        for i, player in enumerate(self.players):
            player.video_set_spu(-1)
            self.sub_states[i] = False
            self.sub_buttons[i].setText(f"SUB{i+1} [OFF]")
            print(f"Player {i+1}: Subtitles OFF")

    def toggle_mute(self, index):
        player = self.players[index]
        current_mute = player.audio_get_mute()
        player.audio_set_mute(not current_mute)
        self.mute_buttons[index].setText(
            f"{'🔇' if not current_mute else '🔊'} {index+1} [{'OFF' if not current_mute else 'ON'}]"
        )

    def toggle_subtitles(self, index):
        player = self.players[index]
        current_state = self.sub_states[index]

        if current_state:
            # Turn subtitles OFF
            player.video_set_spu(-1)
            self.sub_buttons[index].setText(f"SUB{index+1} [OFF]")
            self.sub_states[index] = False
            print(f"Player {index+1}: Subtitles OFF")
        else:
            # Turn subtitles ON - set first available subtitle track
            tracks = player.video_get_spu_description() or []
            for track in tracks:
                track_id = track[0]
                if track_id != -1:
                    player.video_set_spu(track_id)
                    self.sub_buttons[index].setText(f"SUB{index+1} [ON]")
                    self.sub_states[index] = True
                    print(f"Player {index+1}: Subtitles ON track: {track_id}")
                    break

    def update_subtitle_state(self, i, player):
        current_sub_id = player.video_get_spu()
        if current_sub_id != -1:
            self.sub_states[i] = True
            sub_text = f"SUB{i+1} [ON]"
        else:
            self.sub_states[i] = False
            sub_text = f"SUB{i+1} [OFF]"

        self.sub_buttons[i].setText(sub_text)

    def mute_only(self, index):
        # Mute all except the selected player
        for i, player in enumerate(self.players):
            mute = (i != index)
            player.audio_set_mute(mute)
            self.mute_buttons[i].setText(f"{'🔇' if mute else '🔊'} {i+1} [{'OFF' if mute else 'ON'}]")

    def switch_group(self, index):
        if index == self.master_app.current_group_index:
            print(f"cannot switch group, already in group {index}")
            return

        # Switch group in the main app (which will setup new players)
        self.master_app.switch_group(index)

        # Update self.players to new players list
        self.players = self.master_app.players
        self.sub_states = [True] * len(self.players)
        self.mute_states = []

        self.master_app.current_group_index = index
        current_group = self.stream_groups[index]
        print(f"Switched to group {index}: {current_group}")

        # Rebuild the controls UI for the new players
        self.build_controls_ui()

        # Turn subtitles on for all new players
        QTimer.singleShot(1000, lambda: self.subs_all_on())

    def take_screenshot_one(self, i):
        downloads = Path.home() / "Downloads" / "tvplayer_screenshots"
        downloads.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        channel_number = self.master_app.stream_groups_numbers[self.master_app.current_group_index][i]
        channel_name = self.master_app.channels_by_number[channel_number][0]

        filename = self._generate_safe_filename(channel_name, timestamp)
        filepath = downloads / filename

        if self._take_snapshot(self.players[i], filepath):
            print(f"Screenshot saved for player {i+1} at {filepath}")
        else:
            print(f"Failed to save screenshot for player {i+1}")

    def _generate_safe_filename(self, channel_name, timestamp):
        safe_channel_name = "".join(
            c if c.isalnum() or c in ('-', '_') else "_" for c in channel_name.replace(" ", "_")
        ).rstrip("_")
        return f"{timestamp}_-_{safe_channel_name}.jpg"

    def _take_snapshot(self, player, final_filepath):
        # Save temp PNG
        temp_png = final_filepath.with_suffix('.png')
        result = player.video_take_snapshot(0, str(temp_png), 0, 0) == 0
        if not result or not temp_png.exists():
            return False

        # Convert PNG to JPEG with quality=90 using PIL
        img = Image.open(temp_png)
        img.convert("RGB").save(final_filepath, "JPEG", quality=90)

        # Remove temp PNG
        temp_png.unlink()
        return True

    def take_screenshot_all(self):
        downloads = Path.home() / "Downloads" / "tvplayer_screenshots"
        downloads.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        for i, player in enumerate(self.players):
            channel_number = self.master_app.stream_groups_numbers[self.master_app.current_group_index][i]
            channel_name = self.master_app.channels_by_number[channel_number][0]
            filename = self._generate_safe_filename(channel_name, timestamp)
            filepath = downloads / filename

            if self._take_snapshot(player, filepath):
                print(f"Screenshot saved for player {i+1} at {filepath}")
            else:
                print(f"Failed to save screenshot for player {i+1}")

    def take_combined_screenshot(self):
        downloads = Path.home() / "Downloads" / "tvplayer_screenshots"
        downloads.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        snapshots = []
        temp_files = []

        for i, player in enumerate(self.players):
            channel_number = self.master_app.stream_groups_numbers[self.master_app.current_group_index][i]
            channel_name = self.master_app.channels_by_number[channel_number][0]
            filename = self._generate_safe_filename(channel_name, timestamp)
            filepath = downloads / filename

            success = self._take_snapshot(player, filepath)
            if success:
                img = Image.open(filepath)
                snapshots.append(img)
                temp_files.append(filepath)
            else:
                print(f"Failed to take snapshot for player {i+1}, skipping...")

        if not snapshots:
            print("No snapshots to combine.")
            return

        num_images = len(snapshots)
        cols = getattr(self.master_app, "grid_cols", 3)
        rows = (num_images + cols - 1) // cols

        # If only one snapshot, just keep original file and remove temp files cleanup is not needed
        if num_images == 1:
            print(f"Only one snapshot. Screenshot saved at {temp_files[0]}")
            return

        width, height = snapshots[0].size
        combined_img = Image.new('RGB', (width * cols, height * rows))

        for idx, img in enumerate(snapshots):
            x = (idx % cols) * width
            y = (idx // cols) * height
            combined_img.paste(img, (x, y))

        combined_filename = downloads / f"{timestamp}_combined_grid.jpg"
        combined_img.save(combined_filename, "JPEG", quality=90)

        # Delete individual snapshot files after combining
        for file_path in temp_files:
            try:
                file_path.unlink()
            except Exception as e:
                print(f"Failed to delete temp file {file_path}: {e}")

        print(f"Combined screenshot saved at {combined_filename}")


if __name__ == "__main__":
    # --- Load Configuration ---
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    app = QApplication(sys.argv)
    main_app = MultiPlayerApp(config)
    main_app.show()

    stream_groups_numbers = list(config['stream_groups'].values())
    all_groups_labels = list(config['stream_groups'].keys())

    controls = ControlsWindow(main_app, main_app.players, stream_groups_numbers, all_groups_labels)
    controls.show()

    # Connect closing controls window to quit the whole app
    controls.finished.connect(app.quit)
    controls.rejected.connect(app.quit)

    sys.exit(app.exec())