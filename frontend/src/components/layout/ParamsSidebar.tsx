import { useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { ChevronsLeft, ChevronsRight, FileText, Loader2, Sparkles } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { DIFFICULTIES, TYPE_LABELS, TYPE_ORDER } from '../../constants'
import Dropdown from '../ui/Dropdown'

/** 面板宽度拖拽范围：默认最宽，只能向左收窄 */
const PANEL_MIN_WIDTH = 220
const PANEL_MAX_WIDTH = 300

/** 右侧「题目参数」面板：仅出现在智能生成标签页，可向右折叠，左缘可拖拽调宽 */
export default function ParamsSidebar() {
  const {
    paramsCollapsed,
    toggleParams,
    kbs,
    docs,
    selectedKbId,
    selectedDocId,
    selectKb,
    selectDoc,
    typeConfigs,
    setTypeConfig,
    difficulty,
    setDifficulty,
    knowledgeScope,
    setKnowledgeScope,
    generating,
    generate,
  } = useApp()

  // 拖拽调宽：手柄在面板左缘，向右拖变窄，向左拖变宽（上限即默认宽度）
  const [panelWidth, setPanelWidth] = useState(PANEL_MAX_WIDTH)
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef({ x: 0, width: PANEL_MAX_WIDTH })

  const startResize = (e: ReactMouseEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragStart.current = { x: e.clientX, width: panelWidth }
    setDragging(true)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'

    const onMove = (ev: MouseEvent) => {
      ev.preventDefault()
      const next = dragStart.current.width + (dragStart.current.x - ev.clientX)
      setPanelWidth(Math.min(PANEL_MAX_WIDTH, Math.max(PANEL_MIN_WIDTH, next)))
    }
    const onUp = () => {
      setDragging(false)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  // 折叠态：右侧细条，点击展开
  if (paramsCollapsed) {
    return (
      <aside className="z-10 my-4 mr-4 flex w-12 shrink-0 flex-col items-center gap-3 rounded-2xl border border-line/70 bg-white py-4 shadow-[0_6px_24px_rgba(30,90,180,0.06)]">
        <button
          type="button"
          onClick={toggleParams}
          title="展开参数面板"
          className="rounded-lg p-1.5 text-ink-3 transition-colors hover:bg-primary-weak hover:text-primary"
        >
          <ChevronsLeft size={18} />
        </button>
        <button
          type="button"
          onClick={toggleParams}
          className="flex-1 cursor-pointer text-sm font-semibold tracking-[0.3em] text-ink-2 [writing-mode:vertical-rl] transition-colors hover:text-primary"
        >
          题目参数
        </button>
      </aside>
    )
  }

  return (
    <aside
      className={`relative z-10 my-4 mr-4 flex shrink-0 flex-col overflow-hidden rounded-2xl border border-line/70 bg-white shadow-[0_6px_24px_rgba(30,90,180,0.06)] ${dragging ? '' : 'transition-all duration-300'}`}
      style={{ width: panelWidth }}
    >
      {/* 拖拽调宽手柄 */}
      <div
        onMouseDown={startResize}
        title="拖动调整面板宽度"
        className={`absolute top-0 bottom-0 left-0 z-20 w-1.5 cursor-col-resize transition-colors ${
          dragging ? 'bg-primary/70' : 'bg-transparent hover:bg-primary/30'
        }`}
      />
      {/* 面板头部 */}
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div className="flex items-center gap-2 text-[17px] font-bold text-ink">
          <FileText size={18} className="text-primary" />
          题目参数
        </div>
        <button
          type="button"
          onClick={toggleParams}
          className="flex items-center gap-1 text-xs text-ink-3 transition-colors hover:text-primary"
        >
          折叠 <ChevronsRight size={14} />
        </button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
        {/* 1. 选择知识库文档：先选知识库，再选其中一份文档 */}
        <section>
          <h3 className="mb-2.5 text-sm font-bold text-ink">1. 选择知识库文档</h3>
          <Dropdown
            value={selectedKbId}
            options={kbs.map((k) => ({ value: k.id, label: k.name }))}
            onChange={(v) => selectKb(v)}
            placeholder="请选择知识库"
          />
          <ul className="mt-2 space-y-1.5">
            {docs.map((d) => {
              const selected = d.id === selectedDocId
              return (
                <li key={d.id}>
                  <button
                    type="button"
                    onClick={() => selectDoc(d.id)}
                    className={`flex w-full items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left text-[14px] transition-colors ${
                      selected
                        ? 'border-primary/50 bg-primary-weak'
                        : 'border-line bg-white hover:border-primary/40'
                    }`}
                  >
                    <FileText size={16} className={selected ? 'text-primary' : 'text-ink-3'} />
                    <span className={`flex-1 truncate ${selected ? 'font-medium text-ink' : 'text-ink-2'}`}>
                      {d.name}
                    </span>
                    {selected && <span className="rounded bg-primary px-1.5 py-0.5 text-[11px] text-white">已选</span>}
                  </button>
                </li>
              )
            })}
            {!docs.length && <li className="py-3 text-center text-xs text-ink-3">该知识库暂无文档</li>}
          </ul>
        </section>

        {/* 2. 描述知识点或者章节范围 */}
        <section>
          <h3 className="mb-2.5 text-sm font-bold text-ink">2. 描述知识点或者章节范围</h3>
          <input
            type="text"
            value={knowledgeScope}
            onChange={(e) => setKnowledgeScope(e.target.value)}
            placeholder="如：导数的定义与求导法则"
            className="block w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-primary"
          />
        </section>

        {/* 3. 选择题型和题数：每个题型带数量输入框 */}
        <section>
          <h3 className="mb-2.5 text-sm font-bold text-ink">3. 选择题型和题数</h3>
          <div className="divide-y divide-line/70 rounded-lg border border-line px-3">
            {TYPE_ORDER.map((t) => {
              const cfg = typeConfigs[t]
              return (
                <div key={t} className="flex items-center gap-2.5 py-2.5">
                  <input
                    type="checkbox"
                    checked={cfg.checked}
                    onChange={(e) => setTypeConfig(t, { checked: e.target.checked })}
                    className="h-4 w-4 accent-primary"
                  />
                  <span className="flex-1 text-sm text-ink">{TYPE_LABELS[t]}</span>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={cfg.count || ''}
                    placeholder="0"
                    onChange={(e) => {
                      const v = Math.max(0, Math.min(20, Number(e.target.value) || 0))
                      setTypeConfig(t, { count: v, checked: v > 0 ? true : cfg.checked })
                    }}
                    className="h-7 w-14 rounded-md border border-line bg-page px-1 text-center text-sm text-ink outline-none transition-colors focus:border-primary"
                  />
                </div>
              )
            })}
          </div>
        </section>

        {/* 4. 选择题目难度 */}
        <section>
          <h3 className="mb-2.5 text-sm font-bold text-ink">4. 选择题目难度</h3>
          <div className="grid grid-cols-4 gap-2">
            {DIFFICULTIES.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDifficulty(d)}
                className={`rounded-lg py-2 text-sm transition-colors ${
                  difficulty === d
                    ? 'bg-primary font-medium text-white'
                    : 'bg-page text-ink-2 hover:bg-primary-weak hover:text-primary'
                }`}
              >
                {d}
              </button>
            ))}
          </div>
        </section>
      </div>

      {/* 生成按钮 */}
      <div className="border-t border-line px-5 py-4">
        <button
          type="button"
          disabled={generating}
          onClick={() => void generate()}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary py-3 text-[16px] font-semibold text-white shadow-[0_4px_14px_rgba(30,111,255,0.35)] transition-all hover:bg-[#1a5fe6] active:scale-[0.98] disabled:opacity-60"
        >
          {generating ? <Loader2 size={17} className="animate-spin" /> : <Sparkles size={17} />}
          {generating ? '生成中…' : '生成题目'}
        </button>
      </div>
    </aside>
  )
}
