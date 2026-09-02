// tus 断点续传上传面板：可暂停/继续，断线或刷新后按服务端 offset 续传。
// 业务校验以后端为准，这里只做传输与进度展示。
import { useRef, useState, type DragEvent } from 'react'
import * as tus from 'tus-js-client'
import { formatApiError } from '../api/client'
import { Icon } from './Icon'

type Phase = 'idle' | 'uploading' | 'paused'

export function UploadPanel({
  meetingId,
  resuming = false,
  onUploaded,
}: {
  meetingId: string
  resuming?: boolean
  onUploaded: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [percent, setPercent] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const uploadRef = useRef<tus.Upload | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const startUpload = () => {
    if (file === null) {
      return
    }
    setError(null)
    setPercent(0)
    const upload = new tus.Upload(file, {
      endpoint: `/api/meetings/${meetingId}/files/`,
      metadata: { filename: file.name, filetype: file.type },
      retryDelays: [0, 1000, 3000],
      removeFingerprintOnSuccess: true,
      onError: (err) => {
        setPhase('paused')
        setError(formatApiError(err))
      },
      onProgress: (bytesUploaded, bytesTotal) => {
        setPercent(bytesTotal > 0 ? Math.floor((bytesUploaded / bytesTotal) * 100) : 0)
      },
      onSuccess: () => {
        uploadRef.current = null
        setPhase('idle')
        onUploaded()
      },
    })
    uploadRef.current = upload
    setPhase('uploading')
    // 同一文件此前传过一半（含刷新页面后）就从断点继续，否则新建上传
    void upload.findPreviousUploads().then((previous) => {
      if (previous.length > 0) {
        upload.resumeFromPreviousUpload(previous[0])
      }
      upload.start()
    })
  }

  const pause = () => {
    void uploadRef.current?.abort()
    setPhase('paused')
  }

  const resume = () => {
    setError(null)
    uploadRef.current?.start()
    setPhase('uploading')
  }

  const handleFileChange = (selected: File | null) => {
    if (uploadRef.current !== null) {
      void uploadRef.current.abort()
      uploadRef.current = null
    }
    setFile(selected)
    setPhase('idle')
    setPercent(0)
    setError(null)
  }

  const onDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    if (!dragging) {
      setDragging(true)
    }
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    const dropped = event.dataTransfer?.files?.[0] ?? null
    if (dropped !== null) {
      handleFileChange(dropped)
    }
  }

  return (
    <div
      className={`upload-panel${dragging ? ' dragging' : ''}`}
      data-testid="upload-dropzone"
      onDragOver={onDragOver}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <span className="upload-icon">
        <Icon name="mic" size={16} />
      </span>
      <div>
        <div className="section-title">上传会议录音</div>
        <div className="section-desc">音频只在本机处理，不会上传到云端</div>
      </div>
      {resuming && phase === 'idle' && (
        <div className="section-desc">上次上传未完成：选择同一个文件可从断点继续</div>
      )}
      {/* 原生 file input 只留给无障碍与键盘：样式化按钮代为打开 */}
      <input
        ref={inputRef}
        type="file"
        accept="audio/*"
        className="visually-hidden"
        aria-label="选择音频文件"
        onChange={(event) => handleFileChange(event.target.files?.[0] ?? null)}
      />
      <div className="upload-pick">
        <button
          type="button"
          className="btn"
          disabled={phase === 'uploading'}
          onClick={() => inputRef.current?.click()}
        >
          选择文件
        </button>
        <span className="upload-filename">
          {file !== null ? file.name : '或把录音拖到这里'}
        </span>
      </div>
      {error !== null && <div className="notice notice-error">{error}</div>}
      {phase === 'idle' ? (
        <button
          type="button"
          className="btn btn-primary"
          disabled={file === null}
          onClick={startUpload}
        >
          <Icon name="upload" size={12} />
          上传音频
        </button>
      ) : (
        <>
          <div className="upload-progress" aria-label="上传进度">
            <div className="upload-progress-track">
              <div className="upload-progress-fill" style={{ width: `${percent}%` }} />
            </div>
            <span className="upload-progress-text">
              {phase === 'paused' ? `已暂停 · ${percent}%` : `${percent}%`}
            </span>
          </div>
          {phase === 'uploading' ? (
            <button type="button" className="btn" onClick={pause}>
              <Icon name="pause" size={12} />
              暂停
            </button>
          ) : (
            <button type="button" className="btn btn-primary" onClick={resume}>
              <Icon name="play" size={12} />
              继续
            </button>
          )}
        </>
      )}
    </div>
  )
}
