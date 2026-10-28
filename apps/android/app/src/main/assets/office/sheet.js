// An Excel workbook drawn on the phone (OfficePreview, Android 1.0.5): SheetJS reads it, and each sheet Excel shows
// is a table here, one at a time, chosen from the row of names above. A sheet longer than 2,000 rows or wider than 100
// columns shows its first part and says so. The file comes from the app at ./file and nothing else is fetched. When
// it cannot be read, the page says so and its title tells the app, which asks the computer for its PDF instead.
(function () {
  var MAX_ROWS = 2000;
  var MAX_COLUMNS = 100;
  var note = document.getElementById("note");
  var tabs = document.getElementById("tabs");
  var grid = document.getElementById("grid");
  if (/[?&]dark=1/.test(location.search)) document.body.classList.add("dark");

  function failed() {
    note.textContent = "手机上显示不了这个文件。";
    note.hidden = false;
    tabs.hidden = true;
    grid.textContent = "";
    document.title = "teleply:failed";
  }

  function say(text) {
    note.textContent = text;
    note.hidden = !text;
  }

  function show(book, name, button) {
    tabs.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-selected", b === button ? "true" : "false"); });
    grid.textContent = "";
    var sheet = book.Sheets[name];
    if (!sheet || !sheet["!ref"]) {
      say("这个工作表是空的。");
      return;
    }
    var range = XLSX.utils.decode_range(sheet["!ref"]);
    var cut = false;
    if (range.e.r - range.s.r >= MAX_ROWS) { range.e.r = range.s.r + MAX_ROWS - 1; cut = true; }
    if (range.e.c - range.s.c >= MAX_COLUMNS) { range.e.c = range.s.c + MAX_COLUMNS - 1; cut = true; }
    var part = Object.assign({}, sheet, { "!ref": XLSX.utils.encode_range(range) });
    // SheetJS writes each cell's text escaped; a link in a cell may lead only to the web or to mail.
    grid.innerHTML = XLSX.utils.sheet_to_html(part, { header: "", footer: "", editable: false });
    grid.querySelectorAll("a[href]").forEach(function (a) {
      if (!/^(https?|mailto):/i.test(a.getAttribute("href"))) a.removeAttribute("href");
    });
    say(cut ? "只显示前 " + MAX_ROWS + " 行、" + MAX_COLUMNS + " 列；完整内容请用其他应用打开。" : "");
  }

  fetch("file")
    .then(function (answer) {
      if (!answer.ok) throw new Error("HTTP " + answer.status);
      return answer.arrayBuffer();
    })
    .then(function (data) {
      var book = XLSX.read(new Uint8Array(data), { type: "array", cellDates: true });
      var kept = (book.Workbook && book.Workbook.Sheets) || [];
      // The sheets Excel shows; all of them when every one is hidden.
      var names = book.SheetNames.filter(function (name, i) { return !(kept[i] && kept[i].Hidden); });
      if (!names.length) names = book.SheetNames.slice();
      if (!names.length) throw new Error("no sheets");
      var first = null;
      names.forEach(function (name) {
        var button = document.createElement("button");
        button.type = "button";
        button.setAttribute("role", "tab");
        button.textContent = name;
        button.addEventListener("click", function () { show(book, name, button); });
        tabs.appendChild(button);
        if (!first) first = button;
      });
      tabs.hidden = names.length < 2;
      show(book, names[0], first);
    })
    .catch(failed);
})();
