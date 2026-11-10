import { PersonalModelSettings } from './PersonalModelSettings'

interface ModelSettingsProps {
  onDirtyChange?: (dirty: boolean) => void
  onSavingChange?: (saving: boolean) => void
}

export function ModelSettings({ onDirtyChange, onSavingChange }: ModelSettingsProps) {
  return <PersonalModelSettings onDirtyChange={onDirtyChange} onSavingChange={onSavingChange} />
}
