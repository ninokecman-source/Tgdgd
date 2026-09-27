"use strict";
// Katalog grešaka iz uputa (poglavlje 6), s oznakama G-xx.
//
//   temporary: true  -> [P] privremena, ima smisla ponoviti
//   temporary: false -> [T] trajna, NE ponavljati isti zahtjev
//   scope: "global"    -> kvar postavki/računa, pogodio bi SVE poruke: posao
//                         se prekida, termini ostaju na čekanju, pacijent
//                         nije kriv
//   scope: "recipient" -> vezano uz tog pacijenta/poruku: ostali idu dalje
//   retryNow: true     -> vrijedi ponoviti odmah, s čekanjem 1 s, 2 s, 4 s, 8 s

const CATALOG = {};

function add(codes, entry) {
  for (const code of codes) CATALOG[code] = { code, ...entry };
}

// 6.2 Telefonski broj i registracija
add([133010], {
  ref: "G-11", scope: "global", temporary: false,
  title: "Broj nije registriran na Cloud API",
  fix: "Registriraj broj s PIN-om: npm run alat -- registriraj <PIN>",
});
add([133005], {
  ref: "G-13", scope: "global", temporary: false,
  title: "Pogrešan PIN za dvofaktorsku provjeru",
  fix: "Unesi ispravan PIN; ako je izgubljen, resetiraj 2FA u WhatsApp Manageru (e-mail ide adminu).",
});
add([133008], {
  ref: "G-14", scope: "global", temporary: true,
  title: "Previše pokušaja PIN-a",
  fix: "Čekaj navedeno vrijeme, ne pogađaj dalje.",
});
add([133015], {
  ref: "G-15", scope: "global", temporary: true,
  title: "Prerano za registraciju nakon brisanja",
  fix: "Pričekaj nekoliko minuta (do par sati) nakon brisanja iz aplikacije pa ponovi.",
});
add([133000], {
  ref: "G-16", scope: "global", temporary: true,
  title: "Nepotpuna deregistracija",
  fix: "Ponovi deregistraciju pa registraciju.",
});
add([133006], {
  ref: "G-17", scope: "global", temporary: false,
  title: "Broj treba ponovno verificirati",
  fix: "Ponovno verificiraj broj (SMS/poziv) pa registriraj.",
});

// 6.3 Token, dozvole, autentifikacija
add([190], {
  ref: "G-20", scope: "global", temporary: false,
  title: "Pristupni token je istekao ili nije valjan",
  fix: "Koristi trajni System User token (korak 4 uputa) i upiši ga u WA_TOKEN.",
});
add([10, 200], {
  ref: "G-21", scope: "global", temporary: false,
  title: "Dozvola odbijena",
  fix: "Business Settings -> System users -> Assign assets (aplikacija + WABA), pa generiraj token s whatsapp_business_messaging i whatsapp_business_management.",
});
add([100], {
  ref: "G-22", scope: "global", temporary: false,
  title: "Neispravan parametar (često krivi ID)",
  fix: "/messages i /register idu na WA_PHONE_NUMBER_ID; /subscribed_apps i /message_templates na WA_WABA_ID. Provjeri da nisu zamijenjeni.",
});
add([131005], {
  ref: "G-23", scope: "global", temporary: false,
  title: "Pristup odbijen",
  fix: "Provjeri dozvole tokena i da broj pripada tom WABA-u.",
});

// 6.5 Slanje poruka
add([131047], {
  ref: "G-40", scope: "recipient", temporary: false,
  title: "Prošlo je više od 24 h od zadnje poruke pacijenta",
  fix: "Izvan 24-satnog prozora šalje se samo odobreni predložak.",
});
add([131026], {
  ref: "G-41", scope: "recipient", temporary: false,
  title: "Poruku nije moguće isporučiti",
  fix: "Broj možda nema WhatsApp ili je krivo upisan. Provjeri broj u Clinikou i javi se pacijentu telefonom/SMS-om.",
});
add([131030], {
  ref: "G-42", scope: "recipient", temporary: false,
  title: "Primatelj nije na popisu dopuštenih (testni broj)",
  fix: "Dodaj primatelja u API Setup -> \"To\" ili koristi pravi (produkcijski) broj.",
});
add([131021], {
  ref: "G-43", scope: "recipient", temporary: false,
  title: "Primatelj je isti kao pošiljatelj",
  fix: "Ne šalji na broj same klinike – u Clinikou je kod pacijenta upisan broj klinike.",
});
add([131008, 131009], {
  ref: "G-44", scope: "recipient", temporary: false,
  title: "Parametar nedostaje ili nije ispravan",
  fix: "Provjeri broj i ime pacijenta u Clinikou (prazno ime, broj s neobičnim znakovima).",
});
add([131051], {
  ref: "G-45", scope: "global", temporary: false,
  title: "Nepodržana vrsta poruke",
  fix: "Koristi podržane tipove (text, template, interactive...).",
});
add([131052, 131053], {
  ref: "G-46", scope: "recipient", temporary: false,
  title: "Greška pri preuzimanju/slanju medija",
  fix: "Prvo uploadaj na /{PHONE_NUMBER_ID}/media i šalji media ID; poštuj limite veličine.",
});
add([131042], {
  ref: "G-47", scope: "global", temporary: false,
  title: "Problem s plaćanjem / podobnošću računa",
  fix: "Dodaj ili ažuriraj način plaćanja u WhatsApp Manageru -> Billing.",
});
add([131031], {
  ref: "G-48", scope: "global", temporary: false,
  title: "Poslovni račun je zaključan",
  fix: "WhatsApp Manager -> Account quality -> pokreni žalbu; pregledaj sadržaj poruka i privole.",
});
add([368], {
  ref: "G-49", scope: "global", temporary: false,
  title: "Privremeno blokirano zbog kršenja pravila",
  fix: "Kao G-48; smanji volumen, provjeri prijave korisnika.",
});
add([131000, 135000, 133004], {
  ref: "G-50", scope: "recipient", temporary: true, retryNow: true,
  title: "Generička / serverska greška",
  fix: "Ponavlja se automatski; ako traje, provjeri status stranicu Meta platforme.",
});

