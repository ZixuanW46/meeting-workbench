import { extractDecisions, parseMinutes } from './minutesStructure'

const MARKDOWN = [
  '# 08-30 会议：产品方向对齐',
  '',
  '**参会人员：** Will、Leo',
  '',
  '总览段落。',
  '',
  '## 议程时间轴',
  '- 00:00–07:32 见山与橄榄树延展机会',
  '',
  '## 见山与教育业务机会',
  '- **要点小标题：** 具体内容与数字 2000–3000 元',
  '- **结论：** 见山暂不作为**主业**，小步探索。',
  '',
  '## 后续跟进',
  '**@Will**',
  '- [ ] 推进模拟面试对接（截止：待定）',
  '- [x] 已完成的事项',
  '',
  '**@待认领**',
  '- [ ] 设计线上招募渠道（截止：待定）',
].join('\n')

describe('纪要结构解析', () => {
  it('按二级标题切分议题，一级标题与总览留在 intro', () => {
    const structure = parseMinutes(MARKDOWN)

    expect(structure.intro).toContain('# 08-30 会议：产品方向对齐')
    expect(structure.intro).toContain('总览段落。')
    expect(structure.sections.map((section) => section.title)).toEqual([
      '议程时间轴',
      '见山与教育业务机会',
      '后续跟进',
    ])
    expect(structure.sections[1].body).toContain('要点小标题')
    expect(structure.sections[1].body).not.toContain('## ')
  })

  it('抽取「结论」条目并统计任务项数量', () => {
    const structure = parseMinutes(MARKDOWN)

    expect(structure.sections[0].conclusion).toBeNull()
    expect(structure.sections[1].conclusion).toBe(
      '见山暂不作为主业，小步探索。',
    )
    expect(structure.sections[2].taskCount).toBe(3)
    expect(structure.sections[0].taskCount).toBe(0)
  })

  it('决议一览来自带结论的议题，去掉粗体标记', () => {
    const decisions = extractDecisions(parseMinutes(MARKDOWN))

    expect(decisions).toEqual([
      { section: '见山与教育业务机会', sectionIndex: 1, text: '见山暂不作为主业，小步探索。' },
    ])
  })

  it('没有二级标题时整体归入 intro', () => {
    const structure = parseMinutes('# 只有标题\n\n一段话。')

    expect(structure.sections).toEqual([])
    expect(structure.intro).toContain('一段话。')
  })
})
