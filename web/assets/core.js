/* Shared: API, icons, header/footer, toast, modal, form helper */
(function () {
  var S = window.SITE;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var esc = function (t) {
    return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var money = function (n) { return "$" + Number(n).toFixed(2); };

  /* ---------- API ---------- */
  function api(method, path, body) {
    return fetch(path, {
      method: method, credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) { var e = new Error(d.error || "Something went wrong"); e.status = r.status; throw e; }
        return d;
      });
    });
  }
  var meCache = null;
  function me(force) {
    if (meCache && !force) return meCache;
    meCache = api("GET", "/api/me").then(function (d) { return d.user; }).catch(function () { return null; });
    return meCache;
  }

  /* ---------- icons (original glyphs, "app icon" tile) ---------- */
  var G = {
    play: '<path d="M8 5v14l11-7z" fill="#fff" stroke="none"/>',
    tv: '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8"/>',
    music: '<path d="M9 18V6l10-2v12"/><circle cx="7" cy="18" r="2.5"/><circle cx="17" cy="16" r="2.5"/>',
    shield: '<path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
    spark: '<path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/>',
    pencil: '<path d="M4 20l1-4L16 5a2 2 0 013 3L8 19z"/>',
    briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2M3 13h18"/>',
    cloud: '<path d="M7 18a4 4 0 010-8 5 5 0 019.5-1A4.5 4.5 0 0117 18z"/>',
    game: '<rect x="3" y="8" width="18" height="10" rx="5"/><path d="M8 11v4M6 13h4"/><circle cx="16" cy="12" r="1"/><circle cx="18" cy="14" r="1"/>',
    book: '<path d="M5 4h10a3 3 0 013 3v13H8a3 3 0 01-3-3z"/><path d="M5 17a3 3 0 013-3h10"/>',
    bolt: '<path d="M13 2L5 14h6l-1 8 8-12h-6z"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>',
    star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>'
  };
  function icon(p, px) {
    px = px || 56;
    var st = 'style="--c:' + esc(p.color || "#7c3aed") + ";width:" + px + "px;height:" + px + 'px"';
    if (p.image) return '<span class="tile img" ' + st + '><img src="' + esc(p.image) + '" alt="" loading="lazy"></span>';
    if (p.glyph === "mono" && p.name) {
      var ch = esc(String(p.name).trim().charAt(0).toUpperCase());
      return '<span class="tile" ' + st + '><b class="mono-ch" style="font-size:' + Math.round(px * 0.5) + 'px">' + ch + "</b></span>";
    }
    var g = G[p.glyph] || G.star;
    return '<span class="tile" ' + st + '><svg viewBox="0 0 24 24" width="' + Math.round(px * 0.52) + '" height="' + Math.round(px * 0.52) +
      '" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + g + "</svg></span>";
  }

  /* ---------- toast / modal ---------- */
  function toast(msg, bad) {
    var t = document.createElement("div");
    t.className = "toast" + (bad ? " bad" : "");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.classList.add("show"); }, 10);
    setTimeout(function () { t.classList.remove("show"); setTimeout(function () { t.remove(); }, 300); }, 3500);
  }
  function modal(html, opts) {
    var o = document.createElement("div");
    o.className = "overlay";
    o.innerHTML = '<div class="modal' + (opts && opts.wide ? " wide" : "") + '" role="dialog" aria-modal="true"><button class="x" aria-label="Close">×</button>' + html + "</div>";
    document.body.appendChild(o);
    document.body.style.overflow = "hidden";
    var close = function () { o.remove(); document.body.style.overflow = ""; };
    o.addEventListener("mousedown", function (e) { if (e.target === o) close(); });
    $(".x", o).onclick = close;
    return { el: $(".modal", o), close: close };
  }
  function copy(text) {
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () { toast("Copied"); },
      function () { toast("Could not copy. Please select and copy manually", true); });
  }
  function busy(btn, fn) {
    btn.disabled = true;
    var old = btn.textContent;
    return Promise.resolve().then(fn).catch(function (e) { toast(e.message, true); }).then(function (r) { btn.disabled = false; btn.textContent = old; return r; });
  }

  /* ---------- generic form modal (admin) ---------- */
  function formModal(title, fields, values, onSave) {
    values = values || {};
    var html = "<h3>" + esc(title) + '</h3><form class="form">';
    fields.forEach(function (f) {
      var v = values[f.k] != null ? values[f.k] : (f.def != null ? f.def : "");
      html += '<label class="fld"><span>' + esc(f.label) + "</span>";
      if (f.type === "textarea") html += '<textarea name="' + f.k + '" rows="' + (f.rows || 4) + '">' + esc(v) + "</textarea>";
      else if (f.type === "select") html += '<select name="' + f.k + '">' + f.options.map(function (o) {
        return '<option value="' + esc(o[0]) + '"' + (String(o[0]) === String(v) ? " selected" : "") + ">" + esc(o[1]) + "</option>";
      }).join("") + "</select>";
      else if (f.type === "checkbox") html += '<input type="checkbox" name="' + f.k + '"' + (Number(v) || v === true ? " checked" : "") + ">";
      else if (f.type === "image") html += '<input type="hidden" name="' + f.k + '" value="' + esc(v) + '"><input type="file" accept="image/png,image/jpeg,image/webp" data-up="' + f.k + '"><small class="muted upmsg">' + (v ? "Image set: " + esc(v) : "No image (the icon glyph will be used)") + "</small>";
      else html += '<input name="' + f.k + '" type="' + (f.type || "text") + '" value="' + esc(v) + '"' + (f.step ? ' step="' + f.step + '"' : "") + (f.ph ? ' placeholder="' + esc(f.ph) + '"' : "") + (f.type === "password" ? ' autocomplete="new-password"' : "") + ">";
      if (f.help) html += "<small class=\"muted\">" + esc(f.help) + "</small>";
      html += "</label>";
    });
    html += '<button class="btn btn-primary" type="submit">Save</button></form>';
    var m = modal(html);
    var form = $("form", m.el);
    form.querySelectorAll("[data-up]").forEach(function (inp) {
      var holder = inp.parentNode, msg = $(".upmsg", holder);
      var prev = document.createElement("div"); prev.className = "upprev"; holder.appendChild(prev);
      var show = function (url) {
        prev.innerHTML = url ? icon({ image: url }, 72) + ' <button type="button" class="btn btn-ghost btn-sm">Remove</button>' : "";
        msg.textContent = url ? "App icon set" : "No image (the icon glyph will be used)";
        var rm = $("button", prev); if (rm) rm.onclick = function () { form.elements[inp.dataset.up].value = ""; show(""); };
      };
      show(form.elements[inp.dataset.up].value);
      inp.onchange = function () {
        var file = inp.files[0]; if (!file) return;
        var url = "", img = new Image();
        img.onerror = function () { toast("Could not read this image. Use a PNG, JPG or WebP file.", true); };
        img.onload = function () {
          /* centre-crop to a square and scale to 256x256 so any logo fits the app-icon tile */
          var side = Math.min(img.naturalWidth, img.naturalHeight), cv = document.createElement("canvas");
          cv.width = cv.height = 256;
          cv.getContext("2d").drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, 256, 256);
          api("POST", "/api/admin/upload", { data: cv.toDataURL("image/png").split(",")[1] }).then(function (d) {
            form.elements[inp.dataset.up].value = d.url; show(d.url);
          }).catch(function (e) { toast(e.message, true); });
        };
        var fr = new FileReader();
        fr.onerror = img.onerror;
        fr.onload = function () { img.src = fr.result; };
        fr.readAsDataURL(file);
      };
    });
    form.onsubmit = function (e) {
      e.preventDefault();
      var out = {};
      fields.forEach(function (f) {
        var el = form.elements[f.k];
        out[f.k] = f.type === "checkbox" ? (el.checked ? 1 : 0) : el.value;
      });
      busy($("button[type=submit]", form), function () {
        return Promise.resolve(onSave(out)).then(function () { m.close(); });
      });
    };
    return m;
  }

  /* ---------- header / footer ---------- */
  var path = location.pathname.split("/").pop() || "index.html";
  var nav = [["plans.html", "Shop"], ["how-it-works.html", "How it works"], ["faq.html", "FAQ"], ["support.html", "Support"]];
  function renderHeader(user) {
    var h = '<header class="nav"><div class="wrap"><a class="logo" href="index.html"><img src="assets/logo.svg" alt="" width="34" height="34"><span id="brand-name">' + esc(S.BRAND) + "</span></a>" +
      '<button class="burger" aria-label="Menu" id="burger">☰</button><nav id="menu">' +
      nav.map(function (l) { return '<a href="' + l[0] + '"' + (path === l[0] ? ' class="on"' : "") + ">" + l[1] + "</a>"; }).join("") +
      (user ? ((user.is_admin ? '<a href="admin.html">Admin</a>' : "") + '<a class="btn btn-primary btn-sm" href="account.html">' + money(user.balance) + " · Account</a>")
        : '<a class="btn btn-primary btn-sm" href="account.html">Login / Sign up</a>') + '<button class="theme-toggle" id="themeToggle" type="button" aria-label="Toggle dark mode" title="Light / dark">☾</button></nav></div></header>';
    var el = $("#site-header"); if (el) el.outerHTML = h;
    var tt = $("#themeToggle"); if (tt) tt.onclick = function () {
      var dark = document.documentElement.getAttribute("data-theme") === "dark";
      if (dark) document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", "dark");
      try { localStorage.setItem("vs_theme", dark ? "light" : "dark"); } catch (e) {}
    };
    var b = $("#burger"); if (b) b.onclick = function () { $("#menu").classList.toggle("open"); };
  }
  function renderFooter() {
    var f = '<footer><div class="wrap"><div class="fgrid"><div><a class="logo" href="index.html"><img src="assets/logo.svg" alt="" width="34" height="34">' + esc(S.BRAND) + "</a>" +
      '<p class="muted" style="margin-top:12px;max-width:280px">' + esc(S.TAGLINE) + ".</p></div>" +
      '<div><h4>Shop</h4><a href="plans.html">All plans</a><a href="how-it-works.html">How it works</a><a href="account.html#wallet">Wallet &amp; top-up</a><a href="account.html#referral">Referral</a></div>' +
      '<div><h4>Help</h4><a href="faq.html">FAQ</a><a href="support.html">Support</a><a href="delivery.html">Delivery</a></div>' +
      '<div><h4>Legal</h4><a href="refund-policy.html">Refund policy</a><a href="terms.html">Terms</a><a href="privacy.html">Privacy</a></div></div>' +
      '<div class="legal">© ' + new Date().getFullYear() + " " + esc(S.BRAND) + ". We are not affiliated with any brand. All names and trademarks belong to their respective owners and are used as text only.</div></div></footer>";
    var el = $("#site-footer"); if (el) el.outerHTML = f;
  }
  var ready = me().then(function (u) { renderHeader(u); renderFooter(); return u; });
  api("GET", "/api/settings").then(function (s) {
    if (s.store_name) { S.BRAND = s.store_name; document.querySelectorAll(".logo").forEach(function (l) { var n = l.querySelector("#brand-name"); if (n) n.textContent = s.store_name; }); }
  }).catch(function () {});

  window.Core = { $: $, esc: esc, money: money, api: api, me: me, icon: icon, glyphs: Object.keys(G).concat(["mono"]), toast: toast, modal: modal, copy: copy, busy: busy, formModal: formModal, ready: ready };
})();
