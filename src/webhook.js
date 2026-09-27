"use strict";
// Obrada webhook događaja (poglavlje 3, tokovi 2-4, i 6.4).

const crypto = require("node:crypto");
const { WhatsAppError } = require("./whatsapp");
const { formatError } = require("./errors");
const { maskPhone } = require("./phone");
const { formatDate, formatTime, iso } = require("./timeutil");

// G-32: HMAC se računa nad SIROVIM tijelom zahtjeva, s App Secretom (ne verify tokenom).
function verifySignature(rawBody, header, appSecret) {
  if (!appSecret || !header) return false;
  const expected = "sha256=" + crypto.createHmac("sha256", appSecret).update(rawBody).digest("hex");
  const a = Buffer.from(header);
  const b = Buffer.from(expected);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// "Potvrđujem", "POTVRĐUJEM" i "potvrdujem" su isti gumb (đ se ne rastavlja kroz NFD).
function normalizeLabel(s) {
  return String(s || "")
    .replace(/[đĐ]/g, "d")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function classifyButton(text, payload, template) {
  const candidates = [text, payload].map(normalizeLabel);
  if (candidates.includes(normalizeLabel(template.confirmLabel))) return "confirmed";
  if (candidates.includes(normalizeLabel(template.changeLabel))) return "change_requested";
  return null;
}

function messageText(msg) {
  if (msg.type === "text") return msg.text?.body ?? "";
  if (msg.type === "button") return msg.button?.text ?? "";
  if (msg.type === "interactive") {
    return msg.interactive?.button_reply?.title ?? msg.interactive?.list_reply?.title ?? "";
  }
  return null;
}

const MEDIA_LABELS = {
  image: "sliku",
  audio: "glasovnu poruku",
  video: "video",
  document: "dokument",
  sticker: "naljepnicu",
  location: "lokaciju",
  contacts: "kontakt",
};

function appointmentLabel(reminder, timezone) {
  const start = new Date(reminder.starts_at);
  return `${formatDate(start, timezone)} u ${formatTime(start, timezone)} h`;
}

async function sendReply(ctx, phone, body) {
  if (!body) return;
  try {
    const wamid = await ctx.wa.sendText({ to: phone, body });
    ctx.store.insertOutbound({ wamid, phone, type: "text", createdAt: iso(ctx.now()) });
  } catch (err) {
    const why = err instanceof WhatsAppError ? formatError(err.code, err.httpStatus) : err.message;
    ctx.log.warn(`Odgovor pacijentu ${maskPhone(phone)} nije poslan: ${why}`);
  }
}

async function handleMessage(msg, ctx) {
  const { store, config, log } = ctx;
  const phone = msg.from;
  const createdAt = msg.timestamp ? iso(Number(msg.timestamp) * 1000) : iso(ctx.now());
  const now = iso(ctx.now());

  if (msg.type === "reaction" || msg.type === "system") {
    store.insertInbound({ wamid: msg.id, phone, type: msg.type, createdAt });
    return;
  }

  const text = messageText(msg);
  const messageId = store.insertInbound({ wamid: msg.id, phone, type: msg.type, body: text, createdAt });
  if (messageId === null) return; // već obrađeno (G-33)

  // Tok 2: gumb na podsjetniku.
  const isButton = msg.type === "button" || (msg.type === "interactive" && msg.interactive?.button_reply);
  if (isButton) {
    const payload = msg.button?.payload ?? msg.interactive?.button_reply?.id;
    const kind = classifyButton(text, payload, config.template);
    const reminder = msg.context?.id ? store.findReminderByWamid(msg.context.id) : null;
    if (!kind || !reminder) {
      // G-83: bez veze s terminom radije ništa ne mijenjamo – recepcija provjerava.
      store.addTask({
        kind: "patient_message",
        phone,
        messageId,
        details: "Odgovor gumbom koji se ne može povezati s terminom",
        createdAt: now,
      });
      log.warn(`Gumb "${text}" od ${maskPhone(phone)} nije povezan s terminom`);
      return;
    }
    store.setReminderReply({
      appointmentId: reminder.appointment_id,
      startsAt: reminder.starts_at,
      reply: kind,
      at: createdAt,
    });
    const when = appointmentLabel(reminder, config.timezone);
    if (kind === "confirmed") {
      log.info(`Termin #${reminder.appointment_id} potvrđen (${maskPhone(phone)})`);
      await sendReply(ctx, phone, config.replies.confirmed);
    } else {
      store.addTask({
        kind: "change_requested",
        appointmentId: reminder.appointment_id,
        phone,
        details: `${reminder.patient_name || "Pacijent"} traži promjenu termina ${when}`,
        createdAt: now,
      });
      log.info(`Termin #${reminder.appointment_id}: pacijent traži promjenu (${maskPhone(phone)})`);
      await sendReply(ctx, phone, config.replies.changeRequested);
    }
    return;
  }

  // Odjava ("STOP") – privola se opoziva odmah.
  if (msg.type === "text" && config.stopWords.includes(text.trim().toUpperCase())) {
    store.revokeConsent(phone, createdAt);
    store.addTask({
      kind: "opt_out",
      phone,
      messageId,
      details: "Pacijent se odjavio s WhatsApp obavijesti – termine potvrđivati telefonom",
      createdAt: now,
    });
    log.info(`Odjava s WhatsApp obavijesti: ${maskPhone(phone)}`);
    await sendReply(ctx, phone, config.replies.optOut);
    return;
  }

  // Tok 3: slobodna poruka -> inbox recepcije.
  const details =
    msg.type === "text" || msg.type === "interactive"
      ? null
      : `Pacijent je poslao ${MEDIA_LABELS[msg.type] || msg.type} – ne preuzima se; zamolite ga da napiše tekstom ili nazovite`;
  store.addTask({ kind: "patient_message", phone, messageId, details, createdAt: now });
  log.info(`Nova poruka pacijenta (${msg.type}) od ${maskPhone(phone)}`);
}

// Tok 4: statusi isporuke.
function handleStatus(st, ctx) {
  const { store, config, log } = ctx;
  const errorCode = st.errors?.[0]?.code ?? null;
  const at = st.timestamp ? iso(Number(st.timestamp) * 1000) : iso(ctx.now());
  const res = store.applyStatus({ wamid: st.id, status: st.status, errorCode, at });
  if (!res.changed || st.status !== "failed") return;

  const reason = formatError(errorCode, null);
  const reminder = store.findReminderByWamid(st.id);
  if (reminder) {
    store.setReminderStatus({
      appointmentId: reminder.appointment_id,
      startsAt: reminder.starts_at,
      status: "failed",
      errorCode,
      now: iso(ctx.now()),
    });
    store.addTask({
      kind: "delivery_failed",
      appointmentId: reminder.appointment_id,
      phone: reminder.patient_phone,
      details: `Podsjetnik za termin ${appointmentLabel(reminder, config.timezone)} nije isporučen – javite se telefonom ili SMS-om. ${reason}`,
      createdAt: iso(ctx.now()),
    });
  }
  log.warn(`Isporuka nije uspjela (${maskPhone(res.row.patient_phone)}): ${reason}`);
}

function handleTemplateStatus(v, ctx) {
  if (!v.event || v.event === "APPROVED") return;
  const details = `Predložak "${v.message_template_name}" (${v.message_template_language}): ${v.event}${
    v.reason && v.reason !== "NONE" ? ` – ${v.reason}` : ""
  }. Vidi G-60 i G-67 u uputama.`;
  ctx.store.addTask({ kind: "template", details, createdAt: iso(ctx.now()) });
  ctx.log.warn(details);
}

async function handlePayload(payload, ctx) {
  for (const entry of payload.entry || []) {
    for (const change of entry.changes || []) {
      const v = change.value || {};
      if (change.field === "message_template_status_update") {
        handleTemplateStatus(v, ctx);
        continue;
      }
      if (change.field !== "messages") continue;
      const ours = ctx.config.wa.phoneNumberId;
      if (ours && v.metadata?.phone_number_id && v.metadata.phone_number_id !== ours) continue;
      for (const msg of v.messages || []) await handleMessage(msg, ctx);
      for (const st of v.statuses || []) handleStatus(st, ctx);
    }
  }
}

// Obrađuje sve spremljene, a neobrađene događaje. Nikad ne radi dvaput
// istovremeno u istom procesu; događaj koji pukne bilježi se s greškom.
async function processPendingEvents(ctx) {
  if (ctx.busy) {
    ctx.again = true;
    return;
  }
  ctx.busy = true;
  try {
    do {
      ctx.again = false;
      let batch;
      while ((batch = ctx.store.pendingEvents()).length) {
        for (const ev of batch) {
          let error = null;
          try {
            await handlePayload(JSON.parse(ev.payload), ctx);
          } catch (err) {
            error = String((err && err.stack) || err);
            ctx.log.error(`Webhook događaj #${ev.id} nije obrađen: ${err.message}`);
          }
          ctx.store.markEventProcessed(ev.id, iso(ctx.now()), error);
        }
      }
    } while (ctx.again);
  } finally {
    ctx.busy = false;
  }
}

module.exports = { verifySignature, handlePayload, processPendingEvents, classifyButton };