// 6.6 Predlošci
add([132001], {
  ref: "G-62", scope: "global", temporary: false,
  title: "Predložak ne postoji",
  fix: "Ime i jezik moraju biti točno kao pri kreiranju (\"hr\" nije \"hr_HR\"), predložak odobren i na istom WABA-u. Provjeri: npm run alat -- provjera",
});
add([132000], {
  ref: "G-63", scope: "global", temporary: false,
  title: "Broj parametara se ne podudara s predloškom",
  fix: "Predložak mora imati točno 3 varijable u tijelu: {{1}} ime, {{2}} datum, {{3}} sat.",
});
add([132012], {
  ref: "G-64", scope: "global", temporary: false,
  title: "Format parametra ne odgovara predlošku",
  fix: "Varijable predloška moraju biti tipa text.",
});
add([132005], {
  ref: "G-65", scope: "recipient", temporary: false,
  title: "Tekst s popunjenim varijablama je predugačak",
  fix: "Skrati vrijednosti varijabli (npr. predugo ime).",
});
add([132007], {
  ref: "G-66", scope: "recipient", temporary: false,
  title: "Nedopušteni znakovi u varijabli",
  fix: "Novi redovi, tabovi ili više od 4 razmaka u varijabli – provjeri ime pacijenta u Clinikou.",
});
add([132015, 132016], {
  ref: "G-67", scope: "global", temporary: false,
  title: "Predložak je pauziran ili onemogućen",
  fix: "Loša kvaliteta (pacijenti blokiraju/prijavljuju). Izmijeni tekst, kreiraj novi predložak, šalji samo onima s privolom.",
});

// 6.7 Limiti i kvaliteta
add([130429], {
  ref: "G-70", scope: "global", temporary: true, retryNow: true,
  title: "Prekoračena propusnost API-ja",
  fix: "Ponavlja se s čekanjem; ostatak ide u sljedećem prolasku.",
});
add([131056], {
  ref: "G-71", scope: "recipient", temporary: true, retryNow: true,
  title: "Previše poruka istom broju",
  fix: "Provjeri da neka petlja ne šalje isti podsjetnik više puta.",
});
add([80007], {
  ref: "G-72", scope: "global", temporary: true,
  title: "Dosegnut limit WhatsApp računa (WABA)",
  fix: "Rasporedi slanje kroz dan; ostatak ide u sljedećem prolasku.",
});
add([131048], {
  ref: "G-73", scope: "global", temporary: false,
  title: "Limit zbog prijava spama",
  fix: "Pacijenti blokiraju/prijavljuju poruke: provjeri privole, ton i učestalost; privremeno smanji volumen.",
});
add([131049, 131050], {
  ref: "G-74", scope: "recipient", temporary: false,
  title: "Meta nije isporučila / korisnik je odjavio poruke",
  fix: "Poštuj odluku; javi se pacijentu telefonom.",
});

function describe(code, httpStatus) {
  if (code !== null && code !== undefined && CATALOG[code]) return CATALOG[code];
  // Nepoznat kod: mrežna greška ili 5xx je vjerojatno privremena, ostalo trajno.
  const temporary = code === null || code === undefined || (httpStatus || 0) >= 500;
  return {
    code,
    ref: null,
    scope: "recipient",
    temporary,
    retryNow: temporary,
    title: temporary ? "Privremena greška (mreža ili Meta server)" : "Nepoznata greška",
    fix: temporary
      ? "Ponavlja se automatski."
      : "Potraži kod na https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes",
  };
}

function formatError(code, httpStatus) {
  const d = describe(code, httpStatus);
  const ref = d.ref ? `${d.ref} ` : "";
  const kod = code === null || code === undefined ? "bez koda" : code;
  return `${ref}(${kod}) ${d.title}. Ispravak: ${d.fix}`;
}

module.exports = { CATALOG, describe, formatError };
