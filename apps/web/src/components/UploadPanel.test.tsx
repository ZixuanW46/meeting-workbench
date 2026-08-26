import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { UploadPanel } from './UploadPanel'

const state = vi.hoisted(() => ({
  uploads: [] as FakeUploadShape[],
}))

interface FakeUploadShape {
  file: File
  options: {
    endpoint: string
    metadata: { filename: string; filetype: string }
    onProgress?: (uploaded: number, total: number) => void
    onSuccess?: () => void
  }
  startCalls: number
  abortCalls: number
}

vi.mock('tus-js-client', () => {
  class Upload {
    file: File
    options: FakeUploadShape['options']
    startCalls = 0
    abortCalls = 0

    constructor(file: File, options: FakeUploadShape['options']) {
      this.file = file
      this.options = options
      state.uploads.push(this as unknown as FakeUploadShape)
    }

    findPreviousUploads() {
      return Promise.resolve([])
    }

    resumeFromPreviousUpload() {}

    start() {
      this.startCalls += 1
    }

    abort() {
      this.abortCalls += 1
      return Promise.resolve()
    }
  }
  return { Upload }
})

function selectFile() {
  const file = new File(['audio-bytes'], '周会录音.wav', { type: 'audio/wav' })
  fireEvent.change(screen.getByLabelText('选择音频文件'), {
    target: { files: [file] },
  })
  return file
}

describe('tus 上传面板', () => {
  beforeEach(() => {
    state.uploads.length = 0
  })

  it('选文件后点上传：走会议作用域 tus 端点并带原始文件名', async () => {
    render(<UploadPanel meetingId="m1" onUploaded={() => {}} />)

    selectFile()
    fireEvent.click(screen.getByRole('button', { name: '上传音频' }))

    await waitFor(() => expect(state.uploads).toHaveLength(1))
    const upload = state.uploads[0]
    expect(upload.options.endpoint).toBe('/api/meetings/m1/files/')
    expect(upload.options.metadata.filename).toBe('周会录音.wav')
    await waitFor(() => expect(upload.startCalls).toBe(1))
  })

  it('上传中可暂停、暂停后可继续', async () => {
    render(<UploadPanel meetingId="m1" onUploaded={() => {}} />)
    selectFile()
    fireEvent.click(screen.getByRole('button', { name: '上传音频' }))
    await waitFor(() => expect(state.uploads[0]?.startCalls).toBe(1))

    fireEvent.click(screen.getByRole('button', { name: '暂停' }))
    expect(state.uploads[0].abortCalls).toBe(1)
    expect(screen.getByText(/已暂停/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '继续' }))
    expect(state.uploads[0].startCalls).toBe(2)
  })

  it('进度回调更新百分比，onSuccess 通知上层刷新', async () => {
    const onUploaded = vi.fn()
    render(<UploadPanel meetingId="m1" onUploaded={onUploaded} />)
    selectFile()
    fireEvent.click(screen.getByRole('button', { name: '上传音频' }))
    await waitFor(() => expect(state.uploads).toHaveLength(1))

    state.uploads[0].options.onProgress?.(50, 100)
    await screen.findByText('50%')

    state.uploads[0].options.onSuccess?.()
    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1))
  })

  it('会议卡在 UPLOADING 时给出断点续传提示', () => {
    render(<UploadPanel meetingId="m1" resuming onUploaded={() => {}} />)

    expect(
      screen.getByText('上次上传未完成：选择同一个文件可从断点继续'),
    ).toBeInTheDocument()
  })
})
