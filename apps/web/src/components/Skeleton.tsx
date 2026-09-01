/** 骨架屏基元：占位形状＋微光扫过，加载完成即被真实内容替换。 */
export function Skeleton({
  width,
  height = 14,
}: {
  width: number | string
  height?: number
}) {
  return <span className="skeleton" aria-hidden="true" style={{ width, height }} />
}

/** 会议列表行的骨架：两行式，与真实行同高，避免加载完成时跳动。 */
export function SkeletonListRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="list-card" data-testid="list-skeleton">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="list-row">
          <span className="list-row-main" style={{ gap: 6 }}>
            <Skeleton width={`${52 - index * 8}%`} />
            <Skeleton width={120} height={11} />
          </span>
          <Skeleton width={64} height={20} />
        </div>
      ))}
    </div>
  )
}
