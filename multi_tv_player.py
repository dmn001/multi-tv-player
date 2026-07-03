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

    def __init__(self, master_app, target_widget, channel_number, override_number=None):
        super().__init__(master_app)
        self.target_widget = target_widget
        self.real_channel_number = str(channel_number)
        self.override_number = str(override_number) if override_number else None
        self.has_shown_override = False
        
        initial_text = self.override_number if self.override_number else self.real_channel_number
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
        
        self.label = OutlinedLabel(initial_text, self.clip_widget)
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
        if hasattr(self, 'real_channel_number') and self.real_channel_number:
            if self.override_number and not self.has_shown_override:
                self.label.setText(self.override_number)
                self.has_shown_override = True
            else:
                self.label.setText(self.real_channel_number)
                
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
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        
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
        
        # Auto-enable subtitles once the stream loads
        self.init_sub_timer = QTimer(self)
        self.init_sub_timer.timeout.connect(self._try_init_subs)
        QTimer.singleShot(3600, lambda: self.init_sub_timer.start(1000))
        self._sub_attempts = 0

    def _try_init_subs(self):
        self._sub_attempts += 1
        tracks = self.player.video_get_spu_description() or []
        valid_tracks = [t[0] for t in tracks if t[0] != -1]
        if valid_tracks:
            self.set_subtitles(True)
            self.init_sub_timer.stop()
        elif self._sub_attempts > 10:
            self.init_sub_timer.stop()

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
        
        self.adjustSize()
        rect = self.target_widget.geometry()
        top_left = self.target_widget.mapToGlobal(QPoint(0, 0))
        
        x = top_left.x() + (rect.width() - self.width()) // 2
        y = top_left.y() + rect.height() - self.height()
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

from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtCore import QRect, Qt

class SmoothProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.start_ts = None
        self.stop_ts = None
        self.start_str = ""
        self.stop_str = ""
        self.is_fs = False
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(1000)
        self.update_timer.timeout.connect(self.update)
        self.update_timer.start()

    def set_fullscreen(self, is_fs):
        self.is_fs = is_fs
        self.setFixedHeight(34 if is_fs else 24)
        self.update()

    def update_data(self, start_ts, stop_ts, start_str, stop_str):
        self.start_ts = start_ts
        self.stop_ts = stop_ts
        self.start_str = start_str
        self.stop_str = stop_str
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        bg_color = QColor(40, 40, 40, 255)
        painter.setBrush(bg_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, rect.height()/2, rect.height()/2)
        
        if self.start_ts is None or self.stop_ts is None:
            painter.end()
            return
            
        import time
        now = int(time.time())
        total = self.stop_ts - self.start_ts
        elapsed = now - self.start_ts
        
        if total <= 0:
            painter.end()
            return
            
        progress_pct = max(0.0, min(1.0, elapsed / total))
        
        hue = max(0, min(120, int(120 - (progress_pct * 100 * 1.2))))
        fill_color = QColor.fromHsl(hue, int(255 * 0.9), int(255 * 0.45))
        painter.setBrush(fill_color)
        fill_rect = QRect(rect.x(), rect.y(), int(rect.width() * progress_pct), rect.height())
        painter.setClipRect(fill_rect)
        painter.drawRoundedRect(rect, rect.height()/2, rect.height()/2)
        painter.setClipping(False)
        
        painter.setPen(QPen(Qt.white))
        font = painter.font()
        font.setPointSize(14 if self.is_fs else 10)
        font.setBold(True)
        painter.setFont(font)
        
        left_text = f"{self.start_str} - {self.stop_str}"
        margin = int(rect.height() / 2) + 2
        painter.drawText(rect.adjusted(margin, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, left_text)
        
        dur_hours = total // 3600
        dur_mins = (total % 3600) // 60
        if dur_hours > 0:
            dur_str = f"{dur_hours}h {dur_mins}m"
        else:
            dur_str = f"{dur_mins}m"
        pct_str = f"{progress_pct*100:.1f}%"
        center_text = f"{dur_str} ({pct_str})"
        painter.drawText(rect, Qt.AlignCenter, center_text)
        
        remaining = max(0, self.stop_ts - now)
        rem_hours = remaining // 3600
        rem_mins = (remaining % 3600) // 60
        rem_secs = remaining % 60
        if rem_hours > 0:
            right_text = f"{rem_hours}:{rem_mins:02d}:{rem_secs:02d}"
        else:
            right_text = f"{rem_mins:02d}:{rem_secs:02d}"
        painter.drawText(rect.adjusted(0, 0, -margin, 0), Qt.AlignRight | Qt.AlignVCenter, right_text)
        painter.end()

class EPGOverlay(QWidget):
    def __init__(self, master_app, target_widget, channel_name):
        super().__init__(master_app)
        self.master_app = master_app
        self.target_widget = target_widget
        self.channel_name = channel_name
        
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.bg_frame = QFrame(self)
        self.bg_frame.setObjectName("epgBg")
        self.bg_frame.setStyleSheet("""
            #epgBg {
                background-color: rgba(0, 0, 0, 180);
                border-radius: 8px;
                border: none;
            }
            QLabel {
                color: white;
                background: transparent;
                margin: 0px;
                padding: 0px;
                border: none;
            }
        """)
        main_layout.addWidget(self.bg_frame)
        
        self.layout = QVBoxLayout(self.bg_frame)
        self.layout.setContentsMargins(10, 0, 10, 5)
        self.layout.setSpacing(0)
        
        self.progress_bar = SmoothProgressBar()
        
        self.now_label = QLabel("NOW: Fetching EPG...")
        self.now_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        self.desc_label = QLabel("")
        self.desc_label.setStyleSheet("font-size: 12px; color: #dddddd;")
        self.desc_label.setWordWrap(True)
        
        self.next_label = QLabel("")
        self.next_label.setStyleSheet("font-size: 12px; color: #aaaaaa;")
        
        self.layout.addWidget(self.progress_bar)
        self.layout.addWidget(self.now_label)
        self.layout.addWidget(self.desc_label)
        self.layout.addWidget(self.next_label)
        
        self.setFixedWidth(380)
        self.hide()
        
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)
        
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim.setDuration(300)

    def windowOpacity(self):
        return self.opacity_effect.opacity()
        
    def update_fonts(self, is_single_fs):
        self.now_label.setWordWrap(True)
        self.next_label.setWordWrap(True)
        if is_single_fs:
            self.setFixedWidth(900)
            self.now_label.setStyleSheet("font-weight: bold; font-size: 24px; color: white; border: none; padding: 0px; margin: 0px; background: transparent;")
            self.desc_label.setStyleSheet("font-size: 18px; color: #dddddd; border: none; padding: 0px; margin: 0px; background: transparent;")
            self.progress_bar.set_fullscreen(True)
            self.next_label.setStyleSheet("font-size: 18px; color: #aaaaaa; border: none; padding: 0px; margin: 0px; background: transparent;")
        else:
            self.setFixedWidth(600)
            self.now_label.setStyleSheet("font-weight: bold; font-size: 14px; color: white; border: none; padding: 0px; margin: 0px; background: transparent;")
            self.desc_label.setStyleSheet("font-size: 12px; color: #dddddd; border: none; padding: 0px; margin: 0px; background: transparent;")
            self.progress_bar.set_fullscreen(False)
            self.next_label.setStyleSheet("font-size: 12px; color: #aaaaaa; border: none; padding: 0px; margin: 0px; background: transparent;")

    def update_position(self):
        if not hasattr(self, 'target_widget') or not self.target_widget.isVisible() or self.target_widget.width() == 0:
            return
            
        is_fs = getattr(self.master_app, 'single_fs_active', False)
        fs_changed = not hasattr(self, 'last_is_fs') or self.last_is_fs != is_fs
        self.last_is_fs = is_fs
        
        self.update_fonts(is_fs)
            
        rect = self.target_widget.geometry()
        top_left = self.target_widget.mapToGlobal(QPoint(0, 0))
        
        if fs_changed:
            self.layout.invalidate()
            h = self.layout.heightForWidth(self.width()) if self.layout.hasHeightForWidth() else self.layout.sizeHint().height()
            self.setFixedHeight(h)
            
        x = top_left.x() + (rect.width() - self.width()) // 2
        y = top_left.y()
        self.move(x, y)
        
    def hide_instantly(self):
        self.anim.stop()
        self.opacity_effect.setOpacity(0.0)
        self.hide()
        
    def update_data(self, data):
        if not data:
            if self.now_label.text() != "No EPG Data":
                self.now_label.setText("No EPG Data")
                self.desc_label.setText("")
                self.progress_bar.update_data(None, None, "", "")
                self.next_label.setText("")
                self.update_position()
            return
            
        new_now = f"{data.get('now_title', '')}"
        new_desc = data.get('desc', '')
        new_next = f"NEXT: {data.get('next_title')} ({data.get('next_time', '')})" if data.get('next_title') else ""
        
        needs_resize = False
        if self.now_label.text() != new_now:
            self.now_label.setText(new_now)
            needs_resize = True
        if self.desc_label.text() != new_desc:
            self.desc_label.setText(new_desc)
            needs_resize = True
        if self.next_label.text() != new_next:
            self.next_label.setText(new_next)
            needs_resize = True
            
        time_str = data.get('now_time', ' - ')
        parts = time_str.split(' - ')
        start_str = parts[0].strip() if len(parts) > 0 else ""
        stop_str = parts[1].strip() if len(parts) > 1 else ""
        
        self.progress_bar.update_data(data.get('start_ts'), data.get('stop_ts'), start_str, stop_str)
        
        if needs_resize:
            self.layout.invalidate()
            h = self.layout.heightForWidth(self.width()) if self.layout.hasHeightForWidth() else self.layout.sizeHint().height()
            self.setFixedHeight(h)
            self.update_position()
        
    def show_instantly(self):
        if not getattr(self.master_app, 'show_epg_overlays', True):
            return
            
        self.show()
        self.update_position()
        self.anim.stop()
        self.opacity_effect.setOpacity(1.0)
        self.raise_()

    def fade_in(self):
        if not getattr(self.master_app, 'show_epg_overlays', True):
            return
            
        self.show()
        self.update_position()
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

