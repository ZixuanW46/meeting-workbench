import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  meeting_date: '2026-08-26',
  meeting_date_source: 'created',
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

  it('有清洗版时工具栏出「查看原文」按钮，点按在两个口径间切换', async () => {
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json({ ...MEETING, state: 'PARTIAL_READY' }),
      ),
      http.get('/api/meetings/m1/transcript', () =>
        HttpResponse.json({
          raw_markdown: '张三 00:00-00:01\n嗯，先对齐进度',
          cleaned_markdown: '张三 00:00-00:01\n先对齐进度',
        }),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    // 默认清洗版
    expect(await screen.findByText('先对齐进度')).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: '查看原文' }))
    expect(await screen.findByText('嗯，先对齐进度')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看清洗版' }))
    expect(await screen.findByText('先对齐进度')).toBeInTheDocument()
  })

  it('没有清洗版时不出切换按钮', async () => {
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

    expect(await screen.findByText('先对齐进度')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: '查看原文' }),
    ).not.toBeInTheDocument()
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

  it('元信息行展示会议日期与推断来源，可就地改日期', async () => {
    let patched: Record<string, unknown> | null = null
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json(
          patched === null
            ? { ...MEETING, meeting_date: '2026-08-31', meeting_date_source: 'filename' }
            : { ...MEETING, ...patched, meeting_date_source: 'user' },
        ),
      ),
      http.patch('/api/meetings/m1', async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...MEETING, ...patched, meeting_date_source: 'user' })
      }),
    )

    render(<WorkbenchPage meetingId="m1" />)

    expect(await screen.findByText(/会议日期 2026-08-31/)).toBeInTheDocument()
    expect(screen.getByText(/按文件名推断/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '修改会议日期' }))
    const input = screen.getByLabelText('会议日期')
    fireEvent.change(input, { target: { value: '2026-08-30' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByText(/会议日期 2026-08-30/)).toBeInTheDocument()
    expect(patched).toEqual({ meeting_date: '2026-08-30' })
    expect(screen.queryByText(/按文件名推断/)).not.toBeInTheDocument()
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

    // 低频操作折叠在「更多操作」菜单里，键盘打开后选择。
    const trigger = await screen.findByRole('button', { name: '更多操作' })
    fireEvent.keyDown(trigger, { key: 'Enter' })
    const reopen = await screen.findByRole('menuitem', {
      name: '重新确认说话人',
    })
    fireEvent.click(reopen)

    expect(await screen.findByText('说话人确认')).toBeInTheDocument()
    expect(reopenCalled).toBe(true)
  })

  it('READY 的更多操作菜单包含全部导出口', async () => {
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json({ ...MEETING, state: 'READY' }),
      ),
      http.get('/api/meetings/m1/minutes', () =>
        HttpResponse.json({ markdown: '# 会议纪要', note: '' }),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    const trigger = await screen.findByRole('button', { name: '更多操作' })
    fireEvent.keyDown(trigger, { key: 'Enter' })

    expect(
      await screen.findByRole('menuitem', { name: '导出转写 MD' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('menuitem', { name: '导出纪要 MD' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('menuitem', { name: '导出纪要 DOCX' }),
    ).toBeInTheDocument()
    // 工具栏上不再平铺这些按钮。
    expect(
      screen.queryByRole('link', { name: /导出转写 MD/ }),
    ).not.toBeInTheDocument()
  })

  it('FAILED 展示失败原因，「重新处理」把会议放回队列', async () => {
    let state = 'FAILED'
    let retranscribed = false
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json({
          ...MEETING,
          state,
          processing_error: state === 'FAILED' ? 'RuntimeError: 模型内存不足' : null,
        }),
      ),
      http.post('/api/meetings/m1/retranscribe', () => {
        retranscribed = true
        state = 'QUEUED'
        return HttpResponse.json({ ...MEETING, state, processing_error: null })
      }),
      http.get('/api/meetings/m1/progress', () =>
        HttpResponse.json({ state: 'QUEUED', processing_step: null, seq: 1 }),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    expect(await screen.findByText(/模型内存不足/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新处理' }))

    expect(await screen.findByText('排队中')).toBeInTheDocument()
    expect(retranscribed).toBe(true)
  })

  it('CANCELED 也能重新处理', async () => {
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json({ ...MEETING, state: 'CANCELED', processing_error: null }),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    expect(await screen.findByRole('button', { name: '重新处理' })).toBeInTheDocument()
  })

  it('PARTIAL_READY 把纪要失败原因写在提示里', async () => {
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json({
          ...MEETING,
          state: 'PARTIAL_READY',
          processing_error: 'MinutesCliError: claude 失败：Not logged in',
        }),
      ),
      http.get('/api/meetings/m1/transcript', () =>
        HttpResponse.json({ raw_markdown: '张三 00:00-00:01\n先对齐进度', cleaned_markdown: null }),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    expect(await screen.findByText(/Not logged in/)).toBeInTheDocument()
  })

  it('READY 菜单里的「重新转写」要二次确认，确认后调用重转写接口', async () => {
    let retranscribed = false
    server.use(
      http.get('/api/meetings/m1', () =>
        HttpResponse.json({ ...MEETING, state: 'READY' }),
      ),
      http.get('/api/meetings/m1/minutes', () =>
        HttpResponse.json({ markdown: '# 会议纪要', note: '' }),
      ),
      http.post('/api/meetings/m1/retranscribe', () => {
        retranscribed = true
        return HttpResponse.json({ ...MEETING, state: 'QUEUED' })
      }),
      http.get('/api/meetings/m1/progress', () =>
        HttpResponse.json({ state: 'QUEUED', processing_step: null, seq: 1 }),
      ),
    )

    render(<WorkbenchPage meetingId="m1" />)

    const trigger = await screen.findByRole('button', { name: '更多操作' })
    fireEvent.keyDown(trigger, { key: 'Enter' })
    fireEvent.click(await screen.findByRole('menuitem', { name: '重新转写' }))

    // 会丢掉已确认的说话人与纪要，所以先出确认条，不直接发请求。
    expect(await screen.findByText(/会丢弃/)).toBeInTheDocument()
    expect(retranscribed).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '确认重新转写' }))

    await waitFor(() => expect(retranscribed).toBe(true))
  })

  it('PARTIAL_READY 的菜单没有纪要导出口', async () => {
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

    const trigger = await screen.findByRole('button', { name: '更多操作' })
    fireEvent.keyDown(trigger, { key: 'Enter' })

    expect(
      await screen.findByRole('menuitem', { name: '导出转写 MD' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('menuitem', { name: '导出纪要 MD' }),
    ).not.toBeInTheDocument()
  })
})
