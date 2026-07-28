import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({ phase: 'foundation' as const }),
})

