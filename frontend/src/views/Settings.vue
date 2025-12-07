<script setup>
import { ref, onMounted, computed } from 'vue'
import {
  NCard, NForm, NFormItem, NInput, NInputNumber, NSwitch, NButton,
  NSpace, NSelect, NAlert, NDivider, NIcon, NGrid, NGi, NUpload, NTag
} from 'naive-ui'
import {
  SaveOutline, RefreshOutline, CheckmarkCircleOutline, CloseCircleOutline,
  CloudUploadOutline, TrashOutline, LogoYoutube, PowerOutline
} from '@vicons/ionicons5'
import { useAppStore } from '../stores/app'
import axios from 'axios'

const store = useAppStore()
const formRef = ref(null)
const saving = ref(false)
const testing = ref(false)
const saveMessage = ref('')
const testResult = ref(null)
const uploadingCredentials = ref(false)
const credentialsMessage = ref('')
const deletingCredentials = ref(false)
const autostartStatus = ref({ enabled: false, available: false })
const autostartLoading = ref(false)

const form = ref({
  download_dir: '',
  smb_enabled: false,
  smb_host: '',
  smb_share: '',
  smb_user: '',
  smb_password: '',
  smb_path: '/youtube',
  smb_shorts_path: '/shorts',
  max_concurrent_smb_uploads: 3,
  video_quality: 'best',
  max_concurrent_downloads: 3,
  max_concurrent_shorts_downloads: 3,
  delete_after_upload: true,
  shorts_max_duration: 60,
  sync_days_back: 5
})

const qualityOptions = [
  { label: 'Best', value: 'best' },
  { label: '1080p', value: '1080p' },
  { label: '720p', value: '720p' },
  { label: '480p', value: '480p' }
]

const youtubeStatus = computed(() => store.youtubeStatus)

onMounted(async () => {
  await Promise.all([
    store.fetchConfig(),
    store.fetchYouTubeStatus(),
    fetchAutostartStatus()
  ])
  if (store.config) {
    Object.keys(form.value).forEach(key => {
      if (store.config[key] !== undefined) {
        form.value[key] = store.config[key]
      }
    })
  }
})

async function fetchAutostartStatus() {
  try {
    const response = await axios.get('/api/config/autostart')
    autostartStatus.value = response.data
  } catch (error) {
    console.error('Failed to fetch autostart status:', error)
  }
}

async function toggleAutostart() {
  autostartLoading.value = true
  try {
    if (autostartStatus.value.enabled) {
      await axios.post('/api/config/autostart/disable')
      autostartStatus.value.enabled = false
    } else {
      await axios.post('/api/config/autostart/enable')
      autostartStatus.value.enabled = true
    }
  } catch (error) {
    console.error('Failed to toggle autostart:', error)
    // Refresh status in case of error
    await fetchAutostartStatus()
  } finally {
    autostartLoading.value = false
  }
}

