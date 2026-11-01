/** 头像裁剪弹窗：图片拖拽平移 + 滑块缩放，圆形区域导出 dataURL */
import { useCallback, useEffect, useRef, useState } from 'react'
import { RotateCcw, X, ZoomIn } from 'lucide-react'

const VIEW = 260 // 预览区边长
const OUT = 240 // 导出尺寸

interface Props {
  imageSrc: string
  fileName: string
  onConfirm: (dataUrl: string) => void
  onClose: () => void
}

export default function AvatarCropModal({ imageSrc, fileName, onConfirm, onClose }: Props) {
  const imgRef = useRef<HTMLImageElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [ready, setReady] = useState(false)
  const [scale, setScale] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(null)

  // 加载图片并初始化：短边铺满圆形区域
  useEffect(() => {
    const img = new Image()
    img.onload = () => {
      imgRef.current = img
      const base = VIEW / Math.min(img.width, img.height)
      setScale(base)
      setOffset({ x: 0, y: 0 })
      setReady(true)
    }
    img.src = imageSrc
  }, [imageSrc])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const img = imgRef.current
    if (!canvas || !img || !ready) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    canvas.width = OUT
    canvas.height = OUT
    ctx.clearRect(0, 0, OUT, OUT)
    const w = img.width * scale
    const h = img.height * scale
    // 视口中心对齐图片中心 + 用户偏移，1:1 映射到导出画布
    const dx = (OUT - w) / 2 + (offset.x * OUT) / VIEW
    const dy = (OUT - h) / 2 + (offset.y * OUT) / VIEW
    ctx.drawImage(img, dx, dy, w, h)
  }, [ready, scale, offset])

  useEffect(() => {
    draw()
  }, [draw])

  const clampOffset = useCallback(
    (x: number, y: number) => {
      const img = imgRef.current
      if (!img) return { x, y }
      const w = img.width * scale
      const h = img.height * scale
      const maxX = Math.max(0, (w - VIEW) / 2)
      const maxY = Math.max(0, (h - VIEW) / 2)
      return { x: Math.min(maxX, Math.max(-maxX, x)), y: Math.min(maxY, Math.max(-maxY, y)) }
    },
    [scale],
  )

  const onPointerDown = (e: React.PointerEvent) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, baseX: offset.x, baseY: offset.y }
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current
    if (!d) return
    const next = clampOffset(d.baseX + (e.clientX - d.startX), d.baseY + (e.clientY - d.startY))
    setOffset(next)
  }
  const onPointerUp = () => {
    dragRef.current = null
  }

  const confirm = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    onConfirm(canvas.toDataURL('image/png'))
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f1b33]/45 p-4" onClick={onClose}>
      <div
        className="flex max-h-[88vh] w-[420px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h3 className="text-base font-bold text-ink">裁剪头像</h3>
          <button type="button" onClick={onClose} className="rounded p-1 text-ink-3 transition-colors hover:bg-page hover:text-ink">
            <X size={18} />
          </button>
        </div>

        <div className="flex flex-col items-center gap-4 px-5 py-5">
          {/* 裁剪预览区：圆形遮罩，图片可拖拽 */}
          <div
            className="relative cursor-grab select-none overflow-hidden rounded-full bg-page active:cursor-grabbing"
            style={{ width: VIEW, height: VIEW }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
          >
            {ready ? (
              <img
                src={imageSrc}
                alt={fileName}
                draggable={false}
                className="pointer-events-none absolute origin-top-left"
                style={{
                  width: (imgRef.current?.width ?? 0) * scale,
                  height: (imgRef.current?.height ?? 0) * scale,
                  left: `calc(50% + ${offset.x}px - ${(imgRef.current?.width ?? 0) * scale / 2}px)`,
                  top: `calc(50% + ${offset.y}px - ${(imgRef.current?.height ?? 0) * scale / 2}px)`,
                }}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-ink-3">图片加载中…</div>
            )}
          </div>

          {/* 缩放滑块 */}
          <div className="flex w-full items-center gap-3 px-2">
            <ZoomIn size={15} className="shrink-0 text-ink-3" />
            <input
              type="range"
              min={scale}
              max={Math.max(scale, 3)}
              step={0.01}
              value={scale}
              onChange={(e) => {
                const next = Number(e.target.value)
                setScale(next)
                setOffset((prev) => clampOffset(prev.x, prev.y))
              }}
              className="h-1.5 flex-1 accent-primary"
            />
            <button
              type="button"
              title="重置"
              onClick={() => {
                const base = VIEW / Math.min(imgRef.current?.width ?? VIEW, imgRef.current?.height ?? VIEW)
                setScale(base)
                setOffset({ x: 0, y: 0 })
              }}
              className="rounded-md p-1.5 text-ink-3 transition-colors hover:bg-page hover:text-primary"
            >
              <RotateCcw size={14} />
            </button>
          </div>
          <p className="text-xs text-ink-3">拖动图片调整位置，滑块缩放大小</p>
          <canvas ref={canvasRef} className="hidden" />
        </div>

        <div className="flex justify-end gap-2.5 border-t border-line px-5 py-3.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm text-ink-2 transition-colors hover:bg-page"
          >
            取消
          </button>
          <button
            type="button"
            onClick={confirm}
            className="rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-colors hover:bg-[#1a5fe6]"
          >
            确认使用
          </button>
        </div>
      </div>
    </div>
  )
}
