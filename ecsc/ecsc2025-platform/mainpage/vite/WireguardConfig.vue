<script setup lang="ts">
import {inject, onMounted, ref, useTemplateRef} from "vue";
import Interface from "./Interface.vue";
import KeySlots from "./KeySlots.vue";
import {getInterface, InterfaceConfig} from "./api";

const interfaceConfig = ref<InterfaceConfig | null>(null);
const hosting = inject("hosting");

const interfaceConfigComponent = useTemplateRef<typeof Interface | null>("interfaceConfigComponent");

function handleKeySlotChange(e: any) {
  if (interfaceConfigComponent.value) {
    interfaceConfigComponent.value.replaceKeySlots(e);
  }
}

onMounted(async function () {
  interfaceConfig.value = await getInterface();
});
</script>

<template>
  <div class="wg-conf">
    <h3 class="mt-4">WireGuard Keys</h3>
    <p>
      We generate WireGuard credentials for you.
    </p>
    <p>
      If you are captain or technician, you can download all config files for your team,
      make sure to not use a config someone else expects to use.
    </p>
    <p>
      Players can only see their own config files.
    </p>
    <div class="alert alert-info">
      General information about WireGuard can be found on the
      <a href="/setup">setup page</a>.
    </div>
    <KeySlots class="wg-conf-wrapper"
              :mayAdd="(interfaceConfig && !interfaceConfig.managed)"
              @change="handleKeySlotChange"/>
    <template v-if="interfaceConfig">
      <h3 class="mt-4">Interface Configuration</h3>
      <p class="text-muted">
        You can {{ interfaceConfig.managed ? 'view' : 'edit' }} our WireGuard VPN server
        config.
        <template v-if="hosting == 'cloud'">
          You're <em>cloud hosting</em>, so default settings should be good. Proceed
          with care.
        </template>
        <template v-if="hosting == 'self'">
          You're <em>self-hosting</em>, so you should have a peer for
          {{ interfaceConfig.cidr.replace("/24", "/25") }}
          <small>(or at least {{
              interfaceConfig.cidr.replace(".0/24", ".2/32")
            }})</small>.
        </template>
      </p>
      <Interface :initialInterfaceConfig="interfaceConfig"
                 ref="interfaceConfigComponent"/>
    </template>
  </div>
</template>

<style scoped>
.wg-conf-wrapper {
  margin-bottom: 1em;
}

:global(.wg-conf-section) {
  border: 1px solid #ccc;
  font-family: monospace;
  background-color: #fefefe;
  color: #333;
  padding: 1.5em;
  border-radius: 5px;
  font-size: 1em;
  box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.05);
  overflow: auto;
  position: relative;
  transition: background-color 0.3s;
}

:global(.wg-conf button) {
  background-color: #007bff;
  color: #fff;
  border: none;
  padding: 0.5em 1em;
  margin: 0.5em 0.5em 0 0;
  border-radius: 3px;
  cursor: pointer;
  font-size: 1em;
  transition: background-color 0.3s,
  transform 0.1s;
}

:global(.wg-conf button:hover) {
  background-color: #0056b3;
}

:global(.wg-conf button[disabled]) {
  background-color: #ccc;
  cursor: not-allowed;
}

:global(.wg-conf-section button) {
  background-color: #fff;
  color: #333;
  border: 1px solid black;
  padding: 0.1em 0.5em;
  border-radius: 1px;
  font-size: 0.8em;
}

:global(.wg-conf-section button:hover) {
  background-color: #f0f0f0;
  color: #000;
}

:global(.error) {
  color: red;
}

.setup-details {
  padding: 5px 10px;
  margin: 10px 0;
  background-color: #f9f9f9;
  border: 1px solid #ccc;
  border-radius: 5px;
}
</style>
