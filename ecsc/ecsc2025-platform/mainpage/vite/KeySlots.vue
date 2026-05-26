<script setup lang="ts">
import {computed, ref, reactive, onMounted, toRaw} from "vue";
import {
  CreateKeySlot,
  KeySlot,
  getKeySlots,
  deleteKeySlot,
  postKeySlot,
  putKeySlot,
  getHumanReadableError
} from "./api";
import EditKeySlot from "./EditKeySlot.vue";

const emit = defineEmits(["change"]);

const props = defineProps<{
  mayAdd: boolean;
}>();


const keySlots = ref<KeySlot[] | null>(null);
const keySlotChanges = reactive<Map<number, KeySlot>>(new Map());
const keySlotErrors = reactive<Map<number, string>>(new Map());
const toDeleteKeySlots = reactive<Set<number>>(new Set());

const effectiveKeySlots = computed(() => {
  if (!keySlots.value) return [];
  return keySlots.value.map((keySlot) => {
    const changed = keySlotChanges.has(keySlot.id);
    const effective = changed ? keySlotChanges.get(keySlot.id) : keySlot;
    return {
      effectiveKeySlot: effective,
      updated: changed,
    };
  });
});

const hasChanges = computed(() => {
  return keySlotChanges.size > 0 || toDeleteKeySlots.size > 0;
});

function discardKeySlot(index: number) {
  keySlotErrors.delete(index);
  toDeleteKeySlots.delete(index);
  keySlotChanges.delete(index);
}

function changeKeySlot(id: number, keySlot: KeySlot) {
  keySlotErrors.delete(id);
  keySlotChanges.set(id, keySlot);
}

function removeKeySlot(index: number) {
  if (!keySlots.value) return;
  if (toDeleteKeySlots.has(index)) {
    toDeleteKeySlots.delete(index);
  } else {
    toDeleteKeySlots.add(index);
  }
}

let newIndex = -1;

function addKey() {
  if (!keySlots.value) return;
  const newKeySlot: KeySlot = {
    id: newIndex--,
    owner: "You",
    name: "",
    public_key: "",
    managed: false,
    config_url: null,
  };
  keySlots.value.push(newKeySlot);
}

async function saveKeySlot(id: number) {
  if (!keySlots.value) return;
  if (toDeleteKeySlots.has(id)) {
    try {
      if (id >= 0) {
        await deleteKeySlot(id);
      }
      keySlots.value = keySlots.value.filter((ks) => ks.id !== id);
      emit("change", toRaw(keySlots.value));
    } catch (error) {
      const convertedError = getHumanReadableError(error);
      keySlotErrors.set(id, convertedError);
    }
    return;
  }

  const changed = keySlotChanges.get(id);
  if (!changed) return;
  const index = keySlots.value.findIndex((ks) => ks.id === id);
  try {
    if (changed.id <= -1) {
      const ks: CreateKeySlot = {
        name: changed.name,
        public_key: changed.public_key,
      };
      keySlots.value[index] = await postKeySlot(ks);
      emit("change", toRaw(keySlots.value));
    } else {
      keySlots.value[index] = await putKeySlot(changed);
      emit("change", toRaw(keySlots.value));
    }
  } catch (error) {
    const convertedError = getHumanReadableError(error);
    keySlotErrors.set(id, convertedError);
  }
  keySlotChanges.delete(id);
}

async function saveAll() {
  for (let ks of effectiveKeySlots.value) {
    const {effectiveKeySlot} = ks;
    await saveKeySlot(effectiveKeySlot.id);
  }
}

async function reload() {
  keySlotChanges.clear();
  keySlotErrors.clear();
  toDeleteKeySlots.clear();
  newIndex = -1;
  keySlots.value = await getKeySlots();
}

onMounted(async () => {
  keySlots.value = await getKeySlots();
});
</script>

<template>
  <div v-if="keySlots">
    <div class="wg-conf-section">
      <template v-for="{ effectiveKeySlot, updated } in effectiveKeySlots"
                :key="effectiveKeySlot.id">
        <EditKeySlot
            :keySlot="effectiveKeySlot"
            :unsaved="updated || toDeleteKeySlots.has(effectiveKeySlot.id)"
            :toDelete="toDeleteKeySlots.has(effectiveKeySlot.id)"
            @change="(ks) => changeKeySlot(effectiveKeySlot.id, ks)"
            @save="() => saveKeySlot(effectiveKeySlot.id)"
            @discard="() => discardKeySlot(effectiveKeySlot.id)"
            @delete="() => removeKeySlot(effectiveKeySlot.id)"
        />
        <span class="error" v-if="keySlotErrors.has(effectiveKeySlot.id)">
          # {{ keySlotErrors.get(effectiveKeySlot.id) }}
        </span>
      </template>
      <template v-if="props.mayAdd">
        <br/>
        #
        <button @click="addKey">Add Key</button>
      </template>
    </div>
    <template v-if="props.mayAdd">
      <button @click="saveAll" :disabled="!hasChanges" class="wg-button-small">Save All
      </button>
    </template>
    <button @click="reload" :disabled="hasChanges" class="wg-button-small">Reload
    </button>
  </div>
  <div v-else>Loading...</div>
</template>

<style scoped></style>
