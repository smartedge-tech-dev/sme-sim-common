// Vendored from sme-bac-sim v0.4.0 (d8382883dd7a6f2942659e7e230eef5f153274ca) sme_bacnet_sim/static/shell/shell.js; see sme-sim-common design §6.
"use strict";
/*
 * Reusable application shell (MIT): header with brand + dropdown menu bar, compact status area,
 * mobile nav, footer, about dialog, toasts, theme (system/light/dark) and a tiny i18n helper.
 * It has no protocol / product knowledge; the app passes everything in through Shell.init().
 *
 * Load this file in <head> (not deferred) so the stored theme is applied before first paint.
 * Optional: <script src=".../shell.js" data-storage="myapp"> sets the localStorage key prefix.
 *
 * API
 *   Shell.addStrings(lang, dict)        merge UI strings into I18N[lang]
 *   Shell.t(key, vars)                  translate; "{name}" placeholders are filled from vars
 *   Shell.applyI18n(root)               fill [data-i18n], [data-i18n-placeholder|title|aria-label]
 *   Shell.init({product, tagline, logoSvg, version, license, year, links, about, menus, vendor, copyright})
 *     copyright: i18n key or plain text for the copyright line ({year} {product} {license} {version} filled in);
 *            default "shell.footer.copyright".
 *     links: {home, repo, docs, issues, license, vendor: {name, url}}   (links.vendor: legacy "by X" footer)
 *     vendor: {name, nameLocal, url, contactUrl, email, logoSvg | logoUrl, blurb, services: [key]}
 *            the company behind the product: footer credit + contact link, About section, Help item.
 *            blurb / services are i18n keys (or plain text). Everything is optional except name.
 *     about: [[labelKey, value], ...]   extra rows for the About dialog
 *     menus: [{id, label, items: [item]}]
 *     item:  {id, label, onClick | href (+download) | submenu: [item], checked, radio, disabled, title}
 *            or {separator: true}.  Labels are i18n keys (a missing key renders as-is).
 *   Shell.updateItem(id, patch)         change a menu item (label, checked, disabled, submenu, ...)
 *   Shell.setStatus(html)               set the always-visible status area (right side of header)
 *   Shell.setVersion(v)                 update version in footer / about
 *   Shell.version                       sme-sim-common version: data-common-version on the shell.js <script>,
 *                                       else its ?v= query (both rendered by make_base_app); "" if unknown
 *   Shell.vendors                       vendor presets registered by vendor/vendor.js (e.g. Shell.vendors.smartEdge)
 *   Shell.toast(msg, kind)              kind: "info" | "ok" | "error"
 *   Shell.themeItem()                   ready-made "Theme > System/Light/Dark" menu item
 *   Shell.helpMenu()                    ready-made Help menu built from links
 *   Shell.openAbout(), Shell.setTheme(t), Shell.getTheme(), Shell.closeMenus()
 *   window event "shell:themechange" {detail: {theme, effective}} fires whenever colors change.
 */
