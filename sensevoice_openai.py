 Set the device with environment, default is cuda:0
# export SENSEVOICE_DEVICE=cuda:1

import os, re
from fastapi import FastAPI, File, UploadFile, Form, Request # 导入FastAPI相关的类
from fastapi.responses import HTMLResponse # 用于返回HTML响应
import torchaudio # PyTorch的音频处理库
from model import SenseVoiceSmall # 从本地的 model.py 文件导入 SenseVoiceSmall 类
from funasr.utils.postprocess_utils import rich_transcription_postprocess # 从funasr导入后处理函数
from io import BytesIO # 用于将字节串当作文件来处理

# 模型在ModelScope上的ID或本地路径
# model_dir = "iic/SenseVoiceSmall"
model_dir = "/app/SenseVoiceSmall"
# 加载预训练的SenseVoiceSmall模型
# SenseVoiceSmall.from_pretrained 是一个类方法，用于从指定路径加载模型权重和配置
# device=os.getenv("SENSEVOICE_DEVICE", "cuda:0") 表示：
#   优先使用环境变量 SENSEVOICE_DEVICE 指定的设备 (例如 cuda:1)
#   如果环境变量未设置，则默认使用 "cuda:0" (第一个NVIDIA GPU)
#   如果没有GPU或想用CPU，这里可以改成 "cpu"
m, kwargs = SenseVoiceSmall.from_pretrained(model=model_dir, device=os.getenv("SENSEVOICE_DEVICE", "cuda:0"))
m.eval() # 将模型设置为评估模式，这会关闭dropout等训练时才需要的层

# 定义一个正则表达式，用于后续移除文本中的特定模式 (例如 <|...|> 这样的标记)
regex = r"<\|.*\|>"

# 创建FastAPI应用实例
app = FastAPI()


# 定义根路径 "/" 的GET请求处理函数
@app.get("/", response_class=HTMLResponse)
async def root():
    # 返回一个简单的HTML页面，包含一个指向API文档 (/docs) 的链接
    # FastAPI会自动在 /docs 和 /redoc 生成交互式API文档界面
    return """
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset=utf-8>
            <title>Api information</title>
        </head>
        <body>
            <a href='./docs'>Documents of API</a>
        </body>
    </html>
    """

# 定义 "/api/v1/asr" 路径的POST请求处理函数，用于语音识别
@app.post("/v1/audio/transcriptions")
async def create_transcriptions(
    raw_request: Request,
    file: UploadFile = File(..., description="wav or mp3 audio in 16KHz"), # 接收单个音频文件
    model: str = Form("gpt-4o-transcribe") # Directly accept model as Form
):
    file_bytes = await file.read() # 读取上传文件的字节内容
    file_io = BytesIO(file_bytes) # 将字节串包装成类似文件的对象

    # torchaudio.load 可以从文件路径或类文件对象中加载音频
    waveform, audio_fs = torchaudio.load(file_io)
    file_io.close() # 关闭BytesIO对象

    # waveform.mean(0) 的作用:
    # 如果音频是多声道（例如立体声），这会取所有声道的平均值，将其转换为单声道。
    # 语音识别模型通常期望单声道输入。
    mono_waveform = waveform.mean(0)
    audios = [mono_waveform] # 将处理后的单声道音频张量放入列表中 (因为inference期望列表)
    
    # 调用SenseVoice模型的inference方法进行语音识别
    res = m.inference(
        data_in=audios,         # 输入处理后的音频张量列表 (现在只有一个)
        language="auto",        # 硬编码为"auto"，因为移除了语言参数
        use_itn=True,          # 是否使用逆文本正则化
        ban_emo_unk=False,      # 是否禁止未知情感的输出
        key=["audio_file"],     # 硬编码一个默认键名，因为移除了键名参数
        fs=audio_fs,            # 音频的采样率
        **kwargs,               # 其他从 from_pretrained 获取的参数
    )

    # 如果识别结果为空，返回空文本
    if len(res) == 0 or len(res[0]) == 0:
        return {"text": ""}

    # 对识别结果进行后处理
    # res[0] 假设是包含所有音频识别结果的列表
    # 提取第一个结果的文本
    first_result_text = res[0][0]["text"]
    
    # 使用之前定义的正则表达式 regex 移除文本中匹配 <|...|> 模式的子串
    clean_text = re.sub(regex, "", first_result_text, 0, re.MULTILINE)
    # 使用 funasr 提供的 rich_transcription_postprocess 函数进一步处理文本
    processed_text = rich_transcription_postprocess(clean_text)
    
    # 返回处理后的结果，只包含 'text' 字段
    return {"text": processed_text}


# ... (您上面提供的所有代码) ...

# 在脚本的最后添加以下内容：
if __name__ == "__main__":
    import uvicorn # 确保您已经安装了 uvicorn: pip install uvicorn

    print("Starting Uvicorn server sensevoice_app")
    # uvicorn.run() 的第一个参数通常是 "文件名:FastAPI实例名" 的字符串，
    # 但如果是在 if __name__ == "__main__": 块中直接运行，
    # 并且 app 实例在当前作用域内，可以直接传递 app 对象。
    # 为了简单和通用，直接传递 app 对象即可。
    uvicorn.run(
        app,
        host="0.0.0.0",  # 监听所有可用IP地址
        port=8000,       # 指定监听端口为 8000 (您可以根据需要更改)
        # reload=True    # 可选: 在开发时，如果代码更改，服务器会自动重启。生产环境通常不开启。
    )