from PySide6.QtCore import QThread, Signal
from datetime import datetime

class EPGFetcher(QThread):
    data_ready = Signal(dict)
    
    def __init__(self, tvh_url="http://192.168.1.73:9981"):
        super().__init__()
        self.tvh_url = tvh_url
        self.running = True
        
    def format_time(self, ts):
        return datetime.fromtimestamp(ts).strftime('%H:%M')
        
    def progress_bar(self, start_ts, stop_ts, now_ts, length=25):
        total = stop_ts - start_ts
        elapsed = now_ts - start_ts
        if total <= 0 or elapsed < 0: return '[No progress]'
        progress = int((elapsed / total) * length)
        progress = min(max(progress, 0), length - 1)
        return '[' + '=' * progress + '>' + '.' * (length - progress - 1) + ']'
        
    def run(self):
        import time, requests
        while self.running:
            try:
                url = f"{self.tvh_url}/api/epg/events/grid"
                resp = requests.get(url, params={"start": 0, "limit": 1000}, timeout=5)
                if resp.status_code == 200:
                    epg_data = resp.json().get('entries', [])
                    now = int(time.time())
                    
                    channel_data = {}
                    for event in epg_data:
                        cname = event.get('channelName', '')
                        if cname not in channel_data:
                            channel_data[cname] = []
                        channel_data[cname].append(event)
                        
                    parsed_epg = {}
                    for cname, events in channel_data.items():
                        events.sort(key=lambda e: e['start'])
                        now_event, next_event = None, None
                        for i, e in enumerate(events):
                            if e['start'] <= now < e['stop']:
                                now_event = e
                                if i + 1 < len(events):
                                    next_event = events[i + 1]
                                break
                            elif e['start'] > now and next_event is None:
                                next_event = e
                                
                        if now_event or next_event:
                            parsed_epg[cname] = {}
                            if now_event:
                                parsed_epg[cname]['now_title'] = now_event.get('title', 'No Title')
                                parsed_epg[cname]['now_time'] = f"{self.format_time(now_event['start'])} - {self.format_time(now_event['stop'])}"
                                parsed_epg[cname]['desc'] = now_event.get('subtitle', '') or now_event.get('description', '')
                                parsed_epg[cname]['start_ts'] = now_event['start']
                                parsed_epg[cname]['stop_ts'] = now_event['stop']
                                parsed_epg[cname]['progress'] = self.progress_bar(now_event['start'], now_event['stop'], now)
                            if next_event:
                                parsed_epg[cname]['next_title'] = next_event.get('title', 'No Title')
                                parsed_epg[cname]['next_time'] = f"{self.format_time(next_event['start'])} - {self.format_time(next_event['stop'])}"
                                
                    self.data_ready.emit(parsed_epg)
            except Exception as e:
                print(f"EPG Fetch error: {e}")
                
            for _ in range(1):
                if not self.running: break
                time.sleep(1)


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
        
        self.show_epg_overlays = True
        self.epg_mode = 'hover'
        self.epg_data = {}
        self.epg_overlays = []
        self.epg_fetcher = EPGFetcher()
        self.epg_fetcher.data_ready.connect(self.on_epg_data_ready)
        self.epg_fetcher.start()
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
        QShortcut(QKeySequence("Ctrl+W"), self, self.close, context=Qt.ApplicationShortcut)
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

        all_overlays = list(self.overlays)
        if getattr(self, 'epg_mode', 'locked') == 'hover':
            all_overlays.extend(getattr(self, 'epg_overlays', []))
        for overlay in all_overlays:
            if not overlay.target_widget.isVisible():
                continue
                
            video_rect = overlay.target_widget.rect()
            mapped_video_pos = overlay.target_widget.mapFromGlobal(pos)
            
            # Add a 50px margin of error to swallow any Qt geometry desyncs after DWM transitions
            margin = 50
            over_video = (-margin <= mapped_video_pos.x() <= video_rect.width() + margin) and \
                         (-margin <= mapped_video_pos.y() <= video_rect.height() + margin)
            
            try:
                overlay_idx = self.videos.index(overlay.target_widget)
            except ValueError:
                overlay_idx = -1
                
            is_forced = getattr(self, 'single_fs_active', False) and \
                        overlay_idx == getattr(self, 'single_fs_index', -1) and \
                        time.time() < getattr(self, 'force_show_overlays_until', 0)
                        
            if is_forced:
                over_video = True
                mouse_is_idle = False
            
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
                    overlay.fade_out()
                    
        # Check if mouse is hovering over the main application window
        mapped_main = self.mapFromGlobal(pos)
        over_main_window = self.rect().contains(mapped_main)
                    
        # Cursor hiding logic
        if mouse_is_idle and over_main_window:
            if not getattr(self, '_cursor_hidden', False):
                QApplication.setOverrideCursor(Qt.BlankCursor)
                self._cursor_hidden = True
        else:
            if getattr(self, '_cursor_hidden', False):
                QApplication.restoreOverrideCursor()
                self._cursor_hidden = False
                    
        # Fade controls window based on mouse activity
        if hasattr(self, 'controls_window'):
            controls = self.controls_window
            
            if getattr(self, 'single_fs_active', False):
                # Completely hide the global controls in single fullscreen
                if controls.opacity_effect.opacity() > 0 or controls.isVisible():
                    controls.fade_out()
            else:
                mapped_controls = controls.mapFromGlobal(pos)
                over_controls = controls.isVisible() and controls.rect().contains(mapped_controls)
                
                # Check if mouse is hovering over the main application window
                mapped_main = self.mapFromGlobal(pos)
                over_main_window = self.rect().contains(mapped_main)
                
                # Make the HUD disappear faster (0.5s) than the video controls
                hud_is_idle = idle_time >= 0.5
                
                if (hud_is_idle and not over_controls) or not over_main_window:
                    if controls.opacity_effect.opacity() > 0 or controls.isVisible():
                        controls.fade_out()
                elif over_main_window:
                    controls.fade_in()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for t in [10, 50, 200, 500]:
            QTimer.singleShot(t, lambda: [o.update_position() for o in self.overlays])
            QTimer.singleShot(t, lambda: [e.update_position() for e in getattr(self, 'epg_overlays', [])])
            
        if hasattr(self, 'controls_window'):
            for t in [10, 50, 200, 500]:
                QTimer.singleShot(t, self.controls_window.position_bottom_center)
            QTimer.singleShot(t, lambda: [c.update_position() for c in self.channel_overlays])

    def moveEvent(self, event):
        super().moveEvent(event)
        for t in [10, 50, 200, 500]:
            QTimer.singleShot(t, lambda: [o.update_position() for o in self.overlays])
            QTimer.singleShot(t, lambda: [c.update_position() for c in self.channel_overlays])
            QTimer.singleShot(t, lambda: [e.update_position() for e in getattr(self, 'epg_overlays', [])])

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
        if event.type() == QEvent.Wheel:
            delta = event.angleDelta().y() if hasattr(event, 'angleDelta') else 0
            if delta != 0:
                if getattr(self, 'single_fs_active', False):
                    # Scroll down -> next channel, Scroll up -> prev channel (no wrapping)
                    if delta < 0:
                        next_idx = min(self.single_fs_index + 1, len(self.videos) - 1)
                    else:
                        next_idx = max(self.single_fs_index - 1, 0)
                        
                    if next_idx != self.single_fs_index:
                        self.toggle_single_fullscreen(next_idx)
                else:
                    # In grid view, scroll down to enter single fs on index 0
                    if delta < 0:
                        self.toggle_single_fullscreen(0)
                return True
                
        if event.type() in (QEvent.Move, QEvent.Resize):
            for overlay in self.overlays:
                overlay.update_position()
            for chan_overlay in getattr(self, 'channel_overlays', []):
                chan_overlay.update_position()
            for mute_overlay in getattr(self, 'mute_overlays', []):
                mute_overlay.update_position()
                
        elif event.type() == QEvent.MouseButtonRelease:
            if obj in self.videos:
                index = self.videos.index(obj)
                
                if getattr(self, 'single_fs_active', False):
                    # In single fullscreen, only the lower third toggles mute
                    pos_y = event.position().y() if hasattr(event, 'position') else event.pos().y()
                    if pos_y <= obj.height() * (2/3):
                        return super().eventFilter(obj, event)

                if event.button() == Qt.LeftButton:
                    if getattr(self, '_ignore_next_release', False):
                        self._ignore_next_release = False
                        return super().eventFilter(obj, event)
                        
                    if hasattr(self, '_single_click_timer') and self._single_click_timer.isActive():
                        return super().eventFilter(obj, event)
                        
                    self._single_click_timer = QTimer(self)
                    self._single_click_timer.setSingleShot(True)
                    self._single_click_timer.timeout.connect(lambda idx=index: self.handle_single_click(idx, is_left_click=True))
                    self._single_click_timer.start(250)
                    
                elif event.button() == Qt.RightButton:
                    self.handle_single_click(index, is_left_click=False)
                
        elif event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            self._ignore_next_release = True
            if hasattr(self, '_single_click_timer') and self._single_click_timer.isActive():
                self._single_click_timer.stop()
            if obj in self.videos:
                index = self.videos.index(obj)
                self.toggle_single_fullscreen(index)
                
        return super().eventFilter(obj, event)

    def handle_single_click(self, index, is_left_click=True):
        if index < len(self.overlays):
            unmuted_indices = [i for i, o in enumerate(self.overlays) if not o.player.audio_get_mute()]
            
            if is_left_click:
                # If the user clicked the ONLY unmuted video, toggle it off (mute it)
                if len(unmuted_indices) == 1 and unmuted_indices[0] == index:
                    self.overlays[index].toggle_mute()
                else:
                    for i, overlay in enumerate(self.overlays):
                        is_currently_muted = overlay.player.audio_get_mute()
                        if i == index:
                            if is_currently_muted:
                                overlay.toggle_mute()
                        else:
                            if not is_currently_muted:
                                overlay.toggle_mute()
                    self.fs_grid_direction_up = True
            else:
                self.overlays[index].toggle_mute()
                if not self.overlays[index].player.audio_get_mute():
                    # If we just unmuted it, set direction up
                    self.fs_grid_direction_up = True
                
            # Remember the last unmuted video if there is exactly 1 unmuted
            new_unmuted = [i for i, o in enumerate(self.overlays) if not o.player.audio_get_mute()]
            if len(new_unmuted) == 1:
                self.last_unmuted_index = new_unmuted[0]

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
        app_fs = getattr(self, 'app_fs_active', False)
        single_fs = self.single_fs_active
        
        if not hasattr(self, 'fs_grid_direction_up'):
            self.fs_grid_direction_up = True
            
        unmuted = [i for i, o in enumerate(self.overlays) if not o.player.audio_get_mute()]
        has_single_unmuted = (len(unmuted) == 1)
        
        target_index = -1
        if has_single_unmuted:
            target_index = unmuted[0]
        elif len(unmuted) == 0 and hasattr(self, 'last_unmuted_index'):
            target_index = self.last_unmuted_index
            
        if not app_fs and not single_fs:
            # Max Window -> Full Screen Grid
            self.app_fs_active = True
            self.fs_grid_direction_up = True
            self.update_window_state()
            
        elif single_fs:
            # Full Screen 1 Vid -> Full Screen Grid
            self.toggle_single_fullscreen(self.single_fs_index)
            self.app_fs_active = True
            self.fs_grid_direction_up = False
            self.update_window_state()
            
        elif app_fs and not single_fs:
            # We are in Full Screen Grid. Check direction.
            if self.fs_grid_direction_up:
                # Full Screen Grid -> Full Screen 1 Vid
                if target_index != -1:
                    final_target = target_index
                else:
                    final_target = getattr(self, 'locked_audio_index', -1)
                    if final_target == -1:
                        final_target = getattr(self, 'last_single_fs_index', 0)
                        
                self.toggle_single_fullscreen(final_target)
                self.app_fs_active = True
                self.fs_grid_direction_up = False
            else:
                # Full Screen Grid -> Max Window
                self.app_fs_active = False
                self.fs_grid_direction_up = True
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
                
            for epg in getattr(self, 'epg_overlays', []):
                QTimer.singleShot(100, epg.update_position)
                
            self.update_window_state()
        else:
            # Go single fullscreen
            import time
            self.force_show_overlays_until = time.time() + 1.6
            for i, v in enumerate(self.videos):
                if i != index:
                    v.hide()
                    self.overlays[i].hide_instantly()
                    if i < len(getattr(self, 'epg_overlays', [])):
                        self.epg_overlays[i].hide_instantly()
                    if i < len(getattr(self, 'channel_overlays', [])):
                        self.channel_overlays[i].hide()
                    if i < len(getattr(self, 'mute_overlays', [])):
                        self.mute_overlays[i].hide()
                        self.mute_overlays[i].hide_timer.stop()
            self.videos[index].show()
            self.single_fs_active = True
            
            # Switch EPG to hover mode instantly
            if getattr(self, 'epg_mode', 'locked') == 'locked':
                self.epg_mode = 'hover'
                
            if index < len(getattr(self, 'epg_overlays', [])):
                QTimer.singleShot(100, self.epg_overlays[index].update_position)
                self.epg_overlays[index].fade_in()
            
            if self.single_fs_index != -1 and self.single_fs_index != index:
                self.overlays[self.single_fs_index].fs_btn.setText("🔲")
                
            self.single_fs_index = index
            self.last_single_fs_index = index
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
            QTimer.singleShot(delay, lambda: [e.update_position() for e in getattr(self, 'epg_overlays', [])])

    def on_epg_data_ready(self, data):
        self.epg_data = data
        for overlay in self.epg_overlays:
            if hasattr(overlay, 'channel_name'):
                overlay.update_data(data.get(overlay.channel_name, {}))
                
        if getattr(self, 'epg_mode', 'locked') == 'locked':
            for o in self.epg_overlays:
                if o.target_widget.isVisible() and o.windowOpacity() == 0.0:
                    o.fade_in()
                
    def toggle_epg(self):
        if getattr(self, 'epg_mode', 'locked') == 'locked':
            self.epg_mode = 'hover'
            for o in self.epg_overlays: 
                o.hide_instantly()
        else:
            self.epg_mode = 'locked'
            for o in self.epg_overlays: 
                o.fade_in()

    def closeEvent(self, event):
        if hasattr(self, 'epg_fetcher'):
            self.epg_fetcher.running = False
            self.epg_fetcher.wait(1000)
        super().closeEvent(event)

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
        self.epg_mode = 'hover'
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
        for epg_overlay in getattr(self, 'epg_overlays', []):
            epg_overlay.deleteLater()
            
        self.videos.clear()
        self.players.clear()
        self.overlays.clear()
        self.channel_overlays.clear()
        self.mute_overlays.clear()
        self.epg_overlays.clear()
        
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
            
            epg_overlay = EPGOverlay(self, video_widget, name)
            if hasattr(self, 'epg_data') and name in self.epg_data:
                epg_overlay.update_data(self.epg_data[name])
            self.epg_overlays.append(epg_overlay)
            
            channel_number = self.stream_groups_numbers[self.current_group_index][i]
            
            # User requested hardcoded display overrides for the first 6 channels
            # Grid Top Row: 24, 109, 63
            # Grid Second Row: 87, 18, 247
            override_numbers = ["24", "109", "63", "87", "18", "247"]
            initial_override = None
            if i < len(override_numbers):
                initial_override = override_numbers[i]
                
            chan_overlay = ChannelOverlay(self, video_widget, channel_number, initial_override)
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
        
        if hasattr(self, 'controls_window'):
            self.controls_window.raise_()

    def _load_next_stream(self):
        if not hasattr(self, 'load_queue') or not self.load_queue:
            if hasattr(self, 'load_timer'):
                self.load_timer.stop()
            return
            
        idx = self.load_queue.pop(0)
        if idx < len(self.players) and idx < len(self.channel_overlays):
            self.players[idx].play()
            if getattr(self, 'epg_mode', 'locked') == 'locked' and idx < len(getattr(self, 'epg_overlays', [])):
                if self.epg_overlays[idx].windowOpacity() == 0.0:
                    QTimer.singleShot(3600, self.epg_overlays[idx].show_instantly)
            
            if not self.load_queue:
                QTimer.singleShot(3600, self._auto_lock_epg)

    def _auto_lock_epg(self):
        if getattr(self, 'epg_mode', 'hover') != 'locked':
            self.epg_mode = 'locked'
            for o in getattr(self, 'epg_overlays', []):
                if o.windowOpacity() == 0.0:
                    o.show_instantly()

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


