import { Upload, FileAudio, FileVideo, Loader2, CheckCircle2, X, Copy, Check } from 'lucide-react'
import { useState, useRef } from 'react'
import { cn } from './lib/utils'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './components/ui/card'
import { Button } from './components/ui/button'
import { Progress } from './components/ui/progress'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './components/ui/tabs'

const ALLOWED_VIDEO = ['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv', 'wmv']
const ALLOWED_AUDIO = ['mp3', 'wav', 'm4a', 'aac', 'ogg', 'flac', 'wma']
const ALL_ALLOWED = [...ALLOWED_VIDEO, ...ALLOWED_AUDIO]
const MAX_SIZE = 500 * 1024 * 1024

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function StepIcon({ done, running, children }) {
  return (
    <div className={cn(
      'w-8 h-8 rounded-full flex items-center justify-center text-sm',
      done && 'bg-green-100 text-green-600',
      running && 'bg-blue-100 text-blue-600 animate-pulse',
      !done && !running && 'bg-gray-100 text-gray-400'
    )}>
      {done ? <CheckCircle2 size={16} /> : children}
    </div>
  )
}

function UploadCard({ onFileSelect }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef()

  const handleDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) validateAndSelect(file)
  }

  const validateAndSelect = (file) => {
    const ext = file.name.split('.').pop().toLowerCase()
    if (!ALL_ALLOWED.includes(ext)) {
      alert('不支持的文件格式')
      return
    }
    if (file.size > MAX_SIZE) {
      alert('文件过大，请选择小于 500MB 的文件')
      return
    }
    onFileSelect(file)
  }

  return (
    <Card className="w-full max-w-md mx-auto">
      <CardHeader className="text-center">
        <CardTitle className="flex items-center justify-center gap-2">
          <FileVideo size={20} />
          视频转文字
        </CardTitle>
        <CardDescription>Whisper Large-v3 + MiniMax AI</CardDescription>
      </CardHeader>
      <CardContent>
        <div
          className={cn(
            'border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors',
            dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
          )}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept="video/*,audio/*"
            className="hidden"
            onChange={(e) => e.target.files[0] && validateAndSelect(e.target.files[0])}
          />
          <Upload className="mx-auto mb-3 text-gray-400" size={32} />
          <p className="text-sm text-gray-600">选择视频或音频文件</p>
          <p className="text-xs text-gray-400 mt-1">支持 {ALL_ALLOWED.join(', ')}</p>
        </div>
      </CardContent>
    </Card>
  )
}

