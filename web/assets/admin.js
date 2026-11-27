/* Admin panel */
(function () {
  var C = window.Core, $ = C.$, esc = C.esc, money = C.money;
  var root = $("#adm");
  var TABS = [["dash", "Dashboard"], ["deposits", "Deposits"], ["orders", "Orders"], ["catalog", "Catalog & inventory"], ["users", "Users"], ["coupons", "Coupons"], ["suppliers", "Supplier API"], ["audit", "Activity"], ["settings", "Settings"]];
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
      el.innerHTML = '<div class="grid g-3">' + box("Pending deposits", s.pending_deposits, "Approve them in the Deposits tab") + box("Processing orders", s.processing_orders, "Awaiting manual delivery") +
        box("Pre-orders waiting", s.preorders_waiting, "Delivered as soon as inventory is added") + box("Users", s.users) + box("Orders", s.orders) + box("Revenue", money(s.revenue)) + box("Wallet balances (liability)", money(s.wallet_liability)) + "</div>";
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
        }).join("") + "</table></div>" : '<div class="empty">Nothing to show.</div>') +
        '<p class="muted small" style="margin-top:12px">Before approving manually, confirm in your UPI or Binance app that the correct amount arrived for that UTR/ID. USDT deposits are verified on the blockchain automatically, and UPI/Binance can be verified automatically when enabled in Settings.</p>';
      $("#fs", el).onchange = function () { sessionStorage.setItem("depf", this.value); reload(); };
      el.onclick = function (e) {
        var b = e.target.closest("[data-a]"); if (!b) return;
        var id = parseInt(b.dataset.id, 10), act = b.dataset.a;
        if (act === "approve") { if (!confirm("Approve this deposit? The amount will be added to the user's wallet.")) return; P("/api/admin/deposit/decide", { id: id, action: act }).then(function () { ok("Approved"); reload(); }).catch(function (x) { C.toast(x.message, true); }); }
        else C.formModal("Reject deposit #" + id, [{ k: "note", label: "Reason (shown to the user)" }], {}, function (v) { return P("/api/admin/deposit/decide", { id: id, action: "reject", note: v.note }).then(function () { ok("Rejected"); reload(); }); });
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
            '</td><td><span class="badge b-low">' + o.status + "</span>" + (o.supplier ? '<div class="small" style="margin-top:4px">→ ' + esc(o.supplier.name) + ": " + supChip(o.supplier).replace(/<div.*$/, "") + "</div>" : "") + "</td><td>" +
            (o.status === "processing" ? '<button class="btn btn-primary btn-sm" data-a="deliver" data-id="' + o.id + '">Deliver</button> ' : "") +
            (o.status === "completed" && o.delivery_text ? '<button class="btn btn-ghost btn-sm" data-a="view" data-id="' + o.id + '">View</button> ' : "") +
            (["refunded", "cancelled"].indexOf(o.status) < 0 ? '<button class="btn btn-ghost btn-sm" data-a="refund" data-id="' + o.id + '">Refund</button>' : "") + "</td></tr>";
        }).join("") + "</table></div>" : '<div class="empty">No orders.</div>');
      $("#fs", el).onchange = function () { sessionStorage.setItem("ordf", this.value); reload(); };
      el.onclick = function (e) {
        var b = e.target.closest("[data-a]"); if (!b) return;
        var id = parseInt(b.dataset.id, 10), o = d.orders.filter(function (x) { return x.id === id; })[0];
        if (b.dataset.a === "deliver") C.formModal("Deliver order #" + id, [{ k: "text", label: "Delivery details (shown to the user)", type: "textarea", rows: 6 }], {}, function (v) { return P("/api/admin/order/deliver", { id: id, text: v.text }).then(function () { ok("Delivered"); reload(); }); });
        else if (b.dataset.a === "view") C.modal("<h3>Order #" + id + '</h3><pre class="deliv">' + esc(o.delivery_text) + "</pre>");
        else if (confirm("Order #" + id + ": refund it? " + money(o.total) + " will be returned to the user's wallet.")) P("/api/admin/order/refund", { id: id }).then(function () { ok("Refunded"); reload(); }).catch(function (x) { C.toast(x.message, true); });
      };
    });
  };

  /* ---------- catalog ---------- */
  views.catalog = function (el) {
    return C.api("GET", "/api/admin/catalog").then(function (d) {
      var cats = d.categories;
      var h = '<div class="bar"><button class="btn btn-primary btn-sm" data-a="newcat">+ Category</button></div>';
      cats.forEach(function (c) {
        h += '<div class="card" style="margin-bottom:18px"><div class="orow"><h3>' + esc(c.name) + (c.active ? "" : ' <span class="badge b-out">hidden</span>') + '</h3><div><button class="btn btn-ghost btn-sm" data-a="editcat" data-id="' + c.id + '">Edit</button> <button class="btn btn-ghost btn-sm" data-a="newprod" data-id="' + c.id + '">+ Product</button></div></div>';
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
      if (!cats.length) h += '<div class="empty">Create a category first, then add products and plans.</div>';
      el.innerHTML = h;
      var findProd = function (id) { for (var i = 0; i < cats.length; i++) for (var j = 0; j < cats[i].products.length; j++) if (cats[i].products[j].id === id) return cats[i].products[j]; };
      var findVar = function (id) { for (var i = 0; i < cats.length; i++) for (var j = 0; j < cats[i].products.length; j++) for (var k = 0; k < cats[i].products[j].variations.length; k++) if (cats[i].products[j].variations[k].id === id) return [cats[i].products[j].variations[k], cats[i].products[j]]; };
      var catF = [{ k: "name", label: "Name" }, { k: "position", label: "Sort order (lowest first)", type: "number", def: 0 }, { k: "active", label: "Visible", type: "checkbox", def: 1 }];
      var prodF = [
        { k: "category_id", label: "Category", type: "select", options: cats.map(function (c) { return [c.id, c.name]; }) },
        { k: "name", label: "Product name" }, { k: "description", label: "Description (activation steps etc.)", type: "textarea", rows: 5 },
        { k: "mode", label: "Delivery mode", type: "select", options: [["auto", "AUTO (instant, from inventory)"], ["manual", "MANUAL (delivered by an admin)"]] },
        { k: "glyph", label: "Icon glyph", type: "select", options: C.glyphs.map(function (g) { return [g, g]; }) },
        { k: "color", label: "Icon colour", type: "color", def: "#0ea5e9" },
        { k: "image", label: "Custom icon image (optional, PNG/JPG/WEBP)", type: "image", help: "Only upload images you have the right to use." },
        { k: "quick_drop", label: "Quick drop (hide automatically when sold out)", type: "checkbox" },
        { k: "position", label: "Sort order", type: "number", def: 0 }, { k: "active", label: "Visible", type: "checkbox", def: 1 }];
      var varF = function (mode) {
        return [{ k: "name", label: "Plan name (1 Month, 1 Year…)" }, { k: "price", label: "Price (USD)", type: "number", step: "0.01" },
          { k: "min_qty", label: "Min qty", type: "number", def: 1 }, { k: "max_qty", label: "Max qty", type: "number", def: 1 }]
          .concat(mode === "manual" ? [{ k: "stock", label: "Stock (number)", type: "number", def: 0 }] : [])
          .concat([{ k: "position", label: "Sort order", type: "number", def: 0 }, { k: "active", label: "Visible", type: "checkbox", def: 1 }]);
      };
      el.onclick = function (e) {
        var b = e.target.closest("[data-a]"); if (!b) return;
        var id = parseInt(b.dataset.id, 10), a = b.dataset.a;
        var save = function (path, extra) { return function (v) { for (var k in extra) v[k] = extra[k]; return P(path, v).then(function () { ok(); reload(); }); }; };
        if (a === "newcat") C.formModal("New category", catF, {}, save("/api/admin/category", {}));
        else if (a === "editcat") C.formModal("Edit category", catF, cats.filter(function (c) { return c.id === id; })[0], save("/api/admin/category", { id: id }));
        else if (a === "newprod") C.formModal("New product", prodF, { category_id: id }, save("/api/admin/product", {}));
        else if (a === "editprod") C.formModal("Edit product", prodF, findProd(id), save("/api/admin/product", { id: id }));
        else if (a === "newvar") C.formModal("New plan", varF(findProd(id).mode), {}, save("/api/admin/variation", { product_id: id }));
        else if (a === "editvar") { var fv = findVar(id); C.formModal("Edit plan", varF(fv[1].mode), fv[0], save("/api/admin/variation", { id: id, product_id: fv[1].id })); }
        else if (a === "inv") inventory(id, findVar(id)[0]);
      };
    });
  };

  function inventory(vid, v) {
    var m = C.modal('<h3>Inventory · ' + esc(v.name) + '</h3><form class="form" id="af"><label class="fld"><span>New items (one per line: account details, link or code)</span><textarea name="text" rows="6" placeholder="email:password"></textarea></label><button class="btn btn-primary" type="submit">Add items</button></form><div id="il" style="margin-top:16px"></div>', { wide: true });
    var load = function () {
      C.api("GET", "/api/admin/inventory?variation_id=" + vid).then(function (d) {
        $("#il", m.el).innerHTML = d.items.length ? '<div class="tbl"><table><tr><th>#</th><th>Content</th><th>Status</th><th></th></tr>' + d.items.map(function (i) {
          return "<tr><td>" + i.id + '</td><td class="mono wrapc">' + esc(i.content) + '</td><td><span class="badge ' + (i.status === "available" ? "b-in" : "b-out") + '">' + i.status + (i.order_id ? " #" + i.order_id : "") + "</span></td><td>" + (i.status === "available" ? '<button class="btn btn-ghost btn-sm" data-del="' + i.id + '">Delete</button>' : "") + "</td></tr>";
        }).join("") + "</table></div>" : '<p class="muted">No items yet.</p>';
      });
    };
    load();
    $("#af", m.el).onsubmit = function (e) {
      e.preventDefault();
      C.busy($("button", e.target), function () {
        return P("/api/admin/inventory", { variation_id: vid, text: e.target.elements.text.value }).then(function (r) {
          C.toast(r.added + " added, " + r.skipped_duplicates + " duplicates skipped" + (r.preorders_fulfilled ? ", " + r.preorders_fulfilled + " pre-orders delivered" : ""));
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
          '</td><td><button class="btn btn-ghost btn-sm" data-a="adj" data-id="' + u.id + '">Adjust balance</button> <button class="btn btn-ghost btn-sm" data-a="rst" data-id="' + u.id + '">Reset link</button> <button class="btn btn-ghost btn-sm" data-a="blk" data-id="' + u.id + '" data-b="' + (u.blocked ? 0 : 1) + '">' + (u.blocked ? "Unblock" : "Block") + "</button></td></tr>";
      }).join("") + "</table></div>";
      el.onclick = function (e) {
        var b = e.target.closest("[data-a]"); if (!b) return;
        var id = parseInt(b.dataset.id, 10);
        if (b.dataset.a === "adj") C.formModal("Adjust balance", [{ k: "amount", label: "Amount in USD (+ to add, − to deduct)", type: "number", step: "0.01" }, { k: "reason", label: "Reason", def: "adjust" }], {}, function (v) { return P("/api/admin/user/adjust", { id: id, amount: v.amount, reason: v.reason }).then(function () { ok(); reload(); }); });
        else if (b.dataset.a === "rst") P("/api/admin/user/reset-link", { id: id }).then(function (d) { C.formModal("Password reset link", [{ k: "l", label: "Send this link to " + d.email + " (valid for " + d.valid_minutes + " minutes, single use)" }], { l: location.origin + d.path }, function () { return Promise.resolve(); }); }).catch(function (x) { C.toast(x.message, true); });
        else P("/api/admin/user/block", { id: id, blocked: parseInt(b.dataset.b, 10) }).then(function () { ok(); reload(); }).catch(function (x) { C.toast(x.message, true); });
      };
    });
  };

  /* ---------- supplier API keys ---------- */
  function supChip(i) {
    var t = { queued: ["b-low", "Queued to send"], sent: ["b-low", "Sent · waiting for delivery"], delivered: ["b-in", "Delivered by supplier"], failed: ["b-out", "Failed · customer refunded"], attention: ["b-out", "Needs attention"] }[i.status] || ["b-low", i.status];
    return '<span class="badge ' + t[0] + '">' + t[1] + "</span>" + (i.error ? '<div class="muted small">' + esc(i.error) + "</div>" : "");
  }

  views.suppliers = function (el) {
    return C.api("GET", "/api/admin/suppliers").then(function (d) {
      var F = function (editing) {
        return [{ k: "name", label: "Supplier name" },
          { k: "kind", label: "API type", type: "select", options: [["prodseller", "ProdSeller (full order forwarding)"], ["generic", "Other (catalog import only)"]], def: "prodseller" },
          { k: "base_url", label: "API base URL", help: "ProdSeller: https://prodseller.com/v1 (do not add /balance here)" },
          { k: "auth_mode", label: "Authentication", type: "select", options: [["header", "API key in a header"], ["bearer", "Authorization: Bearer key"]] },
          { k: "auth_header", label: "Header name (header mode)", def: "X-API-Key" },
          { k: "api_key", label: editing ? "API key (leave blank to keep the saved key)" : "API key", type: "password", help: "Stored on the server only. It is never shown again after saving." },
          { k: "auto_sync", label: "Keep prices and stock in sync every 10 minutes", type: "checkbox", def: 1 },
          { k: "active", label: "Enabled", type: "checkbox", def: 1 }];
      };
      el.innerHTML = '<div class="bar"><button class="btn btn-primary btn-sm" id="ns">+ Add supplier</button></div>' +
        (d.suppliers.length ? '<div class="tbl card"><table><tr><th>Name</th><th>Base URL</th><th>Key</th><th>Status</th><th></th></tr>' + d.suppliers.map(function (x) {
          return "<tr><td>" + esc(x.name) + '</td><td class="mono wrapc">' + esc(x.base_url) + '</td><td class="mono">' + (x.has_key ? esc(x.key_hint) : '<span class="muted">none</span>') + '</td><td><span class="badge ' + (x.active ? "b-in" : "b-out") + '">' + (x.active ? "enabled" : "off") + '</span></td><td>' +
            '<button class="btn btn-primary btn-sm" data-a="imp" data-id="' + x.id + '">Import products</button> <button class="btn btn-ghost btn-sm" data-a="bal" data-id="' + x.id + '">Balance</button> <button class="btn btn-ghost btn-sm" data-a="test" data-id="' + x.id + '">Test</button> <button class="btn btn-ghost btn-sm" data-a="edit" data-id="' + x.id + '">Edit</button> <button class="btn btn-ghost btn-sm" data-a="del" data-id="' + x.id + '">Delete</button></td></tr>';
        }).join("") + "</table></div>" : '<div class="empty">No supplier connected yet.</div>') +
        '<p class="muted small" style="margin-top:12px">Add the API key given by your supplier. Use Test to check the connection: it sends one read-only GET request (for example /balance) and shows the response. Keys are stored on the server and are never displayed again.</p>';
      C.api("GET", "/api/admin/supplier-orders").then(function (so) {
        var h = '<h3 style="margin:22px 0 8px">Orders sent to suppliers</h3>' + (so.items.length ? '<div class="tbl card"><table><tr><th>Order</th><th>Item</th><th>Supplier</th><th>Status</th><th>Cost</th><th>Profit</th><th></th></tr>' + so.items.map(function (i) {
          return "<tr><td>#" + i.order_id + "</td><td>" + esc(i.product_name) + " · " + esc(i.plan_name) + "</td><td>" + esc(i.sname) + "</td><td>" + supChip(i) + "</td><td>" + money(i.cost) + "</td><td>" + money(i.total - i.cost) + "</td><td>" +
            (i.status === "attention" ? '<button class="btn btn-primary btn-sm" data-r="' + i.id + '">Retry</button>' : "") + "</td></tr>";
        }).join("") + "</table></div>" : '<div class="empty">No order has been sent to a supplier yet.</div>');
        var box = document.createElement("div"); box.innerHTML = h; el.appendChild(box);
        box.onclick = function (e) { var b = e.target.closest("[data-r]"); if (b) P("/api/admin/supplier-order/retry", { id: +b.dataset.r }).then(function () { ok("Sent again"); reload(); }); };
      });
      $("#ns", el).onclick = function () { C.formModal("Add supplier", F(false), {}, function (v) { return P("/api/admin/supplier", v).then(function () { ok(); reload(); }); }); };
      el.onclick = function (e) {
        var b = e.target.closest("[data-a]"); if (!b) return;
        var id = parseInt(b.dataset.id, 10), x = d.suppliers.filter(function (s) { return s.id === id; })[0];
        if (b.dataset.a === "edit") C.formModal("Edit supplier", F(true), x, function (v) { v.id = id; return P("/api/admin/supplier", v).then(function () { ok(); reload(); }); });
        else if (b.dataset.a === "del") { if (confirm("Delete " + x.name + " and its saved key?")) P("/api/admin/supplier/delete", { id: id }).then(function () { ok("Deleted"); reload(); }); }
        else if (b.dataset.a === "imp") importFlow(x);
        else if (b.dataset.a === "bal") P("/api/admin/supplier/balance", { id: id }).then(function (t) { C.toast("Supplier balance: $" + t.balance + (t.username ? " (" + t.username + ")" : "")); });
        else C.formModal("Test " + x.name, [{ k: "path", label: "Path to call (GET)", def: "/balance" }], { path: "/balance" }, function (v) {
          return P("/api/admin/supplier/test", { id: id, path: v.path }).then(function (t) {
            C.modal("<h3>Response " + t.status + (t.ok ? " ✓" : "") + '</h3>' + (t.status === 404 ? '<div class="note">This path does not exist on the supplier. Use <b>Import products</b> to search for the catalog path automatically, or check the base URL (many suppliers use a prefix such as /api/reseller).</div>' : "") + '<p class="muted small">' + esc(t.content_type) + (t.keys ? " · keys: " + esc(Array.isArray(t.keys) ? t.keys.join(", ") : t.keys) : "") + '</p><pre class="deliv">' + esc(t.preview) + "</pre>", { wide: true });
          });
        });
      };
    });
  };

  function importFlow(sup) {
    var m = C.modal('<h3>Import products · ' + esc(sup.name) + '</h3><p class="muted small">Step 1: find the catalog endpoint. Step 2: preview. Step 3: import. Imported products are created as manual-delivery plans; prices = supplier cost + your markup. Re-importing refreshes price and stock only.</p>' +
      '<div id="fd"><button class="btn btn-primary btn-sm" id="find">Find catalog automatically</button></div><form class="form" id="imf" style="margin-top:14px" hidden>' +
      '<label class="fld"><span>Catalog path</span><input name="path" required></label>' +
      '<label class="fld"><span>Markup % added to supplier price</span><input name="markup" type="number" min="0" max="1000" step="0.1" value="20"></label>' +
      '<label class="fld"><span>Supplier prices are in</span><select name="cents"><option value="0">Dollars (e.g. 4.99)</option><option value="1">Cents (e.g. 499)</option></select></label>' +
      '<button class="btn btn-ghost" type="submit">Preview</button></form><div id="pv" style="margin-top:14px"></div>', { wide: true });
    var form = $("#imf", m.el), run = function (dry) {
      var f = form.elements;
      return P("/api/admin/supplier/import", { id: sup.id, path: f.path.value.trim(), markup: parseFloat(f.markup.value) || 0, cents: f.cents.value === "1", dry: dry });
    };
    var show = function (path) { form.hidden = false; form.elements.path.value = path; };
    $("#find", m.el).onclick = function () {
      var b = this;
      C.busy(b, function () {
        return P("/api/admin/supplier/discover", { id: sup.id }).then(function (d) {
          if (!d.found.length) { $("#fd", m.el).innerHTML = '<div class="note">No catalog found automatically. Enter the products path from your supplier\'s documentation below.</div>'; show("/products"); return; }
          $("#fd", m.el).innerHTML = '<p>Found: ' + d.found.map(function (x) { return '<button type="button" class="btn btn-ghost btn-sm" data-path="' + esc(x.path) + '">' + esc(x.path) + " (" + x.count + " products)</button>"; }).join(" ") + "</p>";
          show(d.found[0].path);
          $("#fd", m.el).onclick = function (e) { var p = e.target.closest("[data-path]"); if (p) show(p.dataset.path); };
        });
      });
    };
    form.onsubmit = function (e) {
      e.preventDefault();
      C.busy($("button", form), function () {
        return run(true).then(function (d) {
          $("#pv", m.el).innerHTML = "<b>" + d.total + " products found.</b> Sample:" + '<div class="tbl"><table><tr><th>Category</th><th>Name</th><th>Cost</th><th>Your price</th><th>Stock</th></tr>' + d.preview.map(function (i) {
            return "<tr><td>" + esc(i.category) + "</td><td>" + esc(i.name) + "</td><td>" + money(i.cost / 100) + "</td><td>" + money(i.price / 100) + "</td><td>" + i.stock + (i.stock_note ? " <small>(" + esc(i.stock_note) + ")</small>" : "") + "</td></tr>";
          }).join("") + '</table></div><p class="muted small">Check that prices look right (dollars vs cents). Stock reported only as available/unavailable is set to 1 or 0; edit it afterwards if needed.</p><button class="btn btn-primary" id="go">Import all ' + d.total + " products</button>";
          $("#go", m.el).onclick = function () {
            C.busy(this, function () { return run(false).then(function (r) { C.toast(r.created + " added, " + r.updated + " updated, " + r.images + " images"); m.close(); reload(); }); });
          };
        });
      });
    };
  }

  /* ---------- activity log ---------- */
  views.audit = function (el) {
    return C.api("GET", "/api/admin/audit").then(function (d) {
      el.innerHTML = d.audit.length ? '<div class="tbl card"><table><tr><th>Time</th><th>Admin</th><th>Action</th><th>Detail</th></tr>' + d.audit.map(function (a) {
        return "<tr><td>" + dt(a.created_at) + "</td><td>" + esc(a.admin || "") + '</td><td class="mono">' + esc(a.action) + "</td><td>" + esc(a.detail) + "</td></tr>";
      }).join("") + "</table></div>" : '<div class="empty">No activity yet.</div>';
    });
  };

  /* ---------- coupons ---------- */
  views.coupons = function (el) {
    return C.api("GET", "/api/admin/coupons").then(function (d) {
      el.innerHTML = '<div class="bar"><button class="btn btn-primary btn-sm" id="nc">+ Coupon</button></div>' + (d.coupons.length ? '<div class="tbl card"><table><tr><th>Code</th><th>Discount</th><th>Used</th><th>Status</th><th></th></tr>' + d.coupons.map(function (c) {
        return "<tr><td class=\"mono\">" + esc(c.code) + "</td><td>" + c.percent + "%</td><td>" + c.uses + "/" + c.max_uses + '</td><td><span class="badge ' + (c.active ? "b-in" : "b-out") + '">' + (c.active ? "active" : "off") + '</span></td><td><button class="btn btn-ghost btn-sm" data-id="' + c.id + '" data-c="' + c.code + '" data-p="' + c.percent + '" data-on="' + (c.active ? 0 : 1) + '">' + (c.active ? "Disable" : "Enable") + "</button></td></tr>";
      }).join("") + "</table></div>" : '<div class="empty">No coupons.</div>') + '<p class="muted small" style="margin-top:12px">Each user can use a given coupon only once.</p>';
      $("#nc", el).onclick = function () { C.formModal("New coupon", [{ k: "code", label: "Code" }, { k: "percent", label: "Discount %", type: "number", def: 10 }, { k: "max_uses", label: "Maximum number of uses", type: "number", def: 1 }], {}, function (v) { return P("/api/admin/coupon", v).then(function () { ok(); reload(); }); }); };
      el.onclick = function (e) { var b = e.target.closest("[data-id]"); if (b) P("/api/admin/coupon", { id: +b.dataset.id, code: b.dataset.c, percent: +b.dataset.p, active: +b.dataset.on }).then(function () { ok(); reload(); }); };
    });
  };

  /* ---------- settings ---------- */
  views.settings = function (el) {
    return C.api("GET", "/api/admin/settings").then(function (r) {
      var s = r.settings;
      var F = [
        { k: "store_name", label: "Store name" },
        { k: "methods_enabled", label: "Enabled payment methods", help: "Comma-separated: upi,binance_id,usdt_bep20" },
        { k: "upi_id", label: "UPI ID (where users pay)" }, { k: "upi_name", label: "UPI account name" },
        { k: "usd_inr_rate", label: "USD → INR rate", help: "Used to calculate the INR amount for UPI deposits" },
        { k: "upi_auto", label: "UPI auto-verify via email", help: "1 = on, 0 = off. Requires IMAP_HOST, IMAP_USER and IMAP_PASS on the server" },
        { k: "upi_alert_senders", label: "Bank alert sender(s)", help: "Comma-separated, e.g. alerts@yourbank.com or @yourbank.com. Only emails from these senders are trusted" },
        { k: "upi_require_dkim", label: "Require sender DKIM check", help: "1 = accept only emails that pass DKIM (recommended)" },
        { k: "binance_id", label: "Binance ID (Pay ID)" },
        { k: "binance_auto", label: "Binance auto-verify via API", help: "1 = on. Requires BINANCE_API_KEY and BINANCE_API_SECRET (read-only) on the server" },
        { k: "usdt_address", label: "USDT BEP20 wallet address (0x…)", help: "Public address only. Never enter a private key here." },
        { k: "usdt_contract", label: "USDT token contract (BSC)", help: "Defaults to BSC-USD (USDT). Do not change it unless you know why." },
        { k: "bsc_rpc", label: "BSC RPC URL (https://)" }, { k: "confirmations", label: "Required confirmations", type: "number" },
        { k: "min_deposit", label: "Minimum deposit (USD)" }, { k: "max_deposit", label: "Maximum deposit (USD)" },
        { k: "referral_reward", label: "Referral reward (USD)" },
        { k: "support_text", label: "Support text (shown on the Support page)", type: "textarea", rows: 3 }, { k: "support_url", label: "Support link (https://… optional)" },
        { k: "site_url", label: "Site URL (used in password-reset emails)", help: "For example https://yourdomain.com. Emails are sent only when SMTP is configured on the server." }];
      el.innerHTML = '<div class="card"><div class="orow"><h3>Settings</h3><button class="btn btn-primary btn-sm" id="es">Edit</button></div><div class="tbl"><table>' + F.map(function (f) { return "<tr><td>" + esc(f.label) + '</td><td class="mono wrapc">' + (esc(s[f.k]) || '<span class="muted">—</span>') + "</td></tr>"; }).join("") + "</table></div></div>";
      $("#es", el).onclick = function () { C.formModal("Settings", F, s, function (v) { return P("/api/admin/settings", v).then(function () { ok(); reload(); }); }); };
    });
  };

  C.me().then(function (u) {
    if (!u) { location.href = "account.html?next=admin.html"; return; }
    if (!u.is_admin) { root.innerHTML = '<div class="empty">This page is for administrators only.</div>'; return; }
    shell();
  });
})();
