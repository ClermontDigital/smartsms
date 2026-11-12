/* SmartSMS messages card - read and send SMS through SmartSMS (Mobile Message).
 * Buildless: plain JS custom element, served by the smartsms integration.
 * Admins only: the message history comes from the admin-only smartsms/* WebSocket API.
 */
const SMS_VERSION = "1.1.0";
const MAX_LEN = 765; // smartsms.send_sms refuses longer messages

// GSM 03.38: the basic set costs one unit, the extension set two; anything else (emoji, curly
// quotes...) sends the whole message as UCS-2, 70 characters a part instead of 160.
const GSM = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
const GSM_EXT = "^{}\\[~]|€\f";
const READ_KEY = "smartsms-card-read";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const linkify = (html) => html.replace(/\bhttps?:\/\/[^\s<]+?(?=[.,!?)]*(?:\s|$))/g, (u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
const ts = (m) => Date.parse(m.timestamp) || 0;
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** The same key the integration files messages under: 61xxxxxxxxx for Australian numbers. */
function normalise(number) {
  const n = String(number ?? "").trim();
  if (!/^\+?[0-9 ()-]+$/.test(n)) return n.toLowerCase();
  let d = n.replace(/\D/g, "");
  if (d.startsWith("00")) d = d.slice(2);
  else if (d.length === 10 && d.startsWith("0")) d = "61" + d.slice(1);
  return d;
}

const canReply = (thread) => /^\d{6,}$/.test(thread);

function displayNumber(thread, raw) {
  if (/^614\d{8}$/.test(thread)) { const l = "0" + thread.slice(2); return `${l.slice(0, 4)} ${l.slice(4, 7)} ${l.slice(7)}`; }
  if (/^61[2378]\d{8}$/.test(thread)) { const l = "0" + thread.slice(2); return `${l.slice(0, 2)} ${l.slice(2, 6)} ${l.slice(6)}`; }
  if (/^\d+$/.test(thread)) return `+${thread}`;
  return raw || thread; // a sender name such as a bank's
}

function smsParts(text) {
  let units = 0;
  for (const ch of text) {
    if (GSM.includes(ch)) units += 1;
    else if (GSM_EXT.includes(ch)) units += 2;
    else {
      const n = text.length; // UCS-2 counts UTF-16 units, so an emoji is two
      const parts = n <= 70 ? 1 : Math.ceil(n / 67);
      return { parts, left: (parts === 1 ? 70 : parts * 67) - n, unicode: true };
    }
  }
  const parts = units <= 160 ? 1 : Math.ceil(units / 153);
  return { parts, left: (parts === 1 ? 160 : parts * 153) - units, unicode: false };
}

class SmartSMSMessagesCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
  }

  static getStubConfig() { return {}; }
  getCardSize() { return 12; }
  getGridOptions() { return { columns: "full", rows: "auto" }; }

  set hass(hass) {
    this._hass = hass;
    if (!this._started) { this._started = true; this._init(); }
  }

  connectedCallback() {
    if (this._started && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) { this._unsub.then((u) => u && u()).catch(() => {}); this._unsub = null; }
  }

  /* ---------- setup and data ---------- */

  _init() {
    this._messages = [];
    this._contacts = {};
    this._canSend = true;
    this._selected = null;      // thread key, or "new" while writing to a new number
    this._drafts = {};          // thread key -> unsent text
    this._showConvo = false;    // narrow layout: conversation instead of the list
    this._read = this._loadRead();

    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${this._css()}</style>
      <ha-card class="card"><div class="sms">
        <aside class="threads">
          <header class="threads-head">
            <h2>Messages</h2>
            <button class="icon-btn" data-act="new" title="New message" aria-label="New message"><ha-icon icon="mdi:message-plus-outline"></ha-icon></button>
          </header>
          <div class="list"><p class="hint">Loading…</p></div>
        </aside>
        <section class="convo">
          <header class="convo-head"></header>
          <div class="body" aria-live="polite"></div>
          <footer class="composer"></footer>
        </section>
      </div></ha-card>`;
    this._el = {
      sms: root.querySelector(".sms"), list: root.querySelector(".list"), head: root.querySelector(".convo-head"),
      body: root.querySelector(".body"), composer: root.querySelector(".composer"),
    };
    this._card = root.querySelector(".card");
    root.addEventListener("click", (e) => this._onClick(e));
    root.addEventListener("input", (e) => this._onInput(e));
    root.addEventListener("keydown", (e) => this._onKey(e));
    new ResizeObserver(([entry]) => {
      const narrow = entry.contentRect.width < 640;
      if (narrow !== this._narrow) { this._narrow = narrow; this._layout(); }
    }).observe(this._el.sms);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) this._markRead(); });
    this._subscribe();
  }

  _subscribe() {
    if (!this._hass) return;
    this._unsub = this._hass.connection.subscribeMessage((data) => this._onData(data), { type: "smartsms/subscribe" })
      .catch((err) => {
        this._unsub = null;
        const denied = err && err.code === "unauthorized";
        this._el.list.innerHTML = `<p class="hint">${denied
          ? "Only Home Assistant administrators can read messages."
          : `Couldn't load messages: ${esc(err && (err.message || err.code) || err)}`}</p>`;
        this._el.head.innerHTML = this._el.body.innerHTML = this._el.composer.innerHTML = "";
        return null;
      });
  }

  _onData(data) {
    this._messages = data.messages || [];
    this._contacts = data.contacts || {};
    this._canSend = data.can_send !== false;
    const threads = this._threads();
    if (this._read === null) { // first visit on this device: nothing old counts as new
      this._read = {};
      for (const t of threads) this._read[t.key] = ts(t.last);
      this._saveRead();
    }
    if (this._selected === null) this._selected = threads.length ? threads[0].key : "new";
    this._render();
  }

  _threads() {
    const map = new Map();
    for (const m of this._messages) {
      const key = m.thread || normalise(m.number);
      let t = map.get(key);
      if (!t) map.set(key, (t = { key, number: m.number, messages: [] }));
      t.messages.push(m);
      t.last = m;
      if (m.direction === "in") t.lastIn = m;
    }
    return [...map.values()].sort((a, b) => ts(b.last) - ts(a.last));
  }

  _name(key, raw) { return this._contacts[key] || displayNumber(key, raw); }

  /* ---------- read state (per device) ---------- */

  _loadRead() {
    try { const v = JSON.parse(localStorage.getItem(READ_KEY)); return v && typeof v === "object" ? v : null; } catch (e) { return null; }
  }

  _saveRead() {
    try { localStorage.setItem(READ_KEY, JSON.stringify(this._read)); } catch (e) { /* private window */ }
  }

  _unread(t) { return t.lastIn && ts(t.lastIn) > (this._read[t.key] || 0); }

  _markRead() {
    if (!this._read || document.hidden || !this._selected || this._selected === "new") return;
    if (this._narrow && !this._showConvo) return;
    const t = this._threads().find((x) => x.key === this._selected);
    if (t && this._unread(t)) { this._read[t.key] = ts(t.lastIn); this._saveRead(); this._renderList(); }
  }

  /* ---------- rendering ---------- */

  _render() {
    // A panel view (isPanel) gets the whole screen; elsewhere a fixed height, or the card's own
    this._card.style.height = this._config.height || (this.isPanel ? "calc(100dvh - var(--header-height, 56px) - 16px)" : "600px");
    this._renderList();
    this._renderConvo();
    this._layout();
    this._markRead();
  }

  _layout() {
    this._el.sms.classList.toggle("narrow", !!this._narrow);
    this._el.sms.classList.toggle("show-convo", !!this._showConvo);
  }

  _renderList() {
    const threads = this._threads();
    if (!threads.length) {
      this._el.list.innerHTML = `<p class="hint">No messages yet. Texts to your Mobile Message number will show up here.</p>`;
      return;
    }
    this._el.list.innerHTML = threads.map((t) => {
      const last = t.last;
      const name = this._name(t.key, t.number);
      const failed = last.status === "failed";
      const preview = (last.direction === "out" ? (failed ? "Not sent: " : "You: ") : "") + last.body.replace(/\s+/g, " ");
      return `<button class="thread${t.key === this._selected ? " sel" : ""}${this._unread(t) ? " unread" : ""}" data-thread="${esc(t.key)}">
        <span class="avatar" aria-hidden="true">${this._initials(t.key, name)}</span>
        <span class="name">${esc(name)}</span>
        <span class="when">${esc(this._fmtWhen(new Date(ts(last))))}</span>
        <span class="preview${failed ? " err" : ""}">${esc(preview)}</span>
        <span class="dot" aria-label="unread"></span>
      </button>`;
    }).join("");
  }

  _initials(key, name) {
    if (!this._contacts[key] && canReply(key)) return `<ha-icon icon="mdi:account"></ha-icon>`;
    const words = name.split(/\s+/).filter(Boolean);
    return esc(((words[0] || "?")[0] + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase());
  }

  _renderConvo() {
    const key = this._selected;
    if (key === "new") { this._renderNew(); return; }
    // A number with no messages yet (just sent to, still arriving) gets an empty conversation
    const t = this._threads().find((x) => x.key === key) || (canReply(key) ? { key, number: key, messages: [] } : null);
    if (!t) { this._selected = "new"; this._renderNew(); return; }
    const name = this._name(t.key, t.number);
    const named = !!this._contacts[t.key];
    const reply = canReply(t.key);
    const typed = this.shadowRoot.querySelector(".name-input")?.value; // a message arriving mid-rename
    this._el.head.innerHTML = this._editing
      ? `${this._backBtn()}<input class="name-input" type="text" maxlength="40" value="${esc(typed ?? this._contacts[t.key] ?? "")}" placeholder="Name for ${esc(displayNumber(t.key, t.number))}" aria-label="Contact name">
         <button class="text-btn" data-act="save-name">Save</button><button class="text-btn quiet" data-act="cancel-name">Cancel</button>`
      : `${this._backBtn()}<span class="avatar" aria-hidden="true">${this._initials(t.key, name)}</span>
         <div class="who"><div class="title">${esc(name)}</div>${named ? `<div class="sub">${esc(displayNumber(t.key, t.number))}</div>` : ""}</div>
         ${reply ? `<a class="icon-btn" href="tel:+${esc(t.key)}" title="Call" aria-label="Call"><ha-icon icon="mdi:phone-outline"></ha-icon></a>` : ""}
         <button class="icon-btn" data-act="edit-name" title="${named ? "Rename" : "Add a name"}" aria-label="${named ? "Rename" : "Add a name"}"><ha-icon icon="mdi:account-edit-outline"></ha-icon></button>`;
    if (this._editing && typed === undefined) setTimeout(() => this.shadowRoot.querySelector(".name-input")?.focus(), 0);

    const body = this._el.body;
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    const switched = this._shownThread !== key;
    this._shownThread = key;
    body.innerHTML = this._bubbles(t.messages);
    if (switched || atBottom) body.scrollTop = body.scrollHeight;

    this._renderComposer(key, reply ? "" : `${esc(name)} is a sender name, not a number, so it can't get replies.`);
  }

  _renderNew() {
    if (this._shownThread === "new" && this.shadowRoot.querySelector(".to-input")) return; // keep typing undisturbed
    this._shownThread = "new";
    this._el.head.innerHTML = `${this._backBtn()}<label class="to"><span>To</span>
      <input class="to-input" type="tel" inputmode="tel" autocomplete="off" placeholder="04xx xxx xxx" value="${esc(this._newTo || "")}" aria-label="Phone number"></label>`;
    this._el.body.innerHTML = `<p class="hint centre">Messages go out from your Mobile Message number and cost a credit for each SMS part.</p>`;
    this._renderComposer("new", "");
  }

  _backBtn() {
    return `<button class="icon-btn back" data-act="back" title="All messages" aria-label="All messages"><ha-icon icon="mdi:arrow-left"></ha-icon></button>`;
  }

  _bubbles(messages) {
    let html = "";
    let prevDay = null;
    messages.forEach((m, i) => {
      const when = new Date(ts(m));
      if (!prevDay || !sameDay(prevDay, when)) { html += `<div class="day">${esc(this._fmtDay(when))}</div>`; prevDay = when; }
      const next = messages[i + 1];
      const failed = m.status === "failed";
      // Time under the last of a run: same direction, same day, within 10 minutes
      const endOfRun = failed || !next || next.direction !== m.direction || ts(next) - ts(m) > 600000 || !sameDay(when, new Date(ts(next)));
      let meta = "";
      if (failed) meta = `<div class="meta err">Not sent${m.error ? `: ${esc(m.error)}` : ""}</div>`;
      else if (endOfRun) {
        const by = m.direction === "out" ? (m.sent_by ? ` · ${esc(m.sent_by)}` : " · Automation") : "";
        meta = `<div class="meta">${esc(this._fmtTime(when))}${by}</div>`;
      }
      html += `<div class="msg ${m.direction === "out" ? "out" : "in"}${failed ? " failed" : ""}${endOfRun ? " end" : ""}">
        <div class="bubble">${linkify(esc(m.body))}</div>${meta}</div>`;
    });
    return html;
  }

  _renderComposer(key, blocked) {
    if (blocked || !this._canSend) {
      this._el.composer.innerHTML = `<p class="hint">${blocked || "SmartSMS isn't set up, so messages can't be sent."}</p>`;
      return;
    }
    if (this._composerFor === key && this._el.composer.querySelector("textarea")) return; // keep typing undisturbed
    this._composerFor = key;
    this._el.composer.innerHTML = `<div class="compose-row">
        <textarea rows="1" placeholder="Text message" aria-label="Message">${esc(this._drafts[key] || "")}</textarea>
        <button class="send" data-act="send" title="Send (Ctrl+Enter)" aria-label="Send" disabled><ha-icon icon="mdi:send"></ha-icon></button>
      </div>
      <div class="count"><span class="status"></span><span class="parts"></span></div>`;
    this._updateComposer();
  }

  _updateComposer() {
    const ta = this.shadowRoot.querySelector("textarea");
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight + 2, 160)}px`;
    const text = ta.value;
    const len = [...text].length;
    const p = smsParts(text);
    const over = len > MAX_LEN;
    const to = this._selected === "new" ? normalise(this._newTo || "") : this._selected;
    const send = this.shadowRoot.querySelector(".send");
    send.disabled = this._sending || !text.trim() || over || !canReply(to);
    this.shadowRoot.querySelector(".parts").innerHTML = !text ? "" : over
      ? `<span class="err">${len - MAX_LEN} over the ${MAX_LEN}-character limit</span>`
      : `${p.parts} SMS · ${p.left} left${p.unicode ? ` <span title="Emoji and some symbols make every part 70 characters">(special characters)</span>` : ""}`;
    const status = this.shadowRoot.querySelector(".status");
    status.className = `status${this._error ? " err" : ""}`;
    status.textContent = this._sending ? "Sending…" : this._error || "";
  }

  /* ---------- actions ---------- */

  _onClick(e) {
    const thread = e.target.closest("[data-thread]");
    if (thread) { this._open(thread.dataset.thread); return; }
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "new") { this._newTo = ""; this._open("new"); setTimeout(() => this.shadowRoot.querySelector(".to-input")?.focus(), 0); }
    else if (act === "back") { this._showConvo = false; this._editing = false; this._layout(); this._renderList(); }
    else if (act === "send") this._send();
    else if (act === "edit-name") { this._editing = true; this._renderConvo(); }
    else if (act === "cancel-name") { this._editing = false; this._renderConvo(); }
    else if (act === "save-name") this._saveName();
  }

  _open(key) {
    this._selected = key;
    this._editing = false;
    this._error = "";
    this._showConvo = true;
    this._render();
  }

  _onInput(e) {
    if (e.target.matches("textarea")) { this._drafts[this._composerFor] = e.target.value; this._error = ""; this._updateComposer(); }
    else if (e.target.matches(".to-input")) { this._newTo = e.target.value; this._error = ""; this._updateComposer(); }
    else if (e.target.matches(".name-input")) e.target.setCustomValidity("");
  }

  _onKey(e) {
    if (e.target.matches("textarea") && e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this._send(); }
    else if (e.target.matches(".to-input") && e.key === "Enter") { e.preventDefault(); this.shadowRoot.querySelector("textarea")?.focus(); }
    else if (e.target.matches(".name-input") && e.key === "Enter") { e.preventDefault(); this._saveName(); }
    else if (e.target.matches(".name-input") && e.key === "Escape") { this._editing = false; this._renderConvo(); }
  }

  async _send() {
    const ta = this.shadowRoot.querySelector("textarea");
    const from = this._composerFor;
    const to = from === "new" ? (this._newTo || "").trim() : from;
    const text = ta ? ta.value : "";
    if (this._sending || !text.trim() || [...text].length > MAX_LEN || !canReply(normalise(to))) return;
    this._sending = true;
    this._error = "";
    this._updateComposer();
    try {
      await this._hass.callWS({
        type: "call_service", domain: "smartsms", service: "send_sms",
        service_data: { to: from === "new" ? to : `+${to}`, message: text }, return_response: true,
      });
      delete this._drafts[from];
      if (this._composerFor === from && ta) ta.value = "";
      if (from === "new") { this._newTo = ""; this._composerFor = null; this._selected = normalise(to); }
    } catch (err) {
      this._error = (err && err.message) || "Couldn't send the message";
    }
    this._sending = false;
    if (this._selected !== this._shownThread) this._render();
    else this._updateComposer();
  }

  async _saveName() {
    const input = this.shadowRoot.querySelector(".name-input");
    if (!input) return;
    try {
      await this._hass.callWS({ type: "smartsms/contact_set", number: this._selected, name: input.value });
      this._editing = false; // the subscription redraws with the new name
    } catch (err) {
      input.setCustomValidity((err && err.message) || "Couldn't save the name");
      input.reportValidity();
    }
  }

  /* ---------- dates ---------- */

  _lang() { return this._hass?.locale?.language || this._hass?.language || navigator.language; }

  _h12() {
    const f = this._hass?.locale?.time_format;
    return f === "12" ? true : f === "24" ? false : undefined;
  }

  _fmtTime(d) { return d.toLocaleTimeString(this._lang(), { hour: "numeric", minute: "2-digit", hour12: this._h12() }); }

  _daysAgo(d) {
    const a = new Date(d); a.setHours(0, 0, 0, 0);
    const b = new Date(); b.setHours(0, 0, 0, 0);
    return Math.round((b - a) / 86400000);
  }

  _fmtDay(d) {
    const ago = this._daysAgo(d);
    if (ago === 0) return "Today";
    if (ago === 1) return "Yesterday";
    if (ago < 7) return d.toLocaleDateString(this._lang(), { weekday: "long" });
    const year = d.getFullYear() === new Date().getFullYear() ? undefined : "numeric";
    return d.toLocaleDateString(this._lang(), { weekday: "short", day: "numeric", month: "short", year });
  }

  _fmtWhen(d) {
    const ago = this._daysAgo(d);
    if (ago === 0) return this._fmtTime(d);
    if (ago === 1) return "Yesterday";
    if (ago < 7) return d.toLocaleDateString(this._lang(), { weekday: "short" });
    const year = d.getFullYear() === new Date().getFullYear() ? undefined : "2-digit";
    return d.toLocaleDateString(this._lang(), { day: "numeric", month: "short", year });
  }

  /* ---------- styles ---------- */

  _css() {
    return `
      :host { display: block; }
      .card { display: flex; overflow: hidden; min-height: 360px; }
      .sms { display: grid; grid-template-columns: minmax(240px, 320px) 1fr; width: 100%; min-height: 0;
        color: var(--primary-text-color); font-family: var(--ha-font-family-body, inherit); }
      .threads { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--divider-color); }
      .threads-head { display: flex; align-items: center; justify-content: space-between; min-height: 56px;
        padding: 0 8px 0 16px; box-sizing: border-box; }
      h2 { margin: 0; font-size: 20px; font-weight: 500; }
      .list { flex: 1; overflow-y: auto; padding-bottom: 8px; }
      .thread { display: grid; grid-template-columns: 40px 1fr auto; grid-template-rows: auto auto; column-gap: 12px;
        align-items: center; width: 100%; padding: 10px 16px; border: 0; background: none; color: inherit;
        font: inherit; text-align: left; cursor: pointer; position: relative; }
      .thread:hover { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
      .thread.sel { background: color-mix(in srgb, var(--primary-color) 16%, transparent); }
      .thread .avatar { grid-row: 1 / 3; }
      .avatar { width: 40px; height: 40px; flex: none; border-radius: 50%; display: grid; place-items: center;
        background: color-mix(in srgb, var(--primary-color) 22%, transparent); color: var(--primary-color);
        font-weight: 600; font-size: 15px; --mdc-icon-size: 22px; }
      .name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .when { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; }
      .preview { grid-column: 2 / 4; font-size: 13px; color: var(--secondary-text-color); overflow: hidden;
        text-overflow: ellipsis; white-space: nowrap; padding-right: 14px; }
      .dot { display: none; position: absolute; right: 16px; bottom: 15px; width: 8px; height: 8px; border-radius: 50%;
        background: var(--primary-color); }
      .unread .dot { display: block; }
      .unread .name, .unread .preview { color: var(--primary-text-color); font-weight: 600; }
      .unread .when { color: var(--primary-color); }
      .convo { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
      .convo-head { display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 8px 8px 8px 16px;
        box-sizing: border-box; border-bottom: 1px solid var(--divider-color); }
      .who { flex: 1; min-width: 0; }
      .title { font-size: 16px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .sub { font-size: 12px; color: var(--secondary-text-color); }
      .body { flex: 1; overflow-y: auto; padding: 8px 16px 12px; display: flex; flex-direction: column; }
      .day { align-self: center; margin: 16px 0 8px; font-size: 12px; color: var(--secondary-text-color); }
      .msg { display: flex; flex-direction: column; max-width: min(78%, 560px); margin-bottom: 2px; }
      .msg.end { margin-bottom: 6px; }
      .msg.in { align-self: flex-start; }
      .msg.out { align-self: flex-end; align-items: flex-end; }
      .bubble { padding: 8px 12px; border-radius: 18px; line-height: 1.4; font-size: 15px; white-space: pre-wrap;
        overflow-wrap: anywhere; }
      .in .bubble { background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); }
      .in.end .bubble { border-bottom-left-radius: 6px; }
      .out .bubble { background: color-mix(in srgb, var(--primary-color) 72%, #000); color: #fff; }
      .out.end .bubble { border-bottom-right-radius: 6px; }
      .out.failed .bubble { background: none; color: var(--primary-text-color); border: 1px solid var(--error-color, #db4437); }
      .bubble a { color: inherit; text-decoration: underline; }
      .meta { margin: 3px 6px 0; font-size: 11px; color: var(--secondary-text-color); }
      .out .meta { text-align: right; }
      .err { color: var(--error-color, #db4437); }
      .composer { padding: 8px 8px 8px 16px; border-top: 1px solid var(--divider-color); }
      .compose-row { display: flex; align-items: flex-end; gap: 8px; }
      textarea, input { font: inherit; color: var(--primary-text-color); background: none; box-sizing: border-box; }
      textarea { flex: 1; min-height: 40px; max-height: 160px; resize: none; padding: 9px 14px; font-size: 15px;
        line-height: 1.4; border: 1px solid var(--divider-color); border-radius: 20px; }
      textarea:focus, input:focus { outline: none; border-color: var(--primary-color); }
      .send { flex: none; width: 40px; height: 40px; border: 0; border-radius: 50%; display: grid; place-items: center;
        background: var(--primary-color); color: var(--text-primary-color, #fff); cursor: pointer; --mdc-icon-size: 20px; }
      .send:disabled { opacity: 0.35; cursor: default; }
      .count { display: flex; justify-content: space-between; gap: 8px; min-height: 16px; margin: 4px 56px 0 14px;
        font-size: 11px; color: var(--secondary-text-color); }
      .icon-btn { flex: none; width: 40px; height: 40px; border: 0; border-radius: 50%; display: grid; place-items: center;
        background: none; color: var(--secondary-text-color); cursor: pointer; text-decoration: none; --mdc-icon-size: 22px; }
      .icon-btn:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); color: var(--primary-text-color); }
      .threads-head .icon-btn { color: var(--primary-color); }
      .back { display: none; margin-left: -8px; }
      .to { flex: 1; display: flex; align-items: center; gap: 12px; color: var(--secondary-text-color); }
      .to-input, .name-input { flex: 1; min-width: 0; height: 40px; padding: 0 14px; font-size: 15px;
        border: 1px solid var(--divider-color); border-radius: 20px; }
      .text-btn { border: 0; background: none; color: var(--primary-color); font: inherit; font-weight: 500;
        padding: 8px 10px; border-radius: 8px; cursor: pointer; }
      .text-btn.quiet { color: var(--secondary-text-color); }
      .text-btn:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
      .hint { margin: 16px; color: var(--secondary-text-color); font-size: 14px; line-height: 1.5; }
      .hint.centre { margin: auto; max-width: 320px; text-align: center; }
      button:focus-visible, a:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
      .sms.narrow { grid-template-columns: 1fr; }
      .sms.narrow .threads { border-right: 0; }
      .sms.narrow.show-convo .threads, .sms.narrow:not(.show-convo) .convo { display: none; }
      .sms.narrow .back { display: grid; }
      .sms.narrow .msg { max-width: 85%; }
    `;
  }
}

if (!customElements.get("smartsms-messages-card")) customElements.define("smartsms-messages-card", SmartSMSMessagesCard);
window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "smartsms-messages-card")) {
  window.customCards.push({ type: "smartsms-messages-card", name: "SmartSMS messages", description: "Read and send SMS (admins only).", preview: false });
}
console.info(`%c SMARTSMS-MESSAGES-CARD %c ${SMS_VERSION} `, "background:#003049;color:#fff", "background:#C1121F;color:#fff");
