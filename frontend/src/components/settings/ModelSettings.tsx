import { PersonalModelSettings } from '../tabs/ProfileTab/PersonalModelSettings'

interface ModelSettingsProps {
  onDirtyChange?: (dirty: boolean) => void
}

export function ModelSettings({ onDirtyChange }: ModelSettingsProps) {
  return <PersonalModelSettings onDirtyChange={onDirtyChange} />
}
