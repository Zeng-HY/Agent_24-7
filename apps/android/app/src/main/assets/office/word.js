// A Word file drawn on the phone (OfficePreview, Android 1.0.5): docx-preview turns it into pages of HTML, as wide as
// the screen; a pinch makes them larger. The file comes from the app at ./file and nothing else is fetched. When it
// cannot be drawn, the page says so and its title tells the app, which asks the computer for its PDF instead.
(function () {
  var note = document.getElementById("note");
  var doc = document.getElementById("doc");
  if (/[?&]dark=1/.test(location.search)) document.body.classList.add("dark");

  function failed() {
    note.textContent = "手机上显示不了这个文件。";
    note.hidden = false;
    doc.textContent = "";
    document.title = "teleply:failed";
  }

  // The widest page fills the 980 CSS px the web view lays this page out at, which it shrinks to the screen (as the
  // open-source Gander's fitPageWidth does); the other pages keep their size beside it. Measured at zoom 1, because
  // whether a zoomed page's box includes the zoom depends on the Chromium version.
  function fit() {
    var wrapper = doc.querySelector(".docx-wrapper");
    var pages = wrapper ? wrapper.querySelectorAll("section.docx") : [];
    if (!pages.length) return;
    wrapper.style.setProperty("--page-zoom", "1");
    var style = getComputedStyle(wrapper);
    var room = wrapper.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0);
    var widest = 0;
    pages.forEach(function (page) { widest = Math.max(widest, page.getBoundingClientRect().width); });
    if (room > 0 && widest > 0) wrapper.style.setProperty("--page-zoom", String(room / widest));
  }

  fetch("file")
    .then(function (answer) {
      if (!answer.ok) throw new Error("HTTP " + answer.status);
      return answer.arrayBuffer();
    })
    .then(function (data) {
      // Parts that are HTML of their own (altChunks) and comments are left out: the page shows what Word prints.
      return docx.renderAsync(data, doc, null, {
        className: "docx", inWrapper: true, breakPages: true, ignoreLastRenderedPageBreak: true,
        renderHeaders: true, renderFooters: true, renderFootnotes: true, renderEndnotes: true,
        renderComments: false, renderChanges: false, renderAltChunks: false, useBase64URL: false
      });
    })
    .then(function () {
      note.hidden = true;
      fit();
      window.addEventListener("resize", fit);
    })
    .catch(failed);
})();
