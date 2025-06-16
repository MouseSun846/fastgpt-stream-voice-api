<script setup lang="ts">
import { ref, onMounted } from 'vue'

const textInput = ref('居住在中国内地的中国公民在内地收养登记、解除收养关系登记-办事指南')
const streamTextInput = ref('居住在中国内地的中国公民在内地收养登记、解除收养关系登记-办事指南')
const status = ref('Ready')
const voice = ref('default') // Default to default voice

class PaddleSpeechTTSClient {
  private socket: WebSocket | null = null
  private sessionId: string | null = null
  private audioQueue: AudioBuffer[] = []
  private isPlaying = false
  private audioContext: AudioContext | null = null

  constructor(private url: string) {}

  private initAudioContext() {
    if (!this.audioContext) {
      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
    }
  }

  private async playNext() {
    this.initAudioContext()
    if (this.isPlaying || this.audioQueue.length === 0) return
    
    this.isPlaying = true
    const nextAudio = this.audioQueue.shift()
    if (nextAudio && this.audioContext) {
      const source = this.audioContext.createBufferSource()
      source.buffer = nextAudio
      source.connect(this.audioContext.destination)
      source.onended = () => {
        this.isPlaying = false
        this.playNext() // Play next item if available
      }
      source.start()
    } else {
      this.isPlaying = false
    }
  }

  private startPlaybackLoop() {
    // No longer needed as we use event-driven approach
  }

  async init(): Promise<void> {
    this.socket = new WebSocket(this.url)
    
    return new Promise<void>((resolve, reject) => {
      if (!this.socket) return reject(new Error('WebSocket initialization failed'))
      
      this.socket.onmessage = async (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data)
          
          if (data.status === 0 && data.signal === 'server ready') {
            this.sessionId = data.session || ''
            status.value = 'Server ready'
          } 
          else if (data.status === -1) {
            // Error case
            status.value = 'Server error'
            await this.endStream()
          }
          else if (data.status === 1 || data.status === 2) {
            if (data.status === 2) {
              // Last chunk
              // await this.endStream()
              // status.value = 'Ready'
              return
            }
            if (data.audio) {
              try {
                // Initialize AudioContext if not already created
                if (!this.audioContext) {
                  this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
                }

                // Decode base64 data
                const binaryString = atob(data.audio)
                const bytes = new Uint8Array(binaryString.length)
                for (let i = 0; i < binaryString.length; i++) {
                  bytes[i] = binaryString.charCodeAt(i)
                }

                // Create MP3 blob directly from the bytes
                const blob = new Blob([bytes], { type: 'audio/mpeg' })
                const arrayBuffer = await blob.arrayBuffer()
                const audioBuffer = await this.audioContext?.decodeAudioData(arrayBuffer)
                if (audioBuffer) {
                  this.audioQueue.push(audioBuffer)
                  status.value = 'Queued audio chunk...'
                  this.playNext() // Trigger playback immediately
                }
              } catch (error) {
                console.error('Error processing audio:', error)
                status.value = `Error: ${error instanceof Error ? error.message : String(error)}`
              }
            }

          }
        } catch (error) {
          console.error('Error processing message:', error)
          status.value = `Error: ${error instanceof Error ? error.message : String(error)}`
        }
      }

      this.socket.onopen = () => {
        // Send start signal
        this.socket?.send(JSON.stringify({
          task: 'tts',
          signal: 'start'
        }))
        status.value = 'Connecting...'
        this.startPlaybackLoop()
        resolve()
      }
      
      this.socket.onerror = (error: Event) => {
        status.value = 'Connection error'
        reject(new Error('WebSocket error'))
      }
    })
  }



  async streamText(text: string): Promise<void> {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({
        text: text,
        spk_id: voice.value
      }))
    } else {
      throw new Error('WebSocket is not connected')
    }
  }

  async endStream(): Promise<void> {
    if (this.socket && this.sessionId) {
      this.socket.send(JSON.stringify({
        task: 'tts',
        signal: 'end',
        session: this.sessionId
      }))
      this.socket.close()
      this.sessionId = null
    }
  }

  isConnected(): boolean {
    return this.socket !== null && this.socket.readyState === WebSocket.OPEN
  }
}

const ttsClient = new PaddleSpeechTTSClient('/ws/tts')

async function initTTS() {
  try {
    status.value = 'Initializing TTS...'
    await ttsClient.init()
    status.value = 'Ready'
  } catch (error: unknown) {
    status.value = `Initialization failed: ${error instanceof Error ? error.message : String(error)}`
  }
}