class ControlsWindow(QWidget):
    def __init__(self, master_app, all_groups_labels):
        super().__init__(master_app.central_widget)
        self.master_app = master_app
        self.all_groups_labels = all_groups_labels
        
        self.setStyleSheet("""
            #BgFrame {
                background-color: rgba(30, 30, 30, 220);
                border: 1px solid rgba(100, 100, 100, 100);
                border-radius: 10px;
            }
            QPushButton {
                background-color: rgba(60, 60, 60, 200);
                color: white;
                border: 1px solid #555;
                padding: 5px 15px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(90, 90, 90, 255);
                border: 1px solid #00aa00;
                color: #00FF00;
            }
        """)
        
        self.bg_frame = QFrame(self)
        self.bg_frame.setObjectName("BgFrame")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.bg_frame)
        
        self.layout = QGridLayout(self.bg_frame)
        # Reduced padding so the borders aren't too large
        self.layout.setContentsMargins(15, 10, 15, 10)
        self.layout.setVerticalSpacing(10)
        
        self.build_controls_ui()
        QTimer.singleShot(500, self.position_bottom_center)
        
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim.setDuration(250)
        self.anim.finished.connect(self._on_anim_finished)
        self.opacity_effect.setOpacity(0.0)
        
        self._drag_pos = None
        self._dragged = False

    def position_bottom_center(self):
        self.adjustSize()
        if not self.parent(): return
        rect = self.parent().rect()
        w, h = self.width(), self.height()
        
        try:
            from datetime import datetime
            import pytz
            uk_tz = pytz.timezone('Europe/London')
            now = datetime.now(uk_tz)
            if now.hour >= 19 or now.hour < 7:
                # 7pm to 7am: Center on the bottom-left tile
                cols = getattr(self.master_app, 'grid_cols', 3)
                col_width = rect.width() / cols
                x = int((col_width - w) / 2)
            else:
                x = (rect.width() - w) // 2
        except Exception as e:
            print(f"Timezone check failed: {e}")
            x = (rect.width() - w) // 2
            
        y = rect.height() - h - 55
        self.move(x, y)

    def mousePressEvent(self, event):
        global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
        self._drag_pos = global_pos - self.mapToGlobal(QPoint(0,0))
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
            # Map global position back to parent coordinates for child widget moving
            local_pos = self.parent().mapFromGlobal(global_pos - self._drag_pos)
            self.move(local_pos)
            event.accept()
            
    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()

    def eventFilter(self, obj, event):
        if isinstance(obj, QPushButton):
            if event.type() == QEvent.MouseButtonPress:
                global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                self._drag_pos = global_pos - self.mapToGlobal(QPoint(0,0))
                self._press_global_pos = global_pos
                self._dragged = False
                
            elif event.type() == QEvent.MouseMove:
                if self._drag_pos is not None:
                    global_pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                    
                    if not self._dragged and hasattr(self, '_press_global_pos'):
                        diff = global_pos - self._press_global_pos
                        if diff.manhattanLength() > 5:
                            self._dragged = True
                            
                    if self._dragged:
                        local_pos = self.parent().mapFromGlobal(global_pos - self._drag_pos)
                        self.move(local_pos)
                        return True
                    
            elif event.type() == QEvent.MouseButtonRelease:
                self._drag_pos = None
                if getattr(self, '_dragged', False):
                    # Cancel the click if we dragged
                    self._dragged = False
                    return True
        return super().eventFilter(obj, event)

    def build_controls_ui(self):
        buttons = []
        
        # 1. Global actions
        global_actions = [
            ("Unmute All", self.master_app.unmute_all),
            ("Mute All", self.master_app.mute_all),
            ("All Subs ON", self.master_app.subs_all_on),
            ("All Subs OFF", self.master_app.subs_all_off),
            ("Screenshots", self.master_app.take_screenshot_all),
            ("Combined Screenshot", self.master_app.take_combined_screenshot),
            ("Toggle EPG", self.master_app.toggle_epg),
            ("Full Screen", self.master_app.toggle_app_fullscreen)
        ]
        
        for label, slot in global_actions:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            buttons.append(btn)
            
        # 2. Group presets
        for i, label in enumerate(self.all_groups_labels):
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, i=i: self.master_app.switch_group(i))
            buttons.append(btn)
            
        # Layout in 2 columns
        for i, btn in enumerate(buttons):
            row = i // 2
            col = i % 2
            self.layout.addWidget(btn, row, col)
            
        for btn in self.findChildren(QPushButton):
            btn.installEventFilter(self)

    def fade_in(self):
        if not self.isVisible():
            self.show()
            self.raise_()
        elif self.opacity_effect.opacity() == 1.0:
            pass # Avoid calling raise_() continuously when fully visible, as it interrupts mouse dragging
            
        is_fading_in = self.anim.state() == QPropertyAnimation.Running and self.anim.endValue() == 1.0
        if self.opacity_effect.opacity() < 1.0 and not is_fading_in:
            self.anim.stop()
            self.anim.setStartValue(self.opacity_effect.opacity())
            self.anim.setEndValue(1.0)
            self.anim.start()

    def fade_out(self):
        is_fading_out = self.anim.state() == QPropertyAnimation.Running and self.anim.endValue() == 0.0
        if self.opacity_effect.opacity() > 0.0 and not is_fading_out:
            self.anim.stop()
            self.anim.setStartValue(self.opacity_effect.opacity())
            self.anim.setEndValue(0.0)
            self.anim.start()

    def _on_anim_finished(self):
        if self.opacity_effect.opacity() == 0.0:
            self.hide()


if __name__ == "__main__":
    import sys
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
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
    main_app.controls_window = controls
    controls.show()
    
    # When the main window is closed, quit the application
    q_app.setQuitOnLastWindowClosed(True)

    sys.exit(q_app.exec())