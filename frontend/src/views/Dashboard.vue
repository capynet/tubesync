<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import {
  NGrid, NGi, NCard, NStatistic, NButton, NProgress,
  NTag, NSpace, NIcon, NAlert, NTooltip
} from 'naive-ui'
import {
  CloudDownloadOutline, CloudUploadOutline,
  LogoYoutube, SyncOutline, TimeOutline, PauseOutline, PlayOutline
} from '@vicons/ionicons5'
import { useAppStore } from '../stores/app'

const store = useAppStore()
const syncing = ref(false)
const syncMessage = ref('')
const authLoading = ref(false)
let refreshInterval = null

const youtubeStatus = computed(() => store.youtubeStatus)

onMounted(async () => {
  await Promise.all([
    store.fetchStats(),
    store.fetchYouTubeStatus(),
    store.fetchSyncStatus(),
    store.fetchSMBStatus(),
    store.fetchPauseStatus(),
    store.fetchUploadProgress()
  ])
  // Refresh stats and sync status every 200ms for smooth progress
  refreshInterval = setInterval(() => {
    store.fetchStats()
    store.fetchSyncStatus()
    store.fetchUploadProgress()
  }, 200)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})

async function triggerSync() {
  syncing.value = true
  syncMessage.value = ''
  try {
    const result = await store.triggerSync()
    syncMessage.value = result.message
    setTimeout(() => syncMessage.value = '', 5000)
  } catch (error) {
    syncMessage.value = 'Sync failed: ' + error.message
  } finally {
    syncing.value = false
  }
}

async function togglePause() {
  try {
    await store.togglePauseDownloads()
  } catch (error) {
    console.error('Failed to toggle pause:', error)
  }
}

async function toggleUploadPause() {
  try {
    await store.togglePauseUploads()
  } catch (error) {
    console.error('Failed to toggle upload pause:', error)
  }
}

async function startAuth() {
  authLoading.value = true
  try {
    await store.startOAuth()
    // Poll for status change after user authorizes
    const checkAuth = setInterval(async () => {
      await store.fetchYouTubeStatus()
      if (store.youtubeStatus?.credentials_valid) {
        clearInterval(checkAuth)
        authLoading.value = false
      }
    }, 2000)
    // Stop polling after 5 minutes
    setTimeout(() => {
      clearInterval(checkAuth)
      authLoading.value = false
    }, 300000)
  } catch (error) {
    console.error('Failed to start auth:', error)
    authLoading.value = false
  }
}

const downloadingCount = computed(() => {
  return store.activeDownloads?.length || 0
})

const uploadingCount = computed(() => {
  return store.activeUploads?.length || 0
})

const lastSyncFormatted = computed(() => {
  if (!store.syncStatus?.last_sync) return 'Never'
  const date = new Date(store.syncStatus.last_sync)
  return date.toLocaleString()
})

const isYouTubeConfigured = computed(() => {
  return store.youtubeStatus?.configured && store.youtubeStatus?.credentials_valid
})
</script>

