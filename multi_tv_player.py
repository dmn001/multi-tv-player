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

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QFrame,
    QDialog, QPushButton, QHBoxLayout, QVBoxLayout, QLabel,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect
)
from PySide6.QtCore import (
    Qt, QTimer, QObject, QEvent, QPropertyAnimation, QPoint,
    QParallelAnimationGroup, QRect, Signal
)
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, QKeyEvent, QCursor, QPainter

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


class OutlinedLabel(QLabel):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        text = self.text()
        rect = self.rect()
        align = self.alignment()
        
        painter.setPen(Qt.black)
        painter.setFont(self.font())
        
        outline_width = 3
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx == 0 and dy == 0:
                    continue
                painter.drawText(rect.translated(dx, dy), align, text)
                
        painter.end()
        super().paintEvent(event)


class ChannelOverlay(QWidget):
    playing_signal = Signal()

    def __init__(self, master_app, target_widget, channel_number):
        super().__init__(master_app)
        self.target_widget = target_widget
        self.playing_signal.connect(self.show_number)
        
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background-color: transparent;")
        
        self.setFixedSize(200, 140)
        self.setWindowOpacity(1.0)
        
        # Clip widget acts as the window blind pulling down
        self.clip_widget = QWidget(self)
        self.clip_widget.setAttribute(Qt.WA_TranslucentBackground, True)
        self.clip_widget.setStyleSheet("background-color: transparent;")
        self.clip_widget.setGeometry(20, 20, 180, 100)
        
        self.label = OutlinedLabel(str(channel_number), self.clip_widget)
        self.label.setGeometry(0, 0, 180, 100)
        self.label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        self.label.setStyleSheet("""
            QLabel {
                background-color: transparent;
                color: #f7d04f;
                font-family: 'Arial Rounded MT Bold', 'Helvetica Rounded', 'Arial Black', sans-serif;
                font-size: 72px;
                font-weight: bold;
            }
        """)
        
        self.anim_group = QParallelAnimationGroup(self)
        
        self.anim_clip = QPropertyAnimation(self.clip_widget, b"geometry")
        self.anim_clip.setDuration(1600)
        
        self.anim_label = QPropertyAnimation(self.label, b"geometry")
        self.anim_label.setDuration(1600)
        
        self.anim_group.addAnimation(self.anim_clip)
        self.anim_group.addAnimation(self.anim_label)
        self.anim_group.finished.connect(self.hide)
        
        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(2000)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.start_wipe)
        
    def start_wipe(self):
        self.anim_clip.setStartValue(QRect(20, 20, 180, 100))
        self.anim_clip.setEndValue(QRect(20, 120, 180, 0))
        
        self.anim_label.setStartValue(QRect(0, 0, 180, 100))
        self.anim_label.setEndValue(QRect(0, -100, 180, 100))
        
        self.anim_group.start()
        
    def update_position(self):
        if not self.target_widget.isVisible() or self.target_widget.width() == 0:
            return
        top_left = self.target_widget.mapToGlobal(QPoint(50, 0))
        self.move(top_left)

    def show_number(self):
        if not self.target_widget.isVisible() or self.target_widget.width() == 0:
            return
            
        self.anim_group.stop()
        self.clip_widget.setGeometry(20, 20, 180, 100)
        self.label.setGeometry(0, 0, 180, 100)
        self.setWindowOpacity(1.0)
        self.update_position()
        self.show()
        self.raise_()
        self.hide_timer.start()

    def attach_player(self, player):
        self.player = player
        self.em = self.player.event_manager()
        # Keep a strong reference to the callback to prevent garbage collection
        self._on_playing_cb = lambda e: self.playing_signal.emit()
        self.em.event_attach(vlc.EventType.MediaPlayerPlaying, self._on_playing_cb)


