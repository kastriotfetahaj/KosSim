<script setup lang="ts">
const props = defineProps({
  commented: { type: Boolean, required: false, default: false },
  strikeThrough: { type: Boolean, required: false, default: false },
});
</script>

<template>
  <span
    :class="{
      commented: props.commented,
      'strike-through': props.strikeThrough,
    }"
    >{{ props.commented ? "# " : "" }}<slot
  /></span>
  <br />
</template>

<style scoped>
.commented {
  color: #999;
  font-style: italic;
}

.strike-through {
  text-decoration: line-through;
  color: #999;
}
</style>
