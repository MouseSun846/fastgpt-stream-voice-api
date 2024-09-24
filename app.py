import sys
import os, json, io
from flask_cors import CORS
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append('{}'.format(ROOT_DIR))
sys.path.append('{}/third_party/Matcha-TTS'.format(ROOT_DIR))

import numpy as np
from flask import Flask, request, Response,send_file
import torch
import torchaudio

from cosyvoice.utils.file_utils import load_wav

from pydub import AudioSegment
import torch
from hyperpyyaml import load_hyperpyyaml
from modelscope import snapshot_download
from cosyvoice.cli.frontend import CosyVoiceFrontEnd
from cosyvoice.cli.model import CosyVoiceModel
from cosyvoice.cli.cosyvoice import CosyVoice
cosyvoice = CosyVoice('/workspace/CosyVoice/pretrained_models/CosyVoice-300M/')

print(cosyvoice.list_avaliable_spks())

app = Flask(__name__)
CORS(app)  

@app.route("/v1/audio/speech", methods=['POST'])
def stream():
    question_data = request.get_json()
    tts_text = question_data.get('input')
    prompt_text = app_config['prompt_text']
    prompt_speech = load_wav('/workspace/CosyVoice/audio/'+app_config['prompt_speech'], 16000)
    prompt_audio = (prompt_speech.numpy() * (2**15)).astype(np.int16).tobytes()
    prompt_speech_16k = torch.from_numpy(np.array(np.frombuffer(prompt_audio, dtype=np.int16))).unsqueeze(dim=0)
    prompt_speech_16k = prompt_speech_16k.float() / (2**15)
    if not tts_text:
        return {"error": "Query parameter 'query' is required"}, 400
    def generate_stream():
        # 从 cosyvoice 逐块生成 PCM 数据
        for chunk in cosyvoice.stream(tts_text, prompt_text, prompt_speech_16k):
            float_data = chunk.numpy()  # 获取 PCM 浮点音频数据
            byte_data = (float_data * 32767).astype(np.int16).tobytes()  # 转换为 16-bit PCM 数据

            # 将这块 PCM 数据转换为 MP3 格式
            pcm_buffer = io.BytesIO(byte_data)  # 创建一个临时字节流
            audio_segment = AudioSegment(
                data=pcm_buffer.read(),
                sample_width=2,  # 16-bit PCM
                frame_rate=24000,  # 假设采样率为 24000 Hz
                channels=1  # 单声道
            )

            # 将 PCM 数据块转换为 MP3 格式
            mp3_buffer = io.BytesIO()
            audio_segment.export(mp3_buffer, format="mp3")
            mp3_buffer.seek(0)

            # 每次生成 MP3 数据块并通过 yield 发送
            while True:
                mp3_data = mp3_buffer.read(1024)  # 每次读取 1024 字节
                if not mp3_data:
                    break
                yield mp3_data  # 逐块传输
    return Response(generate_stream(), mimetype="audio/mpeg")                

if __name__ == "__main__":
    config_path = '/workspace/CosyVoice/audio/config.json'
    if not os.path.exists(config_path):
        print('Config file does not exist.')
        exit(1)
    global app_config
    with open(config_path, 'r', encoding='utf-8') as fr:
        app_config = json.load(fr)
    app.run(host='0.0.0.0', port=50000)