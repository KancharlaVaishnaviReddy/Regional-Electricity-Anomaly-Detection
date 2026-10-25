// Supabase Edge Function: Database Webhook + Streamlit manual alert -> Resend
//
// Automatic webhook request:
//   Header: x-webhook-secret: WEBHOOK_SECRET
//   Body: Supabase Database Webhook INSERT payload for public.anomalies
//
// Manual dashboard request:
//   Header: x-manual-alert-secret: MANUAL_ALERT_SECRET
//   Body: { "action": "manual_send", "anomaly_id": "<database row id>" }
//
// Keep Resend and Supabase privileged credentials in Edge Function secrets only.
// Configure this function with JWT verification disabled because this function
// authenticates the webhook/manual routes with their separate shared secrets.

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-webhook-secret, x-manual-alert-secret",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

type DenoRuntime = {
  env: {
    get(name: string): string | undefined;
  };
  serve(handler: (request: Request) => Response | Promise<Response>): void;
};

const deno = (globalThis as typeof globalThis & { Deno: DenoRuntime }).Deno;

type AnomalyRecord = {
  id?: number | string;
  region?: string;
  ts?: string;
  mw?: number;
  expected_mw?: number;
  z_score?: number;
  severity?: string;
  alerted?: boolean | string | null;
};

type WebhookPayload = {
  action?: string;
  anomaly_id?: number | string;
  type?: string;
  table?: string;
  schema?: string;
  record?: AnomalyRecord | null;
};

function jsonResponse(
  body: Record<string, unknown>,
  status = 200,
): Response {
  return Response.json(body, {
    status,
    headers: corsHeaders,
  });
}

function constantTimeEquals(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  if (a.length !== b.length) return false;

  let difference = 0;
  for (let i = 0; i < a.length; i++) {
    difference |= a[i] ^ b[i];
  }
  return difference === 0;
}

/**
 * Supabase currently provides newer secret keys through SUPABASE_SECRET_KEYS.
 * The legacy service-role key remains a fallback for older projects.
 */
function getAdminApiKey(): string | null {
  const secretKeysJson = deno.env.get("SUPABASE_SECRET_KEYS");

  if (secretKeysJson) {
    try {
      const secretKeys = JSON.parse(secretKeysJson);
      const defaultSecret = secretKeys?.default;
      if (typeof defaultSecret === "string" && defaultSecret.length > 0) {
        return defaultSecret;
      }
    } catch (error) {
      console.error("Could not parse SUPABASE_SECRET_KEYS:", error);
    }
  }

  return deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? null;
}

function getSupabaseConfig(): { url: string; apiKey: string } | null {
  const url = deno.env.get("SUPABASE_URL");
  const apiKey = getAdminApiKey();
  if (!url || !apiKey) return null;
  return { url: url.replace(/\/$/, ""), apiKey };
}

function isValidRecordId(value: unknown): value is number | string {
  if (typeof value !== "number" && typeof value !== "string") return false;
  const id = String(value);
  // Supports integer IDs and UUID IDs; disallows PostgREST filter syntax.
  return /^\d+$/.test(id) ||
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
      .test(id);
}

function normalizeRecord(record: AnomalyRecord): {
  id?: number | string;
  region: string;
  timestamp: string;
  mw: number;
  expectedMw: number;
  zScore: number;
  severity: string;
} | null {
  const region = typeof record.region === "string" ? record.region.trim() : "";
  const timestamp = typeof record.ts === "string" ? record.ts : "";
  const mw = Number(record.mw);
  const expectedMw = Number(record.expected_mw);
  const zScore = Number(record.z_score);
  const severity = typeof record.severity === "string"
    ? record.severity.trim().toUpperCase()
    : "";

  if (
    !region || !timestamp || !Number.isFinite(Date.parse(timestamp)) ||
    !Number.isFinite(mw) || !Number.isFinite(expectedMw) ||
    !Number.isFinite(zScore) || severity !== "CRITICAL"
  ) {
    return null;
  }

  return {
    id: record.id,
    region,
    timestamp,
    mw,
    expectedMw,
    zScore,
    severity,
  };
}

