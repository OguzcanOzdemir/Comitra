// Detects the visitor's OS, highlights the matching download and fills the
// download buttons with direct links to the latest GitHub release assets.
// Without JavaScript (or if the API is unreachable) every button still
// points to the latest release page, so nothing breaks.
(function () {
  "use strict";
  var REPO = "OguzcanOzdemir/Comitra";
  var LATEST = "https://github.com/" + REPO + "/releases/latest";

  function detectOS() {
    var ua = navigator.userAgent || "";
    var p = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    if (/win/i.test(p) || /Windows/i.test(ua)) return "windows";
    if (/mac/i.test(p) || /Mac OS X/i.test(ua)) return /iPhone|iPad/.test(ua) ? null : "macos";
    if (/linux/i.test(p) || /Linux|X11/i.test(ua)) return /Android/i.test(ua) ? null : "linux";
    return null;
  }

  var PATTERNS = {
    "windows-setup": /windows-x64-setup\.exe$/i,
    "windows-portable": /windows-x64-portable\.zip$/i,
    "macos-arm64": /macos-arm64\.dmg$/i,
    "macos-x64": /macos-x64\.dmg$/i,
    "macos-portable": /macos-arm64-portable\.zip$/i,
    "linux-appimage": /linux-x86_64\.AppImage$/i,
    "linux-portable": /linux-x86_64-portable\.tar\.gz$/i
  };

  function fmtSize(bytes) {
    return bytes ? (bytes / 1048576).toFixed(0) + " MB" : "";
  }

  var os = detectOS();
  var hero = document.getElementById("hero-download");
  var labels = { windows: "Download for Windows", macos: "Download for macOS", linux: "Download for Linux" };
  if (os) {
    var card = document.getElementById("dl-" + os);
    if (card) card.classList.add("recommended");
    if (hero) hero.querySelector("span").textContent = labels[os];
  }

  if (!window.fetch) return;
  fetch("https://api.github.com/repos/" + REPO + "/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (rel) {
      var assets = rel.assets || [];
      var found = {};
      Object.keys(PATTERNS).forEach(function (key) {
        for (var i = 0; i < assets.length; i++) {
          if (PATTERNS[key].test(assets[i].name)) { found[key] = assets[i]; break; }
        }
      });
      document.querySelectorAll("[data-asset]").forEach(function (a) {
        var asset = found[a.getAttribute("data-asset")];
        if (asset) {
          a.href = asset.browser_download_url;
          var s = a.querySelector("small");
          if (s) s.textContent = fmtSize(asset.size);
        } else if (a.getAttribute("data-asset") === "macos-x64") {
          a.style.display = "none";
        }
      });
      if (hero && os) {
        var heroKey = { windows: "windows-setup", macos: "macos-arm64", linux: "linux-appimage" }[os];
        if (found[heroKey]) hero.href = found[heroKey].browser_download_url;
      }
      var info = document.getElementById("release-info");
      if (info && rel.tag_name) {
        var date = rel.published_at ? new Date(rel.published_at).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" }) : "";
        info.textContent = info.getAttribute("data-template").replace("{v}", rel.tag_name).replace("{d}", date);
      }
    })
    .catch(function () { /* keep links to the release page */ });

  document.querySelectorAll('a[href="#latest"]').forEach(function (a) { a.href = LATEST; });
})();
