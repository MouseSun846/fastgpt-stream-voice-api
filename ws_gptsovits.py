"""
ws_voice.py
This module implements both a FastAPI-based text-to-speech API compatible with OpenAI's interface specification
and a websocket-based streaming TTS interface.

Main features and improvements:
- Support both REST API and websocket streaming interfaces
- Use app.state to manage global state, ensuring thread safety
- Add exception handling and unified error responses to improve stability  
- Support multiple voice options and audio formats for greater flexibility
- Add input validation to ensure the validity of request parameters
- Support additional OpenAI TTS parameters (e.g., speed) for richer functionality
- Implement health check endpoint for easy service status monitoring
- Use asyncio.Lock to manage model access, improving concurrency performance
- Load and manage speaker embedding files to support personalized speech synthesis
- Support real-time audio streaming via websocket
"""



import io
import os
import sys
import asyncio
import base64
import json
import threading
import queue
from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect
from contextlib import asynccontextmanager

import logging
import os,io
import sys
import time

now_dir = os.getcwd()
sys.path.append(now_dir)
sys.path.append("%s/GPT_SoVITS" % (now_dir))

import uvicorn
from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config
from pydub import AudioSegment


# man http://112.29.111.160:18011/gptsovits/tts?text=居住在中国内地的中国公民在内地收养登记、解除收养关系登记-办事指南。&text_lang=zh&ref_audio_path=audio/man_24k_9.wav&prompt_lang=zh&prompt_text=大家好，我是小泰，我是经济小窗口，四海经纬，寓意经济技术开发区头屯河区以全球化视野发展外向型经济。&text_split_method=cut5&batch_size=1&media_type=wav&streaming_mode=false

# woman http://112.29.111.160:18011/gptsovits/tts?text=居住在中国内地的中国公民在内地收养登记、解除收养关系登记-办事指南。&text_lang=zh&ref_audio_path=audio/woman_24k_9.wav&prompt_lang=zh&prompt_text=大家好，我是小维，我是民生小帮手，东西开泰寓意亨通安泰、光明吉祥、大道通畅，象征经济技术开发。&text_split_method=cut5&batch_size=1&media_type=wav&streaming_mode=false# Define lifespan handler first



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    tts_config = TTS_Config("/workspace/GPT-SoVITS/GPT_SoVITS/configs/tts_infer.yaml")
    app.tts_pipeline = TTS(tts_config)
    
    # Initialize connection manager
    app.state.manager = ConnectionManager(asyncio.get_event_loop())
    app.state.manager.cleanup_task = asyncio.create_task(
        app.state.manager._cleanup_stale_connections()
    )
    
    yield
    
    # Shutdown logic
    app.state.manager.cleanup_task.cancel()
    try:
        await app.state.manager.cleanup_task
    except asyncio.CancelledError:
        pass
    app.state.manager.shutdown()

# Initialize FastAPI application with lifespan handler
app = FastAPI(lifespan=lifespan)

