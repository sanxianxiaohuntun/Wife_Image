import sys
import os
import yaml
import json
import queue
import multiprocessing
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QMenu, QAction, QDesktopWidget, QFrame
from PyQt5.QtGui import QPixmap, QPainter, QFont, QColor, QPen, QBrush, QFontMetrics
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal, pyqtSlot
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtCore import QUrl

class TextBubble(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.text = ""
        self.config = {}
        self.parent_widget = parent
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.hide)
        
        self.hide()
    
    def set_config(self, config):
        self.config = config
        self.font = QFont()
        self.font.setPointSize(self.config.get('font_size', 12))
        self.font_metrics = QFontMetrics(self.font)
    
    def set_always_on_top(self, always_on_top):
        flags = self.windowFlags()
        if always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if self.isVisible():
            self.show()
    
    def show_message(self, text):
        if not text:
            return
        
        self.text = self.format_text(text)
        self.calc_size_and_position()
        self.show()
        
        self.timer.stop()
        duration = self.config.get('show_duration', 5) * 1000
        self.timer.start(duration)
    
    def format_text(self, text):
        max_chars = self.config.get('max_chars_per_line', 30)
        max_lines = self.config.get('max_lines', 5)
        
        lines = []
        current_line = ""
        
        for char in text:
            if len(current_line) >= max_chars:
                lines.append(current_line)
                current_line = ""
                
                if len(lines) >= max_lines:
                    lines[-1] = lines[-1][:-3] + "..."
                    break
            
            current_line += char
            
            if char == '\n':
                lines.append(current_line)
                current_line = ""
                
                if len(lines) >= max_lines:
                    break
        
        if current_line and len(lines) < max_lines:
            lines.append(current_line)
        
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            if lines[-1][-3:] != "...":
                lines[-1] = lines[-1][:-3] + "..."
        
        return "\n".join(lines)
    
    def calc_size_and_position(self):
        if not self.parent_widget:
            return
        
        font_height = self.font_metrics.height()
        lines = self.text.split('\n')
        max_width = 0
        
        for line in lines:
            width = self.font_metrics.width(line)
            max_width = max(max_width, width)
        
        padding = self.config.get('padding', 10)
        bubble_width = max_width + padding * 2
        bubble_height = font_height * len(lines) + padding * 2
        
        self.resize(bubble_width, bubble_height)
        
        parent_pos = self.parent_widget.pos()
        parent_size = self.parent_widget.size()
        
        x = parent_pos.x() + (parent_size.width() - bubble_width) // 2
        y = parent_pos.y() - bubble_height - 10
        
        if y < 0:
            y = 0
        
        self.move(x, y)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        painter.setFont(self.font)
        
        bubble_width = self.width()
        bubble_height = self.height()
        
        bg_color = QColor(255, 255, 255, 216)
        try:
            bg_str = self.config.get('background_color', 'rgba(255, 255, 255, 0.85)')
            if bg_str.startswith('rgba'):
                r, g, b, a = [int(x) if i < 3 else float(x) for i, x in enumerate(
                    bg_str.replace('rgba(', '').replace(')', '').split(','))]
                bg_color = QColor(r, g, b, int(a * 255))
        except:
            pass
        
        border_radius = self.config.get('border_radius', 10)
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(0, 0, bubble_width, bubble_height, border_radius, border_radius)
        
        text_color = QColor(0, 0, 0)
        try:
            text_str = self.config.get('text_color', 'rgb(0, 0, 0)')
            if text_str.startswith('rgb'):
                r, g, b = [int(x) for x in text_str.replace('rgb(', '').replace(')', '').split(',')]
                text_color = QColor(r, g, b)
        except:
            pass
        
        painter.setPen(QPen(text_color))
        padding = self.config.get('padding', 10)
        font_height = self.font_metrics.height()
        
        y_pos = padding
        for line in self.text.split('\n'):
            painter.drawText(padding, y_pos + font_height, line)
            y_pos += font_height
    
    def update_position(self):
        if self.isVisible():
            self.calc_size_and_position()

class MessageHandler(QObject):
    emotion_signal = pyqtSignal(str)
    message_signal = pyqtSignal(str)
    config_signal = pyqtSignal(dict)
    audio_signal = pyqtSignal(str)
    
    def __init__(self, widget):
        super().__init__()
        self.emotion_signal.connect(widget.change_emotion)
        self.message_signal.connect(widget.show_message)
        self.config_signal.connect(widget.update_config)
        self.audio_signal.connect(widget.play_audio)

