import { useState } from 'react'
import { Boxes, Database, FileScan, SlidersHorizontal } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { EngineSettings } from './EngineSettings'
import { KnowledgeConnections } from './KnowledgeConnections'
import { ModelSettings } from './ModelSettings'
import { ParsingSettings } from './ParsingSettings'

type Section = 'models' | 'knowledge' | 'engines' | 'parsing'
const SECTIONS = [
  { key: 'models', label: '模型与服务', icon: SlidersHorizontal },
  { key: 'knowledge', label: '知识库连接', icon: Database },
  { key: 'engines', label: '知识库引擎', icon: Boxes },
  { key: 'parsing', label: '文档解析', icon: FileScan },
] as const

export function SettingsPage({ initialEngine }: { initialEngine?: string }) {
  const [section, setSection] = useState<Section>(initialEngine ? 'engines' : 'models')
  const { hasUnsavedChanges, setHasUnsavedChanges } = useApp()
  const switchSection = (next: Section) => {
    if (next === section) return
    if (hasUnsavedChanges && !window.confirm('有未保存的更改，确定切换设置分区并放弃更改？')) return
    setHasUnsavedChanges(false)
    setSection(next)
  }
  return <div className="flex min-h-0 flex-1 flex-col bg-page/60">
    <div className="shrink-0 border-b border-line bg-white px-5 pt-5">
      <h2 className="text-xl font-bold">应用设置</h2>
      <p className="mt-1 text-sm text-ink-2">管理教学服务的模型、知识库连接、知识库引擎与文档解析。</p>
      <div className="mt-4 flex gap-1 overflow-x-auto" role="tablist" aria-label="设置分区">
        {SECTIONS.map(({ key, label, icon: Icon }) => <button key={key} type="button" role="tab" aria-selected={section === key} onClick={() => switchSection(key)} className={
          'flex shrink-0 items-center gap-2 border-b-2 px-4 py-3 text-sm ' + (section === key ? 'border-primary font-semibold text-primary' : 'border-transparent text-ink-2 hover:text-primary')
        }><Icon size={17} />{label}</button>)}
      </div>
    </div>
    <div className="min-h-0 flex-1 overflow-auto p-4 sm:p-6" role="tabpanel">
      {section === 'models' && <ModelSettings onDirtyChange={setHasUnsavedChanges} />}
      {section === 'knowledge' && <KnowledgeConnections />}
      {section === 'engines' && <EngineSettings initialEngine={initialEngine} onDirtyChange={setHasUnsavedChanges} />}
      {section === 'parsing' && <ParsingSettings onDirtyChange={setHasUnsavedChanges} />}
    </div>
  </div>
}
