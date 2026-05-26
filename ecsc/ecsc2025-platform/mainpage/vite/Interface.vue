<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  getInterface,
  putInterface,
  InterfaceConfig,
  getHumanReadableError,
  Peer as PeerT,
  getKeySlots,
  KeySlot,
} from "./api";
import Peer from "./Peer.vue";
import ConfigLine from "./ConfigLine.vue";

const props = defineProps<{
  initialInterfaceConfig: InterfaceConfig;
}>();

const interfaceConfig = ref<InterfaceConfig | null>(null);
const configError = ref<string | null>(null);
const keySlots = ref<KeySlot[] | null>(null);

const toDeletePeers = reactive<Set<number>>(new Set());

const peerChanges = reactive<Map<number, PeerT>>(new Map());
const interfacePropertyChanges = reactive<Map<string, any>>(new Map());

const saveButtonText = ref("Save Changes");
const discardButtonText = ref("Discard Changes");

const effectiveInterfaceConfig = computed(() => {
  if (!interfaceConfig.value) return null;
  let effective = { ...interfaceConfig.value };
  for (let [key, value] of interfacePropertyChanges.entries()) {
    effective[key] = value;
  }
  return effective;
});

const sortedPeers = computed(() => {
  if (!interfaceConfig.value) return [];
  return interfaceConfig.value.peers.toSorted(
    (a: PeerT, b: PeerT) => a.order - b.order,
  );
});

const effectivePeers = computed(() => {
  return sortedPeers.value
    .map((peer: PeerT, i: number) => {
      const updated = peerChanges.has(i);
      const use_peer = updated ? peerChanges.get(i) : peer;
      return {
        peer: use_peer,
        key_slot: keySlots.value.find((ks) => ks.id === use_peer.key_slot),
      };
    })
    .filter((e) => e.key_slot !== undefined);
});

const hasChanges = computed(() => {
  return (
    toDeletePeers.size > 0 ||
    peerChanges.size > 0 ||
    interfacePropertyChanges.size > 0
  );
});

function addPeer() {
  if (!interfaceConfig.value) return;
  const maxIp = Math.max(
    ...interfaceConfig.value.peers.map((p) =>
      Number(p.cidr.split("/")[0].split(".")[3]),
    ),
  );
  const maxOrder = Math.max(...interfaceConfig.value.peers.map((p) => p.order));
  const [teamId1, teamId2, teamId3] = interfaceConfig.value.cidr
    .split(".")
    .slice(0, 3)
    .map(Number);
  const newPeer: PeerT = {
    cidr: `${teamId1}.${teamId2}.${teamId3}.${maxIp + 1}/32`,
    key_slot: 0,
    order: maxOrder + 1,
    managed: false,
    comment: "",
    enabled: true,
  };
  interfaceConfig.value.peers.push(newPeer);
}

function removePeer(index: number) {
  if (!interfaceConfig.value) return;
  if (toDeletePeers.has(index)) {
    toDeletePeers.delete(index);
  } else {
    toDeletePeers.add(index);
  }
}

function restorePeer(index: number) {
  toDeletePeers.delete(index);
}

function changePeer(peer: PeerT, index: number) {
  peerChanges.set(index, peer);
  configError.value = null;
}

function changeAutoIpAssignment(value: boolean) {
  if (interfaceConfig.value.auto_ip_assignment != value) {
    interfacePropertyChanges.set("auto_ip_assignment", value);
  } else {
    interfacePropertyChanges.delete("auto_ip_assignment");
  }
}

async function saveChanges() {
  configError.value = null;
  if (!interfaceConfig.value) return;
  const newPeers = effectivePeers.value
    .map((p: any) => p.peer)
    .filter((_: any, index: number) => !toDeletePeers.has(index));
  try {
    let saveData = {
      ...interfaceConfig.value,
      peers: newPeers,
    };
    for (let [key, value] of interfacePropertyChanges.entries()) {
      saveData[key] = value;
    }
    interfaceConfig.value = await putInterface(saveData);
    saveButtonText.value = "✓ Changes Saved";
    peerChanges.clear();
    toDeletePeers.clear();
    interfacePropertyChanges.clear();
  } catch (error) {
    const convertedError = getHumanReadableError(error);
    configError.value = convertedError;
    saveButtonText.value = "Configuration Error";
  }
  setTimeout(() => {
    saveButtonText.value = "Save Changes";
  }, 2000);
}

