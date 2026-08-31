import { render, screen } from '@testing-library/react'
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
  '## 议题详情',
  '- **要点小标题：** 具体内容与数字 2000–3000 元',
  '  - 子要点：嵌套层级要保留',
  '',
  '## 后续跟进',
  '**@Will**',
  '- [ ] 推进模拟面试对接（截止：待定）',
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
    expect(screen.getByRole('checkbox')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('[ ]')
    expect(
      screen.getByText(/推进模拟面试对接（截止：待定）/),
    ).toBeInTheDocument()
  })

  it('渲染附带的生成说明横幅', async () => {
    mockMinutes('# 标题')

    render(<MinutesView meetingId="m1" canRetry={false} onRetried={() => {}} />)

    expect(await screen.findByText('本地生成')).toBeInTheDocument()
  })
})
