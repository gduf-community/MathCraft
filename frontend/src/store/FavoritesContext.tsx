import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { favoritesApi } from '../api/favorites'
import type { Question } from '../types'
import type { FavoriteFolder, FavoriteItem } from '../types/favorites'

interface FavoritesState {
  items: FavoriteItem[]
  folders: FavoriteFolder[]
  /** 每个收藏夹的题量，'inbox' 表示未分类 */
  folderCounts: Record<string, number>
  loading: boolean
  /** 本次会话累计「加入组卷清单」的题量（仅演示计数） */
  pendingAssembleCount: number
  isFavorite: (questionId: string) => boolean
  /** 收藏 / 取消收藏，返回操作后的收藏状态 */
  toggleFavorite: (question: Question) => Promise<boolean>
  removeFavorite: (favoriteId: string) => Promise<FavoriteItem | null>
  restoreFavorite: (item: FavoriteItem) => Promise<void>
  createFolder: (name: string, description?: string) => Promise<FavoriteFolder>
  renameFolder: (id: string, name: string, description?: string) => Promise<void>
  deleteFolder: (id: string) => Promise<void>
  moveFavorites: (ids: string[], folderId: string) => Promise<void>
  updateQuestionSnapshot: (question: Question) => Promise<void>
  addToAssemble: (count: number) => void
}

const FavoritesContext = createContext<FavoritesState | null>(null)

export function FavoritesProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<FavoriteItem[]>([])
  const [folders, setFolders] = useState<FavoriteFolder[]>([])
  const [loading, setLoading] = useState(true)
  const [pendingAssembleCount, setPendingAssembleCount] = useState(0)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const [nextItems, nextFolders] = await Promise.all([
        favoritesApi.listFavorites(),
        favoritesApi.listFolders(),
      ])
      if (cancelled) return
      setItems(nextItems)
      setFolders(nextFolders)
      setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const favoriteIds = useMemo(() => new Set(items.map((item) => item.questionId)), [items])
  const isFavorite = useCallback((questionId: string) => favoriteIds.has(questionId), [favoriteIds])

  const toggleFavorite = useCallback(
    async (question: Question) => {
      const existing = items.find((item) => item.questionId === question.id)
      if (existing) {
        await favoritesApi.removeFavorite(existing.id)
        setItems((prev) => prev.filter((item) => item.id !== existing.id))
        return false
      }
      const added = await favoritesApi.addFavorite(question)
      setItems((prev) => (prev.some((item) => item.id === added.id) ? prev : [added, ...prev]))
      return true
    },
    [items],
  )

  const removeFavorite = useCallback(async (favoriteId: string) => {
    const removed = await favoritesApi.removeFavorite(favoriteId)
    if (removed) setItems((prev) => prev.filter((item) => item.id !== favoriteId))
    return removed
  }, [])

  const restoreFavorite = useCallback(async (item: FavoriteItem) => {
    await favoritesApi.restoreFavorite(item)
    setItems((prev) =>
      prev.some((current) => current.id === item.id || current.questionId === item.questionId)
        ? prev
        : [...prev, item],
    )
  }, [])

  const createFolder = useCallback(async (name: string, description = '') => {
    const folder = await favoritesApi.createFolder(name, description)
    setFolders((prev) => [...prev, folder])
    return folder
  }, [])

  const renameFolder = useCallback(async (id: string, name: string, description = '') => {
    await favoritesApi.renameFolder(id, name, description)
    setFolders((prev) =>
      prev.map((folder) =>
        folder.id === id ? { ...folder, name: name.trim(), description: description.trim() || undefined } : folder,
      ),
    )
  }, [])

  const deleteFolder = useCallback(async (id: string) => {
    await favoritesApi.deleteFolder(id)
    setFolders((prev) => prev.filter((folder) => folder.id !== id))
    setItems((prev) =>
      prev.map((item) => (item.folderId === id ? { ...item, folderId: 'inbox' } : item)),
    )
  }, [])

  const moveFavorites = useCallback(async (ids: string[], folderId: string) => {
    await favoritesApi.moveFavorites(ids, folderId)
    const target = new Set(ids)
    setItems((prev) =>
      prev.map((item) => (target.has(item.id) ? { ...item, folderId } : item)),
    )
  }, [])

  const updateQuestionSnapshot = useCallback(async (question: Question) => {
    await favoritesApi.updateFavoriteQuestion(question)
    setItems((prev) =>
      prev.map((item) =>
        item.questionId === question.id ? { ...item, question: { ...question, starred: true } } : item,
      ),
    )
  }, [])

  const addToAssemble = useCallback((count: number) => {
    setPendingAssembleCount((prev) => prev + Math.max(0, count))
  }, [])

  const folderCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const item of items) counts[item.folderId] = (counts[item.folderId] ?? 0) + 1
    return counts
  }, [items])

  const value: FavoritesState = {
    items,
    folders,
    folderCounts,
    loading,
    pendingAssembleCount,
    isFavorite,
    toggleFavorite,
    removeFavorite,
    restoreFavorite,
    createFolder,
    renameFolder,
    deleteFolder,
    moveFavorites,
    updateQuestionSnapshot,
    addToAssemble,
  }

  return <FavoritesContext.Provider value={value}>{children}</FavoritesContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useFavorites(): FavoritesState {
  const ctx = useContext(FavoritesContext)
  if (!ctx) throw new Error('useFavorites must be used within FavoritesProvider')
  return ctx
}
