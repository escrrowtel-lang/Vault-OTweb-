/* Account: login/register, orders, wallet top-up, referral */
(function () {
  var C = window.Core, $ = C.$, esc = C.esc, money = C.money;
  var root = $("#acc");
  var params = new URLSearchParams(location.search);
  if (params.get("ref")) { try { localStorage.setItem("ref", params.get("ref")); } catch (e) {} }

  function nextUrl() {
    var n = params.get("next") || "";
    return /^[a-z0-9\-]+\.html(\?[a-z0-9=&%_\-]*)?$/i.test(n) ? n : "";
  }

  /* ---------- auth ---------- */
  function authView() {
    var ref = ""; try { ref = localStorage.getItem("ref") || ""; } catch (e) {}
    root.innerHTML = '<div class="authbox card"><div class="tabs" id="at"><button class="tab on" data-m="login">Login</button><button class="tab" data-m="register">Sign up</button></div>' +
      '<form class="form" id="af"><label class="fld" id="nm" hidden><span>Naam (optional)</span><input name="name" autocomplete="name"></label>' +
      '<label class="fld"><span>Email</span><input name="email" type="email" required autocomplete="email"></label>' +
      '<label class="fld"><span>Password</span><input name="password" type="password" required minlength="8" autocomplete="current-password"><small class="muted" id="pwh" hidden>Kam se kam 8 characters</small></label>' +
      (ref ? '<small class="muted">Referral code laga hai: <b>' + esc(ref) + "</b></small>" : "") +
      '<button class="btn btn-primary" id="asub" type="submit">Login</button>' +
      '<button class="btn btn-ghost btn-sm" id="fp" type="button">Password bhool gaye?</button></form></div>';
    var mode = "login";
    if (location.hash === "#register") setMode("register");
    function setMode(m) {
      mode = m;
      document.querySelectorAll("#at .tab").forEach(function (t) { t.classList.toggle("on", t.dataset.m === m); });
      $("#nm").hidden = m !== "register"; $("#pwh").hidden = m !== "register";
      $("#asub").textContent = m === "register" ? "Account banao" : "Login";
      $("#af").elements.password.autocomplete = m === "register" ? "new-password" : "current-password";
    }
    $("#fp").onclick = function () {
      C.formModal("Password reset", [{ k: "email", label: "Apna email", type: "email" }], { email: $("#af").elements.email.value }, function (v) {
        return C.api("POST", "/api/auth/forgot", { email: v.email }).then(function () {
          C.toast("Agar email setup hai to reset link bhej diya gaya. Warna support/admin se reset link maango.");
        });
      });
    };
    $("#at").onclick = function (e) { var t = e.target.closest("[data-m]"); if (t) setMode(t.dataset.m); };
    $("#af").onsubmit = function (e) {
      e.preventDefault();
      var f = e.target.elements;
      C.busy($("#asub"), function () {
        var body = { email: f.email.value, password: f.password.value };
        if (mode === "register") { body.name = f.name.value; body.ref = ref; }
        return C.api("POST", "/api/auth/" + mode, body).then(function () { location.href = nextUrl() || "account.html"; });
      });
    };
  }

  /* ---------- dashboard ---------- */
  function dash(u) {
    root.innerHTML = '<div class="dhead"><div><h1 style="font-size:32px">Hi' + (u.name ? ", " + esc(u.name) : "") + '</h1><p class="muted">' + esc(u.email) + '</p></div>' +
      '<div class="balbox"><small>Wallet balance</small><b>' + money(u.balance) + '</b></div></div>' +
      '<div class="tabs" id="dt"><button class="tab" data-t="orders">Orders</button><button class="tab" data-t="wallet">Wallet &amp; top-up</button><button class="tab" data-t="referral">Referral</button>' +
      '<button class="tab" id="lo" style="margin-left:auto">Logout</button></div><div id="pane"></div>';
    $("#lo").onclick = function () { C.api("POST", "/api/auth/logout", {}).then(function () { location.href = "index.html"; }); };
    $("#dt").onclick = function (e) { var t = e.target.closest("[data-t]"); if (t) { location.hash = t.dataset.t; } };
    function show() {
      var t = (location.hash || "#orders").slice(1);
      if (["orders", "wallet", "referral"].indexOf(t) < 0) t = "orders";
      document.querySelectorAll("#dt [data-t]").forEach(function (b) { b.classList.toggle("on", b.dataset.t === t); });
      ({ orders: orders, wallet: wallet, referral: referral })[t]();
    }
    window.addEventListener("hashchange", show);
    show();
  }

  var ST = { pending: "b-pre", processing: "b-low", completed: "b-in", cancelled: "b-out", refunded: "b-out" };
  function dt(ts) { return new Date(ts * 1000).toLocaleString(); }

  function orders() {
    var pane = $("#pane"); pane.innerHTML = '<div class="skeleton"></div>';
    C.api("GET", "/api/orders").then(function (d) {
      if (!d.orders.length) { pane.innerHTML = '<div class="empty">Abhi koi order nahi. <a href="plans.html"><u>Plans dekho</u></a></div>'; return; }
      pane.innerHTML = '<div class="olist">' + d.orders.map(function (o) {
        var msg = o.status === "pending" ? "Pre-order: stock aate hi apne aap deliver hoga." : (o.status === "processing" ? "Admin team deliver karegi. Yahan details aa jayengi." : "");
        return '<div class="card order"><div class="orow"><div><b>' + esc(o.product_name) + "</b> · " + esc(o.plan_name) + " × " + o.qty +
          '<div class="muted small">Order #' + o.id + " · " + dt(o.created_at) + '</div></div><div class="oright"><span class="badge ' + (ST[o.status] || "b-out") + '">' + esc(o.status) + "</span><b>" + money(o.total) + "</b></div></div>" +
          (o.delivery_text ? '<pre class="deliv">' + esc(o.delivery_text) + '</pre><button class="btn btn-ghost btn-sm" data-cp="' + o.id + '">Copy</button>' : (msg ? '<div class="note">' + msg + "</div>" : "")) + "</div>";
      }).join("") + "</div>";
      pane.onclick = function (e) {
        var b = e.target.closest("[data-cp]"); if (!b) return;
        var o = d.orders.filter(function (x) { return String(x.id) === b.dataset.cp; })[0]; C.copy(o.delivery_text);
      };
    }).catch(function (e) { pane.innerHTML = '<div class="empty">' + esc(e.message) + "</div>"; });
  }

  function wallet() {
    var pane = $("#pane"); pane.innerHTML = '<div class="skeleton"></div>';
    Promise.all([C.api("GET", "/api/wallet"), C.api("GET", "/api/settings")]).then(function (r) {
      var w = r[0], s = r[1], rate = parseFloat(s.usd_inr_rate) || 100;
      var names = { upi: "UPI", binance_id: "Binance ID", usdt_bep20: "USDT (BEP20)" };
      var html = '<div class="card"><h3>Wallet top-up</h3><p class="muted small">Limit $' + esc(s.min_deposit) + " se $" + esc(s.max_deposit) + ". Khareedari wallet balance se hoti hai.</p>";
      if (!s.methods.length) html += '<div class="note">Top-up abhi band hai.</div>';
      else {
        html += '<div class="tabs" id="mt" style="margin:14px 0">' + s.methods.map(function (m, i) { return '<button class="tab' + (i ? "" : " on") + '" data-m="' + m + '">' + names[m] + "</button>"; }).join("") + '</div><div id="mpane"></div>';
      }
      html += "</div>";
      html += '<div class="card" style="margin-top:18px"><h3>Deposits</h3>' + (w.deposits.length ? '<div class="tbl"><table><tr><th>Date</th><th>Method</th><th>Amount</th><th>Reference</th><th>Status</th></tr>' + w.deposits.map(function (d) {
        return "<tr><td>" + dt(d.created_at) + "</td><td>" + esc(names[d.method] || d.method) + "</td><td>" + money(d.amount) + '</td><td class="mono">' + esc(d.reference.slice(0, 18)) + (d.reference.length > 18 ? "…" : "") + '</td><td><span class="badge ' + (d.status === "approved" ? "b-in" : d.status === "pending" ? "b-low" : "b-out") + '">' + d.status + "</span>" + (d.note ? "<br><small>" + esc(d.note) + "</small>" : "") + "</td></tr>";
      }).join("") + "</table></div>" : '<p class="muted">Abhi koi deposit nahi.</p>') + "</div>";
      html += '<div class="card" style="margin-top:18px"><h3>Wallet history</h3>' + (w.ledger.length ? '<div class="tbl"><table><tr><th>Date</th><th>Type</th><th>Amount</th><th>Balance</th></tr>' + w.ledger.map(function (l) {
        return "<tr><td>" + dt(l.created_at) + "</td><td>" + esc(l.reason) + '</td><td class="' + (l.delta < 0 ? "neg" : "pos") + '">' + (l.delta < 0 ? "−" : "+") + money(Math.abs(l.delta)) + "</td><td>" + money(l.balance_after) + "</td></tr>";
      }).join("") + "</table></div>" : '<p class="muted">Abhi kuch nahi.</p>') + "</div>";
      pane.innerHTML = html;
      if (s.methods.length) {
        var mp = $("#mpane");
        var go = function (m) { topup(mp, m, s, rate); };
        go(s.methods[0]);
        $("#mt").onclick = function (e) {
          var t = e.target.closest("[data-m]"); if (!t) return;
          document.querySelectorAll("#mt .tab").forEach(function (x) { x.classList.toggle("on", x === t); });
          go(t.dataset.m);
        };
      }
    }).catch(function (e) { pane.innerHTML = '<div class="empty">' + esc(e.message) + "</div>"; });
  }

  function topup(el, m, s, rate) {
    var done = function () { C.toast("Submit ho gaya"); C.me(true).then(function () { location.reload(); }); };
    if (m === "upi" || m === "binance_id") {
      var upi = m === "upi";
      var dest = upi ? s.upi_id : s.binance_id;
      if (!dest) { el.innerHTML = '<div class="note">Ye method abhi set nahi hai.</div>'; return; }
      el.innerHTML = '<ol class="steps"><li>Neeche amount (USD) daalo' + (upi ? " — INR amount dikhega" : "") + ".</li><li>" + (upi ? "Is UPI ID par pay karo" : "Is Binance ID par transfer karo") + ': <b class="mono">' + esc(dest) + "</b> " + (upi && s.upi_name ? "(" + esc(s.upi_name) + ")" : "") + ' <button class="btn btn-ghost btn-sm" id="cpd">Copy</button></li><li>' +
        (upi ? "Payment ka 12-digit <b>UTR</b>" : "Binance ka <b>Transaction / Order ID</b>") + " yahan daalo. " + ((upi ? s.upi_auto : s.binance_auto) ? "Payment verify hote hi wallet mein <b>apne aap</b> add ho jaayega (1-2 min lag sakte hain)." : "Admin verify karke wallet mein add karega.") + "</li></ol>" +
        '<form class="form" id="tf"><label class="fld"><span>Amount (USD)</span><input name="amount" type="number" step="0.01" min="' + esc(s.min_deposit) + '" max="' + esc(s.max_deposit) + '" required></label>' +
        (upi ? '<div class="note" id="inr">Pay karne ka amount: ₹—</div>' : "") +
        '<label class="fld"><span>' + (upi ? "UTR (12 digit)" : "Binance Transaction/Order ID") + '</span><input name="reference" required autocomplete="off"></label><button class="btn btn-primary" type="submit">Submit for verification</button></form>';
      $("#cpd", el).onclick = function () { C.copy(dest); };
      var f = $("#tf", el);
      if (upi) f.elements.amount.oninput = function () { $("#inr", el).textContent = "Pay karne ka amount: ₹" + ((parseFloat(f.elements.amount.value) || 0) * rate).toFixed(2); };
      f.onsubmit = function (e) {
        e.preventDefault();
        C.busy($("button", f), function () { return C.api("POST", "/api/deposits", { method: m, amount: f.elements.amount.value, reference: f.elements.reference.value.trim() }).then(done); });
      };
      return;
    }
    /* USDT BEP20 (automatic) */
    if (!s.usdt_address) { el.innerHTML = '<div class="note">Ye method abhi set nahi hai.</div>'; return; }
    el.innerHTML = '<ol class="steps"><li>Amount (USD) daalo aur <b>exact USDT amount</b> lo.</li><li>Sirf <b>BEP20 (BNB Smart Chain)</b> par, <b>exact utna hi USDT</b> neeche wale address par bhejo.</li><li>Transaction hash yahan daalo. Blockchain par confirm hote hi balance <b>turant</b> add ho jata hai.</li></ol>' +
      '<form class="form" id="i1"><label class="fld"><span>Amount (USD)</span><input name="amount" type="number" step="0.01" min="' + esc(s.min_deposit) + '" max="' + esc(s.max_deposit) + '" required></label><button class="btn btn-ghost" type="submit">Exact amount lo</button></form>' +
      '<div id="i2" hidden class="card inner"><p>Ye <b>exact</b> amount bhejo (2 ghante tak valid):</p><div class="big mono" id="ex"></div><p>Address (BEP20):</p><div class="mono addr" id="ad">' + esc(s.usdt_address) + '</div><button class="btn btn-ghost btn-sm" id="cpa">Copy address</button>' +
      '<form class="form" id="i3" style="margin-top:14px"><label class="fld"><span>Transaction hash</span><input name="reference" placeholder="0x…" required autocomplete="off"></label><button class="btn btn-primary" type="submit">Verify &amp; add balance</button></form>' +
      '<small class="muted">Galat amount ya galat network par bheja to paisa auto add nahi hoga; support se baat karo.</small></div>';
    $("#i1", el).onsubmit = function (e) {
      e.preventDefault();
      C.busy($("#i1 button", el), function () {
        return C.api("POST", "/api/deposits/crypto-intent", { amount: e.target.elements.amount.value }).then(function (d) {
          $("#ex", el).textContent = d.expected + " USDT"; $("#i2", el).hidden = false;
        });
      });
    };
    $("#cpa", el).onclick = function () { C.copy(s.usdt_address); };
    $("#i3", el).onsubmit = function (e) {
      e.preventDefault();
      C.busy($("#i3 button", el), function () { return C.api("POST", "/api/deposits", { method: "usdt_bep20", reference: e.target.elements.reference.value.trim() }).then(done); });
    };
  }

  function referral() {
    var pane = $("#pane"); pane.innerHTML = '<div class="skeleton"></div>';
    C.api("GET", "/api/referral").then(function (d) {
      var link = location.origin + "/account.html?ref=" + d.code + "#register";
      pane.innerHTML = '<div class="card"><h3>Dost ko bulao, reward pao</h3><p class="muted">Aapka link se aaya naya user jab apna <b>pehla deposit</b> karta hai, aapko <b>$' + esc(d.reward) + "</b> wallet mein milta hai.</p>" +
        '<div class="addr mono" id="rl">' + esc(link) + '</div><button class="btn btn-primary btn-sm" id="cr" style="margin-top:10px">Copy link</button>' +
        '<div class="stats3"><div><b>' + d.invited + "</b><small>Invited</small></div><div><b>" + d.rewarded + "</b><small>Rewarded</small></div><div><b>" + money(d.earned) + "</b><small>Earned</small></div></div></div>";
      $("#cr").onclick = function () { C.copy(link); };
    }).catch(function (e) { pane.innerHTML = '<div class="empty">' + esc(e.message) + "</div>"; });
  }

  C.me().then(function (u) { if (u) dash(u); else authView(); });
})();
