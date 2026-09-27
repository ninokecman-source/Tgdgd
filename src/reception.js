"use strict";
// Inbox recepcije (tok 3, G-88): zadaci, poruke pacijenata, potvrde termina
// i privole. Zaštićeno lozinkom (RECEPTION_USER / RECEPTION_PASSWORD) i
// dostupno samo preko HTTPS-a (reverse proxy).

const crypto = require("node:crypto");
const express = require("express");
const { normalizePhone, maskPhone } = require("./phone");
const { formatDate, formatTime, iso, addHours } = require("./timeutil");
const { WhatsAppError } = require("./whatsapp");
const { formatError } = require("./errors");

const TASK_LABELS = {
  change_requested: "Traži promjenu termina – nazvati",
  delivery_failed: "Poruka nije isporučena – nazvati ili SMS",
  undelivered: "Podsjetnik još nije isporučen – nazvati",
  send_failed: "Podsjetnik nije poslan – nazvati",
  send_unknown: "Provjeriti je li podsjetnik stigao",
  patient_message: "Poruka pacijenta",
  opt_out: "Pacijent se odjavio (STOP)",
  template: "Obavijest Mete o predlošku",
};

const REPLY_LABELS = { confirmed: "✔ Potvrđeno", change_requested: "✎ Traži promjenu" };
const DELIVERY_LABELS = {
  accepted: "poslano",
  sent: "poslano",
  delivered: "isporučeno",
  read: "pročitano",
  failed: "NIJE isporučeno",
};
const REMINDER_LABELS = {
  pending: "čeka ponovni pokušaj",
  sending: "šalje se",
  failed: "NIJE poslano",
  skipped: "preskočeno (otkazan/pomaknut)",
  unknown: "nepoznato – provjeriti",
};

