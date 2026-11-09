/** 显式挂载 Turnstile；每次提交、过期和错误均销毁旧票据。 */
import { useEffect, useRef, useState } from 'react'
import { getAuthConfig } from '../../api/auth'
interface TurnstileOptions { sitekey: string; action: string; callback: (token: string) => void; 'expired-callback': () => void; 'error-callback': () => void }
interface TurnstileApi { render: (element: HTMLElement, options: TurnstileOptions) => string; remove: (id: string) => void }
declare global { interface Window { turnstile?: TurnstileApi } }
let scriptFlight: Promise<void> | undefined
function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve()
  if (!scriptFlight) scriptFlight = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => { script.remove(); scriptFlight = undefined; reject(new Error('无法加载人机验证，请检查网络后重试')) }
    document.head.append(script)
  })
  return scriptFlight
}
interface Props { action: string; onToken: (token: string) => void; onRequired?: (required: boolean) => void }
export function Turnstile({ action, onToken, onRequired }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    let widget: string | undefined
    onToken('')
    onRequired?.(true)
    async function configure() {
      const config = await getAuthConfig()
      if (!active || !host.current) return
      if (config.available === false) throw new Error('认证配置不可用')
      onRequired?.(config.turnstile_enabled)
      if (!config.turnstile_enabled) return
      if (!config.site_key) throw new Error('人机验证配置不可用')
      await loadScript()
      if (!active || !host.current) return
      if (!window.turnstile) throw new Error('人机验证配置不可用')
      widget = window.turnstile.render(host.current, {
        sitekey: config.site_key, action,
        callback: token => { if (active) { setError(''); onToken(token) } },
        'expired-callback': () => { if (active) { onToken(''); setError('验证已过期，请重新验证') } },
        'error-callback': () => { if (active) { onToken(''); setError('人机验证失败，请重试') } },
      })
    }
    void configure().catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : '验证服务不可用') })
    return () => { active = false; if (widget) window.turnstile?.remove(widget) }
  }, [action, attempt, onToken, onRequired])
  return <div className="auth-challenge"><div ref={host} />{error && <div role="alert">{error}<button type="button" onClick={() => { setError(''); setAttempt(n => n + 1) }}>重试验证</button></div>}</div>
}
