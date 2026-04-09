import { createClient } from "npm:@supabase/supabase-js@2";

import { encryptText } from "../_shared/crypto.ts";
import { dispatchGitHubWorker } from "../_shared/github.ts";
import { sendTelegramMessage } from "../_shared/telegram.ts";

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const credentialsSecret = Deno.env.get("CREDENTIALS_SECRET") ?? "";

const supabase = createClient(supabaseUrl, serviceRoleKey);

const HELP_TEXT =
  "Comandos:\n" +
  "/credenciales correo contraseña\n" +
  "/reservar miercoles 17:00 V-Power\n" +
  "/estado\n" +
  "/cancelar <request_id>";

const DAY_MAP: Record<string, number> = {
  lunes: 0,
  martes: 1,
  miercoles: 2,
  miércoles: 2,
  jueves: 3,
  viernes: 4,
  sabado: 5,
  sábado: 5,
  domingo: 6,
};

function madridParts(now = new Date()) {
  const formatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Madrid",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  });

  const parts = Object.fromEntries(
    formatter
      .formatToParts(now)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );

  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    weekday: String(parts.weekday),
  };
}

function nextTargetDate(dayLabel: string): string {
  const today = madridParts();
  const weekdayMap: Record<string, number> = {
    Mon: 0,
    Tue: 1,
    Wed: 2,
    Thu: 3,
    Fri: 4,
    Sat: 5,
    Sun: 6,
  };
  const currentWeekday = weekdayMap[today.weekday];
  const targetWeekday = DAY_MAP[dayLabel.toLowerCase()];

  if (targetWeekday === undefined) {
    throw new Error(`Día no soportado: ${dayLabel}`);
  }

  const base = new Date(Date.UTC(today.year, today.month - 1, today.day));
  const delta = (targetWeekday - currentWeekday + 7) % 7;
  base.setUTCDate(base.getUTCDate() + delta);
  return base.toISOString().slice(0, 10);
}

function watchUntilIso(hours = 2): string {
  return new Date(Date.now() + hours * 60 * 60 * 1000).toISOString();
}

async function upsertAccount(
  chatId: string,
  email: string,
  password: string,
  displayName: string | null,
  telegramUsername: string | null,
) {
  const encryptedUsername = await encryptText(credentialsSecret, email);
  const encryptedPassword = await encryptText(credentialsSecret, password);

  const { error } = await supabase.from("member_accounts").upsert(
    {
      telegram_chat_id: chatId,
      telegram_username: telegramUsername,
      display_name: displayName,
      gym_username_ciphertext: encryptedUsername,
      gym_password_ciphertext: encryptedPassword,
    },
    { onConflict: "telegram_chat_id" },
  );

  if (error) {
    throw new Error(`No se pudieron guardar las credenciales: ${error.message}`);
  }
}

async function accountForChat(chatId: string) {
  const { data, error } = await supabase
    .from("member_accounts")
    .select("id, club")
    .eq("telegram_chat_id", chatId)
    .single();

  if (error || !data) {
    throw new Error("Primero envía /credenciales correo contraseña");
  }

  return data;
}

async function createRequest(chatId: string, text: string): Promise<string> {
  const parts = text.trim().split(/\s+/);
  if (parts.length < 4) {
    throw new Error("Uso: /reservar miercoles 17:00 V-Power");
  }

  const [, day, time, ...classParts] = parts;
  const className = classParts.join(" ");
  const account = await accountForChat(chatId);

  const { data, error } = await supabase
    .from("booking_requests")
    .insert({
      account_id: account.id,
      club: account.club ?? "Bolueta",
      day,
      time,
      class_name: className,
      target_date: nextTargetDate(day),
      interval_seconds: 120,
      watch_until: watchUntilIso(2),
      status: "pending",
    })
    .select("id, class_name, day, time")
    .single();

  if (error || !data) {
    throw new Error(`No se pudo crear la solicitud: ${error?.message ?? "unknown"}`);
  }

  await dispatchGitHubWorker(data.id);
  return `✅ Solicitud creada: ${data.id}\n🎯 ${data.class_name} ${data.day} ${data.time}`;
}

async function requestStatus(chatId: string): Promise<string> {
  const account = await accountForChat(chatId);
  const { data, error } = await supabase
    .from("booking_requests")
    .select("id, class_name, day, time, status, attempts, last_result")
    .eq("account_id", account.id)
    .order("created_at", { ascending: false })
    .limit(5);

  if (error) {
    throw new Error(`No se pudo leer el estado: ${error.message}`);
  }

  if (!data || data.length === 0) {
    return "No tienes solicitudes recientes.";
  }

  return data
    .map((row) => {
      return [
        `${row.id}`,
        `${row.class_name} ${row.day} ${row.time}`,
        `estado=${row.status} intentos=${row.attempts}`,
        row.last_result ? `último=${row.last_result}` : null,
      ]
        .filter(Boolean)
        .join("\n");
    })
    .join("\n\n");
}

async function cancelRequest(chatId: string, text: string): Promise<string> {
  const [, requestId] = text.trim().split(/\s+/);
  if (!requestId) {
    throw new Error("Uso: /cancelar <request_id>");
  }

  const account = await accountForChat(chatId);
  const { data, error } = await supabase
    .from("booking_requests")
    .update({
      status: "cancelled",
      last_result: "Cancelada por el usuario desde Telegram",
    })
    .eq("account_id", account.id)
    .eq("id", requestId)
    .select("id")
    .single();

  if (error || !data) {
    throw new Error("No se pudo cancelar esa solicitud");
  }

  return `🛑 Solicitud cancelada: ${data.id}`;
}

Deno.serve(async (request) => {
  try {
    const update = await request.json();
    const message = update?.message;

    if (!message?.text || !message?.chat?.id) {
      return new Response("ok");
    }

    const chatId = String(message.chat.id);
    const text = String(message.text).trim();
    const telegramUsername = message.from?.username ?? null;
    const displayName = message.from?.first_name
      ? `${message.from.first_name} ${message.from.last_name ?? ""}`.trim()
      : null;

    if (text.startsWith("/start")) {
      await sendTelegramMessage(chatId, HELP_TEXT);
      return new Response("ok");
    }

    if (text.startsWith("/credenciales")) {
      const [, email, password] = text.split(/\s+/);
      if (!email || !password) {
        await sendTelegramMessage(chatId, "Uso: /credenciales correo contraseña");
        return new Response("ok");
      }

      await upsertAccount(
        chatId,
        email,
        password,
        displayName,
        telegramUsername,
      );
      await sendTelegramMessage(
        chatId,
        "🔐 Credenciales guardadas. Ya puedes usar /reservar miercoles 17:00 V-Power",
      );
      return new Response("ok");
    }

    if (text.startsWith("/reservar")) {
      const reply = await createRequest(chatId, text);
      await sendTelegramMessage(chatId, reply);
      return new Response("ok");
    }

    if (text.startsWith("/estado")) {
      const reply = await requestStatus(chatId);
      await sendTelegramMessage(chatId, reply);
      return new Response("ok");
    }

    if (text.startsWith("/cancelar")) {
      const reply = await cancelRequest(chatId, text);
      await sendTelegramMessage(chatId, reply);
      return new Response("ok");
    }

    await sendTelegramMessage(chatId, HELP_TEXT);
    return new Response("ok");
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return new Response(message, { status: 500 });
  }
});
