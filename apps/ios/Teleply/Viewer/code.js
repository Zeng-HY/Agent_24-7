/* The code page of the file preview (file-preview design §6.2, last paragraph). It runs with no network and no bridge
   to the app: this file only draws the text handed to it by the app's own request to /text. It is plain DOM and works
   the same in the app's WebView and in a browser. */
(function () {
  "use strict";
  var params = new URLSearchParams(location.search);
  var codeEl = document.getElementById("code");
  var banner = document.getElementById("banner");
  var style = document.getElementById("style");
  var dark = params.get("dark") === "1";
  if (dark) { document.documentElement.classList.add("dark"); document.body.classList.add("dark"); style.href = "/code-dark.css"; }

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
  var lines = [];
  var lineEls = [];
  var jumped = false;

  function escapeHtml(value) {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* highlight.js can leave a span open across a newline (a multi-line string or comment). Each line is closed at its
     end and the same spans are opened again at the start of the next line, so every row holds whole HTML. */
  function splitHighlighted(html) {
    var out = [];
    var current = "";
    var stack = [];
    var token = /<[^>]+>|[^<]+/g;
    var match;
    function closeOpen() { for (var i = stack.length - 1; i >= 0; i--) current += "</" + stack[i].name + ">"; }
    function openOpen() { for (var i = 0; i < stack.length; i++) current += stack[i].open; }
    while ((match = token.exec(html)) !== null) {
      var part = match[0];
      if (part.charAt(0) === "<") {
        if (part.charAt(1) === "/") {
          var closing = part.slice(2).replace(/[^a-zA-Z0-9].*$/, "").toLowerCase();
          for (var i = stack.length - 1; i >= 0; i--) {
            if (stack[i].name.toLowerCase() === closing) { stack.splice(i, 1); break; }
          }
          current += part;
        } else if (/^<[a-zA-Z]/.test(part) && !/\/>$/.test(part)) {
          var name = part.slice(1).replace(/[^a-zA-Z0-9].*$/, "");
          stack.push({ name: name, open: part });
          current += part;
        } else {
          current += part;
        }
      } else {
        var chunks = part.split("\n");
        for (var c = 0; c < chunks.length; c++) {
          if (c > 0) { closeOpen(); out.push(current); current = ""; openOpen(); }
          current += chunks[c];
        }
      }
    }
    closeOpen();
    out.push(current);
    return out;
  }

  function render() {
    codeEl.textContent = "";
    lineEls = [];
    var limit = 200 * 1024;
    var highlighted = false;
    if (lang && lang !== "text" && window.hljs && text.length <= limit) {
      try {
        var language = hljs.getLanguage(lang) ? lang : "";
        var html = language ? hljs.highlight(text, { language: language, ignoreIllegals: true }).value : hljs.highlightAuto(text).value;
        lines = splitHighlighted(html);
        highlighted = true;
      } catch (e) { lines = text.split("\n").map(escapeHtml); }
    } else {
      lines = text.split("\n").map(escapeHtml);
    }
    for (var i = 0; i < lines.length; i++) {
      var row = document.createElement("div");
      row.className = "line";
      var number = document.createElement("span");
      number.className = "ln";
      number.setAttribute("aria-hidden", "true");
      number.textContent = String(i + 1);
      var content = document.createElement("span");
      content.className = "lc" + (highlighted ? " hljs" : "");
      // The plain text was escaped above; highlight.js output is already escaped HTML.
      content.innerHTML = highlighted ? (lines[i] || "&nbsp;") : (lines[i] || "&nbsp;");
      row.appendChild(number);
      row.appendChild(content);
      codeEl.appendChild(row);
      lineEls.push(row);
    }
  }

  function jumpTo(line) {
    if (!(line > 0) || !lineEls.length) return;
    var index = Math.max(0, Math.min(lineEls.length - 1, line - 1));
    for (var i = 0; i < lineEls.length; i++) lineEls[i].classList.remove("target");
    var row = lineEls[index];
    row.classList.add("target");
    row.scrollIntoView({ block: "center", behavior: "auto" });
    jumped = true;
  }

  /* If the WebView first measured a 0-height viewport, the page still lays out in normal flow; once it has a height,
     the line the answer named is scrolled to once. */
  function jumpWhenVisible() {
    if (jumped || targetLine <= 0) return;
    if (document.documentElement.clientHeight > 0) jumpTo(targetLine);
  }
  window.addEventListener("resize", jumpWhenVisible);
  if (window.ResizeObserver) new ResizeObserver(jumpWhenVisible).observe(document.body);

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

  document.getElementById("wrap").addEventListener("click", function (event) {
    document.body.classList.toggle("wrap");
    event.currentTarget.textContent = document.body.classList.contains("wrap") ? "不换行" : "自动换行";
  });
  document.getElementById("next").addEventListener("click", function () { find(false); });
  document.getElementById("prev").addEventListener("click", function () { find(true); });
  document.getElementById("copy").addEventListener("click", copyAll);

  fetch("/text").then(function (response) { return response.text(); }).then(function (value) {
    text = value;
    render();
    jumpWhenVisible();
  }).catch(function () {
    banner.className = "show";
    banner.textContent = "文件内容没有读到";
  });
})();
