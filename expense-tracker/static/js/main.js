// main.js — small progressive enhancements for Spendwise.
// The app works fully without JavaScript; this just adds nice-to-haves.

(function () {
    "use strict";

    // 1) Confirm before submitting any form that carries a data-confirm message.
    //    Used by the "Delete" buttons so an accidental click can't wipe data.
    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (form.matches("[data-confirm]")) {
            if (!window.confirm(form.getAttribute("data-confirm"))) {
                event.preventDefault();
            }
        }
    });

    // 2) Stop the mouse wheel / trackpad from changing a focused number input.
    //    Otherwise scrolling the page while the cursor sits in the amount box
    //    silently nudges the value by its step (e.g. 45000 -> 44999.95).
    document.querySelectorAll('input[type="number"]').forEach(function (input) {
        input.addEventListener("wheel", function (event) {
            if (document.activeElement === input) {
                event.preventDefault();
            }
        }, { passive: false });
    });

    // 3) Auto-dismiss flash messages after a few seconds.
    var flashes = document.querySelectorAll(".flash");
    flashes.forEach(function (el) {
        setTimeout(function () {
            el.style.transition = "opacity 0.4s ease";
            el.style.opacity = "0";
            setTimeout(function () { el.remove(); }, 400);
        }, 4000);
    });
})();
