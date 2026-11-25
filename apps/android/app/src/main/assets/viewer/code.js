/* The code page of the file preview (file-preview design §6.2, last paragraph). It runs with no network and no bridge
   to the app: this file only draws the text handed to it by the app's own request to /text. */
(function () {
  "use strict";
  var params = new URLSearchParams(location.search);
  var codeEl = document.getElementById("code");
  var pre = document.getElementById("pre");
  var scroller = document.getElementById("scroller");
  var gutter = document.getElementById("gutter");
  var mark = document.getElementById("mark");
  var banner = document.getElementById("banner");
  var style = document.getElementById("style");
  var dark = params.get("dark") === "1";
  if (dark) { document.body.className += " dark"; style.href = "/code-dark.css"; }

  var truncated = params.get("truncated") === "1";
  var shownBytes = parseInt(params.get("size") || "0", 10);
  var totalBytes = parseInt(params.get("total") || "0", 10);
  function mb(n) { return (n / 1048576).toFixed(1); }
  if (truncated) {
    banner.className = "show";
    banner.textContent = "只显示了开头 " + mb(shownBytes) + " MB，共 " + mb(totalBytes) + " MB，可以保存后看全文";
  }

  var lang = params.get("lang") || "";
  var targetLine = parseInt(params.get("line") || "0", 10);
  var text = "";
  var highlighted = false;

  function draw() {
    codeEl.textContent = text;
    var limit = 200 * 1024;
    if (lang && lang !== "text" && window.hljs && text.length <= limit) {
      try {
        var language = lang;
        if (!hljs.getLanguage(language)) language = "";
        codeEl.innerHTML = language
          ? hljs.highlight(text, { language: language, ignoreIllegals: true }).value
          : hljs.highlightAuto(text).value;
        codeEl.className = "hljs";
        highlighted = true;
      } catch (e) { codeEl.textContent = text; }
    }
    var lines = text.length ? text.split("\n").length : 0;
    var numbers = [];
    for (var i = 1; i <= lines; i++) numbers.push(i);
    gutter.textContent = numbers.join("\n");
    document.body.className = dark ? "dark" : "";
    if (targetLine > 0) jumpTo(targetLine);
  }

  function lineTop(line) {
    var node = codeEl.firstChild;
    var seen = 1;
    while (node) {
      var value = node.nodeType === 3 ? node.nodeValue : node.textContent;
      var count = (value.match(/\n/g) || []).length;
      if (seen + count >= line) {
        var offset = 0;
        if (node.nodeType === 3) {
          var before = value.slice(0, line - seen);
          offset = before.length;
        }
        var range = document.createRange();
        try {
          if (node.nodeType === 3) range.setStart(node, Math.max(0, offset));
          else range.setStart(node, 0);
          range.collapse(true);
          var rect = range.getBoundingClientRect();
          if (rect.height === 0) return (line - 1) * 18;
          return rect.top - pre.getBoundingClientRect().top + pre.offsetTop;
        } catch (e) { return (line - 1) * 18; }
      }
      seen += count;
      node = node.nextSibling;
    }
    return (line - 1) * 18;
  }

  function jumpTo(line) {
    var top = lineTop(line);
    var height = 18;
    mark.style.display = "block";
    mark.style.top = (top + 10) + "px";
    mark.style.height = height + "px";
    scroller.scrollTop = Math.max(0, top - window.innerHeight / 3);
  }

  var findPos = 0;
  function find(backwards) {
    var query = document.getElementById("find").value;
    if (!query) return;
    var at;
    if (backwards) at = text.lastIndexOf(query, Math.max(0, findPos - 1));
    else at = text.indexOf(query, findPos);
    if (at < 0) at = backwards ? text.lastIndexOf(query) : text.indexOf(query);
    if (at < 0) return;
    findPos = backwards ? at : at + query.length;
    var line = text.slice(0, at).split("\n").length;
    jumpTo(line);
  }

  function copyAll() {
    var area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); } catch (e) { }
    document.body.removeChild(area);
  }

  document.getElementById("wrap").addEventListener("click", function () {
    document.body.classList.toggle("wrap");
  });
  document.getElementById("next").addEventListener("click", function () { find(false); });
  document.getElementById("prev").addEventListener("click", function () { find(true); });
  document.getElementById("copy").addEventListener("click", copyAll);

  fetch("/text").then(function (r) { return r.text(); }).then(function (t) {
    text = t;
    draw();
  }).catch(function () {
    banner.className = "show";
    banner.textContent = "文件内容没有读到";
  });
})();
