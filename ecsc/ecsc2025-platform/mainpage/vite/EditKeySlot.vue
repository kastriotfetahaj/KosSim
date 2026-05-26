<script setup lang="ts">
import {computed} from "vue";
import ConfigLine from "./ConfigLine.vue";
import {KeySlot} from "./api";

const emit = defineEmits(["change", "discard", "save", "delete"]);

const props = defineProps<{
  keySlot: KeySlot;
  unsaved: boolean;
  toDelete: boolean;
}>();

const canDownload = computed(() => {
  return props.keySlot.public_key && props.keySlot.config_url;
});

function change(key: string, value: any) {
  const copy = {...props.keySlot};
  copy[key] = value;
  emit("change", copy);
}

function discard() {
  emit("discard");
}

function save() {
  emit("save");
}

function deleteKey() {
  emit("delete");
}

function download() {
  window.open(props.keySlot.config_url, "_blank");
}
</script>

<template>
  <div class="edit-keyslots">
    <ConfigLine commented v-if="unsaved"> Unsaved Changes</ConfigLine>
    <br v-else/>
    <ConfigLine :strike-through="props.toDelete">
      [Key]
      <button v-if="canDownload" @click="download()">Download Config</button>
      <button class="hoverOnly" v-if="unsaved" @click="save()">
        {{ toDelete ? "Confirm Delete" : "Save" }}
      </button>
      <button class="hoverOnly" v-if="unsaved" @click="discard()">Restore</button>
      <button class="hoverOnly" v-if="!toDelete && !props.keySlot.managed"
              @click="deleteKey()">Delete
      </button>
    </ConfigLine>
    <ConfigLine :strike-through="props.toDelete"> # Owner: {{
        keySlot.owner
      }}
    </ConfigLine>
    <ConfigLine :strike-through="props.toDelete">
      Name=<input
        type="text"
        size="71"
        :disabled="props.keySlot.managed"
        :value="keySlot.name"
        @input="change('name', $event.target.value)"
    />
    </ConfigLine>
    <ConfigLine :strike-through="props.toDelete">
      PublicKey=<input
        type="text"
        size="66"
        :disabled="props.keySlot.managed"
        :value="keySlot.public_key"
        @input="change('public_key', $event.target.value)"
    />
    </ConfigLine>
  </div>
</template>

<style scoped>
.edit-keyslots {
  margin-top: 1em;
  line-height: 1.5em;
}

.edit-keyslots:hover input[type="text"] {
  background-color: #f9f9f9;
}

.edit-keyslots button.hoverOnly {
  opacity: 0;
  transition: opacity 0.2s;
}

.edit-keyslots:hover button.hoverOnly {
  opacity: 1;
}

input[type="text"] {
  outline: none;
  border: none;
  height: 1.5em;
  box-sizing: border-box;
}

input[type="text"]:focus {
  background-color: #ddd !important;
}
</style>