(function (global) {
  const doc = global.document;

  // ---------------------------------------------------------------- i18n
  const I18N = (global.I18N = global.I18N || {});
  I18N.en = Object.assign({
    "shell.menu": "Menu",
    "shell.close": "Close",
    "shell.theme": "Theme",
    "shell.theme.system": "System",
    "shell.theme.light": "Light",
    "shell.theme.dark": "Dark",
    "shell.help": "Help",
    "shell.help.docs": "README / Docs",
    "shell.help.issue": "Report an issue",
    "shell.help.about": "About…",
    "shell.about.title": "About {product}",
    "shell.about.version": "Version",
    "shell.about.license": "License",
    "shell.about.common": "Common library",
    "shell.link.github": "GitHub",
    "shell.link.docs": "Docs",
    "shell.link.license": "License {license}",
    "shell.footer.copyright": "© {year} {product} contributors · {license} License · v{version}",
    "shell.footer.by": "by",
    "shell.top": "Back to top",
    "shell.lang": "Language",
  }, I18N.en || {});
  I18N.ja = Object.assign({
    "shell.menu": "メニュー",
    "shell.close": "閉じる",
    "shell.theme": "テーマ",
    "shell.theme.system": "システム設定に従う",
    "shell.theme.light": "ライト",
    "shell.theme.dark": "ダーク",
    "shell.help": "ヘルプ",
    "shell.help.docs": "README / ドキュメント",
    "shell.help.issue": "不具合を報告",
    "shell.help.about": "バージョン情報…",
    "shell.about.title": "{product} について",
    "shell.about.version": "バージョン",
    "shell.about.license": "ライセンス",
    "shell.about.common": "共通ライブラリ",
    "shell.link.github": "GitHub",
    "shell.link.docs": "ドキュメント",
    "shell.link.license": "{license} ライセンス",
    "shell.footer.copyright": "© {year} {product} contributors · {license} License · v{version}",
    "shell.footer.by": "by",
    "shell.top": "ページの先頭へ",
    "shell.lang": "言語",
  }, I18N.ja || {});
  I18N.zh = Object.assign({
    "shell.menu": "菜单",
    "shell.close": "关闭",
    "shell.theme": "主题",
    "shell.theme.system": "跟随系统",
    "shell.theme.light": "浅色",
    "shell.theme.dark": "深色",
    "shell.help": "帮助",
    "shell.help.docs": "README / 文档",
    "shell.help.issue": "报告问题",
    "shell.help.about": "关于…",
    "shell.about.title": "关于 {product}",
    "shell.about.version": "版本",
    "shell.about.license": "许可证",
    "shell.about.common": "公共库",
    "shell.link.github": "GitHub",
    "shell.link.docs": "文档",
    "shell.link.license": "{license} 许可证",
    "shell.footer.copyright": "© {year} {product} contributors · {license} License · v{version}",
    "shell.footer.by": "by",
    "shell.top": "回到顶部",
    "shell.lang": "语言",
  }, I18N.zh || {});

  // UI languages, labelled in their own language. "zh" is Simplified Chinese.
  const LANGS = { en: "English", ja: "日本語", zh: "简体中文" };
  const HTML_LANG = { en: "en", ja: "ja", zh: "zh-CN" };
  const langKey = `${(doc.currentScript && doc.currentScript.dataset.storage) || "shell"}.lang`;
  function detectLang() {
    let saved = null;
    try { saved = global.localStorage.getItem(langKey); } catch (e) { /* storage blocked */ }
    if (saved && saved in LANGS) return saved;
    for (const l of (global.navigator && (global.navigator.languages || [global.navigator.language])) || []) {
      const base = String(l || "").toLowerCase().split("-")[0];
      if (base in LANGS) return base;
    }
    return "en";
  }
  let lang = detectLang();
  doc.documentElement.lang = HTML_LANG[lang];
  // Menus, dialogs and tables are rendered once from the dictionary, so switching reloads the page.
  function setLang(l) {
    if (!(l in LANGS) || l === lang) return;
    try { global.localStorage.setItem(langKey, l); } catch (e) { /* storage blocked */ }
    global.location.reload();
  }

  function t(key, vars) {
    let s = (I18N[lang] && I18N[lang][key]) ?? (I18N.en && I18N.en[key]) ?? key;
    if (vars) s = String(s).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
    return s;
  }
  function addStrings(l, dict) { I18N[l] = Object.assign(I18N[l] || {}, dict); }
  function applyI18n(root) {
    root = root || doc;
    root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    for (const attr of ["placeholder", "title", "aria-label"]) {
      root.querySelectorAll(`[data-i18n-${attr}]`).forEach((el) => el.setAttribute(attr, t(el.getAttribute(`data-i18n-${attr}`))));
    }
  }

  // ---------------------------------------------------------------- theme
  const script = doc.currentScript;
  // Version of the shared package (sme-sim-common), shown in About for troubleshooting.
  const COMMON_VERSION = (function () {
    if (!script) return "";
    if (script.dataset.commonVersion) return script.dataset.commonVersion;
    try { return new URL(script.src, global.location.href).searchParams.get("v") || ""; } catch (e) { return ""; }
  })();
  const storeKey = `${(script && script.dataset.storage) || "shell"}.theme`;
  const THEMES = ["system", "light", "dark"];
  const mqDark = global.matchMedia ? global.matchMedia("(prefers-color-scheme: dark)") : null;
  let theme = "system";

  function storeGet(k) { try { return global.localStorage.getItem(k); } catch (e) { return null; } }
  function storeSet(k, v) { try { global.localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
  function effectiveTheme() { return theme === "system" ? (mqDark && mqDark.matches ? "dark" : "light") : theme; }
  function emitTheme() {
    global.dispatchEvent(new CustomEvent("shell:themechange", { detail: { theme, effective: effectiveTheme() } }));
  }
  function applyTheme(th) {
    theme = THEMES.includes(th) ? th : "system";
    const root = doc.documentElement;
    if (theme === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", theme);
  }
  function setTheme(th) {
    applyTheme(th);
    storeSet(storeKey, theme);
    for (const x of THEMES) updateItem(`shell.theme.${x}`, { checked: x === theme });
    emitTheme();
  }
  applyTheme(storeGet(storeKey));
  if (mqDark) {
    const onSys = () => { if (theme === "system") emitTheme(); };
    if (mqDark.addEventListener) mqDark.addEventListener("change", onSys); else if (mqDark.addListener) mqDark.addListener(onSys);
  }

  // ---------------------------------------------------------------- helpers
  let cfg = { product: "", tagline: "", logoSvg: "", version: "", license: "MIT", year: new Date().getFullYear(), links: {}, about: [], menus: [] };
  const items = new Map(); // id -> {item, el}
  let header = null, footer = null, aboutDlg = null, toastBox = null;
  const mqMobile = global.matchMedia ? global.matchMedia("(max-width: 1000px)") : { matches: false };

  function h(tag, attrs, ...kids) {
    const el = doc.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat(Infinity)) if (c != null && c !== false) el.append(c);
    return el;
  }
  const extLink = (href, text, cls) => h("a", { href, class: cls, target: "_blank", rel: "noopener" }, text);

  // ---------------------------------------------------------------- menus
  function renderItem(item) {
    if (item.separator) return h("li", { role: "separator", class: "sh-sep" });
    const hasCheck = "checked" in item && item.checked !== undefined;
    const role = hasCheck ? (item.radio ? "menuitemradio" : "menuitemcheckbox") : "menuitem";
    const kids = [h("span", { class: "sh-check", "aria-hidden": "true" }), h("span", { class: "sh-ilbl" }, t(item.label))];
    let ctl;
    if (item.href && !item.disabled) {
      const external = /^https?:/i.test(item.href);
      ctl = h("a", { role, href: item.href, title: item.title, download: item.download ? "" : null,
        target: external ? "_blank" : null, rel: external ? "noopener" : null }, kids);
    } else {
      ctl = h("button", { type: "button", role, title: item.title, disabled: !!item.disabled }, kids);
    }
    if (hasCheck) ctl.setAttribute("aria-checked", item.checked ? "true" : "false");
    const li = h("li", { role: "none", class: `sh-item${hasCheck && item.checked ? " is-checked" : ""}${item.radio ? " is-radio" : ""}` }, ctl);
    if (item.submenu) {
      li.classList.add("sh-sub");
      ctl.setAttribute("aria-haspopup", "true");
      ctl.setAttribute("aria-expanded", "false");
      ctl.append(h("span", { class: "sh-caret", "aria-hidden": "true" }, "▸"));
      li.append(h("ul", { class: "sh-panel sh-subpanel", role: "menu" }, item.submenu.map(renderItem)));
    }
    ctl.addEventListener("click", (e) => {
      if (item.submenu) {
        e.preventDefault(); e.stopPropagation();
        const open = !li.classList.contains("open");
        li.classList.toggle("open", open);
        ctl.setAttribute("aria-expanded", String(open));
        return;
      }
      if (item.disabled) return;
      closeMenus(null, true);
      if (item.onClick) { e.preventDefault(); item.onClick(e); }
    });
    if (item.id) items.set(item.id, { item, el: li });
    return li;
  }

  function updateItem(id, patch) {
    const rec = items.get(id);
    if (!rec) return;
    Object.assign(rec.item, patch);
    const focused = rec.el.contains(doc.activeElement);
    const wasOpen = rec.el.classList.contains("open");
    const li = renderItem(rec.item);
    if (wasOpen) { li.classList.add("open"); li.firstChild.setAttribute("aria-expanded", "true"); }
    rec.el.replaceWith(li);
    rec.el = li;
    if (focused) li.firstChild.focus();
  }

  function renderMenus() {
    return h("ul", { class: "sh-menubar", role: "menubar" }, cfg.menus.map((m, i) => {
      const panelId = `sh-m-${m.id}`;
      const btn = h("button", { type: "button", class: "sh-menubtn", role: "menuitem", "aria-haspopup": "true",
        "aria-expanded": "false", "aria-controls": panelId },
        h("span", { class: "sh-num", "aria-hidden": "true" }, String(i + 1).padStart(2, "0")),
        h("span", { class: "sh-lbl" }, t(m.label)),
        h("span", { class: "sh-arrow", "aria-hidden": "true" }, "→"));
      const li = h("li", { class: "sh-menu", role: "none" }, btn,
        h("ul", { class: "sh-panel", role: "menu", id: panelId }, m.items.map(renderItem)));
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (li.classList.contains("open")) closeMenus(); else openMenu(li);
      });
      btn.addEventListener("mouseenter", () => {
        // Desktop menu-bar behavior: once a menu is open, hovering another one switches to it.
        if (!mqMobile.matches && header.querySelector(".sh-menu.open") && !li.classList.contains("open")) openMenu(li);
      });
      return li;
    }));
  }

  function openMenu(li) {
    closeMenus(li);
    li.classList.add("open");
    li.querySelector(".sh-menubtn").setAttribute("aria-expanded", "true");
  }

  function closeMenus(except, closeNav) {
    if (!header) return;
    header.querySelectorAll(".sh-menu.open, .sh-sub.open").forEach((li) => {
      if (li === except) return;
      li.classList.remove("open");
      const b = li.querySelector(".sh-menubtn") || li.firstChild;
      if (b) b.setAttribute("aria-expanded", "false");
    });
    if (closeNav) setNav(false);
  }

  function setNav(open) {
    header.classList.toggle("nav-open", open);
    header.querySelector(".sh-burger").setAttribute("aria-expanded", String(open));
  }

  function onKey(e) {
    if (e.key === "Escape") {
      const openBtn = header.querySelector(".sh-menu.open > .sh-menubtn");
      const navOpen = header.classList.contains("nav-open");
      if (!openBtn && !navOpen) return;
      closeMenus(null, true);
      (openBtn || header.querySelector(".sh-burger")).focus();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const menu = header.querySelector(".sh-menu.open");
    if (!menu || !menu.contains(doc.activeElement)) return;
    // Arrow keys move focus through the visible, enabled entries of the open menu.
    const list = [...menu.querySelectorAll(".sh-item > button:not([disabled]), .sh-item > a")].filter((x) => x.offsetParent);
    if (!list.length) return;
    e.preventDefault();
    const i = list.indexOf(doc.activeElement);
    const n = e.key === "ArrowDown" ? (i + 1) % list.length : (i <= 0 ? list.length - 1 : i - 1);
    list[n].focus();
  }

  // ---------------------------------------------------------------- brand / footer / about
  function brand(cls) {
    return h("span", { class: `sh-brandbox ${cls || ""}` },
      h("span", { class: "sh-mark", "aria-hidden": "true", html: cfg.logoSvg }),
      h("span", { class: "sh-type" }, h("span", { class: "sh-name" }, cfg.product), h("span", { class: "sh-tag" }, cfg.tagline)));
  }

  function linkList(cls) {
    const L = cfg.links, out = [];
    if (L.repo) out.push(extLink(L.repo, t("shell.link.github")));
    if (L.docs) out.push(extLink(L.docs, t("shell.link.docs")));
    if (L.license) out.push(extLink(L.license, t("shell.link.license", { license: cfg.license })));
    return h("nav", { class: cls }, out);
  }

  function copyright() {
    return t(cfg.copyright || "shell.footer.copyright", { year: cfg.year, product: cfg.product, license: cfg.license, version: cfg.version || "?" });
  }
  // ---- vendor (company behind the product); all specifics come from cfg.vendor
  function vendorName(v) { return v.nameLocal ? `${v.name} (${v.nameLocal})` : v.name; }
  function vendorLogo(v, cls) {
    const alt = t("vendor.logo", { name: v.name });
    if (v.logoSvg) return h("span", { class: `sh-vlogo ${cls || ""}`, role: "img", "aria-label": alt, html: v.logoSvg });
    if (v.logoUrl) return h("img", { class: `sh-vlogo ${cls || ""}`, src: v.logoUrl, alt, width: 14, height: 14 });
    return null;
  }
  function vendorContact(v) { return v.contactUrl || (v.email ? `mailto:${v.email}` : v.url); }

  function vendorLine() {
    const v = cfg.vendor;
    if (v && v.name) {
      const contact = vendorContact(v);
      return h("span", { class: "sh-by", title: `${t("vendor.developedBy")} ${vendorName(v)}` },
        vendorLogo(v), `${t("vendor.developedBy")} `,
        v.url ? extLink(v.url, vendorName(v)) : vendorName(v),
        contact ? [` · ${t("vendor.customDev")}: `, extLink(contact, t("vendor.contactUs"))] : null);
    }
    const lv = cfg.links.vendor;
    return lv ? h("span", { class: "sh-by" }, `${t("shell.footer.by")} `, extLink(lv.url, lv.name)) : null;
  }

  // Website / contact page / e-mail links, shared by the About dialog and the full footer.
  function vendorLinks(v, cls) {
    const out = [];
    if (v.url) out.push(extLink(v.url, t("vendor.website")));
    if (v.contactUrl) out.push(extLink(v.contactUrl, t("vendor.contactPage")));
    if (v.email) out.push(h("a", { href: `mailto:${v.email}` }, v.email));
    return out.length ? h("nav", { class: cls }, out) : null;
  }

  function vendorFoot() {
    const v = cfg.vendor;
    if (!v || !v.name) return null;
    return h("div", { class: "sh-foot-vendor" }, vendorLogo(v, "sh-vlogo-lg"),
      h("span", null, vendorName(v)), vendorLinks(v, "sh-foot-links"));
  }

  function vendorAbout() {
    const v = cfg.vendor;
    if (!v || !v.name) return null;
    const services = (v.services || []).map((k) => h("li", null, t(k)));
    return h("section", { class: "sh-about-vendor" },
      h("div", { class: "sh-vendor-head" }, vendorLogo(v, "sh-vlogo-lg"), h("strong", null, vendorName(v))),
      v.blurb ? h("p", { class: "sh-vendor-blurb" }, t(v.blurb)) : null,
      services.length ? [h("p", { class: "sh-vendor-h" }, t("vendor.available")), h("ul", { class: "sh-vendor-svc" }, services)] : null,
      vendorLinks(v, "sh-about-links"));
  }

  function renderFooter() {
    const top = h("button", { type: "button", class: "sh-top", "aria-label": t("shell.top"), title: t("shell.top"),
      onclick: () => global.scrollTo({ top: 0, behavior: "smooth" }) }, "↑");
    return h("footer", { class: "sh-footer" },
      h("div", { class: "sh-foot-top" }, brand(), linkList("sh-foot-links"), top),
      vendorFoot(),
      h("div", { class: "sh-foot-bottom" }, h("span", { class: "sh-copy" }, copyright()), vendorLine()));
  }

  function renderAbout() {
    const rows = [[t("shell.about.version"), cfg.version ? `v${cfg.version}` : "?"], [t("shell.about.license"), cfg.license]]
      .concat((cfg.about || []).map(([k, v]) => [t(k), v]))
      .concat(COMMON_VERSION ? [[t("shell.about.common"), `sme-sim-common v${COMMON_VERSION}`]] : []);
    const dlg = h("dialog", { class: "sh-dialog sh-about", "aria-label": t("shell.about.title", { product: cfg.product }) },
      h("form", { method: "dialog", class: "sh-about-body" },
        brand("sh-about-brand"),
        h("dl", { class: "sh-about-rows" }, rows.map(([k, v]) => [h("dt", null, k), h("dd", null, v)])),
        linkList("sh-about-links"),
        vendorAbout(),
        h("p", { class: "sh-about-copy" }, copyright(), cfg.vendor ? null : [" ", vendorLine()]),
        h("div", { class: "sh-about-btns" }, h("button", { class: "btn primary", value: "close" }, t("shell.close")))));
    return dlg;
  }

  function openAbout() {
    const fresh = renderAbout();
    if (aboutDlg) aboutDlg.replaceWith(fresh); else doc.body.append(fresh);
    aboutDlg = fresh;
    aboutDlg.showModal();
  }

  function setVersion(v) {
    if (!v || v === cfg.version) return;
    cfg.version = v;
    if (footer) footer.querySelector(".sh-copy").textContent = copyright();
  }

  // ---------------------------------------------------------------- ready-made menus
  function themeItem() {
    return { id: "shell.theme", label: "shell.theme", submenu: THEMES.map((x) => ({
      id: `shell.theme.${x}`, label: `shell.theme.${x}`, radio: true, checked: x === theme, onClick: () => setTheme(x) })) };
  }
  function langItem() {
    return { id: "shell.lang", label: "shell.lang", submenu: Object.entries(LANGS).map(([x, name]) => ({
      id: `shell.lang.${x}`, label: name, radio: true, checked: x === lang, onClick: () => setLang(x) })) };
  }
  function helpMenu(extra) {
    const L = cfg.links, its = [];
    if (L.docs) its.push({ id: "shell.help.docs", label: "shell.help.docs", href: L.docs });
    if (L.issues) its.push({ id: "shell.help.issue", label: "shell.help.issue", href: L.issues });
    if (extra) its.push(...extra);
    if (its.length) its.push({ separator: true });
    const v = cfg.vendor, contact = v && v.name ? vendorContact(v) : null;
    if (contact) its.push({ id: "shell.help.custom", label: "vendor.help.custom", href: contact });
    its.push({ id: "shell.help.about", label: "shell.help.about", onClick: openAbout });
    return { id: "help", label: "shell.help", items: its };
  }

  // ---------------------------------------------------------------- toast / status
  function toast(msg, kind) {
    if (!toastBox) { toastBox = h("div", { class: "sh-toasts", "aria-live": "polite" }); doc.body.append(toastBox); }
    const el = h("div", { class: `sh-toast sh-toast-${kind || "info"}`, role: kind === "error" ? "alert" : "status" }, String(msg));
    const kill = () => el.remove();
    el.addEventListener("click", kill);
    toastBox.append(el);
    while (toastBox.children.length > 4) toastBox.firstChild.remove();
    setTimeout(kill, kind === "error" ? 7000 : 4000);
    return el;
  }
  function setStatus(html) {
    const el = header && header.querySelector(".sh-status");
    if (el) el.innerHTML = html;
    return el;
  }

  // ---------------------------------------------------------------- init
  function init(options) {
    // Help menu helpers read cfg.links, so merge links before menus are built by the caller.
    cfg = Object.assign(cfg, options || {});
    cfg.links = cfg.links || {};
    const menus = typeof cfg.menus === "function" ? cfg.menus() : cfg.menus;
    cfg.menus = menus || [];

    const burger = h("button", { type: "button", class: "sh-burger", "aria-expanded": "false", "aria-controls": "sh-nav",
      "aria-label": t("shell.menu") }, h("span"), h("span"));
    header = h("header", { class: "sh-header" },
      h("div", { class: "sh-headin" },
        h("a", { class: "sh-brand", href: cfg.links.home || "./", "aria-label": cfg.product }, brand()),
        h("nav", { class: "sh-nav", id: "sh-nav", "aria-label": t("shell.menu") }, renderMenus()),
        h("div", { class: "sh-status" }),
        burger));
    burger.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = !header.classList.contains("nav-open");
      closeMenus();
      setNav(open);
    });
    footer = renderFooter();

    const body = doc.body;
    body.prepend(header);
    const content = body.querySelector(".sh-body");
    if (content) content.after(footer); else body.append(footer);

    // Outside click closes menus and the mobile nav (status widgets in the header count as "outside").
    doc.addEventListener("click", (e) => { if (!e.target.closest(".sh-menubar, .sh-burger")) closeMenus(null, true); });
    doc.addEventListener("keydown", onKey);
    const onMq = () => closeMenus(null, true);
    if (mqMobile.addEventListener) mqMobile.addEventListener("change", onMq);
    applyI18n(doc);
    return header;
  }

  global.Shell = {
    init, t, addStrings, applyI18n, updateItem, setStatus, setVersion, toast,
    version: COMMON_VERSION, vendors: {},
    themeItem, langItem, setLang, helpMenu, openAbout, setTheme, getTheme: () => theme, effectiveTheme,
    closeMenus: () => closeMenus(null, true),
    get lang() { return lang; },
  };
})(window);
