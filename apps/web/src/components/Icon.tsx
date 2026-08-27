import type { ReactNode } from 'react'

// 全站统一图标：16 视口、1.5 描边、currentColor，跟随文字颜色。
// 只收克制的线性图标，不引入图标库。
export const ICON_NAMES = [
  'meetings',
  'voiceprints',
  'plus',
  'chevron-left',
  'chevron-right',
  'upload',
  'download',
  'play',
  'pause',
  'close',
  'refresh',
  'check',
  'mic',
  'trash',
  'hotwords',
] as const

export type IconName = (typeof ICON_NAMES)[number]

const PATHS: Record<IconName, ReactNode> = {
  meetings: (
    <>
      <path d="M5.75 4.25h7.5M5.75 8h7.5M5.75 11.75h7.5" />
      <path d="M2.75 4.25h.01M2.75 8h.01M2.75 11.75h.01" />
    </>
  ),
  voiceprints: (
    <path d="M2.75 6.5v3M5.5 4.25v7.5M8.25 2.5v11M11 5.25v5.5M13.75 6.75v2.5" />
  ),
  plus: <path d="M8 3.5v9M3.5 8h9" />,
  'chevron-left': <path d="m9.75 4.25-3.5 3.75 3.5 3.75" />,
  'chevron-right': <path d="m6.25 4.25 3.5 3.75-3.5 3.75" />,
  upload: <path d="M8 10.5V3.25M4.75 6.25 8 3l3.25 3.25M3 12.75h10" />,
  download: <path d="M8 3v7.25M4.75 7 8 10.25 11.25 7M3 12.75h10" />,
  play: (
    <path d="M5.75 4.1v7.8c0 .48.53.77.94.52l6.24-3.9a.61.61 0 0 0 0-1.04L6.69 3.58a.61.61 0 0 0-.94.52Z" />
  ),
  pause: <path d="M5.75 4v8M10.25 4v8" />,
  close: <path d="m4.25 4.25 7.5 7.5M11.75 4.25l-7.5 7.5" />,
  refresh: (
    <>
      <path d="M13.25 8A5.25 5.25 0 1 1 11.6 4.2" />
      <path d="M13.25 2.75v2.7h-2.7" />
    </>
  ),
  check: <path d="m3.5 8.5 3 3 6-7" />,
  mic: (
    <>
      <rect x="6" y="2" width="4" height="7" rx="2" />
      <path d="M3.5 7.75a4.5 4.5 0 0 0 9 0M8 12.25V14" />
    </>
  ),
  trash: (
    <>
      <path d="M3 4.5h10M6.25 4.5V3.25a.75.75 0 0 1 .75-.75h2a.75.75 0 0 1 .75.75V4.5" />
      <path d="m4.25 4.5.55 8.05a1 1 0 0 0 1 .95h4.4a1 1 0 0 0 1-.95l.55-8.05M6.75 7.25v3.5M9.25 7.25v3.5" />
    </>
  ),
  hotwords: (
    <>
      <path d="M2.75 3.5h5.5l5 5-4.75 4.75-5-5z" />
      <path d="M5.75 6.5h.01" />
    </>
  ),
}

export function Icon({
  name,
  size = 14,
  className,
}: {
  name: IconName
  size?: number
  className?: string
}) {
  return (
    <svg
      className={className === undefined ? 'icon' : `icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  )
}
