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
      '<form class="form" id="af"><label class="fld" id="nm" hidden><span>Name (optional)</span><input name="name" autocomplete="name"></label>' +
      '<label class="fld"><span>Email</span><input name="email" type="email" required autocomplete="email"></label>' +
      '<label class="fld"><span>Password</span><input name="password" type="password" required minlength="8" autocomplete="current-password"><small class="muted" id="pwh" hidden>At least 8 characters</small></label>' +
      (ref ? '<small class="muted">Referral code applied: <b>' + esc(ref) + "</b></small>" : "") +
      '<button class="btn btn-primary" id="asub" type="submit">Login</button>' +
      '<button class="btn btn-ghost btn-sm" id="fp" type="button">Forgot your password?</button></form></div>';
    var mode = "login";
    if (location.hash === "#register") setMode("register");
    function setMode(m) {
      mode = m;
      document.querySelectorAll("#at .tab").forEach(function (t) { t.classList.toggle("on", t.dataset.m === m); });
      $("#nm").hidden = m !== "register"; $("#pwh").hidden = m !== "register";
      $("#asub").textContent = m === "register" ? "Create account" : "Login";
      $("#af").elements.password.autocomplete = m === "register" ? "new-password" : "current-password";
    }
    $("#fp").onclick = function () {
      C.formModal("Password reset", [{ k: "email", label: "Your email", type: "email" }], { email: $("#af").elements.email.value }, function (v) {
        return C.api("POST", "/api/auth/forgot", { email: v.email }).then(function () {
          C.toast("If email is configured, a reset link has been sent. Otherwise, ask support for a reset link.");
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
      if (!d.orders.length) { pane.innerHTML = '<div class="empty">You have no orders yet. <a href="plans.html"><u>Browse plans</u></a></div>'; return; }
      pane.innerHTML = '<div class="olist">' + d.orders.map(function (o) {
        var msg = o.status === "pending" ? "Pre-order: it will be delivered automatically when stock arrives." : (o.status === "processing" ? "Our team will deliver this order. The details will appear here." : "");
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
      var html = '<div class="card"><h3>Wallet top-up</h3><p class="muted small">Limit: $' + esc(s.min_deposit) + " to $" + esc(s.max_deposit) + ". Purchases are paid from your wallet balance.</p>";
      if (!s.methods.length) html += '<div class="note">Top-ups are currently unavailable.</div>';
      else {
        html += '<div class="tabs" id="mt" style="margin:14px 0">' + s.methods.map(function (m, i) { return '<button class="tab' + (i ? "" : " on") + '" data-m="' + m + '">' + names[m] + "</button>"; }).join("") + '</div><div id="mpane"></div>';
      }
      html += "</div>";
      html += '<div class="card" style="margin-top:18px"><h3>Deposits</h3>' + (w.deposits.length ? '<div class="tbl"><table><tr><th>Date</th><th>Method</th><th>Amount</th><th>Reference</th><th>Status</th></tr>' + w.deposits.map(function (d) {
        return "<tr><td>" + dt(d.created_at) + "</td><td>" + esc(names[d.method] || d.method) + "</td><td>" + money(d.amount) + '</td><td class="mono">' + esc(d.reference.slice(0, 18)) + (d.reference.length > 18 ? "…" : "") + '</td><td><span class="badge ' + (d.status === "approved" ? "b-in" : d.status === "pending" ? "b-low" : "b-out") + '">' + d.status + "</span>" + (d.note ? "<br><small>" + esc(d.note) + "</small>" : "") + "</td></tr>";
      }).join("") + "</table></div>" : '<p class="muted">No deposits yet.</p>') + "</div>";
      html += '<div class="card" style="margin-top:18px"><h3>Wallet history</h3>' + (w.ledger.length ? '<div class="tbl"><table><tr><th>Date</th><th>Type</th><th>Amount</th><th>Balance</th></tr>' + w.ledger.map(function (l) {
        return "<tr><td>" + dt(l.created_at) + "</td><td>" + esc(l.reason) + '</td><td class="' + (l.delta < 0 ? "neg" : "pos") + '">' + (l.delta < 0 ? "−" : "+") + money(Math.abs(l.delta)) + "</td><td>" + money(l.balance_after) + "</td></tr>";
      }).join("") + "</table></div>" : '<p class="muted">Nothing here yet.</p>') + "</div>";
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
    var done = function () { C.toast("Submitted"); C.me(true).then(function () { location.reload(); }); };
    if (m === "upi" || m === "binance_id") {
      var upi = m === "upi";
      var dest = upi ? s.upi_id : s.binance_id;
      if (!dest) { el.innerHTML = '<div class="note">This method is not available right now.</div>'; return; }
      el.innerHTML = '<ol class="steps"><li>Enter the amount (USD) below' + (upi ? " — the INR amount is shown" : "") + ".</li><li>" + (upi ? "Pay to this UPI ID" : "Transfer to this Binance ID") + ': <b class="mono">' + esc(dest) + "</b> " + (upi && s.upi_name ? "(" + esc(s.upi_name) + ")" : "") + ' <button class="btn btn-ghost btn-sm" id="cpd">Copy</button></li><li>' +
        (upi ? "Enter the 12-digit <b>UTR</b> of your payment" : "Enter the Binance <b>Transaction / Order ID</b>") + " here. " + ((upi ? s.upi_auto : s.binance_auto) ? "Your wallet is credited <b>automatically</b> once the payment is verified (usually within 1–2 minutes)." : "An admin will verify it and credit your wallet.") + "</li></ol>" +
        '<form class="form" id="tf"><label class="fld"><span>Amount (USD)</span><input name="amount" type="number" step="0.01" min="' + esc(s.min_deposit) + '" max="' + esc(s.max_deposit) + '" required></label>' +
        (upi ? '<div class="note" id="inr">Amount to pay: ₹—</div>' : "") +
        '<label class="fld"><span>' + (upi ? "UTR (12 digit)" : "Binance Transaction/Order ID") + '</span><input name="reference" required autocomplete="off"></label><button class="btn btn-primary" type="submit">Submit for verification</button></form>';
      $("#cpd", el).onclick = function () { C.copy(dest); };
      var f = $("#tf", el);
      if (upi) f.elements.amount.oninput = function () { $("#inr", el).textContent = "Amount to pay: ₹" + ((parseFloat(f.elements.amount.value) || 0) * rate).toFixed(2); };
      f.onsubmit = function (e) {
        e.preventDefault();
        C.busy($("button", f), function () { return C.api("POST", "/api/deposits", { method: m, amount: f.elements.amount.value, reference: f.elements.reference.value.trim() }).then(done); });
      };
      return;
    }
    /* USDT BEP20 (automatic) */
    if (!s.usdt_address) { el.innerHTML = '<div class="note">This method is not available right now.</div>'; return; }
    el.innerHTML = '<ol class="steps"><li>Enter the amount (USD) to get your <b>exact USDT amount</b>.</li><li>Send <b>exactly that amount</b> of USDT to the address below, on the <b>BEP20 (BNB Smart Chain)</b> network only.</li><li>Paste the transaction hash here. Your balance is credited <b>instantly</b> once the transaction is confirmed on the blockchain.</li></ol>' +
      '<form class="form" id="i1"><label class="fld"><span>Amount (USD)</span><input name="amount" type="number" step="0.01" min="' + esc(s.min_deposit) + '" max="' + esc(s.max_deposit) + '" required></label><button class="btn btn-ghost" type="submit">Exact amount lo</button></form>' +
      '<div id="i2" hidden class="card inner"><p>Send this <b>exact</b> amount (valid for 2 hours):</p><div class="big mono" id="ex"></div><p>Address (BEP20):</p><div class="mono addr" id="ad">' + esc(s.usdt_address) + '</div><button class="btn btn-ghost btn-sm" id="cpa">Copy address</button>' +
      '<form class="form" id="i3" style="margin-top:14px"><label class="fld"><span>Transaction hash</span><input name="reference" placeholder="0x…" required autocomplete="off"></label><button class="btn btn-primary" type="submit">Verify &amp; add balance</button></form>' +
      '<small class="muted">If you send a different amount or use the wrong network, the payment will not be credited automatically. Please contact support.</small></div>';
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
      pane.innerHTML = '<div class="card"><h3>Invite friends, earn rewards</h3><p class="muted">When someone who signed up with your link makes their <b>first deposit</b>, you receive <b>$' + esc(d.reward) + "</b> in your wallet.</p>" +
        '<div class="addr mono" id="rl">' + esc(link) + '</div><button class="btn btn-primary btn-sm" id="cr" style="margin-top:10px">Copy link</button>' +
        '<div class="stats3"><div><b>' + d.invited + "</b><small>Invited</small></div><div><b>" + d.rewarded + "</b><small>Rewarded</small></div><div><b>" + money(d.earned) + "</b><small>Earned</small></div></div></div>";
      $("#cr").onclick = function () { C.copy(link); };
    }).catch(function (e) { pane.innerHTML = '<div class="empty">' + esc(e.message) + "</div>"; });
  }

  C.me().then(function (u) { if (u) dash(u); else authView(); });
})();
