import { render, screen } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../test/server'
import { TranscriptView } from './TranscriptView'

// 后端导出为 PLAUD 风格段落块：标签行「{说话人} {mm:ss}-{mm:ss}」+ 文本行，块间空行。
const BLOCK_MARKDOWN = [
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

function mockTranscript(text: string) {
  server.use(
    http.get('/api/meetings/m1/export/transcript.md', () =>
      HttpResponse.text(text),
    ),
  )
}

describe('转写视图', () => {
  it('把段落块解析成「时间 / 说话人 / 文本」行，时间戳原样展示', async () => {
    mockTranscript(BLOCK_MARKDOWN)

    render(<TranscriptView meetingId="m1" />)

    expect(await screen.findByText('已知用户 1')).toBeInTheDocument()
    expect(screen.getByText('00:00 – 00:58')).toBeInTheDocument()
    expect(
      screen.getByText('大家好，今天对齐三件事。首先是上线时间。'),
    ).toBeInTheDocument()
    expect(screen.getByText('说话人S2（未确认）')).toBeInTheDocument()
    expect(screen.getByText('00:58 – 01:40')).toBeInTheDocument()
    // 超一小时的 h:mm:ss 时间戳同样可解析。
    expect(screen.getByText('李四（就近归属）')).toBeInTheDocument()
    expect(screen.getByText('1:08:10 – 1:08:45')).toBeInTheDocument()
    // 标题行不产生转写行。
    expect(screen.queryByText(/会议转写/)).not.toBeInTheDocument()
  })

  it('解析不出任何块时原样展示全文兜底', async () => {
    mockTranscript('（本场会议没有可解析的逐字稿）')

    render(<TranscriptView meetingId="m1" />)

    expect(
      await screen.findByText('（本场会议没有可解析的逐字稿）'),
    ).toBeInTheDocument()
  })
})
