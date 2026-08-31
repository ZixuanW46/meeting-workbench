import { fireEvent, render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { makeDoctorReport } from '../test/doctor'
import { server } from '../test/server'
import { WorkbenchPage } from './WorkbenchPage'

const MEETING = {
  id: 'm1',
  title: '产品周会',
  state: 'CANCELED',
  expected_speakers: null,
  hotwords: [],
  created_at: '2026-08-26T08:00:00Z',
}

beforeEach(() => {
  sessionStorage.clear()
})

describe('工作台页', () => {
  it('转写未就绪时显示红色横幅，不挡工作台内容', async () => {
    server.use(
      http.get('/api/meetings/m1', () => HttpResponse.json(MEETING)),
      http.get('/api/doctor', () =>
        HttpResponse.json(
          makeDoctorReport({
            ffmpeg: false,
            transcription_ready: false,
          }),
        ),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    expect(await screen.findByText('产品周会')).toBeInTheDocument()
    expect(await screen.findByText(/转写暂不可用/)).toBeInTheDocument()
  })

  it('PARTIAL_READY 用人话状态并说明纪要需要本机 CLI', async () => {
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json({ ...MEETING, state: 'PARTIAL_READY' }),
      ),
      http.get('/api/meetings/m1/export/transcript.md', () =>
        HttpResponse.text('张三 00:00-00:01\n先对齐进度'),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    expect(await screen.findByText('转写完成，纪要待生成')).toBeInTheDocument()
    expect(
      await screen.findByText(/音频已转写并完成说话人确认/),
    ).toBeInTheDocument()
    expect(screen.getByText(/本机 Claude 或 Codex CLI/)).toBeInTheDocument()
  })

  it('READY 提供「重新确认说话人」，点击后回到确认停点', async () => {
    let meetingState = 'READY'
    let reopenCalled = false
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json({ ...MEETING, state: meetingState }),
      ),
      http.get('/api/meetings/m1/minutes', () =>
        HttpResponse.json({ markdown: '# 会议纪要', note: '' }),
      ),
      http.post('/api/meetings/m1/review/reopen', () => {
        reopenCalled = true
        meetingState = 'AWAITING_SPEAKER_REVIEW'
        return HttpResponse.json({ state: meetingState })
      }),
      http.get('/api/meetings/m1/review', () =>
        HttpResponse.json({ cards: [] }),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    const reopen = await screen.findByRole('button', {
      name: '重新确认说话人',
    })
    fireEvent.click(reopen)

    expect(await screen.findByText('说话人确认')).toBeInTheDocument()
    expect(reopenCalled).toBe(true)
  })
})
