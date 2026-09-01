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
  speakers: [],
  unknown_speaker_count: 0,
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
      http.get('/api/meetings/m1/transcript', () =>
        HttpResponse.json({
          raw_markdown: '张三 00:00-00:01\n先对齐进度',
          cleaned_markdown: null,
        }),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    expect(await screen.findByText('转写完成，纪要待生成')).toBeInTheDocument()
    expect(
      await screen.findByText(/音频已转写并完成说话人确认/),
    ).toBeInTheDocument()
    expect(screen.getByText(/本机 Claude 或 Codex CLI/)).toBeInTheDocument()
  })

  it('标题可就地编辑，保存后展示新标题', async () => {
    let patchedTitle: string | null = null
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json(
          patchedTitle === null ? MEETING : { ...MEETING, title: patchedTitle },
        ),
      ),
      http.patch('/api/meetings/m1', async ({ request }) => {
        const body = (await request.json()) as { title: string }
        patchedTitle = body.title
        return HttpResponse.json({ ...MEETING, title: body.title })
      }),
    )

    render(<WorkbenchPage meetingId="m1" />)

    fireEvent.click(await screen.findByRole('button', { name: '编辑标题' }))
    const input = screen.getByLabelText('会议标题')
    fireEvent.change(input, { target: { value: '08-30 团队战略会' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    expect(
      await screen.findByRole('heading', { name: '08-30 团队战略会' }),
    ).toBeInTheDocument()
    expect(patchedTitle).toBe('08-30 团队战略会')
  })

  it('编辑标题按 Esc 取消，不发请求', async () => {
    let patchCalled = false
    server.use(
      http.get('/api/meetings/m1', () => HttpResponse.json(MEETING)),
      http.patch('/api/meetings/m1', () => {
        patchCalled = true
        return HttpResponse.json(MEETING)
      }),
    )

    render(<WorkbenchPage meetingId="m1" />)

    fireEvent.click(await screen.findByRole('button', { name: '编辑标题' }))
    const input = screen.getByLabelText('会议标题')
    fireEvent.change(input, { target: { value: '不想要的标题' } })
    fireEvent.keyDown(input, { key: 'Escape' })

    expect(screen.getByRole('heading', { name: '产品周会' })).toBeInTheDocument()
    expect(screen.queryByLabelText('会议标题')).not.toBeInTheDocument()
    expect(patchCalled).toBe(false)
  })

  it('确认后的会议展示实际参会人数与人名', async () => {
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json({
          ...MEETING,
          state: 'READY',
          speakers: ['Will', 'Leo', 'Eddie'],
          unknown_speaker_count: 1,
        }),
      ),
      http.get('/api/meetings/m1/minutes', () =>
        HttpResponse.json({ markdown: '# 会议纪要', note: '' }),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    expect(
      await screen.findByText(/参会 4 人：Will、Leo、Eddie、未知说话人 ×1/),
    ).toBeInTheDocument()
    expect(screen.queryByText(/预计人数/)).not.toBeInTheDocument()
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
