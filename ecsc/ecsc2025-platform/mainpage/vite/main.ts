import Vue, { createApp } from "vue";
import WireguardConfig from "./WireguardConfig.vue";

const container = document.getElementById("wireguardConfig");
const wireguardConfigApp = createApp(WireguardConfig);
wireguardConfigApp.provide("hosting", container.dataset["hosting"]);
wireguardConfigApp.mount(container);
