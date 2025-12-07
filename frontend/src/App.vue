<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { NLayout, NLayoutHeader, NLayoutContent, NMenu, NIcon, NSpace, NButton, NConfigProvider, darkTheme } from 'naive-ui'
import { HomeOutline, SettingsOutline, SyncOutline } from '@vicons/ionicons5'
import { useAppStore } from './stores/app'

const router = useRouter()
const store = useAppStore()
const isDark = ref(true)

const menuOptions = [
  {
    label: 'Dashboard',
    key: '/',
    icon: () => h(NIcon, null, { default: () => h(HomeOutline) })
  },
  {
    label: 'Settings',
    key: '/settings',
    icon: () => h(NIcon, null, { default: () => h(SettingsOutline) })
  }
]

const activeKey = ref('/')

function handleMenuUpdate(key) {
  activeKey.value = key
  router.push(key)
}

import { h } from 'vue'

onMounted(() => {
  store.connectWebSocket()
  store.fetchStats()
})

onUnmounted(() => {
  store.disconnectWebSocket()
})
</script>

<template>
  <n-config-provider :theme="isDark ? darkTheme : null">
    <n-layout style="min-height: 100vh">
      <n-layout-header bordered style="padding: 12px 24px; display: flex; align-items: center; justify-content: space-between;">
        <n-space align="center">
          <span style="font-size: 20px; font-weight: 600;">TubeSync</span>
        </n-space>
        <n-menu
          mode="horizontal"
          :options="menuOptions"
          :value="activeKey"
          @update:value="handleMenuUpdate"
        />
      </n-layout-header>
      <n-layout-content style="padding: 24px;">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-config-provider>
</template>

<style>
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
</style>