<template>
  <div>
    <!-- YouTube Setup Callout -->
    <n-alert
      v-if="!isYouTubeConfigured"
      type="warning"
      :title="youtubeStatus?.client_file_exists ? 'YouTube Authorization Required' : 'YouTube API Not Configured'"
      closable
      style="margin-bottom: 24px;"
    >
      <template v-if="!youtubeStatus?.client_file_exists">
        <p style="margin: 0 0 12px 0;">
          To automatically download videos from your YouTube subscriptions, you need to set up Google API credentials:
        </p>
        <ol style="margin: 0 0 12px 0; padding-left: 20px;">
          <li>Go to <a href="https://console.cloud.google.com/apis/credentials" target="_blank">Google Cloud Console</a></li>
          <li>Create a project and enable the YouTube Data API v3</li>
          <li>Create OAuth 2.0 credentials (Web application type)</li>
          <li>Add authorized redirect URI: <code style="background: #333; padding: 2px 6px; border-radius: 3px;">http://localhost:9876/api/youtube/oauth/callback</code></li>
          <li>Download the JSON file</li>
          <li>Go to <router-link to="/settings">Settings</router-link> and upload the file</li>
          <li>Come back here to authorize</li>
        </ol>
        <n-space>
          <n-button size="small" tag="a" href="https://console.cloud.google.com/apis/credentials" target="_blank">
            Open Google Cloud Console
          </n-button>
          <n-button size="small" type="primary" @click="$router.push('/settings')">
            Go to Settings
          </n-button>
        </n-space>
      </template>
      <template v-else>
        <p style="margin: 0 0 12px 0;">
          Google API credentials found! Click the button below to authorize TubeSync to access your YouTube subscriptions.
        </p>
        <n-button type="primary" size="small" @click="startAuth" :loading="authLoading">
          Authorize with Google
        </n-button>
      </template>
    </n-alert>

    <!-- Stats Cards -->
    <n-grid :cols="3" :x-gap="16" :y-gap="16" style="margin-bottom: 24px;">
      <n-gi>
        <n-card>
          <n-statistic label="Total Downloads">
            <template #prefix>
              <n-icon :component="CloudDownloadOutline" />
            </template>
            {{ store.stats?.downloads?.completed || 0 }} / {{ store.stats?.total_videos }}
          </n-statistic>

          <div v-if="store.stats?.downloads?.pending > 0 || store.stats?.active?.videos > 0 || store.downloadsPaused" style="margin-top: 12px;">
            <n-tooltip trigger="hover">
              <template #trigger>
                <n-button
                  :type="store.downloadsPaused ? 'success' : 'warning'"
                  size="small"
                  @click="togglePause"
                >
                  <template #icon>
                    <n-icon :component="store.downloadsPaused ? PlayOutline : PauseOutline" />
                  </template>
                  {{ store.downloadsPaused ? 'Resume' : 'Pause' }}
                </n-button>
              </template>
              {{ store.downloadsPaused ? 'Resume downloads' : 'Pause downloads (current ones will finish)' }}
            </n-tooltip>
          </div>

          <template #footer>
            <n-tag type="info" size="small" v-if="store.stats?.total_videos > 0">
              {{ store.stats?.active?.videos || 0 }} downloading now
            </n-tag>
            <n-tag type="default" size="small" v-else>No videos yet</n-tag>
          </template>
        </n-card>
      </n-gi>

      <n-gi>
        <n-card>
          <n-statistic>
            <template #label>
              <n-space align="center" :size="8">
                SMB Uploads
                <n-tag :type="store.smbStatus?.connected ? 'success' : 'error'" size="small">
                  {{ store.smbStatus?.connected ? 'Connected' : 'Disconnected' }}
                </n-tag>
              </n-space>
            </template>
            <template #prefix>
              <n-icon :component="CloudUploadOutline" />
            </template>
            {{ store.stats?.uploads?.uploaded || 0 }} / {{ (store.stats?.uploads?.uploaded || 0) + (store.stats?.uploads?.pending || 0) }}
          </n-statistic>

          <div v-if="store.smbStatus?.connected && (store.uploadStats?.active > 0 || (store.uploadsPaused && store.stats?.uploads?.pending > 0))" style="margin-top: 12px;">
            <n-tooltip trigger="hover">
              <template #trigger>
                <n-button
                  :type="store.uploadsPaused ? 'success' : 'warning'"
                  size="small"
                  @click="toggleUploadPause"
                >
                  <template #icon>
                    <n-icon :component="store.uploadsPaused ? PlayOutline : PauseOutline" />
                  </template>
                  {{ store.uploadsPaused ? 'Resume' : 'Pause' }}
                </n-button>
              </template>
              {{ store.uploadsPaused ? 'Resume uploads' : 'Pause uploads (current ones will finish)' }}
            </n-tooltip>
          </div>

          <template #footer>
            <n-tag type="info" size="small">
              {{ store.uploadStats?.active || 0 }} uploading now
            </n-tag>
          </template>
        </n-card>
      </n-gi>

      <n-gi>
        <n-card>
          <n-statistic label="Channels">
            <template #prefix>
              <n-icon :component="LogoYoutube" />
            </template>
            {{ store.stats?.channels || store.syncStatus?.channel_count || 0 }}
          </n-statistic>
          <template #footer>
            <n-space>
              <n-tag :type="isYouTubeConfigured ? 'success' : 'warning'" size="small">
                {{ isYouTubeConfigured ? 'Connected' : 'Not configured' }}
              </n-tag>
            </n-space>
          </template>
        </n-card>
      </n-gi>
    </n-grid>

    <!-- Auto Sync Status -->
    <n-card style="margin-bottom: 24px;">
      <n-space align="center" justify="space-between">
        <div>
          <n-space align="center" :size="12">
            <n-icon :component="TimeOutline" size="24" />
            <div>
              <h3 style="margin: 0 0 4px 0;">Auto Sync</h3>
              <p style="margin: 0; color: #888; font-size: 14px;">
                Runs every hour - Last: {{ lastSyncFormatted }}
                <span v-if="store.syncStatus?.last_queued > 0">
                  ({{ store.syncStatus.last_queued }} videos queued)
                </span>
              </p>
            </div>
          </n-space>
        </div>
        <n-space>
          <n-tooltip trigger="hover">
            <template #trigger>
              <n-button
                type="primary"
                :loading="syncing || store.syncStatus?.running"
                @click="triggerSync"
                :disabled="!isYouTubeConfigured"
              >
                <template #icon>
                  <n-icon :component="SyncOutline" />
                </template>
                Sync Now
              </n-button>
            </template>
            Manually trigger sync (normally automatic every hour)
          </n-tooltip>
        </n-space>
      </n-space>
      <!-- Sync Progress Bar (only during sync) -->
      <div v-if="store.syncStatus?.running && store.syncStatus?.progress_total > 0" style="margin-top: 16px;">
        <n-space justify="space-between" style="margin-bottom: 4px;">
          <span>Scanning channels...</span>
          <span>{{ store.syncStatus.progress_current }} / {{ store.syncStatus.progress_total }}</span>
        </n-space>
        <n-progress
          type="line"
          :percentage="Math.round((store.syncStatus.progress_current / store.syncStatus.progress_total) * 100)"
          :show-indicator="false"
          status="info"
        />
      </div>
      <!-- Channel results (persists after sync) -->
      <div v-if="store.syncStatus?.channel_results?.length > 0" style="margin-top: 16px;">
        <n-space justify="space-between" align="center" style="margin-bottom: 8px;">
          <span style="font-size: 13px; color: #888;">
            {{ store.syncStatus.running ? 'Channels with new videos:' : 'Last sync results:' }}
          </span>
          <n-tag size="small" :type="store.syncStatus.running ? 'info' : 'success'">
            {{ store.syncStatus.total_videos_found || store.syncStatus.channel_results.reduce((sum, ch) => sum + ch.videos_found, 0) }} videos from {{ store.syncStatus.channels_with_videos || store.syncStatus.channel_results.length }} channels
          </n-tag>
        </n-space>
        <div>
          <n-space vertical :size="4">
            <n-tag v-for="(ch, idx) in store.syncStatus.channel_results.slice().reverse()" :key="idx" size="small" type="success">
              {{ ch.channel_name }}: {{ ch.videos_found }} video{{ ch.videos_found > 1 ? 's' : '' }}
            </n-tag>
          </n-space>
        </div>
      </div>
      <n-alert v-if="syncMessage" :type="syncMessage.includes('failed') ? 'error' : 'success'" style="margin-top: 16px;">
        {{ syncMessage }}
      </n-alert>
      <n-alert v-if="store.youtubeStatus?.quota_exceeded" type="warning" style="margin-top: 16px;">
        YouTube API quota exceeded. Will reset at {{ store.youtubeStatus?.quota_reset_time || 'midnight PT' }}
      </n-alert>
    </n-card>


  </div>
</template>
