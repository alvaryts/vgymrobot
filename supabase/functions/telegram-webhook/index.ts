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
  "/credenciales <correo> <contraseña>\n" +
  "/reservar <dia> <hora> <clase>\n" +
  "Ejemplo: /reservar viernes 16:15 V-Metcon\n" +
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

async function createRequest(chatId: string, text: string) {
  const parts = text.trim().split(/\s+/);
  if (parts.length < 4) {
    throw new Error("Uso: /reservar <dia> <hora> <clase>");
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

  return data;
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

async function processTelegramUpdate(update: any): Promise<void> {
  let chatId: string | null = null;
  try {
    const message = update?.message;

    if (!message?.text || !message?.chat?.id) {
      return;
    }

    chatId = String(message.chat.id);
    const text = String(message.text).trim();
    const telegramUsername = message.from?.username ?? null;
    const displayName = message.from?.first_name
      ? `${message.from.first_name} ${message.from.last_name ?? ""}`.trim()
      : null;

    const normalizedText = text.replace(/^\/([a-z_]+)@\w+/i, "/$1");

    if (normalizedText.startsWith("/start")) {
      await sendTelegramMessage(chatId, HELP_TEXT);
      return;
    }

    if (normalizedText.startsWith("/credenciales")) {
      const [, email, password] = normalizedText.split(/\s+/);
      if (!email || !password) {
        await sendTelegramMessage(
          chatId,
          "Uso: /credenciales <correo> <contraseña>",
        );
        return;
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
      return;
    }

    if (normalizedText.startsWith("/reservar")) {
      const bookingRequest = await createRequest(chatId, normalizedText);
      await sendTelegramMessage(
        chatId,
        `✅ Solicitud creada: ${bookingRequest.id}\n🎯 ${bookingRequest.class_name} ${bookingRequest.day} ${bookingRequest.time}`,
      );

      try {
        await dispatchGitHubWorker(bookingRequest.id);
        await sendTelegramMessage(
          chatId,
          "🤖 Worker lanzado. Te avisaré cuando haya resultado.",
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown error";
        await sendTelegramMessage(
          chatId,
          `⚠️ La solicitud se creó, pero no se pudo lanzar el worker: ${message}`,
        );
      }

      return;
    }

    if (normalizedText.startsWith("/estado")) {
      const reply = await requestStatus(chatId);
      await sendTelegramMessage(chatId, reply);
      return;
    }

    if (normalizedText.startsWith("/cancelar")) {
      const reply = await cancelRequest(chatId, normalizedText);
      await sendTelegramMessage(chatId, reply);
      return;
    }

    await sendTelegramMessage(chatId, HELP_TEXT);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    if (chatId) {
      try {
        await sendTelegramMessage(chatId, `⚠️ Error: ${message}`);
      } catch (_) {
        // Si Telegram falla al responder, devolvemos igualmente el 500 original.
      }
    }
  }
}

Deno.serve(async (request) => {
  const update = await request.json();
  EdgeRuntime.waitUntil(processTelegramUpdate(update));
  return new Response("ok");
});