class WifeImageWidget(QWidget):
    def __init__(self, config, msg_queue, config_path):
        super().__init__()
        self.config = config
        self.msg_queue = msg_queue
        self.config_path = config_path
        self.plugin_dir = os.path.dirname(os.path.abspath(config_path))
        self.emotions_json_path = os.path.join(self.plugin_dir, "emotions.json")
        self.current_image = None
        self.original_pixmap = None
        self.dragging = False
        self.drag_position = None
        
        self.media_player = QMediaPlayer()
        
        self.init_size = (
            config['window']['default_width'], 
            config['window']['default_height']
        )
        
        self.current_size = (
            config['window'].get('current_width', self.init_size[0]),
            config['window'].get('current_height', self.init_size[1])
        )
        
        self.default_emotion = config.get('emotion_reset', {}).get('default_emotion', 'happy')
        self.auto_reset = config.get('emotion_reset', {}).get('auto_reset', True)
        self.reset_delay = config.get('emotion_reset', {}).get('reset_delay', 5) * 1000
        self.emotion_reset_timer = QTimer(self)
        self.emotion_reset_timer.timeout.connect(self.reset_emotion)
        self.emotion_reset_timer.setSingleShot(True)
        
        self.emotions = self.load_emotions()
        
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        if self.config['window']['always_on_top']:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.resize(self.current_size[0], self.current_size[1])
        
        self.text_bubble = TextBubble(None)
        self.text_bubble.set_config(config['chat_bubble'])
        
        if self.config['window']['always_on_top']:
            self.text_bubble.set_always_on_top(True)
        
        self.msg_handler = MessageHandler(self)
        
        self.msg_timer = QTimer(self)
        self.msg_timer.timeout.connect(self.check_message_queue)
        self.msg_timer.start(100)
        
        self.settings_timer = QTimer(self)
        self.settings_timer.timeout.connect(self.save_settings)
        self.settings_timer.start(5000)
        
        self.init_ui()
        
        self.running = True
    
    def init_ui(self):
        self.resize(self.current_size[0], self.current_size[1])
        self.setWindowOpacity(self.config['window']['opacity'])
        self.load_default_emotion()
        self.move_to_initial_position()
        self.show()
    
    def move_to_initial_position(self):
        if (self.config.get('position', {}).get('remember', False) and
            self.config['position']['x'] >= 0 and self.config['position']['y'] >= 0):
            x = self.config['position']['x']
            y = self.config['position']['y']
        else:
            desktop = QDesktopWidget().availableGeometry()
            x = desktop.width() - self.width() - 20
            y = desktop.height() - self.height() - 40
        
        self.move(x, y)
    
    def save_settings(self):
        if self.config.get('position', {}).get('remember', False):
            if 'position' not in self.config:
                self.config['position'] = {}
            
            self.config['position']['x'] = self.x()
            self.config['position']['y'] = self.y()
            
            self.config['window']['always_on_top'] = bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
            
            self.config['window']['current_width'] = self.width()
            self.config['window']['current_height'] = self.height()
            
            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    yaml.dump(self.config, f, default_flow_style=False)
            except Exception:
                pass
    
    def load_image(self, image_name):
        image_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'image')
        image_path = os.path.join(image_dir, image_name)
        
        if os.path.exists(image_path):
            self.current_image = image_path
            self.original_pixmap = QPixmap(image_path)
            self.update_image_size()
            
            if self.text_bubble.isVisible():
                self.text_bubble.update_position()
    
    def update_image_size(self):
        if self.original_pixmap:
            scaled_pixmap = self.original_pixmap.scaled(
                self.width(), self.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)
            self.image_label.resize(self.width(), self.height())
    
    def load_emotions(self):
        emotions = {}
        
        try:
            if os.path.exists(self.emotions_json_path):
                with open(self.emotions_json_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                    
                if 'emotions' in json_data and isinstance(json_data['emotions'], list):
                    for emotion_name in json_data['emotions']:
                        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                            potential_file = f"{emotion_name}{ext}"
                            if os.path.exists(os.path.join(self.plugin_dir, 'image', potential_file)):
                                emotions[emotion_name] = potential_file
                                break
        except Exception:
            pass
        
        return emotions
    
    def load_default_emotion(self):
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            potential_file = f"{self.default_emotion}{ext}"
            image_dir = os.path.join(self.plugin_dir, 'image')
            if os.path.exists(os.path.join(image_dir, potential_file)):
                self.load_image(potential_file)
                return
        
        if self.emotions:
            first_emotion = next(iter(self.emotions.values()))
            self.load_image(first_emotion)
    
    def reset_emotion(self):
        self.load_default_emotion()
    
    @pyqtSlot(str)
    def change_emotion(self, emotion):
        if self.emotion_reset_timer.isActive():
            self.emotion_reset_timer.stop()
        
        if emotion in self.config['emotions']:
            image_name = self.config['emotions'][emotion]
            self.load_image(image_name)
        elif emotion in self.emotions:
            image_name = self.emotions[emotion]
            self.load_image(image_name)
        
        if self.auto_reset:
            self.emotion_reset_timer.start(self.reset_delay)
    
    @pyqtSlot(str)
    def show_message(self, text):
        if text:
            self.text_bubble.parent_widget = self
            self.text_bubble.show_message(text)
    
    @pyqtSlot(dict)
    def update_config(self, config_data):
        if 'always_on_top' in config_data:
            self.set_always_on_top(config_data['always_on_top'])
    
    def set_always_on_top(self, always_on_top):
        flags = self.windowFlags()
        if always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        
        if self.text_bubble:
            self.text_bubble.set_always_on_top(always_on_top)
        
        self.config['window']['always_on_top'] = always_on_top
    
    @pyqtSlot(str)
    def play_audio(self, audio_path):
        if not audio_path or not os.path.exists(audio_path):
            return
            
        try:
            self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(audio_path)))
            self.media_player.play()
        except Exception as e:
            pass
    
    def check_message_queue(self):
        try:
            if self.msg_queue and not self.msg_queue.empty():
                msg = self.msg_queue.get_nowait()
                
                if msg['type'] == 'emotion':
                    self.msg_handler.emotion_signal.emit(msg['content'])
                elif msg['type'] == 'message':
                    self.msg_handler.message_signal.emit(msg['content'])
                elif msg['type'] == 'config':
                    self.msg_handler.config_signal.emit(msg['content'])
                elif msg['type'] == 'audio':
                    self.msg_handler.audio_signal.emit(msg['content'])
                elif msg['type'] == 'exit':
                    self.close()
        except queue.Empty:
            pass
        except Exception:
            pass
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.config['window']['drag_enabled']:
            self.dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event.globalPos())
    
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.dragging:
            self.move(event.globalPos() - self.drag_position)
            
            if self.text_bubble.isVisible():
                self.text_bubble.update_position()
                
            event.accept()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.save_settings()
    
    def wheelEvent(self, event):
        if not self.config['window']['resize_enabled']:
            return
            
        delta = event.angleDelta().y()
        scale_factor = 1.1 if delta > 0 else 0.9
        
        new_width = int(self.width() * scale_factor)
        new_height = int(self.height() * scale_factor)
        
        new_width = max(100, new_width)
        new_height = max(100, new_height)
        
        self.resize(new_width, new_height)
        self.current_size = (new_width, new_height)
        
        self.update_image_size()
        
        if self.text_bubble.isVisible():
            self.text_bubble.update_position()
        
        self.save_settings()
    
    def show_context_menu(self, pos):
        context_menu = QMenu(self)
        
        always_on_top_action = QAction("置顶窗口", self, checkable=True)
        always_on_top_action.setChecked(bool(self.windowFlags() & Qt.WindowStaysOnTopHint))
        always_on_top_action.triggered.connect(lambda checked: self.set_always_on_top(checked))
        
        reset_size_action = QAction("重置大小", self)
        reset_size_action.triggered.connect(self.reset_size)
        
        reset_position_action = QAction("重置位置", self)
        reset_position_action.triggered.connect(self.reset_position)
        
        context_menu.addAction(always_on_top_action)
        context_menu.addAction(reset_size_action)
        context_menu.addAction(reset_position_action)
        
        context_menu.exec_(pos)
    
    def reset_size(self):
        self.resize(self.init_size[0], self.init_size[1])
        self.current_size = self.init_size
        self.update_image_size()
        
        if self.text_bubble.isVisible():
            self.text_bubble.update_position()
    
    def reset_position(self):
        desktop = QDesktopWidget().availableGeometry()
        x = desktop.width() - self.width() - 20
        y = desktop.height() - self.height() - 40
        self.move(x, y)
        
        if self.text_bubble.isVisible():
            self.text_bubble.update_position()
            
        self.save_settings()
    
    def moveEvent(self, event):
        super().moveEvent(event)
        if self.text_bubble.isVisible():
            self.text_bubble.update_position()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_image_size()
        if self.text_bubble.isVisible():
            self.text_bubble.update_position()
    
    def closeEvent(self, event):
        self.save_settings()
        
        if self.text_bubble:
            self.text_bubble.hide()
            self.text_bubble.close()
        
        self.media_player.stop()
        
        self.running = False
        self.msg_timer.stop()
        self.settings_timer.stop()
        event.accept()

def start_ui(config_path, msg_queue):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    app = QApplication(sys.argv)
    widget = WifeImageWidget(config, msg_queue, config_path)
    sys.exit(app.exec_())

if __name__ == "__main__":
    try:
        config_path = "config.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        msg_queue = multiprocessing.Queue()
        start_ui(config_path, msg_queue)
    except Exception:
        pass 