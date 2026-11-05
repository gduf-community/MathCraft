/* global console */
/** 学习空间 4 列网格布局截图验证 */
import { chromium } from 'playwright-core'
import { homedir } from 'node:os'
import { join } from 'node:path'

const exe = join(homedir(), 'AppData', 'Local', 'ms-playwright', 'chromium-1248', 'chrome-win64', 'chrome.exe')
const browser = await chromium.launch({ executablePath: exe, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto('http://localhost:5173/')
await page.waitForTimeout(2000)
await page.getByRole('button', { name: '学习空间' }).click()
await page.waitForTimeout(800)

const cards = await page.locator('.grid.grid-cols-4 > div').count()
const firstCard = await page.locator('.grid.grid-cols-4 > div').first().boundingBox()
const secondCard = await page.locator('.grid.grid-cols-4 > div').nth(1).boundingBox()
const sameRow = firstCard && secondCard && Math.abs(firstCard.y - secondCard.y) < 3
const gapOk = firstCard && secondCard && secondCard.x - (firstCard.x + firstCard.width) >= 12

// 编号点击复制
await page.locator('button[title=点击复制空间编号]').first().click()
await page.waitForTimeout(300)
const copyToast = await page.locator('text=已复制').count()

// 创建弹窗成功态
await page.getByRole('button', { name: '创建学习空间' }).click()
await page.waitForSelector('text=空间编号（创建后自动生成）')
await page.locator('input[placeholder="如：计科2班"]').fill('网格验证班')
await page.getByRole('button', { name: '创建', exact: true }).click()
await page.waitForSelector('text=创建成功')
await page.screenshot({ path: 'v7-success.png' })
await page.getByRole('button', { name: '完成' }).click()
await page.waitForTimeout(500)
const cardsAfter = await page.locator('.grid.grid-cols-4 > div').count()

// 滚到底看最后几张卡
await page.locator('.grid.grid-cols-4').evaluate((el) => el.scrollIntoView({ block: 'end' }))
await page.waitForTimeout(400)
await page.screenshot({ path: 'v7-grid-bottom.png' })

console.log(`cards=${cards} sameRow=${sameRow} gapOk=${gapOk} copy=${copyToast >= 1} after=${cardsAfter}`)
await browser.close()