# Websocket connection manager with per-connection state
class ConnectionManager:
    def __init__(self, loop):
        self.active_connections = {}
        self.lock = threading.Lock()
        self.request_queue = queue.Queue()
        self._stop_event = threading.Event()
        self.main_loop = loop
        self.worker_thread = threading.Thread(target=self._process_requests)
        self.worker_thread.daemon = True
        self.worker_thread.start()
        self.connection_timeout = 300  # 5 minute timeout
        self.heartbeat_interval = 30  # 30 seconds
        self.cleanup_task = None
    def tts_handle(self,req: dict, websocket: WebSocket):
        """
        Text to speech handler.

        Args:
            req (dict):
                {
                    "text": "",                   # str.(required) text to be synthesized
                    "text_lang: "",               # str.(required) language of the text to be synthesized
                    "ref_audio_path": "",         # str.(required) reference audio path
                    "aux_ref_audio_paths": [],    # list.(optional) auxiliary reference audio paths for multi-speaker synthesis
                    "prompt_text": "",            # str.(optional) prompt text for the reference audio
                    "prompt_lang": "",            # str.(required) language of the prompt text for the reference audio
                    "top_k": 5,                   # int. top k sampling
                    "top_p": 1,                   # float. top p sampling
                    "temperature": 1,             # float. temperature for sampling
                    "text_split_method": "cut5",  # str. text split method, see text_segmentation_method.py for details.
                    "batch_size": 1,              # int. batch size for inference
                    "batch_threshold": 0.75,      # float. threshold for batch splitting.
                    "split_bucket: True,          # bool. whether to split the batch into multiple buckets.
                    "speed_factor":1.0,           # float. control the speed of the synthesized audio.
                    "fragment_interval":0.3,      # float. to control the interval of the audio fragment.
                    "seed": -1,                   # int. random seed for reproducibility.
                    "media_type": "wav",          # str. media type of the output audio, support "wav", "raw", "ogg", "aac".
                    "streaming_mode": False,      # bool. whether to return a streaming response.
                    "parallel_infer": True,       # bool.(optional) whether to use parallel inference.
                    "repetition_penalty": 1.35    # float.(optional) repetition penalty for T2S model.
                    "sample_steps": 32,           # int. number of sampling steps for VITS model V3.
                    "super_sampling": False,       # bool. whether to use super-sampling for audio when using VITS model V3.
                }
        returns:
            StreamingResponse: audio stream response.
        """
        req["return_fragment"] = True

        try:
            tts_generator = app.tts_pipeline.run(req)
            for sr, chunk in tts_generator:
                pcm_buffer = io.BytesIO(chunk)
                audio_segment = AudioSegment(
                    data=pcm_buffer.read(),
                    sample_width=2,
                    frame_rate=sr,
                    channels=1
                )

                # 将 PCM 数据块转换为 MP3 格式
                mp3_buffer = io.BytesIO()
                audio_segment.export(mp3_buffer, format="mp3")
                mp3_buffer.seek(0)
                audio_base64 = base64.b64encode(mp3_buffer.getvalue()).decode('utf-8')     
                if websocket in self.active_connections:
                    asyncio.run_coroutine_threadsafe(
                            websocket.send_json({
                                "status": 1,
                                "audio": audio_base64
                            }),
                            self.main_loop
                        ).result()
                        
            print(f"model_output end")
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({
                    "status": 2,
                    "signal": "end"
                }),
                self.main_loop
            ).result()                
        except Exception as e:
            logging.error(e)
            

    def tts_get_endpoint(
        self,
        text: str = None,
        spkid: str = "man",
        websocket: WebSocket=None,
    ):
        if spkid == "man":
            req = {
                "text": text,
                "text_lang": "zh",
                "ref_audio_path": "audio/man_24k_9.wav",
                "aux_ref_audio_paths": None,
                "prompt_text": "大家好，我是小泰，我是经济小窗口，四海经纬，寓意经济技术开发区头屯河区以全球化视野发展外向型经济。",
                "prompt_lang": "zh",
                "top_k": 5,
                "top_p": 1,
                "temperature": 1,
                "text_split_method": "cut5",
                "batch_size": 1,
                "media_type": "wav",
                "streaming_mode": True,            
                "batch_threshold": float(0.75),
                "speed_factor": float(0.8),
                "split_bucket": True,
                "fragment_interval": 0.3,
                "seed": -1,
                "parallel_infer": True,
                "repetition_penalty": float(1.35),
                "sample_steps": int(32),
                "super_sampling": False,
            }
        else:
            req = {
                "text": text,
                "text_lang": "zh",
                "aux_ref_audio_paths": None,
                "ref_audio_path": "audio/woman_24k_9.wav",
                "prompt_text": "大家好，我是小维，我是民生小帮手，东西开泰寓意亨通安泰、光明吉祥、大道通畅，象征经济技术开发。",
                "prompt_lang": "zh",                
                "top_k": 5,
                "top_p": 1,
                "temperature": 1,
                "text_split_method": "cut5",
                "batch_size": 1,
                "media_type": "wav",
                "streaming_mode": True,            
                "batch_threshold": float(0.75),
                "speed_factor": float(0.8),
                "split_bucket": True,
                "fragment_interval": 0.3,
                "seed": -1,
                "parallel_infer": True,
                "repetition_penalty": float(1.35),
                "sample_steps": int(32),
                "super_sampling": False,
            }        
        return self.tts_handle(req, websocket)
    async def _cleanup_stale_connections(self):
        """Periodically check for and remove stale connections"""
        while not self._stop_event.is_set():
            await asyncio.sleep(60)  # Check every minute
            current_time = time.time()
            stale_connections = []
            with self.lock:
                for ws, data in list(self.active_connections.items()):
                    if current_time - data.get('last_active', 0) > self.connection_timeout:
                        stale_connections.append(ws)
                
                for ws in stale_connections:
                    logging.info(f"Disconnecting stale connection: {ws}")
                    self.disconnect(ws)

    def _process_requests(self):
        """Worker thread that processes TTS requests from the queue"""
        while not self._stop_event.is_set():
            try:
                logging.info(f"Queue size before get: {self.request_queue.qsize()}")
                websocket, text, voice = self.request_queue.get()
                logging.info(f"Processing request for websocket: {id(websocket)}, text length: {len(text)}")
                if websocket not in self.active_connections:
                    time.sleep(1)
                    continue
                
                conn_data = self.get_connection_data(websocket)
                if not conn_data:
                    time.sleep(1)
                    continue
                self.tts_get_endpoint(text, voice, websocket)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue
            except Exception as e:
                logging.error(f"Error processing TTS request: {str(e)}")
                time.sleep(1)
                websocket = None  # Ensure websocket is initialized
                if 'websocket' in locals() and websocket and websocket in self.active_connections:
                    asyncio.run_coroutine_threadsafe(
                        websocket.send_json({
                            "status": -1,
                            "signal": str(e)
                        }),
                        self.main_loop
                    ).result()

    def shutdown(self):
        """Stop the worker thread gracefully"""
        self._stop_event.set()
        # Empty the queue to unblock worker thread
        while not self.request_queue.empty():
            try:
                self.request_queue.get_nowait()
            except queue.Empty:
                break
        self.worker_thread.join(timeout=5.0)
        if self.worker_thread.is_alive():
            logging.warning("Worker thread did not shutdown gracefully")
        
    async def _heartbeat(self, websocket: WebSocket):
        """Send periodic pings to keep connection alive and detect disconnects"""
        try:
            while websocket in self.active_connections:
                await asyncio.sleep(self.heartbeat_interval)
                if websocket in self.active_connections:
                    try:
                        await websocket.send_json({"status": 0, "signal": "ping"})
                        with self.lock:
                            self.active_connections[websocket]['last_active'] = time.time()
                    except:
                        self.disconnect(websocket)
                        break
        except Exception as e:
            logging.error(f"Heartbeat error: {str(e)}")
            self.disconnect(websocket)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        with self.lock:
            # Generate a new connection ID even for reconnections
            conn_id = f"{id(websocket)}_{time.time()}"
            self.active_connections[websocket] = {
                'id': conn_id,
                'buffer': b'',
                'thread': None,
                'streaming': False,
                'last_active': time.time()
            }
            logging.info(f"New connection established: {conn_id}")
        # Start heartbeat task
        asyncio.create_task(self._heartbeat(websocket))

    def disconnect(self, websocket: WebSocket):
        with self.lock:
            if websocket in self.active_connections:
                conn_data = self.active_connections[websocket]
                logging.info(f"Disconnecting websocket {conn_data['id']}")
                
                if conn_data['thread'] and conn_data['thread'].is_alive():
                    conn_data['thread'].join()
                
                # Clear all queued requests for this connection
                while True:
                    try:
                        self.request_queue.get_nowait()
                    except queue.Empty:
                        break
                    logging.info(f"Cleared all pending requests for websocket {conn_data['id']}")
                
                del self.active_connections[websocket]
                logging.info(f"Websocket {conn_data['id']} removed from active connections")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        if websocket in self.active_connections:
            await websocket.send_text(message)

    def get_connection_data(self, websocket: WebSocket):
        with self.lock:
            return self.active_connections.get(websocket)

    async def broadcast(self, message: str):
        with self.lock:
            for websocket in list(self.active_connections.keys()):
                try:
                    await websocket.send_text(message)
                except:
                    self.disconnect(websocket)

