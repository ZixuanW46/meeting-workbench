import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { GENERAL, PROJECTS, server, useProjects } from '../test/server'
import { Toaster } from '../components/Toast'
import { HotwordsPage } from './HotwordsPage'

const ITEMS = [
  { id: 'h1', word: 'Qwen3', note: '本机转写模型' },
  { id: 'h2', word: '声纹库', note: null },
]

/** 左栏从上到下的范围名（含固定在第一的「通用」） */
function railNames(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('.scope-row .scope-name')).map(
    (node) => node.textContent ?? '',
  )
}

/** p2 在前、p1 在后的重排结果（General 照旧垫底），供 PUT /api/projects/order 回吐 */
const SWAPPED = [
  { ...PROJECTS[1], position: 0 },
  { ...PROJECTS[0], position: 1 },
  { ...GENERAL, position: 2 },
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
            position: 2,
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

  it('选中项目后右栏头部常驻「重命名」「删除」；通用范围没有这两个按钮', async () => {
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.get('/api/projects/p1/hotwords', () => HttpResponse.json({ items: [] })),
    )

    render(<HotwordsPage />)
    await screen.findByText('Qwen3')

    expect(screen.getByRole('heading', { name: '通用' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重命名' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除' })).not.toBeInTheDocument()

    fireEvent.click(await screen.findByRole('button', { name: /^会议工作台/ }))

    expect(await screen.findByRole('heading', { name: '会议工作台' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重命名' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '删除' })).toBeInTheDocument()
  })

  it('头部「重命名」就地改名：回车保存，标题与左栏同时更新', async () => {
    let patched: { id: string; name: string } | null = null
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.get('/api/projects/p2/hotwords', () => HttpResponse.json({ items: [] })),
      http.patch('/api/projects/:id', async ({ params, request }) => {
        const body = (await request.json()) as { name: string }
        patched = { id: String(params.id), name: body.name }
        return HttpResponse.json({ ...PROJECTS[1], name: body.name })
      }),
    )

    render(<HotwordsPage />)
    fireEvent.click(await screen.findByRole('button', { name: /^声纹研究/ }))
    fireEvent.click(await screen.findByRole('button', { name: '重命名' }))

    const input = screen.getByLabelText('项目新名字 声纹研究')
    fireEvent.change(input, { target: { value: '声纹与说话人' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(
      await screen.findByRole('heading', { name: '声纹与说话人' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^声纹与说话人/ })).toBeInTheDocument()
    expect(patched).toEqual({ id: 'p2', name: '声纹与说话人' })
  })

  it('头部重命名按 Esc 取消：名字不变，也不发 PATCH', async () => {
    let patchCalls = 0
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.get('/api/projects/p2/hotwords', () => HttpResponse.json({ items: [] })),
      http.patch('/api/projects/:id', () => {
        patchCalls += 1
        return HttpResponse.json(PROJECTS[1])
      }),
    )

    render(<HotwordsPage />)
    fireEvent.click(await screen.findByRole('button', { name: /^声纹研究/ }))
    fireEvent.click(await screen.findByRole('button', { name: '重命名' }))

    const input = screen.getByLabelText('项目新名字 声纹研究')
    fireEvent.change(input, { target: { value: '改一半' } })
    fireEvent.keyDown(input, { key: 'Escape' })

    expect(screen.getByRole('heading', { name: '声纹研究' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重命名' })).toBeInTheDocument()
    expect(patchCalls).toBe(0)
  })

  it('头部「删除」就地二次确认，文案说明会议改挂 General、项目热词一并删', async () => {
    let deleted: string | null = null
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.get('/api/projects/p2/hotwords', () => HttpResponse.json({ items: [] })),
      http.delete('/api/projects/:id', ({ params }) => {
        deleted = String(params.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    render(<HotwordsPage />)
    fireEvent.click(await screen.findByRole('button', { name: /^声纹研究/ }))
    fireEvent.click(await screen.findByRole('button', { name: '删除' }))

    expect(
      screen.getByText(/该项目的会议会改挂到 General，项目热词一并删除/),
    ).toBeInTheDocument()
    expect(deleted).toBeNull()

    // 先验证「取消」收起确认，再重新走一遍到「确认删除」
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(
      screen.queryByText(/该项目的会议会改挂到 General/),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '删除' }))
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

    fireEvent.click(screen.getByRole('button', { name: '删除' }))
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))

    expect(await screen.findByText('Qwen3')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '通用' })).toBeInTheDocument()
  })

  it('projectId 直达：打开就选中该项目，右栏拉的是它的词', async () => {
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.get('/api/projects/p2/hotwords', () =>
        HttpResponse.json({ items: [{ id: 'ph2', word: '说话人簇', note: null }] }),
      ),
    )

    render(<HotwordsPage projectId="p2" />)

    expect(await screen.findByText('说话人簇')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '声纹研究' })).toBeInTheDocument()
    expect(screen.queryByText('Qwen3')).not.toBeInTheDocument()
  })

  it('projectId 指向不存在的项目时退回通用，不去拉那个项目的词', async () => {
    let projectHotwordCalls = 0
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.get('/api/projects/:id/hotwords', () => {
        projectHotwordCalls += 1
        return HttpResponse.json({ detail: '项目不存在' }, { status: 404 })
      }),
    )

    render(<HotwordsPage projectId="p404" />)

    expect(await screen.findByText('Qwen3')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '通用' })).toBeInTheDocument()
    expect(projectHotwordCalls).toBe(0)
    expect(screen.queryByText(/项目不存在/)).not.toBeInTheDocument()
  })

  it('右栏说明三层热词如何叠加', async () => {
    server.use(http.get('/api/hotwords', () => HttpResponse.json({ items: [] })))

    render(<HotwordsPage />)

    expect(
      await screen.findByText(/通用词库对所有会议生效；项目热词只对该项目的会议生效/),
    ).toBeInTheDocument()
  })

  it('左栏项目按后端返回的顺序排，不再按名字重排', async () => {
    useProjects(SWAPPED)
    server.use(http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })))

    const { container } = render(<HotwordsPage />)
    await screen.findByRole('button', { name: /^声纹研究/ })

    expect(railNames(container)).toEqual(['通用', '声纹研究', '会议工作台', 'General'])
  })

  it('把手上按 ⌥↓ 下移一位：乐观换序并把新顺序 PUT 给后端', async () => {
    let ordered: string[] | null = null
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.put('/api/projects/order', async ({ request }) => {
        const body = (await request.json()) as { ids: string[] }
        ordered = body.ids
        return HttpResponse.json({ items: SWAPPED })
      }),
    )

    const { container } = render(<HotwordsPage />)
    const grip = await screen.findByRole('button', { name: '拖动排序 会议工作台' })

    // 已经在第一位，⌥↑ 是空操作，不该打后端
    fireEvent.keyDown(grip, { key: 'ArrowUp', altKey: true })
    expect(ordered).toBeNull()
    expect(railNames(container)).toEqual(['通用', '会议工作台', '声纹研究', 'General'])

    fireEvent.keyDown(grip, { key: 'ArrowDown', altKey: true })
    expect(railNames(container)).toEqual(['通用', '声纹研究', '会议工作台', 'General'])

    await waitFor(() => expect(ordered).toEqual(['p2', 'p1', 'pg']))
    expect(railNames(container)).toEqual(['通用', '声纹研究', '会议工作台', 'General'])
  })

  it('拖拽排序：拖动中出插入线，松手后落到目标位置', async () => {
    let ordered: string[] | null = null
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.put('/api/projects/order', async ({ request }) => {
        const body = (await request.json()) as { ids: string[] }
        ordered = body.ids
        return HttpResponse.json({ items: SWAPPED })
      }),
    )

    const { container } = render(<HotwordsPage />)
    await screen.findByRole('button', { name: '拖动排序 声纹研究' })

    // rows[0] 是不参与排序的「通用」
    const rows = container.querySelectorAll('.scope-row')
    fireEvent.dragStart(rows[1])
    expect(rows[1]).toHaveClass('dragging')

    fireEvent.dragOver(rows[2])
    expect(rows[2]).toHaveClass('drop-after')

    fireEvent.drop(rows[2])

    await waitFor(() => expect(ordered).toEqual(['p2', 'p1', 'pg']))
    expect(railNames(container)).toEqual(['通用', '声纹研究', '会议工作台', 'General'])
    expect(container.querySelector('.scope-row.dragging')).toBeNull()
  })

  it('排序失败：左栏顺序回滚并给出错误提示', async () => {
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.put('/api/projects/order', () =>
        HttpResponse.json({ detail: '项目顺序不完整' }, { status: 422 }),
      ),
    )

    const { container } = render(<HotwordsPage />)
    const grip = await screen.findByRole('button', { name: '拖动排序 会议工作台' })

    fireEvent.keyDown(grip, { key: 'ArrowDown', altKey: true })
    expect(railNames(container)).toEqual(['通用', '声纹研究', '会议工作台', 'General'])

    expect(await screen.findByText('项目顺序不完整')).toBeInTheDocument()
    expect(railNames(container)).toEqual(['通用', '会议工作台', '声纹研究', 'General'])
  })

  it('选中 General：只给一段说明，不渲染词条编辑，也不给「删除」', async () => {
    useProjects()
    server.use(http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })))

    render(<HotwordsPage />)
    await screen.findByText('Qwen3')

    fireEvent.click(await screen.findByRole('button', { name: 'General' }))

    expect(
      await screen.findByText(
        'General 是默认项目，会自动叠加全局词库和所有项目的热词，不用单独维护',
      ),
    ).toBeInTheDocument()
    // 不拉它的热词（没注册 handler，真发请求会被 onUnhandledRequest 判错）
    expect(screen.queryByLabelText('添加词语')).not.toBeInTheDocument()
    expect(screen.queryByText('Qwen3')).not.toBeInTheDocument()
    // 改名保留、删除隐藏
    expect(screen.getByRole('button', { name: '重命名' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除' })).not.toBeInTheDocument()
  })

  it('General 在左栏不挂词数：它的词是叠加出来的，数字没有意义', async () => {
    useProjects()
    server.use(http.get('/api/hotwords', () => HttpResponse.json({ items: [] })))

    render(<HotwordsPage />)
    const general = await screen.findByRole('button', { name: 'General' })

    expect(general.querySelector('.scope-count')).toBeNull()
    expect(
      screen.getByRole('button', { name: /^会议工作台/ }).querySelector('.scope-count'),
    ).not.toBeNull()
  })

  it('通用词库多选后移动到项目：请求体、行移除、左栏计数与 toast', async () => {
    let moveBody: unknown = null
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.post('/api/hotwords/move', async ({ request }) => {
        moveBody = await request.json()
        return HttpResponse.json({ moved: 2, merged: 0 })
      }),
    )

    render(
      <>
        <HotwordsPage />
        <Toaster />
      </>,
    )
    await screen.findByText('Qwen3')

    fireEvent.click(await screen.findByLabelText('选择 Qwen3'))
    fireEvent.click(screen.getByLabelText('选择 声纹库'))
    expect(screen.getByText('已选 2 个')).toBeInTheDocument()

    fireEvent.keyDown(screen.getByRole('button', { name: '移动到' }), { key: 'Enter' })
    fireEvent.click(await screen.findByRole('menuitem', { name: '会议工作台' }))

    await waitFor(() => expect(screen.queryByText('Qwen3')).not.toBeInTheDocument())
    expect(moveBody).toEqual({
      from: { project_id: null },
      to: { project_id: 'p1' },
      ids: ['h1', 'h2'],
    })
    expect(screen.queryByText('声纹库')).not.toBeInTheDocument()
    expect(await screen.findByText('已移动 2 个词到「会议工作台」')).toBeInTheDocument()
    // p1 原本 2 条，收下两条变 4；选中态一并清空
    expect(screen.getByRole('button', { name: /^会议工作台/ })).toHaveTextContent('4')
    expect(screen.queryByText(/已选/)).not.toBeInTheDocument()
  })

  it('移动目标不含当前范围与 General', async () => {
    useProjects()
    server.use(http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })))

    render(<HotwordsPage />)
    await screen.findByText('Qwen3')

    fireEvent.click(await screen.findByLabelText('选择 Qwen3'))
    fireEvent.keyDown(screen.getByRole('button', { name: '移动到' }), { key: 'Enter' })

    const items = await screen.findAllByRole('menuitem')
    expect(items.map((item) => item.textContent)).toEqual(['会议工作台', '声纹研究'])
  })

  it('行尾单条「移动到」：项目 → 通用词库，合并数写进 toast', async () => {
    let moveBody: unknown = null
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: [] })),
      http.get('/api/projects/p1/hotwords', () =>
        HttpResponse.json({ items: [{ id: 'ph1', word: '亚秒轮次', note: '轮次时长' }] }),
      ),
      http.post('/api/hotwords/move', async ({ request }) => {
        moveBody = await request.json()
        return HttpResponse.json({ moved: 0, merged: 1 })
      }),
    )

    render(
      <>
        <HotwordsPage />
        <Toaster />
      </>,
    )
    fireEvent.click(await screen.findByRole('button', { name: /^会议工作台/ }))
    await screen.findByText('亚秒轮次')

    fireEvent.keyDown(screen.getByRole('button', { name: '移动词语 亚秒轮次' }), {
      key: 'Enter',
    })
    fireEvent.click(await screen.findByRole('menuitem', { name: '通用词库' }))

    await waitFor(() => expect(screen.queryByText('亚秒轮次')).not.toBeInTheDocument())
    expect(moveBody).toEqual({
      from: { project_id: 'p1' },
      to: { project_id: null },
      ids: ['ph1'],
    })
    expect(
      await screen.findByText('已移动 1 个词到「通用词库」，合并 1 个'),
    ).toBeInTheDocument()
  })

  it('列表头「全选」勾上全部词条，「取消选择」清空', async () => {
    useProjects()
    server.use(http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })))

    render(<HotwordsPage />)
    await screen.findByText('Qwen3')

    fireEvent.click(await screen.findByLabelText('全选'))
    expect(screen.getByText('已选 2 个')).toBeInTheDocument()
    expect(screen.getByLabelText('选择 Qwen3')).toBeChecked()

    fireEvent.click(screen.getByRole('button', { name: '取消选择' }))
    expect(screen.queryByText(/已选/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('选择 Qwen3')).not.toBeChecked()
  })

  it('移动失败：词条留在原处，错误进 toast', async () => {
    useProjects()
    server.use(
      http.get('/api/hotwords', () => HttpResponse.json({ items: ITEMS })),
      http.post('/api/hotwords/move', () =>
        HttpResponse.json({ detail: '词语不存在' }, { status: 404 }),
      ),
    )

    render(
      <>
        <HotwordsPage />
        <Toaster />
      </>,
    )
    await screen.findByText('Qwen3')

    fireEvent.click(await screen.findByLabelText('选择 Qwen3'))
    fireEvent.keyDown(screen.getByRole('button', { name: '移动到' }), { key: 'Enter' })
    fireEvent.click(await screen.findByRole('menuitem', { name: '声纹研究' }))

    expect(await screen.findByText('词语不存在')).toBeInTheDocument()
    expect(screen.getByText('Qwen3')).toBeInTheDocument()
  })
})
