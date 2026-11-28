/* Home + Shop pages: catalog, product modal, checkout */
(function () {
  var C = window.Core, $ = C.$, esc = C.esc, money = C.money;
  var data = null;

  function fromPrice(p) { return Math.min.apply(null, p.variations.map(function (v) { return v.price; })); }
  function state(p) {
    if (p.variations.some(function (v) { return v.stock > 0; })) return ["b-in", "In stock"];
    if (p.variations.some(function (v) { return v.prebook; })) return ["b-pre", "Pre-order"];
    return ["b-out", "Sold out"];
  }
  function vBadge(v) {
    if (v.stock > 0) return v.stock <= 5 ? '<span class="badge b-low">Only ' + v.stock + " left</span>" : '<span class="badge b-in">In stock</span>';
    return v.prebook ? '<span class="badge b-pre">Pre-order</span>' : '<span class="badge b-out">Sold out</span>';
  }
  function tags(p) {
    var t = [];
    if (p.mode === "auto" && p.variations.some(function (v) { return v.stock > 0; })) t.push('<span class="tag t-fast">⚡ Instant</span>');
    if (p.variations.some(function (v) { return v.needs_email; })) t.push('<span class="tag">✉ Email activation</span>');
    if (p.variations.length > 1) t.push('<span class="tag">' + p.variations.length + " plans</span>");
    return t.join("");
  }
  function prodCard(p, cat) {
    var st = state(p), dead = st[1] === "Sold out";
    var media = p.image ? '<img src="' + esc(p.image) + '" alt="" loading="lazy">' : C.icon(p, 84);
    return '<button class="card pcard" data-p="' + p.id + '"><div class="pmedia' + (p.image ? " has-img" : "") + '">' + media + "</div>" +
      '<div class="tags">' + tags(p) + "</div>" +
      '<div class="pmeta"><span class="stock ' + st[0] + '"><i></i>' + st[1] + "</span><span>" + esc(cat.name) + "</span></div>" +
      '<div class="pname">' + esc(p.name) + "</div>" +
      '<div class="pdesc">' + esc((p.description || "").replace(/\s+/g, " ").slice(0, 140)) + "</div>" +
      '<div class="pfoot"><div class="pprice"><small>' + (p.variations.length > 1 ? "From" : "Your price") + "</small><b>" + money(fromPrice(p)) + '</b></div><span class="btn ' + (dead ? "btn-ghost" : "btn-primary") + ' btn-sm">' + (dead ? "View details" : st[1] === "Pre-order" ? "Pre-order" : "Buy now") + "</span></div></button>";
  }
  function catCard(c, ci) {
    var n = c.products.length;
    var mn = Math.min.apply(null, c.products.map(fromPrice));
    return '<a class="card cat" href="plans.html?cat=' + c.id + '"><div class="ico">' + esc(String(c.name || "?").trim().charAt(0).toUpperCase()) +
      "</div><h3>" + esc(c.name) + "</h3><small>" + n + " product" + (n === 1 ? "" : "s") + '</small><div class="from">From ' + money(mn) + "</div></a>";
  }
  function find(pid) {
    for (var i = 0; i < data.length; i++) for (var j = 0; j < data[i].products.length; j++)
      if (data[i].products[j].id === pid) return [data[i].products[j], data[i]];
  }

  /* ---------- product modal + checkout ---------- */
  function openProduct(pid) {
    var f = find(pid); if (!f) return;
    var p = f[0], cat = f[1], sel = null, pct = 0;
    var vs = p.variations;
    var m = C.modal('<div class="mhead">' + C.icon(p, 64) + '<div><div class="cat-name">' + esc(cat.name) + "</div><h3>" + esc(p.name) + "</h3></div></div>" +
      (p.description ? '<div class="desc">' + esc(p.description) + "</div>" : "") +
      '<div class="vlist">' + vs.map(function (v) {
        var dead = v.stock === 0 && !v.prebook;
        return '<label class="vrow' + (dead ? " dead" : "") + '"><input type="radio" name="v" value="' + v.id + '"' + (dead ? " disabled" : "") + "><span class=\"vn\">" + esc(v.name) +
          "</span>" + vBadge(v) + '<b class="vp">' + money(v.price) + "</b></label>";
      }).join("") + "</div>" +
      '<div id="co" class="co" hidden><div class="qrow"><span>Quantity</span><div class="stepper"><button type="button" id="qm">−</button><input id="qty" type="number" value="1" min="1"><button type="button" id="qp">+</button></div></div>' +
      '<div class="qrow" id="emrow" hidden><input id="semail" class="search" type="email" placeholder="Email to activate the subscription on" autocomplete="email"></div><div class="qrow"><input id="coupon" class="search" placeholder="Coupon code (optional)"><button class="btn btn-ghost btn-sm" id="capply" type="button">Apply</button></div>' +
      '<div class="note" id="note"></div><div class="total"><span>Total</span><b id="tot">$0.00</b></div>' +
      '<button class="btn btn-primary btn-lg" id="buy" style="width:100%"></button></div>');
    var el = m.el;
    function recalc() {
      if (!sel) return;
      var q = Math.max(sel.min_qty, Math.min(sel.max_qty, parseInt($("#qty", el).value, 10) || 1));
      $("#qty", el).value = q;
      var gross = Math.round(sel.price * 100) * q, disc = Math.floor(gross * pct / 100);
      $("#tot", el).textContent = money((gross - disc) / 100);
      $("#note", el).textContent = pct ? pct + "% coupon discount applied" : (sel.prebook ? "Currently sold out. Pre-order now and it will be delivered automatically when stock arrives, usually within a few hours." : "");
      $("#emrow", el).hidden = !sel.needs_email;
      if (sel.needs_email) { $("#qty", el).value = 1; }
      $("#buy", el).textContent = sel.prebook ? "Pre-order now" : "Buy now";
    }
    el.addEventListener("change", function (e) {
      if (e.target.name !== "v") return;
      sel = vs.filter(function (v) { return String(v.id) === e.target.value; })[0];
      $("#co", el).hidden = false;
      $("#qty", el).min = sel.min_qty; $("#qty", el).max = sel.max_qty;
      $("#qty", el).value = sel.min_qty; pct = 0;
      recalc();
    });
    $("#qm", el).onclick = function () { $("#qty", el).value = (parseInt($("#qty", el).value, 10) || 1) - 1; recalc(); };
    $("#qp", el).onclick = function () { $("#qty", el).value = (parseInt($("#qty", el).value, 10) || 1) + 1; recalc(); };
    $("#qty", el).onchange = recalc;
    $("#capply", el).onclick = function () {
      var b = this;
      C.me().then(function (u) {
        if (!u) { C.toast("Please sign in to use a coupon", true); return; }
        return C.busy(b, function () {
          return C.api("POST", "/api/coupon/check", { code: $("#coupon", el).value }).then(function (d) {
            pct = d.percent; recalc(); if (!pct) C.toast("Enter a coupon code");
          });
        });
      });
    };
    $("#buy", el).onclick = function () {
      var b = this;
      C.me().then(function (u) {
        if (!u) { location.href = "account.html?next=" + encodeURIComponent(location.pathname.split("/").pop() + location.search); return; }
        return C.busy(b, function () {
          return C.api("POST", "/api/buy", { variation_id: sel.id, qty: parseInt($("#qty", el).value, 10), coupon: $("#coupon", el).value, email: sel.needs_email ? $("#semail", el).value : "" })
            .then(function (d) { done(m, d.order); });
        });
      });
    };
  }
  function done(m, o) {
    var body;
    if (o.status === "completed") body = "<p>Your order has been delivered. The details are below and also saved under Account → Orders:</p><pre class=\"deliv\">" + esc(o.delivery_text) + '</pre><button class="btn btn-ghost btn-sm" id="cp">Copy</button>';
    else if (o.preorder) body = "<p>Your pre-order is placed. It will be delivered automatically when stock arrives. You can track it under Account → Orders.</p>";
    else body = "<p>Your order has been received. Our team will deliver it shortly, and the details will appear under Account → Orders.</p>";
    m.el.innerHTML = '<button class="x" aria-label="Close">×</button><h3>Order #' + o.id + " ✓</h3><p class=\"muted\">" + esc(o.product_name) + " · " + esc(o.plan_name) + " × " + o.qty + " · " + money(o.total) + "</p>" + body +
      '<p style="margin-top:16px"><a class="btn btn-primary btn-sm" href="account.html#orders">My orders</a></p>';
    $(".x", m.el).onclick = m.close;
    var cp = $("#cp", m.el); if (cp) cp.onclick = function () { C.copy(o.delivery_text); };
  }

  /* ---------- pages ---------- */
  function load() {
    return C.api("GET", "/api/catalog").then(function (d) { data = d.categories; return data; });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-p]");
    if (b && data) openProduct(parseInt(b.dataset.p, 10));
  });

  var cats = $("#cats");
  if (cats) {
    cats.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
    load().then(function (d) {
      cats.innerHTML = d.length ? d.map(catCard).join("") : '<div class="empty">The catalog is being prepared. Plans will appear here soon.</div>';
      var dots = $("#dots");
      if (dots) dots.innerHTML = d.slice(0, 7).map(function (c) { return '<span class="chip">' + esc(c.name) + "</span>"; }).join("");
      var pop = $("#popular");
      if (pop) {
        var all = [];
        d.forEach(function (c, ci) { c.products.forEach(function (p) { if (state(p)[1] === "In stock") all.push(prodCard(p, c)); }); });
        pop.innerHTML = all.slice(0, 6).join("") || '<div class="empty">No plans are in stock right now.</div>';
      }
    }).catch(function () { cats.innerHTML = '<div class="empty">Could not load the catalog. Please try again shortly.</div>'; });
  }

  var list = $("#plans");
  if (list) {
    var ls = function (k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) {} return null; };
    var base = { cat: new URLSearchParams(location.search).get("cat") || "all", q: "", sort: ls("vs_sort") || "featured", stock: false, instant: false, pre: false, min: "", max: "", view: ls("vs_view") || "grid" };
    var st = Object.assign({}, base);
    var qs = function (id) { return document.getElementById(id); };
    var sync = function () {
      qs("sort").value = st.sort; qs("pmin").value = st.min; qs("pmax").value = st.max; qs("q").value = st.q;
      qs("f-stock").checked = st.stock; qs("f-instant").checked = st.instant; qs("f-pre").checked = st.pre;
      document.querySelectorAll(".vtoggle button").forEach(function (b) { b.classList.toggle("on", b.dataset.v === st.view); });
      list.classList.toggle("as-list", st.view === "list");
    };
    var pass = function (p, c, skipCat) {
      if (!skipCat && st.cat !== "all" && String(c.id) !== st.cat) return false;
      var s = state(p)[1], lo = fromPrice(p);
      if (st.stock && s !== "In stock") return false;
      if (st.instant && !(p.mode === "auto" && s === "In stock")) return false;
      if (st.pre && s !== "Pre-order") return false;
      if (st.min !== "" && lo < parseFloat(st.min)) return false;
      if (st.max !== "" && lo > parseFloat(st.max)) return false;
      return !st.q || (p.name + " " + c.name + " " + p.variations.map(function (v) { return v.name; }).join(" ")).toLowerCase().indexOf(st.q) > -1;
    };
    var render = function () {
      var counts = {}, total = 0;
      data.forEach(function (c) { counts[c.id] = c.products.filter(function (p) { return pass(p, c, true); }).length; total += counts[c.id]; });
      var row = function (id, name, n) { return '<button class="crow' + (String(id) === st.cat ? " on" : "") + '" data-c="' + id + '"><span>' + esc(name) + "</span><em>" + n + "</em></button>"; };
      qs("cats-list").innerHTML = row("all", "All products", total) + data.map(function (c) { return row(c.id, c.name, counts[c.id]); }).join("");
      qs("tabs").innerHTML = '<button class="tab' + (st.cat === "all" ? " on" : "") + '" data-c="all">All</button>' + data.map(function (c) {
        return '<button class="tab' + (String(c.id) === st.cat ? " on" : "") + '" data-c="' + c.id + '">' + esc(c.name) + "</button>";
      }).join("");
      var out = [];
      data.forEach(function (c) { c.products.forEach(function (p) { if (pass(p, c)) out.push([p, c]); }); });
      if (st.sort === "low") out.sort(function (x, y) { return fromPrice(x[0]) - fromPrice(y[0]); });
      else if (st.sort === "high") out.sort(function (x, y) { return fromPrice(y[0]) - fromPrice(x[0]); });
      else if (st.sort === "name") out.sort(function (x, y) { return x[0].name.localeCompare(y[0].name); });
      qs("count").textContent = out.length + (out.length === 1 ? " product" : " products");
      var ch = [];
      if (st.q) ch.push(["q", "“" + st.q + "”"]); if (st.stock) ch.push(["stock", "In stock"]); if (st.instant) ch.push(["instant", "Instant"]);
      if (st.pre) ch.push(["pre", "Pre-order"]); if (st.min !== "") ch.push(["min", "≥ $" + st.min]); if (st.max !== "") ch.push(["max", "≤ $" + st.max]);
      qs("achips").innerHTML = ch.map(function (x) { return '<button class="achip" data-x="' + x[0] + '">' + esc(x[1]) + " ×</button>"; }).join("");
      list.innerHTML = out.map(function (x) { return prodCard(x[0], x[1]); }).join("") ||
        '<div class="empty">No products match these filters.<br><button class="btn btn-ghost btn-sm" data-reset="1" style="margin-top:12px">Reset filters</button></div>';
      sync();
    };
    list.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
    var refresh = function () { return load().then(render); };
    refresh().catch(function () { list.innerHTML = '<div class="empty">Could not load the catalog.</div>'; });
    setInterval(function () { if (!document.querySelector(".overlay") && document.visibilityState === "visible") refresh().catch(function () {}); }, 30000);
    var pick = function (e) { var t = e.target.closest("[data-c]"); if (t) { st.cat = t.dataset.c; render(); } };
    qs("tabs").addEventListener("click", pick); qs("cats-list").addEventListener("click", pick);
    qs("sort").addEventListener("change", function (e) { st.sort = e.target.value; ls("vs_sort", st.sort); render(); });
    qs("q").addEventListener("input", function (e) { st.q = e.target.value.trim().toLowerCase(); render(); });
    [["pmin", "min"], ["pmax", "max"]].forEach(function (x) { qs(x[0]).addEventListener("input", function (e) { st[x[1]] = e.target.value; render(); }); });
    [["f-stock", "stock"], ["f-instant", "instant"], ["f-pre", "pre"]].forEach(function (x) { qs(x[0]).addEventListener("change", function (e) { st[x[1]] = e.target.checked; render(); }); });
    document.querySelector(".vtoggle").addEventListener("click", function (e) { var b = e.target.closest("[data-v]"); if (b) { st.view = b.dataset.v; ls("vs_view", st.view); sync(); } });
    qs("ftoggle").addEventListener("click", function () { qs("filters").classList.toggle("open"); });
    var reset = function () { var keep = { sort: st.sort, view: st.view }; st = Object.assign({}, base, keep, { cat: "all" }); render(); };
    qs("reset").addEventListener("click", reset);
    document.addEventListener("click", function (e) {
      if (e.target.closest("[data-reset]")) reset();
      var a = e.target.closest("[data-x]"); if (a) { var k = a.dataset.x; st[k] = (k === "stock" || k === "instant" || k === "pre") ? false : ""; render(); }
    });
  }
})();
