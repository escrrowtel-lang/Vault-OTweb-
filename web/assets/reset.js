(function () {
  var C = window.Core;
  var token = new URLSearchParams(location.search).get("token") || "";
  document.getElementById("rf").onsubmit = function (e) {
    e.preventDefault();
    var pw = e.target.elements.password.value;
    C.busy(document.getElementById("rsub"), function () {
      return C.api("POST", "/api/auth/reset", { token: token, password: pw }).then(function () {
        C.toast("Password badal gaya. Ab login karo.");
        setTimeout(function () { location.href = "account.html"; }, 1200);
      });
    });
  };
})();
