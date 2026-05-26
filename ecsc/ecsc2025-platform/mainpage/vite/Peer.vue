<script setup lang="ts">
import { computed, ref } from "vue";
import { KeySlot, Peer } from "./api";
import ConfigLine from "./ConfigLine.vue";

const emit = defineEmits(["change", "removePeer"]);

const props = defineProps<{
  peer: Peer;
  currentKey: KeySlot | undefined;
  key_slots: KeySlot[];
  toDelete: boolean;
}>();

const parsedCidr = computed(() => {
  const [ip, mask] = props.peer.cidr.split("/");
  return [ip, mask];
});

const ipOctets = computed(() => {
  const [ip, _] = parsedCidr.value;
  return ip.split(".").map(Number);
});

const lastIpOctets = computed(() => {
  return ipOctets.value[3];
});

const cidrRange = computed(() => {
  const [_, mask] = parsedCidr.value;
  return Number(mask);
});

const keyOptions = computed<KeySlot[]>(() => {
  if (props.peer.managed) {
    return props.key_slots;
  } else {
    return props.key_slots.filter((ks: KeySlot) => !ks.managed);
  }
});

function change(key: string, value: any) {
  const copy = { ...props.peer };
  switch (key) {
    case "key_slot":
      copy[key] = value;
      break;
    case "ip":
      copy["cidr"] = `${ipOctets.value[0]}.${ipOctets.value[1]}.${ipOctets.value[2]}.${value}/${cidrRange.value}`;
      break;
    case "netmask":
      copy["cidr"] = `${ipOctets.value[0]}.${ipOctets.value[1]}.${ipOctets.value[2]}.${lastIpOctets.value}/${value}`;
      break;
    default:
      copy[key] = value;
  }
  emit("change", copy);
}

function removePeer() {
  emit("removePeer");
}
</script>

<template>
  <div class="wg-peer">
    <ConfigLine :commented="!peer.enabled" :strike-through="props.toDelete">
      [Peer]
      <button v-if="!peer.managed" type="button" @click="change('enabled', !peer.enabled)">
        {{ peer.enabled ? "Disable" : "Enable" }}
      </button>
      <button v-if="!peer.managed" type="button" @click="removePeer()">
        {{ props.toDelete ? "Restore" : "Remove" }}
      </button>
    </ConfigLine>

    <ConfigLine v-if="peer.comment" commented :strike-through="props.toDelete">
      {{ peer.comment }}
    </ConfigLine>
    <ConfigLine :commented="!peer.enabled" :strike-through="props.toDelete">
      #
      <select :value="peer.key_slot" :disabled="peer.managed" @change="change('key_slot', Number($event.target.value))">
        <option v-for="ks in keyOptions" :key="ks.id" :value="ks?.id">
          {{ ks.name }}
        </option>
      </select>
    </ConfigLine>
    <ConfigLine :commented="!peer.enabled" :strike-through="props.toDelete">
      PublicKey={{ currentKey?.public_key }}
    </ConfigLine>
    <ConfigLine :commented="!peer.enabled" :strike-through="props.toDelete">
      AllowedIPs=<template v-for="(octet, i) in ipOctets.slice(0, 3)" :key="i">
        <input :value="octet" type="number" :disabled="true" @change="change('ip', Number($event.target.value))" />.</template
      >
      <input
        type="number"
        min="1"
        max="254"
        :value="lastIpOctets"
        :disabled="peer.managed"
        @input="change('ip', Number($event.target.value))" />/<input
        type="number"
        min="25"
        max="32"
        :value="cidrRange"
        :disabled="peer.managed"
        @input="change('netmask', Number($event.target.value))" /></ConfigLine
    ><br />
  </div>
</template>

<style scoped>
.wg-peer {
  margin-bottom: 1em;
}

.wg-peer button {
  padding: 0em 1em;
  opacity: 0;
}

.wg-peer:hover button {
  transition: opacity 0.2s;
  opacity: 1;
}

input[type="number"],
select {
  background-color: #fff;
  color: #333;
  border: 1px solid #ced4da;
  padding: 0.375em 0.75em;
  margin: 0 0.2em;
  border-radius: 4px;
  font-size: 1rem;
  transition:
    border-color 0.15s ease-in-out,
    box-shadow 0.15s ease-in-out;
}

input[type="number"] {
  width: 3em;
  padding: 0;
  margin: 0;
  text-align: center;
}

input[type="checkbox"] {
  vertical-align: middle;
}

select {
  padding: 0.2em 0.5em;
}
input:focus,
select:focus {
  border-color: #80bdff;
  outline: none;
  box-shadow: 0 0 0 0.2rem rgba(0, 123, 255, 0.25);
}

input:disabled,
select:disabled {
  background-color: #e9ecef;
  color: #6c757d;
}

input[type="checkbox"]:disabled {
  background-color: #e9ecef;
}

input[type="checkbox"]:focus {
  box-shadow: none;
}
</style>
