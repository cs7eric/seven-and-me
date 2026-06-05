import React from "react"

interface DogLoaderProps {
  size?: number
  label?: string
  /** 全屏蒙版：fixed 居中盖在屏幕中间，遮挡下方内容 */
  overlay?: boolean
}

const DogLoader: React.FC<DogLoaderProps> = ({ size = 50, label = "place wait", overlay = false }) => {
  const normalized = Math.max(1, Math.min(100, size))
  const scale = normalized / 100
  const dimension = `${normalized * 2}px`

  const content = (
    <div
      className={
        overlay
          ? "flex flex-col items-center gap-3"
          : "flex w-full flex-col items-center justify-center gap-3 py-8"
      }
    >
      <div
        className="dog-loader flex items-center justify-center"
        style={{
          transform: `scale(${scale})`,
          width: dimension,
          height: dimension,
          minWidth: "20px",
          minHeight: "20px",
        }}
      >
        <div className="dog-loader__main">
          <div className="dog-loader__dog">
            <div className="dog-loader__paws">
              <div className="dog-loader__leg dog-loader__leg--bl">
                <div className="dog-loader__paw dog-loader__paw--bl" />
                <div className="dog-loader__top dog-loader__top--bl" />
              </div>
              <div className="dog-loader__leg dog-loader__leg--fl">
                <div className="dog-loader__paw dog-loader__paw--fl" />
                <div className="dog-loader__top dog-loader__top--fl" />
              </div>
              <div className="dog-loader__leg dog-loader__leg--fr">
                <div className="dog-loader__paw dog-loader__paw--fr" />
                <div className="dog-loader__top dog-loader__top--fr" />
              </div>
            </div>
            <div className="dog-loader__body">
              <div className="dog-loader__tail" />
            </div>
            <div className="dog-loader__head">
              <div className="dog-loader__snout">
                <div className="dog-loader__nose" />
                <div className="dog-loader__eyes">
                  <div className="dog-loader__eye dog-loader__eye--l" />
                  <div className="dog-loader__eye dog-loader__eye--r" />
                </div>
              </div>
            </div>
            <div className="dog-loader__head-c">
              <div className="dog-loader__ear dog-loader__ear--l" />
              <div className="dog-loader__ear dog-loader__ear--r" />
            </div>
          </div>
        </div>
      </div>
      {label ? (
        <div
          className={
            overlay
              ? "rounded-full bg-slate-900/80 px-3 py-1 text-xs font-medium tracking-wide text-white shadow-md"
              : "text-sm font-medium tracking-wide text-slate-500"
          }
        >
          {label}
        </div>
      ) : null}
    </div>
  )

  if (!overlay) {
    return (
      <div className="dog-loader-area" role="status" aria-label="loading">
        {content}
      </div>
    )
  }

  return (
    <div
      className="pointer-events-none fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/5 backdrop-blur-[1px]"
      role="status"
      aria-label="loading"
    >
      {content}
    </div>
  )
}

export default DogLoader


