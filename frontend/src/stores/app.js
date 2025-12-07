import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'

const api = axios.create({
  baseURL: '/api'
})

export const useAppStore = defineStore('app', () => {
  // State
  const stats = ref(null)
  const videos = ref([])
  const videosTotal = ref(0)
  const videosPage = ref(1)
  const config = ref(null)
  const youtubeStatus = ref(null)
  const syncStatus = ref(null)
  const smbStatus = ref(null)
  const activeDownloads = ref([])
  const activeUploads = ref([])
  const uploadStats = ref({ active: 0, max: 3, queue_size: 0 })
  const ws = ref(null)
  const wsConnected = ref(false)
  const downloadsPaused = ref(false)
  const uploadsPaused = ref(false)

  // Actions
  async function fetchStats() {
    try {
      const response = await api.get('/downloads/stats')
      stats.value = response.data
    } catch (error) {
      console.error('Failed to fetch stats:', error)
    }
  }

  async function fetchVideos(page = 1, status = null) {
    try {
      const params = { page, page_size: 20 }
      if (status) params.status = status
      const response = await api.get('/downloads', { params })
      videos.value = response.data.videos
      videosTotal.value = response.data.total
      videosPage.value = page
    } catch (error) {
      console.error('Failed to fetch videos:', error)
    }
  }

  async function fetchConfig() {
    try {
      const response = await api.get('/config')
      config.value = response.data
    } catch (error) {
      console.error('Failed to fetch config:', error)
    }
  }

  async function updateConfig(newConfig) {
    try {
      await api.put('/config', newConfig)
      await fetchConfig()
      return { success: true }
    } catch (error) {
      console.error('Failed to update config:', error)
      return { success: false, error: error.message }
    }
  }

  async function fetchYouTubeStatus() {
    try {
      const response = await api.get('/youtube/status')
      youtubeStatus.value = response.data
    } catch (error) {
      console.error('Failed to fetch YouTube status:', error)
    }
  }

  async function fetchSyncStatus() {
    try {
      const response = await api.get('/youtube/sync-status')
      syncStatus.value = response.data
    } catch (error) {
      console.error('Failed to fetch sync status:', error)
    }
  }

  async function fetchSMBStatus() {
    try {
      const response = await api.get('/uploads/status')
      smbStatus.value = response.data
    } catch (error) {
      console.error('Failed to fetch SMB status:', error)
    }
  }

  async function fetchUploadProgress() {
    try {
      const response = await api.get('/uploads/progress')
      activeUploads.value = response.data.active_uploads || []
      uploadStats.value = response.data.stats || { active: 0, max: 3, queue_size: 0 }
      // Update pause status from stats
      if (response.data.stats?.paused !== undefined) {
        uploadsPaused.value = response.data.stats.paused
      }
    } catch (error) {
      console.error('Failed to fetch upload progress:', error)
    }
  }

  async function fetchUploadPauseStatus() {
    try {
      const response = await api.get('/uploads/pause/status')
      uploadsPaused.value = response.data.paused
    } catch (error) {
      console.error('Failed to fetch upload pause status:', error)
    }
  }

  async function togglePauseUploads() {
    try {
      if (uploadsPaused.value) {
        const response = await api.post('/uploads/resume')
        uploadsPaused.value = response.data.paused
      } else {
        const response = await api.post('/uploads/pause')
        uploadsPaused.value = response.data.paused
      }
      return { success: true, paused: uploadsPaused.value }
    } catch (error) {
      console.error('Failed to toggle upload pause:', error)
      throw error
    }
  }

  async function triggerSync() {
    try {
      const response = await api.post('/youtube/sync')
      await fetchStats()
      await fetchSyncStatus()
      return response.data
    } catch (error) {
      console.error('Failed to trigger sync:', error)
      throw error
    }
  }

  async function testSMBConnection(credentials = null) {
    try {
      const response = await api.post('/uploads/test', credentials)
      return response.data
    } catch (error) {
      console.error('Failed to test SMB:', error)
      throw error
    }
  }

  async function startOAuth() {
    try {
      const response = await api.post('/youtube/oauth/start')
      // Open the auth URL in a new window
      window.open(response.data.auth_url, '_blank', 'width=600,height=700')
      return response.data
    } catch (error) {
      console.error('Failed to start OAuth:', error)
      throw error
    }
  }

  async function fetchPauseStatus() {
    try {
      const response = await api.get('/downloads/pause/status')
      downloadsPaused.value = response.data.paused
    } catch (error) {
      console.error('Failed to fetch pause status:', error)
    }
  }

  async function togglePauseDownloads() {
    try {
      if (downloadsPaused.value) {
        const response = await api.post('/downloads/resume')
        downloadsPaused.value = response.data.paused
      } else {
        const response = await api.post('/downloads/pause')
        downloadsPaused.value = response.data.paused
      }
      return { success: true, paused: downloadsPaused.value }
    } catch (error) {
      console.error('Failed to toggle pause:', error)
      throw error
    }
  }

  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws`

    ws.value = new WebSocket(wsUrl)

    ws.value.onopen = () => {
      wsConnected.value = true
      console.log('WebSocket connected')
    }

    ws.value.onclose = () => {
      wsConnected.value = false
      console.log('WebSocket disconnected')
      // Reconnect after 3 seconds
      setTimeout(connectWebSocket, 3000)
    }

    ws.value.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        handleWebSocketMessage(data)
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error)
      }
    }

    ws.value.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  }

  function disconnectWebSocket() {
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
  }

  function handleWebSocketMessage(data) {
    switch (data.type) {
      case 'download_progress':
        updateDownloadProgress(data)
        break
      case 'upload_progress':
        updateUploadProgress(data)
        break
      case 'status_change':
        handleStatusChange(data)
        break
      case 'stats_update':
        stats.value = { ...stats.value, ...data }
        break
    }
  }

  function updateDownloadProgress(data) {
    const idx = activeDownloads.value.findIndex(d => d.video_id === data.video_id)
    if (idx >= 0) {
      activeDownloads.value[idx] = { ...activeDownloads.value[idx], ...data }
    } else {
      activeDownloads.value.push(data)
    }
  }

  function updateUploadProgress(data) {
    const idx = activeUploads.value.findIndex(u => u.video_id === data.video_id)
    if (idx >= 0) {
      activeUploads.value[idx] = { ...activeUploads.value[idx], ...data }
    } else {
      activeUploads.value.push(data)
    }
  }

  function handleStatusChange(data) {
    // Remove from active lists if completed
    if (data.status === 'completed') {
      activeDownloads.value = activeDownloads.value.filter(d => d.video_id !== data.video_id)
    }
    if (data.status === 'uploaded') {
      activeUploads.value = activeUploads.value.filter(u => u.video_id !== data.video_id)
    }
    // Refresh stats and sync status
    fetchStats()
    fetchSyncStatus()
    // Refresh video list
    fetchVideos(videosPage.value)
  }

  return {
    // State
    stats,
    videos,
    videosTotal,
    videosPage,
    config,
    youtubeStatus,
    syncStatus,
    smbStatus,
    activeDownloads,
    activeUploads,
    uploadStats,
    wsConnected,
    downloadsPaused,
    uploadsPaused,
    // Actions
    fetchStats,
    fetchVideos,
    fetchConfig,
    updateConfig,
    fetchYouTubeStatus,
    fetchSyncStatus,
    fetchSMBStatus,
    fetchUploadProgress,
    triggerSync,
    testSMBConnection,
    fetchPauseStatus,
    togglePauseDownloads,
    fetchUploadPauseStatus,
    togglePauseUploads,
    startOAuth,
    connectWebSocket,
    disconnectWebSocket
  }
})