async function sendResendEmail(record: AnomalyRecord): Promise<{
  ok: boolean;
  status?: number;
}> {
  const normalized = normalizeRecord(record);
  if (!normalized) {
    return { ok: false, status: 400 };
  }

  const resendApiKey = deno.env.get("RESEND_API_KEY");
  const fromEmail = deno.env.get("ALERT_FROM_EMAIL");
  const toEmail = deno.env.get("ALERT_TO_EMAIL");

  if (!resendApiKey || !fromEmail || !toEmail) {
    console.error(
      "Missing one or more required secrets: RESEND_API_KEY, ALERT_FROM_EMAIL, ALERT_TO_EMAIL",
    );
    return { ok: false, status: 500 };
  }

  const subject = `CRITICAL electricity anomaly: ${normalized.region}`;
  const text = [
    "A CRITICAL electricity consumption anomaly was detected.",
    "",
    `Region: ${normalized.region}`,
    `Timestamp: ${normalized.timestamp}`,
    `Observed MW: ${normalized.mw}`,
    `Expected MW: ${normalized.expectedMw}`,
    `Z-score: ${normalized.zScore}`,
    `Anomaly row ID: ${record.id ?? "not provided"}`,
  ].join("\n");

  try {
    const resendResponse = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${resendApiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: fromEmail,
        to: [toEmail],
        subject,
        text,
      }),
    });

    if (!resendResponse.ok) {
      const responseBody = await resendResponse.text();
      console.error(
        `Resend returned HTTP ${resendResponse.status}: ${responseBody}`,
      );
      return { ok: false, status: resendResponse.status };
    }

    return { ok: true, status: resendResponse.status };
  } catch (error) {
    console.error("Could not contact Resend:", error);
    return { ok: false, status: 502 };
  }
}

