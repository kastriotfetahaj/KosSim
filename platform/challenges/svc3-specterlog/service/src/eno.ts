import type { FastifyRequest } from "fastify";

export type EnoTask = {
  task_id?: number;
  method?: string;
  flag?: string;
  current_round_id?: number;
  related_round_id?: number;
  variant_id?: number;
  attack_info?: string;
};

export function authorized(req: FastifyRequest): boolean {
  const sent = req.headers["x-checker-secret"] ?? req.headers["x-service-secret"];
  const want = process.env.SERVICE_PUSH_SECRET ?? "rotate-secret";
  return typeof sent === "string" && sent.length > 0 && sent === want;
}

export type EnoResult = {
  result: "OK" | "MUMBLE" | "DOWN" | "CORRUPT" | "INTERNAL_ERROR";
  message?: string;
  attack_info?: string;
};
