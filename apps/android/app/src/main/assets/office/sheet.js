// An Excel workbook drawn on the phone (OfficePreview, Android 1.0.5): SheetJS reads it, and each sheet Excel shows
// is a table here, one at a time, chosen from the row of names above. A sheet longer than 2,000 rows or wider than 100
// columns shows its first part and says so. The file comes from the app at ./file and nothing else is fetched. When
// it cannot be read, the page says so and its title tells the app, which asks the computer for its PDF instead.
//
// A CSV or TSV (11-16) comes the same way, but as UTF-8 text the phone read from the file (the computer's text preview
// cannot read GBK). The page is told which separator to use; raw keeps 01 as 01, and the first row becomes the table's
// header, which stays at the top while the rows below scroll.
(function () {
  var MAX_ROWS = 2000;
  var MAX_COLUMNS = 100;
  var textKind = (/[?&]sheet=(csv|tsv)\b/.exec(location.search) || [])[1] || null;
  var note = document.getElementById("note");
  var tabs = document.getElementById("tabs");
  var grid = document.getElementById("grid");
  if (textKind) document.body.classList.add("csv", textKind);
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

  // The first row of a CSV or TSV is its header: a th, in a thead, so it can stay at the top as the rows scroll.
  function makeHeader() {
    var table = grid.querySelector("table");
    var row = table && table.querySelector("tr");
    if (!row) return;
    var head = document.createElement("thead");
    table.insertBefore(head, row.parentNode);
    head.appendChild(row);
    Array.prototype.slice.call(row.children).forEach(function (cell) {
      var th = document.createElement("th");
      th.setAttribute("scope", "col");
      while (cell.firstChild) th.appendChild(cell.firstChild);
      row.replaceChild(th, cell);
    });
  }

  // A long cell gets a box of its own, at most about 19 characters wide, so it wraps instead of stretching its column.
  // Short cells are left alone and keep their width.
  function capLongCells() {
    var cells = grid.querySelectorAll("td, th");
    for (var i = 0; i < cells.length; i++) {
      var cell = cells[i];
      if (!cell.textContent) continue;
      if (cell.textContent.length <= 20 && !cell.querySelector("br")) continue;
      var box = document.createElement("div");
      box.className = "cell";
      while (cell.firstChild) box.appendChild(cell.firstChild);
      cell.appendChild(box);
    }
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
    if (textKind) { makeHeader(); capLongCells(); }
    say(cut ? "只显示前 " + MAX_ROWS + " 行、" + MAX_COLUMNS + " 列；完整内容请用其他应用打开。" : "");
  }

  fetch("file")
    .then(function (answer) {
      if (!answer.ok) throw new Error("HTTP " + answer.status);
      return answer.arrayBuffer();
    })
    .then(function (data) {
      if (textKind) {
        var text = new TextDecoder("utf-8").decode(new Uint8Array(data));
        // raw: true keeps 01 as 01 and a date-looking text as text; FS is the column separator.
        return XLSX.read(text, { type: "string", raw: true, FS: textKind === "tsv" ? "\t" : "," });
      }
      return XLSX.read(new Uint8Array(data), { type: "array", cellDates: true });
    })
    .then(function (book) {
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
