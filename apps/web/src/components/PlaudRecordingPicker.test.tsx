import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, delay, http } from 'msw'
import { server } from '../test/server'
import { PlaudRecordingPicker } from './PlaudRecordingPicker'

// 录音固定用带时区的 ISO；断言时按观看者本地时区换算，用例才不挑 CI 的 TZ
const RECORDINGS = [
  {
    file_id: 'f1',
    // Plaud 设备默认名就是这种「本地时间」串
    name: '2026-09-05 21:08:13',
    started_at: '2026-09-05T13:08:13+00:00',
    duration_ms: 5220000, // 1h27m
    imported_meeting_id: null,
  },
  {
    file_id: 'f2',
    name: '客户访谈',
    started_at: '2026-09-04T02:00:00+00:00',
    duration_ms: 312000, // 5m12s
    imported_meeting_id: null,
  },
  {
    file_id: 'f3',
    name: '上周复盘',
    started_at: '2026-09-03T02:00:00+00:00',
    duration_ms: 14000, // 14s
    imported_meeting_id: 'm-7',
  },
]

function localMinute(iso: string): string {
  const date = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

function statusHandler(body: Record<string, unknown>) {
  return http.get('/api/plaud/status', () => HttpResponse.json(body))
}

const LOGGED_IN = {
  available: true,
  logged_in: true,
  user: { nickname: 'Will', email: 'will@example.com' },
  message: null,
}

function useRecordings(items = RECORDINGS) {
  server.use(
    statusHandler(LOGGED_IN),
    http.get('/api/plaud/recordings', () =>
      HttpResponse.json({
        items,
        page: 1,
        page_size: 20,
        has_more: false,
        filtered: false,
      }),
    ),
  )
}

describe('Plaud 录音选择器', () => {
  it('MCP 未安装：只给安装说明与命令，不去拉录音列表', async () => {
    server.use(
      statusHandler({
        available: false,
        logged_in: false,
        user: null,
        message: 'Plaud MCP 未安装（npm i -g @plaud-ai/mcp）',
      }),
    )

    render(<PlaudRecordingPicker value={null} onChange={() => {}} />)

    expect(
      await screen.findByText('Plaud MCP 未安装（npm i -g @plaud-ai/mcp）'),
    ).toBeInTheDocument()
    expect(screen.getByText('npm install -g @plaud-ai/mcp')).toBeInTheDocument()
    // 未安装时不该出现搜索框；录音请求没有 handler，真发了 MSW 会直接判失败
    expect(screen.queryByLabelText('按录音名称搜索')).not.toBeInTheDocument()
  })

  it('未登录：点「登录 Plaud」，授权中提示等待，完成后自动重拉状态并列出录音', async () => {
    let statusCalls = 0
    server.use(
      http.get('/api/plaud/status', () => {
        statusCalls += 1
        return HttpResponse.json(
          statusCalls === 1
            ? {
                available: true,
                logged_in: false,
                user: null,
                message: 'Plaud 未登录，请先登录',
              }
            : LOGGED_IN,
        )
      }),
      http.post('/api/plaud/login', async () => {
        await delay(20)
        return HttpResponse.json({
          logged_in: true,
          message: 'Successfully authenticated with Plaud!',
        })
      }),
      http.get('/api/plaud/recordings', () =>
        HttpResponse.json({
          items: RECORDINGS,
          page: 1,
          page_size: 20,
          has_more: false,
          filtered: false,
        }),
      ),
    )

    render(<PlaudRecordingPicker value={null} onChange={() => {}} />)

    const loginButton = await screen.findByRole('button', { name: '登录 Plaud' })
    fireEvent.click(loginButton)

    expect(
      await screen.findByText('已在 Mac mini 上打开浏览器，请在 2 分钟内完成授权…'),
    ).toBeInTheDocument()
    expect(await screen.findByText('客户访谈')).toBeInTheDocument()
    expect(statusCalls).toBe(2)
  })

  it('已登录：列出录音，时间转本地、时长按 1h27m / 5m12s / 14s 排版，并显示账号', async () => {
    useRecordings()

    render(<PlaudRecordingPicker value={null} onChange={() => {}} />)

    expect(await screen.findByText('客户访谈')).toBeInTheDocument()
    expect(screen.getByText('Will')).toBeInTheDocument()
    // 自定义名的行附开始时间；设备默认名本身就是时间，不再印一遍
    expect(screen.getByText(localMinute('2026-09-04T02:00:00+00:00'))).toBeInTheDocument()
    expect(screen.getByText(localMinute('2026-09-03T02:00:00+00:00'))).toBeInTheDocument()
    expect(screen.queryByText(localMinute('2026-09-05T13:08:13+00:00'))).not.toBeInTheDocument()
    expect(screen.getByText('1h27m')).toBeInTheDocument()
    expect(screen.getByText('5m12s')).toBeInTheDocument()
    expect(screen.getByText('14s')).toBeInTheDocument()
  })

  it('不管服务端怎么给，列表都按开始时间从新到旧排；加载更多后依然有序', async () => {
    const later = {
      file_id: 'f0',
      name: '最新的一场',
      started_at: '2026-09-06T01:00:00+00:00',
      duration_ms: 60000,
      imported_meeting_id: null,
    }
    server.use(
      statusHandler(LOGGED_IN),
      http.get('/api/plaud/recordings', ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('page') ?? '1')
        return HttpResponse.json({
          // 第一页故意倒着给；第二页给一条比第一页都新的
          items: page === 1 ? [RECORDINGS[2], RECORDINGS[1], RECORDINGS[0]] : [later],
          page,
          page_size: 3,
          has_more: page === 1,
          filtered: false,
        })
      }),
    )

    const { container } = render(<PlaudRecordingPicker value={null} onChange={() => {}} />)
    await screen.findByText('客户访谈')
    const names = () =>
      Array.from(container.querySelectorAll('.plaud-row-name')).map((el) => el.textContent)
    expect(names()).toEqual(['2026-09-05 21:08:13', '客户访谈', '上周复盘'])

    fireEvent.click(screen.getByRole('button', { name: '加载更多' }))
    await screen.findByText('最新的一场')
    expect(names()).toEqual(['最新的一场', '2026-09-05 21:08:13', '客户访谈', '上周复盘'])
  })

  it('已导入的录音：显示「已导入」与「打开」链接，且不可再选', async () => {
    const onChange = vi.fn()
    useRecordings()

    render(<PlaudRecordingPicker value={null} onChange={onChange} />)

    expect(await screen.findByText('上周复盘')).toBeInTheDocument()
    expect(screen.getByText('已导入')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '打开' })).toHaveAttribute(
      'href',
      '#/meetings/m-7',
    )
    expect(
      screen.queryByRole('radio', { name: /上周复盘/ }),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('上周复盘'))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('点选未导入的录音回调 onChange，选中态用 radio 语义标出来', async () => {
    const onChange = vi.fn()
    useRecordings()

    const { rerender } = render(
      <PlaudRecordingPicker value={null} onChange={onChange} />,
    )

    const row = await screen.findByRole('radio', { name: /客户访谈/ })
    expect(row).toHaveAttribute('aria-checked', 'false')

    fireEvent.click(row)
    expect(onChange).toHaveBeenCalledWith(RECORDINGS[1])

    rerender(<PlaudRecordingPicker value={RECORDINGS[1]} onChange={onChange} />)
    expect(screen.getByRole('radio', { name: /客户访谈/ })).toHaveAttribute(
      'aria-checked',
      'true',
    )
  })

  it('搜索防抖 300ms 后带 query 走服务端，中间态不发请求', async () => {
    const queries: (string | null)[] = []
    server.use(
      statusHandler(LOGGED_IN),
      http.get('/api/plaud/recordings', ({ request }) => {
        const query = new URL(request.url).searchParams.get('query')
        queries.push(query)
        const items =
          query === null
            ? RECORDINGS
            : RECORDINGS.filter((item) => item.name.includes(query))
        return HttpResponse.json({
          items,
          page: 1,
          page_size: 20,
          has_more: false,
          filtered: query !== null,
        })
      }),
    )

    render(<PlaudRecordingPicker value={null} onChange={() => {}} />)
    await screen.findByText('客户访谈')

    const search = screen.getByLabelText('按录音名称搜索')
    fireEvent.change(search, { target: { value: '客' } })
    fireEvent.change(search, { target: { value: '客户' } })

    await waitFor(() => expect(queries).toContain('客户'), { timeout: 2000 })
    expect(queries).not.toContain('客')
    await waitFor(() => expect(screen.queryByText('上周复盘')).not.toBeInTheDocument())
  })

  it('还有下一页时「加载更多」把下一页追加到列表末尾', async () => {
    server.use(
      statusHandler(LOGGED_IN),
      http.get('/api/plaud/recordings', ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('page') ?? '1')
        return HttpResponse.json({
          items: page === 1 ? [RECORDINGS[0]] : [RECORDINGS[1]],
          page,
          page_size: 1,
          has_more: page === 1,
          filtered: false,
        })
      }),
    )

    render(<PlaudRecordingPicker value={null} onChange={() => {}} />)
    await screen.findByText('2026-09-05 21:08:13')
    expect(screen.queryByText('客户访谈')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '加载更多' }))

    expect(await screen.findByText('客户访谈')).toBeInTheDocument()
    // 第一页还在，是追加不是替换
    expect(screen.getByText('2026-09-05 21:08:13')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: '加载更多' })).not.toBeInTheDocument(),
    )
  })

  it('列表请求失败：显示后端原文与「重试」，重试后恢复', async () => {
    let calls = 0
    server.use(
      statusHandler(LOGGED_IN),
      http.get('/api/plaud/recordings', () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json({ detail: 'Plaud 服务异常：读取超时' }, { status: 502 })
        }
        return HttpResponse.json({
          items: RECORDINGS,
          page: 1,
          page_size: 20,
          has_more: false,
          filtered: false,
        })
      }),
    )

    render(<PlaudRecordingPicker value={null} onChange={() => {}} />)

    expect(await screen.findByText('Plaud 服务异常：读取超时')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByText('客户访谈')).toBeInTheDocument()
  })
})
