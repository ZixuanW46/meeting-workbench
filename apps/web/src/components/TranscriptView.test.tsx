import { render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
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

function renderView(
  variant: TranscriptVariant,
  onCleanedAvailable?: (available: boolean) => void,
) {
  return render(
    <TranscriptView
      meetingId="m1"
      variant={variant}
      onCleanedAvailable={onCleanedAvailable}
    />,
  )
}

describe('转写视图', () => {
  it('把段落块解析成「时间 / 说话人 / 文本」行，时间戳原样展示', async () => {
    mockTranscript(RAW_MARKDOWN, null)

    renderView('cleaned')

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

  it('有清洗版且口径为 cleaned 时展示清洗文本，并上报清洗版可用', async () => {
    mockTranscript(RAW_MARKDOWN, CLEANED_MARKDOWN)
    const reported: boolean[] = []

    renderView('cleaned', (available) => reported.push(available))

    expect(
      await screen.findByText('大家好，今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('嗯，大家好，今天今天对齐三件事。首先是上线时间。'),
    ).not.toBeInTheDocument()
    expect(reported).toEqual([true])
  })

  it('口径为 raw 时展示 ASR 直出文本', async () => {
    mockTranscript(RAW_MARKDOWN, CLEANED_MARKDOWN)

    renderView('raw')

    expect(
      await screen.findByText('嗯，大家好，今天今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('大家好，今天对齐三件事。首先是上线时间。'),
    ).not.toBeInTheDocument()
  })

  it('没有清洗版时展示原文并上报不可用', async () => {
    mockTranscript(RAW_MARKDOWN, null)
    const reported: boolean[] = []

    renderView('cleaned', (available) => reported.push(available))

    expect(await screen.findByText('已知用户 1')).toBeInTheDocument()
    expect(reported).toEqual([false])
  })

  it('解析不出任何块时原样展示全文兜底', async () => {
    mockTranscript('（本场会议没有可解析的逐字稿）', null)

    renderView('cleaned')

    expect(
      await screen.findByText('（本场会议没有可解析的逐字稿）'),
    ).toBeInTheDocument()
  })
})