class MuteOverlay(ChannelOverlay):
    def __init__(self, master_app, target_widget):
        super().__init__(master_app, target_widget, "")
        try:
            self.playing_signal.disconnect()
        except:
            pass
            
        # Re-apply stylesheet with smaller font for text instead of emoji
        self.label.setStyleSheet("""
            QLabel {
                background-color: transparent;
                color: #f7d04f;
                font-family: 'Arial Rounded MT Bold', 'Helvetica Rounded', 'Arial Black', sans-serif;
                font-size: 48px;
                font-weight: bold;
            }
        """)
            
    def show_icon(self, icon_str):
        self.label.setText(icon_str)
        self.show_number()
        
    def update_position(self):
        if not hasattr(self, 'target_widget') or not self.target_widget.isVisible() or self.target_widget.width() == 0:
            return
            
        top_left = self.target_widget.mapToGlobal(QPoint(50, 0))
        x, y = top_left.x(), top_left.y()
        self.move(x, y)


class OverlayControls(QWidget):
    def __init__(self, master_app, target_widget, player, index):
        super().__init__(master_app)
        self.master_app = master_app
        self.target_widget = target_widget
        self.player = player
        self.index = index
        
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        self.setFixedSize(320, 50)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        btn_style = """
            QPushButton {
                background-color: rgba(30, 30, 30, 220);
                border-radius: 5px;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: rgba(70, 70, 70, 255);
                color: #00FF00;
            }
        """
        
        self.mute_btn = QPushButton("🔊 [ON]")
        self.mute_btn.setStyleSheet(btn_style)
        self.mute_btn.clicked.connect(self.toggle_mute)
        
        self.sub_btn = QPushButton("SUB [OFF]")
        self.sub_btn.setStyleSheet(btn_style)
        self.sub_btn.clicked.connect(self.toggle_subtitles)
        
        self.scr_btn = QPushButton("📸")
        self.scr_btn.setStyleSheet(btn_style)
        self.scr_btn.clicked.connect(self.take_screenshot)
        
        self.fs_btn = QPushButton("🔲")
        self.fs_btn.setStyleSheet(btn_style)
        self.fs_btn.clicked.connect(self.toggle_fullscreen)
        
        layout.addWidget(self.mute_btn)
        layout.addWidget(self.sub_btn)
        layout.addWidget(self.scr_btn)
        layout.addWidget(self.fs_btn)
        
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(250)
        self.anim.finished.connect(self._on_anim_finished)
        self.setWindowOpacity(0.0)
        
        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(1500)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)
        
        self.sub_state = False

    def toggle_mute(self):
        current_mute = self.player.audio_get_mute()
        is_muted = not current_mute
        self.set_mute_ui(is_muted)
        
        text = "MUTE" if is_muted else "VOL"
        if hasattr(self.master_app, 'mute_overlays') and self.index < len(self.master_app.mute_overlays):
            self.master_app.mute_overlays[self.index].show_icon(text)

    def set_mute_ui(self, muted):
        self.player.audio_set_mute(muted)
        self.mute_btn.setText(f"{'🔇' if muted else '🔊'} [{'OFF' if muted else 'ON'}]")

    def toggle_subtitles(self):
        self.set_subtitles(not self.sub_state)

    def set_subtitles(self, state):
        if state:
            tracks = self.player.video_get_spu_description() or []
            for track in tracks:
                track_id = track[0]
                if track_id != -1:
                    self.player.video_set_spu(track_id)
                    self.sub_btn.setText(f"SUB [ON]")
                    self.sub_state = True
                    print(f"Player {self.index+1}: Subtitles ON track: {track_id}")
                    break
        else:
            self.player.video_set_spu(-1)
            self.sub_btn.setText(f"SUB [OFF]")
            self.sub_state = False
            print(f"Player {self.index+1}: Subtitles OFF")

    def check_sub_state(self):
        # Called after a delay to sync state
        current_sub_id = self.player.video_get_spu()
        if current_sub_id != -1:
            self.sub_state = True
            self.sub_btn.setText("SUB [ON]")
        else:
            self.sub_state = False
            self.sub_btn.setText("SUB [OFF]")

    def take_screenshot(self):
        self.master_app.take_screenshot_one(self.index)

    def toggle_fullscreen(self):
        self.master_app.toggle_single_fullscreen(self.index)

    def update_position(self):
        if not self.target_widget.isVisible() or self.target_widget.width() == 0:
            return
        
        rect = self.target_widget.geometry()
        top_left = self.target_widget.mapToGlobal(QPoint(0, 0))
        
        x = top_left.x() + (rect.width() - self.width()) // 2
        y = top_left.y() + rect.height() - self.height() - 20
        self.move(x, y)

    def fade_in(self):
        self.hide_timer.stop()
        self.update_position()
        self.show()
        self.raise_()
        
        is_fading_in = self.anim.state() == QPropertyAnimation.Running and self.anim.endValue() == 1.0
        if self.windowOpacity() < 1.0 and not is_fading_in:
            self.anim.stop()
            self.anim.setStartValue(self.windowOpacity())
            self.anim.setEndValue(1.0)
            self.anim.start()

    def fade_out(self):
        is_fading_out = self.anim.state() == QPropertyAnimation.Running and self.anim.endValue() == 0.0
        if self.windowOpacity() > 0.0 and not is_fading_out:
            self.anim.stop()
            self.anim.setStartValue(self.windowOpacity())
            self.anim.setEndValue(0.0)
            self.anim.start()

    def _on_anim_finished(self):
        if self.windowOpacity() == 0.0:
            self.hide()

    def hide_instantly(self):
        self.anim.stop()
        self.hide_timer.stop()
        self.setWindowOpacity(0.0)
        self.anim.setEndValue(0.0)
        self.hide()

    def mouseDoubleClickEvent(self, event):
        self.toggle_fullscreen()
        super().mouseDoubleClickEvent(event)