async function markRecordAlerted(id: number | string): Promise<boolean> {
  const config = getSupabaseConfig();
  if (!config) {
    console.error(
      "Email accepted, but Supabase server-side URL/key is unavailable for updating alerted.",
    );
    return false;
  }

  const updateUrl = new URL(`${config.url}/rest/v1/anomalies`);
  updateUrl.searchParams.set("id", `eq.${id}`);

  try {
    const response = await fetch(updateUrl, {
      method: "PATCH",
      headers: {
        apikey: config.apiKey,
        Authorization: `Bearer ${config.apiKey}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify({ alerted: true }),
    });

    if (!response.ok) {
      console.error(
        `Email accepted, but updating alerted failed: ${response.status} ${await response.text()}`,
      );
      return false;
    }

    const updatedRows = await response.json().catch(() => []);
    if (!Array.isArray(updatedRows) || updatedRows.length === 0) {
      console.error("Email accepted, but no anomaly row was updated.");
      return false;
    }

    return true;
  } catch (error) {
    console.error("Email accepted, but updating alerted failed:", error);
    return false;
  }
}

async function fetchAnomalyById(id: number | string): Promise<
  { record: AnomalyRecord | null; error?: string }
> {
  const config = getSupabaseConfig();
  if (!config) {
    return { record: null, error: "Supabase server-side configuration is missing" };
  }

  const queryUrl = new URL(`${config.url}/rest/v1/anomalies`);
  queryUrl.searchParams.set(
    "select",
    "id,region,ts,mw,expected_mw,z_score,severity,alerted",
  );
  queryUrl.searchParams.set("id", `eq.${id}`);
  queryUrl.searchParams.set("limit", "1");

  try {
    const response = await fetch(queryUrl, {
      method: "GET",
      headers: {
        apikey: config.apiKey,
        Authorization: `Bearer ${config.apiKey}`,
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      console.error(
        `Could not read anomaly from Supabase: ${response.status} ${await response.text()}`,
      );
      return { record: null, error: "Could not read the anomaly record" };
    }

    const rows = await response.json();
    if (!Array.isArray(rows) || rows.length === 0) {
      return { record: null };
    }

    return { record: rows[0] as AnomalyRecord };
  } catch (error) {
    console.error("Could not read anomaly from Supabase:", error);
    return { record: null, error: "Could not read the anomaly record" };
  }
}

async function handleManualSend(payload: WebhookPayload, req: Request): Promise<Response> {
  const expectedSecret = deno.env.get("MANUAL_ALERT_SECRET");
  const suppliedSecret = req.headers.get("x-manual-alert-secret");

  if (!expectedSecret) {
    console.error("MANUAL_ALERT_SECRET is not configured.");
    return jsonResponse({ success: false, error: "Manual alert is not configured" }, 500);
  }

  if (!suppliedSecret || !constantTimeEquals(suppliedSecret, expectedSecret)) {
    return jsonResponse({ success: false, error: "Unauthorized manual alert request" }, 401);
  }

  if (!isValidRecordId(payload.anomaly_id)) {
    return jsonResponse({ success: false, error: "A valid anomaly_id is required" }, 400);
  }

  const lookup = await fetchAnomalyById(payload.anomaly_id);
  if (lookup.error) {
    return jsonResponse({ success: false, error: lookup.error }, 500);
  }
  if (!lookup.record) {
    return jsonResponse({ success: false, error: "Anomaly record was not found" }, 404);
  }

  const record = lookup.record;
  const normalized = normalizeRecord(record);
  if (!normalized) {
    return jsonResponse({
      success: false,
      error: "Only valid CRITICAL anomaly records can be emailed",
    }, 400);
  }

  const alreadyAlerted = record.alerted === true ||
    String(record.alerted).toLowerCase() === "true";
  if (alreadyAlerted) {
    return jsonResponse({
      success: false,
      alreadyAlerted: true,
      error: "This anomaly is already marked as alerted; refusing a duplicate send",
    }, 409);
  }

  const sendResult = await sendResendEmail(record);
  if (!sendResult.ok) {
    const status = sendResult.status === 400 ? 400 : 502;
    return jsonResponse({ success: false, error: "Resend did not accept the email" }, status);
  }

  const alertedUpdated = record.id === undefined
    ? false
    : await markRecordAlerted(record.id);

  console.log(`Manual critical email accepted for anomaly ${record.id}.`);
  return jsonResponse({
    success: true,
    emailed: true,
    alertedUpdated,
    message: alertedUpdated
      ? "Email accepted by Resend and anomaly marked as alerted"
      : "Email accepted by Resend, but the anomaly alert flag was not updated",
  });
}

deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return jsonResponse({ error: "POST required" }, 405);
  }

  let payload: WebhookPayload;
  try {
    payload = await req.json();
  } catch {
    return jsonResponse({ error: "Request body must be valid JSON" }, 400);
  }

  // The manual dashboard route uses its own secret and loads the row by ID.
  if (payload.action === "manual_send") {
    return await handleManualSend(payload, req);
  }

  // All other requests are treated as Database Webhook events.
  const expectedSecret = deno.env.get("WEBHOOK_SECRET");
  const suppliedSecret = req.headers.get("x-webhook-secret");

  if (!expectedSecret) {
    console.error("WEBHOOK_SECRET is not configured.");
    return jsonResponse({ error: "Webhook secret is not configured" }, 500);
  }

  if (!suppliedSecret || !constantTimeEquals(suppliedSecret, expectedSecret)) {
    return jsonResponse({ error: "Unauthorized webhook" }, 401);
  }

  if (payload.schema && payload.schema !== "public") {
    return jsonResponse({ ok: true, skipped: true, reason: "Not the public schema" });
  }
  if (payload.table && payload.table !== "anomalies") {
    return jsonResponse({ ok: true, skipped: true, reason: "Not the anomalies table" });
  }
  if (payload.type && payload.type !== "INSERT") {
    return jsonResponse({ ok: true, skipped: true, reason: "Not an INSERT event" });
  }

  const record = payload.record;
  if (!record) {
    return jsonResponse({ error: "Webhook payload has no record" }, 400);
  }

  if ((record.severity ?? "").toUpperCase() !== "CRITICAL") {
    return jsonResponse({
      ok: true,
      skipped: true,
      reason: "Anomaly severity is not CRITICAL",
    });
  }

  if (!normalizeRecord(record)) {
    return jsonResponse({ error: "Critical anomaly record has invalid required fields" }, 400);
  }

  const sendResult = await sendResendEmail(record);
  if (!sendResult.ok) {
    return jsonResponse({ error: "Resend did not accept the email" }, 502);
  }

  const alertedUpdated = record.id === undefined
    ? false
    : await markRecordAlerted(record.id);

  console.log(`Webhook critical email accepted for region ${record.region}.`);
  return jsonResponse({
    ok: true,
    emailed: true,
    alertedUpdated,
  });
});