async function handleCredentialsUpload({ file }) {
  uploadingCredentials.value = true
  credentialsMessage.value = ''

  const formData = new FormData()
  formData.append('file', file.file)

  try {
    const response = await axios.post('/api/youtube/credentials/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    credentialsMessage.value = response.data.message
    await store.fetchYouTubeStatus()
  } catch (error) {
    console.error('Upload error:', error)
    credentialsMessage.value = error.response?.data?.detail || error.response?.data?.message || error.message || 'Upload failed'
  } finally {
    uploadingCredentials.value = false
  }

  return false // Prevent default upload behavior
}

async function deleteCredentials() {
  if (!confirm('Are you sure you want to delete all Google credentials? You will need to re-upload and re-authorize.')) {
    return
  }

  deletingCredentials.value = true
  credentialsMessage.value = ''

  try {
    const response = await axios.delete('/api/youtube/credentials')
    credentialsMessage.value = response.data.message
    await store.fetchYouTubeStatus()
  } catch (error) {
    credentialsMessage.value = error.response?.data?.detail || 'Delete failed'
  } finally {
    deletingCredentials.value = false
  }
}

async function saveConfig() {
  saving.value = true
  saveMessage.value = ''
  try {
    const result = await store.updateConfig(form.value)
    if (result.success) {
      saveMessage.value = 'Settings saved successfully'
    } else {
      saveMessage.value = 'Failed to save: ' + result.error
    }
    setTimeout(() => saveMessage.value = '', 3000)
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    // Send form values so user can test before saving
    const credentials = {
      host: form.value.smb_host,
      share: form.value.smb_share,
      user: form.value.smb_user,
      password: form.value.smb_password,
      path: form.value.smb_path
    }
    const result = await store.testSMBConnection(credentials)
    testResult.value = result
  } catch (error) {
    testResult.value = { success: false, message: error.message }
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div style="max-width: 800px;">
    <n-alert v-if="saveMessage" :type="saveMessage.includes('Failed') ? 'error' : 'success'" style="margin-bottom: 16px;">
      {{ saveMessage }}
    </n-alert>

    <!-- YouTube API Settings -->
    <n-card style="margin-bottom: 16px;">
      <template #header>
        <n-space align="center">
          <n-icon :component="LogoYoutube" size="20" />
          <span>YouTube API Credentials</span>
        </n-space>
      </template>

      <n-space vertical :size="16">
        <!-- Status -->
        <n-space align="center">
          <span>Status:</span>
          <n-tag v-if="youtubeStatus?.credentials_valid" type="success" size="small">
            <template #icon>
              <n-icon :component="CheckmarkCircleOutline" />
            </template>
            Connected
          </n-tag>
          <n-tag v-else-if="youtubeStatus?.client_file_exists" type="warning" size="small">
            Credentials uploaded - Authorization needed
          </n-tag>
          <n-tag v-else type="error" size="small">
            <template #icon>
              <n-icon :component="CloseCircleOutline" />
            </template>
            Not configured
          </n-tag>
        </n-space>

        <!-- Upload section -->
        <div v-if="!youtubeStatus?.client_file_exists">
          <p style="margin: 0 0 12px 0; color: #666;">
            Upload your Google OAuth client credentials file (google-client.json) to enable YouTube subscription sync.
          </p>
          <n-upload
            accept=".json"
            :max="1"
            :custom-request="handleCredentialsUpload"
            :show-file-list="false"
          >
            <n-button :loading="uploadingCredentials">
              <template #icon>
                <n-icon :component="CloudUploadOutline" />
              </template>
              Upload google-client.json
            </n-button>
          </n-upload>
        </div>

        <!-- Credentials loaded -->
        <div v-else>
          <n-space align="center">
            <n-tag type="info" size="small">google-client.json loaded</n-tag>
            <n-button
              size="small"
              type="error"
              quaternary
              @click="deleteCredentials"
              :loading="deletingCredentials"
            >
              <template #icon>
                <n-icon :component="TrashOutline" />
              </template>
              Delete credentials
            </n-button>
          </n-space>
        </div>

        <!-- Message -->
        <n-alert
          v-if="credentialsMessage"
          :type="credentialsMessage.includes('failed') || credentialsMessage.includes('Invalid') ? 'error' : 'success'"
          closable
          @close="credentialsMessage = ''"
        >
          {{ credentialsMessage }}
        </n-alert>

        <!-- Help text -->
        <p style="margin: 0; color: #888; font-size: 13px;">
          Get credentials from
          <a href="https://console.cloud.google.com/apis/credentials" target="_blank">Google Cloud Console</a>
          (OAuth 2.0 Client ID → Web application → Add redirect URI → Download JSON)
        </p>
      </n-space>
    </n-card>

    <n-card title="SMB Upload Settings">
      <n-form ref="formRef" :model="form" label-placement="left" label-width="180">
        <n-form-item label="Enable SMB Upload">
          <n-switch v-model:value="form.smb_enabled" />
        </n-form-item>

        <template v-if="form.smb_enabled">
          <n-form-item label="Host">
            <n-input v-model:value="form.smb_host" placeholder="192.168.1.100" />
          </n-form-item>

          <n-form-item label="Share Name">
            <n-input v-model:value="form.smb_share" placeholder="video" />
          </n-form-item>

          <n-form-item label="Username">
            <n-input v-model:value="form.smb_user" placeholder="username" />
          </n-form-item>

          <n-form-item label="Password">
            <n-input v-model:value="form.smb_password" type="password" placeholder="password" show-password-on="click" />
          </n-form-item>

          <n-form-item label="Videos Path">
            <n-input v-model:value="form.smb_path" placeholder="/youtube" />
          </n-form-item>

          <n-form-item label="Shorts Path">
            <n-input v-model:value="form.smb_shorts_path" placeholder="/shorts" />
          </n-form-item>

          <n-form-item label="Delete After Upload">
            <n-switch v-model:value="form.delete_after_upload" />
          </n-form-item>

          <n-form-item label="Concurrent Uploads">
            <n-input-number v-model:value="form.max_concurrent_smb_uploads" :min="1" :max="10" />
          </n-form-item>

          <n-form-item label="">
            <n-space>
              <n-button @click="testConnection" :loading="testing">
                <template #icon>
                  <n-icon :component="RefreshOutline" />
                </template>
                Test Connection
              </n-button>
              <n-alert v-if="testResult" :type="testResult.success ? 'success' : 'error'" style="padding: 8px 12px;">
                <n-space align="center">
                  <n-icon :component="testResult.success ? CheckmarkCircleOutline : CloseCircleOutline" />
                  {{ testResult.message }}
                </n-space>
              </n-alert>
            </n-space>
          </n-form-item>
        </template>
      </n-form>
    </n-card>

    <n-card title="Download Settings" style="margin-top: 16px;">
      <n-form :model="form" label-placement="left" label-width="180">
        <n-form-item label="Download Directory">
          <n-input v-model:value="form.download_dir" placeholder="/path/to/downloads" style="width: 400px;" />
        </n-form-item>

        <n-form-item label="Video Quality">
          <n-select v-model:value="form.video_quality" :options="qualityOptions" style="width: 200px;" />
        </n-form-item>

        <n-form-item label="Concurrent Downloads">
          <n-input-number v-model:value="form.max_concurrent_downloads" :min="1" :max="10" />
        </n-form-item>

        <n-form-item label="Concurrent Shorts Downloads">
          <n-input-number v-model:value="form.max_concurrent_shorts_downloads" :min="1" :max="10" />
        </n-form-item>

        <n-form-item label="Shorts Max Duration (sec)">
          <n-input-number v-model:value="form.shorts_max_duration" :min="30" :max="180" />
        </n-form-item>
      </n-form>
    </n-card>

    <n-card title="Auto-Sync Settings" style="margin-top: 16px;">
      <n-form :model="form" label-placement="left" label-width="180">
        <n-form-item label="Days to Look Back">
          <n-input-number v-model:value="form.sync_days_back" :min="1" :max="30" />
        </n-form-item>
      </n-form>
    </n-card>

    <!-- Service Settings -->
    <n-card style="margin-top: 16px;">
      <template #header>
        <n-space align="center">
          <n-icon :component="PowerOutline" size="20" />
          <span>Service Settings</span>
        </n-space>
      </template>
      <n-form label-placement="left" label-width="180">
        <n-form-item label="Start on Boot">
          <n-space align="center">
            <n-switch
              :value="autostartStatus.enabled"
              :loading="autostartLoading"
              :disabled="!autostartStatus.available"
              @update:value="toggleAutostart"
            />
            <span style="color: #888; font-size: 13px;">
              <template v-if="!autostartStatus.available">
                Not available (systemd service not installed)
              </template>
              <template v-else>
                {{ autostartStatus.enabled ? 'TubeSync starts automatically when system boots' : 'TubeSync must be started manually' }}
              </template>
            </span>
          </n-space>
        </n-form-item>
      </n-form>
    </n-card>

    <div style="margin-top: 24px; text-align: right;">
      <n-button type="primary" size="large" @click="saveConfig" :loading="saving">
        <template #icon>
          <n-icon :component="SaveOutline" />
        </template>
        Save Settings
      </n-button>
    </div>
  </div>
</template>
