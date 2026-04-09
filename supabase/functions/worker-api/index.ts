import { createClient } from "npm:@supabase/supabase-js@2";

import { decryptText } from "../_shared/crypto.ts";
import { sendTelegramMessage } from "../_shared/telegram.ts";

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const credentialsSecret = Deno.env.get("CREDENTIALS_SECRET") ?? "";
const workerSecret = Deno.env.get("WORKER_SHARED_SECRET") ?? "";

const supabase = createClient(supabaseUrl, serviceRoleKey);

function jsonResponse(status: number, payload: Record<string, unknown>) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function assertWorkerSecret(request: Request): void {
  const received = request.headers.get("x-worker-secret") ?? "";
  if (!workerSecret || received != workerSecret) {
    throw new Error("Unauthorized");
  }
}

async function fetchRequest(requestId: string) {
  const { data, error } = await supabase
    .from("booking_requests")
    .select(`
      id,
      club,
      day,
      time,
      class_name,
      target_date,
      interval_seconds,
      watch_until,
      attempts,
      status,
      member_accounts!booking_requests_account_id_fkey (
        telegram_chat_id,
        gym_username_ciphertext,
        gym_password_ciphertext
      )
    `)
    .eq("id", requestId)
    .single();

  if (error || !data) {
    throw new Error(`Solicitud no encontrada: ${requestId}`);
  }

  const member = Array.isArray(data.member_accounts)
    ? data.member_accounts[0]
    : data.member_accounts;

  if (!member) {
    throw new Error("La solicitud no tiene cuenta asociada");
  }

  return {
    id: data.id,
    club: data.club,
    day: data.day,
    time: data.time,
    class_name: data.class_name,
    target_date: data.target_date,
    interval_seconds: data.interval_seconds,
    watch_until: data.watch_until,
    attempts: data.attempts,
    status: data.status,
    member: {
      telegram_chat_id: member.telegram_chat_id,
      gym_username: await decryptText(credentialsSecret, member.gym_username_ciphertext),
      gym_password: await decryptText(credentialsSecret, member.gym_password_ciphertext),
    },
  };
}

async function updateRequest(payload: Record<string, unknown>) {
  const requestId = String(payload.request_id ?? "");
  const patch: Record<string, unknown> = {};

  for (const key of ["status", "attempts", "last_result", "last_checked_at", "booked_at"]) {
    if (key in payload) {
      patch[key] = payload[key];
    }
  }

  const { data, error } = await supabase
    .from("booking_requests")
    .update(patch)
    .eq("id", requestId)
    .select(`
      id,
      status,
      class_name,
      day,
      time,
      last_result,
      member_accounts!booking_requests_account_id_fkey (
        telegram_chat_id
      )
    `)
    .single();

  if (error || !data) {
    throw new Error(`No se pudo actualizar ${requestId}`);
  }

  const member = Array.isArray(data.member_accounts)
    ? data.member_accounts[0]
    : data.member_accounts;

  if (member?.telegram_chat_id && (data.status === "booked" || data.status === "expired")) {
    const message = data.status === "booked"
      ? `🎉 Reserva confirmada: ${data.class_name} ${data.day} ${data.time}`
      : `⌛ Solicitud expirada: ${data.class_name} ${data.day} ${data.time}`;

    await sendTelegramMessage(member.telegram_chat_id, message);
  }

  return data;
}

Deno.serve(async (request) => {
  try {
    assertWorkerSecret(request);
    const payload = await request.json();
    const action = String(payload.action ?? "");

    if (action === "fetch") {
      const data = await fetchRequest(String(payload.request_id ?? ""));
      return jsonResponse(200, { request: data });
    }

    if (action === "update") {
      const data = await updateRequest(payload);
      return jsonResponse(200, { request: data });
    }

    return jsonResponse(400, { error: "Acción no soportada" });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    const status = message === "Unauthorized" ? 401 : 500;
    return jsonResponse(status, { error: message });
  }
});
