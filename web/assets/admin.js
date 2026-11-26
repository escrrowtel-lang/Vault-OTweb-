/* Admin panel */
(function () {
  var C = window.Core, $ = C.$, esc = C.esc, money = C.money;
  var root = $("#adm");
  var TABS = [["dash", "Dashboard"], ["deposits", "Deposits"], ["orders", "Orders"], ["catalog", "Catalog & inventory"], ["users", "Users"], ["coupons", "Coupons"], ["audit", "Activity"], ["settings", "Settings"]];
  var dt = function (ts) { return ts ? new Date(ts * 1000).toLocaleString() : ""; };
  var ok = function (m) { C.toast(m || "Saved"); };
  var P = function (path, body) { return C.api("POST", path, body); };

  function shell() {
    root.innerHTML = '<div class="tabs" id="at" style="margin-bottom:22px">' + TABS.map(function (t) { return '<button class="tab" data-t="' + t[0] + '">' + t[1] + "</button>"; }).join("") + '</div><div id="pane"></div>';
    $("#at").onclick = function (e) { var t = e.target.closest("[data-t]"); if (t) location.hash = t.dataset.t; };
    var show = function () {
      var t = (location.hash || "#dash").slice(1);
      if (!views[t]) t = "dash";
      document.querySelectorAll("#at .tab").forEach(function (b) { b.classList.toggle("on", b.dataset.t === t); });
      $("#pane").innerHTML = '<div class="skeleton"></div>';
      views[t]($("#pane")).catch(function (e) { $("#pane").innerHTML = '<div class="empty">' + esc(e.message) + "</div>"; });
    };
    window.addEventListener("hashchange", show);
    window.reloadView = show;
    show();
  }
  var reload = function () { window.reloadView(); };

  var views = {};

  /* ---------- dashboard ---------- */
  views.dash = function (el) {
    return C.api("GET", "/api/admin/stats").then(function (s) {
      var box = function (l, v, hint) { return '<div class="card stat"><small>' + l + "</small><b>" + v + "</b>" + (hint ? "<span class=\"muted small\">" + hint + "</span>" : "") + "</div>"; };
      el.innerHTML = '<div class="grid g-3">' + box("Pending deposits", s.pending_deposits, "Deposits tab mein approve karo") + box("Processing orders", s.processing_orders, "Manual delivery baaki") +
        box("Pre-orders waiting", s.preorders_waiting, "Inventory add karte hi deliver") + box("Users", s.users) + box("Orders", s.orders) + box("Revenue", money(s.revenue)) + box("Wallet balances (liability)", money(s.wallet_liability)) + "</div>";
    });
  };

  /* ---------- deposits ---------- */
  var NAMES = { upi: "UPI", binance_id: "Binance ID", usdt_bep20: "USDT BEP20" };
  views.deposits = function (el) {
    var f = sessionStorage.getItem("depf") || "pending";
    return C.api("GET", "/api/admin/deposits?status=" + f).then(function (d) {
      el.innerHTML = '<div class="bar"><select id="fs" class="search" style="max-width:200px">' + ["pending", "approved", "rejected", ""].map(function (s) { return '<option value="' + s + '"' + (s === f ? " selected" : "") + ">" + (s || "all") + "</option>"; }).join("") + "</select></div>" +
        (d.deposits.length ? '<div class="tbl card"><table><tr><th>#</th><th>Date</th><th>User</th><th>Method</th><th>Amount</th><th>Reference</th><th>Status</th><th></th></tr>' + d.deposits.map(function (x) {
          return "<tr><td>" + x.id + "</td><td>" + dt(x.created_at) + "</td><td>" + esc(x.email) + "</td><td>" + NAMES[x.method] + "</td><td>" + money(x.amount) + (x.method === "upi" ? "<br><small>₹" + x.inr_expected + " expected</small>" : "") +
            '</td><td class="mono">' + esc(x.reference) + '</td><td><span class="badge ' + (x.status === "approved" ? "b-in" : x.status === "pending" ? "b-low" : "b-out") + '">' + x.status + "</span></td><td>" +
            (x.status === "pending" ? '<button class="btn btn-primary btn-sm" data-a="approve" data-id="' + x.id + '">Approve</button> <button class="btn btn-ghost btn-sm" data-a="reject" data-id="' + x.id + '">Reject</button>' : "") + "</td></tr>";
        }).join("") + "</table></div>" : '<div class="empty">Kuch nahi.</div>') +
        '<p class="muted small" style="margin-top:12px">Approve karne se pehle apne UPI/Binance app mein dekho ki UTR/ID par sahi amount asal mein aaya hai. USDT deposits blockchain se apne aap verify hote hain.</p>';
      $("#fs", el).onchange = function () { sessionStorage.setItem("depf", this.value); reload(); };
      el.onclick = function (e) {
        var b = e.target.closest("[data-a]"); if (!b) return;
        var id = parseInt(b.dataset.id, 10), act = b.dataset.a;
        if (act === "approve") { if (!confirm("Pakka approve? Wallet mein paisa add ho jayega.")) return; P("/api/admin/deposit/decide", { id: id, action: act }).then(function () { ok("Approved"); reload(); }).catch(function (x) { C.toast(x.message, true); }); }
        else C.formModal("Reject deposit #" + id, [{ k: "note", label: "Reason (user ko dikhega)" }], {}, function (v) { return P("/api/admin/deposit/decide", { id: id, action: "reject", note: v.note }).then(function () { ok("Rejected"); reload(); }); });
      };
    });
  };

  /* ---------- orders ---------- */
  views.orders = function (el) {
    var f = sessionStorage.getItem("ordf") || "";
    return C.api("GET", "/api/admin/orders?status=" + f).then(function (d) {
      el.innerHTML = '<div class="bar"><select id="fs" class="search" style="max-width:200px">' + ["", "processing", "pending", "completed", "refunded", "cancelled"].map(function (s) { return '<option value="' + s + '"' + (s === f ? " selected" : "") + ">" + (s || "all") + "</option>"; }).join("") + "</select></div>" +
        (d.orders.length ? '<div class="tbl card"><table><tr><th>#</th><th>Date</th><th>User</th><th>Item</th><th>Total</th><th>Status</th><th></th></tr>' + d.orders.map(function (o) {
          return "<tr><td>" + o.id + "</td><td>" + dt(o.created_at) + "</td><td>" + esc(o.email) + "</td><td>" + esc(o.product_name) + " · " + esc(o.plan_name) + " × " + o.qty + (o.preorder ? " <small>(pre-order)</small>" : "") + "</td><td>" + money(o.total) +
            '</td><td><span class="badge b-low">' + o.status + "</span></td><td>" +
            (o.status === "processing" ? '<button class="btn btn-primary btn-sm" data-a="deliver" data-id="' + o.id + '">Deliver</button> ' : "") +
            (o.status === "completed" && o.delivery_text ? '<button class="btn btn-ghost btn-sm" data-a="view" data-id="' + o.id + '">View</button> ' : "") +
            (["refunded", "cancelled"].indexOf(o.status) < 0 ? '<button class="btn btn-ghost btn-sm" data-a="refund" data-id="' + o.id + '">Refund</button>' : "") + "</td></tr>";
        }).join("") + "</table></div>" : '<div class="empty">Koi order nahi.</div>');
      $("#fs", el).onchange = function () { sessionStorage.setItem("ordf", this.value); reload(); };
      el.onclick = function (e) {
        var b = e.target.closest("[data-a]"); if (!b) return;
        var id = parseInt(b.dataset.id, 10), o = d.orders.filter(function (x) { return x.id === id; })[0];
        if (b.dataset.a === "deliver") C.formModal("Deliver order #" + id, [{ k: "text", label: "Delivery details (user ko dikhenge)", type: "textarea", rows: 6 }], {}, function (v) { return P("/api/admin/order/deliver", { id: id, text: v.text }).then(function () { ok("Delivered"); reload(); }); });
        else if (b.dataset.a === "view") C.modal("<h3>Order #" + id + '</h3><pre class="deliv">' + esc(o.delivery_text) + "</pre>");
        else if (confirm("Order #" + id + " refund karna hai? " + money(o.total) + " user ke wallet mein wapas jayega.")) P("/api/admin/order/refund", { id: id }).then(function () { ok("Refunded"); reload(); }).catch(function (x) { C.toast(x.message, true); });
      };
    });
  };

  /* ---------- catalog ---------- */
  views.catalog = function (el) {
    return C.api("GET", "/api/admin/catalog").then(function (d) {
      var cats = d.categories;
      var h = '<div class="bar"><button class="btn btn-primary btn-sm" data-a="newcat">+ Category</button></div>';
      cats.forEach(function (c) {
        h += '<div class="card" style="margin-bottom:18px"><div class="orow"><h3>' + esc(c.emoji) + " " + esc(c.name) + (c.active ? "" : ' <span class="badge b-out">hidden</span>') + '</h3><div><button class="btn btn-ghost btn-sm" data-a="editcat" data-id="' + c.id + '">Edit</button> <button class="btn btn-ghost btn-sm" data-a="newprod" data-id="' + c.id + '">+ Product</button></div></div>';
        c.products.forEach(function (p) {
          h += '<div class="aprod"><div class="orow">' + '<div class="mhead" style="margin:0">' + C.icon(p, 44) + "<div><b>" + esc(p.name) + '</b> <span class="badge ' + (p.mode === "auto" ? "b-in" : "b-pre") + '">' + p.mode + "</span>" + (p.quick_drop ? ' <span class="badge b-low">quick drop</span>' : "") + (p.active ? "" : ' <span class="badge b-out">hidden</span>') + "</div></div>" +
            '<div><button class="btn btn-ghost btn-sm" data-a="editprod" data-id="' + p.id + '">Edit</button> <button class="btn btn-ghost btn-sm" data-a="newvar" data-id="' + p.id + '">+ Plan</button></div></div>';
          if (p.variations.length) h += '<div class="tbl"><table><tr><th>Plan</th><th>Price</th><th>Qty</th><th>' + (p.mode === "auto" ? "Inventory" : "Stock") + "</th><th></th></tr>" + p.variations.map(function (v) {
            return "<tr><td>" + esc(v.name) + (v.active ? "" : " <small>(hidden)</small>") + "</td><td>" + money(v.price) + "</td><td>" + v.min_qty + "–" + v.max_qty + "</td><td>" + v.available + '</td><td><button class="btn btn-ghost btn-sm" data-a="editvar" data-id="' + v.id + '">Edit</button> ' +
              (p.mode === "auto" ? '<button class="btn btn-primary btn-sm" data-a="inv" data-id="' + v.id + '">Inventory</button>' : "") + "</td></tr>";
          }).join("") + "</table></div>";
          h += "</div>";
        });
        h += "</div>";
      });
      if (!cats.length) h += '<div class="empty">Pehle ek category banao, phir product aur plan.</div>';
      el.innerHTML = h;
      var findProd = function (id) { for (var i = 0; i < cats.length; i++) for (var j = 0; j < cats[i].products.length; j++) if (cats[i].products[j].id === id) return cats[i].products[j]; };
      var findVar = function (id) { for (var i = 0; i < cats.length; i++) for (var j = 0; j < cats[i].products.length; j++) for (var k = 0; k < cats[i].products[j].variations.length; k++) if (cats[i].products[j].variations[k].id === id) return [cats[i].products[j].variations[k], cats[i].products[j]]; };
      var catF = [{ k: "name", label: "Naam" }, { k: "emoji", label: "Emoji" }, { k: "position", label: "Order (chhota pehle)", type: "number", def: 0 }, { k: "active", label: "Visible", type: "checkbox", def: 1 }];
      var prodF = [
        { k: "category_id", label: "Category", type: "select", options: cats.map(function (c) { return [c.id, c.name]; }) },
        { k: "name", label: "Product naam" }, { k: "description", label: "Description (activation steps etc.)", type: "textarea", rows: 5 },
        { k: "mode", label: "Delivery mode", type: "select", options: [["auto", "AUTO (inventory se turant)"], ["manual", "MANUAL (admin deliver karta hai)"]] },
        { k: "glyph", label: "Icon glyph", type: "select", options: C.glyphs.map(function (g) { return [g, g]; }) },
        { k: "color", label: "Icon colour", type: "color", def: "#7c3aed" },
        { k: "image", label: "Apni icon image (optional, PNG/JPG/WEBP)", type: "image", help: "Sirf wahi image upload karo jiska use karne ka aapko haq hai." },
        { k: "quick_drop", label: "Quick drop (sold out par apne aap band)", type: "checkbox" },
        { k: "position", label: "Order", type: "number", def: 0 }, { k: "active", label: "Visible", type: "checkbox", def: 1 }];
      var varF = function (mode) {
        return [{ k: "name", label: "Plan naam (1 Month, 1 Year…)" }, { k: "price", label: "Price (USD)", type: "number", step: "0.01" },
          { k: "min_qty", label: "Min qty", type: "number", def: 1 }, { k: "max_qty", label: "Max qty", type: "number", def: 1 }]
          .concat(mode === "manual" ? [{ k: "stock", label: "Stock (number)", type: "number", def: 0 }] : [])
          .concat([{ k: "position", label: "Order", type: "number", def: 0 }, { k: "active", label: "Visible", type: "checkbox", def: 1 }]);
      };
      el.onclick = function (e) {
        var b = e.target.closest("[data-a]"); if (!b) return;
        var id = parseInt(b.dataset.id, 10), a = b.dataset.a;
        var save = function (path, extra) { return function (v) { for (var k in extra) v[k] = extra[k]; return P(path, v).then(function () { ok(); reload(); }); }; };
        if (a === "newcat") C.formModal("Nayi category", catF, {}, save("/api/admin/category", {}));
        else if (a === "editcat") C.formModal("Category edit", catF, cats.filter(function (c) { return c.id === id; })[0], save("/api/admin/category", { id: id }));
        else if (a === "newprod") C.formModal("Naya product", prodF, { category_id: id }, save("/api/admin/product", {}));
        else if (a === "editprod") C.formModal("Product edit", prodF, findProd(id), save("/api/admin/product", { id: id }));
        else if (a === "newvar") C.formModal("Naya plan", varF(findProd(id).mode), {}, save("/api/admin/variation", { product_id: id }));
        else if (a === "editvar") { var fv = findVar(id); C.formModal("Plan edit", varF(fv[1].mode), fv[0], save("/api/admin/variation", { id: id, product_id: fv[1].id })); }
        else if (a === "inv") inventory(id, findVar(id)[0]);
      };
    });
  };

  function inventory(vid, v) {
    var m = C.modal('<h3>Inventory · ' + esc(v.name) + '</h3><form class="form" id="af"><label class="fld"><span>Naye items (ek line = ek item; account details, link ya code)</span><textarea name="text" rows="6" placeholder="email:password"></textarea></label><button class="btn btn-primary" type="submit">Add items</button></form><div id="il" style="margin-top:16px"></div>', { wide: true });
    var load = function () {
      C.api("GET", "/api/admin/inventory?variation_id=" + vid).then(function (d) {
        $("#il", m.el).innerHTML = d.items.length ? '<div class="tbl"><table><tr><th>#</th><th>Content</th><th>Status</th><th></th></tr>' + d.items.map(function (i) {
          return "<tr><td>" + i.id + '</td><td class="mono wrapc">' + esc(i.content) + '</td><td><span class="badge ' + (i.status === "available" ? "b-in" : "b-out") + '">' + i.status + (i.order_id ? " #" + i.order_id : "") + "</span></td><td>" + (i.status === "available" ? '<button class="btn btn-ghost btn-sm" data-del="' + i.id + '">Delete</button>' : "") + "</td></tr>";
        }).join("") + "</table></div>" : '<p class="muted">Abhi koi item nahi.</p>';
      });
    };
    load();
    $("#af", m.el).onsubmit = function (e) {
      e.preventDefault();
      C.busy($("button", e.target), function () {
        return P("/api/admin/inventory", { variation_id: vid, text: e.target.elements.text.value }).then(function (r) {
          C.toast(r.added + " add hue, " + r.skipped_duplicates + " duplicate skip" + (r.preorders_fulfilled ? ", " + r.preorders_fulfilled + " pre-order deliver hue" : ""));
          e.target.elements.text.value = ""; load();
        });
      });
    };
    m.el.addEventListener("click", function (e) {
      var b = e.target.closest("[data-del]"); if (!b) return;
      P("/api/admin/inventory/delete", { id: parseInt(b.dataset.del, 10) }).then(load).catch(function (x) { C.toast(x.message, true); });
    });
    var x = $(".x", m.el), old = x.onclick; x.onclick = function () { old(); reload(); };
  }

  /* ---------- users ---------- */
  views.users = function (el) {
    return C.api("GET", "/api/admin/users").then(function (d) {
      el.innerHTML = '<div class="tbl card"><table><tr><th>#</th><th>Email</th><th>Balance</th><th>Joined</th><th></th></tr>' + d.users.map(function (u) {
        return "<tr><td>" + u.id + "</td><td>" + esc(u.email) + (u.is_admin ? ' <span class="badge b-pre">admin</span>' : "") + (u.blocked ? ' <span class="badge b-out">blocked</span>' : "") + "</td><td>" + money(u.balance) + "</td><td>" + dt(u.created_at) +
          '</td><td><button class="btn btn-ghost btn-sm" data-a="adj" data-id="' + u.id + '">Balance adjust</button> <button class="btn btn-ghost btn-sm" data-a="rst" data-id="' + u.id + '">Reset link</button> <button class="btn btn-ghost btn-sm" data-a="blk" data-id="' + u.id + '" data-b="' + (u.blocked ? 0 : 1) + '">' + (u.blocked ? "Unblock" : "Block") + "</button></td></tr>";
      }).join("") + "</table></div>";
      el.onclick = function (e) {
        var b = e.target.closest("[data-a]"); if (!b) return;
        var id = parseInt(b.dataset.id, 10);
        if (b.dataset.a === "adj") C.formModal("Balance adjust", [{ k: "amount", label: "Amount USD (+ add, − kam)", type: "number", step: "0.01" }, { k: "reason", label: "Reason", def: "adjust" }], {}, function (v) { return P("/api/admin/user/adjust", { id: id, amount: v.amount, reason: v.reason }).then(function () { ok(); reload(); }); });
        else if (b.dataset.a === "rst") P("/api/admin/user/reset-link", { id: id }).then(function (d) { C.formModal("Password reset link", [{ k: "l", label: d.email + " ko ye link bhejo (" + d.valid_minutes + " min, sirf ek baar)" }], { l: location.origin + d.path }, function () { return Promise.resolve(); }); }).catch(function (x) { C.toast(x.message, true); });
        else P("/api/admin/user/block", { id: id, blocked: parseInt(b.dataset.b, 10) }).then(function () { ok(); reload(); }).catch(function (x) { C.toast(x.message, true); });
      };
    });
  };

  /* ---------- activity log ---------- */
  views.audit = function (el) {
    return C.api("GET", "/api/admin/audit").then(function (d) {
      el.innerHTML = d.audit.length ? '<div class="tbl card"><table><tr><th>Time</th><th>Admin</th><th>Action</th><th>Detail</th></tr>' + d.audit.map(function (a) {
        return "<tr><td>" + dt(a.created_at) + "</td><td>" + esc(a.admin || "") + '</td><td class="mono">' + esc(a.action) + "</td><td>" + esc(a.detail) + "</td></tr>";
      }).join("") + "</table></div>" : '<div class="empty">Abhi koi activity nahi.</div>';
    });
  };

  /* ---------- coupons ---------- */
  views.coupons = function (el) {
    return C.api("GET", "/api/admin/coupons").then(function (d) {
      el.innerHTML = '<div class="bar"><button class="btn btn-primary btn-sm" id="nc">+ Coupon</button></div>' + (d.coupons.length ? '<div class="tbl card"><table><tr><th>Code</th><th>Discount</th><th>Used</th><th>Status</th><th></th></tr>' + d.coupons.map(function (c) {
        return "<tr><td class=\"mono\">" + esc(c.code) + "</td><td>" + c.percent + "%</td><td>" + c.uses + "/" + c.max_uses + '</td><td><span class="badge ' + (c.active ? "b-in" : "b-out") + '">' + (c.active ? "active" : "off") + '</span></td><td><button class="btn btn-ghost btn-sm" data-id="' + c.id + '" data-c="' + c.code + '" data-p="' + c.percent + '" data-on="' + (c.active ? 0 : 1) + '">' + (c.active ? "Disable" : "Enable") + "</button></td></tr>";
      }).join("") + "</table></div>" : '<div class="empty">Koi coupon nahi.</div>') + '<p class="muted small" style="margin-top:12px">Har user ek coupon sirf ek baar use kar sakta hai.</p>';
      $("#nc", el).onclick = function () { C.formModal("Naya coupon", [{ k: "code", label: "Code" }, { k: "percent", label: "Discount %", type: "number", def: 10 }, { k: "max_uses", label: "Kitne log use kar sakte hain", type: "number", def: 1 }], {}, function (v) { return P("/api/admin/coupon", v).then(function () { ok(); reload(); }); }); };
      el.onclick = function (e) { var b = e.target.closest("[data-id]"); if (b) P("/api/admin/coupon", { id: +b.dataset.id, code: b.dataset.c, percent: +b.dataset.p, active: +b.dataset.on }).then(function () { ok(); reload(); }); };
    });
  };

  /* ---------- settings ---------- */
  views.settings = function (el) {
    return C.api("GET", "/api/admin/settings").then(function (r) {
      var s = r.settings;
      var F = [
        { k: "store_name", label: "Store naam" },
        { k: "methods_enabled", label: "Enabled payment methods", help: "Comma se: upi,binance_id,usdt_bep20" },
        { k: "upi_id", label: "UPI ID (jahan user pay karega)" }, { k: "upi_name", label: "UPI account ka naam" },
        { k: "usd_inr_rate", label: "USD → INR rate", help: "UPI deposits ke liye INR amount isi se banta hai" },
        { k: "upi_auto", label: "UPI auto-verify (email se)", help: "1 = on, 0 = off. Server par IMAP_HOST/IMAP_USER/IMAP_PASS set hona chahiye" },
        { k: "upi_alert_senders", label: "Bank alert sender(s)", help: "Comma se, jaise alerts@yourbank.com ya @yourbank.com. Sirf yahi emails maane jaayenge" },
        { k: "upi_require_dkim", label: "Sender DKIM check", help: "1 = sirf wahi email jo DKIM pass kare (recommended)" },
        { k: "binance_id", label: "Binance ID (Pay ID)" },
        { k: "binance_auto", label: "Binance auto-verify (API se)", help: "1 = on. Server par BINANCE_API_KEY/SECRET (read-only) set hona chahiye" },
        { k: "usdt_address", label: "USDT BEP20 wallet address (0x…)", help: "Sirf apna address. Private key kabhi yahan mat daalna." },
        { k: "usdt_contract", label: "USDT token contract (BSC)", help: "Default BSC-USD (USDT). Jab tak pata na ho mat badlo." },
        { k: "bsc_rpc", label: "BSC RPC URL (https://)" }, { k: "confirmations", label: "Required confirmations", type: "number" },
        { k: "min_deposit", label: "Min deposit (USD)" }, { k: "max_deposit", label: "Max deposit (USD)" },
        { k: "referral_reward", label: "Referral reward (USD)" },
        { k: "support_text", label: "Support text (support page par dikhega)", type: "textarea", rows: 3 }, { k: "support_url", label: "Support link (https://… optional)" },
        { k: "site_url", label: "Site URL (password-reset email ke link ke liye)", help: "Jaise https://yourdomain.com. SMTP server par set ho tabhi email jaayega." }];
      el.innerHTML = '<div class="card"><div class="orow"><h3>Settings</h3><button class="btn btn-primary btn-sm" id="es">Edit</button></div><div class="tbl"><table>' + F.map(function (f) { return "<tr><td>" + esc(f.label) + '</td><td class="mono wrapc">' + (esc(s[f.k]) || '<span class="muted">—</span>') + "</td></tr>"; }).join("") + "</table></div></div>";
      $("#es", el).onclick = function () { C.formModal("Settings", F, s, function (v) { return P("/api/admin/settings", v).then(function () { ok(); reload(); }); }); };
    });
  };

  C.me().then(function (u) {
    if (!u) { location.href = "account.html?next=admin.html"; return; }
    if (!u.is_admin) { root.innerHTML = '<div class="empty">Ye page sirf admin ke liye hai.</div>'; return; }
    shell();
  });
})();