class MultiPlayerApp(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.setWindowTitle("Multi-TV-player - Videos")
        self.setMinimumSize(640, 480)
        self.setContentsMargins(0, 0, 0, 0)
        
        # We apply this universally to KILL any default Qt margins or lines
        self.setStyleSheet("background-color: black; border: none;")

        self.central_widget = QWidget()
        self.central_widget.setStyleSheet("background-color: black; margin: 0px; padding: 0px; border: none;")
        self.setCentralWidget(self.central_widget)
        self.grid_layout = QGridLayout(self.central_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)

        self.is_fullscreen = False
        self.players = []
        self.videos = []
        self.overlays = []
        self.channel_overlays = []
        self.mute_overlays = []
        self.grid_rows = 2
        self.grid_cols = 2
        
        self.single_fs_active = False
        self.single_fs_index = -1

        self.config = config
        self.load_channels_from_url()

        self.stream_groups_numbers = list(self.config['stream_groups'].values())
        self.all_groups_labels = list(self.config['stream_groups'].keys())
        self.stream_groups = [
            [self.channels_by_number[number] for number in group] for group in self.stream_groups_numbers
        ]
        self.current_group_index = 0

        # Set application palette to pure black just in case
        palette = self.palette()
        palette.setColor(self.backgroundRole(), Qt.black)
        self.setPalette(palette)

        # Force VLC to use Direct3D11, as older renderers (Direct3D9) often create a 1px border
        self.instance = vlc.Instance('--quiet', '--network-caching=100', "--aout=directsound", "--vout=direct3d11", "--no-keyboard-events")
        self.setup_players(self.stream_groups[self.current_group_index])
        
        # Shortcuts
        QShortcut(QKeySequence("M"), self, self.handle_mute_toggle, context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("S"), self, self.handle_sub_toggle, context=Qt.ApplicationShortcut)
        for i in range(1, 10):
            QShortcut(QKeySequence(str(i)), self, lambda checked=False, idx=i-1: self.handle_number_shortcut(idx), context=Qt.ApplicationShortcut)
            
        QShortcut(QKeySequence("F11"), self, self.toggle_app_fullscreen, context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("F"), self, self.toggle_app_fullscreen, context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("0"), self, self.toggle_app_fullscreen, context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("Esc"), self, self.handle_escape, context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("*"), self, self.close, context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("Up"), self, self.unmute_all, context=Qt.ApplicationShortcut)
        QShortcut(QKeySequence("Down"), self, self.mute_all, context=Qt.ApplicationShortcut)
            
        # Default main window size to 1080p instead of forcing borderless fullscreen
        self.resize(1920, 1080)

        # Hover checker
        self.hover_timer = QTimer(self)
        self.hover_timer.setInterval(15)
        self.hover_timer.timeout.connect(self.check_hover)
        self.hover_timer.start()
        
        self.installEventFilter(self)

    def check_hover(self):
        pos = QCursor.pos()
        
        # Track idle time
        import time
        if not hasattr(self, 'last_mouse_pos') or self.last_mouse_pos != pos:
            self.last_mouse_pos = pos
            self.last_mouse_move_time = time.time()
            
        idle_time = time.time() - getattr(self, 'last_mouse_move_time', time.time())
        mouse_is_idle = idle_time >= 1.6

        for overlay in self.overlays:
            if not overlay.target_widget.isVisible():
                continue
                
            video_rect = overlay.target_widget.rect()
            mapped_video_pos = overlay.target_widget.mapFromGlobal(pos)
            
            # Add a 50px margin of error to swallow any Qt geometry desyncs after DWM transitions
            margin = 50
            over_video = (-margin <= mapped_video_pos.x() <= video_rect.width() + margin) and \
                         (-margin <= mapped_video_pos.y() <= video_rect.height() + margin)
            
            overlay_rect = overlay.rect()
            mapped_overlay_pos = overlay.mapFromGlobal(pos)
            over_overlay = overlay.isVisible() and overlay_rect.contains(mapped_overlay_pos)
            
            if over_video or over_overlay:
                if mouse_is_idle and not over_overlay:
                    if overlay.windowOpacity() > 0 or overlay.isVisible():
                        overlay.fade_out()
                else:
                    overlay.fade_in()
            else:
                if overlay.windowOpacity() > 0 or overlay.isVisible():
                    overlay.hide_instantly()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for t in [10, 50, 200, 500]:
            QTimer.singleShot(t, lambda: [o.update_position() for o in self.overlays])
            QTimer.singleShot(t, lambda: [c.update_position() for c in self.channel_overlays])

    def moveEvent(self, event):
        super().moveEvent(event)
        for t in [10, 50, 200, 500]:
            QTimer.singleShot(t, lambda: [o.update_position() for o in self.overlays])
            QTimer.singleShot(t, lambda: [c.update_position() for c in self.channel_overlays])

    def showEvent(self, event):
        super().showEvent(event)
        import sys
        if sys.platform == 'win32':
            try:
                import ctypes
                from ctypes.wintypes import BOOL
                hwnd = int(self.winId())
                
                # 1. Force Windows DWM to use Dark Mode for the window frame (fixes white borders and titlebar)
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(BOOL(True)), ctypes.sizeof(BOOL))
                
                # Disable DWM window transitions/animations (fixes maximize/fullscreen animation delay)
                DWMWA_TRANSITIONS_FORCEDISABLE = 3
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_TRANSITIONS_FORCEDISABLE, ctypes.byref(BOOL(True)), ctypes.sizeof(BOOL))
                
                # 2. Force the window class background brush to black (fixes 1px white line when true fullscreen)
                GCLP_HBRBACKGROUND = -10
                BLACK_BRUSH = 4
                GetStockObject = ctypes.windll.gdi32.GetStockObject
                GetStockObject.restype = ctypes.c_void_p
                
                if ctypes.sizeof(ctypes.c_void_p) == 8:
                    SetClassLongPtr = ctypes.windll.user32.SetClassLongPtrW
                    SetClassLongPtr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                else:
                    SetClassLongPtr = ctypes.windll.user32.SetClassLongW
                    SetClassLongPtr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                    
                SetClassLongPtr(hwnd, GCLP_HBRBACKGROUND, GetStockObject(BLACK_BRUSH))
            except Exception as e:
                print(f"Windows API hack failed: {e}")

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Move, QEvent.Resize):
            for overlay in self.overlays:
                overlay.update_position()
            for chan_overlay in getattr(self, 'channel_overlays', []):
                chan_overlay.update_position()
            for mute_overlay in getattr(self, 'mute_overlays', []):
                mute_overlay.update_position()
        elif event.type() == QEvent.MouseButtonRelease:
            if getattr(self, '_ignore_next_release', False):
                self._ignore_next_release = False
                return super().eventFilter(obj, event)
                
            if obj in self.videos:
                index = self.videos.index(obj)
                # Wait 250ms to ensure it's not a double-click
                if hasattr(self, '_single_click_timer') and self._single_click_timer.isActive():
                    return super().eventFilter(obj, event)
                    
                self._single_click_timer = QTimer(self)
                self._single_click_timer.setSingleShot(True)
                self._single_click_timer.timeout.connect(lambda idx=index: self.handle_single_click(idx))
                self._single_click_timer.start(250)
                
        elif event.type() == QEvent.MouseButtonDblClick:
            self._ignore_next_release = True
            if hasattr(self, '_single_click_timer') and self._single_click_timer.isActive():
                self._single_click_timer.stop()
            if obj in self.videos:
                index = self.videos.index(obj)
                self.toggle_single_fullscreen(index)
        return super().eventFilter(obj, event)

    def handle_single_click(self, index):
        if index < len(self.overlays):
            overlay = self.overlays[index]
            overlay.toggle_mute()

    def update_window_state(self):
        app_fs = getattr(self, 'app_fs_active', False)
        if app_fs or self.single_fs_active:
            if not self.isFullScreen():
                self.showFullScreen()
        else:
            if self.isFullScreen():
                self.showNormal()
                self.showMaximized()

    def toggle_app_fullscreen(self):
        self.app_fs_active = not getattr(self, 'app_fs_active', False)
        self.update_window_state()

    def handle_escape(self):
        if self.single_fs_active:
            self.toggle_single_fullscreen(self.single_fs_index)

    def toggle_single_fullscreen(self, index):
        self.setUpdatesEnabled(False)
        
        if self.single_fs_active and self.single_fs_index == index:
            # Restore grid
            for v in self.videos:
                v.show()
            self.single_fs_active = False
            self.single_fs_index = -1
            self.overlays[index].fs_btn.setText("🔲")
            for chan_overlay in getattr(self, 'channel_overlays', []):
                chan_overlay.show_number()
                
            self.update_window_state()
        else:
            # Go single fullscreen
            for i, v in enumerate(self.videos):
                if i != index:
                    v.hide()
                    self.overlays[i].hide_instantly()
                    if i < len(self.channel_overlays):
                        self.channel_overlays[i].hide()
            self.videos[index].show()
            self.single_fs_active = True
            
            if self.single_fs_index != -1 and self.single_fs_index != index:
                self.overlays[self.single_fs_index].fs_btn.setText("🔲")
                
            self.single_fs_index = index
            self.overlays[index].fs_btn.setText("🔳")
            
            # Automatically unmute this video and mute all others
            self.mute_only(index)
            
            if index < len(self.channel_overlays):
                self.channel_overlays[index].show_number()
                
            self.update_window_state()
            
        self.setUpdatesEnabled(True)
        
        for delay in (10, 50, 200, 500):
            QTimer.singleShot(delay, lambda: [o.update_position() for o in self.overlays])
            QTimer.singleShot(delay, lambda: [c.update_position() for c in getattr(self, 'channel_overlays', [])])
            QTimer.singleShot(delay, lambda: [m.update_position() for m in getattr(self, 'mute_overlays', [])])

    def load_channels_from_url(self):
        url = self.config['playlist_url']
        self.channels = {}            
        self.channels_by_number = {}  

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
                name_match = line.split(',', 1)
                channel_name = name_match[1].strip() if len(name_match) > 1 else f"Unknown_{i}"

                if 'HD' in channel_name:
                    print(line)

                chno_match = re.search(r'tvg-chno="(\d+)"', line)
                channel_number = chno_match.group(1) if chno_match else None

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
        for overlay in self.overlays:
            overlay.deleteLater()
        for chan_overlay in self.channel_overlays:
            chan_overlay.deleteLater()
        for mute_overlay in self.mute_overlays:
            mute_overlay.deleteLater()
            
        self.videos.clear()
        self.players.clear()
        self.overlays.clear()
        self.channel_overlays.clear()
        self.mute_overlays.clear()
        
        self.single_fs_active = False
        self.single_fs_index = -1

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
            video_widget.setFrameShape(QFrame.NoFrame)
            video_widget.setStyleSheet("background-color: black; border: none;")
            self.grid_layout.addWidget(video_widget, i // self.grid_cols, i % self.grid_cols)
            self.videos.append(video_widget)
            
            # Important: set event filter on video frame too to catch resizes
            video_widget.installEventFilter(self)
            self.set_vlc_video_widget(player, video_widget)
            
            # Disable VLC's native mouse handling so Qt can receive double clicks
            player.video_set_mouse_input(False)
            player.video_set_key_input(False)
            
            overlay = OverlayControls(self, video_widget, player, i)
            self.overlays.append(overlay)
            
            channel_number = self.stream_groups_numbers[self.current_group_index][i]
            chan_overlay = ChannelOverlay(self, video_widget, channel_number)
            chan_overlay.attach_player(player)
            self.channel_overlays.append(chan_overlay)
            
            mute_overlay = MuteOverlay(self, video_widget)
            self.mute_overlays.append(mute_overlay)
            
            should_mute = False
            overlay.set_mute_ui(should_mute)
            
            QTimer.singleShot(1000, overlay.check_sub_state)
            
        # Staggered loading
        load_order_1_based = [5, 1, 3, 2, 4, 6, 7, 8, 9]
        self.load_queue = [x - 1 for x in load_order_1_based if (x - 1) < num_streams]
        for i in range(num_streams):
            if i not in self.load_queue:
                self.load_queue.append(i)
                
        if not hasattr(self, 'load_timer'):
            self.load_timer = QTimer(self)
            self.load_timer.setInterval(1000)
            self.load_timer.timeout.connect(self._load_next_stream)
            
        # Start the first stream immediately, and the timer will handle the rest
        self.load_timer.stop()
        self._load_next_stream()
        self.load_timer.start()

    def _load_next_stream(self):
        if not hasattr(self, 'load_queue') or not self.load_queue:
            if hasattr(self, 'load_timer'):
                self.load_timer.stop()
            return
            
        idx = self.load_queue.pop(0)
        if idx < len(self.players) and idx < len(self.channel_overlays):
            self.players[idx].play()

    def set_vlc_video_widget(self, player, widget):
        if sys.platform.startswith('linux'):
            player.set_xwindow(widget.winId())
        elif sys.platform == "win32":
            player.set_hwnd(int(widget.winId()))
        elif sys.platform == "darwin":
            player.set_nsobject(int(widget.winId()))

    def showFullScreenOnMonitor(self, monitor_index):
        # Kept for reference, but we default to 1080p normal window now
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
            if group_index == self.current_group_index:
                return
            self.current_group_index = group_index
            print(f"Switched to group {group_index}")
            self.setup_players(self.stream_groups[group_index])
            QTimer.singleShot(1000, self.subs_all_on)

    # --- Global Actions ---
    def handle_mute_toggle(self):
        if not self.players: return
        any_unmuted = any(not p.audio_get_mute() for p in self.players)
        if any_unmuted:
            self.mute_all()
        else:
            self.unmute_all()

    def handle_sub_toggle(self):
        if not self.players: return
        any_subs_on = any(o.sub_state for o in self.overlays)
        if any_subs_on:
            self.subs_all_off()
        else:
            self.subs_all_on()

    def handle_number_shortcut(self, idx):
        if idx >= len(self.players):
            return
            
        if self.single_fs_active and self.single_fs_index == idx:
            # User pressed the same number while in fullscreen. Toggle back to grid.
            self.toggle_single_fullscreen(idx)
        else:
            # User pressed a new number. Solo the audio and isolate the video.
            self.mute_only(idx)
            # If it's not already the active fullscreen, trigger it
            if not (self.single_fs_active and self.single_fs_index == idx):
                self.toggle_single_fullscreen(idx)

    def mute_only(self, index):
        if index >= len(self.overlays): return
        for i, overlay in enumerate(self.overlays):
            overlay.set_mute_ui(i != index)

    def unmute_all(self):
        for overlay in self.overlays:
            overlay.set_mute_ui(False)

    def mute_all(self):
        for overlay in self.overlays:
            overlay.set_mute_ui(True)

    def subs_all_on(self):
        for overlay in self.overlays:
            overlay.set_subtitles(True)

    def subs_all_off(self):
        for overlay in self.overlays:
            overlay.set_subtitles(False)

    def take_screenshot_one(self, i):
        downloads = Path.home() / "Downloads" / "tvplayer_screenshots"
        downloads.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        channel_number = self.stream_groups_numbers[self.current_group_index][i]
        channel_name = self.channels_by_number[channel_number][0]
        filename = self._generate_safe_filename(channel_name, timestamp)
        filepath = downloads / filename
        if self._take_snapshot(self.players[i], filepath):
            print(f"Screenshot saved for player {i+1} at {filepath}")

    def take_screenshot_all(self):
        downloads = Path.home() / "Downloads" / "tvplayer_screenshots"
        downloads.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        for i, player in enumerate(self.players):
            channel_number = self.stream_groups_numbers[self.current_group_index][i]
            channel_name = self.channels_by_number[channel_number][0]
            filename = self._generate_safe_filename(channel_name, timestamp)
            filepath = downloads / filename
            if self._take_snapshot(player, filepath):
                print(f"Screenshot saved for player {i+1} at {filepath}")

    def take_combined_screenshot(self):
        downloads = Path.home() / "Downloads" / "tvplayer_screenshots"
        downloads.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        snapshots = []
        temp_files = []
        for i, player in enumerate(self.players):
            channel_number = self.stream_groups_numbers[self.current_group_index][i]
            channel_name = self.channels_by_number[channel_number][0]
            filename = self._generate_safe_filename(channel_name, timestamp)
            filepath = downloads / filename
            if self._take_snapshot(player, filepath):
                img = Image.open(filepath)
                snapshots.append(img)
                temp_files.append(filepath)
        if not snapshots: return
        num_images = len(snapshots)
        cols = self.grid_cols
        rows = (num_images + cols - 1) // cols
        if num_images == 1:
            print(f"Screenshot saved at {temp_files[0]}")
            return
        width, height = snapshots[0].size
        combined_img = Image.new('RGB', (width * cols, height * rows))
        for idx, img in enumerate(snapshots):
            x = (idx % cols) * width
            y = (idx // cols) * height
            combined_img.paste(img, (x, y))
        combined_filename = downloads / f"{timestamp}_combined_grid.jpg"
        combined_img.save(combined_filename, "JPEG", quality=90)
        for file_path in temp_files:
            try: file_path.unlink()
            except Exception: pass
        print(f"Combined screenshot saved at {combined_filename}")

    def _generate_safe_filename(self, channel_name, timestamp):
        safe_channel_name = "".join(c if c.isalnum() or c in ('-', '_') else "_" for c in channel_name.replace(" ", "_")).rstrip("_")
        return f"{timestamp}_-_{safe_channel_name}.jpg"

    def _take_snapshot(self, player, final_filepath):
        temp_png = final_filepath.with_suffix('.png')
        result = player.video_take_snapshot(0, str(temp_png), 0, 0) == 0
        if not result or not temp_png.exists(): return False
        img = Image.open(temp_png)
        img.convert("RGB").save(final_filepath, "JPEG", quality=90)
        temp_png.unlink()
        return True


class ControlsWindow(QDialog):
    def __init__(self, master_app, all_groups_labels):
        super().__init__(master_app)
        self.setWindowTitle("Global Controls")
        self.setMinimumSize(400, 50)
        self.setWindowFlags(Qt.Window | Qt.WindowDoesNotAcceptFocus | Qt.WindowStaysOnTopHint)
        self.master_app = master_app
        self.all_groups_labels = all_groups_labels
        
        # Because the main app universally forces everything to black, we explicitly 
        # style this dialog to have standard dark-mode colors so it isn't an invisible void.
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                border: 1px solid #444;
            }
            QPushButton {
                background-color: #3b3b3b;
                color: white;
                border: 1px solid #555;
                padding: 5px 15px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #505050;
                border: 1px solid #00aa00;
            }
        """)
        
        self.layout = QGridLayout(self)
        self.build_controls_ui()
        self.position_middle_right()

    def build_controls_ui(self):
        row = 0
        for col, (label, slot) in enumerate([
            ("Unmute All", self.master_app.unmute_all),
            ("Mute All", self.master_app.mute_all),
            ("All Subs ON", self.master_app.subs_all_on),
            ("All Subs OFF", self.master_app.subs_all_off),
            ("Screenshots", self.master_app.take_screenshot_all),
            ("Combined Screenshot", self.master_app.take_combined_screenshot)
        ]):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            self.layout.addWidget(btn, row, col)
            
        row = 1
        for i, label in enumerate(self.all_groups_labels):
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, i=i: self.master_app.switch_group(i))
            self.layout.addWidget(btn, row, i)

    def position_middle_right(self):
        screens = QGuiApplication.screens()
        screen = screens[0]
        geometry = screen.geometry()
        self.adjustSize()
        w, h = self.width(), self.height()
        x = geometry.x() + geometry.width() - w - 50
        y = geometry.y() + (geometry.height() - h) // 2
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        import sys
        if sys.platform == 'win32':
            try:
                import ctypes
                from ctypes.wintypes import BOOL
                hwnd = int(self.winId())
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(BOOL(True)), ctypes.sizeof(BOOL))
            except Exception:
                pass


if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        except Exception:
            pass

    try:
        config = load_config()
    except Exception as e:
        print(f"Error loading config: {e}")
        sys.exit(1)

    q_app = QApplication(sys.argv)
    main_app = MultiPlayerApp(config)
    
    # By default show video window full screen on the non-primary monitor
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    target_screen = primary
    for s in screens:
        if s != primary:
            target_screen = s
            break
            
    # In PySide6, moving an unshown window often gets ignored when going fullscreen/maximized.
    # We must show it normally first, bind it to the target screen's window handle, move it, then maximize it.
    main_app.showNormal()
    if main_app.windowHandle():
        main_app.windowHandle().setScreen(target_screen)
    main_app.move(target_screen.geometry().topLeft())
    main_app.showMaximized()

    all_groups_labels = list(config['stream_groups'].keys())
    controls = ControlsWindow(main_app, all_groups_labels)
    controls.show()
    
    controls.finished.connect(q_app.quit)
    controls.rejected.connect(q_app.quit)

    sys.exit(q_app.exec())