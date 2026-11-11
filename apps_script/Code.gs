/**
 * E.ON W1000 export -> Home Assistant híd (pull változat).
 *
 * A script a saját Gmail fiókodban fut. A Home Assistant integráció POST
 * kéréssel kérdezi le tőle az E.ON ütemezett export leveleinek csatolmányait.
 * A script semmit nem módosít a postafiókban, és csak a lenti QUERY-re
 * illeszkedő leveleket adja ki, kizárólag érvényes tokennel.
 *
 * Telepítés: lásd a README.md "Apps Script" fejezetét.
 */

// Gmail keresés, amire az export levelek illeszkednek. A tárgyat az
// ütemezett export beállításakor te adod meg a portálon; legyen egyedi.
const QUERY = 'subject:"eon-energy-metrics" has:attachment';

// Egy válaszban legfeljebb ennyi levél megy ki.
const MAX_LIMIT = 10;

/**
 * Egyszer futtasd le kézzel a szerkesztőből: engedélyt kér a Gmailhez,
 * létrehozza a titkos tokent, és kiírja a naplóba.
 */
function setup() {
  const props = PropertiesService.getScriptProperties();
  let token = props.getProperty('TOKEN');
  if (!token) {
    token = (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '');
    props.setProperty('TOKEN', token);
  }
  const found = GmailApp.search(QUERY, 0, 5).length;
  Logger.log('Token (ezt add meg a Home Assistantban): ' + token);
  Logger.log('A keresésre illeszkedő levélszálak (max 5): ' + found);
}

/** Új tokent generál; a régi azonnal érvénytelen lesz. */
function rotateToken() {
  PropertiesService.getScriptProperties().deleteProperty('TOKEN');
  setup();
}

function doPost(e) {
  let body = {};
  try {
    body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    return json_({ ok: false, error: 'bad_request' });
  }

  const token = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!token || typeof body.token !== 'string' || !safeEqual_(body.token, token)) {
    return json_({ ok: false, error: 'unauthorized' });
  }

  const after = Math.max(0, Number(body.after) || 0); // epoch ms
  const limit = Math.min(MAX_LIMIT, Math.max(1, Number(body.limit) || MAX_LIMIT));

  try {
    return json_({ ok: true, messages: collect_(after, limit) });
  } catch (err) {
    return json_({ ok: false, error: 'internal', detail: String(err) });
  }
}

function doGet() {
  return json_({ ok: false, error: 'use_post' });
}

/** Az `after` (ms) utáni levelek, időrendben, legfeljebb `limit` darab. */
function collect_(after, limit) {
  let query = QUERY;
  if (after > 0) {
    query += ' after:' + Math.floor(after / 1000);
  }

  const messages = [];
  const pageSize = 100;
  for (let start = 0; start < 1000; start += pageSize) {
    const threads = GmailApp.search(query, start, pageSize);
    threads.forEach(function (thread) {
      thread.getMessages().forEach(function (msg) {
        if (msg.getDate().getTime() > after) {
          messages.push(msg);
        }
      });
    });
    if (threads.length < pageSize) break;
  }

  messages.sort(function (a, b) {
    return a.getDate().getTime() - b.getDate().getTime();
  });

  return messages.slice(0, limit).map(function (msg) {
    return {
      id: msg.getId(),
      date: msg.getDate().getTime(),
      subject: msg.getSubject(),
      attachments: msg
        .getAttachments({ includeInlineImages: false, includeAttachments: true })
        .map(function (att) {
          return {
            name: att.getName(),
            contentType: att.getContentType(),
            data: Utilities.base64Encode(att.getBytes()),
          };
        }),
    };
  });
}

function safeEqual_(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