function discardChanges() {
  configError.value = null;
  peerChanges.clear();
  toDeletePeers.clear();
  interfacePropertyChanges.clear();
  discardButtonText.value = "✓ Changes Discarded";
  setTimeout(() => {
    discardButtonText.value = "Discard Changes";
  }, 2000);
}

function replaceKeySlots(newKeySlots: KeySlot[]) {
  keySlots.value = newKeySlots;
  setTimeout(async () => {
    interfaceConfig.value = await getInterface();
  }, 500);
}

async function reload() {
  toDeletePeers.clear();
  peerChanges.clear();
  interfacePropertyChanges.clear();
  interfaceConfig.value = await getInterface();
  keySlots.value = await getKeySlots();
}

onMounted(async function () {
  if (props.initialInterfaceConfig) {
    interfaceConfig.value = props.initialInterfaceConfig;
  } else {
    interfaceConfig.value = await getInterface();
  }
  keySlots.value = await getKeySlots();
});

defineExpose({
  replaceKeySlots,
});
</script>

<template>
  <div v-if="interfaceConfig && keySlots">
    <div class="wg-conf-wrapper">
      <div class="wg-conf-section">
        <ConfigLine> [Interface]</ConfigLine>
        <ConfigLine> PublicKey={{ interfaceConfig.public_key }}</ConfigLine>

        <ConfigLine commented>Host={{ interfaceConfig.vpn_host }}</ConfigLine>
        <ConfigLine> ListenPort={{ interfaceConfig.vpn_port }}</ConfigLine>
        <ConfigLine commented>
          You can ping the game router at the IP below:
        </ConfigLine>
        <ConfigLine> Address={{ interfaceConfig.cidr }}</ConfigLine>
        <br />
        <Peer
          v-for="({ peer, key_slot }, i) in effectivePeers"
          :key="i"
          :peer="peer"
          :key_slots="keySlots"
          :currentKey="key_slot"
          :toDelete="toDeletePeers.has(i)"
          @change="(peer) => changePeer(peer, i)"
          @removePeer="() => removePeer(i)"
          @restorePeer="() => restorePeer(i)"
        />
        <template v-if="!initialInterfaceConfig.managed">
          #
          <button @click="addPeer" class="button">Add Peer</button>
          <br /><br />
          # Automatically assign free IPs to new keys:
          <input
            type="checkbox"
            value=""
            id="auto_ip_assignment"
            :checked="effectiveInterfaceConfig.auto_ip_assignment"
            @change="
              (e) =>
                changeAutoIpAssignment((e.target as HTMLInputElement).checked)
            "
          />
          <br />
          <span class="error" v-if="configError"> # {{ configError }} </span
          ><br />
          <ConfigLine commented> Last modified:</ConfigLine>
          <ConfigLine commented>{{ interfaceConfig.last_modified }}</ConfigLine>
          <template v-if="interfaceConfig.last_synced">
            <ConfigLine commented> Last version synced with router:</ConfigLine>
            <ConfigLine commented>{{ interfaceConfig.last_synced }}</ConfigLine>
          </template>
        </template>
      </div>

      <template v-if="!initialInterfaceConfig.managed">
        <button :disabled="!hasChanges" @click="saveChanges" class="button">
          {{ saveButtonText }}
        </button>
        <button :disabled="!hasChanges" @click="discardChanges" class="button">
          {{ discardButtonText }}
        </button>
        <button @click="reload" :disabled="hasChanges" class="button">
          Reload
        </button>
      </template>
    </div>
  </div>
  <div v-else>Loading...</div>
</template>

<style scoped></style>
