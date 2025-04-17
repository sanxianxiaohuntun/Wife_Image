import os
import http.client
import json
import re
import time

class QhaiTTS:

    def __init__(self, config=None):
        self.config = config or {}
        self.api_key = config.get('api_key', '')
        self.api_url = config.get('api_url', 'api.qhaigc.net').replace('https://', '').replace('http://', '')
        self.model = config.get('model', 'qhai-tts:永雏塔菲')
        self.max_text_length = config.get('max_text_length', 300)

        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_dir = os.path.join(self.plugin_dir, 'audio_cache')
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def clean_text(self, text):
        text = re.sub(r'\[:[\w\u4e00-\u9fa5]+\]', '', text)
        text = re.sub(r'\(.*?\)', '', text)
        text = re.sub(r'（.*?）', '', text)
        text = self._process_urls(text)
        text = self._process_numbers(text)
        text = self._process_symbols(text)
        text = re.sub(r'\s*\n\s*', '。', text)
        text = re.sub(r'。{2,}', '。', text)
        text = text.strip()
        
        return text
    
    def _process_numbers(self, text):
        def _should_split_digits(match):
            number = match.group()
            context_before = text[max(0, match.start() - 20):match.start()]
            phone_patterns = [
                r'电话[号码]?[是为:：]?',
                r'联系[方式]?[是为:：]?',
                r'[致]?电[:]?',
                r'手机[号码]?',
                r'[致]?电话[:]?',
                r'Tel[:.：]?',
                r'TEL[:.：]?',
                r'Phone[:.：]?',
            ]
            
            for pattern in phone_patterns:
                if re.search(pattern, context_before):
                    return True
                    
            if '-' in number or len(number) in [7, 8, 11]:
                return True
                
            return False

        text = re.sub(r'\d+[-\s]+\d+', 
                     lambda m: ' '.join(m.group()) if _should_split_digits(m) else m.group(), 
                     text)
        
        text = re.sub(r'\d+',
                     lambda m: ' '.join(m.group()) if _should_split_digits(m) else m.group(),
                     text)
        
        return text

    def _process_urls(self, text):
        text = re.sub(r'https?://[^\s<>"]+|www\.[^\s<>"]+', '网址链接', text)
        return text

    def _process_symbols(self, text):
        preserved_symbols = [
            '。', '，', '、', '；', '：', '？', '！',
            '—', '·',
            '.', ',', ';', ':', '?', '!',
            '"', '"', ''', ''',
            '\n', '\r', '\t', ' '
        ]
        
        preserved_pattern = '|'.join(map(re.escape, preserved_symbols))
        
        symbol_replacements = {
            r'@': '艾特',
            r'#': '井号',
            r'\$': '美元',
            r'%': '百分',
            r'&': '和',
            r'\+': '加',
            r'=': '等于',
            r'\^': '上尖号',
            r'\*': '星号',
            r'×': '乘以',
            r'÷': '除以',
            r'√': '根号',
            r'∑': '求和',
            r'∏': '求积',
            r'±': '正负',
            r'≠': '不等于',
            r'≤': '小于等于',
            r'≥': '大于等于',
            r'≈': '约等于',
            r'∞': '无穷',
            r'∵': '因为',
            r'∴': '所以',
            r'∠': '角',
            r'⊙': '圆',
            r'○': '圆',
            r'π': '派',
            r'∫': '积分',
            r'∮': '曲线积分',
            r'∪': '并集',
            r'∩': '交集',
            r'∈': '属于',
            r'∉': '不属于',
            r'⊆': '包含于',
            r'⊂': '真包含于',
            r'⊇': '包含',
            r'⊃': '真包含',
            r'∅': '空集',
            r'∀': '任意',
            r'∃': '存在',
            r'¬': '非',
            r'∧': '与',
            r'∨': '或',
            r'⇒': '推出',
            r'⇔': '等价于'
        }
        
        for symbol, replacement in symbol_replacements.items():
            text = re.sub(symbol, replacement, text)
        
        text = re.sub(f'[^\\w\\s{preserved_pattern}]', '', text)
        
        return text

    def clean_markdown(self, text):
        pattern = r'<think>[\s\S]*?</think>'
        iteration = 0
        max_iterations = 10
        
        while "<think>" in text and iteration < max_iterations:
            if not re.findall(pattern, text):
                break
            text = re.sub(pattern, '', text)
            text = re.sub(r'\n\s*\n', '\n', text.strip())
            iteration += 1
        
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`[^`]*`', '', text)
        text = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', text)
        text = re.sub(r'!\[([^\]]*)\]\([^\)]*\)', '', text)
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*\*([^\*]*)\*\*', r'\1', text)
        text = re.sub(r'\*([^\*]*)\*', r'\1', text)
        text = re.sub(r'__([^_]*)__', r'\1', text)
        text = re.sub(r'_([^_]*)_', r'\1', text)
        text = re.sub(r'^\s*>\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'[~…]+', '', text)
        text = re.sub(r'\s*\n\s*', '。', text)
        text = re.sub(r'。{2,}', '。', text)
        text = text.strip()
        
        return text
    
    def text_to_speech(self, text):
        if not text:
            return None
            
        if len(text) > self.max_text_length:
            text = text[:self.max_text_length]
        
        text = self.clean_text(text)
        
        if not text:
            return None
            
        if not self.api_key:
            return None
        
        try:
            conn = http.client.HTTPSConnection(self.api_url)
            
            payload = json.dumps({
                "model": self.model,
                "input": text
            })
            
            headers = {
                'Authorization': self.api_key,
                'User-Agent': 'Wife_image/1.0.0',
                'Content-Type': 'application/json',
                'Accept': '*/*',
                'Host': self.api_url,
                'Connection': 'keep-alive'
            }
            
            conn.request("POST", "/v1/audio/speech", payload, headers)
            
            response = conn.getresponse()
            
            data = response.read()
            
            if response.status == 200 and response.getheader('Content-Type', '').startswith('audio/'):
                timestamp = int(time.time())
                filename = f"tts_{timestamp}.mp3"
                output_path = os.path.join(self.cache_dir, filename)
                
                with open(output_path, "wb") as f:
                    f.write(data)
                
                return output_path
            else:
                try:
                    error_msg = data.decode("utf-8")
                except UnicodeDecodeError:
                    error_msg = "无法解码的错误响应"
                
                return None
                
        except Exception as e:
            return None
        finally:
            conn.close()