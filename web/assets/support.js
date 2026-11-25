Core.api("GET", "/api/settings").then(function (s) {
  if (s.support_text) document.getElementById("stext").textContent = s.support_text;
  var u = (s.support_url || "").trim();
  if (/^(https?:\/\/|mailto:|tel:)/i.test(u)) {
    var a = document.createElement("a");
    a.className = "btn btn-grad"; a.textContent = "Support se baat karo"; a.href = u; a.rel = "noopener";
    if (/^https?:/i.test(u)) a.target = "_blank";
    document.getElementById("sbtn").appendChild(a);
  }
}).catch(function () {});