async function cleanMarkdown(content: string) {
    let cleanedContent = content;
    // 替换Markdown格式标记为空字符串
    cleanedContent = cleanedContent
        // 移除frontmatter
        .replace(/---[\s\S]*?---/g, "")
        // 移除代码块
        .replace(/```[\s\S]*?```/g, "")
        // 移除HTML标签
        .replace(/<[^>]*>/g, "")
        // 移除换行符
        .replace(/\n/g, "")
        .replace(/#/g, "")
        .replace(/-/g, "")
        // 移除标题符号
        .replace(/^#{1,6}\s+/g, "")
        // 移除列表标记
        .replace(/^(\s*[-*+]|\d+\.)\s+/g, "")
        // 移除块引用符号
        .replace(/^>\s*/g, "")
        // 移除表格行
        .replace(/\|.*\|/g, "")
        // 移除水平线
        .replace(/\s[-*_]{3,}\s/g, "")
        // 移除强调符号 (粗体、斜体、删除线)
        .replace(/(\*\*|__)(.*?)(\*\*|__)/g, "$2")
        .replace(/(\*|_)(.*?)(\*|_)/g, "$2")
        .replace(/~~(.*?)~~/g, "$2")
        // 移除链接和图片标记
        .replace(/!\[(.*?)\]\(.*?\)/g, "$1")
        .replace(/\[(.*?)\]\(.*?\)/g, "$1")
        // 移除脚注引用
        .replace(/\[\^\d+\]/g, "")
        // 移除特殊块 (如:::info)
        .replace(/:::[^:]*:::/g, "")
        // 移除中文标点符号
        .replace(/[：；《》]/g, "");
    
    // 移除多余的空白和换行符
    cleanedContent = cleanedContent
        // 移除连续的空行
        .replace(/\n{3,}/g, "\n\n")
        // 移除每行开头的空白
        .replace(/^\s+/gm, "")
        // 移除每行结尾的空白
        .replace(/\s+$/gm, "")
        // 移除文档开头和结尾的空白
        .trim();
    
    return cleanedContent;
}


async function sendToLLM(text: string) {
    try {
        const response = await fetch('/conversation/v1/responses', {
            method: 'POST',
            mode: 'cors',
            headers: {
                'Accept': 'text/event-stream',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                model: "gpt-4.1",
                user: "lsy0123",
                instructions: "",
                input: text,
                stream: true,
                previous_response_id: "",
                tools: [
                    {
                        type: "file_search",
                        vector_store_ids: ["test0922"]
                    },
                    {
                        type: "gov_service_classify"
                    }
                ],
                metadata: {
                    assistant_id: "4d366a43d43a4d35ad3a3a3da3d33"
                }
            })
        });

        if (!response.ok) {
            throw new Error(`LLM API error: ${response.status}`);
        }

        if (!response.body) {
            throw new Error('No response body from LLM API');
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        let accumulatedText = '';
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                // Process any remaining accumulated text
                if (accumulatedText.trim()) {
                    console.log(accumulatedText);
                    // await ttsClient.streamText(accumulatedText);
                }
                break;
            }

            buffer += decoder.decode(value, { stream: true });
            const events = buffer.split('\n\n');
            buffer = events.pop() || '';

            for (const event of events) {
                if (event.includes('response.output_text.delta')) {
                    const data = JSON.parse(event.replace('event: response.output_text.delta\ndata: ', ''));
                    if (data.delta) {
                        accumulatedText += data.delta;
                        
                        if (data.delta.includes('\n')) {                   
                            const parts = accumulatedText.split('\n');
                            // Check text before newline
                            const textBeforeNewline = parts.slice(0, -1).join('\n');
                            if (textBeforeNewline.length >= 32) {
                                let fmtText = await cleanMarkdown(textBeforeNewline)
                                console.log(fmtText);
                                await ttsClient.streamText(fmtText);
                                accumulatedText = parts.slice(-1)[0];
                            }
                        }
                    }
                } else if (event.includes('response.output_text.done')) {
                  let fmtText = await cleanMarkdown(accumulatedText)
                  console.log(fmtText);
                  await ttsClient.streamText(fmtText);                  
                }
            }
        }
    } catch (error) {
        console.error('LLM processing error:', error);
        status.value = `Error: ${error instanceof Error ? error.message : String(error)}`;
    }
}

async function streamText() {
  if (!streamTextInput.value.trim()) {
    status.value = 'Please enter some text to stream'
    return
  }

  status.value = 'Streaming...'
  
  try {
    if (!ttsClient.isConnected()) {
      await initTTS()
    }
    await ttsClient.streamText(streamTextInput.value)
    status.value = 'Streaming complete'
  } catch (error: unknown) {
    status.value = `Error: ${error instanceof Error ? error.message : String(error)}`
  }
}

async function synthesize() {
  if (!textInput.value.trim()) {
    status.value = 'Please enter some text'
    return
  }

  status.value = 'Processing...'
  
  try {
    // Check if connection is established, if not try to reconnect
    if (!ttsClient.isConnected()) {
      await initTTS()
    }
    await sendToLLM(textInput.value)
    status.value = 'Processing audio...'
  } catch (error: unknown) {
    status.value = `Error: ${error instanceof Error ? error.message : String(error)}`
  } finally {
    // Don't end stream here - wait for server to send all audio chunks
  }
}

onMounted(() => {
  initTTS()
})
</script>

<template>
  <div class="tts-demo">
    <h1>PaddleSpeech TTS Demo</h1>
    <div class="card">
      <textarea v-model="textInput" placeholder="Enter text to convert to speech..."></textarea>
      <div>
        <button @click="synthesize">知识库检索测试，Generate Speech</button>
      </div>
    </div>

    <div class="card">
        <textarea v-model="streamTextInput" placeholder="Enter text to convert to speech..."></textarea>        
        <div>
          <button @click="streamText">输入指定文本测试，Stream Text</button>
        </div>
    </div>

    <div class="status">{{ status }}</div>
    
    <div class="voice-selection">
      <span>音色选择:</span>
      <label>
        <input type="radio" v-model="voice" value="default"> Default Voice
      </label>
      <label>
        <input type="radio" v-model="voice" value="woman"> Female Voice
      </label>
      <label>
        <input type="radio" v-model="voice" value="man"> Male Voice
      </label>
    </div>
  </div>
</template>

<style scoped>
.tts-demo {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  padding: 20px;
}

textarea {
  width: 100%;
  height: 100px;
  margin-bottom: 10px;
}

button {
  padding: 10px 20px;
  background-color: #4CAF50;
  color: white;
  border: none;
  cursor: pointer;
}

button:disabled {
  background-color: #cccccc;
}

.audio-controls {
  margin-top: 20px;
}

.voice-selection {
  margin-top: 15px;
  display: flex;
  gap: 20px;
}

.voice-selection label {
  display: flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
}

.status {
  margin-top: 10px;
  color: #666;
}
</style>