function FileCard({ file, onRemove }) {
  return (
    <Card className="w-full max-w-md mx-auto">
      <CardContent className="p-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-100 flex items-center justify-center">
            <FileAudio className="text-blue-600" size={20} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{file.name}</p>
            <p className="text-xs text-gray-500">{formatSize(file.size)}</p>
          </div>
          <Button variant="ghost" size="icon" onClick={onRemove}>
            <X size={16} />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function ProgressCard({ phase, progress, steps, rawText, polishedText }) {
  const isPolishing = phase === 'polish'

  return (
    <Card className="w-full max-w-3xl mx-auto">
      <CardHeader className="pb-4">
        <CardTitle className="text-base flex items-center gap-2">
          {phase === 'done' ? <CheckCircle2 size={18} className="text-green-600" /> : <Loader2 size={18} className="animate-spin text-blue-600" />}
          {phase === 'done' ? '处理完成' : isPolishing ? 'AI 润色中...' : phase === 'transcribe' ? '转写中...' : '上传中...'}
        </CardTitle>
        <CardDescription>{progress}%</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Progress value={progress} />

        <div className="space-y-2">
          {['上传文件', '语音转写', 'AI 润色'].map((label, i) => {
            const stepMap = ['Upload', 'Transcribe', 'Polish']
            const step = stepMap[i]
            const done = steps[step] === 'done'
            const running = steps[step] === 'running'
            const icons = ['📤', '📝', '✨']
            const statusText = done ? '完成' : running ? '进行中...' : '等待中'
            return (
              <div key={step} className="flex items-center gap-3 text-sm">
                <StepIcon done={done} running={running}>{icons[i]}</StepIcon>
                <span className={cn(done && 'text-green-600', running && 'text-blue-600')}>{label}</span>
                <span className="text-xs text-gray-400 ml-auto">{statusText}</span>
              </div>
            )
          })}
        </div>

        {isPolishing ? (
          <div className="grid grid-cols-2 gap-3 mt-4">
            <div>
              <p className="text-xs text-gray-500 mb-1">📝 原文（转写完成）</p>
              <div className="bg-gray-100 rounded-lg p-3 text-sm text-gray-700 min-h-32 max-h-48 overflow-y-auto whitespace-pre-wrap">
                {rawText || '（无内容）'}
              </div>
            </div>
            <div>
              <p className="text-xs text-gray-500 mb-1">✨ 润色中...</p>
              <div className="bg-blue-50 rounded-lg p-3 text-sm text-gray-700 min-h-32 max-h-48 overflow-y-auto whitespace-pre-wrap">
                {polishedText || '正在润色，请稍候...'}
              </div>
            </div>
          </div>
        ) : (
          <>
            {rawText && (
              <div className="mt-4">
                <p className="text-xs text-gray-500 mb-1">📝 实时转写：</p>
                <div className="bg-gray-50 rounded-lg p-3 text-sm text-gray-700 min-h-20 max-h-32 overflow-y-auto whitespace-pre-wrap">
                  {rawText}
                </div>
              </div>
            )}
            {polishedText && (
              <div className="mt-2">
                <p className="text-xs text-gray-500 mb-1">✨ AI 润色：</p>
                <div className="bg-blue-50 rounded-lg p-3 text-sm text-gray-700 min-h-20 max-h-32 overflow-y-auto whitespace-pre-wrap">
                  {polishedText}
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function ResultCard({ rawText, polishedText, summaryText, polishError, charCount, onReset }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    const text = polishedText || polishError || ''
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Card className="w-full max-w-6xl mx-auto">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>转换结果</CardTitle>
          <Button variant="outline" size="sm" onClick={onReset}>
            重新开始
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-xs text-gray-500 mb-2 font-medium">📝 原始转写</p>
            <div className="bg-gray-50 rounded-xl p-4 text-sm whitespace-pre-wrap min-h-48 max-h-96 overflow-y-auto">
              {rawText || '（无内容）'}
            </div>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-2 font-medium">✨ AI 润色</p>
            <div className="bg-blue-50 rounded-xl p-4 text-sm whitespace-pre-wrap min-h-48 max-h-96 overflow-y-auto">
              {polishedText || polishError || '（润色失败）'}
            </div>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-2 font-medium">🧠 AI 摘要与总结</p>
            <div className="bg-purple-50 rounded-xl p-4 text-sm whitespace-pre-wrap min-h-48 max-h-96 overflow-y-auto">
              {summaryText || '（等待摘要...）'}
            </div>
          </div>
        </div>
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-gray-500">字符数：{charCount || 0}</p>
          <Button onClick={handleCopy} size="sm">
            {copied ? <><Check size={14} /> 已复制</> : <><Copy size={14} /> 复制润色结果</>}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function App() {
  const [phase, setPhase] = useState('idle') // idle | uploading | transcribe | polish | done | error
  const [progress, setProgress] = useState(0)
  const [steps, setSteps] = useState({ Upload: 'pending', Transcribe: 'pending', Polish: 'pending' })
  const [selectedFile, setSelectedFile] = useState(null)
  const [rawText, setRawText] = useState('')
  const [polishedText, setPolishedText] = useState('')
  const [summaryText, setSummaryText] = useState('')
  const [polishError, setPolishError] = useState(null)
  const [charCount, setCharCount] = useState(0)
  const [errorMsg, setErrorMsg] = useState('')
  const taskIdRef = useRef(null)
  const eventSourceRef = useRef(null)

  const handleFileSelect = (file) => {
    setSelectedFile(file)
  }

  const handleRemoveFile = () => {
    setSelectedFile(null)
  }

  const handleStart = async () => {
    if (!selectedFile) return

    setPhase('uploading')
    setProgress(10)
    setSteps({ Upload: 'done', Transcribe: 'pending', Polish: 'pending' })
    setRawText('')
    setPolishedText('')
    setSummaryText('')
    setPolishError(null)

    const formData = new FormData()
    formData.append('file', selectedFile)
    formData.append('mode', 'all')

    try {
      const res = await fetch('/api/transcribe', { method: 'POST', body: formData })
      const data = await res.json()
      if (!data.task_id) throw new Error(data.error || '启动失败')
      taskIdRef.current = data.task_id
      startStream(data.task_id)
    } catch (e) {
      setErrorMsg(e.message)
      setPhase('error')
    }
  }

  let streamClosed = false

  const startStream = (taskId) => {
    streamClosed = false
    console.log('[SSE] connecting to', `/api/stream/${taskId}`)
    const es = new EventSource(`http://localhost:5000/api/stream/${taskId}`)
    eventSourceRef.current = es

    es.onmessage = (e) => {
      if (streamClosed) return
      try {
        const data = JSON.parse(e.data)
        console.log('[SSE] ←', data.type, data.progress)
        handleStreamData(data)
      } catch (err) {
        console.warn('[SSE] parse error:', err, e.data)
      }
    }

    es.onerror = (e) => {
      console.warn('[SSE] onerror', e, 'streamClosed:', streamClosed)
      if (!streamClosed) {
        es.close()
        streamClosed = true
      }
    }
  }

  const handleStreamData = (data) => {
    const type = data.type
    const prog = data.progress
    console.log('[handleStreamData]', type, 'progress:', prog)

    if (typeof prog === 'number' && !isNaN(prog)) {
      setProgress(Math.min(Math.max(prog, 0), 100))
    }

    if (type === 'chunk') {
      setPhase('transcribe')
      setSteps(s => ({ ...s, Transcribe: 'running' }))
      if (typeof data.text === 'string') setRawText(data.text)
    } else if (type === 'transcribe_done') {
      setSteps(s => ({ ...s, Transcribe: 'done' }))
    } else if (type === 'polish_start') {
      setPhase('polish')
      setSteps(s => ({ ...s, Polish: 'running' }))
    } else if (type === 'polish_char') {
      if (typeof data.text === 'string') setPolishedText(data.text)
    } else if (type === 'polish_done') {
      setSteps(s => ({ ...s, Polish: 'done' }))
    } else if (type === 'summary_start') {
      setSummaryText('')
    } else if (type === 'summary_char') {
      if (typeof data.text === 'string') setSummaryText(data.text)
    } else if (type === 'summary_done') {
      setPhase('done')
      setProgress(100)
      eventSourceRef.current?.close()
    } else if (type === 'done') {
      setPhase('done')
      setProgress(100)
      setSteps(s => ({ ...s, Polish: 'done' }))
      setRawText(typeof data.raw_text === 'string' ? data.raw_text : '')
      setPolishedText(typeof data.polished_text === 'string' ? data.polished_text : '')
      setPolishError(typeof data.polish_error === 'string' ? data.polish_error : null)
      setCharCount(typeof data.char_count === 'number' ? data.char_count : 0)
      eventSourceRef.current?.close()
    } else if (type === 'error') {
      setErrorMsg(typeof data.error === 'string' ? data.error : '处理失败')
      setPhase('error')
      eventSourceRef.current?.close()
    }
  }

  const handleReset = () => {
    streamClosed = true
    eventSourceRef.current?.close()
    setPhase('idle')
    setProgress(0)
    setSteps({ Upload: 'pending', Transcribe: 'pending', Polish: 'pending' })
    setSelectedFile(null)
    setRawText('')
    setPolishedText('')
    setSummaryText('')
    setPolishError(null)
    setCharCount(0)
    setErrorMsg('')
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-6 gap-4">
      <div className="w-full max-w-md text-center mb-2">
        <h1 className="text-2xl font-bold text-gray-900">📝 视频转文字</h1>
        <p className="text-sm text-gray-500 mt-1">Whisper Large-v3 + MiniMax AI</p>
      </div>

      {phase === 'idle' && !selectedFile && <UploadCard onFileSelect={handleFileSelect} />}

      {phase === 'idle' && selectedFile && (
        <div className="w-full max-w-md space-y-4">
          <FileCard file={selectedFile} onRemove={handleRemoveFile} />
          <div className="flex gap-2">
            <Button className="flex-1" onClick={handleStart}>开始处理</Button>
            <Button variant="outline" onClick={handleReset}>取消</Button>
          </div>
        </div>
      )}

      {(phase === 'uploading' || phase === 'transcribe' || phase === 'polish') && (
        <ProgressCard
          phase={phase}
          progress={progress}
          steps={steps}
          rawText={rawText}
          polishedText={polishedText}
        />
      )}

      {phase === 'done' && (
        <ResultCard
          rawText={rawText}
          polishedText={polishedText}
          summaryText={summaryText}
          polishError={polishError}
          charCount={charCount}
          onReset={handleReset}
        />
      )}

      {phase === 'error' && (
        <Card className="w-full max-w-md mx-auto border-red-200 bg-red-50">
          <CardContent className="p-6 text-center">
            <p className="text-red-600 mb-4">{errorMsg || '处理失败'}</p>
            <Button variant="outline" onClick={handleReset}>重新开始</Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default App