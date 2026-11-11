/**
 * E.ON W1000 export -> Home Assistant bridge (pull mode).
 *
 * Runs in your own Gmail account. The Home Assistant integration fetches the
 * attachments of the E.ON scheduled export e-mails from it with a POST
 * request. The script never modifies the mailbox, and it only returns
 * messages that match QUERY below, and only for a valid token.
 *
 * Setup: see the "Apps Script" section of README.md.
 */

// Gmail search matching the export e-mails. You choose the subject when
// setting up the scheduled export on the portal; keep it unique.
const QUERY = 'subject:"eon-energy-metrics" has:attachment';

// Maximum number of messages in one response.
const MAX_LIMIT = 10;

/**
 * Run once by hand from the editor: asks for Gmail access, creates the
 * secret token and writes it to the execution log.
 */
function setup() {
  const props = PropertiesService.getScriptProperties();
  let token = props.getProperty('TOKEN');
  if (!token) {
    token = (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '');
    props.setProperty('TOKEN', token);
  }
  const found = GmailApp.search(QUERY, 0, 5).length;
  Logger.log('Token (enter this in Home Assistant): ' + token);
  Logger.log('Threads matching the search (max 5): ' + found);
}

/** Creates a new token; the old one stops working immediately. */
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

/** Messages newer than `after` (ms), oldest first, at most `limit`. */
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
