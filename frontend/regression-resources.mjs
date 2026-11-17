import process from 'node:process'
import { chromium } from 'playwright-core'

export function launchBrowser() {
  return chromium.launch({
    headless: true,
    channel: 'chromium',
    ...(process.env.AUTH_BROWSER ? { executablePath: process.env.AUTH_BROWSER } : {}),
  })
}

// Register immediately after acquisition, so setup failures also release resources.
export async function withResources(run) {
  const cleanups = []
  const errors = []
  const use = (resource, close = () => resource.close()) => {
    cleanups.unshift(close)
    return resource
  }
  try {
    await run(use)
  } catch (error) {
    errors.push(error)
  } finally {
    for (const close of cleanups) {
      try {
        await close()
      } catch (error) {
        errors.push(error)
      }
    }
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Regression and resource cleanup failed')
}
