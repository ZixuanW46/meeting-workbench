// 纪要结构解析：把 LLM 产出的 markdown 按二级标题切成议题，供
// 目录导航与「本场决议一览」使用。纯函数，不做任何渲染。

export interface MinutesSection {
  title: string
  /** 该议题的 markdown 正文（不含标题行） */
  body: string
  /** 「- **结论：**」条目抽出的内容；没有则为 null */
  conclusion: string | null
  /** GFM 任务项（- [ ] / - [x]）数量，目录徽标用 */
  taskCount: number
}

export interface MinutesStructure {
  /** 首个二级标题之前的全部内容（一级标题、参会人员、总览段） */
  intro: string
  sections: MinutesSection[]
}

export interface MinutesDecision {
  section: string
  text: string
}

const SECTION_HEADING = /^##\s+(.+?)\s*$/
const CONCLUSION_BULLET = /^-\s*\*\*结论[：:]?\*\*[：:]?\s*(.+)$/
const TASK_BULLET = /^\s*-\s*\[[ xX]\]/

export function parseMinutes(markdown: string): MinutesStructure {
  const lines = markdown.split('\n')
  const sections: MinutesSection[] = []
  let introLines: string[] = []
  let current: { title: string; lines: string[] } | null = null

  for (const line of lines) {
    const heading = SECTION_HEADING.exec(line)
    if (heading !== null) {
      if (current !== null) {
        sections.push(buildSection(current.title, current.lines))
      }
      current = { title: heading[1], lines: [] }
      continue
    }
    if (current === null) {
      introLines.push(line)
    } else {
      current.lines.push(line)
    }
  }
  if (current !== null) {
    sections.push(buildSection(current.title, current.lines))
  }
  return { intro: introLines.join('\n').trim(), sections }
}

function buildSection(title: string, lines: string[]): MinutesSection {
  let conclusion: string | null = null
  let taskCount = 0
  for (const line of lines) {
    const match = CONCLUSION_BULLET.exec(line.trim())
    if (match !== null && conclusion === null) {
      conclusion = stripEmphasis(match[1].trim())
    }
    if (TASK_BULLET.test(line)) {
      taskCount += 1
    }
  }
  return { title, body: lines.join('\n').trim(), conclusion, taskCount }
}

/** 抽取各议题的结论作为决议一览；没有任何结论时返回空数组。 */
export function extractDecisions(structure: MinutesStructure): MinutesDecision[] {
  return structure.sections
    .filter((section) => section.conclusion !== null)
    .map((section) => ({
      section: section.title,
      text: section.conclusion as string,
    }))
}

/** 决议一览里只要纯文本：去掉粗体/斜体标记，保留文字本身。 */
function stripEmphasis(text: string): string {
  return text.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/\*([^*]+)\*/g, '$1')
}
