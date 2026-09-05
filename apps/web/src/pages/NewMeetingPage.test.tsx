import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server, useProjects } from '../test/server'
import { NewMeetingPage } from './NewMeetingPage'

describe('新建会议表单', () => {
  beforeEach(() => {
    window.location.hash = '#/new'
  })

  it('标题可留空：提交不带 title，由后端按文件名与纪要自动命名', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    // 等项目下拉落到默认项目，提交体才是稳定的
    await screen.findByRole('option', { name: 'General' })
    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({
      hotwords: [],
      meeting_date: localToday(),
      language: 'zh',
      project_id: 'pg',
    })
    expect(screen.queryByText('请输入标题')).not.toBeInTheDocument()
  })

  it('人数默认「不确定」，热词回车成标签，提交后跳转工作台', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          {
            id: 'm-new',
            title: '周会',
            state: 'DRAFT',
            expected_speakers: null,
            hotwords: ['声纹', 'MLX'],
            created_at: '2026-08-26T08:00:00Z',
          },
          { status: 201 },
        )
      }),
    )

    render(<NewMeetingPage />)
    await screen.findByRole('option', { name: 'General' })

    fireEvent.change(screen.getByLabelText('标题'), { target: { value: '周会' } })

    const hotwordInput = screen.getByLabelText('本场热词')
    fireEvent.change(hotwordInput, { target: { value: '声纹' } })
    fireEvent.keyDown(hotwordInput, { key: 'Enter' })
    fireEvent.change(hotwordInput, { target: { value: 'MLX' } })
    fireEvent.keyDown(hotwordInput, { key: 'Enter' })
    // 两个标签已渲染
    expect(screen.getByText('声纹')).toBeInTheDocument()
    expect(screen.getByText('MLX')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({
      title: '周会',
      hotwords: ['声纹', 'MLX'],
      meeting_date: localToday(),
      language: 'zh',
      project_id: 'pg',
    })
    await waitFor(() => expect(window.location.hash).toBe('#/meetings/m-new'))
  })

  it('语言默认中文，选 English 后随表单提交', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)

    // 默认选中「中文」
    expect(screen.getByRole('button', { name: '中文' })).toHaveClass('active')
    expect(screen.getByRole('button', { name: 'English' })).not.toHaveClass('active')

    fireEvent.click(screen.getByRole('button', { name: 'English' }))
    expect(screen.getByRole('button', { name: 'English' })).toHaveClass('active')

    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ language: 'en' })
  })

  it('会议日期默认今天，可改成录音当天并随表单提交', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)

    const dateInput = screen.getByLabelText('会议日期') as HTMLInputElement
    expect(dateInput.value).toBe(localToday())
    fireEvent.change(screen.getByLabelText('标题'), { target: { value: '周会' } })
    fireEvent.change(dateInput, { target: { value: '2026-08-30' } })
    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ meeting_date: '2026-08-30' })
  })
  it('项目下拉默认选中 General，选中别的项目后随表单提交 project_id', async () => {
    let body: Record<string, unknown> | null = null
    useProjects()
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    const select = await screen.findByLabelText('项目')
    await screen.findByRole('option', { name: '声纹研究' })
    // 不选就落到默认项目，不再有「无项目」这一态
    await waitFor(() => expect((select as HTMLSelectElement).value).toBe('pg'))

    fireEvent.change(select, { target: { value: 'p2' } })
    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ project_id: 'p2' })
  })

  it('不动项目下拉直接创建：project_id 就是 General', async () => {
    let body: Record<string, unknown> | null = null
    useProjects()
    server.use(
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    await screen.findByRole('option', { name: 'General' })

    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ project_id: 'pg' })
  })

  it('下拉里没有「新建项目…」哨兵，也没有「无项目」空选项', async () => {
    useProjects()
    render(<NewMeetingPage />)

    await screen.findByRole('option', { name: '声纹研究' })
    expect(screen.queryByRole('option', { name: '新建项目…' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: '无项目' })).not.toBeInTheDocument()
    const options = screen.getByLabelText('项目').querySelectorAll('option')
    expect(options.length).toBe(3)
    expect(Array.from(options).every((option) => option.value !== '')).toBe(true)
  })

  it('下拉旁的「新建项目」就地创建，创建完自动选中并随表单提交', async () => {
    let posted: { name: string } | null = null
    let body: Record<string, unknown> | null = null
    useProjects()
    server.use(
      http.post('/api/projects', async ({ request }) => {
        posted = (await request.json()) as { name: string }
        return HttpResponse.json(
          {
            id: 'p9',
            name: posted.name,
            created_at: '2026-09-03T00:00:00Z',
            meeting_count: 0,
            hotword_count: 0,
            position: 2,
          },
          { status: 201 },
        )
      }),
      http.post('/api/meetings', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-new' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    const select = await screen.findByLabelText('项目')
    await screen.findByRole('option', { name: '声纹研究' })

    fireEvent.click(screen.getByRole('button', { name: '新建项目' }))
    const nameInput = screen.getByLabelText('新项目名字')
    fireEvent.change(nameInput, { target: { value: '内网基建' } })
    fireEvent.keyDown(nameInput, { key: 'Enter' })

    await waitFor(() => expect((select as HTMLSelectElement).value).toBe('p9'))
    expect(posted).toEqual({ name: '内网基建' })
    expect(screen.queryByLabelText('新项目名字')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '创建会议' }))
    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ project_id: 'p9' })
  })
})

const PLAUD_RECORDINGS = [
  {
    file_id: 'f1',
    name: '2026-09-05 21:08:13',
    started_at: '2026-09-05T13:08:13+00:00',
    duration_ms: 5220000,
    imported_meeting_id: null,
  },
  {
    file_id: 'f2',
    name: '客户访谈',
    started_at: '2026-09-04T02:00:00+00:00',
    duration_ms: 312000,
    imported_meeting_id: null,
  },
]

