import axios from "axios";

axios.defaults.xsrfHeaderName = "X-CSRFTOKEN";
axios.defaults.xsrfCookieName = "csrftoken";

export interface CreateKeySlot {
  name: string;
  public_key: string | null;
}
export interface KeySlot extends CreateKeySlot {
  id: number;
  owner: string | null;
  managed: boolean;
  config_url: string | null;
}

export interface Peer {
  key_slot: number;
  cidr: string;
  managed: boolean;
  enabled: boolean;
  order: number;
  comment: string | null;
}

export interface InterfaceConfig {
  id: number;
  peers: Peer[];
  cidr: string;
  managed: boolean;
  public_key: string | null;
  auto_ip_assignment: boolean;
  last_modified: string | null;
  last_synced: string | null;
  vpn_host: string;
  vpn_port: number;
}

const client = axios.create({
  baseURL: "/api/player/",
  xsrfHeaderName: "X-CSRFTOKEN",
  xsrfCookieName: "csrftoken",
});

function handleAxiosError(err: any) {
  if (err.response) {
    throw err;
  } else if (err.request) {
    throw new Error("No response from server");
  } else {
    throw new Error("Request failed");
  }
}

export async function getKeySlots() {
  try {
    const resp = await client.get<KeySlot[]>("/key_slots");
    return resp.data;
  } catch (err) {
    handleAxiosError(err);
  }
}

export async function putKeySlot(keySlot: KeySlot) {
  try {
    const resp = await client.put(`/key_slots/${keySlot.id}`, keySlot);
    return resp.data;
  } catch (err) {
    handleAxiosError(err);
  }
}

export async function postKeySlot(keySlot: CreateKeySlot) {
  try {
    const resp = await client.post("/key_slots", keySlot);
    return resp.data;
  } catch (err) {
    handleAxiosError(err);
  }
}

export async function deleteKeySlot(id: number) {
  try {
    const resp = await client.delete(`/key_slots/${id}`);
    return resp.data;
  } catch (err) {
    handleAxiosError(err);
  }
}

export async function getInterface(): Promise<InterfaceConfig | null> {
  try {
    const resp = await client.get<InterfaceConfig>("/interface");
    return resp.data;
  } catch (err) {
    handleAxiosError(err);
  }
  return null;
}

export async function putInterface(config: InterfaceConfig) {
  const payload = {
    ...config,
    peers: config.peers.filter((p) => p.managed !== true),
  };
  const resp = await client.put("/interface", payload);
  return resp.data;
}

export function getHumanReadableError(error: any): string {
  if (error.response) {
    const status = error.response.status;
    const data = JSON.stringify(error.response.data, null, 2);
    return `Error: ${status}\n${data}`;
  } else if (error.request) {
    return "No response from server";
  } else {
    return "Request failed";
  }
}
