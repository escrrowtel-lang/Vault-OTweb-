/* Applies the saved colour theme before first paint (light by default, or the OS preference). */
(function () {
  var t = null;
  try { t = localStorage.getItem("vs_theme"); } catch (e) {}
  if (!t && window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches) t = "dark";
  if (t === "dark") document.documentElement.setAttribute("data-theme", "dark");
})();