/** 录音开始时间在观看者本地时区的日期，用例不挑 CI 的 TZ */
function localDateOf(iso: string): string {
  const date = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function usePlaudRecordings() {
  server.use(
    http.get('/api/plaud/status', () =>
      HttpResponse.json({
        available: true,
        logged_in: true,
        user: { nickname: 'Will', email: 'will@example.com' },
        message: null,
      }),
    ),
    http.get('/api/plaud/recordings', () =>
      HttpResponse.json({
        items: PLAUD_RECORDINGS,
        page: 1,
        page_size: 20,
        has_more: false,
        filtered: false,
      }),
    ),
  )
}

describe('新建会议 · 从 Plaud 导入', () => {
  beforeEach(() => {
    window.location.hash = '#/new'
  })

  it('默认是「稍后上传文件」，切到 Plaud 才出录音列表；没选录音不给提交', async () => {
    usePlaudRecordings()

    render(<NewMeetingPage />)

    expect(screen.getByRole('button', { name: '稍后上传文件' })).toHaveClass('active')
    expect(screen.queryByLabelText('按录音名称搜索')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '创建会议' })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: '从 Plaud 导入' }))

    expect(await screen.findByText('客户访谈')).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: '导入并开始处理' })
    expect(submit).toBeDisabled()

    fireEvent.click(await screen.findByRole('radio', { name: /客户访谈/ }))
    expect(screen.getByRole('button', { name: '导入并开始处理' })).toBeEnabled()
  })

  it('选中录音后提交：POST /api/plaud/import 带 plaud_file_id 与表单字段，成功跳工作台', async () => {
    let body: Record<string, unknown> | null = null
    usePlaudRecordings()
    useProjects()
    server.use(
      http.post('/api/plaud/import', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 'm-plaud', title: '客户访谈' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    fireEvent.click(screen.getByRole('button', { name: '从 Plaud 导入' }))
    fireEvent.click(await screen.findByRole('radio', { name: /客户访谈/ }))

    fireEvent.click(screen.getByRole('button', { name: 'English' }))
    await screen.findByRole('option', { name: '声纹研究' })
    fireEvent.change(screen.getByLabelText('项目'), { target: { value: 'p2' } })

    fireEvent.click(screen.getByRole('button', { name: '导入并开始处理' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({
      hotwords: [],
      meeting_date: localDateOf('2026-09-04T02:00:00+00:00'),
      language: 'en',
      project_id: 'p2',
      plaud_file_id: 'f2',
    })
    await waitFor(() => expect(window.location.hash).toBe('#/meetings/m-plaud'))
  })

  it('#/new?source=plaud 打开即选中 Plaud 来源', async () => {
    window.location.hash = '#/new?source=plaud'
    usePlaudRecordings()

    render(<NewMeetingPage />)

    expect(screen.getByRole('button', { name: '从 Plaud 导入' })).toHaveClass('active')
    expect(await screen.findByText('客户访谈')).toBeInTheDocument()
  })

  it('选中录音后标题占位变成录音名、会议日期跟着录音；用户改过日期就不覆盖', async () => {
    usePlaudRecordings()

    render(<NewMeetingPage />)
    fireEvent.click(screen.getByRole('button', { name: '从 Plaud 导入' }))
    fireEvent.click(await screen.findByRole('radio', { name: /客户访谈/ }))

    expect(screen.getByLabelText('标题')).toHaveAttribute('placeholder', '客户访谈')
    const dateInput = screen.getByLabelText('会议日期') as HTMLInputElement
    expect(dateInput.value).toBe(localDateOf('2026-09-04T02:00:00+00:00'))

    fireEvent.change(dateInput, { target: { value: '2026-08-30' } })
    fireEvent.click(screen.getByRole('radio', { name: /2026-09-05 21:08:13/ }))
    expect(dateInput.value).toBe('2026-08-30')
  })

  it('在搜索框里回车只是搜索，不会顺手把表单提交掉', async () => {
    let imports = 0
    usePlaudRecordings()
    server.use(
      http.post('/api/plaud/import', () => {
        imports += 1
        return HttpResponse.json({ id: 'm-plaud' }, { status: 201 })
      }),
    )

    render(<NewMeetingPage />)
    fireEvent.click(screen.getByRole('button', { name: '从 Plaud 导入' }))
    fireEvent.click(await screen.findByRole('radio', { name: /客户访谈/ }))

    const search = screen.getByLabelText('按录音名称搜索')
    fireEvent.change(search, { target: { value: '客户' } })
    // 回车被 preventDefault 拦下（dispatchEvent 返回 false），浏览器就不会隐式提交表单
    expect(fireEvent.keyDown(search, { key: 'Enter' })).toBe(false)

    await waitFor(() => expect(imports).toBe(0))
    expect(window.location.hash).toBe('#/new')
  })

  it('导入失败：错误显示在表单上，不跳转', async () => {
    usePlaudRecordings()
    server.use(
      http.post('/api/plaud/import', () =>
        HttpResponse.json({ detail: '该 Plaud 录音已导入' }, { status: 409 }),
      ),
    )

    render(<NewMeetingPage />)
    fireEvent.click(screen.getByRole('button', { name: '从 Plaud 导入' }))
    fireEvent.click(await screen.findByRole('radio', { name: /客户访谈/ }))
    fireEvent.click(screen.getByRole('button', { name: '导入并开始处理' }))

    expect(await screen.findByText('该 Plaud 录音已导入')).toBeInTheDocument()
    expect(window.location.hash).toBe('#/new')
  })
})

function localToday(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}