@app.websocket("/ws/tts")
async def websocket_endpoint(websocket: WebSocket):
    """Websocket endpoint for streaming TTS"""
    # Clean up any existing connection for this websocket
    if websocket in app.state.manager.active_connections:
        app.state.manager.disconnect(websocket)
    
    await app.state.manager.connect(websocket)
    try:
        while True:
            try:
                data = await websocket.receive_text()
                request = json.loads(data)
            except WebSocketDisconnect as e:
                logging.info(f"Client disconnected: {e.code} - {e.reason}")
                break
                
            # Handle start signal from client
            if request.get('signal') == 'start':
                await websocket.send_json({
                    "status": 0,
                    "signal": "Server ready"
                })
                continue
                
            # Validate request
            if "text" not in request:
                await websocket.send_json({"status": -1, "signal": "Missing text parameter"})
                continue

            # Get speaker embedding
            voice = request.get("spk_id", "man")
            # Add request to queue for processing
            with app.state.manager.lock:
                if websocket in app.state.manager.active_connections:
                    app.state.manager.request_queue.put((websocket, request['text'], voice))
                    await websocket.send_json({
                        "status": 0,
                        "signal": "Request queued for processing"
                    })

    except Exception as e:
        logging.error(f"Websocket error: {str(e)}")
        await websocket.send_json({
            "status": -1,
            "signal": str(e)
        })
    finally:
        logging.info("Client disconnected, cleaning up websocket connection")
        app.state.manager.disconnect(websocket)
        logging.info("Websocket cleanup completed")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=18088)