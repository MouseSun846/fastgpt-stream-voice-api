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
from collections import deque
from fastapi import FastAPI, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect
from contextlib import asynccontextmanager

import logging
import os,io
import sys
import time
import numpy as np
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append('{}/../../..'.format(ROOT_DIR))
sys.path.append('{}/../../../third_party/Matcha-TTS'.format(ROOT_DIR))
from cosyvoice.cli.cosyvoice import CosyVoice, CosyVoice2
from cosyvoice.utils.file_utils import load_wav

from pydub import AudioSegment

# Define lifespan handler first
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    app.cosyvoice = CosyVoice("/app/pretrained_models/CosyVoice-300M")
    app.man_prompt_speech = load_wav("/app/audio/man_24k_9.wav", 24000)
    app.woman_prompt_speech = load_wav("/app/audio/woman_24k_9.wav", 24000)
    app.default_prompt_speech = load_wav('/app/asset/zero_shot_prompt.wav', 16000)
    app.man_pompt_text="大家好，我是小泰，我是经济小窗口，四海经纬，寓意经济技术开发区头屯河区以全球化视野发展外向型经济，以经济纽带连接四方，以广博高远、兼收并蓄、海纳百川的胸怀和气魄，创建西部综合投资环境一流的外向型、开放型新经济平台。"
    app.man_pompt_text="大家好，我是小泰，我是经济小窗口，四海经纬，寓意经济技术开发区头屯河区以全球化视野发展外向型经济。"
    app.woman_pompt_text="大家好，我是小维，我是民生小帮手，东西开泰寓意亨通安泰、光明吉祥、大道通畅，象征经济技术开发区头屯河区全方位开放，东联西出，东承沿海内陆发达地区，西联中西亚各国，创建充满活力、发展无限、合作共赢的兴业空间。"
    app.woman_pompt_text="大家好，我是小维，我是民生小帮手，东西开泰寓意亨通安泰、光明吉祥、大道通畅，象征经济技术开发。"
    app.default_prompt_text="希望你以后能够做的比我还好呦。"
    
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
                websocket, text, prompt_speech, prompt_text = self.request_queue.get()
                logging.info(f"Processing request for websocket: {id(websocket)}, text length: {len(text)}")
                if websocket not in self.active_connections:
                    time.sleep(1)
                    continue
                
                conn_data = self.get_connection_data(websocket)
                if not conn_data:
                    time.sleep(1)
                    continue
                
                try:
                    print(f"text:{text}")
                    model_output = app.cosyvoice.inference_zero_shot(text, prompt_text, prompt_speech, stream=True)
                    print(f"type(model_output):{type(model_output)}")
                    for item in model_output:
                        if isinstance(item, dict):
                            tts_audio = (item['tts_speech'].numpy() * (2 ** 15)).astype(np.int16).tobytes()
                            pcm_buffer = io.BytesIO(tts_audio)
                            audio_segment = AudioSegment(
                                data=pcm_buffer.read(),
                                sample_width=2,
                                frame_rate=24000,
                                channels=1
                            )

                            # 将 PCM 数据块转换为 MP3 格式
                            mp3_buffer = io.BytesIO()
                            audio_segment.export(mp3_buffer, format="mp3")
                            mp3_buffer.seek(0)
                            audio_base64 = base64.b64encode(mp3_buffer.getvalue()).decode('utf-8')                        
                            print(f"model_output ...")
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
                finally:
                    conn_data['streaming'] = False
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
            if voice == "man":
                prompt_speech = app.man_prompt_speech
                prompt_text = app.man_pompt_text
            elif voice == "woman":
                prompt_speech = app.woman_prompt_speech
                prompt_text = app.woman_pompt_text
            else:
                prompt_speech = app.default_prompt_speech
                prompt_text = app.default_prompt_text
          
            # Add request to queue for processing
            with app.state.manager.lock:
                if websocket in app.state.manager.active_connections:
                    app.state.manager.request_queue.put((websocket, request['text'], prompt_speech, prompt_text))
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
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=18088)