function reminderLabel(r) {
  if (r.delivery_status === "failed") return DELIVERY_LABELS.failed;
  if (r.status === "sent") return DELIVERY_LABELS[r.delivery_status] || "poslano";
  return REMINDER_LABELS[r.status] || r.status;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function sameSecret(a, b) {
  const ha = crypto.createHash("sha256").update(String(a)).digest();
  const hb = crypto.createHash("sha256").update(String(b)).digest();
  return crypto.timingSafeEqual(ha, hb);
}

function basicAuth(user, password) {
  return (req, res, next) => {
    const header = req.get("Authorization") || "";
    const [scheme, encoded] = header.split(" ");
    if (scheme === "Basic" && encoded) {
      const decoded = Buffer.from(encoded, "base64").toString("utf8");
      const i = decoded.indexOf(":");
      // Obje usporedbe se uvijek izvrše (bez prečaca), da vrijeme odgovora ne otkriva korisničko ime.
      const userOk = i > 0 && sameSecret(decoded.slice(0, i), user);
      const passOk = i > 0 && sameSecret(decoded.slice(i + 1), password);
      if (userOk && passOk) {
        return next();
      }
    }
    res.set("WWW-Authenticate", 'Basic realm="Recepcija", charset="UTF-8"');
    return res.status(401).send("Potrebna prijava");
  };
}

function withinServiceWindow(store, phone, now) {
  const last = store.lastInboundAt(phone);
  return Boolean(last) && new Date(last) > addHours(now, -24);
}

function when(isoString, tz) {
  const d = new Date(isoString);
  return `${formatDate(d, tz)} ${formatTime(d, tz)}`;
}

function page({ ctx, csrf, flash }) {
  const { store, config } = ctx;
  const tz = config.timezone;
  const now = ctx.now();
  const tasks = store.openTasks();
  const upcoming = store.remindersBetween(iso(addHours(now, -2)), iso(addHours(now, 48)));
  const consents = store.listConsents();
  const active = consents.filter((c) => !c.revoked_at).length;
  const hidden = `<input type="hidden" name="_csrf" value="${esc(csrf)}">`;

  const taskRows = tasks
    .map((t) => {
      const phone = t.patient_phone
        ? `<a href="tel:+${esc(t.patient_phone)}">+${esc(t.patient_phone)}</a>`
        : "";
      const body = t.message_body ? `<blockquote>${esc(t.message_body)}</blockquote>` : "";
      const reply =
        t.patient_phone && t.kind === "patient_message" && withinServiceWindow(store, t.patient_phone, now)
          ? `<form method="post" action="/recepcija/odgovor" class="reply">${hidden}
               <input type="hidden" name="task" value="${t.id}">
               <input type="hidden" name="phone" value="${esc(t.patient_phone)}">
               <textarea name="text" rows="2" required placeholder="Odgovor (bez zdravstvenih podataka)"></textarea>
               <button>Pošalji i riješi</button></form>`
          : "";
      return `<li class="task ${esc(t.kind)}">
        <div class="meta"><strong>${esc(TASK_LABELS[t.kind] || t.kind)}</strong> · ${esc(when(t.created_at, tz))} ${phone}</div>
        ${t.details ? `<div>${esc(t.details)}</div>` : ""}${body}${reply}
        <form method="post" action="/recepcija/zadatak/${t.id}/rijeseno">${hidden}<button class="done">Riješeno</button></form>
      </li>`;
    })
    .join("");

  const upcomingRows = upcoming
    .map(
      (r) => `<tr>
        <td>${esc(when(r.starts_at, tz))}</td>
        <td>${esc(r.patient_name || "")}</td>
        <td>${r.patient_phone ? `<a href="tel:+${esc(r.patient_phone)}">+${esc(r.patient_phone)}</a>` : ""}</td>
        <td>${esc(reminderLabel(r))}</td>
        <td>${esc(REPLY_LABELS[r.reply] || "—")}</td>
      </tr>`
    )
    .join("");

  const consentRows = consents
    .slice(0, 30)
    .map(
      (c) => `<tr class="${c.revoked_at ? "revoked" : ""}">
        <td>+${esc(c.phone)}</td><td>${esc(when(c.consent_given_at, tz))}</td>
        <td>${esc(c.consent_source)}</td><td>${c.revoked_at ? `opozvano ${esc(when(c.revoked_at, tz))}` : "aktivna"}</td>
      </tr>`
    )
    .join("");

  return `<!doctype html>
<html lang="hr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WhatsApp recepcija</title>
<style>
  :root { color-scheme: light dark; --line: #8884; --accent: #1a7f5a; }
  body { font: 15px/1.45 system-ui, sans-serif; margin: 0 auto; max-width: 960px; padding: 16px; }
  h1 { font-size: 1.3rem; } h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid var(--line); }
  ul { list-style: none; padding: 0; } .task { border: 1px solid var(--line); border-radius: 8px; padding: 10px; margin: 8px 0; }
  .task.change_requested, .task.delivery_failed, .task.undelivered, .task.send_failed { border-left: 4px solid #c0392b; }
  .task.patient_message { border-left: 4px solid var(--accent); }
  .task.opt_out, .task.send_unknown, .task.template { border-left: 4px solid #d68910; }
  .meta { font-size: .9rem; opacity: .85; } blockquote { margin: 6px 0; padding: 6px 10px; border-left: 3px solid var(--line); white-space: pre-wrap; }
  table { border-collapse: collapse; width: 100%; font-size: .92rem; } td, th { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--line); }
  .wrap { overflow-x: auto; } tr.revoked { opacity: .55; }
  form { margin: 6px 0 0; } textarea, input[type=text] { width: 100%; box-sizing: border-box; font: inherit; padding: 6px; }
  button { font: inherit; padding: 5px 12px; cursor: pointer; } .flash { padding: 8px 12px; border-radius: 6px; background: #1a7f5a22; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; } .row > * { flex: 1 1 180px; }
</style></head><body>
<h1>WhatsApp – recepcija</h1>
${flash ? `<p class="flash">${esc(flash)}</p>` : ""}
<p><a href="/recepcija">Osvježi</a></p>

<h2>Zadaci (${tasks.length})</h2>
${tasks.length ? `<ul>${taskRows}</ul>` : "<p>Nema otvorenih zadataka.</p>"}

<h2>Termini – sljedeća 2 dana</h2>
${upcoming.length ? `<div class="wrap"><table><tr><th>Termin</th><th>Pacijent</th><th>Telefon</th><th>Podsjetnik</th><th>Odgovor</th></tr>${upcomingRows}</table></div>` : "<p>Nema poslanih podsjetnika za sljedeća 2 dana.</p>"}

<h2>Privole (${active} aktivnih)</h2>
<form method="post" action="/recepcija/privola">${hidden}
  <div class="row">
    <input type="text" name="phone" required placeholder="Mobitel, npr. 098 123 4567">
    <input type="text" name="source" required placeholder="Izvor, npr. obrazac pri naručivanju">
    <input type="text" name="patient" placeholder="Cliniko ID pacijenta (nije obavezno)">
  </div>
  <button>Upiši privolu</button>
</form>
<form method="post" action="/recepcija/privola/opoziv">${hidden}
  <div class="row"><input type="text" name="phone" required placeholder="Mobitel za opoziv privole"></div>
  <button>Opozovi privolu</button>
</form>
${consents.length ? `<div class="wrap"><table><tr><th>Broj</th><th>Dana</th><th>Izvor</th><th>Stanje</th></tr>${consentRows}</table></div>` : ""}
</body></html>`;
}

function mountReception(app, ctx) {
  const { config, store, log } = ctx;
  const csrf = crypto.randomBytes(24).toString("hex");
  const router = express.Router();

  router.use(basicAuth(config.reception.user, config.reception.password));
  router.use((req, res, next) => {
    res.set({
      "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
      "Referrer-Policy": "no-referrer",
    });
    next();
  });
  router.use(express.urlencoded({ extended: false, limit: "20kb" }));
  router.use((req, res, next) => {
    if (req.method !== "POST") return next();
    if (!req.body || typeof req.body._csrf !== "string" || !sameSecret(req.body._csrf, csrf)) {
      return res.status(403).send("Neispravan obrazac – osvježi stranicu");
    }
    next();
  });

  const back = (res, msg) => res.redirect(303, `/recepcija?poruka=${encodeURIComponent(msg)}`);

  router.get("/", (req, res) => {
    const flash = typeof req.query.poruka === "string" ? req.query.poruka : "";
    res.type("html").send(page({ ctx, csrf, flash }));
  });

  router.post("/zadatak/:id/rijeseno", (req, res) => {
    store.completeTask(Number(req.params.id), iso(ctx.now()));
    back(res, "Zadatak riješen");
  });

  router.post("/odgovor", async (req, res) => {
    const phone = normalizePhone(req.body.phone);
    const text = String(req.body.text || "").trim();
    if (!phone || !text) return back(res, "Nedostaje broj ili tekst");
    // G-40: slobodan tekst samo unutar 24 h od zadnje poruke pacijenta.
    if (!withinServiceWindow(store, phone, ctx.now())) {
      return back(res, "Prošlo je više od 24 h od pacijentove poruke – nazovite pacijenta (G-40)");
    }
    try {
      const wamid = await ctx.wa.sendText({ to: phone, body: text });
      store.insertOutbound({ wamid, phone, type: "text", createdAt: iso(ctx.now()) });
      if (req.body.task) store.completeTask(Number(req.body.task), iso(ctx.now()));
      log.info(`Recepcija odgovorila pacijentu ${maskPhone(phone)}`);
      back(res, "Odgovor poslan");
    } catch (err) {
      const why = err instanceof WhatsAppError ? formatError(err.code, err.httpStatus) : err.message;
      log.warn(`Odgovor recepcije nije poslan (${maskPhone(phone)}): ${why}`);
      back(res, `Odgovor NIJE poslan: ${why}`);
    }
  });

  router.post("/privola", (req, res) => {
    const phone = normalizePhone(req.body.phone);
    const source = String(req.body.source || "").trim();
    if (!phone) return back(res, "Broj nije ispravan – upiši ga npr. kao 098 123 4567");
    if (!source) return back(res, "Upiši izvor privole (npr. obrazac pri naručivanju)");
    const patientId = String(req.body.patient || "").trim() || null;
    store.addConsent({ phone, patientId, source, givenAt: iso(ctx.now()) });
    log.info(`Privola upisana: ${maskPhone(phone)}`);
    back(res, `Privola upisana za +${phone}`);
  });

  router.post("/privola/opoziv", (req, res) => {
    const phone = normalizePhone(req.body.phone);
    if (!phone) return back(res, "Broj nije ispravan");
    const revoked = store.revokeConsent(phone, iso(ctx.now()));
    if (revoked) log.info(`Privola opozvana: ${maskPhone(phone)}`);
    back(res, revoked ? `Privola opozvana za +${phone}` : `Za +${phone} nema aktivne privole`);
  });

  app.use("/recepcija", router);
}

module.exports = { mountReception, esc };
