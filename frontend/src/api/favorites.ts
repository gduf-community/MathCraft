/**
 * 收藏领域 API 封装。
 *
 * 本期全部转调 `api/mock/favoritesMock`；页面与 `FavoritesContext` 只依赖本文件。
 * 后端接入时只需把这里的实现换成 HTTP 请求，调用方无需改动。
 */
import type { Question } from '../types'
import type { FavoriteFolder, FavoriteItem, FavoriteSource } from '../types/favorites'
import * as favoritesMock from './mock/favoritesMock'

export const favoritesApi = {
  listFavorites: (): Promise<FavoriteItem[]> => favoritesMock.listFavorites(),
  listFolders: (): Promise<FavoriteFolder[]> => favoritesMock.listFolders(),
  addFavorite: (question: Question, folderId?: string, source?: FavoriteSource): Promise<FavoriteItem> =>
    favoritesMock.addFavorite(question, folderId, source),
  removeFavorite: (id: string): Promise<FavoriteItem | null> => favoritesMock.removeFavorite(id),
  restoreFavorite: (item: FavoriteItem): Promise<void> => favoritesMock.restoreFavorite(item),
  createFolder: (name: string, description?: string): Promise<FavoriteFolder> =>
    favoritesMock.createFolder(name, description),
  renameFolder: (id: string, name: string, description?: string): Promise<void> =>
    favoritesMock.renameFolder(id, name, description),
  deleteFolder: (id: string): Promise<void> => favoritesMock.deleteFolder(id),
  reorderFolders: (ids: string[]): Promise<void> => favoritesMock.reorderFolders(ids),
  moveFavorites: (ids: string[], folderId: string): Promise<void> =>
    favoritesMock.moveFavorites(ids, folderId),
  updateFavoriteQuestion: (question: Question): Promise<void> =>
    favoritesMock.updateFavoriteQuestion(question),
}
