import { fireEvent, render, screen, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { MinutesView } from './MinutesView'

// 覆盖纪要模板会产出的 Markdown 构件：行内粗体、多级标题、嵌套要点、
// checkbox 行动项。它们必须真正渲染，而不是把标记符号原样漏给用户。
const MINUTES_MARKDOWN = [
  '# 08-30 会议：产品方向对齐',
  '',
  '**参会人员：** Will、未知说话人（S2）',
  '',
  '## 议程时间轴',
  '- 00:00–07:32 剑山与橄榄树延展机会',
  '',
  '## 见山与教育业务机会',
  '- **要点小标题：** 具体内容与数字 2000–3000 元',
  '  - 子要点：嵌套层级要保留',
  '- **结论：** 见山暂不作为主业，小步探索。',
  '',
  '## Taplore 复盘与内测',
  '- **产品定义过大：** 需要收缩。',
  '- **结论：** 先跑内测，再决定拆分或重塑。',
  '',
  '## 后续跟进',
  '**@Will**',
  '- [ ] 推进模拟面试对接（截止：待定）',
  '- [ ] 争取线下内测摊位（截止：待定）',
].join('\n')

function mockMinutes(markdown: string) {
  server.use(
    http.get('/api/meetings/m1/minutes', () =>
      HttpResponse.json({ markdown, note: '本地生成' }),
    ),
  )
}

describe('纪要视图', () => {
  it('把 Markdown 渲染成富文本：粗体、标题、嵌套列表、checkbox', async () => {
    mockMinutes(MINUTES_MARKDOWN)

    render(<MinutesView meetingId="m1" canRetry={false} onRetried={() => {}} />)

    // 行内粗体渲染为 <strong>，不能把 ** 星号漏出来。
    const label = await screen.findByText('参会人员：')
    expect(label.tagName).toBe('STRONG')
    expect(document.body.textContent).not.toContain('**')

    expect(
      screen.getByRole('heading', { name: '议程时间轴' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/子要点：嵌套层级要保留/)).toBeInTheDocument()

    // - [ ] 行动项渲染成复选框，而不是字面「[ ]」。
    expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(0)
    expect(document.body.textContent).not.toContain('[ ]')
    expect(
      screen.getByText(/推进模拟面试对接（截止：待定）/),
    ).toBeInTheDocument()
  })

  it('结构化纪要出目录导航与决议一览，跟进项带数量徽标', async () => {
    mockMinutes(MINUTES_MARKDOWN)

    render(<MinutesView meetingId="m1" canRetry={false} onRetried={() => {}} />)

    const toc = await screen.findByRole('navigation', { name: '纪要目录' })
    const entries = within(toc).getAllByRole('button')
    expect(entries.map((entry) => entry.textContent)).toEqual([
      '决议一览',
      '议程时间轴',
      '见山与教育业务机会',
      'Taplore 复盘与内测',
      '后续跟进2',
    ])

    // 决议一览：带结论的两个议题各占一行，编号 + 议题名 + 结论文本。
    expect(screen.getByText('本场决议一览')).toBeInTheDocument()
    expect(screen.getByText('01')).toBeInTheDocument()
    // 决议文本在摘要和议题正文各出现一次。
    expect(screen.getAllByText(/见山暂不作为主业，小步探索。/)).toHaveLength(2)
    expect(screen.getAllByText(/先跑内测，再决定拆分或重塑。/)).toHaveLength(2)
  })

  it('点目录项与决议行会把对应议题标为当前', async () => {
    mockMinutes(MINUTES_MARKDOWN)

    render(<MinutesView meetingId="m1" canRetry={false} onRetried={() => {}} />)

    const toc = await screen.findByRole('navigation', { name: '纪要目录' })
    // 有决议时默认「决议一览」为当前项。
    expect(within(toc).getByRole('button', { name: '决议一览' }).className).toContain(
      'active',
    )

    fireEvent.click(
      within(toc).getByRole('button', { name: 'Taplore 复盘与内测' }),
    )
    expect(
      within(toc).getByRole('button', { name: 'Taplore 复盘与内测' }).className,
    ).toContain('active')
    expect(
      within(toc).getByRole('button', { name: '决议一览' }).className,
    ).not.toContain('active')
  })

  it('议题不足两个时回退单卡整体渲染，不出目录', async () => {
    mockMinutes('# 标题\n\n只有一段话，没有议题结构。')

    render(<MinutesView meetingId="m1" canRetry={false} onRetried={() => {}} />)

    expect(await screen.findByText(/只有一段话/)).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '纪要目录' })).not.toBeInTheDocument()
    expect(screen.queryByText('本场决议一览')).not.toBeInTheDocument()
  })

  it('不再渲染生成说明横幅', async () => {
    mockMinutes('# 标题\n\n正文。')

    render(<MinutesView meetingId="m1" canRetry={false} onRetried={() => {}} />)

    expect(await screen.findByText(/正文/)).toBeInTheDocument()
    expect(screen.queryByText('本地生成')).not.toBeInTheDocument()
  })
})
