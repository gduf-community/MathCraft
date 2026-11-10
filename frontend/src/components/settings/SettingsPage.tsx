import { useApp } from '../../store/AppContext'
import { ModelSettings } from './ModelSettings'

export function SettingsPage() {
  const { setHasUnsavedChanges, setIsSettingsSaving } = useApp()
  return <div className="flex min-h-0 flex-1 flex-col bg-page/60">
    <div className="shrink-0 border-b border-line bg-white px-5 py-5">
      <h2 className="text-xl font-bold">模型与服务</h2>
      <p className="mt-1 text-sm text-ink-2">管理个人 DeepSeek 与 MinerU 服务配置。题库配置请前往题库管理。</p>
    </div>
    <div className="min-h-0 flex-1 overflow-auto p-4 sm:p-6">
      <ModelSettings onDirtyChange={setHasUnsavedChanges} onSavingChange={setIsSettingsSaving} />
    </div>
  </div>
}
