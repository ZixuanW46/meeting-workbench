import { fireEvent, render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { useState } from 'react'
import type { TranscriptVariant } from '../api/client'
import { server } from '../test/server'
import { TranscriptView } from './TranscriptView'

// 后端导出为 PLAUD 风格段落块：标签行「{说话人} {mm:ss}-{mm:ss}」+ 文本行，块间空行。
const RAW_MARKDOWN = [
  '# 会议转写',
  '',
  '已知用户 1 00:00-00:58',
  '嗯，大家好，今天今天对齐三件事。首先是上线时间。',
  '',
  '说话人S2（未确认） 00:58-01:40',
  '呃，我这边周五可以发布。',
  '',
  '李四（就近归属） 1:08:10-1:08:45',
  '收到。',
].join('\n')

const CLEANED_MARKDOWN = [
  '# 会议转写',
  '',
  '已知用户 1 00:00-00:58',
  '大家好，今天对齐三件事。首先是上线时间。',
  '',
  '说话人S2（未确认） 00:58-01:40',
  '我这边周五可以发布。',
  '',
  '李四（就近归属） 1:08:10-1:08:45',
  '收到。',
].join('\n')

function mockTranscript(raw: string, cleaned: string | null) {
  server.use(
    http.get('/api/meetings/m1/transcript', () =>
      HttpResponse.json({ raw_markdown: raw, cleaned_markdown: cleaned }),
    ),
  )
}

// 组件是受控的（版本状态由工作台持有），测试用最小外壳还原同样接法。
function Harness({ initial = 'cleaned' }: { initial?: TranscriptVariant }) {
  const [variant, setVariant] = useState<TranscriptVariant>(initial)
  return (
    <TranscriptView meetingId="m1" variant={variant} onVariantChange={setVariant} />
  )
}

describe('转写视图', () => {
  it('把段落块解析成「时间 / 说话人 / 文本」行，时间戳原样展示', async () => {
    mockTranscript(RAW_MARKDOWN, null)

    render(<Harness />)

    expect(await screen.findByText('已知用户 1')).toBeInTheDocument()
    expect(screen.getByText('00:00 – 00:58')).toBeInTheDocument()
    expect(
      screen.getByText('嗯，大家好，今天今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(screen.getByText('说话人S2（未确认）')).toBeInTheDocument()
    expect(screen.getByText('00:58 – 01:40')).toBeInTheDocument()
    // 超一小时的 h:mm:ss 时间戳同样可解析。
    expect(screen.getByText('李四（就近归属）')).toBeInTheDocument()
    expect(screen.getByText('1:08:10 – 1:08:45')).toBeInTheDocument()
    // 标题行不产生转写行。
    expect(screen.queryByText(/会议转写/)).not.toBeInTheDocument()
  })

  it('有清洗版时默认展示清洗版，并给出版本切换', async () => {
    mockTranscript(RAW_MARKDOWN, CLEANED_MARKDOWN)

    render(<Harness />)

    expect(
      await screen.findByText('大家好，今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('嗯，大家好，今天今天对齐三件事。首先是上线时间。'),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('group', { name: '转写版本' })).toBeInTheDocument()
    expect(
      screen.getByText('已去除语气词与口误，原始转写完整保留'),
    ).toBeInTheDocument()
  })

  it('切到「原文」展示 ASR 直出文本，切回「清洗版」恢复', async () => {
    mockTranscript(RAW_MARKDOWN, CLEANED_MARKDOWN)

    render(<Harness />)

    fireEvent.click(await screen.findByRole('button', { name: '原文' }))
    expect(
      screen.getByText('嗯，大家好，今天今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('已去除语气词与口误，原始转写完整保留'),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '清洗版' }))
    expect(
      screen.getByText('大家好，今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
  })

  it('没有清洗版时不出切换，直接展示原文', async () => {
    mockTranscript(RAW_MARKDOWN, null)

    render(<Harness />)

    expect(await screen.findByText('已知用户 1')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: '转写版本' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '原文' })).not.toBeInTheDocument()
  })

  it('解析不出任何块时原样展示全文兜底', async () => {
    mockTranscript('（本场会议没有可解析的逐字稿）', null)

    render(<Harness />)

    expect(
      await screen.findByText('（本场会议没有可解析的逐字稿）'),
    ).toBeInTheDocument()
  })
})
