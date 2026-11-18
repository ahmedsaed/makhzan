// makhzan admin: the little the server-rendered pages need from a script.
// - [data-copy]: copy its text to the clipboard (crosswalk snippets, a token).
// - [data-arm]: a second click is the real one (revoking a worker's token);
//   the first relabels the button and sets the form's `confirmed` field.
// - [data-job]: a queued or running job; poll its row and reload when it ends.
// Everything works without it except copying: forms post as plain HTML.
(function () {
  "use strict";

  function toast(message) {
    var box = document.getElementById("toasts");
    if (!box) return;
    var t = document.createElement("div");
    t.className = "toast";
    t.textContent = message;
    box.appendChild(t);
    setTimeout(function () { t.remove(); }, 4200);
  }

  document.addEventListener("click", function (event) {
    var copy = event.target.closest("[data-copy]");
    if (copy) {
      event.preventDefault();
      var text = copy.getAttribute("data-copy");
      var said = copy.getAttribute("data-copied") || "Copied";
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(
          function () { toast(said); },
          function () { window.prompt("Copy this:", text); }
        );
      } else {
        // Plain HTTP over the tailnet is not a secure context: no clipboard API.
        window.prompt("Copy this (Ctrl+C):", text);
      }
      return;
    }
    var arm = event.target.closest("[data-arm]");
    if (arm && !arm.dataset.armed) {
      event.preventDefault();
      arm.dataset.armed = "1";
      arm.textContent = arm.getAttribute("data-arm");
      arm.classList.add("primary");
      var field = arm.form && arm.form.querySelector("input[name=confirmed]");
      if (field) field.value = "yes";
    }
  });

  var jobs = Array.prototype.slice.call(document.querySelectorAll("[data-job]"));
  if (jobs.length) {
    var polls = 0;
    var poll = function () {
      Promise.all(
        jobs.map(function (el) {
          return fetch("/jobs/" + el.getAttribute("data-job") + ".json", {
            credentials: "same-origin",
          })
            .then(function (r) { return r.ok ? r.json() : null; })
            .catch(function () { return null; });
        })
      ).then(function (states) {
        var ended = states.some(function (s) {
          return s && s.status !== "queued" && s.status !== "running";
        });
        polls += 1;
        // Done or failed: reload to show it. Still queued or running after 30
        // minutes, longer than a limit=200 run takes: stop asking (a lost job is
        // marked failed on the next page load).
        if (ended) window.location.reload();
        else if (polls < 720) setTimeout(poll, 2500);
      });
    };
    setTimeout(poll, 2500);
  }
})();
