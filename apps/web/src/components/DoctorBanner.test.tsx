import { act, fireEvent, render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { makeDoctorReport } from '../test/doctor'
import { server } from '../test/server'
import { DoctorBanner } from './DoctorBanner'

// 等 doctor 请求落地（msw 在进程内，几毫秒即完成）
async function flushDoctorRequest() {
  await act(() => new Promise((resolve) => setTimeout(resolve, 30)))
}

beforeEach(() => {
  sessionStorage.clear()
})

describe('DoctorBanner', () => {
  it('转写未就绪：红色横幅点名缺什么并提示 doctor.sh', async () => {
    server.use(
      http.get('/api/doctor', () =>
        HttpResponse.json(
          makeDoctorReport({
            ffmpeg: false,
            models: { asr: false, segmentation: true, embedding: true },
            transcription_ready: false,
          }),
        ),
      ),
    )

    render(<DoctorBanner />)

    const banner = await screen.findByText(/转写暂不可用/)
    expect(banner).toHaveTextContent('ffmpeg')
    expect(banner).toHaveTextContent('ASR 模型')
    expect(banner).not.toHaveTextContent('切分模型')
    expect(banner).not.toHaveTextContent('声纹模型')
    expect(banner).toHaveTextContent('./scripts/doctor.sh')
    // 红色横幅
    expect(banner.closest('.notice')).toHaveClass('notice-error')
    // 纪要就绪：黄条不出现
    expect(screen.queryByText(/纪要暂不可用/)).not.toBeInTheDocument()
  })

  it('纪要 CLI 未就绪：黄色横幅说明需要本机 claude 或 codex', async () => {
    server.use(
      http.get('/api/doctor', () =>
        HttpResponse.json(
          makeDoctorReport({
            cli: {
              claude_available: false,
              codex_available: false,
            },
            minutes_ready: false,
          }),
        ),
      ),
    )

    render(<DoctorBanner />)

    const banner = await screen.findByText(/纪要暂不可用/)
    expect(banner).toHaveTextContent('claude')
    expect(banner).toHaveTextContent('codex')
    expect(banner).toHaveTextContent(/转写不受影响/)
    expect(banner.closest('.notice')).toHaveClass('notice-warn')
    expect(screen.queryByText(/转写暂不可用/)).not.toBeInTheDocument()
  })

  it('全就绪：什么都不渲染', async () => {
    render(<DoctorBanner />)

    await flushDoctorRequest()

    expect(screen.queryByText(/转写暂不可用/)).not.toBeInTheDocument()
    expect(screen.queryByText(/纪要暂不可用/)).not.toBeInTheDocument()
  })

  it('doctor 请求失败：静默不渲染', async () => {
    server.use(http.get('/api/doctor', () => HttpResponse.error()))

    render(<DoctorBanner />)

    await flushDoctorRequest()

    expect(screen.queryByText(/转写暂不可用/)).not.toBeInTheDocument()
    expect(screen.queryByText(/纪要暂不可用/)).not.toBeInTheDocument()
  })

  it('两条可同时出现；关一条不影响另一条，且本次会话内记住', async () => {
    server.use(
      http.get('/api/doctor', () =>
        HttpResponse.json(
          makeDoctorReport({
            ffmpeg: false,
            transcription_ready: false,
            minutes_ready: false,
          }),
        ),
      ),
    )

    const first = render(<DoctorBanner />)

    expect(await screen.findByText(/转写暂不可用/)).toBeInTheDocument()
    expect(await screen.findByText(/纪要暂不可用/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '关闭转写提示' }))

    expect(screen.queryByText(/转写暂不可用/)).not.toBeInTheDocument()
    expect(screen.getByText(/纪要暂不可用/)).toBeInTheDocument()

    // 同一 session 重新挂载：已关的不再出现，另一条仍在
    first.unmount()
    render(<DoctorBanner />)

    expect(await screen.findByText(/纪要暂不可用/)).toBeInTheDocument()
    await flushDoctorRequest()
    expect(screen.queryByText(/转写暂不可用/)).not.toBeInTheDocument()
  })
})
