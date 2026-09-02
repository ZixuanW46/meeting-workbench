import { act, render, screen } from '@testing-library/react'
import { Progress } from './Progress'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: ((event: unknown) => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }
}

function progressJson(state: string, step: string | null, seq: number) {
  return new Response(
    JSON.stringify({ state, processing_step: step, seq }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('进度组件', () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('SSE 事件更新步骤文案', async () => {
    render(<Progress meetingId="m1" />)

    const source = FakeEventSource.instances[0]
    expect(source.url).toBe('/api/meetings/m1/events')

    act(() => {
      source.onmessage?.({
        data: JSON.stringify({ state: 'PROCESSING', processing_step: 'ASR', seq: 1 }),
      })
    })

    expect(screen.getByText('语音转写')).toBeInTheDocument()
  })

  it('步骤内进度（清洗 3/12）跟在步骤文案后面', async () => {
    render(<Progress meetingId="m1" />)

    act(() => {
      FakeEventSource.instances[0].onmessage?.({
        data: JSON.stringify({
          state: 'GENERATING_MINUTES',
          processing_step: 'CLEANING_TRANSCRIPT',
          detail: '3/12',
          seq: 1,
        }),
      })
    })

    expect(screen.getByText('清洗转写 3/12')).toBeInTheDocument()
  })

  it('SSE 断开后落到 3 秒轮询', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(progressJson('PROCESSING', 'DIARIZATION', 2))
      .mockResolvedValueOnce(progressJson('PROCESSING', 'VOICEPRINT_MATCHING', 3))
    vi.stubGlobal('fetch', fetchMock)

    render(<Progress meetingId="m1" />)
    const source = FakeEventSource.instances[0]

    act(() => {
      source.onmessage?.({
        data: JSON.stringify({ state: 'PROCESSING', processing_step: 'ASR', seq: 1 }),
      })
      source.onerror?.(new Event('error'))
    })
    expect(source.closed).toBe(true)

    // 3 秒内不轮询
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2999)
    })
    expect(fetchMock).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/meetings/m1/progress')
    expect(screen.getByText('说话人切分')).toBeInTheDocument()

    // 再过 3 秒轮询第二次
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.getByText('声纹匹配')).toBeInTheDocument()
  })
})
