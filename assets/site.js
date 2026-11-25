(function () {
  var S = window.SITE;
  var PALETTE = ["#7c3aed", "#2563eb", "#0d9488", "#f97316", "#ec4899", "#16a34a", "#d97706"];
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var esc = function (t) {
    return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  /* ---------- header / footer ---------- */
  var path = location.pathname.split("/").pop() || "index.html";
  var links = [
    ["plans.html", "Plans"], ["how-it-works.html", "How it works"], ["wallet.html", "Wallet"],
    ["faq.html", "FAQ"], ["support.html", "Support"]
  ];
  var support = S.SUPPORT_URL || "support.html";
  var header = '<header class="nav"><div class="wrap">' +
    '<a class="logo" href="index.html"><i>V</i>' + esc(S.BRAND) + '</a>' +
    '<button class="burger" aria-label="Menu" id="burger">☰</button>' +
    '<nav id="menu">' + links.map(function (l) {
      return '<a href="' + l[0] + '"' + (path === l[0] ? ' class="on"' : "") + ">" + l[1] + "</a>";
    }).join("") + '<a class="btn btn-primary btn-sm" href="plans.html">Browse plans</a></nav></div></header>';

  var footer = '<footer><div class="wrap"><div class="fgrid">' +
    '<div><a class="logo" href="index.html"><i>V</i>' + esc(S.BRAND) + '</a>' +
    '<p class="muted" style="margin-top:12px;max-width:280px">' + esc(S.TAGLINE) + '. Payment aur delivery Telegram bot par hoti hai.</p></div>' +
    '<div><h4>Shop</h4><a href="plans.html">All plans</a><a href="how-it-works.html">How it works</a><a href="wallet.html">Wallet &amp; top-up</a><a href="referral.html">Referral</a></div>' +
    '<div><h4>Help</h4><a href="faq.html">FAQ</a><a href="support.html">Support</a><a href="delivery.html">Delivery</a></div>' +
    '<div><h4>Legal</h4><a href="refund-policy.html">Refund policy</a><a href="terms.html">Terms</a><a href="privacy.html">Privacy</a></div>' +
    '</div><div class="legal">© ' + new Date().getFullYear() + ' ' + esc(S.BRAND) +
    '. Hum kisi bhi brand ke saath affiliated nahi hain; saare naam aur trademarks unke maalikon ke hain. Sirf naam text mein use hote hain.</div></div></footer>';

  var h = $("#site-header"), f = $("#site-footer");
  if (h) h.outerHTML = header;
  if (f) f.outerHTML = footer;
  var b = $("#burger");
  if (b) b.onclick = function () { $("#menu").classList.toggle("open"); };

  /* support / bot buttons */
  document.querySelectorAll("[data-support]").forEach(function (a) { a.href = support; });
  document.querySelectorAll("[data-bot]").forEach(function (a) {
    a.href = S.BOT_USERNAME ? "https://t.me/" + S.BOT_USERNAME : "plans.html";
  });

  /* ---------- catalog ---------- */
  var DEMO = { demo: true, categories: [
    { id: 1, name: "Streaming", emoji: "🎬", from_price: "4.80", plans: [
      { product_id: 1, variation_id: 1, product: "Sample Video Plan", plan: "1 Month", price: "4.80", stock: 3, min_qty: 1, max_qty: 3, prebook: false, buy_url: "#" },
      { product_id: 1, variation_id: 2, product: "Sample Video Plan", plan: "1 Year", price: "39.00", stock: 0, min_qty: 1, max_qty: 1, prebook: true, buy_url: "#" }] },
    { id: 2, name: "Music", emoji: "🎧", from_price: "9.60", plans: [
      { product_id: 2, variation_id: 3, product: "Sample Music Plan", plan: "3 Month", price: "9.60", stock: 12, min_qty: 1, max_qty: 5, prebook: false, buy_url: "#" }] },
    { id: 3, name: "AI Tools", emoji: "🤖", from_price: "12.00", plans: [
      { product_id: 3, variation_id: 4, product: "Sample AI Plan", plan: "1 Month", price: "12.00", stock: 0, min_qty: 1, max_qty: 1, prebook: false, buy_url: "#" }] },
    { id: 4, name: "VPN", emoji: "🔒", from_price: "3.20", plans: [
      { product_id: 4, variation_id: 5, product: "Sample VPN Plan", plan: "1 Year", price: "3.20", stock: 40, min_qty: 1, max_qty: 10, prebook: false, buy_url: "#" }] }
  ] };

  function loadCatalog() {
    if (!S.API_BASE) {
      return Promise.resolve(S.DEMO_WHEN_NO_API ? DEMO : { categories: [], error: "API_BASE set nahi hai" });
    }
    return fetch(S.API_BASE.replace(/\/$/, "") + S.CATALOG_PATH, { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { try { sessionStorage.setItem("catalog", JSON.stringify(d)); } catch (e) {} return d; })
      .catch(function () {
        try { var c = sessionStorage.getItem("catalog"); if (c) { var d = JSON.parse(c); d.stale = true; return d; } } catch (e) {}
        return { categories: [], error: "Catalog abhi load nahi ho paaya." };
      });
  }

  function color(i) { return PALETTE[i % PALETTE.length]; }
  function badge(p) {
    if (p.stock > 0) return p.stock <= 5
      ? '<span class="badge b-low">Only ' + p.stock + " left</span>"
      : '<span class="badge b-in">In stock</span>';
    return p.prebook ? '<span class="badge b-pre">Pre-order</span>' : '<span class="badge b-out">Sold out</span>';
  }
  function planCard(p, cat, ci) {
    var can = p.stock > 0 || p.prebook;
    var label = p.stock > 0 ? "Buy on Telegram" : "Pre-order";
    return '<article class="card plan" style="--a:' + color(ci) + '">' +
      '<div class="cat-name">' + esc(cat.emoji || "") + " " + esc(cat.name) + "</div>" +
      '<div><div class="pname">' + esc(p.product) + '</div><div class="pplan">' + esc(p.plan) + "</div></div>" +
      '<div class="price">' + S.CURRENCY + esc(p.price) + "<small>USD</small></div>" +
      '<div class="row">' + badge(p) +
      '<a class="btn btn-primary btn-sm' + (can ? "" : " disabled") + '" href="' + esc(p.buy_url || "#") + '" target="_blank" rel="noopener">' + label + "</a></div></article>";
  }
  function catCard(c, ci) {
    return '<a class="card cat" style="--a:' + color(ci) + '" href="plans.html?cat=' + c.id + '">' +
      '<div class="ico">' + esc(c.emoji || "✨") + "</div><h3>" + esc(c.name) + "</h3>" +
      "<small>" + c.plans.length + " plan" + (c.plans.length === 1 ? "" : "s") + "</small>" +
      '<div class="from">From ' + S.CURRENCY + esc(c.from_price) + "</div></a>";
  }
  function notice(d) {
    var n = "";
    if (d.demo) n = "Ye sirf DEMO data hai (layout dekhne ke liye). <code>assets/config.js</code> mein API_BASE set karo.";
    else if (d.stale) n = "Live catalog abhi nahi mil raha; purana saved data dikh raha hai.";
    return n ? '<div class="notice">' + n + "</div>" : "";
  }

  /* home: categories + popular */
  var catBox = $("#cats");
  if (catBox) {
    catBox.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
    loadCatalog().then(function (d) {
      var n = $("#home-notice"); if (n) n.innerHTML = notice(d);
      catBox.innerHTML = d.categories.length ? d.categories.map(catCard).join("") :
        '<div class="empty">' + esc(d.error || "Abhi koi category nahi.") + "</div>";
      var dots = $("#dots");
      if (dots) dots.innerHTML = d.categories.slice(0, 7).map(function (c, i) {
        return '<span class="chip" style="--a:' + color(i) + '">' + esc(c.emoji || "") + " " + esc(c.name) + "</span>";
      }).join("");
      var pop = $("#popular");
      if (pop) {
        var all = [];
        d.categories.forEach(function (c, ci) { c.plans.forEach(function (p) { if (p.stock > 0) all.push([p, c, ci]); }); });
        pop.innerHTML = all.slice(0, 6).map(function (x) { return planCard(x[0], x[1], x[2]); }).join("") ||
          '<div class="empty">Abhi in-stock plans nahi hain.</div>';
      }
    });
  }

  /* plans page */
  var list = $("#plans");
  if (list) {
    var state = { data: null, cat: new URLSearchParams(location.search).get("cat") || "all", q: "" };
    var render = function () {
      var d = state.data; if (!d) return;
      $("#plans-notice").innerHTML = notice(d);
      $("#tabs").innerHTML = '<button class="tab' + (state.cat === "all" ? " on" : "") + '" data-c="all">All</button>' +
        d.categories.map(function (c) {
          return '<button class="tab' + (String(c.id) === state.cat ? " on" : "") + '" data-c="' + c.id + '">' + esc(c.emoji || "") + " " + esc(c.name) + "</button>";
        }).join("");
      var out = [];
      d.categories.forEach(function (c, ci) {
        if (state.cat !== "all" && String(c.id) !== state.cat) return;
        c.plans.forEach(function (p) {
          var hay = (p.product + " " + p.plan + " " + c.name).toLowerCase();
          if (!state.q || hay.indexOf(state.q) > -1) out.push(planCard(p, c, ci));
        });
      });
      list.innerHTML = out.join("") || '<div class="empty">' + esc(d.error || "Kuch nahi mila. Doosra search try karo.") + "</div>";
    };
    list.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
    var refresh = function () { loadCatalog().then(function (d) { state.data = d; render(); }); };
    refresh();
    if (S.API_BASE) setInterval(refresh, S.REFRESH_MS);
    $("#tabs").addEventListener("click", function (e) {
      var t = e.target.closest("[data-c]"); if (!t) return; state.cat = t.dataset.c; render();
    });
    $("#q").addEventListener("input", function (e) { state.q = e.target.value.trim().toLowerCase(); render(); });
  }
})();
