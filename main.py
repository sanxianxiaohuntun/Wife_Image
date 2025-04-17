import os
import re
import yaml
import json
import multiprocessing
import time
import subprocess
import threading
from pkg.plugin.context import register, handler, BasePlugin, APIHost, EventContext
from pkg.plugin.events import *
from pkg.platform.types import message as platform_message
from pkg.provider import entities as llm_entities
from .tts import QhaiTTS


EMOTION_PATTERN = r'\[:([\w\u4e00-\u9fa5]+)\]'
@register(name="Wife_Image", description="在Windows桌面显示可交互的角色形象", version="0.3", author="小馄饨")
class WifeImagePlugin(BasePlugin):
    def __init__(self, host: APIHost):
        super().__init__(host)
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.plugin_dir, "config.yaml")
        self.emotions_json_path = os.path.join(self.plugin_dir, "emotions.json")
        self.image_dir = os.path.join(self.plugin_dir, "image")
        self.audio_cache_dir = os.path.join(self.plugin_dir, "audio_cache")

        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)
            
        if not os.path.exists(self.audio_cache_dir):
            os.makedirs(self.audio_cache_dir)
        
        self.config = self.load_config()
        self.emotions = {}
        self.msg_queue = None
        self.ui_process = None
        self.emotion_pattern = re.compile(EMOTION_PATTERN)
        self.scan_emotions()
        
        self.tts = None
        if self.config.get('tts', {}).get('enabled', False):
            self.tts = QhaiTTS(self.config.get('tts', {}))
            
        self.ffmpeg_path = os.path.join(self.plugin_dir, 'ffmpeg', 'ffmpeg.exe')
        self.encoder_path = os.path.join(self.plugin_dir, 'ffmpeg', 'silk_v3_encoder.exe')
        
        self.cleanup_thread = threading.Thread(target=self.cleanup_audio_files, daemon=True)
        self.cleanup_thread.start()
    
    def load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            return {
                'window': {'always_on_top': True, 'default_width': 240, 'default_height': 320, 
                          'opacity': 0.9, 'drag_enabled': True, 'resize_enabled': True},
                'emotions': {},
                'chat_bubble': {'font_size': 12, 'show_duration': 5, 'max_width': 300,
                               'background_color': 'rgba(255, 255, 255, 0.85)', 
                               'text_color': 'rgb(0, 0, 0)', 'border_radius': 10, 'padding': 10,
                               'max_lines': 5, 'max_chars_per_line': 30},
                'process': {'use_separate_process': True},
                'position': {'remember': True, 'x': -1, 'y': -1},
                'emotion_reset': {'auto_reset': True, 'default_emotion': 'happy', 'reset_delay': 5},
                'access_control': {'enabled': True, 'admins': [], 'whitelist': []},
                'tts': {'enabled': False, 'api_key': '', 'api_url': 'https://api.qhaigc.net', 
                       'model': 'qhai-tts:永雏塔菲', 'max_text_length': 300}
            }
    
    def check_user_permission(self, user_id):
        user_id = str(user_id)
        
        if not self.config.get('access_control', {}).get('enabled', True):
            return True
        
        admins = [str(admin_id) for admin_id in self.config.get('access_control', {}).get('admins', [])]
        whitelist = [str(user_id) for user_id in self.config.get('access_control', {}).get('whitelist', [])]
        
        if user_id in admins or user_id in whitelist:
            return True
            
        return False
    
    def scan_emotions(self):
        valid_emotions = {}
        emotion_list = []
        
        for file in os.listdir(self.image_dir):
            name, ext = os.path.splitext(file)
            if ext.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                valid_emotions[name] = file
                emotion_list.append(name)
        
        self.emotions = valid_emotions
        
        try:
            with open(self.emotions_json_path, 'w', encoding='utf-8') as f:
                json.dump({"emotions": emotion_list}, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
    
    def save_config(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False)
        except Exception:
            pass
    
    async def initialize(self):
        try:
            self.msg_queue = multiprocessing.Queue()
            
            if self.config['process']['use_separate_process']:
                try:
                    from plugins.Wife_image.ui import start_ui
                    self.ui_process = multiprocessing.Process(
                        target=start_ui,
                        args=(self.config_path, self.msg_queue)
                    )
                    self.ui_process.daemon = True
                    self.ui_process.start()
                except Exception:
                    pass
        except Exception:
            pass
    
    def process_emotion(self, text):
        modified_text = text
        found_emotion = None
        
        matches = re.findall(self.emotion_pattern, text)
        for emotion in matches:
            if emotion in self.emotions:
                found_emotion = emotion
                modified_text = re.sub(r'\[:{}]'.format(re.escape(emotion)), '', modified_text)
        
        return modified_text.strip(), found_emotion
    
    def remove_all_emotions(self, text):
        return re.sub(self.emotion_pattern, '', text).strip()
    
    def send_to_ui(self, msg_type, content):
        if self.msg_queue:
            try:
                self.msg_queue.put({
                    'type': msg_type,
                    'content': content,
                    'timestamp': time.time()
                })
            except Exception:
                pass
    
    def play_audio(self, audio_path):
        if self.msg_queue and audio_path and os.path.exists(audio_path):
            try:
                self.msg_queue.put({
                    'type': 'audio',
                    'content': audio_path,
                    'timestamp': time.time()
                })
            except Exception:
                pass
    
    def convert_to_silk(self, mp3_file):
        try:
            silk_file_path = f"{mp3_file}.silk"
            pcm_file_path = f"{mp3_file}.pcm"
            
            if not os.path.exists(self.ffmpeg_path):
                return None
                
            if not os.path.exists(mp3_file):
                return None
                
            result = subprocess.run(
                [
                    self.ffmpeg_path,
                    '-y',
                    '-i', mp3_file,
                    '-f', 's16le',
                    '-ar', '24000',
                    '-ac', '1',
                    pcm_file_path
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=False,
                check=False
            )
            
            if result.returncode != 0 or not os.path.exists(pcm_file_path):
                return None

            if os.path.exists(self.encoder_path):
                result = subprocess.run(
                    [
                        self.encoder_path,
                        pcm_file_path,
                        silk_file_path,
                        "-rate", "24000",
                        "-tencent",
                        "-quiet"
                    ],
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=False,
                    check=False
                )
                
                if os.path.exists(pcm_file_path):
                    os.remove(pcm_file_path)
                    
                if result.returncode == 0 and os.path.exists(silk_file_path) and os.path.getsize(silk_file_path) > 0:
                    return silk_file_path
                else:
                    return None
            else:
                if os.path.exists(pcm_file_path):
                    os.remove(pcm_file_path)
                return None
                
        except Exception as e:
            return None
    
    @handler(PromptPreProcessing)
    async def handle_prompt_preprocessing(self, ctx: EventContext):
        emotion_list = ", ".join(self.emotions.keys())
        emotion_prompt = f"你现在有一个**虚拟形象**可以在对话中使用命令来表达情感或心情控制虚拟形象每次只能使用一个表情，格式为[:表情名]。**当前支持的表情**: {emotion_list}。表情标记会在回复中显示对应的表情，但不会在消息文本中显示。不使用表情时需要默认带上[:默认]，多使用不同的表情。"
        
        last_user_index = -1
        for i, prompt in enumerate(ctx.event.default_prompt):
            if prompt.role == 'user':
                last_user_index = i
        
        if last_user_index != -1:
            ctx.event.default_prompt.insert(last_user_index + 1, llm_entities.Message(
                role='system',
                content=emotion_prompt
            ))
        else:
            ctx.event.default_prompt.append(llm_entities.Message(
                role='system',
                content=emotion_prompt
            ))
    
    @handler(NormalMessageResponded)
    async def handle_model_response(self, ctx: EventContext):
        response_text = ctx.event.response_text
        sender_id = ctx.event.sender_id
        
        has_emotion = bool(re.search(self.emotion_pattern, response_text))
        
        if has_emotion:
            modified_text, emotion = self.process_emotion(response_text)
            
            if self.check_user_permission(sender_id):
                if emotion:
                    audio_path = None
                    silk_path = None
                    if self.tts and self.config.get('tts', {}).get('enabled', False):
                        audio_path = self.tts.text_to_speech(modified_text)
                        if audio_path:
                            silk_path = self.convert_to_silk(audio_path)
                    
                    self.send_to_ui('emotion', emotion)
                    self.send_to_ui('message', modified_text)
                    
                    if audio_path:
                        self.play_audio(audio_path)
                    
                    if silk_path and os.path.exists(silk_path):
                        ctx.prevent_default()
                        
                        await ctx.send_message(
                            ctx.event.launcher_type,
                            ctx.event.launcher_id,
                            [platform_message.Plain(modified_text)]
                        )
                        
                        await ctx.send_message(
                            ctx.event.launcher_type,
                            ctx.event.launcher_id,
                            [platform_message.Voice(path=silk_path)]
                        )
                        return
                    elif modified_text != response_text:
                        ctx.prevent_default()
                        await ctx.send_message(
                            ctx.event.launcher_type,
                            ctx.event.launcher_id,
                            [platform_message.Plain(modified_text)]
                        )
                        return
            
            if modified_text != response_text:
                ctx.prevent_default()
                await ctx.send_message(
                    ctx.event.launcher_type,
                    ctx.event.launcher_id,
                    [platform_message.Plain(modified_text)]
                )
    
    def cleanup_audio_files(self):
        while True:
            try:
                time.sleep(3600)
                
                current_time = time.time()
                
                for filename in os.listdir(self.audio_cache_dir):
                    file_path = os.path.join(self.audio_cache_dir, filename)
                    try:
                        file_mod_time = os.path.getmtime(file_path)
                        
                        if current_time - file_mod_time > 86400:
                            os.remove(file_path)
                            
                            silk_path = f"{file_path}.silk"
                            pcm_path = f"{file_path}.pcm"
                            
                            if os.path.exists(silk_path):
                                os.remove(silk_path)
                                
                            if os.path.exists(pcm_path):
                                os.remove(pcm_path)
                    except Exception:
                        pass
            except Exception:
                pass
    
    def __del__(self):
        try:
            if self.msg_queue:
                try:
                    self.msg_queue.put({'type': 'exit', 'content': None})
                except:
                    pass
                    
            if self.ui_process and self.ui_process.is_alive():
                time.sleep(0.5)
                self.ui_process.terminate()
                self.ui_process.join(3)
                
            try:
                for filename in os.listdir(self.audio_cache_dir):
                    file_path = os.path.join(self.audio_cache_dir, filename)
                    try:
                        os.remove(file_path)
                        
                        silk_path = f"{file_path}.silk"
                        pcm_path = f"{file_path}.pcm"
                        
                        if os.path.exists(silk_path):
                            os.remove(silk_path)
                            
                        if os.path.exists(pcm_path):
                            os.remove(pcm_path)
                    except:
                        pass
            except:
                pass
        except:
            pass 