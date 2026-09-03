import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { PROJECTS, server, useProjects } from '../test/server'
import { HotwordsPage } from './HotwordsPage'

const ITEMS = [
  { id: 'h1', word: 'Qwen3', note: '本机转写模型' },
  { id: 'h2', word: '声纹库', note: null },
]

describe('词库页', () => {
  it('列出全局词语并说明快照语义', async () => {
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
    )

    render(<HotwordsPage />)

    expect(await screen.findByText('Qwen3')).toBeInTheDocument()
    expect(screen.getByText('声纹库')).toBeInTheDocument()
    expect(screen.getByText(/只影响之后开始转写的会议/)).toBeInTheDocument()
  })

  it('回车添加词语并出现在列表；重复词把 409 详情展示出来', async () => {
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.post('/api/hotwords', async ({ request }) => {
        const body = (await request.json()) as { word: string }
        if (body.word === '已存在') {
          return HttpResponse.json({ detail: '词语已存在' }, { status: 409 })
        }
        return HttpResponse.json({ id: 'h9', word: body.word }, { status: 201 })
      }),
    )

    render(<HotwordsPage />)
    const input = await screen.findByLabelText('添加词语')

    fireEvent.change(input, { target: { value: 'meeting-workbench' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(await screen.findByText('meeting-workbench')).toBeInTheDocument()
    expect((input as HTMLInputElement).value).toBe('')

    fireEvent.change(input, { target: { value: '已存在' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(await screen.findByText(/词语已存在/)).toBeInTheDocument()
  })

  it('删除词语后从列表移除', async () => {
    let deleted: string | null = null
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.delete('/api/hotwords/:id', ({ params }) => {
        deleted = String(params.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    render(<HotwordsPage />)
    await screen.findByText('Qwen3')

    fireEvent.click(screen.getByRole('button', { name: '删除词语 Qwen3' }))

    await waitFor(() => {
      expect(screen.queryByText('Qwen3')).not.toBeInTheDocument()
    })
    expect(deleted).toBe('h1')
    expect(screen.getByText('声纹库')).toBeInTheDocument()
  })

  it('词库为空时给出引导文案', async () => {
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
    )

    render(<HotwordsPage />)

    expect(await screen.findByText('词库是空的')).toBeInTheDocument()
  })

  it('展示词语注解；无注解的词提供添加入口', async () => {
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
    )

    render(<HotwordsPage />)

    expect(await screen.findByText('本机转写模型')).toBeInTheDocument()
    // 两行都有注解编辑入口（有注解的显示「编辑注解」，没有的显示「添加注解」）。
    expect(
      screen.getByRole('button', { name: '编辑注解 Qwen3' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '添加注解 声纹库' }),
    ).toBeInTheDocument()
  })

  it('就地编辑注解并保存：PATCH 生效、列表即时更新', async () => {
    let patched: { id: string; note: unknown } | null = null
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.patch('/api/hotwords/:id', async ({ params, request }) => {
        const body = (await request.json()) as { note: string | null }
        patched = { id: String(params.id), note: body.note }
        return HttpResponse.json({ id: params.id, word: 'Qwen3', note: body.note })
      }),
    )

    render(<HotwordsPage />)
    await screen.findByText('本机转写模型')

    fireEvent.click(screen.getByRole('button', { name: '编辑注解 Qwen3' }))
    const noteInput = screen.getByLabelText('注解内容 Qwen3')
    expect((noteInput as HTMLInputElement).value).toBe('本机转写模型')

    fireEvent.change(noteInput, { target: { value: '本机 ASR 模型（Qwen3-ASR）' } })
    fireEvent.keyDown(noteInput, { key: 'Enter' })

    expect(
      await screen.findByText('本机 ASR 模型（Qwen3-ASR）'),
    ).toBeInTheDocument()
    expect(patched).toEqual({ id: 'h1', note: '本机 ASR 模型（Qwen3-ASR）' })
  })

  it('添加词语可以顺带填注解，一起提交', async () => {
    let posted: { word: string; note?: string | null } | null = null
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.post('/api/hotwords', async ({ request }) => {
        posted = (await request.json()) as { word: string; note?: string | null }
        return HttpResponse.json(
          { id: 'h9', word: posted.word, note: posted.note ?? null },
          { status: 201 },
        )
      }),
    )

    render(<HotwordsPage />)
    const wordInput = await screen.findByLabelText('添加词语')
    const noteInput = screen.getByLabelText('注解（选填，喂给纪要 LLM）')

    fireEvent.change(wordInput, { target: { value: 'CUES' } })
    fireEvent.change(noteInput, { target: { value: '剑桥工程社团简称' } })
    fireEvent.keyDown(noteInput, { key: 'Enter' })

    expect(await screen.findByText('CUES')).toBeInTheDocument()
    expect(screen.getByText('剑桥工程社团简称')).toBeInTheDocument()
    expect(posted).toEqual({ word: 'CUES', note: '剑桥工程社团简称' })
  })
  it('切到项目范围后换数据源：只显示该项目的热词', async () => {
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.get('/api/projects/p1/hotwords', () =>
        HttpResponse.json({ items: [{ id: 'ph1', word: '亚秒轮次', note: null }] }),
      ),
    )

    render(<HotwordsPage />)
    expect(await screen.findByText('Qwen3')).toBeInTheDocument()

    fireEvent.click(await screen.findByRole('button', { name: /^会议工作台/ }))

    expect(await screen.findByText('亚秒轮次')).toBeInTheDocument()
    expect(screen.queryByText('Qwen3')).not.toBeInTheDocument()
  })

  it('项目范围下加词打到项目路由，左栏计数跟着涨', async () => {
    let postedTo: string | null = null
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.get('/api/projects/p2/hotwords', () => HttpResponse.json({ items: [] })),
      http.post('/api/projects/:id/hotwords', async ({ params, request }) => {
        postedTo = String(params.id)
        const body = (await request.json()) as { word: string }
        return HttpResponse.json({ id: 'ph9', word: body.word, note: null }, { status: 201 })
      }),
    )

    render(<HotwordsPage />)
    fireEvent.click(await screen.findByRole('button', { name: /^声纹研究/ }))
    await screen.findByText(/还没有项目热词/)

    const input = screen.getByLabelText('添加词语')
    fireEvent.change(input, { target: { value: '说话人簇' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByText('说话人簇')).toBeInTheDocument()
    expect(postedTo).toBe('p2')
    expect(await screen.findByRole('button', { name: /^声纹研究/ })).toHaveTextContent('1')
  })

  it('左栏新建项目：创建后自动切到它', async () => {
    let posted: { name: string } | null = null
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.post('/api/projects', async ({ request }) => {
        posted = (await request.json()) as { name: string }
        return HttpResponse.json(
          {
            id: 'p9',
            name: posted.name,
            created_at: '2026-09-03T00:00:00Z',
            meeting_count: 0,
            hotword_count: 0,
          },
          { status: 201 },
        )
      }),
      http.get('/api/projects/p9/hotwords', () => HttpResponse.json({ items: [] })),
    )

    render(<HotwordsPage />)
    await screen.findByText('Qwen3')

    const input = screen.getByLabelText('新建项目')
    fireEvent.change(input, { target: { value: '内网基建' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByText('「内网基建」还没有项目热词')).toBeInTheDocument()
    expect(posted).toEqual({ name: '内网基建' })
  })

  it('重命名项目：就地改名，PATCH 生效', async () => {
    let patched: { id: string; name: string } | null = null
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.patch('/api/projects/:id', async ({ params, request }) => {
        const body = (await request.json()) as { name: string }
        patched = { id: String(params.id), name: body.name }
        return HttpResponse.json({ ...PROJECTS[1], name: body.name })
      }),
    )

    render(<HotwordsPage />)
    fireEvent.click(await screen.findByRole('button', { name: '重命名项目 声纹研究' }))

    const input = screen.getByLabelText('项目新名字 声纹研究')
    fireEvent.change(input, { target: { value: '声纹与说话人' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByRole('button', { name: /^声纹与说话人/ })).toBeInTheDocument()
    expect(patched).toEqual({ id: 'p2', name: '声纹与说话人' })
  })

  it('删除项目要二次确认，文案说明会议变无项目、项目热词一并删', async () => {
    let deleted: string | null = null
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.delete('/api/projects/:id', ({ params }) => {
        deleted = String(params.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    render(<HotwordsPage />)
    fireEvent.click(await screen.findByRole('button', { name: '删除项目 声纹研究' }))

    expect(
      screen.getByText(/该项目的会议会变成无项目，项目热词一并删除/),
    ).toBeInTheDocument()
    expect(deleted).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))

    await waitFor(() => expect(deleted).toBe('p2'))
    expect(screen.queryByRole('button', { name: /^声纹研究/ })).not.toBeInTheDocument()
  })

  it('删掉当前所在的项目后退回通用词库', async () => {
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.get('/api/projects/p1/hotwords', () =>
        HttpResponse.json({ items: [{ id: 'ph1', word: '亚秒轮次', note: null }] }),
      ),
      http.delete('/api/projects/p1', () => new HttpResponse(null, { status: 204 })),
    )

    render(<HotwordsPage />)
    fireEvent.click(await screen.findByRole('button', { name: /^会议工作台/ }))
    await screen.findByText('亚秒轮次')

    fireEvent.click(screen.getByRole('button', { name: '删除项目 会议工作台' }))
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))

    expect(await screen.findByText('Qwen3')).toBeInTheDocument()
  })

  it('右栏说明三层热词如何叠加', async () => {
    server.use(http.get('/api/hotwords', () => HttpResponse.json({ items: [] })))

    render(<HotwordsPage />)

    expect(
      await screen.findByText(/通用词库对所有会议生效；项目热词只对该项目的会议生效/),
    ).toBeInTheDocument()
  })
})
